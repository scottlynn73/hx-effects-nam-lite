/* test_sequence - Sequence's reference tests (no hardware, no files). */
#include "sequence.h"
#include "../common/signals.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SR 48000.0f
#define N  ((size_t)(2 * 48000))

static int failures, checks;

#define CHECK(cond, ...) do { checks++; if (!(cond)) { failures++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static void set(FxParams *p, int pattern, float speed, int wave, int octave, float glide, float tone, float output,
                float mix)
{
    memset(p, 0, sizeof *p);
    p->value[Q_PATTERN] = (float)pattern; p->value[Q_SPEED] = speed; p->value[Q_WAVE] = (float)wave;
    p->value[Q_OCTAVE] = (float)octave; p->value[Q_GLIDE] = glide; p->value[Q_TONE] = tone;
    p->value[Q_OUTPUT] = output; p->value[Q_MIX] = mix;
}

static void render(const FxParams *p, const float *in, float *out, size_t n, size_t block)
{
    SequenceState s;
    size_t i;
    fx_sequence.reset(&s, SR);
    for (i = 0; i < n; i += block)
        fx_sequence.process(&s, p, in + i, out + i, n - i < block ? n - i : block);
}

static double goertzel(const float *x, size_t n, double hz)
{
    double w = 2 * 3.14159265358979323846 * hz / SR, c = 2 * cos(w), s1 = 0, s2 = 0, s;
    size_t i;
    for (i = 0; i < n; i++) { s = x[i] + c * s1 - s2; s2 = s1; s1 = s; }
    return sqrt(s1 * s1 + s2 * s2 - c * s1 * s2) * 2 / (double)n;
}

static double strongest(const float *y, size_t n, const double *hz, int nh)
{
    int k, best = 0;
    double a, top = -1;
    for (k = 0; k < nh; k++) {
        a = goertzel(y, n, hz[k]);
        if (a > top) { top = a; best = k; }
    }
    return hz[best];
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
    static const double CAND[] = { 55.0, 110.0, 138.59, 164.81, 220.0, 440.0 };
    FxParams p;
    double f;
    int b;
    if (!x || !y || !z) return 2;

    CHECK(sequence_ratio(1, 1) == 2.0f && sequence_ratio(0, 5) == 1.0f && fabsf(sequence_ratio(2, 2) - 1.4983071f) < 1e-6f,
          "ratios");

    /* Off, unison, square: the synth plays the note */
    sig_sine(x, N, SR, 110.0f, 0.5f);
    set(&p, 0, 4, 0, 2, 0, 1, 0, 1); render(&p, x, y, N, 16);
    f = strongest(y + N / 2, N / 2, CAND, 6);
    CHECK(f == 110.0, "Off: strongest %g Hz", f);
    /* Octave -1: an octave down */
    set(&p, 0, 4, 0, 1, 0, 1, 0, 1); render(&p, x, y, N, 16);
    f = strongest(y + N / 2, N / 2, CAND, 6);
    CHECK(f == 55.0, "Octave -1: strongest %g Hz", f);
    /* the octave bounce at 2 steps a second: 110 Hz in one step, 220 Hz in the next */
    set(&p, 1, 2, 1, 2, 0, 1, 0, 1); render(&p, x, y, N, 16);
    f = strongest(y + 26000, 20000, CAND, 6);
    CHECK(f == 220.0, "bounce step 2: strongest %g Hz", f);
    f = strongest(y + 50000, 20000, CAND, 6);
    CHECK(f == 110.0, "bounce step 3: strongest %g Hz", f);
    /* the major arpeggio's third step is the fifth (164.8 Hz) */
    set(&p, 2, 2, 2, 2, 0, 1, 0, 1); render(&p, x, y, N, 16);
    f = strongest(y + 50000, 20000, CAND, 6);
    CHECK(f == 164.81, "major step 3: strongest %g Hz", f);

    /* silence: exactly silent */
    sig_silence(x, N);
    set(&p, 4, 8, 1, 3, 0.3f, 1, 12, 1); render(&p, x, y, N, 16);
    CHECK(memcmp(x, y, N * sizeof *x) == 0, "silence: not silent");

    /* Mix 0: the input exactly */
    sig_noise(x, N, 9, 0.5f);
    set(&p, 5, 8, 3, 0, 0.5f, 0.5f, 6, 0); render(&p, x, y, N, 16);
    CHECK(memcmp(x, y, N * sizeof *x) == 0, "Mix 0: not the input");

    /* any block size gives the same output */
    sig_chord(x, N, SR, CHORD, 6, 960, 1.6f);
    set(&p, 7, 6, 2, 3, 0.2f, 0.6f, -3, 0.8f);
    render(&p, x, y, N, 16);
    for (b = 1; b <= 97; b += 48) {
        render(&p, x, z, N, (size_t)b);
        CHECK(memcmp(y, z, N * sizeof *y) == 0, "block size %d differs from 16", b);
    }
    CHECK(bounded(y, N), "chord: output not finite and bounded");

    /* hostile input and parameters stay finite and bounded */
    sig_noise(x, N, 4, 4.0f);
    x[100] = NAN; x[200] = INFINITY; x[300] = -1e30f;
    set(&p, 99, 1e9f, 99, 99, 9, 9, 99, 9); render(&p, x, y, N, 16);
    CHECK(bounded(y, N), "hostile input: output not finite and bounded");
    set(&p, -9, -9, -9, -9, -9, -9, -99, -9); render(&p, x, y, N, 16);
    CHECK(bounded(y, N), "hostile low parameters: output not finite and bounded");

    printf("%d checks, %d failures\n", checks, failures);
    free(x); free(y); free(z);
    return failures ? 1 : 0;
}
