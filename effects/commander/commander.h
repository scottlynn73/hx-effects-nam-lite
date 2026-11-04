/* commander.h - "Commander": a square-wave octave fuzz. An original algorithm in the spirit of
 * comparator/divider octave fuzz pedals; no vendor circuit or tables.
 *
 * Signal path (per sample):
 *   in -> DC block -> two one-pole lowpasses (300 Hz: the tracking signal t)
 *      -> envelope follower (instant attack, 50 ms release)
 *      -> Schmitt comparator on t (hysteresis 50 % of the envelope): the square, at the note
 *      -> divide by two on each rising edge (-1 octave), and again (-2 octaves)
 *      -> |t| above half the envelope: a square at twice the note (+1 octave)
 *      -> mix of the four squares x the envelope (x4, at most 1: the fuzz follows the playing)
 *      -> x the gate (smoothed, opens above the Gate threshold) -> tone (two one-pole lowpasses)
 *      -> output gain, plus the dry input at Dry -> out
 *
 * Eight parameters, to fit the host model's knob words. Written so the SHARC port matches it bit for
 * bit: no division, the only transcendental is geiger_exp, constants rounded once from double, and
 * the build uses -ffp-contract=off.
 */
#ifndef COMMANDER_H
#define COMMANDER_H

#include "../common/fx.h"

enum { C_FUZZ, C_SUB1, C_SUB2, C_UP, C_TONE, C_GATE, C_DRY, C_OUTPUT, C_NPARAMS };
enum { CG_FUZZ, CG_SUB1, CG_SUB2, CG_UP, CG_DRY, CG_OUT, CG_N };     /* the smoothed gains */

#define COMMANDER_GATE_STEPS 10        /* Gate: 0 Off, k = 1..10 -> -90 + 6k dB (-84 .. -30 dB) */
#define COMMANDER_DRY_STEPS 10         /* Dry: k = 0..10 -> k x 10 % */

typedef struct {
    float dc_r, smooth_k, lp_a, rel, neg_w, top;        /* constants */
    float dcx, dcy, lp1, lp2, env;
    float sq, d1, d2;                                   /* the squares, +-1 */
    float t1, t2;                                       /* tone */
    float g[CG_N], ggate;
    int primed;
} CommanderState;

extern const FxAlgorithm fx_commander;

/* Exposed for the tests and the SHARC port: the gate threshold (linear) for list position k. */
float commander_gate(int k);

#endif
