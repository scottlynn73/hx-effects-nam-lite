/* sequence.h - "Sequence": a pitch-tracking arpeggiator synth. An original algorithm in the spirit of
 * tracking sequencer pedals; no vendor code, tables or patterns.
 *
 * Signal path (per sample):
 *   in -> DC block -> two one-pole lowpasses (300 Hz: the tracking signal t) -> envelope (instant attack,
 *      50 ms release) -> Schmitt comparator on t (hysteresis half the envelope plus a floor); the period P
 *      between its rising edges, when 16 <= P <= 2400, sets the note: (2^24 / P, an exact integer quotient)
 *      x 2^-24 cycles a sample
 *   the sequencer: eight steps at Speed; the step's interval (Pattern 0 Off: unison; 1..8 arpeggios of
 *      -12 .. +24 semitones, a table of 2^(k/12) rounded once) x Octave (x 1/4 .. x 2) x the note is the
 *      oscillator's target rate, at most 0.45; the rate glides toward it (Glide 0 instant .. 1 slow)
 *   the oscillator: a phase accumulator, Wave square, saw, triangle or 25 % pulse
 *      x the envelope (x 4, at most 1) x a gate at -66 dB (smoothed)
 *   -> tone (two one-pole lowpasses) -> DC block -> output gain -> mix with the dry input -> out
 *
 * Eight parameters, to fit the host model's knob words. Bit-exact on the SHARC port: no float division,
 * geiger_exp the only transcendental, constants and tables rounded once.
 */
#ifndef SEQUENCE_H
#define SEQUENCE_H

#include "../common/fx.h"

enum { Q_PATTERN, Q_SPEED, Q_WAVE, Q_OCTAVE, Q_GLIDE, Q_TONE, Q_OUTPUT, Q_MIX, Q_NPARAMS };

#define SEQUENCE_STEPS 8
#define SEQUENCE_PATTERNS 9                /* 0 = Off, 1..8 */
#define SEQUENCE_PMIN 16
#define SEQUENCE_PMAX 2400
#define SEQUENCE_CNT_MAX 4096

typedef struct {
    float dc_r, smooth_k, lp_a, rel, neg_w, top;       /* constants */
    float dcx, dcy, lp1, lp2, env, sq;
    int cnt;
    float base, inc, ph;                               /* the note (cycles a sample), the oscillator */
    float sphase;
    int step;
    float t1, t2, ox, oy;
    float g_out, g_mix, ggate;
    int primed;
} SequenceState;

extern const FxAlgorithm fx_sequence;

/* Exposed for the tests and the SHARC port: the step's frequency ratio (pattern p, step k), the octave
   multipliers. */
float sequence_ratio(int p, int k);
extern const float SEQUENCE_OCTAVE[4];

#endif
