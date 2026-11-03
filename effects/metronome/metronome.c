#include "metronome.h"

#include <math.h>
#include <string.h>

#define PI 3.14159265358979323846

static const FxParamDesc PARAMS[M_NPARAMS] = {
    { "tempo",  "Tempo",       FX_CONTINUOUS, 20.0f, 300.0f, 120.0f, "BPM", "immediate (0.01 BPM steps)" },
    { "meter",  "Beats/Bar",   FX_INTEGER,    2.0f,  5.0f,   4.0f,   "beats", "immediate" },
    { "accent", "Accent",      FX_INTEGER,    0.0f,  12.0f,  6.0f,   "dB", "immediate" },
    { "sound",  "Sound",       FX_INTEGER,    0.0f,  2.0f,   0.0f,   "", "immediate" },
    { "level",  "Level",       FX_CONTINUOUS, 0.0f,  1.0f,   0.5f,   "x (shown as %)", "immediate" },
    { "subdiv", "Subdivision", FX_INTEGER,    1.0f,  4.0f,   1.0f,   "per beat", "immediate" },
};

/* Pitches (Hz) per sound and click kind: accent, beat, subdivision. Original choices. */
const float click_pitch[SOUNDS][CLICK_KINDS] = {
    { 1760.0f, 1320.0f, 990.0f },     /* click: a short sine ping */
    { 1150.0f, 880.0f, 660.0f },      /* wood: two inharmonic partials, a little longer */
    { 1760.0f, 1320.0f, 990.0f },     /* beep: a gated tone */
};
const float click_sub_gain = 0.4f;
#define SUB_GAIN click_sub_gain                  /* subdivisions sit about 8 dB under the beat */
const float click_wood_ratio = 2.71f, click_wood_mix = 0.45f;
#define WOOD_RATIO click_wood_ratio
#define WOOD_MIX click_wood_mix
static const float TAU_CLICK = 0.003f, TAU_WOOD = 0.012f;   /* decay time constants, s */
static const float BEEP_GATE = 0.040f, BEEP_RELEASE = 0.005f;
static const float MAX_VOICE = 0.2f;                 /* no voice outlives this, whatever happens */
/* Everything below is arranged so a SHARC port can match it bit for bit: constants are computed
   in double and rounded once to float (the port's tables are made the same way), there is no
   division or transcendental function per sample or per tick, and the build turns off fused
   multiply-add (-ffp-contract=off), which the SHARC does not do. */
const float click_silent = 1e-4f;
#define SILENT click_silent                   /* -80 dB: the voice stops */

static void rotor(Rotor *r, float hz, float sr)
{
    double w = 2 * PI * hz / sr;
    r->c = 1.0f; r->s = 0.0f;
    r->wc = (float)cos(w); r->ws = (float)sin(w);
}

static float rotor_step(Rotor *r)                    /* returns sin(n w), then advances */
{
    float s = r->s, c = r->c;
    r->c = c * r->wc - s * r->ws;
    r->s = s * r->wc + c * r->ws;
    return s;
}

static void reset(void *st, float sr)
{
    MetronomeState *m = st;
    memset(m, 0, sizeof *m);
    m->sr = sr;
    m->period = (uint32_t)(sr * 6000.0f + 0.5f);     /* sr x 60 s x 100 */
    m->fire_now = 1;                                  /* beat 1 on the first sample */
    m->decay_k[0] = (float)exp(-1.0 / ((double)TAU_CLICK * sr));
    m->decay_k[1] = (float)exp(-1.0 / ((double)TAU_WOOD * sr));
    m->gate = (uint32_t)(BEEP_GATE * sr);
    m->rel_step = (float)(1.0 / (double)(uint32_t)(BEEP_RELEASE * sr));
    m->max_age = (uint32_t)(MAX_VOICE * sr);
    m->last_kind = -1;
}

static void trigger(MetronomeState *m, int kind, int sound, float level, float accent_gain)
{
    float a = level;
    int pitch_kind = kind;
    if (kind == CLICK_ACCENT) {
        if (accent_gain <= 1.0f) pitch_kind = CLICK_BEAT;   /* Accent 0 dB: no accent at all */
        a *= accent_gain;
    } else if (kind == CLICK_SUB) {
        a *= SUB_GAIN;
    }
    if (a > 1.0f) a = 1.0f;
    m->active = a > 0.0f;
    m->kind = kind;
    m->sound = sound;
    m->amp = a;
    m->env = 1.0f;
    m->age = 0;
    rotor(&m->osc[0], click_pitch[sound][pitch_kind], m->sr);
    rotor(&m->osc[1], click_pitch[sound][pitch_kind] * WOOD_RATIO, m->sr);
    m->mix2 = sound == SOUND_WOOD ? WOOD_MIX : 0.0f;
    m->decay = sound == SOUND_BEEP ? 1.0f : m->decay_k[sound == SOUND_WOOD];
}

static float voice(MetronomeState *m)
{
    float y = rotor_step(&m->osc[0]);
    if (m->mix2 != 0.0f) {
        float y2 = rotor_step(&m->osc[1]);
        y = (1.0f - m->mix2) * y + m->mix2 * y2;
    }
    y = y * (m->amp * m->env);
    if (y > m->amp) y = m->amp;                      /* the rotor's rounding can overshoot by ~1e-5 */
    if (y < -m->amp) y = -m->amp;
    m->age++;
    if (m->sound == SOUND_BEEP) {
        if (m->age > m->gate)
            m->env = m->env - m->rel_step;               /* a straight line to 0 over BEEP_RELEASE */
    } else {
        m->env *= m->decay;
    }
    if (m->env < SILENT || m->age > m->max_age)
        m->active = 0;
    return y;
}

static void process(void *st, const FxParams *p, const float *in, float *out, size_t n)
{
    MetronomeState *m = st;
    const FxParamDesc *d = PARAMS;
    float tempo = fx_param_clamp(&d[M_TEMPO], p->value[M_TEMPO]);
    int meter = (int)fx_param_clamp(&d[M_METER], p->value[M_METER]);
    float accent = (float)pow(10.0, (double)fx_param_clamp(&d[M_ACCENT], p->value[M_ACCENT]) / 20.0);
    int sound = (int)fx_param_clamp(&d[M_SOUND], p->value[M_SOUND]);
    float level = fx_param_clamp(&d[M_LEVEL], p->value[M_LEVEL]);   /* 0..1, as HX Mix/level knobs */
    int sub = (int)fx_param_clamp(&d[M_SUBDIV], p->value[M_SUBDIV]);
    uint32_t inc = (uint32_t)(tempo * 100.0f + 0.5f) * (uint32_t)sub;
    size_t i;

    for (i = 0; i < n; i++) {
        int tick = 0;
        float x = in[i];
        if (m->fire_now) {
            m->fire_now = 0;
            tick = 1;
        } else {
            m->acc += inc;
            if (m->acc >= m->period) {
                m->acc -= m->period;
                tick = 1;
            }
        }
        if (tick) {
            int kind;
            if (m->sub_idx >= sub) { m->sub_idx = 0; m->beat++; }    /* Subdivision or */
            if (m->beat >= meter) m->beat = 0;                       /* Beats/Bar turned down */
            kind = m->sub_idx ? CLICK_SUB : m->beat ? CLICK_BEAT : CLICK_ACCENT;
            trigger(m, kind, sound, level, accent);
            m->last_kind = kind;
            m->ticks++;
            if (++m->sub_idx >= sub) {
                m->sub_idx = 0;
                if (++m->beat >= meter) m->beat = 0;
            }
        }
        /* The click is finite and |c| <= 1 by construction; the guitar is never altered
           (a non-finite input passes through as it came: it is not this block's). */
        out[i] = m->active ? x + voice(m) : x;
    }
}

const FxAlgorithm fx_metronome = {
    "metronome", "Click", sizeof(MetronomeState), PARAMS, M_NPARAMS, reset, process,
};
