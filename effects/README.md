# Reference effects (C99)

Portable reference implementations of custom effects, an offline WAV renderer and tests. They are
the specification for hand-written SHARC kernels; they are not compiled for the unit. Nothing here
touches firmware. See `docs/baseline-audit.md` for what is known about the real primitive ABI.

```
cd effects
make test        # every test; no hardware, no audio files needed
make demo        # out/fixtures/*.wav (generated signals), out/geiger/*.wav, out/metronome/*.wav
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

## Click (`metronome/`)

A metronome as an ordinary **preset block**: it lives in a preset, takes one block, and follows the
block's bypass/footswitch. Not a global metronome. The guitar passes at exactly unity gain; a
synthesised click is added.

Six parameters: Tempo (20..300 BPM, quarter-note beats, 0.01 BPM resolution), Beats/Bar (2..5: 2/4,
3/4, 4/4, 5/4), Accent (0..12 dB on beat 1; 0 dB = no accent, same sound as other beats), Sound
(click, wood, beep), Level (0..100 %, linear, peak 1.0), Subdivision (1..4 per beat: quarters, eighths,
triplets, sixteenths; subdivision clicks are lower and about 8 dB quieter).

- **Timing is exact.** The tempo phase is an integer: it gains BPM x 100 x subdivision per sample and
  ticks at sample rate x 6000, so tick k lands on the first sample at or after k x 60 / BPM s, for
  ever. No floating-point drift (tested over 10 minutes at 20, 60, 120, 137.5 and 300 BPM).
- **Bar position:** the first sample after `reset()` is beat 1, accented ("restart on enable"). Whether
  the unit re-creates or resets a block when it is enabled is not known yet; if it does not, the block
  will resume its running count instead. Tempo changes keep the phase within the beat.
- **Voices:** sine partials from a quadrature oscillator (no tables, no samples), exponential decay
  (click 3 ms, wood 12 ms with a second partial at 2.71x) or a 40 ms gate with 5 ms release (beep).
  A new tick replaces a sounding voice; no voice lasts more than 200 ms.
- **Not in V1:** HX tap tempo, preset tempo or MIDI clock (needs evidence of how stock tempo-synced
  blocks get their tempo), compound meters such as 6/8, and a separate click output.

The tests (`metronome/test_metronome.c`, the brief's acceptance tests 1-4): exact tick count and every
tick within one sample of its ideal time for 10 minutes at five tempos; downbeat at sample 0 and the
accent/beat/subdivision pattern in all 16 meter x subdivision combinations; Level 0 gives exactly the
input, otherwise output = input + click (within 1e-6) with a peak of at most 1.0 and the guitar
untouched between clicks; random knob changes (including NaN) and resets for two minutes give only
finite, bounded output, no two ticks closer than the fastest possible interval, and no voice longer
than 200 ms; two interleaved instances equal each alone; identical output for block sizes 1/16/37/4096.

### Click on the SHARC (`metronome/sharc/`)

`click_kernel.asm` is a hand-written port of `metronome.c` for the HX Effects' SHARC, assembled with
`tools/sharc/sasm.py`. `click_kernel.py --check` (or `make sharc-check`) runs it in `tools/sharc/ssim.py`
and calls the C reference through `out/libfx.so`, and requires **every output word to be identical**:
six fixed settings (including Level 0 and out-of-range knobs) and two interleaved instances with all
knobs moving every 100 ms. Each call is also held to the register contract the NAM kernel's rig uses
(R0-R15, the alternate registers, the DAG registers and MODE1 unchanged; no loop or PC stack left),
and every memory write must land in the output buffer, the instance's state words or the save area.

Measured (6.5 s per case, 2,496,000 samples): bit-identical; 283 instructions; worst 1,361 and mean
about 620 cycles per 16-sample call, under 1 % of the roughly 150,000 a call has at 450 MHz.

For the match to be exact the reference avoids anything the port can't reproduce: constants are
computed in double and rounded once (the port's tables are generated the same way), Accent is whole dB
(a 13-entry table), Level is scaled by x 0.01 (no division), the beep's release is a fixed per-sample
step, and the C build uses `-ffp-contract=off` (no fused multiply-add).

The port's own ABI, which the firmware integration must give it: knob words DM(5) Tempo (float),
DM(6) Beats/Bar (int), DM(7) Accent (int dB), DM(8) Sound (int), DM(9) Level (float %), DM(10)
Subdivision (int); state in words 16..37 of the instance block (assumed free: the NAM kernel only used
words up to 15); a zeroed block starts at beat 1. Code at PM 0xc4ef8, data at DM 0xe4850 (NAM's
regions: Click replaces NAM in its own build). Not yet done: the Entry 3/4/0 changes for Click's
knobs, and anything on the unit.
