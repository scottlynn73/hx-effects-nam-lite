/* corrupt.h - "Corrupt": a monophonic pitch-tracking square synth. An original algorithm in the spirit
 * of PLL-style synth pedals; no vendor circuit or tables.
 *
 * Signal path (per sample):
 *   in -> DC block -> two one-pole lowpasses (300 Hz: the tracking signal t)
 *      -> envelope follower (instant attack, 50 ms release)
 *      -> Schmitt comparator on t: the input's square (the Square voice)
 *      -> the period P in samples between its rising edges; when 16 <= P <= 2400 (20 Hz .. 3 kHz)
 *         the oscillator's target rate becomes Harmonic x 2^(Root - 2) / P cycles a sample, as the exact
 *         integer quotient (Harmonic << (22 + Root)) / P scaled by 2^-24, at most 0.5
 *      -> Glide: the rate follows its target, one-pole (instant .. very slow)
 *      -> a phase accumulator: a square at that rate (the Master voice) and, toggled on each of its
 *         cycles, a square an octave below it (the Sub voice)
 *      -> mix x the envelope (x4, at most 1) x a gate at -66 dB (smoothed)
 *      -> tone (two one-pole lowpasses) -> DC block -> output gain -> out
 *
 * Eight parameters, to fit the host model's knob words. Bit-exact on the SHARC port: no float division
 * (the quotient is integer arithmetic), geiger_exp the only transcendental, constants rounded once.
 */
#ifndef CORRUPT_H
#define CORRUPT_H

#include "../common/fx.h"

enum { R_SQUARE, R_MASTER, R_SUB, R_GLIDE, R_TONE, R_OUTPUT, R_ROOT, R_HARM, R_NPARAMS };
enum { RG_SQUARE, RG_MASTER, RG_SUB, RG_OUT, RG_N };     /* the smoothed gains */

#define CORRUPT_PMIN 16                /* periods accepted, in samples */
#define CORRUPT_PMAX 2400
#define CORRUPT_CNT_MAX 4096           /* the period counter stops here */
#define CORRUPT_QMAX 0x800000u         /* the rate, x 2^24: at most half the sample rate */

typedef struct {
    float dc_r, smooth_k, lp_a, rel, neg_w, top;        /* constants */
    float dcx, dcy, lp1, lp2, env, sq;
    int cnt;                                            /* samples since the last rising edge */
    float inc_t, inc, ph, sub;                          /* the oscillator */
    float t1, t2, ox, oy;                               /* tone, output DC block */
    float g[RG_N], ggate;
    int primed;
} CorruptState;

extern const FxAlgorithm fx_corrupt;

#endif
