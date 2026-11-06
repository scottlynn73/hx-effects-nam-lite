/* stutter.h - "Stutter": a triggered glitch repeater. An original algorithm in the spirit of buffer-repeat
 * pedals; no vendor code or tables.
 *
 * Signal path (per sample):
 *   in -> a STUTTER_RING-sample ring (recording, frozen while a stutter plays)
 *   triggers: a clock at Rate (Trigger Clock or Both) and/or a transient detector (fast envelope above
 *   twice a slow one plus a floor, 50 ms hold-off; Trigger Transient or Both); each opportunity fires with
 *   probability Chance (xorshift32). A firing (also while a stutter plays: a retrigger) takes the latest
 *   Length samples (20 .. 500 ms, halved up to twice at random by Random; never more than has been
 *   recorded, and no stutter while that is under 64) and plays them Repeats times at
 *   Speed (1x, 2x, 0.5x, reverse, reverse 2x, or one of those at random), linearly interpolated, each pass
 *   faded over 32 samples at both ends.
 *   out = in x (1 - Mix x a) + slice x Mix x a, where a ramps to 1 over 64 samples while a stutter plays
 *   and back to 0 after; with no stutter, the input exactly.
 *
 * Eight parameters, to fit the host model's knob words. Bit-exact on the SHARC port: no division,
 * geiger_exp the only transcendental, integer PRNG, constants rounded once.
 */
#ifndef STUTTER_H
#define STUTTER_H

#include "../common/fx.h"

enum { U_TRIGGER, U_RATE, U_CHANCE, U_LENGTH, U_REPEATS, U_SPEED, U_RANDOM, U_MIX, U_NPARAMS };

#define STUTTER_RING 32768             /* samples (a power of two) */
#define STUTTER_LMIN 64
#define STUTTER_LMAX 24000             /* 500 ms */
#define STUTTER_FADE 32
#define STUTTER_XFADE 64
#define STUTTER_HOLD 2400              /* transient hold-off, samples */
#define STUTTER_SEED 0x9E3779B9u

typedef struct {
    float smooth_r, slow_k, cphase;     /* constants; the clock */
    float envf, envs;                   /* the transient detector */
    int hold;
    unsigned rnd;
    int w, filled, playing, start, len, left;   /* filled: samples recorded, at most STUTTER_RING */
    float pos, speed, amt;
    float ring[STUTTER_RING];
} StutterState;

extern const FxAlgorithm fx_stutter;

/* Exposed for the tests and the SHARC port: playback speed for Speed list position k (0..4), and the
   speed the Random setting picks for a 3-bit draw. */
float stutter_speed(int k);
float stutter_random_speed(int k);

#endif
