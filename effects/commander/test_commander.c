/* test_commander - Commander's reference tests (no hardware, no files). */
#include "commander.h"
#include "../common/signals.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SR 48000.0f
#define N  ((size_t)(2 * 48000))

static int failures, checks;

#define CHECK(cond, ...) do { checks++; if (!(cond)) { failures++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static void set(FxParams *p, float fuzz, float sub1, float sub2, float up, float tone, int gate, int dry, float output)
{
    memset(p, 0, sizeof *p);
    p->value[C_FUZZ] = fuzz; p->value[C_SUB1] = sub1; p->value[C_SUB2] = sub2; p->value[C_UP] = up;
    p->value[C_TONE] = tone; p->value[C_GATE] = (float)gate; p->value[C_DRY] = (float)dry; p->value[C_OUTPUT] = output;
}

static void render(const FxParams *p, const float *in, float *out, size_t n, size_t block)
{
    CommanderState s;
    size_t i;
    fx_commander.reset(&s, SR);
    for (i = 0; i < n; i += block)
        fx_commander.process(&s, p, in + i, out + i, n - i < block ? n - i : block);
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

/* Which of the candidate frequencies is strongest in the second half of the output. */
static double strongest(const float *y, const double *hz, int nh)
{
    int k, best = 0;
    double a, top = -1;
    for (k = 0; k < nh; k++) {
        a = goertzel(y + N / 2, N / 2, hz[k]);
        if (a > top) { top = a; best = k; }
    }
    return hz[best];
}

int main(void)
{
    float *x = malloc(N * sizeof *x), *y = malloc(N * sizeof *y), *z = malloc(N * sizeof *z);
    static const double CAND[] = { 27.5, 55.0, 110.0, 220.0, 330.0 };
    static const float CHORD[] = { 82.41f, 123.47f, 164.81f, 207.65f, 246.94f, 329.63f };
    FxParams p;
    size_t i;
    int b;
    if (!x || !y || !z) return 2;

    /* each voice alone on a 110 Hz note puts its octave on top */
    sig_sine(x, N, SR, 110.0f, 0.5f);
    set(&p, 1, 0, 0, 0, 1, 3, 0, 0); render(&p, x, y, N, 16);
    CHECK(strongest(y, CAND, 5) == 110.0, "Fuzz alone: strongest %g Hz", strongest(y, CAND, 5));
    set(&p, 0, 1, 0, 0, 1, 3, 0, 0); render(&p, x, y, N, 16);
    CHECK(strongest(y, CAND, 5) == 55.0, "Sub -1 alone: strongest %g Hz", strongest(y, CAND, 5));
    set(&p, 0, 0, 1, 0, 1, 3, 0, 0); render(&p, x, y, N, 16);
    CHECK(strongest(y, CAND, 5) == 27.5, "Sub -2 alone: strongest %g Hz", strongest(y, CAND, 5));
    set(&p, 0, 0, 0, 1, 1, 3, 0, 0); render(&p, x, y, N, 16);
    CHECK(strongest(y, CAND, 5) == 220.0, "Octave Up alone: strongest %g Hz", strongest(y, CAND, 5));
    CHECK(goertzel(y + N / 2, N / 2, 220.0) > 0.1, "Octave Up is loud enough: %g", goertzel(y + N / 2, N / 2, 220.0));

    /* a pluck too (decaying, harmonics): the sub tracks it */
    sig_pluck(x, N, SR, 110.0f, 0.8f, 3);
    set(&p, 0, 1, 0, 0, 0.5f, 1, 0, 0); render(&p, x, y, N, 16);
    CHECK(goertzel(y, N / 4, 55.0) > 3 * goertzel(y, N / 4, 110.0), "pluck: the sub at 55 Hz dominates (%g vs %g)",
          goertzel(y, N / 4, 55.0), goertzel(y, N / 4, 110.0));

    /* silence with the gate on: exactly silent */
    sig_silence(x, N);
    set(&p, 1, 1, 1, 1, 1, 3, 0, 12); render(&p, x, y, N, 16);
    for (i = 0; i < N && y[i] == 0.0f; i++) ;
    CHECK(i == N, "silence: output not silent at %zu (%g)", i, i < N ? y[i] : 0.0f);

    /* Dry 100 % with every voice off: the input exactly */
    sig_noise(x, N, 9, 0.5f);
    set(&p, 0, 0, 0, 0, 0.5f, 0, 10, 0); render(&p, x, y, N, 16);
    CHECK(memcmp(x, y, N * sizeof *x) == 0, "Dry 100 %%, voices off: not the input");

    /* any block size gives the same output */
    sig_chord(x, N, SR, CHORD, 6, 960, 1.6f);
    set(&p, 0.7f, 0.5f, 0.3f, 0.4f, 0.6f, 4, 2, -3);
    render(&p, x, y, N, 16);
    for (b = 1; b <= 97; b += 48) {
        render(&p, x, z, N, (size_t)b);
        CHECK(memcmp(y, z, N * sizeof *y) == 0, "block size %d differs from 16", b);
    }
    CHECK(bounded(y, N), "chord: output not finite and bounded");

    /* hostile input and parameters stay finite and bounded */
    sig_noise(x, N, 4, 4.0f);
    x[100] = NAN; x[200] = INFINITY; x[300] = -1e30f;
    set(&p, 9, -3, 9, 9, 7, 99, 99, 99); render(&p, x, y, N, 16);
    CHECK(bounded(y, N), "hostile input: output not finite and bounded");

    /* the gate's thresholds rise in 6 dB steps */
    CHECK(commander_gate(0) == 0.0f, "gate Off is not 0");
    for (b = 1; b < COMMANDER_GATE_STEPS; b++) {
        double r = 20 * log10(commander_gate(b + 1) / commander_gate(b));
        CHECK(fabs(r - 6.0) < 0.01, "gate %d -> %d: %g dB", b, b + 1, r);
    }

    printf("%d checks, %d failures\n", checks, failures);
    free(x); free(y); free(z);
    return failures ? 1 : 0;
}
