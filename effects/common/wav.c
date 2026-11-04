#include "wav.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint32_t rd32(const unsigned char *p) { return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24; }
static uint16_t rd16(const unsigned char *p) { return (uint16_t)(p[0] | p[1] << 8); }

static void wr32(FILE *f, uint32_t v) { unsigned char b[4] = { v & 255, v >> 8 & 255, v >> 16 & 255, v >> 24 }; fwrite(b, 1, 4, f); }
static void wr16(FILE *f, uint16_t v) { unsigned char b[2] = { v & 255, v >> 8 }; fwrite(b, 1, 2, f); }

int wav_read(const char *path, Wav *w, char *err, size_t errlen)
{
    FILE *f = fopen(path, "rb");
    unsigned char *buf = NULL, *fmt = NULL, *dat = NULL;
    long len;
    size_t pos = 12, datlen = 0, i;
    int fmt_tag = 0, ch = 0, bits = 0;

    memset(w, 0, sizeof *w);
    if (!f) { snprintf(err, errlen, "%s: cannot open", path); return -1; }
    fseek(f, 0, SEEK_END);
    len = ftell(f);
    fseek(f, 0, SEEK_SET);
    buf = malloc((size_t)len);
    if (!buf || fread(buf, 1, (size_t)len, f) != (size_t)len) { fclose(f); free(buf); snprintf(err, errlen, "%s: read failed", path); return -1; }
    fclose(f);
    if (len < 12 || memcmp(buf, "RIFF", 4) || memcmp(buf + 8, "WAVE", 4)) { free(buf); snprintf(err, errlen, "%s: not a WAV file", path); return -1; }
    while (pos + 8 <= (size_t)len) {
        uint32_t sz = rd32(buf + pos + 4);
        if (pos + 8 + sz > (size_t)len) sz = (uint32_t)((size_t)len - pos - 8);
        if (!memcmp(buf + pos, "fmt ", 4) && sz >= 16) fmt = buf + pos + 8;
        if (!memcmp(buf + pos, "data", 4)) { dat = buf + pos + 8; datlen = sz; }
        pos += 8 + sz + (sz & 1);
    }
    if (!fmt || !dat) { free(buf); snprintf(err, errlen, "%s: no fmt or data chunk", path); return -1; }
    fmt_tag = rd16(fmt);
    ch = rd16(fmt + 2);
    w->rate = (int)rd32(fmt + 4);
    bits = rd16(fmt + 14);
    if (fmt_tag == 0xfffe && rd16(fmt + 16) >= 22) fmt_tag = rd16(fmt + 24);   /* WAVE_FORMAT_EXTENSIBLE */
    if (ch < 1 || !((fmt_tag == 1 && (bits == 16 || bits == 24 || bits == 32)) || (fmt_tag == 3 && bits == 32))) {
        free(buf); snprintf(err, errlen, "%s: unsupported format (tag %d, %d bits)", path, fmt_tag, bits); return -1;
    }
    w->frames = datlen / (size_t)(ch * bits / 8);
    w->data = calloc(w->frames ? w->frames : 1, sizeof(float));
    if (!w->data) { free(buf); snprintf(err, errlen, "out of memory"); return -1; }
    for (i = 0; i < w->frames; i++) {
        double acc = 0;
        int c;
        for (c = 0; c < ch; c++) {
            const unsigned char *p = dat + (i * (size_t)ch + (size_t)c) * (size_t)(bits / 8);
            double v;
            if (fmt_tag == 3) { float x; uint32_t u = rd32(p); memcpy(&x, &u, 4); v = x; }
            else if (bits == 16) v = (int16_t)rd16(p) / 32768.0;
            else if (bits == 24) v = (double)((int32_t)((uint32_t)p[0] << 8 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 24) >> 8) / 8388608.0;
            else v = (int32_t)rd32(p) / 2147483648.0;
            acc += v;
        }
        w->data[i] = (float)(acc / ch);
    }
    free(buf);
    return 0;
}

int wav_write(const char *path, const float *data, size_t frames, int rate)
{
    FILE *f = fopen(path, "wb");
    size_t i;
    if (!f) return -1;
    fwrite("RIFF", 1, 4, f); wr32(f, (uint32_t)(36 + 4 * frames)); fwrite("WAVE", 1, 4, f);
    fwrite("fmt ", 1, 4, f); wr32(f, 16); wr16(f, 3); wr16(f, 1); wr32(f, (uint32_t)rate);
    wr32(f, (uint32_t)rate * 4); wr16(f, 4); wr16(f, 32);
    fwrite("data", 1, 4, f); wr32(f, (uint32_t)(4 * frames));
    for (i = 0; i < frames; i++) { uint32_t u; memcpy(&u, &data[i], 4); wr32(f, u); }
    return fclose(f) ? -1 : 0;
}

void wav_free(Wav *w)
{
    free(w->data);
    w->data = NULL;
    w->frames = 0;
}
