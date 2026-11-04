#include "commander.h"
#include "../geiger/geiger.h"                 /* geiger_exp */

#include <math.h>
#include <string.h>

#define PI 3.14159265358979323846

static const FxParamDesc PARAMS[C_NPARAMS] = {
    { "fuzz",   "Fuzz",       FX_CONTINUOUS, 0.0f,  1.0f,  0.7f,  "x (shown as %)", "per-sample" },
    { "sub1",   "Sub -1 Oct", FX_CONTINUOUS, 0.0f,  1.0f,  0.5f,  "x (shown as %)", "per-sample" },
    { "sub2",   "Sub -2 Oct", FX_CONTINUOUS, 0.0f,  1.0f,  0.0f,  "x (shown as %)", "per-sample" },
    { "up",     "Octave Up",  FX_CONTINUOUS, 0.0f,  1.0f,  0.0f,  "x (shown as %)", "per-sample" },
    { "tone",   "Tone",       FX_CONTINUOUS, 0.0f,  1.0f,  0.5f,  "", "immediate" },
    { "gate",   "Gate",       FX_INTEGER,    0.0f,  10.0f, 3.0f,  "0 off, k: -90 + 6k dB", "per-sample" },
    { "dry",    "Dry",        FX_INTEGER,    0.0f,  10.0f, 0.0f,  "k x 10 %", "per-sample" },
    { "output", "Output",     FX_CONTINUOUS, -36.0f, 12.0f, -6.0f, "dB", "per-sample" },
};

#define LN10_20 0.115129255f                  /* ln(10) / 20 */
#define LN100 4.60517019f
#define K_HYST 0.5f                           /* comparator hysteresis, x the envelope (tracks plucked notes, low E to high B) */
#define K_HFLOOR 0.00001f                     /* and at least this, so silence does not chatter */
#define K_UPTH 0.5f                           /* octave up: |t| above half the envelope */
#define K_VCA 4.0f                            /* the squares' level: envelope x 4, at most 1 */

float commander_gate(int k)
{
    if (k <= 0) return 0.0f;
    if (k > COMMANDER_GATE_STEPS) k = COMMANDER_GATE_STEPS;
    return geiger_exp((float)(6 * k - 90) * LN10_20);
}

static void reset(void *st, float sr)
{
    CommanderState *s = st;
    memset(s, 0, sizeof *s);
    s->dc_r = 1.0f - (float)(2 * PI * 10.0 / sr);
    s->smooth_k = (float)(1.0 - exp(-1.0 / (0.005 * sr)));
    s->lp_a = (float)(1.0 - exp(-2 * PI * 300.0 / sr));
    s->rel = (float)exp(-1.0 / (0.05 * sr));
    s->neg_w = (float)(-2 * PI / sr);
    s->top = 0.45f * sr;
    s->sq = s->d1 = s->d2 = 1.0f;
}

static float smooth(float cur, float target, float k)
{
    float d = target - cur;
    if (fabsf(d) < 1e-6f) return target;
    return cur + k * d;
}

static void process(void *st, const FxParams *p, const float *in, float *out, size_t n)
{
    CommanderState *s = st;
    const FxParamDesc *d = PARAMS;
    float tgt[CG_N], thr, fc, tone_a, k = s->smooth_k;
    int j;
    size_t i;

    tgt[CG_FUZZ] = fx_param_clamp(&d[C_FUZZ], p->value[C_FUZZ]);
    tgt[CG_SUB1] = fx_param_clamp(&d[C_SUB1], p->value[C_SUB1]);
    tgt[CG_SUB2] = fx_param_clamp(&d[C_SUB2], p->value[C_SUB2]);
    tgt[CG_UP] = fx_param_clamp(&d[C_UP], p->value[C_UP]);
    tgt[CG_DRY] = (float)(int)fx_param_clamp(&d[C_DRY], p->value[C_DRY]) * 0.1f;
    tgt[CG_OUT] = geiger_exp(fx_param_clamp(&d[C_OUTPUT], p->value[C_OUTPUT]) * LN10_20);
    thr = commander_gate((int)fx_param_clamp(&d[C_GATE], p->value[C_GATE]));
    fc = 100.0f * geiger_exp(fx_param_clamp(&d[C_TONE], p->value[C_TONE]) * LN100);   /* 100 Hz .. 10 kHz */
    if (fc > s->top) fc = s->top;
    tone_a = 1.0f - geiger_exp(fc * s->neg_w);
    if (!s->primed) {
        for (j = 0; j < CG_N; j++) s->g[j] = tgt[j];
        s->primed = 1;
    }

    for (i = 0; i < n; i++) {
        float x = in[i], y, t, a, h, up, v, lvl, gt, w;
        if (!isfinite(x)) x = 0.0f;
        for (j = 0; j < CG_N; j++) s->g[j] = smooth(s->g[j], tgt[j], k);

        y = x - s->dcx + s->dc_r * s->dcy;           /* DC block */
        s->dcx = x; s->dcy = y;
        s->lp1 += s->lp_a * (y - s->lp1);            /* the tracking signal */
        s->lp2 += s->lp_a * (s->lp1 - s->lp2);
        t = s->lp2;
        a = fabsf(t);
        if (a > s->env) s->env = a;                   /* envelope: instant attack, slow release */
        else s->env = s->env * s->rel;

        h = s->env * K_HYST + K_HFLOOR;
        if (s->sq > 0.0f) {
            if (t < -h) s->sq = -1.0f;
        } else if (t > h) {                           /* a rising edge: the dividers step */
            s->sq = 1.0f;
            s->d1 = -s->d1;
            if (s->d1 > 0.0f) s->d2 = -s->d2;
        }
        up = a > s->env * K_UPTH ? 1.0f : -1.0f;

        v = s->sq * s->g[CG_FUZZ] + s->d1 * s->g[CG_SUB1];
        v = v + s->d2 * s->g[CG_SUB2];
        v = v + up * s->g[CG_UP];
        lvl = s->env * K_VCA;
        if (lvl > 1.0f) lvl = 1.0f;
        gt = s->env > thr ? 1.0f : 0.0f;
        s->ggate = smooth(s->ggate, gt, k);
        w = v * lvl;
        w = w * s->ggate;

        s->t1 += tone_a * (w - s->t1);
        s->t2 += tone_a * (s->t1 - s->t2);
        y = x * s->g[CG_DRY] + s->t2 * s->g[CG_OUT];
        if (!isfinite(y) || fabsf(y) > 8.0f) {        /* never pass on a bad value */
            s->dcx = s->dcy = s->lp1 = s->lp2 = s->env = s->t1 = s->t2 = 0.0f;
            y = 0.0f;
        }
        out[i] = y;
    }
}

const FxAlgorithm fx_commander = {
    "commander", "Commander", sizeof(CommanderState), PARAMS, C_NPARAMS, reset, process,
};
