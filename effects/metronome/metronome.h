/* metronome.h - "Click": a metronome as an ordinary preset block (not a global service).
 *
 * The guitar passes through at exactly unity; a synthesised click is added on each beat.
 *
 * Timing is exact rational arithmetic, so there is no long-term drift: tempo is held in
 * hundredths of a BPM, an integer accumulator gains (BPM x 100 x subdivision) per sample,
 * and a tick fires when it reaches sample_rate x 60 x 100. Tick k therefore lands on sample
 * ceil(k x T / inc), the nearest sample at or after its ideal time, forever.
 *
 * Bar position: tick 0 (the first sample after reset) is beat 1 of the bar, accented.
 * Reset = restart at beat 1; whether the unit resets a block on enable is not known yet
 * (docs/baseline-audit.md), so on hardware the block may resume instead.
 *
 * Six parameters (the host model has eight knob words).
 */
#ifndef METRONOME_H
#define METRONOME_H

#include "../common/fx.h"

enum { M_TEMPO, M_METER, M_ACCENT, M_SOUND, M_LEVEL, M_SUBDIV, M_NPARAMS };
enum { CLICK_ACCENT, CLICK_BEAT, CLICK_SUB, CLICK_KINDS };
enum { SOUND_CLICK, SOUND_WOOD, SOUND_BEEP, SOUNDS };

typedef struct {
    float c, s, wc, ws;                  /* quadrature oscillator: (c, s) rotated by angle w */
} Rotor;

typedef struct {
    float sr;
    uint32_t period;                     /* T = sr x 60 x 100 */
    uint32_t acc;                        /* tempo phase, 0 .. T-1 */
    int fire_now;                        /* a tick is due at the next sample (set by reset) */
    int sub_idx, beat;                   /* position of the next tick in the bar */
    /* the voice */
    int active, kind, sound;
    Rotor osc[2];                        /* two partials */
    float amp, env, decay, mix2;         /* amplitude, envelope, per-sample decay, 2nd partial */
    uint32_t age, gate, release;         /* samples since the tick; beep's gate and release */
    /* bookkeeping the tests read */
    uint32_t ticks;
    int last_kind;
} MetronomeState;

extern const FxAlgorithm fx_metronome;

#endif
