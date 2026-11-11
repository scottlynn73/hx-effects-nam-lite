#include "syntax.h"
#include "../geiger/geiger.h"                 /* geiger_exp */
#include "../ottobit/ottobit.h"               /* ottobit_sin */

#include <math.h>
#include <string.h>

#define PI 3.14159265358979323846

static const FxParamDesc PARAMS[Y_NPARAMS] = {
    { "drive",   "Drive",   FX_CONTINUOUS, 0.0f,  36.0f,   12.0f, "dB", "per-sample" },
    { "shift",   "Shift",   FX_CONTINUOUS, 0.0f,  1000.0f, 150.0f, "Hz", "immediate" },
    { "pattern", "Pattern", FX_INTEGER,    0.0f,  8.0f,    1.0f,  "0 Off, 1..8", "immediate" },
    { "speed",   "Speed",   FX_CONTINUOUS, 0.5f,  16.0f,   4.0f,  "steps/s", "immediate" },
    { "glide",   "Glide",   FX_CONTINUOUS, 0.0f,  1.0f,    0.2f,  "", "immediate" },
    { "tone",    "Tone",    FX_CONTINUOUS, 0.0f,  1.0f,    0.7f,  "", "immediate" },
    { "output",  "Output",  FX_CONTINUOUS, -36.0f, 12.0f,  -6.0f, "dB", "per-sample" },
    { "mix",     "Mix",     FX_CONTINUOUS, 0.0f,  1.0f,    1.0f,  "x (shown as %)", "per-sample" },
};

/* The Hilbert pair: each allpass is y = a^2 (x + y[n-2]) - x[n-2]; a from O. Niemitalo's published
   design (two paths ~90 degrees apart over the audio band). */
const float SYNTAX_COEF_A[SYNTAX_AP] = { 0.47940083486f, 0.87621849354f, 0.97659758951f, 0.99749925594f };
const float SYNTAX_COEF_B[SYNTAX_AP] = { 0.16175849837f, 0.73302893234f, 0.94534970033f, 0.99059915668f };

static const float PATTERNS[SYNTAX_PATTERNS][SYNTAX_STEPS] = {
    { 1, 1, 1, 1, 1, 1, 1, 1 },                                        /* Off */
    { 1, -1, 1, -1, 1, -1, 1, -1 },                                    /* up / down */
    { 0.25f, 0.5f, 1, 2, 1, 0.5f, 0.25f, 0 },                          /* swell */
    { 1, 1, -1, -1, 0.5f, 0.5f, -0.5f, -0.5f },                        /* pairs */
    { 2, 0, -2, 0, 1, 0, -1, 0 },                                      /* gaps */
    { 0.125f, 0.25f, 0.375f, 0.5f, 0.625f, 0.75f, 0.875f, 1 },         /* ramp up */
    { -1, -0.75f, -0.5f, -0.25f, 0, 0.25f, 0.5f, 0.75f },              /* through zero */
    { 1, 0.5f, -0.25f, 1.5f, -1, 0.75f, -1.5f, 0.25f },                /* scatter */
    { 2, -1.5f, 1, -0.5f, 0.25f, -2, 1.5f, -0.75f },                   /* wide scatter */
};

const float *syntax_pattern(int p)
{
    return PATTERNS[p < 0 ? 0 : p >= SYNTAX_PATTERNS ? SYNTAX_PATTERNS - 1 : p];
}

#define LN10_20 0.115129255f
#define LN100 4.60517019f
#define K_GL (-9.21034037f)                      /* Glide 1 -> the shift moves 1e-4 of the way a sample */

static void reset(void *st, float sr)
{
    SyntaxState *s = st;
    memset(s, 0, sizeof *s);
    s->dc_r = 1.0f - (float)(2 * PI * 10.0 / sr);
    s->smooth_k = (float)(1.0 - exp(-1.0 / (0.005 * sr)));
    s->two_pi_sr = (float)(2 * PI / sr);
    s->neg_w = (float)(-2 * PI / sr);
    s->top = 0.45f * sr;
    s->c = 1.0f;
}

static float smooth(float cur, float target, float k)
{
    float d = target - cur;
    if (fabsf(d) < 1e-6f) return target;
    return cur + k * d;
}

static float allpass(float x, float *xs, float *ys, float a2)
{
    float y = a2 * (x + ys[1]) - xs[1];
    xs[1] = xs[0]; xs[0] = x;
    ys[1] = ys[0]; ys[0] = y;
    return y;
}

static void process(void *st, const FxParams *p, const float *in, float *out, size_t n)
{
    SyntaxState *s = st;
    const FxParamDesc *d = PARAMS;
    float drive = geiger_exp(fx_param_clamp(&d[Y_DRIVE], p->value[Y_DRIVE]) * LN10_20);
    float shift = fx_param_clamp(&d[Y_SHIFT], p->value[Y_SHIFT]);
    const float *pat = syntax_pattern((int)fx_param_clamp(&d[Y_PATTERN], p->value[Y_PATTERN]));
    float sinc = fx_param_clamp(&d[Y_SPEED], p->value[Y_SPEED]) * (1.0f / FX_DEVICE_RATE);
    float gk = geiger_exp(fx_param_clamp(&d[Y_GLIDE], p->value[Y_GLIDE]) * K_GL);
    float fc = 200.0f * geiger_exp(fx_param_clamp(&d[Y_TONE], p->value[Y_TONE]) * LN100);
    float outg = geiger_exp(fx_param_clamp(&d[Y_OUTPUT], p->value[Y_OUTPUT]) * LN10_20);
    float mix = fx_param_clamp(&d[Y_MIX], p->value[Y_MIX]);
    float tone_a, k = s->smooth_k;
    size_t i;
    int j;

    if (fc > s->top) fc = s->top;
    tone_a = 1.0f - geiger_exp(fc * s->neg_w);
    if (!s->primed) {
        s->g_drive = drive; s->g_out = outg; s->g_mix = mix;
        s->f = shift * pat[0];
        s->primed = 1;
    }

    for (i = 0; i < n; i++) {
        float x = in[i], y, a, b, w, sw, h, cw, nc, ns, g, wet;
        if (!isfinite(x)) x = 0.0f;
        s->g_drive = smooth(s->g_drive, drive, k);
        s->g_out = smooth(s->g_out, outg, k);
        s->g_mix = smooth(s->g_mix, mix, k);

        s->sphase += sinc;                              /* the sequencer and the glide */
        if (s->sphase >= 1.0f) {
            s->sphase -= 1.0f;
            s->step++;
            if (s->step >= SYNTAX_STEPS) s->step = 0;
        }
        s->f += gk * (shift * pat[s->step] - s->f);

        y = x - s->dcx + s->dc_r * s->dcy;              /* DC block, drive, soft clip */
        s->dcx = x; s->dcy = y;
        y = y * s->g_drive;
        if (y > 1.0f) y = 1.0f;
        if (y < -1.0f) y = -1.0f;
        y = 1.5f * y - 0.5f * y * y * y;

        a = s->adel;                                    /* the Hilbert pair: path A a sample later */
        s->adel = y;
        b = y;
        for (j = 0; j < SYNTAX_AP; j++) {
            a = allpass(a, s->ax[j], s->ay[j], SYNTAX_COEF_A[j]);
            b = allpass(b, s->bx[j], s->by[j], SYNTAX_COEF_B[j]);
        }

        w = s->f * s->two_pi_sr;                        /* the oscillator: rotate, renormalise */
        sw = ottobit_sin(w);
        h = ottobit_sin(0.5f * w);
        cw = 1.0f - 2.0f * h * h;
        nc = s->c * cw - s->s * sw;
        ns = s->s * cw + s->c * sw;
        g = 1.5f - 0.5f * (nc * nc + ns * ns);
        s->c = nc * g;
        s->s = ns * g;

        y = a * s->c + b * s->s;                        /* the upper sideband (shift > 0: up) */
        s->tone_z += tone_a * (y - s->tone_z);
        wet = s->tone_z * s->g_out;
        y = x * (1.0f - s->g_mix) + wet * s->g_mix;
        if (!isfinite(y) || fabsf(y) > 8.0f) {
            memset(s->ax, 0, sizeof s->ax); memset(s->ay, 0, sizeof s->ay);
            memset(s->bx, 0, sizeof s->bx); memset(s->by, 0, sizeof s->by);
            s->dcx = s->dcy = s->adel = s->tone_z = 0.0f;
            y = 0.0f;
        }
        out[i] = y;
    }
}

const FxAlgorithm fx_syntax = {
    "syntax", "Syntax", sizeof(SyntaxState), PARAMS, Y_NPARAMS, reset, process,
};
