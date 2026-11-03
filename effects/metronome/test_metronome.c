/* test_metronome - the Click block's acceptance tests 1-4 (docs: effects/README.md).
 * Fast, non-realtime: ten minutes of audio per tempo in well under a second. */
#include "metronome.h"
#include "../common/signals.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SR 48000.0f

static int failures, checks;

#define CHECK(cond, ...) do { checks++; if (!(cond)) { failures++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static void set(FxParams *p, float tempo, int meter, float accent, int sound, float level, int sub)
{
    memset(p, 0, sizeof *p);
    p->value[M_TEMPO] = tempo; p->value[M_METER] = (float)meter; p->value[M_ACCENT] = accent;
    p->value[M_SOUND] = (float)sound; p->value[M_LEVEL] = level; p->value[M_SUBDIV] = (float)sub;
}

/* Run n samples of silence one sample at a time; record each tick's sample index and kind. */
static size_t ticks(const FxParams *p, size_t n, uint32_t *at, int *kind, size_t max)
{
    MetronomeState m;
    size_t i, k = 0;
    float x = 0.0f, y;
    fx_metronome.reset(&m, SR);
    for (i = 0; i < n; i++) {
        uint32_t before = m.ticks;
        fx_metronome.process(&m, p, &x, &y, 1);
        if (m.ticks != before && k < max) {
            at[k] = (uint32_t)i;
            kind[k] = m.last_kind;
            k++;
        }
    }
    return k;
}

/* 1. Exact long-term tempo: ten minutes at 20, 60, 120, 137 and 300 BPM. */
static void test_tempo(void)
{
    static const float bpms[] = { 20.0f, 60.0f, 120.0f, 137.0f, 300.0f };
    const size_t n = (size_t)(600 * SR);
    size_t b;
    uint32_t *at = malloc(4000 * sizeof *at);
    int *kind = malloc(4000 * sizeof *kind);
    for (b = 0; b < sizeof bpms / sizeof bpms[0]; b++) {
        FxParams p;
        size_t k, cnt;
        double interval = SR * 60.0 / bpms[b], worst = 0;
        set(&p, bpms[b], 4, 6, 0, 0.5f, 1);
        cnt = ticks(&p, n, at, kind, 4000);
        CHECK(cnt == (size_t)floor((n - 1) / interval) + 1, "%g BPM: %zu ticks in 10 min, expected %zu",
              bpms[b], cnt, (size_t)floor((n - 1) / interval) + 1);
        for (k = 0; k < cnt; k++) {                      /* each tick: the first sample at/after its time */
            double ideal = k * interval, e = at[k] - ideal;
            CHECK(e >= 0 && e < 1.0, "%g BPM: tick %zu at %u, ideal %.3f", bpms[b], k, at[k], ideal);
            if (fabs(e) > worst) worst = fabs(e);
            if (e < 0 || e >= 1.0) break;
        }
        printf("  %6.1f BPM: %4zu ticks in 10 min, worst offset %.3f samples, no drift\n", bpms[b], cnt, worst);
    }
    free(at); free(kind);
}

/* 2. Downbeat and accents in 2/4..5/4, and with subdivisions. */
static void test_bar(void)
{
    uint32_t at[200];
    int kind[200], meter, sub;
    for (meter = 2; meter <= 5; meter++)
        for (sub = 1; sub <= 4; sub++) {
            FxParams p;
            size_t k, cnt;
            int ok = 1;
            set(&p, 120, meter, 6, 0, 0.5f, sub);
            cnt = ticks(&p, (size_t)(20 * SR), at, kind, 200);
            CHECK(cnt > 0 && at[0] == 0 && kind[0] == CLICK_ACCENT, "%d/4 x%d: first tick not an accent at sample 0", meter, sub);
            for (k = 0; k < cnt; k++) {
                int pos_sub = (int)(k % (size_t)sub), pos_beat = (int)(k / (size_t)sub % (size_t)meter);
                int want = pos_sub ? CLICK_SUB : pos_beat ? CLICK_BEAT : CLICK_ACCENT;
                if (kind[k] != want) ok = 0;
            }
            CHECK(ok, "%d/4 x%d: accent/beat/subdivision pattern wrong", meter, sub);
        }
}

/* 3. Level 0 is exactly the input; otherwise the output is input + a bounded click. */
static void test_passthrough(void)
{
    const size_t n = (size_t)(8 * SR);
    static const float CHORD[] = { 82.41f, 123.47f, 164.81f, 207.65f, 246.94f, 329.63f };
    float *in = malloc(n * sizeof *in), *out = malloc(n * sizeof *out), *click = malloc(n * sizeof *click), *zero = calloc(n, sizeof *zero);
    MetronomeState m;
    FxParams p;
    size_t i;
    int s, same;
    double worst = 0, peak = 0;
    sig_chord(in, n, SR, CHORD, 6, 960, 1.6f);
    set(&p, 120, 4, 12, 0, 0.0f, 4);
    fx_metronome.reset(&m, SR);
    for (i = 0; i < n; i += 16) fx_metronome.process(&m, &p, in + i, out + i, 16);
    CHECK(!memcmp(in, out, n * sizeof *in), "Level 0 changes the guitar");
    for (s = 0; s < SOUNDS; s++) {
        set(&p, 137.0f, 3, 12, s, 1.0f, 3);
        fx_metronome.reset(&m, SR);
        for (i = 0; i < n; i += 16) fx_metronome.process(&m, &p, in + i, out + i, 16);
        fx_metronome.reset(&m, SR);
        for (i = 0; i < n; i += 16) fx_metronome.process(&m, &p, zero + i, click + i, 16);
        same = 1;
        for (i = 0; i < n; i++) {
            double e = fabs((double)out[i] - in[i] - click[i]);
            if (e > worst) worst = e;
            if (fabs(click[i]) > peak) peak = fabs(click[i]);
            if (click[i] == 0.0f && out[i] != in[i]) same = 0;
        }
        CHECK(same, "sound %d: guitar altered between clicks", s);
    }
    CHECK(worst <= 1e-6, "output - input differs from the click by %g", worst);
    CHECK(peak <= 1.0 && peak > 0.5, "click peak %g (expected (0.5, 1])", peak);
    free(in); free(out); free(click); free(zero);
}

/* 4. Tempo/meter/subdivision changes, NaN knobs, resets, two instances: no bad floats, no
 *    double triggers, no stuck tones, no cross-talk; output independent of block size. */
static void test_robustness(void)
{
    const size_t n = (size_t)(120 * SR);
    float *in = calloc(n, sizeof *in), *a = malloc(n * sizeof *a), *b = malloc(n * sizeof *b);
    float *ra = malloc(n * sizeof *ra), *rb = malloc(n * sizeof *rb);
    MetronomeState s1, s2;
    FxParams p, p1, p2;
    Rng r;
    size_t i, last_tick = 0, worst_run = 0;
    uint32_t prev = 0;
    int ok = 1, dbl = 0, first = 1;
    static const size_t blocks[] = { 1, 16, 37, 4096 };
    size_t k;

    rng_seed(&r, 99);
    fx_metronome.reset(&s1, SR);
    for (i = 0; i < n; i += 16) {
        size_t j;
        if (i % 4800 == 0) {                             /* knobs move every 100 ms */
            set(&p, 20 + 280 * (rng_uniform(&r) + 1) / 2, 2 + (int)(rng_u32(&r) % 4), 12 * (rng_uniform(&r) + 1) / 2,
                (int)(rng_u32(&r) % 3), (rng_uniform(&r) + 1) / 2, 1 + (int)(rng_u32(&r) % 4));
            if (rng_u32(&r) % 9 == 0) p.value[rng_u32(&r) % M_NPARAMS] = NAN;
            if (rng_u32(&r) % 50 == 0) fx_metronome.reset(&s1, SR);
        }
        for (j = 0; j < 16; j++) {
            uint32_t before = s1.ticks;
            fx_metronome.process(&s1, &p, in + i + j, a + i + j, 1);
            if (!isfinite(a[i + j]) || fabsf(a[i + j]) > 1.0f) ok = 0;
            if (s1.ticks != before) {
                if (!first && s1.ticks != 1 && i + j - last_tick < 2399) dbl = 1;   /* (T - inc) / inc_max: 300 BPM x 4 */
                last_tick = i + j; first = 0;
            }
            if (s1.ticks < prev) last_tick = i + j;      /* a reset restarts the count */
            prev = s1.ticks;
            if (s1.active && s1.age > worst_run) worst_run = s1.age;   /* samples since its trigger */
        }
    }
    CHECK(ok, "bad or unbounded output under random knob changes");
    CHECK(!dbl, "two ticks closer than the fastest possible interval");
    CHECK(worst_run <= (size_t)(0.2 * SR) + 1, "a voice stayed on for %zu samples after its trigger", worst_run);

    set(&p1, 97.0f, 3, 6, 0, 0.8f, 2);                     /* two instances, interleaved */
    set(&p2, 211.0f, 5, 12, 1, 0.6f, 3);
    for (i = 0; i < n; i++) in[i] = 0.1f * sinf((float)i * 0.01f);
    fx_metronome.reset(&s1, SR);
    for (i = 0; i < n; i += 16) fx_metronome.process(&s1, &p1, in + i, ra + i, 16);
    fx_metronome.reset(&s2, SR);
    for (i = 0; i < n; i += 16) fx_metronome.process(&s2, &p2, in + i, rb + i, 16);
    fx_metronome.reset(&s1, SR);
    fx_metronome.reset(&s2, SR);
    for (i = 0; i < n; i += 16) {
        fx_metronome.process(&s1, &p1, in + i, a + i, 16);
        fx_metronome.process(&s2, &p2, in + i, b + i, 16);
    }
    CHECK(!memcmp(a, ra, n * sizeof *a) && !memcmp(b, rb, n * sizeof *b), "instances interfere");
    for (k = 0; k < sizeof blocks / sizeof blocks[0]; k++) {
        fx_metronome.reset(&s1, SR);
        for (i = 0; i < n; i += blocks[k]) fx_metronome.process(&s1, &p1, in + i, b + i, n - i < blocks[k] ? n - i : blocks[k]);
        CHECK(!memcmp(b, ra, n * sizeof *b), "block size %zu changes the output", blocks[k]);
    }

    set(&p, 20, 4, 6, 2, 1.0f, 1);                       /* the voice ends long before the next beat */
    ok = 1;
    fx_metronome.reset(&s1, SR);
    for (i = 0; i < (size_t)(3 * SR) - 1; i += 1) {
        fx_metronome.process(&s1, &p, in + i, a + i, 1);
        if (i > (size_t)(0.2 * SR) && a[i] != in[i]) { ok = 0; break; }
    }
    CHECK(ok, "click still sounding 200 ms after the beat");
    free(in); free(a); free(b); free(ra); free(rb);
}

int main(void)
{
    test_tempo();
    test_bar();
    test_passthrough();
    test_robustness();
    printf("%d checks, %d failed\n", checks, failures);
    return failures ? 1 : 0;
}
