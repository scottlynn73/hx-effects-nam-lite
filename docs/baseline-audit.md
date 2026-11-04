# Baseline audit (M0)

Recorded 2026‑11‑03 on branch `custom-effects`, from `main` at `88b403c`. Every row says where it comes
from: **observed** (measured or read in this checkout, or seen on the unit), **modelled** (what the
simulator rig assumes and the NAM kernel relies on; working on hardware, never traced in the stock
firmware), or **unknown**.

## Reproducibility baseline

| Item | Value | Source |
|---|---|---|
| Stock input | `firmware/HX_Effects_v3.80.0_0xd97239907.hxf` | observed |
| Stock MD5 / SHA‑256 | `7c2ebdf1bffb6bcc5f89dda97f91e40c` / `c5e29e834c20f0541805e94e210a770128e049c859931655440e4ebb501506a0` | observed |
| Build command | `source .venv/bin/activate && python3 build_effects.py` | observed |
| Output `.hxf` MD5 / SHA‑256 | `a27780d3ff57612ebd2484a4cc4a9f7e` / `915d5c9ccbc4f2f998a3d29b5a1014045b5fb02e3738e68e4b1ae3eef90679c8` | observed, identical across rebuilds |
| Output L6IA MD5 / SHA‑256 | `4425244f4a0115b0f62e172bc5d74368` / `b5ed084b062e677cee71c51e6bb8f0fcbfb29fa0796ef5201957d2ba23338697` | observed |
| Kernel check | 3 slots, 1,239 instructions; worst 34,153 instructions per call (steady worst 32,132, mean 25,567); checked bit for bit against `src/sharc/nam_a2.asm` | observed (`nam_multi.py --check`) |
| On the unit | flashed and booted 2026‑11‑03, by Line 6 Updater and by `tools/flash.py` | observed |

## The artifact chain

`build_effects.py`: stock `.hxf` → MD5 check → `tools/hxf.py` unpack → L6IA (`tools/l6ia.py`) →

1. kernel: `tools/sharc/nam_multi.py` writes `build/nam_lite.asm` and runs it in `ssim.py` (`--check`);
2. Entry 4: a copy of `HD2_ImpulseResponse2048Mono`'s graph (composite `0x6000e9`, 8 members), member 1's
   convolution primitive `0x271c` replaced by primitive `0x9c75`; the other members' inits overridden
   (cuts off, mix wet);
3. Entry 2: Blob 0 buffer `0x76a2c` → `0x78000` words; Heap 6 moved to `0x30d100`;
4. Entry 3: the new model's descriptor fields copied over `HD2_ImpulseResponse1024Mono` (model 72);
5. Entry 0: that model's Table 1 cost (`DSP_COST` = 2700), Table 2 counts/short name, browser name,
   the IR category's strip title;
6. Entry 2 again: the kernel assembled (`sasm.py`) at PM `0xc4ef8`, primitive `0x9c75`'s record
   (template copied from primitive `0x822`) pointed at it, DM 0x91 / PM 0x0d words per instance;
7. `l6ia_verify.py` (all checksums) → `hxf.py pack` with the stock file as donor.

## The primitive ABI as the NAM kernel uses it

| Question | Answer | Source |
|---|---|---|
| Call rate | once per **16‑sample block** | modelled (`nam_multi_kernel.asm` header; `Rig.call` feeds 16 words) |
| Sample rate | 48 kHz assumed: 450 MHz / 48 kHz × 16 ≈ 150,000 cycles per call | assumed, not measured on the unit |
| Audio buffers | `I1` = 16 input floats, `I2` = 16 output floats (separate buffers in the rig; in‑place untested) | modelled |
| Channels | mono in, mono out (host graph is the IR block's mono graph) | modelled |
| Instance DM block | `I0`: 145 words (0x91), zeroed at creation, `DM(3)` set to 1 by the host when knobs change | modelled |
| Instance PM block | `I8`: 13 words (0x0d) | modelled |
| Instance struct | `I3` → call‑list entry; `DM(2, I3)` → instance struct; words 6/7 = its SDRAM block start/end | modelled |
| Knob words | `DM(5..11, I0)` and `DM(15, I0)` (pid order in `patch_amp.NAM_PARAMS`): floats, or an integer for Model (User IR slot 1..128) and a bool for Polarity | modelled + observed (knobs work on the unit) |
| Free state words | the kernel uses `DM(12..14, I0)` for its own state (`P_SLOT`, `P_SEEN`, `P_MET`) | observed (source) |
| Registers | the rig randomises R0–R15, the alternate set and DAG registers, and fails the check if any is changed on return; MODE1 is saved/restored, CBUFEN set on entry | modelled |
| Per‑call budget | the check enforces ≤ 33,000 instructions steady (`MAX_STEADY`); `DSP_COST` 2700 is the host's bookkeeping, not a measurement | observed (source) |
| Parameter smoothing | none by the host as far as known; the NAM kernel crossfades captures itself | unknown for other knob types |
| Bypass / preset change | no explicit callback seen; the kernel detects re‑creation by comparing `I0` and a call counter | modelled |
| Multiple instances | separate `I0`/`I8`/SDRAM per instance; NAM shares 3 internal slots between up to 3 blocks | observed on the unit (two NAM blocks in one preset) |

## Memory left (with the NAM kernel in)

| Region | Use | Free | Source |
|---|---|---|---|
| Block 2 PM tail `0xc4ef8..0xc8000` | kernel code to `0xc53cf`, then staging buffers to `0xc7ff8` | **8 words** | observed (build log) |
| PM guard | `build_effects.py` asserts code ends ≤ `0x0c5554` | — | observed |
| Block 3 `0xe4850..0xe8000` | globals, tables, slots | **1,004 words** after `0xe7c14` | observed |
| DDR2 `0x324500..0x328000` | tone‑stack table | used to `0x324ce5` | observed |
| DDR2 `0x294400 + 0x5000 × slot` | per‑instance long rings (freed by moving Heap 6) | 3 × 0x5000 words, NAM‑specific | observed |

Consequence: **a second kernel cannot sit beside NAM** in the current memory plan. Phase A (one effect
per build, replacing NAM's kernel and its memory) can reuse the whole region; Phase B (several
effects in one image) needs a new memory plan first.

## Tested vs untested

- Tested: the build is byte‑reproducible; NAM output matches the reference bit for bit in the simulator;
  the image boots and the block works on the unit; two NAM blocks coexist.
- Untested: in‑place buffers; how often the host rewrites knob words; behaviour on bypass (whether the
  primitive is still called); any knob type other than float/int/bool; tempo or MIDI clock reaching a
  primitive; any frame count other than 16.

## Already done from the plan's flasher track (F0–F4)

`tools/flash.py` (on `main`) is a working USB flasher with a boot check. Its protocol was recovered from
a capture of Line 6 Updater, replayed byte for byte offline (`flash.py replay`), and it has flashed the
unit successfully. The protocol summary is in `HANDOVER.md`. The brief's `flasher/probe.py` (read‑only
probe) is covered by `flash.py info`. Fail‑safe mode (hold `>` at power‑on) remains the recovery path.
