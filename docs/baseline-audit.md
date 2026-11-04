# Baseline audit (M0)

Recorded 2026‑11‑03 on branch `custom-effects`, from `main` at `88b403c`; updated 2026‑11‑04 with what
the Click hardware builds showed (rows marked **observed on the unit**). Every row says where it comes
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
| Instance DM block | `I0`: 145 words (0x91), zeroed at creation | modelled |
| `DM(3, I0)` | **non‑zero the whole time the block is on**, unchanged by the footswitch; not a knob‑write flag (as the NAM kernel assumed) nor a usable bypass flag. Stock 0x822's kernel passes audio through while it is non‑zero. Never write it. | observed on the unit (probe builds) |
| Other instance words | knob writes change only their own words; nothing else in words 0–144 changed on knob turns or bypass. Write only your own state word (Click: 12) and keep state elsewhere. | observed on the unit (probe builds) |
| Instance PM block | `I8`: 13 words (0x0d) | modelled |
| Instance struct | `I3` → call‑list entry; `DM(2, I3)` → instance struct; words 6/7 = its SDRAM block start/end | modelled |
| Knob words | `DM(5..11, I0)` and `DM(15, I0)` (pid order in `patch_amp.NAM_PARAMS`): floats, or an integer for Model (User IR slot 1..128) and a bool for Polarity | modelled + observed (knobs work on the unit) |
| Free state words | the kernel uses `DM(12..14, I0)` for its own state (`P_SLOT`, `P_SEEN`, `P_MET`) | observed (source) |
| Registers | R0–R15, the alternate set, the DAG registers **including I1–I3**, and MODE1 must come back unchanged (NAM restores I1–I3 through B1–B3). A kernel that returned with I1/I2 advanced froze the unit's knobs and footswitches while audio carried on. The rig now checks I1–I3 too. | observed on the unit |
| Per‑call budget | the check enforces ≤ 33,000 instructions steady (`MAX_STEADY`); `DSP_COST` 2700 is the host's bookkeeping, not a measurement | observed (source) |
| Parameter smoothing | none by the host as far as known; the NAM kernel crossfades captures itself | unknown for other knob types |
| Bypass | applied in the graph, not through the instance block: on a delay host (Click on Mod/Chorus Echo) the footswitch bypasses the block; on the 1024 IR host it lit but did not bypass Click | observed on the unit |
| Preset change / re‑creation | no explicit callback seen; kernels detect re‑creation by comparing `I0` and a call counter | modelled |
| Knob records | floats on Clarity amp records (Bass, ChVol) reach the kernel; a chorus "Mix" record did not; list knobs must stay short (stock has at most 21 entries; a 281‑entry list stopped its page drawing); an IR‑type host draws knob 1 as the IR selector | observed on the unit |
| Tempo sync | a delay's synced Time is computed in its DSP parameter map (ops 0x2a, 0x54); copying those nodes delivers tap tempo / global BPM to a custom kernel as a beat length in seconds | observed on the unit |
| Multiple instances | separate `I0`/`I8`/SDRAM per instance; NAM shares 3 internal slots between up to 3 blocks | observed on the unit (two NAM blocks in one preset) |

## Memory left (with the NAM kernel in)

| Region | Use | Free | Source |
|---|---|---|---|
| Block 2 PM tail `0xc4ef8..0xc8000` | kernel code to `0xc53cf`, then staging buffers to `0xc7ff8` | **8 words** | observed (build log) |
| PM guard | `build_effects.py` asserts code ends ≤ `0x0c5554` | — | observed |
| Block 3 `0xe4850..0xe8000` | globals, tables, slots | **1,004 words** after `0xe7c14` | observed |
| DDR2 `0x324500..0x328000` | tone‑stack table | used to `0x324ce5` | observed |
| DDR2 `0x294400 + 0x5000 × slot` | per‑instance long rings (freed by moving Heap 6) | 3 × 0x5000 words, NAM‑specific | observed |

A second kernel **can** sit beside NAM (done: `build_nam_click.py`, works on the unit):

| Region | Use in the NAM + Click image |
|---|---|
| Block 3 normal words `0xe7c20..0xe7d43` | Click's data (tables, save area, 8 slots) |
| Block 3 48‑bit `0xe5390..0xe54fa` (= normal `0xe7d58..0xe7ff7`) | Click's code (the stock boot stream stops at `0xe47d2`; the stacks are in Block 2) |
| Primitive `0x0128` | Click's hook (zero uses in the stock graphs; `0x2aa8`/`0x2aaa` are used by the root graph) |
| DDR2 `0x21c400..0x295400` | the Blob 0 buffer, enlarged to `0x79000` words for two host graphs |
| DDR2 `0x295400 + 0x5000 × slot` | NAM's slots, moved up by `0x1000` (`NAM_SDR_BASE`) |

A third kernel fits too once NAM runs 2 slots (done: `build_all.py`, NAM + Click + Geiger, works on
the unit; addresses in `build/all_manifest.json`):

| Region | Use in the NAM + Click + Geiger image |
|---|---|
| Block 3 normal words `0xe4850..0xe73cb` | NAM with 2 slots (was to `0xe7c14` with 3) |
| Block 3 normal words `0xe73d0..0xe78f6` | Geiger's data (16 × 65‑point curve tables, save area, 8 slots) |
| Block 3 48‑bit `0xe50a4..0xe5215` (= normal `0xe78f6..0xe7b1f`) | Geiger's code |
| Block 3 from `0xe7c20` | Click's data and code, as above |
| Primitive `0x012e` | Geiger's hook (zero uses in the stock graphs) |
| DDR2 `0x21c400..0x296400` | the Blob 0 buffer, `0x7a000` words for three host graphs |
| DDR2 `0x296400 + 0x5000 × slot` | NAM's two slots (they must end below the IR store at `0x2a912c`; asserted) |

What is left after all three: about 90 instructions in Block 2's tail, about 170 between Geiger's code and
Click's data, and about 90 above Click's code. A fourth kernel needs memory freed first (for example NAM's
staging buffers moved to Block 3 with `nam_multi.py --staging b3`, which frees Block 2's tail).

## Tested vs untested

- Tested: the build is byte‑reproducible; NAM output matches the reference bit for bit in the simulator;
  the image boots and the block works on the unit; two NAM blocks coexist.
- Tested since (Click): a second kernel in Block 3 on its own primitive; bypass on a delay host; tap
  tempo and the global BPM reaching a kernel; the register and instance‑block rules above.
- Untested: in‑place buffers; how often the host rewrites knob words; whether a bypassed block's
  primitive is still called; MIDI clock; any frame count other than 16; NAM's own footswitch bypass.

## Already done from the plan's flasher track (F0–F4)

`tools/flash.py` (on `main`) is a working USB flasher with a boot check. Its protocol was recovered from
a capture of Line 6 Updater, replayed byte for byte offline (`flash.py replay`), and it has flashed the
unit successfully. The protocol summary is in `HANDOVER.md`. The brief's `flasher/probe.py` (read‑only
probe) is covered by `flash.py info`. Fail‑safe mode (hold `>` at power‑on) remains the recovery path.
