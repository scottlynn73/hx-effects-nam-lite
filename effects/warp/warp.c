#include "warp.h"
#include "../geiger/geiger.h"                 /* geiger_exp */

#include <math.h>
#include <string.h>

#define PI 3.14159265358979323846

static const FxParamDesc PARAMS[W_NPARAMS] = {
    { "pitch",    "Pitch",    FX_INTEGER,    0.0f,  7.0f,  6.0f,  "-12, -7, -5, 0, +5, +7, +12, +24 semitones", "immediate" },
    { "depth",    "Depth",    FX_CONTINUOUS, 0.0f,  1.0f,  0.3f,  "", "immediate" },
    { "rate",     "Rate",     FX_CONTINUOUS, 0.05f, 10.0f, 0.5f,  "Hz", "immediate" },
    { "chaos",    "Chaos",    FX_CONTINUOUS, 0.0f,  1.0f,  0.0f,  "", "immediate" },
    { "feedback", "Feedback", FX_CONTINUOUS, 0.0f,  0.95f, 0.5f,  "", "immediate" },
    { "tone",     "Tone",     FX_CONTINUOUS, 0.0f,  1.0f,  0.7f,  "", "immediate" },
    { "output",   "Output",   FX_CONTINUOUS, -36.0f, 12.0f, -3.0f, "dB", "per-sample" },
    { "mix",      "Mix",      FX_CONTINUOUS, 0.0f,  1.0f,  0.5f,  "x (shown as %)", "per-sample" },
};

const float WARP_RATIO[WARP_PITCHES] = { 0.5f, 0.667419927f, 0.749153538f, 1.0f, 1.33483985f, 1.49830708f, 2.0f, 4.0f };

#define M (WARP_RING - 1)
#define LN10_20 0.115129255f
#define LN100 4.60517019f
#define K_MD 0.03f                              /* Depth 1: about half a semitone either way */
#define K_CV 0.001f                             /* the chaos value's glide */
#define K_2W (2.0f / WARP_WIN)
#define K_2M24 (1.0f / 16777216.0f)

static void reset(void *st, float sr)
{
    WarpState *s = st;
    memset(s, 0, sizeof *s);
    s->smooth_k = (float)(1.0 - exp(-1.0 / (0.005 * sr)));
    s->neg_w = (float)(-2 * PI / sr);
    s->top = 0.45f * sr;
    s->rnd = WARP_SEED;
}

static float smooth(float cur, float target, float k)
{
    float d = target - cur;
    if (fabsf(d) < 1e-6f) return target;
    return cur + k * d;
}

static float head(const WarpState *s, float dd)                 /* the ring, dd samples back, interpolated */
{
    int j = (int)dd;
    float f = dd - (float)j, a = s->ring[(s->w - j) & M], b = s->ring[(s->w - j - 1) & M];
    return a + f * (b - a);
}

static void process(void *st, const FxParams *p, const float *in, float *out, size_t n)
{
    WarpState *s = st;
    const FxParamDesc *d = PARAMS;
    float ratio = WARP_RATIO[(int)fx_param_clamp(&d[W_PITCH], p->value[W_PITCH])];
    float depth = fx_param_clamp(&d[W_DEPTH], p->value[W_DEPTH]) * K_MD;
    float linc = fx_param_clamp(&d[W_RATE], p->value[W_RATE]) * (1.0f / FX_DEVICE_RATE);
    float chaos = fx_param_clamp(&d[W_CHAOS], p->value[W_CHAOS]);
    float fb = fx_param_clamp(&d[W_FEEDBACK], p->value[W_FEEDBACK]);
    float fc = 200.0f * geiger_exp(fx_param_clamp(&d[W_TONE], p->value[W_TONE]) * LN100);
    float outg = geiger_exp(fx_param_clamp(&d[W_OUTPUT], p->value[W_OUTPUT]) * LN10_20);
    float mix = fx_param_clamp(&d[W_MIX], p->value[W_MIX]);
    float tone_a, k = s->smooth_k;
    size_t i;

    if (fc > s->top) fc = s->top;
    tone_a = 1.0f - geiger_exp(fc * s->neg_w);
    if (!s->primed) {
        s->g_out = outg; s->g_mix = mix;
        s->primed = 1;
    }

    for (i = 0; i < n; i++) {
        float x = in[i], tri, mod, r, d2, g1, g2, wet, c, y;
        if (!isfinite(x)) x = 0.0f;
        s->g_out = smooth(s->g_out, outg, k);
        s->g_mix = smooth(s->g_mix, mix, k);

        s->lph += linc;                                 /* the modulation */
        if (s->lph >= 1.0f) {
            unsigned u;
            s->lph -= 1.0f;
            s->rnd ^= s->rnd << 13;
            s->rnd ^= s->rnd >> 17;
            s->rnd ^= s->rnd << 5;
            u = s->rnd >> 8;
            s->ct = (float)u * K_2M24 * 2.0f - 1.0f;
        }
        s->cv += K_CV * (s->ct - s->cv);
        tri = 1.0f - 4.0f * fabsf(s->lph - 0.5f);
        mod = tri * (1.0f - chaos) + s->cv * chaos;
        r = ratio * (1.0f + depth * mod);

        s->d += 1.0f - r;                               /* the shifter */
        if (s->d < 0.0f) s->d += (float)WARP_WIN;
        if (s->d >= (float)WARP_WIN) s->d -= (float)WARP_WIN;
        d2 = s->d + (float)(WARP_WIN / 2);
        if (d2 >= (float)WARP_WIN) d2 -= (float)WARP_WIN;
        g1 = 1.0f - fabsf(s->d * K_2W - 1.0f);
        g2 = 1.0f - fabsf(d2 * K_2W - 1.0f);
        wet = head(s, s->d + WARP_BASE) * g1 + head(s, d2 + WARP_BASE) * g2;

        c = wet;                                        /* record, with the shifted signal fed back */
        if (c > 1.0f) c = 1.0f;
        if (c < -1.0f) c = -1.0f;
        s->ring[s->w] = x + fb * c;
        s->w = (s->w + 1) & M;

        s->tone_z += tone_a * (wet - s->tone_z);        /* tone, output, mix */
        wet = s->tone_z * s->g_out;
        y = x * (1.0f - s->g_mix) + wet * s->g_mix;
        if (!isfinite(y) || fabsf(y) > 8.0f) {
            s->tone_z = 0.0f;
            y = 0.0f;
        }
        out[i] = y;
    }
}

const FxAlgorithm fx_warp = {
    "warp", "Warp", sizeof(WarpState), PARAMS, W_NPARAMS, reset, process,
};
