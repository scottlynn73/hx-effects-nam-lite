/* ottobit.h - "Ottobit": a sequenced bit crusher with a resonant filter and short stutters. An original
 * algorithm in the spirit of sequenced crusher pedals; no vendor circuit, tables or patterns.
 *
 * Signal path (per sample):
 *   in -> DC block -> stutter (a ring buffer: while a step stutters it loops the last quarter step
 *         of input instead of passing it) -> sample-and-hold at Rate x the step's rate multiplier
 *      -> quantise to Bits -> resonant lowpass (Chamberlin state-variable, Q 2) at Filter x the step's
 *         filter multiplier -> DC block -> output gain -> mix with the dry input -> out
 *
 * The sequencer: six steps at Speed steps a second. Pattern 0 is Off (every multiplier 1); patterns 1..8
 * set each step's rate and filter multipliers, powers of two (exact). At each step a seeded xorshift32 decides,
 * with probability Stutter, whether that step stutters; a stutter loops the last (previous step's length
 * / 4) samples, 64 .. OTTOBIT_BUF, and ends at the next step.
 *
 * Eight parameters, to fit the host model's knob words. Bit-exact on the SHARC port: no division, the
 * transcendentals are geiger_exp and an odd polynomial for sin, constants rounded once.
 */
#ifndef OTTOBIT_H
#define OTTOBIT_H

#include "../common/fx.h"

enum { O_RATE, O_BITS, O_FILTER, O_PATTERN, O_SPEED, O_STUTTER, O_OUTPUT, O_MIX, O_NPARAMS };

#define OTTOBIT_STEPS 6
#define OTTOBIT_PATTERNS 9              /* 0 = Off, 1..8 */
#define OTTOBIT_BUF 2048                /* the stutter ring, samples (a power of two) */
#define OTTOBIT_LMIN 64
#define OTTOBIT_SEED 0x12345678u

typedef struct {
    float dc_r, smooth_k, inv_sr, pi_sr;               /* constants: 1 / sr, pi / sr */
    float dcx, dcy, ox, oy;                            /* input and output DC blocks */
    float phase, held;                                 /* sample-and-hold */
    float low, band;                                   /* the filter */
    float sphase;                                      /* the sequencer */
    int step, cnt, prev_cnt;
    unsigned rnd;
    int stut, len, j, w, start;                        /* the stutter */
    float g_out, g_mix;
    int primed;
    float buf[OTTOBIT_BUF];
} OttobitState;

extern const FxAlgorithm fx_ottobit;

/* Exposed for the tests and the SHARC port. */
const float *ottobit_pattern(int p);    /* OTTOBIT_STEPS x {rate multiplier, filter multiplier} */
float ottobit_sin(float x);             /* sin(x) for |x| <= 0.53: x (1 - x^2/6 + x^4/120 - x^6/5040), Horner */

#endif
