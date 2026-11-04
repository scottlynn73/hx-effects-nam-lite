#include "geiger.h"

#include <math.h>
#include <string.h>

#define PI 3.14159265358979323846

static const FxParamDesc PARAMS[G_NPARAMS] = {
    { "gain",   "Gain",        FX_CONTINUOUS, 0.0f,  36.0f,    6.0f,     "dB", "per-sample" },
    { "rate",   "Sample Rate", FX_CONTINUOUS, 250.0f, 48000.0f, 12000.0f, "Hz", "immediate" },
    { "bits",   "Bit Depth",   FX_INTEGER,    1.0f,  16.0f,    8.0f,     "bits", "immediate" },
    { "curve",  "Curve",       FX_INTEGER,    0.0f,  15.0f,    0.0f,     "", "immediate" },
    { "tone",   "Tone",        FX_CONTINUOUS, 0.0f,  1.0f,     0.8f,     "", "immediate" },
    { "output", "Output",      FX_CONTINUOUS, -36.0f, 12.0f,   -6.0f,    "dB", "per-sample" },
    { "mix",    "Mix",         FX_CONTINUOUS, 0.0f,  1.0f,     1.0f,     "x (shown as %)", "per-sample" },
    { "aa",     "Anti-Alias",  FX_TOGGLE,     0.0f,  1.0f,     0.0f,     "", "immediate" },
};

/* ------------------------------------------------------------------ the curves */

static const char *const NAMES[GEIGER_CURVES] = {
    "linear", "soft", "hard", "sinefold", "trifold", "fullwave", "halfwave", "steps",
    "asym", "cheby3", "cheby5", "sine", "root", "spline", "ring", "gate",
};

const char *geiger_curve_name(int c) { return (c >= 0 && c < GEIGER_CURVES) ? NAMES[c] : "?"; }

static double clampd(double x, double lo, double hi) { return x < lo ? lo : x > hi ? hi : x; }

static double trifold(double x)                 /* fold into [-1, 1] as a triangle wave */
{
    double t = fmod(x + 1.0, 4.0);
    if (t < 0) t += 4.0;
    return t < 2.0 ? t - 1.0 : 3.0 - t;
}

static double spline(double x)                   /* Catmull-Rom through fixed, original points */
{
    static const double px[] = { -1.0, -0.6, -0.2, 0.0, 0.3, 0.6, 1.0 };
    static const double py[] = { -1.0, -0.15, -0.75, 0.0, 0.85, 0.05, 1.0 };
    const int n = 7;
    int i = 0;
    double t, p0, p1, p2, p3, m1, m2, h;
    while (i < n - 2 && x > px[i + 1]) i++;
    h = px[i + 1] - px[i];
    t = (x - px[i]) / h;
    p1 = py[i]; p2 = py[i + 1];
    p0 = i > 0 ? py[i - 1] : p1;
    p3 = i + 2 < n ? py[i + 2] : p2;
    m1 = (p2 - p0) / (i > 0 ? px[i + 1] - px[i - 1] : h) * h;
    m2 = (p3 - p1) / (i + 2 < n ? px[i + 2] - px[i] : h) * h;
    return (2*t*t*t - 3*t*t + 1) * p1 + (t*t*t - 2*t*t + t) * m1 + (-2*t*t*t + 3*t*t) * p2 + (t*t*t - t*t) * m2;
}

float geiger_curve_exact(int c, float xf)
{
    double x = clampd(xf, -1.0, 1.0), a = fabs(x), s = x < 0 ? -1.0 : 1.0, y;
    switch (c) {
    case 0:  y = x; break;
    case 1:  y = 1.5 * x - 0.5 * x * x * x; break;
    case 2:  y = clampd(2.5 * x, -1.0, 1.0); break;
    case 3:  y = sin(1.5 * PI * x); break;
    case 4:  y = trifold(3.5 * x); break;
    case 5:  y = 2.0 * a - 1.0; break;
    case 6:  y = x > 0 ? x : 0.0; break;
    case 7:  y = floor(x * 4.0 + 0.5) / 4.0; break;
    case 8:  y = x > 0 ? tanh(3.0 * x) / tanh(3.0) : clampd(1.6 * x, -0.55, 0.0) / 0.55; break;
    case 9:  y = 4 * x * x * x - 3 * x; break;
    case 10: y = 16 * pow(x, 5) - 20 * x * x * x + 5 * x; break;
    case 11: y = sin(PI * x); break;
    case 12: y = s * sqrt(a); break;
    case 13: y = spline(x); break;
    case 14: y = x * cos(6.0 * PI * x); break;
    case 15: y = a < 0.15 ? 0.0 : s * (a - 0.15) / 0.85; break;
    default: y = x; break;
    }
    return (float)clampd(y, -1.0, 1.0);
}

static float TABLES[GEIGER_CURVES][GEIGER_TABLE + 1];
static int tables_built;

static void build_tables(void)                  /* read-only once built; same for every instance */
{
    int c, i;
    if (tables_built) return;
    for (c = 0; c < GEIGER_CURVES; c++)
        for (i = 0; i <= GEIGER_TABLE; i++)
            TABLES[c][i] = geiger_curve_exact(c, -1.0f + 2.0f * (float)i / GEIGER_TABLE);
    tables_built = 1;
}

const float *geiger_table(int c) { build_tables(); return TABLES[c < 0 ? 0 : c >= GEIGER_CURVES ? GEIGER_CURVES - 1 : c]; }

float geiger_curve(int c, float x)
{
    const float *t = geiger_table(c);
    float p, f;
    int i;
    if (x < -1.0f) x = -1.0f;
    if (x > 1.0f) x = 1.0f;
    p = (x + 1.0f) * (GEIGER_TABLE / 2);
    i = (int)p;
    if (i >= GEIGER_TABLE) i = GEIGER_TABLE - 1;
    f = p - (float)i;
    return t[i] + f * (t[i + 1] - t[i]);
}

float geiger_quantize(float x, int bits)
{
    float q;
    if (bits < 1) bits = 1;
    if (bits > 24) bits = 24;
    if (x < -1.0f) x = -1.0f;
    if (x > 1.0f) x = 1.0f;
    q = (float)(1L << (bits - 1));
    return floorf(x * q + 0.5f) * (1.0f / q);      /* mid-tread: 2^bits + 1 levels at most; 1/q exact */
}

/* ------------------------------------------------------------------ the effect */

float geiger_exp(float y)
{
    float z = y * 0.0625f, p;
    p = 1.0f / 720.0f;
    p = p * z + 1.0f / 120.0f;
    p = p * z + 1.0f / 24.0f;
    p = p * z + 1.0f / 6.0f;
    p = p * z + 0.5f;
    p = p * z + 1.0f;
    p = p * z + 1.0f;
    p = p * p;
    p = p * p;
    p = p * p;
    return p * p;
}

#define LN10_20 0.115129255f                       /* ln(10) / 20: dB -> exp argument */
#define LN100 4.60517019f                          /* ln(100) */

static float db(float v) { return geiger_exp(v * LN10_20); }

static void reset(void *st, float sr)
{
    GeigerState *s = st;
    memset(s, 0, sizeof *s);
    build_tables();
    s->sr = sr;
    s->dc_r = 1.0f - (float)(2 * PI * 10.0 / sr);
    s->smooth_k = (float)(1.0 - exp(-1.0 / (0.005 * sr)));
    s->inv_sr = (float)(1.0 / sr);
    s->neg_w = (float)(-2 * PI / sr);
    s->aa_rate = -1.0f;
    s->tone_val = -1.0f;
}

static float smooth(float cur, float target, float k)
{
    float d = target - cur;
    if (fabsf(d) < 1e-6f) return target;           /* settle exactly, so Mix 0 is exactly dry */
    return cur + k * d;
}

static void process(void *st, const FxParams *p, const float *in, float *out, size_t n)
{
    GeigerState *s = st;
    const FxParamDesc *d = PARAMS;
    float gain = db(fx_param_clamp(&d[G_GAIN], p->value[G_GAIN]));
    float rate = fx_param_clamp(&d[G_RATE], p->value[G_RATE]);
    int bits = (int)fx_param_clamp(&d[G_BITS], p->value[G_BITS]);
    int curve = (int)fx_param_clamp(&d[G_CURVE], p->value[G_CURVE]);
    float tone = fx_param_clamp(&d[G_TONE], p->value[G_TONE]);
    float outg = db(fx_param_clamp(&d[G_OUTPUT], p->value[G_OUTPUT]));
    float mix = fx_param_clamp(&d[G_MIX], p->value[G_MIX]);
    int aa = (int)fx_param_clamp(&d[G_AA], p->value[G_AA]);
    float inc, k = s->smooth_k;
    size_t i;

    if (rate > s->sr) rate = s->sr;
    inc = rate * s->inv_sr;
    if (rate != s->aa_rate) {                      /* coefficients only when a knob moves */
        float fc = 0.4f * rate;
        s->aa_a = 1.0f - geiger_exp(fc * s->neg_w);
        s->aa_rate = rate;
    }
    if (tone != s->tone_val) {
        float fc = 200.0f * geiger_exp(tone * LN100);   /* 200 Hz .. 20 kHz */
        float top = 0.45f * s->sr;
        if (fc > top) fc = top;
        s->tone_a = 1.0f - geiger_exp(fc * s->neg_w);
        s->tone_val = tone;
    }
    if (!s->primed) {
        s->g_gain = gain; s->g_out = outg; s->g_mix = mix;
        s->primed = 1;
    }

    for (i = 0; i < n; i++) {
        float x = in[i], y, wet;
        if (!isfinite(x)) x = 0.0f;

        s->g_gain = smooth(s->g_gain, gain, k);
        s->g_out = smooth(s->g_out, outg, k);
        s->g_mix = smooth(s->g_mix, mix, k);

        y = x - s->dcin_x1 + s->dc_r * s->dcin_y1;     /* DC block */
        s->dcin_x1 = x; s->dcin_y1 = y;
        y *= s->g_gain;

        if (aa && inc < 1.0f) {                         /* band-limit before decimating */
            s->aa1 += s->aa_a * (y - s->aa1);
            s->aa2 += s->aa_a * (s->aa1 - s->aa2);
            y = s->aa2;
        }
        s->phase += inc;                                /* sample-and-hold at Rate */
        if (s->phase >= 1.0f) {
            s->phase -= 1.0f;
            s->held = y;
        }
        y = geiger_quantize(s->held, bits);
        y = geiger_curve(curve, y);

        s->tone_z += s->tone_a * (y - s->tone_z);
        y = s->tone_z;
        wet = y - s->dcout_x1 + s->dc_r * s->dcout_y1;  /* the rectifying curves add DC */
        s->dcout_x1 = y; s->dcout_y1 = wet;
        wet *= s->g_out;

        y = x * (1.0f - s->g_mix) + wet * s->g_mix;
        if (!isfinite(y) || fabsf(y) > 8.0f) {          /* never pass on a bad value: */
            s->dcin_x1 = s->dcin_y1 = s->dcout_x1 = s->dcout_y1 = 0.0f;   /* clear the filters */
            s->aa1 = s->aa2 = s->held = s->tone_z = 0.0f;
            y = 0.0f;
        }
        out[i] = y;
    }
}

const FxAlgorithm fx_geiger = {
    "geiger", "Geiger", sizeof(GeigerState), PARAMS, G_NPARAMS, reset, process,
};
