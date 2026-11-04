/* geiger.h - "Geiger": sample-rate reduction, bit-depth quantisation and table waveshaping.
 * An original algorithm in the spirit of wavetable-distortion pedals; no vendor tables.
 *
 * Signal path (per sample):
 *   in -> DC block -> gain -> [anti-alias lowpass, if AA] -> sample-and-hold at Rate
 *      -> quantise to Bits -> waveshaper table Curve -> tone lowpass -> DC block
 *      -> output gain -> mix with the dry input -> out
 *
 * Eight parameters, to fit the host model's eight knob words (docs/baseline-audit.md).
 * Written so a SHARC port can match it bit for bit: no division, pow or exp at run time other than
 * geiger_exp, constants rounded once from double, and the build uses -ffp-contract=off.
 */
#ifndef GEIGER_H
#define GEIGER_H

#include "../common/fx.h"

enum { G_GAIN, G_RATE, G_BITS, G_CURVE, G_TONE, G_OUTPUT, G_MIX, G_AA, G_NPARAMS };

#define GEIGER_CURVES 16
#define GEIGER_TABLE 64                  /* segments; GEIGER_TABLE + 1 points over [-1, 1] (sized to fit
                                            beside NAM and Click in the DSP's memory) */

typedef struct {
    float sr;
    float dc_r, smooth_k, inv_sr, neg_w;  /* constants: 1/sr, -2 pi / sr */
    float dcin_x1, dcin_y1, dcout_x1, dcout_y1;
    float aa1, aa2, aa_a, aa_rate;       /* two one-pole lowpasses before the sample-and-hold */
    float phase, held;
    float tone_z, tone_a, tone_val;
    float g_gain, g_out, g_mix;          /* smoothed linear gains */
    int primed;
} GeigerState;

extern const FxAlgorithm fx_geiger;

/* Exposed for the unit tests and the SHARC port. */
const char *geiger_curve_name(int c);
float geiger_curve_exact(int c, float x);        /* the defining function, x in [-1, 1] */
float geiger_curve(int c, float x);              /* the table lookup the effect uses */
const float *geiger_table(int c);                /* GEIGER_TABLE + 1 points */
float geiger_quantize(float x, int bits);
/* exp(y) for |y| <= 5, the way the SHARC port computes it: a degree-6 Taylor polynomial of y/16 (Horner)
   squared four times. Every gain and filter coefficient goes through it, so C and the DSP agree to the bit. */
float geiger_exp(float y);

#endif
