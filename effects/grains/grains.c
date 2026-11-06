#include "grains.h"

#include <math.h>
#include <string.h>

static const FxParamDesc PARAMS[N_NPARAMS] = {
    { "size",     "Size",     FX_INTEGER,    0.0f, 7.0f, 4.0f, "10, 20, 30, 50, 80, 120, 160, 200 ms", "immediate" },
    { "density",  "Density",  FX_INTEGER,    1.0f, 4.0f, 3.0f, "grains at once", "immediate" },
    { "pitch",    "Pitch",    FX_INTEGER,    0.0f, 6.0f, 3.0f, "-12, -7, -5, 0, +5, +7, +12 semitones", "immediate" },
    { "spray",    "Spray",    FX_CONTINUOUS, 0.0f, 1.0f, 0.3f, "up to 0.5 s", "immediate" },
    { "scatter",  "Scatter",  FX_CONTINUOUS, 0.0f, 1.0f, 0.1f, "probability", "immediate" },
    { "reverse",  "Reverse",  FX_CONTINUOUS, 0.0f, 1.0f, 0.2f, "probability", "immediate" },
    { "feedback", "Feedback", FX_CONTINUOUS, 0.0f, 0.9f, 0.3f, "", "immediate" },
    { "mix",      "Mix",      FX_CONTINUOUS, 0.0f, 1.0f, 0.5f, "x (shown as %)", "immediate" },
};

const int GRAINS_LEN[GRAINS_SIZES] = { 480, 960, 1440, 2400, 3840, 5760, 7680, 9600 };
const float GRAINS_INV[GRAINS_SIZES] = { 1.0f / 480, 1.0f / 960, 1.0f / 1440, 1.0f / 2400,
                                         1.0f / 3840, 1.0f / 5760, 1.0f / 7680, 1.0f / 9600 };
const float GRAINS_SPEED[GRAINS_PITCHES] = { 0.5f, 0.667419927f, 0.749153538f, 1.0f, 1.33483985f, 1.49830708f, 2.0f };
const float GRAINS_NORM[GRAINS_VOICES + 1] = { 0.0f, 1.5f, 0.75f, 0.5f, 0.375f };
const float GRAINS_STAGGER[GRAINS_VOICES + 1] = { 0.0f, 1.0f, 0.5f, 1.0f / 3, 0.25f };

#define M (GRAINS_RING - 1)
#define K_2M24 (1.0f / 16777216.0f)

static void reset(void *st, float sr)
{
    GrainsState *s = st;
    (void)sr;
    memset(s, 0, sizeof *s);
    s->rnd = GRAINS_SEED;
}

static unsigned next(GrainsState *s)
{
    s->rnd ^= s->rnd << 13;
    s->rnd ^= s->rnd >> 17;
    s->rnd ^= s->rnd << 5;
    return s->rnd >> 8;
}

static void process(void *st, const FxParams *p, const float *in, float *out, size_t n)
{
    GrainsState *s = st;
    const FxParamDesc *d = PARAMS;
    int size = (int)fx_param_clamp(&d[N_SIZE], p->value[N_SIZE]);
    int dens = (int)fx_param_clamp(&d[N_DENSITY], p->value[N_DENSITY]);
    float speed = GRAINS_SPEED[(int)fx_param_clamp(&d[N_PITCH], p->value[N_PITCH])];
    float spray = fx_param_clamp(&d[N_SPRAY], p->value[N_SPRAY]) * (float)GRAINS_SPRAY;
    unsigned thr_sc = (unsigned)(fx_param_clamp(&d[N_SCATTER], p->value[N_SCATTER]) * 16777216.0f);
    unsigned thr_rev = (unsigned)(fx_param_clamp(&d[N_REVERSE], p->value[N_REVERSE]) * 16777216.0f);
    float fb = fx_param_clamp(&d[N_FEEDBACK], p->value[N_FEEDBACK]);
    float mix = fx_param_clamp(&d[N_MIX], p->value[N_MIX]);
    int len = GRAINS_LEN[size], k;
    size_t i;

    if (!s->started) {                                 /* stagger the voices across a grain */
        for (k = 0; k < GRAINS_VOICES; k++)
            s->v[k].wait = (int)((float)(k * len) * GRAINS_STAGGER[dens]);
        s->started = 1;
    }

    for (i = 0; i < n; i++) {
        float x = in[i], wet = 0.0f, y, c;
        if (!isfinite(x)) x = 0.0f;

        for (k = 0; k < GRAINS_VOICES; k++) {
            GrainVoice *v = &s->v[k];
            if (v->active) {
                float t = (float)v->n * v->inv, win = 4.0f * t * (1.0f - t), f, a, b;
                int j = (int)v->pos;
                f = v->pos - (float)j;
                if (v->dir > 0) {
                    a = s->ring[(v->start + j) & M];
                    b = s->ring[(v->start + j + 1) & M];
                } else {
                    a = s->ring[(v->start - j) & M];
                    b = s->ring[(v->start - j - 1) & M];
                }
                wet += (a + f * (b - a)) * win;
                v->pos += v->speed;
                v->n++;
                if (v->n >= v->len) v->active = 0;
            } else if (k < dens) {
                if (v->wait > 0) {
                    v->wait--;
                } else {                               /* a new grain */
                    float sp = speed;
                    int lsp, off, delay, need;
                    if (next(s) < thr_sc) sp = (next(s) >> 23) ? sp * 2.0f : sp * 0.5f;
                    v->dir = next(s) < thr_rev ? -1 : 1;
                    off = (int)((float)next(s) * K_2M24 * spray);
                    lsp = (int)((float)len * sp) + 1;
                    delay = v->dir > 0 ? lsp + 1 + off : 2 + off;
                    need = v->dir > 0 ? delay : delay + lsp;
                    if (need > s->filled) {
                        v->wait = len;                 /* not enough recorded yet: a silent grain */
                    } else {
                        v->start = (s->w - delay) & M;
                        v->pos = 0.0f;
                        v->n = 0;
                        v->len = len;
                        v->inv = GRAINS_INV[size];
                        v->speed = sp;
                        v->active = 1;
                    }
                }
            }
        }

        wet = wet * GRAINS_NORM[dens];
        c = wet;
        if (c > 1.0f) c = 1.0f;
        if (c < -1.0f) c = -1.0f;
        s->ring[s->w] = x + fb * c;                    /* record, with the grains fed back */
        s->w = (s->w + 1) & M;
        if (s->filled < GRAINS_RING) s->filled++;

        y = x * (1.0f - mix) + wet * mix;
        if (!(fabsf(y) <= 8.0f)) y = 0.0f;
        out[i] = y;
    }
}

const FxAlgorithm fx_grains = {
    "grains", "Grains", sizeof(GrainsState), PARAMS, N_NPARAMS, reset, process,
};
