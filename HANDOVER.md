# Handover: NAM A2 Lite on the Line 6 HX Effects

Working state as of 2026‑11‑03 (first written 2026‑11‑01). A working, tested firmware build exists,
and a USB flasher that installs it without Line 6 Updater. This note is for picking the
project up in Claude Code (or anywhere) without re‑deriving anything.

## What exists

- **Repo:** `/Users/scott/hx-effects-nam-lite` → <https://github.com/scottlynn73/hx-effects-nam-lite>
  (standalone, GPL‑3.0, no Line 6 files tracked; `.gitignore` excludes `firmware/`, `build/`, `*.hxf`,
  `*.l6ia`, `.venv/`, `.DS_Store`, `usblog/`). Work is on `main`, SSH remote; not pushed since 2026‑11‑03.
- **Upstream + scratch work:** `~/hx-stomp-nam-lite` (clone of
  <https://github.com/nocaseguy/hx-stomp-nam-lite> with all the edits applied by `apply_effects*.py`,
  plus the bisection scripts, `*_parts/` entry dumps, `stomp_e2.txt`/`effects_e2.txt`, `*_ddr.txt`).
  Not needed to build; useful if the offsets ever have to be re‑mapped.
- **Build:** `cd /Users/scott/hx-effects-nam-lite && source .venv/bin/activate && python3 build_effects.py`
  reads `firmware/HX_Effects_v3.80.0_0xd97239907.hxf` (MD5 `7c2ebdf1bffb6bcc5f89dda97f91e40c`) and
  writes `build/HX_Effects_v3.80.0_NAM_A2_Lite.hxf` (current output MD5 `a27780d3ff57612ebd2484a4cc4a9f7e`).
- **Flash:** HX Edit and Line 6 Updater closed, then
  `python3 tools/flash.py flash build/HX_Effects_v3.80.0_NAM_A2_Lite.hxf` (~2 min, ends `BOOTED` /
  `BOOT FAILED`, exit 0/1). `flash.py info` is read‑only. Needs `pip install pyusb libusb-package` in
  the venv. Line 6 Updater → Choose File still works too.
- **Result on the unit:** block under **IR → Single → "NAM A2 Lite"** (takes over the 1024‑sample IR
  block's identity; the 2048 IR block is intact). The standalone build was flashed and booted on
  2026‑11‑03, with both Line 6 Updater and `flash.py`. Knobs: Model (User IR slot), Input, Bass, Mid,
  Treble, Presence, Ch Vol, Polarity. Strip title "NAM / IR_2048". Two NAM blocks + a few effects
  fit in one preset. Sounds right (confirmed by ear after the EQ fixes below).
- **Recovery:** hold the **>** (right arrow) button while powering on → fail‑safe update mode → Updater
  → Choose File → stock `.hxf`. Verified against Line 6's reset‑procedures KB page.

## The port, in one screen

All device logic lives in the copied upstream tools, keyed off Entry 0's code segment load address
(`0x28000000` = HX Effects, via `select_device()` in `tools/patch_amp.py`; `NAM_DEVICE=effects` env for
the kernel):

| Piece | HX Stomp (upstream) | HX Effects (ours) |
|---|---|---|
| Entry 2: Blob 0 buffer size word | split across `w[37192..37193]`, `0x77aac` | whole word `w[37370]`, `0x76a2c` → `0x78000` |
| Entry 2: Heap 6 (start, end, clear) | `w[41966, 41971, 41975]`, `0x293eac..0x2ab243` | `w[42147, 42152, 42156]`, `0x292e2c..0x2a8df6` (end exclusive) → moved to `0x30d100..0x3230ca` |
| Primitive table @ `0x200000` | 282 records | 281 (no `0x2aab`); resolved by ID at build time; `0x9c75` @ `0x200588` |
| Hook record template | hardcoded fn addrs | copied from primitive `0x822`'s record (fns shifted −0x39) |
| Kernel PM home | `0xc4ef8` (Block 2 tail) | same (Block 2 layout identical) |
| Kernel IR store | `IR_FLAG 0x2ab56e`, `IR_TOP 0x2abded` | `0x2a912c`, `0x2a99ab` |
| Kernel working memory | host‑allocated SDRAM via instance struct (`--sdram-words 0x5000`) | **fixed DDR2** `0x294400 + 0x5000 × P_SLOT` (region freed by the Heap 6 move); `--sdram-words 0`; asm swap in `nam_multi.py::_kernel_src()` |
| Host graph | Clarity amp composite `0x6001a9` (3 members) | **IR block** composite `0x6000e9` (8 members), member 1 (`0x271c` convolution) → `0x9c75` |
| Other members' inits | n/a | copied from the IR blob, with overrides: member 3 pid 2 = 19.9 (low cut off), member 4 pid 2 = 20100 (high cut off), member 5 pid 1 = −120 dB (dry off), pid 2 = 0 dB (wet) |
| Entry 3 | new model appended | new model appended, then its descriptor fields (0,1,6,7,10,11,13) copied over `HD2_ImpulseResponse1024Mono`'s |
| Entry 0 | tables relocated, new rows, new folder | **nothing relocated**: 1024 IR's Table 1 cost, Table 2 counts/short name, browser item name, and the "Impulse Response" title string, all in place |

Entry 0 map (HX Effects 3.80.0, segment at `0x28000000`): Table 1 (12‑byte rows) `0x28101084` ×465,
base ptrs at `0x28100b1c/b58/b70/c64/df0`, the two "end" ptrs `0x28100b54/b80` also point at a 7‑entry
harness table at `0x28102650`; count getter `movw #465` at `0x28100b5c` (the other four `movw #465` are
`sq.c` line numbers, not counts). Table 2 (44‑byte rows, sorted by name idx) `0x280bd8fc` ×777, ptr
`0x280bd8f8`, counts `movw #777` at `0x2807b2be/0x280bd85c/0x280ed796`. Browser lists: ptrs `0x281001fc`
(we used `0x2810021c` = Distortion onward), counts `+0xf0`, 13 categories × 4, IR = cat 9 (our index),
subfolder counts `0x281003dc`/`0x281003e4`, names `0x28100074`/`0x281004e8`. `btype` per item is a block‑type enum
(IR = 0x13/0x14/0x15), not a category.

## Why the takeover approach

Anything that adds a *new listed* model fails the boot self‑test (`"Boot Failure res = -21"`): the
app resolves listed items through a path ending in an 8‑entry deprecated‑model table at `0x280fb8f4`
and returns −21 when nothing matches. Bisected exhaustively (E1–E16): compaction OK, relocation OK (once
the harness‑table pointers were understood), rows alone OK, any listed new model → −21, even a pure
duplicate of the IR block, any preset id, any btype. Taking over an existing model's identity sidesteps
it entirely. Cost: HX Edit can't edit the block (code −8200, its 5‑knob definition vs our 8), and the
1024 IR block is gone.

Other failures seen on the way and their causes: −33 = Heap 6 end word off by one (exclusive vs
inclusive); silent splash hang = Table 1 walk running to the old end pointer; "boxy" = IR graph's cut
filters at their static 1 kHz; "two signals" = wet/dry sum at −3/−3 dB; "dry only" = mix pair swapped;
"no low end" = cut frequencies swapped.

## The USB flasher, in one screen

Taken from a capture of Line 6 Updater 1.28 flashing this build (`tools/usb/capture.sh` injects
`usblog.dylib` with `DYLD_INSERT_LIBRARIES`; the Updater has no hardened runtime; `decode.py` reads the
log). `flash.py replay <hxf> <log>` reproduces the Updater's traffic byte for byte. The log is in
`usblog/` (git‑ignored: it contains firmware bytes).

1. Main app (`0e41:4245`, class 0xef, device‑info name `F15Main`): update‑port handshake, cmd 01/03/02,
   close. It restarts into the NXP ROM DFU loader (`1fc9:000c`).
2. DFU 1.1: the `.hxf`'s kind‑5 region (83,472‑byte updater app) in 2048‑byte DNLOAD blocks + GETSTATUS,
   then a zero‑length DNLOAD. The unit comes back as `0e41:4245` class 0 (`F15Updater` v0.09.5a).
3. Updater app: cmd 04 per image (status), then per L6IA entry: 05 begin (id, words, entry‑header
   Fletcher pair), 06 start, 07 chunks of 4096 words (index, chunk Fletcher pair, LE data), 09 end; then
   0a finish. About 100 s, limited by the unit (~200 kB/s).
4. Boot check: the main app answers `F15Main` on its device‑info port. This does not yet tell a clean
   boot from one stopped at "Boot Failure"; look at the screen too.

Transport: 16‑byte header (u16 len‑after‑8, kind 0x28 connect / 0x18 stream, ports 0x1001→0x03ef,
u8 seq, BE u16 flags 02/04/08/10, u32 ack = peer base + bytes received), ≤496‑byte payloads, 512‑byte
window, heartbeat every 1 s (the unit times out at 4 s).

**Image 4 is always flagged (status 5).** The updater app's partition table (in the DFU app, file
offset ~0xf8dc) declares image 4's partition as 0x5000 sectors (10 MiB) and flags any image whose header
length exceeds that. Stock 3.80.0's image 4 is already 12.4 MB (the HX Stomp's too); ours is 14.3 MB.
The physical gap to image 5's header (sector 0x11005) is 0x7bfe sectors (15.5 MiB), which the build's
`E4_MAX` stays under. Not damage. One unproven assumption: nothing else uses the sectors between
stock's end and ours (not in the partition table; presets and IRs live elsewhere; nothing broken so far).

## Things that were tried and are still in the scratch tree (not in the standalone repo)

- `NAM_E0_PART`, `NAM_SKIP`, `NAM_NO_SWAP`, `NAM_NO_EXTRA`, `NAM_DUP_IR`, `NAM_REPLACE_1024`,
  `NAM_LIST_ONLY_MOVE`, `NAM_E2_PART`, `NAM_SKIP_E0`, `NAM_SDRAM`, `NAM_PID`: bisection env switches in
  `~/hx-stomp-nam-lite/tools/patch_amp.py` and `build.py`. Harmless; could be stripped.
- `add_model_entry0_effects()`: the superseded "new model + folder" Entry 0 path. Dead code now.
- `apply_effects.py` … `apply_effects4.py`: the edit scripts that turned upstream into the Effects
  version, in order. Re‑runnable on a fresh upstream clone (part 2 needs the Effects MD5 as argument;
  then the small follow‑up edits from the chat: Blob0 byte‑order assert, Heap 6 `0x3230ca`, harness
  pointers, `P_SLOT`‑based fixed SDRAM, mix/cut overrides, `strip_title`).

## Open / next

1. ~~Verify the standalone build on the unit~~ — done 2026‑11‑03 (flashed twice, boots). Still worth a
   look: the "NAM / IR_2048" strip title.
2. ~~Add the DSP‑cost tuning note to the README~~ — done (README, `DSP_COST = 2700`, floor ≈2300).
3. ~~Strip the bisection switches from `tools/patch_amp.py`~~ — done 2026‑11‑03: all `NAM_*` env switches
   (except `NAM_DEVICE`) and the dead `add_model_entry0_effects()` removed; the build output is byte‑identical
   (MD5 `a27780d3ff57612ebd2484a4cc4a9f7e`). The HX Stomp `add-model` path is kept.
4. Optional: open an issue/PR upstream with the findings (amp slots unused on the Effects, the −21
   self‑test path, the identity takeover, fixed‑DDR2 kernel variant, the USB update protocol, the
   image‑4 partition flag).
5. Edge tests not yet done (each build can now be flashed with `tools/flash.py`): changing Model
   while playing with two blocks; a preset with every heavy effect alongside; power‑cycle with a NAM
   block in the startup preset.

## Don'ts

- Don't change the MD5 check to force another firmware through; every offset above is for 3.80.0.
- Don't commit anything from `firmware/` or `build/`; both are Line 6's firmware (the `.l6ia` too).
- Don't flash while HX Edit or Line 6 Updater is open (they hold the USB interface).
- Don't `sudo` anything in the home folder again (that's what broke `~/.config/git` and the venv).
