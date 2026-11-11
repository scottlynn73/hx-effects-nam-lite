/* test_warp - Warp's reference tests (no hardware, no files). */
#include "warp.h"
#include "../common/signals.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SR 48000.0f
#define N  ((size_t)(2 * 48000))

static int failures, checks;

#define CHECK(cond, ...) do { checks++; if (!(cond)) { failures++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static void set(FxParams *p, int pitch, float depth, float rate, float chaos, float feedback, float tone, float output,
                float mix)
{
    memset(p, 0, sizeof *p);
    p->value[W_PITCH] = (float)pitch; p->value[W_DEPTH] = depth; p->value[W_RATE] = rate;
    p->value[W_CHAOS] = chaos; p->value[W_FEEDBACK] = feedback; p->value[W_TONE] = tone;
    p->value[W_OUTPUT] = output; p->value[W_MIX] = mix;
}

static WarpState st;

static void render(const FxParams *p, const float *in, float *out, size_t n, size_t block)
{
    size_t i;
    fx_warp.reset(&st, SR);
    for (i = 0; i < n; i += block)
        fx_warp.process(&st, p, in + i, out + i, n - i < block ? n - i : block);
}

static double goertzel(const float *x, size_t n, double hz)
{
    double w = 2 * 3.14159265358979323846 * hz / SR, c = 2 * cos(w), s1 = 0, s2 = 0, s;
    size_t i;
    for (i = 0; i < n; i++) { s = x[i] + c * s1 - s2; s2 = s1; s1 = s; }
    return sqrt(s1 * s1 + s2 * s2 - c * s1 * s2) * 2 / (double)n;
}

/* The strongest single bin within 50 Hz of hz: a two-head shifter spreads a pure tone into lines a
   window rate (about 23 Hz) apart around the shifted pitch. */
static double band(const float *x, size_t n, double hz)
{
    double f, a, top = 0;
    for (f = hz - 50; f <= hz + 50; f += 1) {
        a = goertzel(x, n, f);
        if (a > top) top = a;
    }
    return top;
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
    double a, b2, h;
    int k;
    if (!x || !y || !z) return 2;

    for (k = 1; k < WARP_PITCHES; k++) CHECK(WARP_RATIO[k] > WARP_RATIO[k - 1], "ratios not rising at %d", k);

    /* +12, -12, +7 and 0 on a 440 Hz tone (no modulation, no feedback, wet only) */
    sig_sine(x, N, SR, 440.0f, 0.5f);
    set(&p, 6, 0, 1, 0, 0, 1, 0, 1); render(&p, x, y, N, 16);
    a = band(y + N / 2, N / 2, 880.0); h = band(y + N / 2, N / 2, 440.0);
    CHECK(a > 0.1 && a > 4 * h, "+12: 880 Hz %g, 440 Hz %g", a, h);
    set(&p, 0, 0, 1, 0, 0, 1, 0, 1); render(&p, x, y, N, 16);
    a = band(y + N / 2, N / 2, 220.0); h = band(y + N / 2, N / 2, 440.0);
    CHECK(a > 0.1 && a > 4 * h, "-12: 220 Hz %g, 440 Hz %g", a, h);
    set(&p, 5, 0, 1, 0, 0, 1, 0, 1); render(&p, x, y, N, 16);
    a = band(y + N / 2, N / 2, 659.25); h = band(y + N / 2, N / 2, 440.0);
    CHECK(a > 0.1 && a > 4 * h, "+7: 659 Hz %g, 440 Hz %g", a, h);
    set(&p, 3, 0, 1, 0, 0, 1, 0, 1); render(&p, x, y, N, 16);
    a = band(y + N / 2, N / 2, 440.0);
    CHECK(fabs(20 * log10(a / 0.5)) < 1.5, "0: 440 Hz at %g dB", 20 * log10(a / 0.5));

    /* feedback at +12 builds a second octave (1760 Hz) */
    set(&p, 6, 0, 1, 0, 0.9f, 1, 0, 1); render(&p, x, y, N, 16);
    b2 = band(y + N / 2, N / 2, 1760.0);
    set(&p, 6, 0, 1, 0, 0, 1, 0, 1); render(&p, x, z, N, 16);
    CHECK(b2 > 3 * band(z + N / 2, N / 2, 1760.0) && b2 > 0.05, "feedback: 1760 Hz %g", b2);

    /* depth moves the pitch: a modulated 0 is not a clean 440 */
    set(&p, 3, 1, 2, 0, 0, 1, 0, 1); render(&p, x, y, N, 16);
    CHECK(band(y + N / 2, N / 2, 440.0) < 0.9 * a, "Depth 1: 440 Hz untouched");

    /* Mix 0: the input exactly */
    sig_noise(x, N, 9, 0.5f);
    set(&p, 7, 0.7f, 3, 0.5f, 0.95f, 0.4f, 6, 0); render(&p, x, y, N, 16);
    CHECK(memcmp(x, y, N * sizeof *x) == 0, "Mix 0: not the input");

    /* any block size gives the same output */
    sig_chord(x, N, SR, CHORD, 6, 960, 1.6f);
    set(&p, 6, 0.5f, 0.7f, 0.6f, 0.8f, 0.6f, -3, 0.8f);
    render(&p, x, y, N, 16);
    for (k = 1; k <= 97; k += 48) {
        render(&p, x, z, N, (size_t)k);
        CHECK(memcmp(y, z, N * sizeof *y) == 0, "block size %d differs from 16", k);
    }
    CHECK(bounded(y, N), "chord: output not finite and bounded");

    /* hostile input and parameters stay finite and bounded */
    sig_noise(x, N, 4, 4.0f);
    x[100] = NAN; x[200] = INFINITY; x[300] = -1e30f;
    set(&p, 99, 9, 1e9f, 9, 9, 9, 99, 9); render(&p, x, y, N, 16);
    CHECK(bounded(y, N), "hostile input: output not finite and bounded");
    set(&p, -9, -9, -9, -9, -9, -9, -99, -9); render(&p, x, y, N, 16);
    CHECK(bounded(y, N), "hostile low parameters: output not finite and bounded");

    printf("%d checks, %d failures\n", checks, failures);
    free(x); free(y); free(z);
    return failures ? 1 : 0;
}
