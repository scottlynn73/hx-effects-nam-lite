/* test_grains - Grains' reference tests (no hardware, no files). */
#include "grains.h"
#include "../common/signals.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SR 48000.0f
#define N  ((size_t)(2 * 48000))

static int failures, checks;

#define CHECK(cond, ...) do { checks++; if (!(cond)) { failures++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static void set(FxParams *p, int size, int density, int pitch, float spray, float scatter, float reverse, float feedback,
                float mix)
{
    memset(p, 0, sizeof *p);
    p->value[N_SIZE] = (float)size; p->value[N_DENSITY] = (float)density; p->value[N_PITCH] = (float)pitch;
    p->value[N_SPRAY] = spray; p->value[N_SCATTER] = scatter; p->value[N_REVERSE] = reverse;
    p->value[N_FEEDBACK] = feedback; p->value[N_MIX] = mix;
}

static GrainsState st;

static void render(const FxParams *p, const float *in, float *out, size_t n, size_t block)
{
    size_t i;
    fx_grains.reset(&st, SR);
    for (i = 0; i < n; i += block)
        fx_grains.process(&st, p, in + i, out + i, n - i < block ? n - i : block);
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
    int b, k, down;
    double a1, a2, a4;
    if (!x || !y || !z) return 2;

    for (k = 0; k < GRAINS_SIZES; k++)
        CHECK(fabsf(GRAINS_INV[k] * (float)GRAINS_LEN[k] - 1.0f) < 1e-6f, "size %d: 1/len", k);
    for (k = 1; k < GRAINS_PITCHES; k++)
        CHECK(GRAINS_SPEED[k] > GRAINS_SPEED[k - 1], "speeds not rising at %d", k);

    /* Mix 0: the input exactly */
    sig_noise(x, N, 9, 0.5f);
    set(&p, 3, 4, 5, 0.7f, 0.5f, 0.5f, 0.6f, 0); render(&p, x, y, N, 16);
    CHECK(memcmp(x, y, N * sizeof *x) == 0, "Mix 0: not the input");

    /* unison, -12 and +12 on a 440 Hz tone: the grains' pitch follows */
    sig_sine(x, N, SR, 440.0f, 0.5f);
    set(&p, 7, 2, 3, 0, 0, 0, 0, 1); render(&p, x, y, N, 16);
    a1 = goertzel(y + N / 2, N / 2, 440.0);
    CHECK(a1 > 0.3, "unison: 440 Hz at %g", a1);
    set(&p, 7, 2, 0, 0, 0, 0, 0, 1); render(&p, x, y, N, 16);
    a2 = goertzel(y + N / 2, N / 2, 220.0); a1 = goertzel(y + N / 2, N / 2, 440.0);
    CHECK(a2 > 0.2 && a2 > 4 * a1, "-12: 220 Hz %g, 440 Hz %g", a2, a1);
    set(&p, 7, 2, 6, 0, 0, 0, 0, 1); render(&p, x, y, N, 16);
    a4 = goertzel(y + N / 2, N / 2, 880.0); a1 = goertzel(y + N / 2, N / 2, 440.0);
    CHECK(a4 > 0.2 && a4 > 4 * a1, "+12: 880 Hz %g, 440 Hz %g", a4, a1);

    /* nothing before enough is recorded: the first grain cannot start at once */
    CHECK(y[0] == 0.0f && y[100] == 0.0f, "the grains play before anything is recorded");

    /* Reverse 1 on a rising ramp: the grains fall */
    for (i = 0; i < N; i++) x[i] = 0.5f * (float)i / (float)N;
    for (k = 0; k < 2; k++) {                       /* the window is symmetric, so compare its two sides */
        size_t i0, i1;
        set(&p, 7, 1, 3, 0, 0, (float)k, 0, 1); render(&p, x, y, N, 16);
        for (i0 = N / 2; i0 < N && y[i0] != 0.0f; i0++) ;
        while (i0 < N && y[i0] == 0.0f) i0++;       /* the grain's first sound */
        for (i1 = i0; i1 < N && y[i1] != 0.0f; i1++) ;
        down = i1 < N && i1 - i0 > 4000 && (k ? y[i1 - 1000] < y[i0 + 1000] : y[i1 - 1000] > y[i0 + 1000]);
        CHECK(down, "Reverse %d: grain %zu..%zu, %g at the start, %g at the end", k, i0, i1,
              i1 < N ? y[i0 + 1000] : 0.0f, i1 < N ? y[i1 - 1000] : 0.0f);
    }

    /* any block size gives the same output; feedback stays bounded */
    sig_chord(x, N, SR, CHORD, 6, 960, 1.6f);
    set(&p, 4, 3, 5, 0.6f, 0.4f, 0.3f, 0.9f, 0.8f);
    render(&p, x, y, N, 16);
    for (b = 1; b <= 97; b += 48) {
        render(&p, x, z, N, (size_t)b);
        CHECK(memcmp(y, z, N * sizeof *y) == 0, "block size %d differs from 16", b);
    }
    CHECK(bounded(y, N), "chord: output not finite and bounded");

    /* hostile input and parameters stay finite and bounded */
    sig_noise(x, N, 4, 4.0f);
    x[100] = NAN; x[200] = INFINITY; x[300] = -1e30f;
    set(&p, 99, 99, 99, 9, 9, 9, 9, 9); render(&p, x, y, N, 16);
    CHECK(bounded(y, N), "hostile input: output not finite and bounded");
    set(&p, -9, -9, -9, -9, -9, -9, -9, -9); render(&p, x, y, N, 16);
    CHECK(bounded(y, N), "hostile low parameters: output not finite and bounded");

    printf("%d checks, %d failures\n", checks, failures);
    free(x); free(y); free(z);
    return failures ? 1 : 0;
}
