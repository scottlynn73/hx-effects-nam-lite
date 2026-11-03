/* test_geiger - Geiger's reference tests. No hardware, no files read except the golden file.
 *
 *   test_geiger [golden.txt]            run the tests (golden checks only if the file is given)
 *   test_geiger --write-golden <file>   record the golden metrics on this platform
 */
#include "geiger.h"
#include "../common/signals.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SR 48000.0f
#define N  ((size_t)(2 * 48000))

static int failures, checks;

#define CHECK(cond, ...) do { checks++; if (!(cond)) { failures++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static void set(FxParams *p, float gain, float rate, int bits, int curve, float tone, float output, float mix, int aa)
{
    memset(p, 0, sizeof *p);
    p->value[G_GAIN] = gain; p->value[G_RATE] = rate; p->value[G_BITS] = (float)bits;
    p->value[G_CURVE] = (float)curve; p->value[G_TONE] = tone; p->value[G_OUTPUT] = output;
    p->value[G_MIX] = mix; p->value[G_AA] = (float)aa;
}

static void render(const FxParams *p, const float *in, float *out, size_t n, size_t block)
{
    GeigerState s;
    size_t i;
    fx_geiger.reset(&s, SR);
    for (i = 0; i < n; i += block)
        fx_geiger.process(&s, p, in + i, out + i, n - i < block ? n - i : block);
}

static double rms(const float *x, size_t n) { double a = 0; size_t i; for (i = 0; i < n; i++) a += (double)x[i] * x[i]; return sqrt(a / (double)n); }

static double rms_diff(const float *a, const float *b, size_t n)
{
    double s = 0; size_t i;
    for (i = 0; i < n; i++) s += ((double)a[i] - b[i]) * ((double)a[i] - b[i]);
    return sqrt(s / (double)n);
}

static double goertzel(const float *x, size_t n, double hz)     /* amplitude at hz */
{
    double w = 2 * 3.14159265358979323846 * hz / SR, c = 2 * cos(w), s1 = 0, s2 = 0, s;
    size_t i;
    for (i = 0; i < n; i++) { s = x[i] + c * s1 - s2; s2 = s1; s1 = s; }
    return sqrt(s1 * s1 + s2 * s2 - c * s1 * s2) * 2 / (double)n;
}

static int all_finite_bounded(const float *x, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++) if (!isfinite(x[i]) || fabsf(x[i]) > 8.0f) return 0;
    return 1;
}

/* ---------------------------------------------------------------- tests */

static void test_curves(void)
{
    int c, d, i;
    for (c = 0; c < GEIGER_CURVES; c++) {
        double worst = 0;
        for (i = 0; i <= 2000; i++) {
            float x = -1.0f + i / 1000.0f, y = geiger_curve_exact(c, x), t = geiger_curve(c, x);
            CHECK(isfinite(y) && y >= -1.0f && y <= 1.0f, "curve %d out of range at %g: %g", c, x, y);
            if (c != 7 && fabs(t - y) > worst) worst = fabs(t - y);     /* 7 "steps" has jumps */
        }
        /* 256 segments track smooth curves within 0.01; the folds' corners (4) and root's
           infinite slope at 0 (12) within 0.025. The table is what the effect (and a SHARC
           port) uses; this checks it stays faithful to the defining function. */
        CHECK(worst < ((c == 4 || c == 12) ? 0.025 : 0.01), "curve %d (%s): table error %g", c, geiger_curve_name(c), worst);
        for (d = 0; d < c; d++) {
            double m = 0;
            for (i = 0; i <= 2000; i++) {
                float x = -1.0f + i / 1000.0f;
                double e = fabs(geiger_curve_exact(c, x) - geiger_curve_exact(d, x));
                if (e > m) m = e;
            }
            CHECK(m > 0.05, "curves %d and %d are nearly the same (max diff %g)", c, d, m);
        }
    }
}

static void test_quantizer(void)
{
    int b, i;
    for (b = 1; b <= 8; b++) {
        float levels[600];
        int n = 0, j;
        for (i = 0; i <= 4000; i++) {
            float y = geiger_quantize(-1.2f + 2.4f * i / 4000.0f, b);
            for (j = 0; j < n && levels[j] != y; j++) ;
            if (j == n && n < 600) levels[n++] = y;
        }
        CHECK(n <= (1 << b) + 1 && n >= (1 << b), "bits %d: %d levels", b, n);
    }
    for (i = 0; i <= 1000; i++) {
        float x = -1.0f + i / 500.0f;
        CHECK(fabsf(geiger_quantize(x, 16) - x) <= 1.0f / 65536 + 1e-7f, "16-bit error at %g", x);
    }
}

static void test_dry(const float *chord, const float *noise)
{
    FxParams p;
    float *out = malloc(N * sizeof *out);
    size_t i;
    int same = 1;
    set(&p, 36, 250, 1, 4, 0, 12, 0, 0);                  /* everything extreme, Mix 0 */
    render(&p, chord, out, N, 16);
    for (i = 0; i < N; i++) if (out[i] != chord[i]) same = 0;
    CHECK(same, "Mix 0 is not exactly the dry input (chord)");
    render(&p, noise, out, N, 16);
    same = 1;
    for (i = 0; i < N; i++) if (out[i] != noise[i]) same = 0;
    CHECK(same, "Mix 0 is not exactly the dry input (noise)");
    free(out);
}

static void test_determinism_and_blocks(const float *chord)
{
    FxParams p;
    static const size_t blocks[] = { 1, 16, 37, 4096 };
    float *a = malloc(N * sizeof *a), *b = malloc(N * sizeof *b);
    size_t k;
    set(&p, 18, 7000, 5, 13, 0.6f, -6, 80, 1);
    render(&p, chord, a, N, 16);
    render(&p, chord, b, N, 16);
    CHECK(!memcmp(a, b, N * sizeof *a), "two renders differ");
    for (k = 0; k < sizeof blocks / sizeof blocks[0]; k++) {
        render(&p, chord, b, N, blocks[k]);
        CHECK(!memcmp(a, b, N * sizeof *a), "block size %zu changes the output", blocks[k]);
    }
    free(a); free(b);
}

static void test_instances(const float *chord, const float *noise)
{
    FxParams p1, p2;
    GeigerState s1, s2;
    float *a = malloc(N * sizeof *a), *b = malloc(N * sizeof *b), *ra = malloc(N * sizeof *ra), *rb = malloc(N * sizeof *rb);
    size_t i;
    set(&p1, 12, 3000, 4, 3, 0.4f, -6, 100, 0);
    set(&p2, 24, 16000, 10, 9, 0.9f, -12, 60, 1);
    render(&p1, chord, ra, N, 16);
    render(&p2, noise, rb, N, 16);
    fx_geiger.reset(&s1, SR);
    fx_geiger.reset(&s2, SR);
    for (i = 0; i < N; i += 16) {                         /* interleaved, as two blocks in a preset */
        fx_geiger.process(&s1, &p1, chord + i, a + i, 16);
        fx_geiger.process(&s2, &p2, noise + i, b + i, 16);
    }
    CHECK(!memcmp(a, ra, N * sizeof *a) && !memcmp(b, rb, N * sizeof *b), "instances interfere");
    free(a); free(b); free(ra); free(rb);
}

static void test_robustness(const float *chord)
{
    FxParams p;
    GeigerState s;
    float *in = malloc(N * sizeof *in), *out = malloc(N * sizeof *out);
    Rng r;
    size_t i;
    int c, ok = 1;
    for (c = 0; c < GEIGER_CURVES; c++) {                 /* every curve at the extremes */
        set(&p, 36, 250, 1, c, 0, 12, 100, 0);   render(&p, chord, out, N, 16); ok &= all_finite_bounded(out, N);
        set(&p, 0, 48000, 16, c, 1, -36, 100, 1); render(&p, chord, out, N, 16); ok &= all_finite_bounded(out, N);
    }
    CHECK(ok, "non-finite or unbounded output at extreme settings");
    memcpy(in, chord, N * sizeof *in);                    /* hostile input */
    in[100] = NAN; in[200] = INFINITY; in[300] = -INFINITY; in[400] = 1e30f; in[500] = -1e30f;
    for (i = 1000; i < 2000; i++) in[i] = 1e20f;
    set(&p, 36, 1000, 3, 10, 0.5f, 12, 100, 1);
    render(&p, in, out, N, 16);
    CHECK(all_finite_bounded(out, N), "hostile input gives bad output");
    rng_seed(&r, 42);                                     /* knobs moving every block, some NaN */
    fx_geiger.reset(&s, SR);
    for (i = 0; i < N; i += 16) {
        int j;
        for (j = 0; j < G_NPARAMS; j++) p.value[j] = 200.0f * rng_uniform(&r);
        if (rng_u32(&r) % 7 == 0) p.value[rng_u32(&r) % G_NPARAMS] = NAN;
        fx_geiger.process(&s, &p, chord + i, out + i, 16);
    }
    CHECK(all_finite_bounded(out, N), "random knob changes give bad output");
    free(in); free(out);
}

static void test_decimator(void)
{
    GeigerState s;
    FxParams p;
    float x, y, last;
    size_t i, n = 48000, updates = 0;
    Rng r;
    static const float rates[] = { 250, 1000, 4410, 12000, 47999, 48000 };
    size_t k;
    for (k = 0; k < sizeof rates / sizeof rates[0]; k++) {
        set(&p, 0, rates[k], 16, 0, 1, 0, 100, 0);
        fx_geiger.reset(&s, SR);
        rng_seed(&r, 3);
        last = s.held;
        updates = 0;
        for (i = 0; i < n; i++) {
            x = 0.5f * rng_uniform(&r);                  /* noise: every hold differs from the last */
            fx_geiger.process(&s, &p, &x, &y, 1);
            if (s.held != last) { updates++; last = s.held; }
        }
        CHECK(labs((long)updates - (long)(rates[k] * n / SR)) <= 1, "rate %g: %zu holds in 1 s", rates[k], updates);
    }
}

static void test_antialias(void)
{
    float *in = malloc(N * sizeof *in), *a = malloc(N * sizeof *a), *b = malloc(N * sizeof *b);
    FxParams p;
    double alias_off, alias_on;
    sig_sine(in, N, SR, 7000.0f, 0.5f);                   /* 7 kHz held at 8 kHz aliases to 1 kHz */
    set(&p, 0, 8000, 16, 0, 1, 0, 100, 0); render(&p, in, a, N, 16);
    set(&p, 0, 8000, 16, 0, 1, 0, 100, 1); render(&p, in, b, N, 16);
    alias_off = goertzel(a + N / 2, N / 2, 1000);
    alias_on = goertzel(b + N / 2, N / 2, 1000);
    CHECK(alias_on < alias_off * 0.5, "anti-alias: 1 kHz alias %g with, %g without", alias_on, alias_off);
    free(in); free(a); free(b);
}

/* Three named variants; each must sound different from the others and from dry. */
static const struct { const char *name; float v[G_NPARAMS]; } VARIANTS[] = {
    { "crush",  { 12, 6000, 4, 0, 0.7f, -6, 100, 0 } },
    { "fold",   { 24, 48000, 16, 4, 0.9f, -9, 100, 1 } },
    { "radio",  { 18, 3000, 6, 13, 0.35f, -3, 100, 0 } },
};
#define NVAR (sizeof VARIANTS / sizeof VARIANTS[0])

static void variants(const float *chord, double *metric)
{
    float *out[NVAR];
    size_t i, j;
    for (i = 0; i < NVAR; i++) {
        FxParams p;
        memset(&p, 0, sizeof p);
        memcpy(p.value, VARIANTS[i].v, sizeof VARIANTS[i].v);
        out[i] = malloc(N * sizeof(float));
        render(&p, chord, out[i], N, 16);
        metric[2 * i] = rms(out[i], N);
        metric[2 * i + 1] = goertzel(out[i], N, 1000.0);
        CHECK(all_finite_bounded(out[i], N), "variant %s bad output", VARIANTS[i].name);
        CHECK(rms_diff(out[i], chord, N) > 0.1 * rms(chord, N), "variant %s is too close to dry", VARIANTS[i].name);
    }
    for (i = 0; i < NVAR; i++)
        for (j = 0; j < i; j++)
            CHECK(rms_diff(out[i], out[j], N) > 0.1 * (rms(out[i], N) + rms(out[j], N)) / 2,
                  "variants %s and %s are too similar", VARIANTS[i].name, VARIANTS[j].name);
    for (i = 0; i < NVAR; i++) free(out[i]);
}

int main(int argc, char **argv)
{
    static const float CHORD[] = { 82.41f, 123.47f, 164.81f, 207.65f, 246.94f, 329.63f };
    float *chord = malloc(N * sizeof *chord), *noise = malloc(N * sizeof *noise);
    double metric[2 * NVAR];
    size_t i;
    int write = argc == 3 && !strcmp(argv[1], "--write-golden");

    sig_chord(chord, N, SR, CHORD, 6, 960, 1.6f);
    sig_noise(noise, N, 7, 0.25f);
    test_curves();
    test_quantizer();
    test_dry(chord, noise);
    test_determinism_and_blocks(chord);
    test_instances(chord, noise);
    test_robustness(chord);
    test_decimator();
    test_antialias();
    variants(chord, metric);

    if (write) {
        FILE *f = fopen(argv[2], "w");
        if (!f) { printf("cannot write %s\n", argv[2]); return 1; }
        for (i = 0; i < 2 * NVAR; i++) fprintf(f, "%s %s %.9g\n", VARIANTS[i / 2].name, i % 2 ? "1k" : "rms", metric[i]);
        fclose(f);
        printf("wrote %s\n", argv[2]);
    } else if (argc == 2) {                               /* golden metrics, 1e-4 relative */
        FILE *f = fopen(argv[1], "r");
        char name[32], kind[8];
        double v;
        CHECK(f != NULL, "no golden file %s", argv[1]);
        for (i = 0; f && i < 2 * NVAR && fscanf(f, "%31s %7s %lf", name, kind, &v) == 3; i++)
            CHECK(fabs(metric[i] - v) <= 1e-4 * fabs(v) + 1e-9, "golden %s %s: %.9g, expected %.9g", name, kind, metric[i], v);
        CHECK(i == 2 * NVAR, "golden file has %zu of %zu values", i, (size_t)(2 * NVAR));
        if (f) fclose(f);
    }
    free(chord); free(noise);
    printf("%d checks, %d failed\n", checks, failures);
    return failures ? 1 : 0;
}
