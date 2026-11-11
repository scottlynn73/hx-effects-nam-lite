#include "fx.h"

#include <math.h>
#include <string.h>

extern const FxAlgorithm fx_commander;
extern const FxAlgorithm fx_corrupt;
extern const FxAlgorithm fx_ottobit;
extern const FxAlgorithm fx_stutter;
extern const FxAlgorithm fx_syntax;
extern const FxAlgorithm fx_grains;
extern const FxAlgorithm fx_sequence;
extern const FxAlgorithm fx_warp;
extern const FxAlgorithm fx_doomchug;
extern const FxAlgorithm fx_geiger;
extern const FxAlgorithm fx_metronome;

static const FxAlgorithm *const ALL[] = { &fx_commander, &fx_corrupt, &fx_geiger, &fx_metronome, &fx_ottobit, &fx_stutter, &fx_syntax, &fx_grains, &fx_sequence, &fx_warp, &fx_doomchug };

const FxAlgorithm *const *fx_all(size_t *n)
{
    *n = sizeof ALL / sizeof ALL[0];
    return ALL;
}

const FxAlgorithm *fx_find(const char *name)
{
    size_t n, i;
    const FxAlgorithm *const *all = fx_all(&n);
    for (i = 0; i < n; i++)
        if (strcmp(all[i]->name, name) == 0)
            return all[i];
    return NULL;
}

void fx_defaults(const FxAlgorithm *a, FxParams *p)
{
    size_t i;
    memset(p, 0, sizeof *p);
    for (i = 0; i < a->n_params && i < FX_MAX_CONTROLS; i++)
        p->value[i] = a->params[i].def;
}

int fx_param_index(const FxAlgorithm *a, const char *id)
{
    size_t i;
    for (i = 0; i < a->n_params; i++)
        if (strcmp(a->params[i].id, id) == 0)
            return (int)i;
    return -1;
}

float fx_param_clamp(const FxParamDesc *d, float v)
{
    if (!(v == v))                          /* NaN: the default */
        v = d->def;
    if (v < d->min) v = d->min;
    if (v > d->max) v = d->max;
    if (d->type != FX_CONTINUOUS)
        v = floorf(v + 0.5f);
    return v;
}

int fx_set_ftz(int on)
{
#if defined(__aarch64__)
    unsigned long fpcr;
    __asm__ volatile("mrs %0, fpcr" : "=r"(fpcr));
    fpcr = on ? (fpcr | (1ul << 24)) : (fpcr & ~(1ul << 24));          /* FPCR.FZ */
    __asm__ volatile("msr fpcr, %0" : : "r"(fpcr));
    return 1;
#elif defined(__x86_64__)
    unsigned int csr;
    __asm__ volatile("stmxcsr %0" : "=m"(csr));
    csr = on ? (csr | 0x8040u) : (csr & ~0x8040u);                      /* FTZ and DAZ */
    __asm__ volatile("ldmxcsr %0" : : "m"(csr));
    return 1;
#else
    (void)on;
    return 0;
#endif
}
