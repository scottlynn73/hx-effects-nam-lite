#include "stutter.h"
#include "../geiger/geiger.h"                 /* geiger_exp */

#include <math.h>
#include <string.h>

static const FxParamDesc PARAMS[U_NPARAMS] = {
    { "trigger", "Trigger",  FX_INTEGER,    0.0f, 2.0f,  0.0f,  "0 Clock, 1 Transient, 2 Both", "immediate" },
    { "rate",    "Rate",     FX_CONTINUOUS, 0.5f, 16.0f, 2.0f,  "Hz", "immediate" },
    { "chance",  "Chance",   FX_CONTINUOUS, 0.0f, 1.0f,  0.5f,  "probability", "immediate" },
    { "length",  "Length",   FX_CONTINUOUS, 0.0f, 1.0f,  0.5f,  "20 .. 500 ms", "immediate" },
    { "repeats", "Repeats",  FX_INTEGER,    1.0f, 16.0f, 4.0f,  "", "immediate" },
    { "speed",   "Speed",    FX_INTEGER,    0.0f, 5.0f,  0.0f,  "1x, 2x, 0.5x, Rev, Rev 2x, Random", "immediate" },
    { "random",  "Random",   FX_CONTINUOUS, 0.0f, 1.0f,  0.0f,  "", "immediate" },
    { "mix",     "Mix",      FX_CONTINUOUS, 0.0f, 1.0f,  1.0f,  "x (shown as %)", "immediate" },
};

static const float SPEEDS[5] = { 1.0f, 2.0f, 0.5f, -1.0f, -2.0f };
static const float RSPEEDS[8] = { 1.0f, 2.0f, 0.5f, -1.0f, -2.0f, 1.0f, -0.5f, 0.5f };

float stutter_speed(int k) { return SPEEDS[k < 0 ? 0 : k > 4 ? 4 : k]; }
float stutter_random_speed(int k) { return RSPEEDS[k & 7]; }

#define LN25 3.21887582f                       /* Length 0..1 -> 20 .. 500 ms */
#define K_FLOOR 0.02f                          /* the transient detector's floor */
#define K_FADE (1.0f / STUTTER_FADE)
#define K_XF (1.0f / STUTTER_XFADE)
#define K_2M24 (1.0f / 16777216.0f)

static void reset(void *st, float sr)
{
    StutterState *s = st;
    memset(s, 0, sizeof *s);
    s->smooth_r = (float)exp(-1.0 / (0.005 * sr));       /* the fast envelope's release */
    s->slow_k = (float)(1.0 - exp(-1.0 / (0.05 * sr)));   /* the slow envelope */
    s->rnd = STUTTER_SEED;
}

static unsigned next(StutterState *s)
{
    s->rnd ^= s->rnd << 13;
    s->rnd ^= s->rnd >> 17;
    s->rnd ^= s->rnd << 5;
    return s->rnd >> 8;
}

static void process(void *st, const FxParams *p, const float *in, float *out, size_t n)
{
    StutterState *s = st;
    const FxParamDesc *d = PARAMS;
    int trig = (int)fx_param_clamp(&d[U_TRIGGER], p->value[U_TRIGGER]);
    float cinc = fx_param_clamp(&d[U_RATE], p->value[U_RATE]) * (1.0f / FX_DEVICE_RATE);
    unsigned thr = (unsigned)(fx_param_clamp(&d[U_CHANCE], p->value[U_CHANCE]) * 16777216.0f);
    float lenf = 960.0f * geiger_exp(fx_param_clamp(&d[U_LENGTH], p->value[U_LENGTH]) * LN25);
    int repeats = (int)fx_param_clamp(&d[U_REPEATS], p->value[U_REPEATS]);
    int speed = (int)fx_param_clamp(&d[U_SPEED], p->value[U_SPEED]);
    float rnd3 = fx_param_clamp(&d[U_RANDOM], p->value[U_RANDOM]) * 3.0f;
    float mix = fx_param_clamp(&d[U_MIX], p->value[U_MIX]);
    int base = (int)lenf;
    size_t i;

    for (i = 0; i < n; i++) {
        float x = in[i], a, y, wet = 0.0f;
        int fire = 0;
        if (!isfinite(x)) x = 0.0f;

        a = fabsf(x);                                    /* the transient detector */
        s->envf = a > s->envf ? a : s->envf * s->smooth_r;
        s->envs += s->slow_k * (a - s->envs);
        if (s->hold > 0) s->hold--;
        if (trig != 0 && s->hold == 0 && s->envf > 2.0f * s->envs + K_FLOOR) {
            s->hold = STUTTER_HOLD;
            fire = 1;
        }
        s->cphase += cinc;                               /* the clock */
        if (s->cphase >= 1.0f) {
            s->cphase -= 1.0f;
            if (trig != 1) fire = 1;
        }
        if (fire && next(s) < thr) {                     /* a stutter (or a retrigger) */
            int len = base, k = (int)((float)next(s) * K_2M24 * rnd3);
            len >>= k;
            if (len < STUTTER_LMIN) len = STUTTER_LMIN;
            if (len > STUTTER_LMAX) len = STUTTER_LMAX;
            if (len > s->filled) len = s->filled;        /* only what has been recorded */
            if (len >= STUTTER_LMIN) {
                s->speed = speed == 5 ? stutter_random_speed((int)(next(s) >> 21)) : SPEEDS[speed];
                s->len = len;
                s->start = (s->w - len) & (STUTTER_RING - 1);
                s->pos = s->speed > 0.0f ? 0.0f : (float)(len - 1);
                s->left = repeats;
                s->playing = 1;
            }
        }

        if (s->playing) {                                /* play the slice */
            int j = (int)s->pos, b0, b1;
            float f = s->pos - (float)j, v0, v1, e;
            b0 = (s->start + j) & (STUTTER_RING - 1);
            b1 = j + 1 < s->len ? (b0 + 1) & (STUTTER_RING - 1) : b0;   /* never past the slice */
            v0 = s->ring[b0];
            v1 = s->ring[b1];
            wet = v0 + f * (v1 - v0);
            e = (float)(s->len - 1) - s->pos;            /* the fades at both ends */
            if (s->pos < e) e = s->pos;
            e = e * K_FADE;
            if (e < 1.0f) wet = wet * e;
            s->pos += s->speed;
            if (s->pos >= (float)s->len - 1.0f) {
                s->pos -= (float)(s->len - 1);
                s->left--;
            } else if (s->pos < 0.0f) {
                s->pos += (float)(s->len - 1);
                s->left--;
            }
            if (s->left <= 0) s->playing = 0;
            s->amt += K_XF;
            if (s->amt > 1.0f) s->amt = 1.0f;
        } else {
            s->ring[s->w] = x;                           /* record */
            s->w = (s->w + 1) & (STUTTER_RING - 1);
            if (s->filled < STUTTER_RING) s->filled++;
            s->amt -= K_XF;
            if (s->amt < 0.0f) s->amt = 0.0f;
        }

        a = mix * s->amt;
        y = x * (1.0f - a) + wet * a;
        if (!(fabsf(y) <= 8.0f)) y = 0.0f;              /* never pass on a bad value */
        out[i] = y;
    }
}

const FxAlgorithm fx_stutter = {
    "stutter", "Stutter", sizeof(StutterState), PARAMS, U_NPARAMS, reset, process,
};
