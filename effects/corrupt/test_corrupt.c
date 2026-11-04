/* test_corrupt - Corrupt's reference tests (no hardware, no files). */
#include "corrupt.h"
#include "../common/signals.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SR 48000.0f
#define N  ((size_t)(2 * 48000))

static int failures, checks;

#define CHECK(cond, ...) do { checks++; if (!(cond)) { failures++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static void set(FxParams *p, float square, float master, float sub, float glide, float tone, float output, int root, int harm)
{
    memset(p, 0, sizeof *p);
    p->value[R_SQUARE] = square; p->value[R_MASTER] = master; p->value[R_SUB] = sub; p->value[R_GLIDE] = glide;
    p->value[R_TONE] = tone; p->value[R_OUTPUT] = output; p->value[R_ROOT] = (float)root; p->value[R_HARM] = (float)harm;
}

static void render(const FxParams *p, const float *in, float *out, size_t n, size_t block)
{
    CorruptState s;
    size_t i;
    fx_corrupt.reset(&s, SR);
    for (i = 0; i < n; i += block)
        fx_corrupt.process(&s, p, in + i, out + i, n - i < block ? n - i : block);
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

/* The strongest of the candidates in the second half, searched +-1 % around each (the rate is an
   integer period's, so it is a little off the note). */
static double strongest(const float *y, const double *hz, int nh)
{
    int k, best = 0, s;
    double a, top = -1;
    for (k = 0; k < nh; k++)
        for (s = -4; s <= 4; s++) {
            a = goertzel(y + N / 2, N / 2, hz[k] * (1 + s * 0.0025));
            if (a > top) { top = a; best = k; }
        }
    return hz[best];
}

int main(void)
{
    float *x = malloc(N * sizeof *x), *y = malloc(N * sizeof *y), *z = malloc(N * sizeof *z);
    static const double CAND[] = { 27.5, 55.0, 110.0, 220.0, 330.0, 440.0 };
    static const float CHORD[] = { 82.41f, 123.47f, 164.81f, 207.65f, 246.94f, 329.63f };
    FxParams p;
    size_t i;
    int b;
    if (!x || !y || !z) return 2;

    sig_sine(x, N, SR, 110.0f, 0.5f);
    set(&p, 0, 1, 0, 0, 1, 0, 2, 1); render(&p, x, y, N, 16);
    CHECK(strongest(y, CAND, 6) == 110.0, "Master, unison: strongest %g Hz", strongest(y, CAND, 6));
    set(&p, 0, 1, 0, 0, 1, 0, 1, 1); render(&p, x, y, N, 16);
    CHECK(strongest(y, CAND, 6) == 55.0, "Master, -1 oct: strongest %g Hz", strongest(y, CAND, 6));
    set(&p, 0, 1, 0, 0, 1, 0, 0, 1); render(&p, x, y, N, 16);
    CHECK(strongest(y, CAND, 6) == 27.5, "Master, -2 oct: strongest %g Hz", strongest(y, CAND, 6));
    set(&p, 0, 1, 0, 0, 1, 0, 3, 1); render(&p, x, y, N, 16);
    CHECK(strongest(y, CAND, 6) == 220.0, "Master, +1 oct: strongest %g Hz", strongest(y, CAND, 6));
    set(&p, 0, 1, 0, 0, 1, 0, 2, 3); render(&p, x, y, N, 16);
    CHECK(strongest(y, CAND, 6) == 330.0, "Master, harmonic 3: strongest %g Hz", strongest(y, CAND, 6));
    set(&p, 0, 0, 1, 0, 1, 0, 2, 1); render(&p, x, y, N, 16);
    CHECK(strongest(y, CAND, 6) == 55.0, "Sub: strongest %g Hz", strongest(y, CAND, 6));
    set(&p, 1, 0, 0, 0, 1, 0, 2, 1); render(&p, x, y, N, 16);
    CHECK(strongest(y, CAND, 6) == 110.0, "Square: strongest %g Hz", strongest(y, CAND, 6));

    /* a pluck: the oscillator follows it */
    sig_pluck(x, N, SR, 82.41f, 0.8f, 5);
    set(&p, 0, 1, 0, 0, 0.6f, 0, 2, 1); render(&p, x, y, N, 16);
    CHECK(goertzel(y, N / 4, 82.41) > 3 * goertzel(y, N / 4, 110.0), "pluck at 82 Hz: tracked (%g vs %g)",
          goertzel(y, N / 4, 82.41), goertzel(y, N / 4, 110.0));

    /* Glide: after a jump from 110 to 220 Hz, Glide 0 is at 220 within 50 ms, Glide 1 is not yet */
    sig_sine(x, N / 2, SR, 110.0f, 0.5f);
    sig_sine(x + N / 2, N / 2, SR, 220.0f, 0.5f);
    {
        double fast, slow;
        set(&p, 0, 1, 0, 0, 1, 0, 2, 1); render(&p, x, y, N, 16);
        fast = goertzel(y + N / 2 + 2400, 4800, 220.0);
        set(&p, 0, 1, 0, 1, 1, 0, 2, 1); render(&p, x, y, N, 16);
        slow = goertzel(y + N / 2 + 2400, 4800, 220.0);
        CHECK(fast > 2 * slow, "Glide: 220 Hz 50 ms after the jump, Glide 0 %g, Glide 1 %g", fast, slow);
    }

    /* silence: exactly silent */
    sig_silence(x, N);
    set(&p, 1, 1, 1, 0.5f, 1, 12, 3, 8); render(&p, x, y, N, 16);
    for (i = 0; i < N && y[i] == 0.0f; i++) ;
    CHECK(i == N, "silence: output not silent at %zu (%g)", i, i < N ? y[i] : 0.0f);

    /* any block size gives the same output */
    sig_chord(x, N, SR, CHORD, 6, 960, 1.6f);
    set(&p, 0.3f, 0.8f, 0.4f, 0.2f, 0.6f, -6, 2, 2);
    render(&p, x, y, N, 16);
    for (b = 1; b <= 97; b += 48) {
        render(&p, x, z, N, (size_t)b);
        CHECK(memcmp(y, z, N * sizeof *y) == 0, "block size %d differs from 16", b);
    }
    CHECK(bounded(y, N), "chord: output not finite and bounded");

    /* hostile input and parameters */
    sig_noise(x, N, 4, 4.0f);
    x[100] = NAN; x[200] = INFINITY; x[300] = -1e30f;
    set(&p, 9, 9, -3, 9, 7, 99, 99, 99); render(&p, x, y, N, 16);
    CHECK(bounded(y, N), "hostile input: output not finite and bounded");
    sig_sine(x, N, SR, 2900.0f, 0.5f);                 /* the top of the range, x8, +1 oct: capped */
    set(&p, 0, 1, 1, 0, 1, 0, 3, 8); render(&p, x, y, N, 16);
    CHECK(bounded(y, N), "2.9 kHz x 16: output not finite and bounded");

    printf("%d checks, %d failures\n", checks, failures);
    free(x); free(y); free(z);
    return failures ? 1 : 0;
}
