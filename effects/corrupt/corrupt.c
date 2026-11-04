#include "corrupt.h"
#include "../geiger/geiger.h"                 /* geiger_exp */

#include <math.h>
#include <string.h>

#define PI 3.14159265358979323846

static const FxParamDesc PARAMS[R_NPARAMS] = {
    { "square", "Square",   FX_CONTINUOUS, 0.0f,  1.0f,  0.0f,  "x (shown as %)", "per-sample" },
    { "master", "Master",   FX_CONTINUOUS, 0.0f,  1.0f,  0.8f,  "x (shown as %)", "per-sample" },
    { "sub",    "Sub",      FX_CONTINUOUS, 0.0f,  1.0f,  0.4f,  "x (shown as %)", "per-sample" },
    { "glide",  "Glide",    FX_CONTINUOUS, 0.0f,  1.0f,  0.2f,  "", "immediate" },
    { "tone",   "Tone",     FX_CONTINUOUS, 0.0f,  1.0f,  0.6f,  "", "immediate" },
    { "output", "Output",   FX_CONTINUOUS, -36.0f, 12.0f, -6.0f, "dB", "per-sample" },
    { "root",   "Root",     FX_INTEGER,    0.0f,  3.0f,  2.0f,  "0 -2 oct, 1 -1 oct, 2 unison, 3 +1 oct", "immediate" },
    { "harm",   "Harmonic", FX_INTEGER,    1.0f,  8.0f,  1.0f,  "x the note", "immediate" },
};

#define LN10_20 0.115129255f
#define LN100 4.60517019f
#define K_GL (-9.21034037f)                   /* ln(1e-4): Glide 1 -> the rate moves 1e-4 of the way a sample */
#define K_HYST 0.5f
#define K_HFLOOR 0.00001f                     /* and at least this, so silence does not chatter */
#define K_VCA 4.0f
#define K_GATE 0.0005f                        /* -66 dB */
#define K_2M24 (1.0f / 16777216.0f)

static void reset(void *st, float sr)
{
    CorruptState *s = st;
    memset(s, 0, sizeof *s);
    s->dc_r = 1.0f - (float)(2 * PI * 10.0 / sr);
    s->smooth_k = (float)(1.0 - exp(-1.0 / (0.005 * sr)));
    s->lp_a = (float)(1.0 - exp(-2 * PI * 300.0 / sr));
    s->rel = (float)exp(-1.0 / (0.05 * sr));
    s->neg_w = (float)(-2 * PI / sr);
    s->top = 0.45f * sr;
}

static float smooth(float cur, float target, float k)
{
    float d = target - cur;
    if (fabsf(d) < 1e-6f) return target;
    return cur + k * d;
}

static void process(void *st, const FxParams *p, const float *in, float *out, size_t n)
{
    CorruptState *s = st;
    const FxParamDesc *d = PARAMS;
    float tgt[RG_N], fc, tone_a, glide_k, k = s->smooth_k;
    unsigned num;
    int j, root, harm;
    size_t i;

    tgt[RG_SQUARE] = fx_param_clamp(&d[R_SQUARE], p->value[R_SQUARE]);
    tgt[RG_MASTER] = fx_param_clamp(&d[R_MASTER], p->value[R_MASTER]);
    tgt[RG_SUB] = fx_param_clamp(&d[R_SUB], p->value[R_SUB]);
    tgt[RG_OUT] = geiger_exp(fx_param_clamp(&d[R_OUTPUT], p->value[R_OUTPUT]) * LN10_20);
    glide_k = geiger_exp(fx_param_clamp(&d[R_GLIDE], p->value[R_GLIDE]) * K_GL);
    fc = 100.0f * geiger_exp(fx_param_clamp(&d[R_TONE], p->value[R_TONE]) * LN100);    /* 100 Hz .. 10 kHz */
    if (fc > s->top) fc = s->top;
    tone_a = 1.0f - geiger_exp(fc * s->neg_w);
    root = (int)fx_param_clamp(&d[R_ROOT], p->value[R_ROOT]);
    harm = (int)fx_param_clamp(&d[R_HARM], p->value[R_HARM]);
    num = (unsigned)harm << (22 + root);
    if (!s->primed) {
        for (j = 0; j < RG_N; j++) s->g[j] = tgt[j];
        s->sq = s->sub = 1.0f;
        s->primed = 1;
    }

    for (i = 0; i < n; i++) {
        float x = in[i], y, t, a, h, m, v, lvl, gt, w;
        if (!isfinite(x)) x = 0.0f;
        for (j = 0; j < RG_N; j++) s->g[j] = smooth(s->g[j], tgt[j], k);

        y = x - s->dcx + s->dc_r * s->dcy;           /* DC block */
        s->dcx = x; s->dcy = y;
        s->lp1 += s->lp_a * (y - s->lp1);            /* the tracking signal */
        s->lp2 += s->lp_a * (s->lp1 - s->lp2);
        t = s->lp2;
        a = fabsf(t);
        if (a > s->env) s->env = a;
        else s->env = s->env * s->rel;

        if (s->cnt < CORRUPT_CNT_MAX) s->cnt++;
        h = s->env * K_HYST + K_HFLOOR;
        if (s->sq > 0.0f) {
            if (t < -h) s->sq = -1.0f;
        } else if (t > h) {                           /* a rising edge: one period measured */
            int per = s->cnt;
            s->sq = 1.0f;
            s->cnt = 0;
            if (per >= CORRUPT_PMIN && per <= CORRUPT_PMAX) {
                unsigned q = num / (unsigned)per;
                if (q > CORRUPT_QMAX) q = CORRUPT_QMAX;
                s->inc_t = (float)q * K_2M24;
            }
        }
        s->inc = s->inc + glide_k * (s->inc_t - s->inc);
        s->ph = s->ph + s->inc;
        if (s->ph >= 1.0f) {
            s->ph = s->ph - 1.0f;
            s->sub = -s->sub;
        }
        m = s->ph < 0.5f ? 1.0f : -1.0f;

        v = s->sq * s->g[RG_SQUARE] + m * s->g[RG_MASTER];
        v = v + s->sub * s->g[RG_SUB];
        lvl = s->env * K_VCA;
        if (lvl > 1.0f) lvl = 1.0f;
        gt = s->env > K_GATE ? 1.0f : 0.0f;
        s->ggate = smooth(s->ggate, gt, k);
        w = v * lvl;
        w = w * s->ggate;

        s->t1 += tone_a * (w - s->t1);
        s->t2 += tone_a * (s->t1 - s->t2);
        w = s->t2 - s->ox + s->dc_r * s->oy;          /* the squares' DC */
        s->ox = s->t2; s->oy = w;
        y = w * s->g[RG_OUT];
        if (!isfinite(y) || fabsf(y) > 8.0f) {
            s->dcx = s->dcy = s->lp1 = s->lp2 = s->env = s->t1 = s->t2 = s->ox = s->oy = 0.0f;
            y = 0.0f;
        }
        out[i] = y;
    }
}

const FxAlgorithm fx_corrupt = {
    "corrupt", "Corrupt", sizeof(CorruptState), PARAMS, R_NPARAMS, reset, process,
};
