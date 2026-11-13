#!/usr/bin/env python3
"""How loud a NAM A2 Lite capture plays on the unit, so captures can be level-matched (tools/nam2ir.py --match).

measure(w, dbu) runs the model in numpy (float64; the same network as src/sharc/nam_a2.asm, checked against it in
ssim to about 1e-6) on a fixed test signal: a strummed E-A-D chord, 1 s, peaking at -10 dBFS, scaled by the input
trim the kernel gives a capture made at `dbu` (nam_lite.input_trim). The output's loudness is K-weighted
(ITU-R BS.1770, 48 kHz) mean square in dB: LUFS-like, with Drive, the tone stack and Ch Vol at 5.0 (flat, x1).

gain_for(w, dbu, target) is the factor on the model's output scale (its last weight; the head is linear, so this
changes the level and nothing else) that brings it to `target`.

usage: nam_level.py <model.nam>...   prints each capture's level and the correction to TARGET
"""
import math
import os
import sys

import numpy as np

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import nam_lite  # noqa: E402
import nam_pack  # noqa: E402

TARGET = -18.0          # dB, K-weighted, on the test signal: the default for nam2ir.py --match
FS = 48000
PAD = 8192              # zeros before the signal: longer than the network's receptive field (the silence state)
# BS.1770 K-weighting at 48 kHz: high shelf, then high pass
K_SHELF = ((1.53512485958697, -2.69169618940638, 1.19839281085285), (1.0, -1.69065929318241, 0.73248077421585))
K_HPF = ((1.0, -2.0, 1.0), (1.0, -1.99004745483398, 0.99007225036621))


def test_signal(n=FS, peak_db=-10.0):
    """A strummed E-A-D chord: three decaying six-harmonic tones 15 ms apart, peaking at peak_db."""
    t = np.arange(n) / FS
    out = np.zeros(n)
    for k, f0 in enumerate((82.41, 110.0, 146.83)):
        t0 = int(k * 0.015 * FS)
        tt = t[:n - t0]
        tone = sum((0.6 ** h) * np.sin(2 * math.pi * f0 * (h + 1) * tt) for h in range(6))
        out[t0:] += np.exp(-3.0 * tt) * tone
    return out * (10 ** (peak_db / 20) / np.max(np.abs(out)))


def _causal(x, W, d):
    """y[o, n] = sum_t,j W[o, j, t] x[j, n - (k-1-t) d] (a causal dilated convolution, zeros before)."""
    co, ci, k = W.shape
    n = x.shape[1]
    y = np.zeros((co, n))
    for t in range(k):
        s = (k - 1 - t) * d
        if s < n:
            y[:, s:] += W[:, :, t] @ x[:, :n - s]
    return y


def forward(w, sig, c=nam_lite.C):
    """The model's output for `sig`, from the silence state (PAD zeros first)."""
    w = np.asarray(w, float)
    u = np.concatenate([np.zeros(PAD), np.asarray(sig, float)])
    o = c
    x = np.outer(w[:c], u)
    hs = np.zeros((c, len(u)))
    for k, d in zip(nam_pack.KERNEL, nam_pack.DILATION):
        W = w[o:o + c * c * k].reshape(c, c, k)
        o += c * c * k
        b, mi = w[o:o + c], w[o + c:o + 2 * c]
        o += 2 * c
        W1 = w[o:o + c * c].reshape(c, c)
        o += c * c
        b1 = w[o:o + c]
        o += c
        z = _causal(x, W, d) + b[:, None] + np.outer(mi, u)
        a = np.where(z > 0, z, 0.01 * z)
        hs += a
        x = x + W1 @ a + b1[:, None]
    Wh = w[o:o + c * nam_pack.HEAD_TAPS].reshape(1, c, nam_pack.HEAD_TAPS)
    o += c * nam_pack.HEAD_TAPS
    return (w[o + 1] * (_causal(hs, Wh, 1)[0] + w[o]))[PAD:]


def _biquad(x, b, a):
    y = np.zeros_like(x)
    x1 = x2 = y1 = y2 = 0.0
    for i, v in enumerate(x):
        r = b[0] * v + b[1] * x1 + b[2] * x2 - a[1] * y1 - a[2] * y2
        x2, x1, y2, y1 = x1, v, y1, r
        y[i] = r
    return y


def loudness(y):
    """K-weighted mean square, in dB."""
    k = _biquad(_biquad(np.asarray(y, float), *K_SHELF), *K_HPF)
    return 10 * math.log10(float(np.mean(k ** 2)) + 1e-20)


def measure(w, dbu=None):
    """The capture's loudness on the unit for the test signal, with its input trim."""
    return loudness(forward(w, test_signal() * nam_lite.input_trim(dbu)))


def gain_for(w, dbu=None, target=TARGET):
    """(factor for the output scale, measured dB) to bring the capture to `target`."""
    db = measure(w, dbu)
    return 10 ** ((target - db) / 20), db


def main():
    paths = sys.argv[1:]
    if not paths:
        sys.exit(__doc__)
    for p in paths:
        w, _ = nam_pack.load(p, channels=nam_lite.C)
        g, db = gain_for(w, nam_pack.input_level_dbu(p))
        print(f'{os.path.basename(p)}: {db:.1f} dB, {20 * math.log10(g):+.1f} dB to {TARGET:g}')


if __name__ == '__main__':
    main()
