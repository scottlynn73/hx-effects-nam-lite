#include "sequence.h"
#include "../geiger/geiger.h"                 /* geiger_exp */

#include <math.h>
#include <string.h>

#define PI 3.14159265358979323846

static const FxParamDesc PARAMS[Q_NPARAMS] = {
    { "pattern", "Pattern", FX_INTEGER,    0.0f,  8.0f,   2.0f,  "0 Off, 1..8", "immediate" },
    { "speed",   "Speed",   FX_CONTINUOUS, 0.5f,  16.0f,  6.0f,  "steps/s", "immediate" },
    { "wave",    "Wave",    FX_INTEGER,    0.0f,  3.0f,   1.0f,  "Square, Saw, Triangle, Pulse", "immediate" },
    { "octave",  "Octave",  FX_INTEGER,    0.0f,  3.0f,   2.0f,  "-2, -1, 0, +1", "immediate" },
    { "glide",   "Glide",   FX_CONTINUOUS, 0.0f,  1.0f,   0.1f,  "", "immediate" },
    { "tone",    "Tone",    FX_CONTINUOUS, 0.0f,  1.0f,   0.6f,  "", "immediate" },
    { "output",  "Output",  FX_CONTINUOUS, -36.0f, 12.0f, -6.0f, "dB", "per-sample" },
    { "mix",     "Mix",     FX_CONTINUOUS, 0.0f,  1.0f,   1.0f,  "x (shown as %)", "per-sample" },
};

static const signed char PATTERNS[SEQUENCE_PATTERNS][SEQUENCE_STEPS] = {     /* semitones */
    { 0, 0, 0, 0, 0, 0, 0, 0 },                  /* Off: follow the note */
    { 0, 12, 0, 12, 0, 12, 0, 12 },              /* octave bounce */
    { 0, 4, 7, 12, 0, 4, 7, 12 },                /* major */
    { 0, 3, 7, 12, 0, 3, 7, 12 },                /* minor */
    { 0, 7, 12, 19, 24, 19, 12, 7 },             /* fifths, up and down */
    { 0, 0, 12, 0, -12, 0, 7, 0 },               /* pedal */
    { 0, 5, 7, 10, 12, 10, 7, 5 },               /* pentatonic */
    { 0, -12, 7, -5, 12, 3, -7, 10 },            /* wide */
    { 0, 2, 3, 5, 7, 8, 10, 12 },                /* minor run */
};

static float RATIO[37];                          /* 2^(k/12), k = -12 .. 24 */
static int ratio_built;

float sequence_ratio(int p, int k)
{
    int i;
    if (!ratio_built) {
        for (i = 0; i < 37; i++) RATIO[i] = (float)pow(2.0, (i - 12) / 12.0);
        ratio_built = 1;
    }
    if (p < 0) p = 0;
    if (p >= SEQUENCE_PATTERNS) p = SEQUENCE_PATTERNS - 1;
    return RATIO[PATTERNS[p][k & (SEQUENCE_STEPS - 1)] + 12];
}

const float SEQUENCE_OCTAVE[4] = { 0.25f, 0.5f, 1.0f, 2.0f };

#define LN10_20 0.115129255f
#define LN100 4.60517019f
#define K_GL (-9.21034037f)
#define K_HYST 0.5f
#define K_HFLOOR 0.00001f
#define K_VCA 4.0f
#define K_GATE 0.0005f
#define K_2M24 (1.0f / 16777216.0f)
#define K_INCMAX 0.45f

static void reset(void *st, float sr)
{
    SequenceState *s = st;
    memset(s, 0, sizeof *s);
    sequence_ratio(0, 0);
    s->dc_r = 1.0f - (float)(2 * PI * 10.0 / sr);
    s->smooth_k = (float)(1.0 - exp(-1.0 / (0.005 * sr)));
    s->lp_a = (float)(1.0 - exp(-2 * PI * 300.0 / sr));
    s->rel = (float)exp(-1.0 / (0.05 * sr));
    s->neg_w = (float)(-2 * PI / sr);
    s->top = 0.45f * sr;
    s->sq = 1.0f;
}

static float smooth(float cur, float target, float k)
{
    float d = target - cur;
    if (fabsf(d) < 1e-6f) return target;
    return cur + k * d;
}

static void process(void *st, const FxParams *p, const float *in, float *out, size_t n)
{
    SequenceState *s = st;
    const FxParamDesc *d = PARAMS;
    int pat = (int)fx_param_clamp(&d[Q_PATTERN], p->value[Q_PATTERN]);
    float sinc = fx_param_clamp(&d[Q_SPEED], p->value[Q_SPEED]) * (1.0f / FX_DEVICE_RATE);
    int wave = (int)fx_param_clamp(&d[Q_WAVE], p->value[Q_WAVE]);
    float oct = SEQUENCE_OCTAVE[(int)fx_param_clamp(&d[Q_OCTAVE], p->value[Q_OCTAVE])];
    float gk = geiger_exp(fx_param_clamp(&d[Q_GLIDE], p->value[Q_GLIDE]) * K_GL);
    float fc = 100.0f * geiger_exp(fx_param_clamp(&d[Q_TONE], p->value[Q_TONE]) * LN100);   /* 100 Hz .. 10 kHz */
    float outg = geiger_exp(fx_param_clamp(&d[Q_OUTPUT], p->value[Q_OUTPUT]) * LN10_20);
    float mix = fx_param_clamp(&d[Q_MIX], p->value[Q_MIX]);
    float tone_a, k = s->smooth_k;
    size_t i;

    if (fc > s->top) fc = s->top;
    tone_a = 1.0f - geiger_exp(fc * s->neg_w);
    if (!s->primed) {
        s->g_out = outg; s->g_mix = mix;
        s->primed = 1;
    }

    for (i = 0; i < n; i++) {
        float x = in[i], y, t, a, h, tgt, v, lvl, gt, w;
        if (!isfinite(x)) x = 0.0f;
        s->g_out = smooth(s->g_out, outg, k);
        s->g_mix = smooth(s->g_mix, mix, k);

        y = x - s->dcx + s->dc_r * s->dcy;              /* DC block, the tracking signal, the envelope */
        s->dcx = x; s->dcy = y;
        s->lp1 += s->lp_a * (y - s->lp1);
        s->lp2 += s->lp_a * (s->lp1 - s->lp2);
        t = s->lp2;
        a = fabsf(t);
        if (a > s->env) s->env = a;
        else s->env = s->env * s->rel;

        if (s->cnt < SEQUENCE_CNT_MAX) s->cnt++;        /* the comparator and the period */
        h = s->env * K_HYST + K_HFLOOR;
        if (s->sq > 0.0f) {
            if (t < -h) s->sq = -1.0f;
        } else if (t > h) {
            int per = s->cnt;
            s->sq = 1.0f;
            s->cnt = 0;
            if (per >= SEQUENCE_PMIN && per <= SEQUENCE_PMAX)
                s->base = (float)(16777216u / (unsigned)per) * K_2M24;
        }

        s->sphase += sinc;                              /* the sequencer */
        if (s->sphase >= 1.0f) {
            s->sphase -= 1.0f;
            s->step = (s->step + 1) & (SEQUENCE_STEPS - 1);
        }
        tgt = s->base * sequence_ratio(pat, s->step) * oct;
        if (tgt > K_INCMAX) tgt = K_INCMAX;
        s->inc += gk * (tgt - s->inc);
        s->ph += s->inc;
        if (s->ph >= 1.0f) s->ph -= 1.0f;

        switch (wave) {                                 /* the oscillator */
        case 0:  v = s->ph < 0.5f ? 1.0f : -1.0f; break;
        case 1:  v = 2.0f * s->ph - 1.0f; break;
        case 2:  v = 1.0f - 4.0f * fabsf(s->ph - 0.5f); break;
        default: v = s->ph < 0.25f ? 1.0f : -1.0f; break;
        }
        lvl = s->env * K_VCA;
        if (lvl > 1.0f) lvl = 1.0f;
        gt = s->env > K_GATE ? 1.0f : 0.0f;
        s->ggate = smooth(s->ggate, gt, k);
        w = v * lvl;
        w = w * s->ggate;

        s->t1 += tone_a * (w - s->t1);                  /* tone, DC block, output, mix */
        s->t2 += tone_a * (s->t1 - s->t2);
        w = s->t2 - s->ox + s->dc_r * s->oy;
        s->ox = s->t2; s->oy = w;
        w = w * s->g_out;
        y = x * (1.0f - s->g_mix) + w * s->g_mix;
        if (!isfinite(y) || fabsf(y) > 8.0f) {
            s->dcx = s->dcy = s->lp1 = s->lp2 = s->env = s->t1 = s->t2 = s->ox = s->oy = 0.0f;
            y = 0.0f;
        }
        out[i] = y;
    }
}

const FxAlgorithm fx_sequence = {
    "sequence", "Sequence", sizeof(SequenceState), PARAMS, Q_NPARAMS, reset, process,
};
