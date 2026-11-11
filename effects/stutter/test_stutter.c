/* test_stutter - Stutter's reference tests (no hardware, no files). */
#include "stutter.h"
#include "../common/signals.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SR 48000.0f
#define N  ((size_t)(2 * 48000))

static int failures, checks;

#define CHECK(cond, ...) do { checks++; if (!(cond)) { failures++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static void set(FxParams *p, int trigger, float rate, float chance, float length, int repeats, int speed, float random,
                float mix)
{
    memset(p, 0, sizeof *p);
    p->value[U_TRIGGER] = (float)trigger; p->value[U_RATE] = rate; p->value[U_CHANCE] = chance;
    p->value[U_LENGTH] = length; p->value[U_REPEATS] = (float)repeats; p->value[U_SPEED] = (float)speed;
    p->value[U_RANDOM] = random; p->value[U_MIX] = mix;
}

static StutterState st;

static void render(const FxParams *p, const float *in, float *out, size_t n, size_t block)
{
    size_t i;
    fx_stutter.reset(&st, SR);
    for (i = 0; i < n; i += block)
        fx_stutter.process(&st, p, in + i, out + i, n - i < block ? n - i : block);
}

static int bounded(const float *x, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++) if (!isfinite(x[i]) || fabsf(x[i]) > 8.0f) return 0;
    return 1;
}

/* The first sample from `from` on where the output leaves the input, or n. */
static size_t first_diff(const float *x, const float *y, size_t from, size_t n)
{
    size_t i;
    for (i = from; i < n && x[i] == y[i]; i++) ;
    return i;
}

int main(void)
{
    float *x = malloc(N * sizeof *x), *y = malloc(N * sizeof *y), *z = malloc(N * sizeof *z);
    static const float CHORD[] = { 82.41f, 123.47f, 164.81f, 207.65f, 246.94f, 329.63f };
    FxParams p;
    size_t i, t;
    int b, down, n;
    if (!x || !y || !z) return 2;

    CHECK(stutter_speed(3) == -1.0f && stutter_speed(9) == -2.0f && stutter_random_speed(9) == 2.0f, "speed tables");

    /* Chance 0, or Mix 0: the input exactly */
    sig_noise(x, N, 9, 0.5f);
    set(&p, 2, 8, 0, 0.5f, 4, 0, 0, 1); render(&p, x, y, N, 16);
    CHECK(memcmp(x, y, N * sizeof *x) == 0, "Chance 0: not the input");
    set(&p, 2, 8, 1, 0.5f, 4, 0, 1, 0); render(&p, x, y, N, 16);
    CHECK(memcmp(x, y, N * sizeof *x) == 0, "Mix 0: not the input");

    /* Clock at 2 Hz, Chance 1, Length 0.5 (4,800 samples), 1x: the first stutter starts near 24,000 and
       repeats every 4,799 samples exactly */
    set(&p, 0, 2, 1, 0.5f, 4, 0, 0, 1); render(&p, x, y, N, 16);
    t = first_diff(x, y, 0, N);
    CHECK(t >= 23990 && t <= 24010, "clock: first stutter at %zu", t);
    n = 0;
    for (i = t + 200; i < t + 200 + 4799; i++) n += y[i] != y[i + 4799];
    CHECK(n == 0, "1x: %d samples differ one pass later", n);
    /* and plays Repeats (4) passes, then the input again */
    t = t + 4 * 4799 + 200;
    CHECK(memcmp(x + t, y + t, 2000 * sizeof *x) == 0, "after 4 passes: not the input");

    /* Reverse on a rising ramp: the output falls during a pass */
    for (i = 0; i < N; i++) x[i] = (float)i / (float)N;
    set(&p, 0, 2, 1, 0.5f, 4, 3, 0, 1); render(&p, x, y, N, 16);
    t = first_diff(x, y, 0, N);
    down = 0;
    for (i = t + 200; i < t + 1200; i++) down += y[i + 1] < y[i];
    CHECK(down == 1000, "Reverse: falling at %d of 1000 samples", down);

    /* Trigger Transient: nothing before the burst, a stutter at it */
    sig_silence(x, N);
    sig_noise(x + 30000, 20000, 3, 0.5f);
    set(&p, 1, 16, 1, 0.3f, 8, 0, 0, 1); render(&p, x, y, N, 16);
    t = first_diff(x, y, 0, N);
    CHECK(t >= 30000 && t < 30100, "transient: first stutter at %zu", t);

    /* Random length and speed, Random 1, any block size gives the same output */
    sig_chord(x, N, SR, CHORD, 6, 960, 1.6f);
    set(&p, 2, 6, 0.7f, 0.6f, 3, 5, 1, 0.8f);
    render(&p, x, y, N, 16);
    for (b = 1; b <= 97; b += 48) {
        render(&p, x, z, N, (size_t)b);
        CHECK(memcmp(y, z, N * sizeof *y) == 0, "block size %d differs from 16", b);
    }
    CHECK(bounded(y, N), "chord: output not finite and bounded");
    CHECK(memcmp(x, y, N * sizeof *x) != 0, "chord: no stutter at all");

    /* hostile input and parameters stay finite and bounded */
    sig_noise(x, N, 4, 4.0f);
    x[100] = NAN; x[200] = INFINITY; x[300] = -1e30f;
    set(&p, 99, 1e9f, 9, 9, 99, 99, 9, 9); render(&p, x, y, N, 16);
    CHECK(bounded(y, N), "hostile input: output not finite and bounded");
    set(&p, -9, -9, -9, -9, -9, -9, -9, -9); render(&p, x, y, N, 16);
    CHECK(bounded(y, N), "hostile low parameters: output not finite and bounded");

    printf("%d checks, %d failures\n", checks, failures);
    free(x); free(y); free(z);
    return failures ? 1 : 0;
}
