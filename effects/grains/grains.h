/* grains.h - "Grains": a granular delay. An original algorithm in the spirit of granular pedals; no
 * vendor code or tables.
 *
 * Signal path (per sample):
 *   in (plus Feedback x the grains, clamped to [-1, 1]) -> a GRAINS_RING-sample ring
 *   GRAINS_VOICES grain voices, Density of them active, staggered by a 1/Density of a grain at the start.
 *   Each grain: Size samples (a list, 10 .. 200 ms) under a parabolic window 4 t (1 - t), read at Pitch
 *   (a list of -12 .. +12 semitones; with probability Scatter an octave up or down instead of that), backwards
 *   with probability Reverse, starting behind the write head by what the read needs plus Spray x a random
 *   amount up to 0.5 s; linearly interpolated. A grain that would need samples not yet recorded is skipped
 *   (silent for its length). The grains sum x 1.5 / Density.
 *   out = in x (1 - Mix) + grains x Mix.
 *
 * Eight parameters, to fit the host model's knob words. Bit-exact on the SHARC port: no division (the
 * sizes, their reciprocals, the speeds and 1 / Density are tables rounded once), integer PRNG.
 */
#ifndef GRAINS_H
#define GRAINS_H

#include "../common/fx.h"

enum { N_SIZE, N_DENSITY, N_PITCH, N_SPRAY, N_SCATTER, N_REVERSE, N_FEEDBACK, N_MIX, N_NPARAMS };

#define GRAINS_RING 65536              /* samples (a power of two) */
#define GRAINS_VOICES 4
#define GRAINS_SIZES 8
#define GRAINS_PITCHES 7
#define GRAINS_SPRAY 24000             /* samples, at Spray 1 */
#define GRAINS_SEED 0x2545F491u

typedef struct {
    int active, wait, n, len, start, dir;   /* dir: 1 forward, -1 back */
    float inv, pos, speed;
} GrainVoice;

typedef struct {
    unsigned rnd;
    int w, filled, started;
    GrainVoice v[GRAINS_VOICES];
    float ring[GRAINS_RING];
} GrainsState;

extern const FxAlgorithm fx_grains;

/* Exposed for the tests and the SHARC port. */
extern const int GRAINS_LEN[GRAINS_SIZES];
extern const float GRAINS_INV[GRAINS_SIZES], GRAINS_SPEED[GRAINS_PITCHES], GRAINS_NORM[GRAINS_VOICES + 1],
    GRAINS_STAGGER[GRAINS_VOICES + 1];

#endif
