/* test_syntax - Syntax's reference tests (no hardware, no files). */
#include "syntax.h"
#include "../common/signals.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SR 48000.0f
#define N  ((size_t)(2 * 48000))

static int failures, checks;

#define CHECK(cond, ...) do { checks++; if (!(cond)) { failures++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static void set(FxParams *p, float drive, float shift, int pattern, float speed, float glide, float tone, float output,
                float mix)
{
    memset(p, 0, sizeof *p);
    p->value[Y_DRIVE] = drive; p->value[Y_SHIFT] = shift; p->value[Y_PATTERN] = (float)pattern;
    p->value[Y_SPEED] = speed; p->value[Y_GLIDE] = glide; p->value[Y_TONE] = tone; p->value[Y_OUTPUT] = output;
    p->value[Y_MIX] = mix;
}

static void render(const FxParams *p, const float *in, float *out, size_t n, size_t block)
{
    SyntaxState s;
    size_t i;
    fx_syntax.reset(&s, SR);
    for (i = 0; i < n; i += block)
        fx_syntax.process(&s, p, in + i, out + i, n - i < block ? n - i : block);
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
    double up, dn, at;
    int b, k;
    if (!x || !y || !z) return 2;

    for (k = 0; k < SYNTAX_PATTERNS; k++)
        for (b = 0; b < SYNTAX_STEPS; b++)
            CHECK(fabsf(syntax_pattern(k)[b]) <= 2.0f && (k || syntax_pattern(k)[b] == 1.0f), "pattern %d step %d", k, b);

    /* Shift 100 Hz on a quiet 1 kHz tone: 1,100 Hz, the lower sideband at least 30 dB down */
    sig_sine(x, N, SR, 1000.0f, 0.1f);
    set(&p, 0, 100, 0, 4, 0, 1, 0, 1); render(&p, x, y, N, 16);
    up = goertzel(y + N / 2, N / 2, 1100.0); dn = goertzel(y + N / 2, N / 2, 900.0); at = goertzel(y + N / 2, N / 2, 1000.0);
    CHECK(up > 0.05 && up > 31.6 * dn && up > 31.6 * at, "shift +100: 1100 %g, 900 %g, 1000 %g", up, dn, at);

    /* Shift 0: the tone stays where it is, at the soft clip's small-signal gain (1.5, +3.5 dB) */
    set(&p, 0, 0, 0, 4, 0, 1, 0, 1); render(&p, x, y, N, 16);
    at = goertzel(y + N / 2, N / 2, 1000.0);
    CHECK(fabs(20 * log10(at / 0.15)) < 1.0, "shift 0: 1 kHz at %g dB re 0.15", 20 * log10(at / 0.15));

    /* Pattern 1 (up, down) at 2 steps a second: up in the first step, down in the second */
    set(&p, 0, 200, 1, 2, 0, 1, 0, 1); render(&p, x, y, N, 16);
    up = goertzel(y + 4000, 16000, 1200.0); dn = goertzel(y + 4000, 16000, 800.0);
    CHECK(up > 10 * dn, "pattern 1 step 1: 1200 %g, 800 %g", up, dn);
    up = goertzel(y + 28000, 16000, 1200.0); dn = goertzel(y + 28000, 16000, 800.0);
    CHECK(dn > 10 * up, "pattern 1 step 2: 1200 %g, 800 %g", up, dn);

    /* Glide 1: half a second into step 2, the shift is still on its way down */
    set(&p, 0, 200, 1, 2, 1, 1, 0, 1); render(&p, x, z, N, 16);
    dn = goertzel(z + 28000, 16000, 800.0);
    CHECK(dn < 0.5 * goertzel(y + 28000, 16000, 800.0), "Glide 1: 800 Hz already %g", dn);

    /* Mix 0: the input exactly */
    sig_noise(x, N, 9, 0.5f);
    set(&p, 20, 300, 4, 8, 0.5f, 0.5f, 6, 0); render(&p, x, y, N, 16);
    CHECK(memcmp(x, y, N * sizeof *x) == 0, "Mix 0: not the input");

    /* any block size gives the same output */
    sig_chord(x, N, SR, CHORD, 6, 960, 1.6f);
    set(&p, 18, 250, 8, 6, 0.3f, 0.6f, -3, 0.8f);
    render(&p, x, y, N, 16);
    for (b = 1; b <= 97; b += 48) {
        render(&p, x, z, N, (size_t)b);
        CHECK(memcmp(y, z, N * sizeof *y) == 0, "block size %d differs from 16", b);
    }
    CHECK(bounded(y, N), "chord: output not finite and bounded");

    /* hostile input and parameters stay finite and bounded */
    sig_noise(x, N, 4, 4.0f);
    x[100] = NAN; x[200] = INFINITY; x[300] = -1e30f;
    set(&p, 99, 1e9f, 99, 1e9f, 9, 9, 99, 9); render(&p, x, y, N, 16);
    CHECK(bounded(y, N), "hostile input: output not finite and bounded");
    set(&p, -9, -9, -9, -9, -9, -9, -99, -9); render(&p, x, y, N, 16);
    CHECK(bounded(y, N), "hostile low parameters: output not finite and bounded");

    printf("%d checks, %d failures\n", checks, failures);
    free(x); free(y); free(z);
    return failures ? 1 : 0;
}
