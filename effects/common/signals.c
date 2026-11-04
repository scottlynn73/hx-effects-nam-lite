#include "signals.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

#define PI 3.14159265358979323846

void rng_seed(Rng *r, uint64_t seed) { r->s = seed ? seed : 0x9e3779b97f4a7c15ull; }

uint32_t rng_u32(Rng *r)
{
    r->s ^= r->s >> 12;
    r->s ^= r->s << 25;
    r->s ^= r->s >> 27;
    return (uint32_t)((r->s * 0x2545f4914f6cdd1dull) >> 32);
}

float rng_uniform(Rng *r) { return (float)((double)rng_u32(r) / 2147483648.0 - 1.0); }

void sig_silence(float *x, size_t n) { memset(x, 0, n * sizeof *x); }

void sig_impulse(float *x, size_t n, float amp) { sig_silence(x, n); if (n) x[0] = amp; }

void sig_step(float *x, size_t n, float amp) { size_t i; for (i = 0; i < n; i++) x[i] = amp; }

void sig_sine(float *x, size_t n, float rate, float hz, float amp)
{
    size_t i;
    for (i = 0; i < n; i++)
        x[i] = (float)(amp * sin(2 * PI * hz * (double)i / rate));
}

void sig_sweep(float *x, size_t n, float rate, float f0, float f1, float amp)
{
    double T = (double)n / rate, k = log((double)f1 / f0);
    size_t i;
    for (i = 0; i < n; i++) {
        double t = i / (double)rate;
        x[i] = (float)(amp * sin(2 * PI * f0 * T / k * (exp(t / T * k) - 1)));
    }
}

void sig_noise(float *x, size_t n, uint64_t seed, float amp)
{
    Rng r;
    size_t i;
    rng_seed(&r, seed);
    for (i = 0; i < n; i++) x[i] = amp * rng_uniform(&r);
}

void sig_pluck(float *x, size_t n, float rate, float hz, float amp, uint64_t seed)
{
    size_t L = (size_t)(rate / hz + 0.5), i;
    float *d;
    Rng r;
    if (L < 2) L = 2;
    d = malloc(L * sizeof *d);
    if (!d) { sig_silence(x, n); return; }
    rng_seed(&r, seed);
    for (i = 0; i < L; i++) d[i] = rng_uniform(&r);
    for (i = 0; i < n; i++) {
        size_t k = i % L;
        float v = d[k];
        d[k] = 0.4985f * (d[k] + d[(k + 1) % L]);   /* averaging = string loss */
        x[i] = amp * v;
    }
    free(d);
}

void sig_chord(float *x, size_t n, float rate, const float *hz, size_t notes, size_t stagger, float amp)
{
    float *tmp = malloc(n * sizeof *tmp);
    size_t j, i;
    sig_silence(x, n);
    if (!tmp) return;
    for (j = 0; j < notes; j++) {
        size_t off = j * stagger;
        if (off >= n) break;
        sig_pluck(tmp, n - off, rate, hz[j], amp / (float)notes, 1000 + j);
        for (i = 0; i < n - off; i++) x[off + i] += tmp[i];
    }
    free(tmp);
}
