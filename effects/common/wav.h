/* wav.h - minimal RIFF/WAVE I/O for the offline renderer and tests.
 * Reads PCM 16/24/32-bit and IEEE float 32-bit, any channel count (mixed to mono).
 * Writes mono IEEE float 32-bit. */
#ifndef WAV_H
#define WAV_H

#include <stddef.h>

typedef struct {
    float *data;        /* mono samples, malloc'd: free with wav_free */
    size_t frames;
    int rate;
} Wav;

int wav_read(const char *path, Wav *w, char *err, size_t errlen);
int wav_write(const char *path, const float *data, size_t frames, int rate);
void wav_free(Wav *w);

#endif
