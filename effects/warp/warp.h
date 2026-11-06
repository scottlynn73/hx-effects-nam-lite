/* warp.h - "Warp": a modulated pitch shifter with regeneration. An original algorithm in the spirit of
 * pitch-shifting modulation pedals; no vendor code or tables.
 *
 * Signal path (per sample):
 *   in + Feedback x the shifted signal (clamped to [-1, 1]) -> a WARP_RING-sample ring
 *   the shifter: two read heads WARP_WIN / 2 apart, each at a delay of 64 + D samples, D moving by
 *      (1 - ratio) a sample and wrapping in [0, WARP_WIN); each head under a triangular crossfade
 *      1 - |2 D / WARP_WIN - 1|; linearly interpolated
 *   ratio = Pitch (a list: -12, -7, -5, 0, +5, +7, +12, +24 semitones) x (1 + Depth x 0.03 x mod), where
 *      mod = (1 - Chaos) x a triangle LFO at Rate + Chaos x a random value drawn each LFO cycle and glided
 *   -> tone (one-pole lowpass) -> output gain -> mix with the dry input -> out
 *
 * Eight parameters, to fit the host model's knob words. Bit-exact on the SHARC port: no division,
 * geiger_exp the only transcendental, integer PRNG, constants and tables rounded once.
 */
#ifndef WARP_H
#define WARP_H

#include "../common/fx.h"

enum { W_PITCH, W_DEPTH, W_RATE, W_CHAOS, W_FEEDBACK, W_TONE, W_OUTPUT, W_MIX, W_NPARAMS };

#define WARP_RING 4096                 /* samples (a power of two) */
#define WARP_WIN 2048                  /* the crossfade window, samples */
#define WARP_BASE 64.0f                /* the heads' least delay */
#define WARP_PITCHES 8
#define WARP_SEED 0x7F4A7C15u

typedef struct {
    float smooth_k, neg_w, top;        /* constants */
    float d, lph, cv, ct;              /* the shifter's offset; the LFO; the chaos value and its target */
    unsigned rnd;
    int w;
    float tone_z, g_out, g_mix;
    int primed;
    float ring[WARP_RING];
} WarpState;

extern const FxAlgorithm fx_warp;

/* Exposed for the tests and the SHARC port. */
extern const float WARP_RATIO[WARP_PITCHES];

#endif
