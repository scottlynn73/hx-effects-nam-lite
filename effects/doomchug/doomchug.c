#include "doomchug.h"
#include "../geiger/geiger.h"                 /* geiger_exp */

#include <math.h>
#include <string.h>

static const FxParamDesc PARAMS[Q_NPARAMS] = {
    { "key",     "Key",     FX_INTEGER,    0.0f, 11.0f, 0.0f,  "semitones above low A", "immediate" },
    { "pattern", "Pattern", FX_INTEGER,    0.0f, 8.0f,  1.0f,  "0 Off, 1..8", "immediate" },
    { "rate",    "Rate",    FX_CONTINUOUS, 0.0f, 1.0f,  0.5f,  "0.05 .. 8 steps/s", "immediate" },
    { "drift",   "Drift",   FX_CONTINUOUS, 0.0f, 1.0f,  0.35f, "", "immediate" },
    { "warble",  "Warble",  FX_CONTINUOUS, 0.0f, 1.0f,  0.5f,  "", "immediate" },
    { "chug",    "Chug",    FX_CONTINUOUS, 0.0f, 1.0f,  0.4f,  "", "immediate" },
    { "tone",    "Tone",    FX_CONTINUOUS, 0.0f, 1.0f,  0.25f, "", "immediate" },
    { "level",   "Level",   FX_CONTINUOUS, 0.0f, 1.0f,  0.5f,  "x (shown as %)", "immediate" },
};

#define NIB(a, b, c, d, e, f, g, h) \
    ((unsigned)(a) | (unsigned)(b) << 4 | (unsigned)(c) << 8 | (unsigned)(d) << 12 | \
     (unsigned)(e) << 16 | (unsigned)(f) << 20 | (unsigned)(g) << 24 | (unsigned)(h) << 28)

static const unsigned PATTERNS[DOOMCHUG_PATTERNS] = {
    NIB(0, 0, 0, 0, 0, 0, 0, 0),                     /* Off */
    NIB(0, 0, 0, 3, 0, 0, 1, 0),                     /* crawl */
    NIB(0, 3, 5, 6, 5, 3, 0, 0),                     /* the blue note */
    NIB(0, 1, 0, 1, 3, 1, 0, 0),                     /* flat second */
    NIB(0, 0, 6, 6, 0, 0, 5, 5),                     /* tritone */
    NIB(0, 7, 6, 5, 3, 1, 0, 0),                     /* descent */
    NIB(0, 0, 0, 0, 10, 8, 7, 6),                    /* falling minor */
    NIB(0, 12, 0, 10, 0, 7, 0, 6),                   /* octave riff */
    NIB(0, 3, 1, 6, 0, 8, 7, 1),                     /* lost */
};

unsigned doomchug_pattern(int p)
{
    return PATTERNS[p < 0 ? 0 : p >= DOOMCHUG_PATTERNS ? DOOMCHUG_PATTERNS - 1 : p];
}

#define K_RATE  1.6666667e-5f                    /* 0.05 Hz in steps a control tick */
#define K_LN160 5.07517382f
#define K_LN80  4.38202663f
#define K_LN2   0.693147182f
#define K_F0    0.0022916667f                    /* 110 Hz in cycles a sample */
#define K_NEG_W (-1.3089969e-4f)                 /* -2 pi / sr */
#define K_1_12  0.083333336f
#define K_R     1.52587890625e-5f                /* 1 / 65536 */
#define K_LA    1.0e-4f                          /* 0.3 Hz, a control tick */
#define K_LB    2.0e-3f                          /* 6 Hz */
#define K_GLIDE 0.0015f
#define K_WALK  0.001f
#define K_ENV   0.9985f
#define K_DRIFT 0.5f                             /* octaves at Drift 1 */
#define K_WARB  0.16f                            /* octaves at Warble 1, on the triangle 0..0.5 */
#define K_TREM  1.2f
#define K_Z     0.6f

static const float OFFSET[DOOMCHUG_VOICES] = { 0.0f, 0.012f, 0.5833333f, 1.0f };   /* root, sharp root, fifth, octave */

static void reset(void *st, float sr)
{
    DoomChugState *s = st;
    (void)sr;
    memset(s, 0, sizeof *s);
    s->rnd = DOOMCHUG_SEED;
    s->sphase = 1.0f;                            /* the first tick is a step: every voice gets a target */
}

/* One control tick: the step, the walks, the LFOs and each voice's pitch and gain ramp. */
static void control(DoomChugState *s, int key, unsigned pw, float rinc, float dk, float wk, float tk, float chug)
{
    float sv, cg;
    int v;

    s->sphase += rinc;
    if (s->sphase >= 1.0f) {
        s->sphase -= 1.0f;
        s->step = (s->step + 1) & 7;
        s->env = 1.0f;
        for (v = 0; v < DOOMCHUG_VOICES; v++) {
            s->rnd ^= s->rnd << 13;              /* xorshift32 */
            s->rnd ^= s->rnd >> 17;
            s->rnd ^= s->rnd << 5;
            s->dt[v] = (float)(s->rnd >> 16) * K_R;
            s->li[v] = K_LA + K_LB * ((float)(s->rnd & 0xFFFFu) * K_R);
        }
    }
    s->env *= K_ENV;
    cg = 1.0f - chug * (1.0f - s->env);
    sv = (float)(key + (int)((pw >> (4 * s->step)) & 15u)) * K_1_12;

    for (v = 0; v < DOOMCHUG_VOICES; v++) {
        float target = sv + OFFSET[v], tri, q;
        s->base[v] += K_GLIDE * (target - s->base[v]);
        s->d[v] += K_WALK * (s->dt[v] - s->d[v]);
        s->lp[v] += s->li[v];
        if (s->lp[v] >= 1.0f) s->lp[v] -= 1.0f;
        tri = fabsf(s->lp[v] - 0.5f);
        q = s->base[v] + dk * s->d[v] + wk * tri;
        if (q > 2.0f) q = 4.0f - q;              /* at most 3.75 here, so q stays above 0 */
        s->inc[v] = geiger_exp(q * K_LN2) * K_F0;
        s->dg[v] = ((1.0f - tk * tri) * cg - s->g[v]) * 0.0625f;
    }
}

static void process(void *st, const FxParams *p, const float *in, float *out, size_t n)
{
    DoomChugState *s = st;
    const FxParamDesc *d = PARAMS;
    int key = (int)fx_param_clamp(&d[Q_KEY], p->value[Q_KEY]);
    unsigned pw = doomchug_pattern((int)fx_param_clamp(&d[Q_PATTERN], p->value[Q_PATTERN]));
    float rinc = geiger_exp(fx_param_clamp(&d[Q_RATE], p->value[Q_RATE]) * K_LN160) * K_RATE;
    float dk = fx_param_clamp(&d[Q_DRIFT], p->value[Q_DRIFT]) * K_DRIFT;
    float warble = fx_param_clamp(&d[Q_WARBLE], p->value[Q_WARBLE]);
    float wk = warble * K_WARB, tk = warble * K_TREM;
    float chug = fx_param_clamp(&d[Q_CHUG], p->value[Q_CHUG]);
    float tone = fx_param_clamp(&d[Q_TONE], p->value[Q_TONE]);
    float level = fx_param_clamp(&d[Q_LEVEL], p->value[Q_LEVEL]);
    size_t i;
    int v;

    s->tone_a = 1.0f - geiger_exp(100.0f * geiger_exp(tone * K_LN80) * K_NEG_W);
    for (i = 0; i < n; i++) {
        float x = in[i], z = 0.0f;
        if (!isfinite(x)) x = 0.0f;
        if (s->cnt == 0) control(s, key, pw, rinc, dk, wk, tk, chug);
        s->cnt = (s->cnt + 1) & 15;

        for (v = 0; v < DOOMCHUG_VOICES; v++) {
            s->ph[v] += s->inc[v];
            if (s->ph[v] >= 1.0f) s->ph[v] -= 1.0f;
            s->g[v] += s->dg[v];
            z += (s->ph[v] - 0.5f) * s->g[v];
        }
        z *= K_Z;
        if (z > 1.0f) z = 1.0f;
        if (z < -1.0f) z = -1.0f;
        z = 1.5f * z - 0.5f * z * z * z;
        s->z1 += s->tone_a * (z - s->z1);
        s->z2 += s->tone_a * (s->z1 - s->z2);
        out[i] = x + s->z2 * level;
    }
}

const FxAlgorithm fx_doomchug = {
    "doomchug", "Doom Chug", sizeof(DoomChugState), PARAMS, Q_NPARAMS, reset, process,
};
