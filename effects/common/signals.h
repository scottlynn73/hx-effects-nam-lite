/* signals.h - deterministic test signals, generated from code (no recorded audio). */
#ifndef SIGNALS_H
#define SIGNALS_H

#include <stddef.h>
#include <stdint.h>

typedef struct { uint64_t s; } Rng;            /* xorshift64*: same sequence on every platform */
void rng_seed(Rng *r, uint64_t seed);
uint32_t rng_u32(Rng *r);
float rng_uniform(Rng *r);                     /* [-1, 1) */

void sig_silence(float *x, size_t n);
void sig_impulse(float *x, size_t n, float amp);
void sig_step(float *x, size_t n, float amp);
void sig_sine(float *x, size_t n, float rate, float hz, float amp);
void sig_sweep(float *x, size_t n, float rate, float f0, float f1, float amp);   /* exponential */
void sig_noise(float *x, size_t n, uint64_t seed, float amp);
/* A plucked string (Karplus-Strong) at hz, decaying; a stand-in for a guitar DI note. */
void sig_pluck(float *x, size_t n, float rate, float hz, float amp, uint64_t seed);
/* Several plucks summed, starting `stagger` samples apart (a strummed chord). */
void sig_chord(float *x, size_t n, float rate, const float *hz, size_t notes, size_t stagger, float amp);

#endif
