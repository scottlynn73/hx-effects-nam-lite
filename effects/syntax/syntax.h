/* syntax.h - "Syntax": drive into a sequenced single-sideband frequency shifter, for metallic, inharmonic
 * tones. An original algorithm in the spirit of glitchy frequency-shift distortions; no vendor code.
 *
 * Signal path (per sample):
 *   in -> DC block -> drive -> soft clip (1.5 x - 0.5 x^3 on [-1, 1])
 *      -> Hilbert pair (two chains of four second-order allpasses, path A a sample later)
 *      -> single-sideband shift: A cos + B sin (the other sideband about 49 dB down at 1 kHz), the
 *         quadrature oscillator a rotating phasor renormalised every sample, at the shift frequency
 *      -> tone (one-pole lowpass) -> output gain -> mix with the dry input -> out
 *   The shift frequency: Shift x the step's multiplier (Pattern 0 Off: x 1; patterns 1..8 eight steps of
 *   -2 .. 2, exact), stepping at Speed, gliding toward each step's value (Glide 0 instant .. 1 slow).
 *
 * Eight parameters, to fit the host model's knob words. Bit-exact on the SHARC port: no division, the
 * transcendentals are geiger_exp and ottobit_sin, constants rounded once.
 */
#ifndef SYNTAX_H
#define SYNTAX_H

#include "../common/fx.h"

enum { Y_DRIVE, Y_SHIFT, Y_PATTERN, Y_SPEED, Y_GLIDE, Y_TONE, Y_OUTPUT, Y_MIX, Y_NPARAMS };

#define SYNTAX_STEPS 8
#define SYNTAX_PATTERNS 9                 /* 0 = Off, 1..8 */
#define SYNTAX_AP 4                       /* allpasses per Hilbert path */

typedef struct {
    float dc_r, smooth_k, two_pi_sr, top, neg_w;      /* constants */
    float dcx, dcy;
    float ax[SYNTAX_AP][2], ay[SYNTAX_AP][2];         /* path A: x[n-1], x[n-2] and y[n-1], y[n-2] */
    float bx[SYNTAX_AP][2], by[SYNTAX_AP][2];         /* path B */
    float adel;                                       /* path A's extra sample of delay */
    float c, s;                                       /* the oscillator */
    float f;                                          /* the shift now, Hz */
    float sphase;
    int step;
    float tone_z, g_drive, g_out, g_mix;
    int primed;
} SyntaxState;

extern const FxAlgorithm fx_syntax;

/* Exposed for the tests and the SHARC port. */
const float *syntax_pattern(int p);       /* SYNTAX_STEPS multipliers */
extern const float SYNTAX_COEF_A[SYNTAX_AP], SYNTAX_COEF_B[SYNTAX_AP];   /* the allpasses' a^2 */

#endif
