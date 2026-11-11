#include "ottobit.h"
#include "../geiger/geiger.h"                 /* geiger_exp, geiger_quantize */

#include <math.h>
#include <string.h>

#define PI 3.14159265358979323846

static const FxParamDesc PARAMS[O_NPARAMS] = {
    { "rate",    "Sample Rate", FX_CONTINUOUS, 250.0f, 48000.0f, 8000.0f, "Hz", "immediate" },
    { "bits",    "Bit Depth",   FX_INTEGER,    1.0f,  16.0f,    6.0f,     "bits", "immediate" },
    { "filter",  "Filter",      FX_CONTINUOUS, 0.0f,  1.0f,     0.7f,     "", "immediate" },
    { "pattern", "Pattern",     FX_INTEGER,    0.0f,  8.0f,     1.0f,     "0 Off, 1..8", "immediate" },
    { "speed",   "Speed",       FX_CONTINUOUS, 0.5f,  16.0f,    4.0f,     "steps/s", "immediate" },
    { "stutter", "Stutter",     FX_CONTINUOUS, 0.0f,  1.0f,     0.2f,     "probability", "immediate" },
    { "output",  "Output",      FX_CONTINUOUS, -36.0f, 12.0f,   -6.0f,    "dB", "per-sample" },
    { "mix",     "Mix",         FX_CONTINUOUS, 0.0f,  1.0f,     1.0f,     "x (shown as %)", "per-sample" },
};

/* Each pattern's six steps as exponents {rate, filter}: the multipliers are 2^e, exact. */
static const signed char EXPS[OTTOBIT_PATTERNS][OTTOBIT_STEPS][2] = {
    { { 0, 0 }, { 0, 0 }, { 0, 0 }, { 0, 0 }, { 0, 0 }, { 0, 0 } },              /* Off */
    { { 0, 0 }, { -1, 0 }, { -2, 0 }, { -3, 0 }, { -2, 0 }, { -1, 0 } },         /* rate down and up */
    { { 0, 0 }, { 0, -1 }, { 0, -2 }, { 0, -3 }, { 0, -2 }, { 0, -1 } },         /* filter down and up */
    { { 0, 0 }, { -1, -1 }, { -2, -2 }, { -3, -3 }, { -4, -4 }, { -5, -5 } },    /* both falling */
    { { 0, -2 }, { -3, 0 }, { 0, -2 }, { -3, 0 }, { 0, -2 }, { -3, 0 } },        /* see-saw */
    { { -4, 0 }, { -2, -3 }, { 0, -1 }, { -4, 0 }, { -2, -3 }, { 0, -1 } },      /* rising triplets */
    { { 0, -1 }, { 0, -1 }, { -2, -3 }, { 0, -1 }, { 0, -1 }, { -4, -5 } },      /* accent on 3 and 6 */
    { { -1, -4 }, { -3, -2 }, { -5, 0 }, { -1, -4 }, { -3, -2 }, { -5, 0 } },    /* crossing */
    { { 0, -3 }, { -5, 0 }, { -1, -4 }, { -4, -1 }, { -2, -5 }, { -3, -2 } },    /* scatter */
};

static float TABLE[OTTOBIT_PATTERNS][OTTOBIT_STEPS][2];
static int table_built;

const float *ottobit_pattern(int p)
{
    int i, j, k;
    if (!table_built) {
        for (i = 0; i < OTTOBIT_PATTERNS; i++)
            for (j = 0; j < OTTOBIT_STEPS; j++)
                for (k = 0; k < 2; k++)
                    TABLE[i][j][k] = ldexpf(1.0f, EXPS[i][j][k]);
        table_built = 1;
    }
    if (p < 0) p = 0;
    if (p >= OTTOBIT_PATTERNS) p = OTTOBIT_PATTERNS - 1;
    return &TABLE[p][0][0];
}

#define S3 (-1.0f / 6.0f)
#define S5 (1.0f / 120.0f)
#define S7 (-1.0f / 5040.0f)

float ottobit_sin(float x)
{
    float x2 = x * x, p;
    p = S7;
    p = p * x2 + S5;
    p = p * x2 + S3;
    p = p * x2 + 1.0f;
    return p * x;
}

#define LN10_20 0.115129255f
#define LN80 4.38202663f                  /* Filter 0..1 -> 100 Hz .. 8 kHz */
#define K_Q 0.5f                          /* the filter's damping: Q 2 */

static void reset(void *st, float sr)
{
    OttobitState *s = st;
    memset(s, 0, sizeof *s);
    ottobit_pattern(0);
    s->dc_r = 1.0f - (float)(2 * PI * 10.0 / sr);
    s->smooth_k = (float)(1.0 - exp(-1.0 / (0.005 * sr)));
    s->inv_sr = (float)(1.0 / sr);
    s->pi_sr = (float)(PI / sr);
    s->rnd = OTTOBIT_SEED;
    s->prev_cnt = 4 * OTTOBIT_LMIN;
}

static float smooth(float cur, float target, float k)
{
    float d = target - cur;
    if (fabsf(d) < 1e-6f) return target;
    return cur + k * d;
}

static void process(void *st, const FxParams *p, const float *in, float *out, size_t n)
{
    OttobitState *s = st;
    const FxParamDesc *d = PARAMS;
    float rate = fx_param_clamp(&d[O_RATE], p->value[O_RATE]);
    int bits = (int)fx_param_clamp(&d[O_BITS], p->value[O_BITS]);
    float fbase = 100.0f * geiger_exp(fx_param_clamp(&d[O_FILTER], p->value[O_FILTER]) * LN80);
    const float *pat = ottobit_pattern((int)fx_param_clamp(&d[O_PATTERN], p->value[O_PATTERN]));
    float sinc = fx_param_clamp(&d[O_SPEED], p->value[O_SPEED]) * s->inv_sr;
    unsigned thr = (unsigned)(fx_param_clamp(&d[O_STUTTER], p->value[O_STUTTER]) * 16777216.0f);
    float outg = geiger_exp(fx_param_clamp(&d[O_OUTPUT], p->value[O_OUTPUT]) * LN10_20);
    float mix = fx_param_clamp(&d[O_MIX], p->value[O_MIX]);
    float inc = rate * s->inv_sr, k = s->smooth_k;
    size_t i;

    if (!s->primed) {
        s->g_out = outg; s->g_mix = mix;
        s->primed = 1;
    }

    for (i = 0; i < n; i++) {
        float x = in[i], y, src, f, hi, wet;
        if (!isfinite(x)) x = 0.0f;
        s->g_out = smooth(s->g_out, outg, k);
        s->g_mix = smooth(s->g_mix, mix, k);

        s->cnt++;                                       /* the sequencer */
        s->sphase += sinc;
        if (s->sphase >= 1.0f) {
            s->sphase -= 1.0f;
            s->step++;
            if (s->step >= OTTOBIT_STEPS) s->step = 0;
            s->prev_cnt = s->cnt;
            s->cnt = 0;
            s->rnd ^= s->rnd << 13;                     /* xorshift32 */
            s->rnd ^= s->rnd >> 17;
            s->rnd ^= s->rnd << 5;
            s->stut = (s->rnd >> 8) < thr;
            if (s->stut) {
                int len = s->prev_cnt >> 2;
                if (len < OTTOBIT_LMIN) len = OTTOBIT_LMIN;
                if (len > OTTOBIT_BUF) len = OTTOBIT_BUF;
                s->len = len;
                s->start = (s->w - len) & (OTTOBIT_BUF - 1);
                s->j = 0;
            }
        }

        y = x - s->dcx + s->dc_r * s->dcy;              /* DC block */
        s->dcx = x; s->dcy = y;
        if (s->stut) {                                  /* the stutter loop, or record */
            src = s->buf[(s->start + s->j) & (OTTOBIT_BUF - 1)];
            s->j++;
            if (s->j >= s->len) s->j = 0;
        } else {
            s->buf[s->w] = y;
            s->w = (s->w + 1) & (OTTOBIT_BUF - 1);
            src = y;
        }

        s->phase += inc * pat[2 * s->step];             /* sample-and-hold */
        if (s->phase >= 1.0f) {
            s->phase -= 1.0f;
            s->held = src;
        }
        y = geiger_quantize(s->held, bits);

        f = 2.0f * ottobit_sin(fbase * pat[2 * s->step + 1] * s->pi_sr);   /* the filter */
        s->low += f * s->band;
        hi = y - s->low - K_Q * s->band;
        s->band += f * hi;
        y = s->low;

        wet = y - s->ox + s->dc_r * s->oy;              /* DC block */
        s->ox = y; s->oy = wet;
        wet = wet * s->g_out;
        y = x * (1.0f - s->g_mix) + wet * s->g_mix;
        if (!isfinite(y) || fabsf(y) > 8.0f) {
            s->dcx = s->dcy = s->ox = s->oy = s->held = s->low = s->band = 0.0f;
            y = 0.0f;
        }
        out[i] = y;
    }
}

const FxAlgorithm fx_ottobit = {
    "ottobit", "Ottobit", sizeof(OttobitState), PARAMS, O_NPARAMS, reset, process,
};
