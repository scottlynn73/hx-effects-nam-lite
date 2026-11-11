/* test_doomchug - Doom Chug's reference tests (no hardware, no files). */
#include "doomchug.h"
#include "../common/signals.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SR 48000.0f
#define N  ((size_t)(6 * 48000))
#define HZ(inc) ((inc) * 48000.0f)

static int failures, checks;

#define CHECK(cond, ...) do { checks++; if (!(cond)) { failures++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static void set(FxParams *p, int key, int pattern, float rate, float drift, float warble, float chug, float tone, float level)
{
    memset(p, 0, sizeof *p);
    p->value[Q_KEY] = (float)key; p->value[Q_PATTERN] = (float)pattern; p->value[Q_RATE] = rate;
    p->value[Q_DRIFT] = drift; p->value[Q_WARBLE] = warble; p->value[Q_CHUG] = chug; p->value[Q_TONE] = tone;
    p->value[Q_LEVEL] = level;
}

static void render(DoomChugState *s, const FxParams *p, const float *in, float *out, size_t n, size_t block)
{
    size_t i;
    fx_doomchug.reset(s, SR);
    for (i = 0; i < n; i += block)
        fx_doomchug.process(s, p, in + i, out + i, n - i < block ? n - i : block);
}

/* The lowest and highest pitch any voice reaches. */
static void pitch_range(const FxParams *p, const float *in, float *out, float *lo, float *hi)
{
    DoomChugState s;
    size_t i;
    int v;
    *lo = 1e9f; *hi = 0.0f;
    fx_doomchug.reset(&s, SR);
    for (i = 0; i + 16 <= N; i += 16) {
        fx_doomchug.process(&s, p, in + i, out + i, 16);
        for (v = 0; v < DOOMCHUG_VOICES; v++) {
            if (HZ(s.inc[v]) < *lo) *lo = HZ(s.inc[v]);
            if (HZ(s.inc[v]) > *hi) *hi = HZ(s.inc[v]);
        }
    }
}

static double rms(const float *x, size_t n)
{
    double e = 0;
    size_t i;
    for (i = 0; i < n; i++) e += (double)x[i] * x[i];
    return sqrt(e / (double)n);
}

int main(void)
{
    float *x = calloc(N, sizeof *x), *y = malloc(N * sizeof *y), *z = malloc(N * sizeof *z);
    DoomChugState s;
    FxParams p;
    float lo, hi, a, b;
    double peak, floor_e;
    size_t i;
    int k, step, key;
    if (!x || !y || !z) return 2;

    for (k = 0; k < DOOMCHUG_PATTERNS; k++)
        CHECK(k || doomchug_pattern(k) == 0u, "pattern 0 is not all zero");

    /* never below low A, never above two octaves up, at every Key and Pattern, with everything turned up */
    for (key = 0; key < 12; key++)
        for (k = 0; k < DOOMCHUG_PATTERNS; k++) {
            set(&p, key, k, 1, 1, 1, 0, 1, 1);
            pitch_range(&p, x, y, &lo, &hi);
            CHECK(lo >= 109.99f && hi <= 440.01f, "key %d pattern %d: %g .. %g Hz", key, k, lo, hi);
        }

    /* Key A, nothing moving: the voices sit on root, a sharp root, the fifth and the octave */
    set(&p, 0, 0, 0.5f, 0, 0, 0, 1, 1); render(&s, &p, x, y, N, 16);
    CHECK(fabsf(HZ(s.inc[0]) - 110.0f) < 0.01f, "root %g", HZ(s.inc[0]));
    CHECK(HZ(s.inc[1]) > 110.5f && HZ(s.inc[1]) < 111.5f, "sharp root %g", HZ(s.inc[1]));
    CHECK(fabsf(HZ(s.inc[2]) - 164.81f) < 0.05f, "fifth %g", HZ(s.inc[2]));
    CHECK(fabsf(HZ(s.inc[3]) - 220.0f) < 0.02f, "octave %g", HZ(s.inc[3]));

    /* Drift and Warble each move the pitch; with both at 0 it stays put */
    set(&p, 0, 0, 0.9f, 0, 0, 0, 1, 1); pitch_range(&p, x, y, &lo, &hi);
    set(&p, 0, 0, 0.9f, 0, 0, 0, 1, 1);
    a = hi;
    set(&p, 0, 0, 0.9f, 1, 0, 0, 1, 1); pitch_range(&p, x, y, &lo, &hi);
    CHECK(hi > a * 1.1f, "Drift 1 reaches only %g Hz, against %g", hi, a);
    set(&p, 0, 0, 0.9f, 0, 1, 0, 1, 1); pitch_range(&p, x, y, &lo, &hi);
    CHECK(hi > a * 1.02f, "Warble 1 reaches only %g Hz, against %g", hi, a);

    /* the Pattern moves the notes: pattern 4 (tritone) visits root and +6 semitones */
    set(&p, 0, 4, 0.75f, 0, 0, 0, 1, 1); pitch_range(&p, x, y, &lo, &hi);
    CHECK(lo < 110.5f && hi > 300.0f, "pattern 4: %g .. %g Hz", lo, hi);

    /* Chug: 1 is loud on the step and much quieter before the next; 0 is steady */
    set(&p, 0, 0, 0.3f, 0, 0, 1, 0.5f, 1); render(&s, &p, x, y, N, 16);
    peak = 0; floor_e = 1e9;
    for (i = 0; i + 960 <= N; i += 960) {
        double e = rms(y + i, 960);
        if (e > peak) peak = e;
        if (e < floor_e) floor_e = e;
    }
    CHECK(peak > 0.05 && floor_e < 0.2 * peak, "Chug 1: peak %g, floor %g", peak, floor_e);
    set(&p, 0, 0, 0.3f, 0, 0, 0, 0.5f, 1); render(&s, &p, x, y, N, 16);
    peak = 0; floor_e = 1e9;
    for (i = 48000; i + 960 <= N; i += 960) {
        double e = rms(y + i, 960);
        if (e > peak) peak = e;
        if (e < floor_e) floor_e = e;
    }
    CHECK(floor_e > 0.5 * peak, "Chug 0: peak %g, floor %g", peak, floor_e);

    /* Tone 0 is darker than Tone 1 */
    set(&p, 0, 1, 0.5f, 0.3f, 0.3f, 0, 0, 1); render(&s, &p, x, y, N, 16);
    set(&p, 0, 1, 0.5f, 0.3f, 0.3f, 0, 1, 1); render(&s, &p, x, z, N, 16);
    a = (float)rms(y + 48000, N - 48000); b = (float)rms(z + 48000, N - 48000);
    CHECK(a < 0.8f * b, "Tone 0 rms %g, Tone 1 rms %g", a, b);

    /* the guitar passes untouched: Level 0 gives the input exactly */
    sig_noise(x, N, 9, 0.5f);
    set(&p, 3, 2, 0.5f, 0.5f, 0.5f, 0.5f, 0.5f, 0); render(&s, &p, x, y, N, 16);
    CHECK(memcmp(x, y, N * sizeof *x) == 0, "Level 0: not the input");

    /* the input never changes the drone: out - in is the same for silence and for noise */
    set(&p, 3, 2, 0.5f, 0.5f, 0.5f, 0.5f, 0.5f, 1); render(&s, &p, x, y, N, 16);
    memset(z, 0, N * sizeof *z);
    {
        float *w = malloc(N * sizeof *w);
        if (!w) return 2;
        render(&s, &p, z, w, N, 16);
        for (i = 0, step = 0; i < N; i++)
            if (fabsf((y[i] - x[i]) - w[i]) > 1e-4f) step++;
        CHECK(step == 0, "the drone depends on the input in %d samples", step);
        free(w);
    }

    /* any block size gives the same output */
    set(&p, 2, 5, 0.7f, 0.4f, 0.6f, 0.5f, 0.3f, 0.6f);
    render(&s, &p, x, y, N, 16);
    for (k = 1; k <= 97; k += 48) {
        render(&s, &p, x, z, N, (size_t)k);
        CHECK(memcmp(y, z, N * sizeof *y) == 0, "block size %d differs from 16", k);
    }

    /* hostile input and parameters stay finite and bounded */
    sig_noise(x, N, 4, 4.0f);
    x[100] = NAN; x[200] = INFINITY;
    set(&p, 99, 99, 9, 9, 9, 9, 9, 9); render(&s, &p, x, y, N, 16);
    for (i = 0, step = 0; i < N; i++) if (!isfinite(y[i]) || fabsf(y[i]) > 8.0f) step++;
    CHECK(step == 0, "hostile high: %d bad samples", step);
    set(&p, -9, -9, -9, -9, -9, -9, -9, -9); render(&s, &p, x, y, N, 16);
    for (i = 0, step = 0; i < N; i++) if (!isfinite(y[i]) || fabsf(y[i]) > 8.0f) step++;
    CHECK(step == 0, "hostile low: %d bad samples", step);

    printf("%d checks, %d failures\n", checks, failures);
    free(x); free(y); free(z);
    return failures ? 1 : 0;
}
