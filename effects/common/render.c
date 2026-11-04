/* fxrender - offline renderer for the reference effects.
 *
 *   fxrender list
 *   fxrender describe <effect>                   the parameter descriptor as JSON
 *   fxrender fixtures <dir>                      write the generated test signals as WAVs
 *   fxrender <effect> <in.wav> <out.wav> [id=value ...] [--block N]
 *
 * Audio is processed in 16-sample blocks by default, as the unit calls a primitive.
 */
#include "fx.h"
#include "signals.h"
#include "wav.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *type_name(FxParamType t)
{
    return t == FX_INTEGER ? "integer" : t == FX_TOGGLE ? "toggle" : "continuous";
}

static void describe(const FxAlgorithm *a)
{
    size_t i;
    printf("{\n  \"id\": \"%s\",\n  \"display_name\": \"%s\",\n  \"parameters\": [\n", a->name, a->display_name);
    for (i = 0; i < a->n_params; i++) {
        const FxParamDesc *d = &a->params[i];
        printf("    {\"id\": \"%s\", \"display\": \"%s\", \"type\": \"%s\", \"min\": %g, \"max\": %g, "
               "\"default\": %g, \"unit\": \"%s\", \"smoothing\": \"%s\"}%s\n",
               d->id, d->display, type_name(d->type), d->min, d->max, d->def, d->unit, d->smoothing,
               i + 1 < a->n_params ? "," : "");
    }
    printf("  ]\n}\n");
}

static int fixtures(const char *dir)
{
    const float R = FX_DEVICE_RATE;
    const size_t N = (size_t)(4 * R);
    static const float CHORD[] = { 82.41f, 123.47f, 164.81f, 207.65f, 246.94f, 329.63f };   /* open E */
    float *x = malloc(N * sizeof *x);
    char path[1024];
    int fail = 0;
    if (!x) return 1;
#define OUT(name) do { snprintf(path, sizeof path, "%s/%s.wav", dir, name); fail |= wav_write(path, x, N, (int)R); } while (0)
    sig_silence(x, N); OUT("silence");
    sig_impulse(x, N, 0.5f); OUT("impulse");
    sig_step(x, N, 0.25f); OUT("step");
    sig_sine(x, N, R, 110.0f, 0.5f); OUT("sine_110");
    sig_sine(x, N, R, 1000.0f, 0.5f); OUT("sine_1k");
    sig_sweep(x, N, R, 20.0f, 20000.0f, 0.5f); OUT("sweep");
    sig_noise(x, N, 7, 0.25f); OUT("noise");
    sig_pluck(x, N, R, 82.41f, 0.8f, 1); OUT("pluck_low_e");
    sig_pluck(x, N, R, 329.63f, 0.8f, 2); OUT("pluck_high_e");
    sig_chord(x, N, R, CHORD, 6, 960, 1.6f); OUT("chord_e");
#undef OUT
    free(x);
    if (fail) fprintf(stderr, "fxrender: could not write into %s\n", dir);
    return fail ? 1 : 0;
}

int main(int argc, char **argv)
{
    const FxAlgorithm *a;
    FxParams p;
    Wav w;
    char err[256];
    float *out;
    void *state;
    size_t block = FX_DEVICE_BLOCK, i;
    int k;

    if (argc >= 2 && !strcmp(argv[1], "list")) {
        size_t n, j;
        const FxAlgorithm *const *all = fx_all(&n);
        for (j = 0; j < n; j++) printf("%s\t%s\n", all[j]->name, all[j]->display_name);
        return 0;
    }
    if (argc == 3 && !strcmp(argv[1], "describe")) {
        if (!(a = fx_find(argv[2]))) { fprintf(stderr, "fxrender: no effect %s\n", argv[2]); return 1; }
        describe(a);
        return 0;
    }
    if (argc == 3 && !strcmp(argv[1], "fixtures"))
        return fixtures(argv[2]);
    if (argc < 4) {
        fprintf(stderr, "usage: fxrender list | describe <effect> | fixtures <dir> |\n"
                        "       <effect> <in.wav> <out.wav> [id=value ...] [--block N]\n");
        return 2;
    }
    if (!(a = fx_find(argv[1]))) { fprintf(stderr, "fxrender: no effect %s\n", argv[1]); return 1; }
    fx_defaults(a, &p);
    for (k = 4; k < argc; k++) {
        char *eq = strchr(argv[k], '=');
        int idx;
        if (!strcmp(argv[k], "--block") && k + 1 < argc) { block = (size_t)atoi(argv[++k]); continue; }
        if (!eq) { fprintf(stderr, "fxrender: expected id=value, got %s\n", argv[k]); return 2; }
        *eq = 0;
        if ((idx = fx_param_index(a, argv[k])) < 0) { fprintf(stderr, "fxrender: %s has no parameter %s\n", a->name, argv[k]); return 2; }
        p.value[idx] = (float)atof(eq + 1);
    }
    if (block < 1) block = 1;
    if (wav_read(argv[2], &w, err, sizeof err)) { fprintf(stderr, "fxrender: %s\n", err); return 1; }
    if (w.rate != (int)FX_DEVICE_RATE)
        fprintf(stderr, "fxrender: note: %s is %d Hz; the unit runs at %d Hz\n", argv[2], w.rate, (int)FX_DEVICE_RATE);
    out = malloc((w.frames ? w.frames : 1) * sizeof *out);
    state = malloc(a->state_bytes);
    if (!out || !state) { fprintf(stderr, "fxrender: out of memory\n"); return 1; }
    a->reset(state, (float)w.rate);
    for (i = 0; i < w.frames; i += block)
        a->process(state, &p, w.data + i, out + i, w.frames - i < block ? w.frames - i : block);
    if (wav_write(argv[3], out, w.frames, w.rate)) { fprintf(stderr, "fxrender: cannot write %s\n", argv[3]); return 1; }
    wav_free(&w);
    free(out);
    free(state);
    return 0;
}
