/* test_ottobit - Ottobit's reference tests (no hardware, no files). */
#include "ottobit.h"
#include "../common/signals.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SR 48000.0f
#define N  ((size_t)(2 * 48000))

static int failures, checks;

#define CHECK(cond, ...) do { checks++; if (!(cond)) { failures++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static void set(FxParams *p, float rate, int bits, float filter, int pattern, float speed, float stutter, float output,
                float mix)
{
    memset(p, 0, sizeof *p);
    p->value[O_RATE] = rate; p->value[O_BITS] = (float)bits; p->value[O_FILTER] = filter;
    p->value[O_PATTERN] = (float)pattern; p->value[O_SPEED] = speed; p->value[O_STUTTER] = stutter;
    p->value[O_OUTPUT] = output; p->value[O_MIX] = mix;
}

static OttobitState st;

static void render(const FxParams *p, const float *in, float *out, size_t n, size_t block)
{
    size_t i;
    fx_ottobit.reset(&st, SR);
    for (i = 0; i < n; i += block)
        fx_ottobit.process(&st, p, in + i, out + i, n - i < block ? n - i : block);
}

static double goertzel(const float *x, size_t n, double hz)
{
    double w = 2 * 3.14159265358979323846 * hz / SR, c = 2 * cos(w), s1 = 0, s2 = 0, s;
    size_t i;
    for (i = 0; i < n; i++) { s = x[i] + c * s1 - s2; s2 = s1; s1 = s; }
    return sqrt(s1 * s1 + s2 * s2 - c * s1 * s2) * 2 / (double)n;
}

static int bounded(const float *x, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++) if (!isfinite(x[i]) || fabsf(x[i]) > 8.0f) return 0;
    return 1;
}

int main(void)
{
    float *x = malloc(N * sizeof *x), *y = malloc(N * sizeof *y), *z = malloc(N * sizeof *z);
    static const float CHORD[] = { 82.41f, 123.47f, 164.81f, 207.65f, 246.94f, 329.63f };
    FxParams p;
    size_t i;
    int b, k;
    double worst, a, g;
    if (!x || !y || !z) return 2;

    /* the sine polynomial over its range */
    worst = 0;
    for (i = 0; i <= 1000; i++) {
        float v = 0.53f * (float)i / 1000.0f;
        double e = fabs(ottobit_sin(v) - sin(v));
        if (e > worst) worst = e;
    }
    CHECK(worst < 2e-7, "ottobit_sin: worst error %g", worst);

    /* the patterns are exact powers of two, at most 1, and Off is all ones */
    for (k = 0; k < OTTOBIT_PATTERNS; k++)
        for (b = 0; b < 2 * OTTOBIT_STEPS; b++) {
            float m = ottobit_pattern(k)[b];
            int e;
            CHECK(frexpf(m, &e) == 0.5f && m <= 1.0f && (k || m == 1.0f), "pattern %d entry %d: %g", k, b, m);
        }

    /* clean settings pass a 220 Hz tone at about unity */
    sig_sine(x, N, SR, 220.0f, 0.5f);
    set(&p, 48000, 16, 1, 0, 4, 0, 0, 1); render(&p, x, y, N, 16);
    a = goertzel(y + N / 2, N / 2, 220.0);
    CHECK(fabs(20 * log10(a / 0.5)) < 1.0, "clean: 220 Hz at %g dB", 20 * log10(a / 0.5));

    /* a 3 kHz sample rate folds 2.2 kHz down to 800 Hz */
    sig_sine(x, N, SR, 2200.0f, 0.5f);
    set(&p, 3000, 16, 1, 0, 4, 0, 0, 1); render(&p, x, y, N, 16);
    CHECK(goertzel(y + N / 2, N / 2, 800.0) > 0.1, "Rate 3 kHz: 800 Hz alias %g", goertzel(y + N / 2, N / 2, 800.0));

    /* 1 bit: before the filter, three levels; the output is far from the input */
    sig_sine(x, N, SR, 220.0f, 0.8f);
    set(&p, 48000, 1, 1, 0, 4, 0, 0, 1); render(&p, x, y, N, 16);
    CHECK(goertzel(y + N / 2, N / 2, 660.0) > 0.05, "1 bit: third harmonic %g", goertzel(y + N / 2, N / 2, 660.0));

    /* Filter 0 (100 Hz) takes the top off a 2 kHz tone */
    sig_sine(x, N, SR, 2000.0f, 0.5f);
    set(&p, 48000, 16, 0, 0, 4, 0, 0, 1); render(&p, x, y, N, 16);
    g = goertzel(y + N / 2, N / 2, 2000.0);
    CHECK(g < 0.5 * 0.01, "Filter 0: 2 kHz at %g dB", 20 * log10(g / 0.5));

    /* a pattern moves the filter: pattern 2's third step (filter / 8) is darker than pattern 0's */
    sig_noise(x, N, 3, 0.5f);
    set(&p, 48000, 16, 0.8f, 0, 2, 0, 0, 1); render(&p, x, y, N, 16);
    set(&p, 48000, 16, 0.8f, 2, 2, 0, 0, 1); render(&p, x, z, N, 16);
    a = goertzel(y + 3 * 24000 + 4000, 16000, 3000.0);
    g = goertzel(z + 3 * 24000 + 4000, 16000, 3000.0);
    CHECK(g < 0.3 * a, "pattern 2 step 3: 3 kHz %g vs %g with no pattern", g, a);

    /* Stutter 1: every step loops; within a step the output repeats at a quarter step (here capped by the ring) */
    sig_noise(x, N, 5, 0.5f);
    set(&p, 48000, 16, 1, 0, 4, 1, 0, 1); render(&p, x, y, N, 16);
    worst = 0;
    for (i = 2 * 12000 + 2000; i < 2 * 12000 + 6000; i++) {
        double e = fabs(y[i] - y[i + OTTOBIT_BUF]);
        if (e > worst) worst = e;
    }
    CHECK(worst < 1e-3, "Stutter 1: not periodic at the ring length (%g)", worst);
    /* and Stutter 0 never loops: the output follows the noise */
    set(&p, 48000, 16, 1, 0, 4, 0, 0, 1); render(&p, x, z, N, 16);
    worst = 0;
    for (i = 2 * 12000 + 2000; i < 2 * 12000 + 6000; i++) {
        double e = fabs(z[i] - z[i + OTTOBIT_BUF]);
        if (e > worst) worst = e;
    }
    CHECK(worst > 0.1, "Stutter 0: periodic (%g)", worst);

    /* Mix 0: the input exactly */
    sig_noise(x, N, 9, 0.5f);
    set(&p, 2000, 3, 0.3f, 5, 8, 0.5f, 6, 0); render(&p, x, y, N, 16);
    CHECK(memcmp(x, y, N * sizeof *x) == 0, "Mix 0: not the input");

    /* any block size gives the same output */
    sig_chord(x, N, SR, CHORD, 6, 960, 1.6f);
    set(&p, 6000, 5, 0.6f, 7, 6, 0.4f, -3, 0.8f);
    render(&p, x, y, N, 16);
    for (b = 1; b <= 97; b += 48) {
        render(&p, x, z, N, (size_t)b);
        CHECK(memcmp(y, z, N * sizeof *y) == 0, "block size %d differs from 16", b);
    }
    CHECK(bounded(y, N), "chord: output not finite and bounded");

    /* hostile input and parameters stay finite and bounded */
    sig_noise(x, N, 4, 4.0f);
    x[100] = NAN; x[200] = INFINITY; x[300] = -1e30f;
    set(&p, 1e9f, 99, 9, 99, 1e9f, 9, 99, 9); render(&p, x, y, N, 16);
    CHECK(bounded(y, N), "hostile input: output not finite and bounded");
    set(&p, -5, -3, -9, -9, -9, -9, -99, -9); render(&p, x, y, N, 16);
    CHECK(bounded(y, N), "hostile low parameters: output not finite and bounded");

    printf("%d checks, %d failures\n", checks, failures);
    free(x); free(y); free(z);
    return failures ? 1 : 0;
}
