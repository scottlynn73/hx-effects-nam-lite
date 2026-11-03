# Reference effects (C99)

Portable reference implementations of custom effects, an offline WAV renderer and tests. They are
the specification for hand-written SHARC kernels; they are not compiled for the unit. Nothing here
touches firmware. See `docs/baseline-audit.md` for what is known about the real primitive ABI.

```
cd effects
make test        # every test; no hardware, no audio files needed
make demo        # out/fixtures/*.wav (generated signals) and out/geiger/{crush,fold,radio}.wav
out/fxrender geiger in.wav out.wav gain=18 rate=4000 bits=5 curve=3   # any WAV, any settings
out/fxrender describe geiger          # the parameter descriptor (= geiger/params.json)
```

`out/` is git-ignored. Test signals are generated from code (`common/signals.c`: impulse, step, sines,
sweep, seeded noise, Karplus-Strong plucks and a strummed E chord); no recorded audio is committed.

## API (`common/fx.h`)

An algorithm is an `FxAlgorithm`: a parameter descriptor table, `state_bytes`, `reset()` and
`process()`. All state lives in the caller's block; no allocation, I/O or mutable globals in
processing (read-only tables built once are allowed). `process()` must give the same output for any
block size, and only finite output. The renderer calls it in 16-sample blocks, as the unit does.

## Geiger (`geiger/`)

Sample-rate reduction, bit-depth quantisation and a 16-curve waveshaper table: an original algorithm
in the spirit of wavetable-distortion pedals.

```
in -> DC block -> Gain -> [Anti-Alias: 2 one-pole lowpasses at 0.4 x Rate] -> sample-and-hold at Rate
   -> quantise to Bits -> Curve (257-point table, linear interpolation) -> Tone lowpass (200 Hz..20 kHz)
   -> DC block -> Output -> Mix with the dry input
```

Eight parameters, to fit the host model's eight knob words: Gain (0..36 dB), Sample Rate
(250..48,000 Hz), Bit Depth (1..16), Curve (0..15), Tone (0..1), Output (-36..+12 dB), Mix (0..100 %),
Anti-Alias (off/on). Gain, Output and Mix are smoothed per sample (5 ms one-pole); the rest act at once.
The curves: linear, soft, hard, sinefold, trifold, fullwave, halfwave, steps, asym, cheby3, cheby5, sine,
root, spline, ring, gate.

The tests (`geiger/test_geiger.c`) check: every curve finite, within ±1, table within 0.01 of its
function (0.025 for the two with corners or an infinite slope) and different from every other curve;
the quantiser's level count; Mix 0 is exactly the dry input; identical output across runs and block
sizes 1/16/37/4096; two interleaved instances equal each alone; finite, bounded output at every curve's
extremes, with NaN/Inf/1e30 input and with random (and NaN) knob values each block; the sample-and-hold
rate; the anti-alias mode cutting a known alias by more than 6 dB; the three variants different from
dry and each other; and `golden.txt` metrics within 1e-4 (recorded on macOS/clang; re-record with
`make golden` after an intended change).
