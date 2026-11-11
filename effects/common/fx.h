/* fx.h - the portable reference API for custom effects (C99).
 *
 * This is the specification and test harness side only. It says nothing about the SHARC
 * primitive's real calling convention (docs/baseline-audit.md): a native kernel is a
 * separate, hand-written port that must match this reference within a stated tolerance.
 *
 * Rules for an algorithm:
 *  - all state lives in the caller-provided block of state_bytes (no globals that change
 *    after initialisation, no malloc, no I/O, no locks);
 *  - reset() fully defines the state; process() never reads uninitialised memory;
 *  - process() accepts any frame count and gives the same output whatever the block size;
 *  - output is always finite.
 */
#ifndef FX_H
#define FX_H

#include <stddef.h>
#include <stdint.h>

#define FX_MAX_CONTROLS 12
#define FX_DEVICE_BLOCK 16          /* samples per primitive call on the unit (modelled) */
#define FX_DEVICE_RATE 48000.0f     /* assumed device sample rate */

typedef struct {
    float value[FX_MAX_CONTROLS];
} FxParams;

typedef enum { FX_CONTINUOUS, FX_INTEGER, FX_TOGGLE } FxParamType;

typedef struct {
    const char *id;
    const char *display;
    FxParamType type;
    float min, max, def;
    const char *unit;
    const char *smoothing;          /* "per-sample" (one-pole), "immediate" */
} FxParamDesc;

typedef struct {
    const char *name;
    const char *display_name;
    size_t state_bytes;
    const FxParamDesc *params;
    size_t n_params;
    void (*reset)(void *state, float sample_rate);
    void (*process)(void *state, const FxParams *params,
                    const float *in, float *out, size_t frames);
} FxAlgorithm;

/* Fill p with each parameter's default. */
void fx_defaults(const FxAlgorithm *a, FxParams *p);
/* Index of parameter id, or -1. */
int fx_param_index(const FxAlgorithm *a, const char *id);
/* Clamp (and round integers / toggles) to the declared range. */
float fx_param_clamp(const FxParamDesc *d, float v);

/* Flush denormal inputs and results to zero (on) or not (off), as the SHARC always does: the SHARC kernels'
   checks run the reference this way, so the two agree to the bit even where a value underflows. Returns 1
   if this machine supports it (arm64, x86-64), else 0. */
int fx_set_ftz(int on);

/* The registry: every algorithm the renderer and tests know. */
const FxAlgorithm *fx_find(const char *name);
const FxAlgorithm *const *fx_all(size_t *n);

#endif
