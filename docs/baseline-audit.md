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
5. Entry 0: that model's Table 1 cost (`DSP_COST` = 2300, 2700 until 2026-11-10), Table 2 counts/short name, browser name,
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
| Per‑call budget | the check enforces ≤ 33,000 instructions steady (`MAX_STEADY`); `DSP_COST` 2300 is the host's bookkeeping, not a measurement | observed (source) |
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

What is left after all three: 8 words in Block 2's tail (NAM's staging buffers fill it to `0xc7ff8`),
about 256 words between Geiger's code and Click's data and about 137 above Click's code. (An earlier
version of this note said "about 90 instructions in Block 2's tail"; that was wrong.)

Four and five kernels (`build_all.py --with commander[,corrupt]`; both work on the unit since 2026-11-04;
addresses in `build/all_commander[_corrupt]_manifest.json`):

| Region | Use |
|---|---|
| Block 3 normal words `0xe4850..0xe6d68` | NAM with 2 slots and the 3‑slot layout's far layers (`nam_multi.py --far-d 17`: the d = 17 rings go to DDR2 too; slot 3,755 words instead of 4,673; checked bit for bit) |
| Block 3 normal `0xe6d70..0xe7296`, 48‑bit `0xe4c64..0xe4dd5` | Geiger's data and code |
| Block 3 normal `0xe74d0..0xe75de`, 48‑bit `0xe4e94..0xe5004` | Commander's (four‑kernel image) |
| Block 3 normal `0xe74d0..0xe7631`, 48‑bit `0xe4ecc..0xe50ea` | Commander + Corrupt as one kernel (five‑kernel image), entries `0xe4ecc` and `0xe4ed1` |
| Block 3 from `0xe7c20` | Click, as before |
| Primitives `0x0100`, `0x0838` | Commander's and Corrupt's hooks (zero uses in the stock graphs) |
| DDR2 `0x21c400..0x297400` | the Blob 0 buffer, `0x7b000` words for five host graphs (`0x7ac3f` used) |
| DDR2 `0x297400 + 0x5000 × slot` | NAM's two slots |

The next limit is **Entry 2's size**: the DSP boot stream must fit its 512 KiB eMMC partition
(`inject_sharc_ldr_blocks` asserts it). Stock is 490,392 bytes; NAM + Click + Geiger leaves 260 bytes.
The four‑ and five‑kernel images load the kernels' zeroed areas (NAM's staging buffers, every save area
and slot pool) with ZERO_LDATA records (tag 1, a 3‑word header; the stock stream already has 81), which
saves about 5.3 KB: 1,912 bytes free with Commander, 812 with Commander and Corrupt sharing one kernel.
Anything more needs a smaller boot stream (Geiger's 4 KB of curve tables computed at start‑up instead,
or NAM's 8 KB tone‑stack table) before it needs DSP memory.

## Finding more memory (2026-11-04)

Five kernels leave 812 bytes of Entry 2 and about 1,500 words of Block 3; each further effect needs about
400-450 instructions and 150-570 data words. What the stock image offers:

- **Entry 2 is mostly code**, about 410 KB of its 490 KB: ISA (48-bit) at PM `0x8c100..0x8ee93` (~70 KB,
  INIT_L48), VISA in internal memory (~130 KB, tag-3 blocks at short-word addresses), and VISA in DDR2
  (~213 KB, tag-10 blocks at `0x300000..0x30d053`). 88 primitives' entries are external: entry PC = 2 x the
  DDR2 word address (every one checked).
- **The external code's format**: 16-bit parcels, two to a 32-bit word, the high half first. 48-bit
  instructions appear with their ISA encoding unchanged (seen: `DM(abs) = ureg`, `JUMP abs`, `CJUMP` into
  the ISA region); RTS's 48-bit form never appears (VISA uses a short form).
- **No code to reclaim from the replaced blocks**: every primitive the five taken-over models use is
  shared with models still in use. The primitives no graph uses own about 380 instructions in all.
- **Entry 2 cannot grow**: its eMMC partition (header sector `0x8802`, `0x400` sectors) ends where image 3's
  begins (the updater's partition table, DFU app file offset ~`0xf8c8`).
- **Entry 4 can**: about 1.9 MB of its 15.5 MiB partition is free, and Blob 0 lands verbatim at DDR2
  `0x21c400` (only its structured fields are relocated), so words appended after its last composite land at
  `0x21c400 + offset`.

What the probes (`build_all.py --probe`, `effects/probe/sharc/`) showed on the unit, 2026-11-06 to 09:

| Probe | Result |
|---|---|
| Words inside Blob 0, read by a kernel | **Work**: 880 Hz, the magic word is at `0x21c400 + offset` |
| 48-bit ISA routine in DDR2, jumped to (Bit Depth 2 of probe 3: beside the stock external code) | **Froze the unit** |
| Routine copied from Blob 0 into Block 3 as 32-bit words through the normal-word view (INIT_L48 packing), then called | **Works**: it ran and came back, with the unit responsive |
| The same routine written through PX to PM, then called | Came back with the flag wrong (low drone); not understood, and not needed |
| PX copy plus `FLUSH CACHE` | Not established (1 bit was not reported separately) |
| Two different routines swapped into one internal region every call, no PM data access, no flush (probe 5, 3 bits) | **Works**: the routine just copied was the one that ran, on every call heard |
| The same with PM data accesses meant to force the instruction cache, with `FLUSH CACHE` (2 bits) | Works; `FLUSH CACHE` executes without harm |
| The forcing routines with no flush (1 bit) | Also worked, so no stale code was seen: either the forcing did not load the cache, or the cache is not in play here. It does **not** show that `FLUSH CACHE` is needed or effective |

Probes 1 and 2 froze because the Probe sat on Geiger's slot, the user's start-up preset contains Geiger, and
their timed jump to DDR2 fired during boot. flash.py's `BOOTED` did not show it: it only means the main app
answers on USB.

So the route for more effects is **overlays**: the kernels' code and data travel inside Blob 0, and a small
resident stub copies a kernel's code into one internal region through the normal-word view before calling it.
The six kernels make no PM data accesses, so they should not load the instruction cache; the stubs still flush
after each copy, since it does no harm.

**Ottobit works on the unit this way** (2026-11-09; `build_all.py --with commander,corrupt,ottobit`, MD5
`0d403adc...`). Its stub (`effects/common/ovl_stub_kernel.py`, 35 instructions on primitive `0x2392`) copies its code and
data once from Blob 0 into Block 3, so the kernel runs entirely from internal memory; only its rings are in DDR2,
above NAM's slots. Image B had about 700 free Block 3 words (not the 1,500 first stated), so this image also moves
Geiger's 1,040 curve words into Blob 0, leaving 4,560 bytes of Entry 2 free. Not yet done: two different overlay
effects sharing the region (swap out their data as well as their code), and a home for the larger rings: only
about 31,000 words of DDR2 are known free below `0x2a8df6`, less than Stutter's or Grains' rings need as written.

**Since then (2026-11-10/11).** Two different overlays sharing the region (Ottobit and Syntax, saving each
one's state to its home in Blob 0) worked, but swapping every call costs about 28,000 cycles on the unit,
and Syntax was dropped for unexplained interface lock-ups. Doom Chug went in as a resident kernel instead
(77 data words, constants as immediates) so it never swaps beside Ottobit. The default image
(`build_all.py`) now has about 2 KB of Entry 2 and a few dozen Block 3 words left (cursor `0xe7c10`
against `0xe7c2f`): a further effect has to be an overlay. NAM in that image sits on the mono Regal Bass
DI rather than the 1024 IR; its memory layout is unchanged.


## Tested vs untested

- Tested: the build is byte‑reproducible; NAM output matches the reference bit for bit in the simulator;
  the image boots and the block works on the unit; two NAM blocks coexist.
- Tested since (Click): a second kernel in Block 3 on its own primitive; bypass on a delay host; tap
  tempo and the global BPM reaching a kernel; the register and instance‑block rules above.
- Untested: in‑place buffers; how often the host rewrites knob words; whether a bypassed block's
  primitive is still called; MIDI clock; any frame count other than 16; NAM's own footswitch bypass.
- Tested since (2026-11-11): overlays copied from Blob 0 and swapped every call; NAM reading the User IR
  store from a non-IR host with no IR block in the preset; a real IR block after NAM.

## Already done from the plan's flasher track (F0–F4)

`tools/flash.py` (on `main`) is a working USB flasher with a boot check. Its protocol was recovered from
a capture of Line 6 Updater, replayed byte for byte offline (`flash.py replay`), and it has flashed the
unit successfully. The protocol summary is in `HANDOVER.md`. The brief's `flasher/probe.py` (read‑only
probe) is covered by `flash.py info`. Fail‑safe mode (hold `>` at power‑on) remains the recovery path.
