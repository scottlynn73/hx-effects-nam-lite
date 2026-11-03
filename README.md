# NAM A2 Lite for the Line 6 HX Effects

> ## ⚠️ Compatible with HX Effects firmware 3.80.0 only
>
> This build is mapped against one exact file: **`HX_Effects_v3.80.0_0xd97239907.hxf`**, MD5
> **`7c2ebdf1bffb6bcc5f89dda97f91e40c`**. Every address it patches (DSP boot stream, model tables,
> browser lists, the IR store) belongs to that image. The build refuses any other file, and that
> refusal is a safety guard, not an obstacle: do **not** edit the MD5 check to force a different
> firmware through. Patching the wrong addresses can leave the unit unable to boot.
>
> - Your HX Effects must be on **3.80.0** when you install, and you must flash the file this build
>   makes from the 3.80.0 stock firmware.
> - **Not** for the HX Stomp, HX Stomp XL, HX One, Helix or POD Go; use the upstream project for the
>   Stomp and XL.
> - A future Line 6 firmware (3.81, 4.0, …) will need the offsets re‑mapped by someone before this
>   can support it. Updating only the MD5 is not a port.

Adds **Neural Amp Modeler (NAM) A2 Lite** to the stock HX Effects firmware 3.80.0, as a block that
runs NAM captures on the unit's own SHARC DSP. This is the HX Effects port of
[hx-stomp-nam-lite](https://github.com/nocaseguy/hx-stomp-nam-lite), whose kernel, assembler,
simulator and firmware tools it uses (copied into `tools/` and `src/`, with the HX Effects support
added).

**You do this at your own risk! Do not attempt it if you are not comfortable with running command line tools and 
potentially having to recover your unit yourself!**

> **Unofficial and experimental.** Not affiliated with, endorsed by or supported by Line 6 or Yamaha
> Guitar Group. Installing modified firmware is at your own risk and may void your warranty. Read
> [Recovery](#recovery) before you start, and keep the stock firmware file to hand.

## What you get

- **NAM A2 Lite**, under **IR → Single** in the block browser, with the knobs:

  | Knob | What it does |
  |---|---|
  | **Model** | Which capture plays: 1–128 is the User IR slot that holds it. A slot holding anything else is silent. |
  | **Input** | Gain into the capture, −20 to +20 dB; 0 dB at 5.0 |
  | **Bass / Mid / Treble / Presence** | A tone stack after the model, ±12 dB, flat at 5.0 |
  | **Ch Vol** | Output level; 0 dB at 5.0, +12 dB at 10 |
  | **Polarity** | Normal / Inverted |

- The block takes over the **1024‑sample IR** block's identity, so that block is no longer available.
  The **2048‑sample IR** block is untouched: captures and cab IRs can share the 128 User IR slots, and a
  preset can run a NAM block into a 2048 IR block (amp, then cab).
- The IR category's default scribble‑strip title becomes **"NAM / IR_2048"**. The NAM block shows the
  capture's name once a slot is selected; the 2048 IR block shows the IR's name once one is selected.
- Everything else in the firmware stays stock 3.80.0.

## What you need

- An **HX Effects** on firmware **3.80.0** (see the warning at the top: no other version).
- `HX_Effects_v3.80.0_0xd97239907.hxf`, Line 6's stock 3.80.0 firmware for the HX Effects, MD5
  `7c2ebdf1bffb6bcc5f89dda97f91e40c`. See [Getting the stock firmware](#getting-the-stock-firmware).
  The build checks the MD5 and refuses any other file.
- Python 3.10 or newer with `numpy`.
- **Line 6 Updater** (to install) and **HX Edit** (to import captures).
- 3‑channel **A2 Lite** `.nam` captures.

## Build

**1. Put the stock firmware in `firmware/`.** Download `HX_Effects_v3.80.0_0xd97239907.hxf` from Line 6
(see [Getting the stock firmware](#getting-the-stock-firmware)) and copy it to:

```
hx-effects-nam-lite/
└── firmware/
    └── HX_Effects_v3.80.0_0xd97239907.hxf      <- here
```

The `firmware/` folder is listed in `.gitignore`, as are `build/` and every `.hxf`: Line 6's file and
anything built from it are copyrighted and must never be committed or shared. Only this repository's
own tools are in version control.

**2. Build:**

```
python3 -m venv .venv && source .venv/bin/activate
pip install numpy
python3 build_effects.py
```

(`python3 build_effects.py path/to/some.hxf` builds from a file elsewhere instead.) This writes
`build/HX_Effects_v3.80.0_NAM_A2_Lite.hxf` in about 30 seconds. The build checks the firmware's MD5 and
refuses any other file; the kernel is first run in the SHARC simulator and must match the reference bit
for bit (`--no-check` skips that).

## Tuning the declared DSP cost

The block declares a DSP cost of 2700 (`DSP_COST` in `build_effects.py`). That number is bookkeeping
only: the app uses it to decide when to grey out other blocks, and it has no effect on what the DSP
actually does. The kernel was measured in the simulator at about 23% of a block (34,000 of 150,000
cycles per audio block); stock blocks declare costs in roughly hundredths of a percent, so the honest
figure is around 2300 and 2700 leaves a heavy block's worth of margin. As shipped, two NAM blocks and
a few effects fit in one preset.

If you want to trade some of that margin for more blocks:

1. Lower `DSP_COST` in `build_effects.py` (try 2300; don't go below it, that's what the measurement
   supports), rebuild and flash.
2. Build the heaviest preset the unit now allows: two NAM blocks plus whatever was previously greyed
   out (the dynamic reverbs, Shimmer, Poly Pitch, Cosmos Echo are the heavy ones).
3. Stress it: big chords, long reverb tails, and change **Model** on both blocks while notes ring. A
   capture change is the kernel's worst case.
4. Crackling, dropouts or a block going silent means the number is too low: raise it and rebuild.

Declaring too little lets the app accept a chain the DSP can't service; declaring too much only costs
you a block you might have fitted. When in doubt, leave it at 2700.


## Install

**Double check that you have a backed up version of the .hxf firmware file for your unit- you may need it for recovery!**

1. In HX Edit, back up your presets and IRs, then **close HX Edit**.
2. Open Line 6 Updater, choose **Choose File**, pick `build/HX_Effects_v3.80.0_NAM_A2_Lite.hxf`.
3. Let it finish and restart the unit. A normal boot means the install worked; see
   [Recovery](#recovery) if it shows "Boot Failure" or stops at the splash.

**Note- you may find the software says there was a problem, just try again and it should work on the second try (this tends to be 
more likely when recovering from scratch, not when updating an already working firmware.**

### Flashing from the command line

`tools/flash.py` does the same update as Line 6 Updater, over USB, and then checks that the unit boots
back into its main app. Close HX Edit and Line 6 Updater first, then:

```
pip install pyusb libusb-package      # once, in the .venv
python3 tools/flash.py flash build/HX_Effects_v3.80.0_NAM_A2_Lite.hxf
```

It checks the file (product, MD5, every entry's checksum), asks you to type `flash`, then: restarts the
main app into its USB DFU loader, loads the updater app from the `.hxf`, writes all 14 images (about
100 seconds), and waits for the unit to answer as `F15Main`. It ends with `BOOTED` or `BOOT FAILED`
(exit code 0 or 1), so it can follow a build in a script. If it stops partway, the unit is left in
updater mode; run it again, or use Line 6 Updater. `python3 tools/flash.py info` shows what the unit is
running without changing anything.

"Booted" means the main app came up and answers on USB. It does not yet tell a clean boot from one that
stops at a "Boot Failure" message, so glance at the screen as well.

The protocol was taken from a USB capture of Line 6 Updater 1.28 (`tools/usb/`: `capture.sh` runs the
Updater with a logging libusb shim, `decode.py` reads the log), and `python3 tools/flash.py replay
<file.hxf> <log>` checks the tool against such a capture byte for byte. It is tested on 3.80.0 only.

## Use

1. Convert a capture to a User IR:
   ```
   python3 tools/nam2ir.py "My Amp.nam" -o "My Amp NAM.wav"
   ```
   The `.wav` is about 8 KB: it is not a sound, it carries the capture's weights.
2. In HX Edit's **Impulses** tab, import the `.wav` into a User IR slot (say slot 5). Do this with a
   preset selected that has no NAM block in it; HX Edit does not understand the NAM block (see Limits).
3. On the unit, add a block, choose **IR → Single → NAM A2 Lite**, and set **Model** to 5.

A layout that's easy to remember helps, since the Model knob shows slot numbers, not names: for
example captures in slots 1–20 and cab IRs from 21.

## Try it quickly: the demo captures

The `captures/` folder holds a few NAM A2 Lite captures **already converted** with `tools/nam2ir.py`,
so you can hear the block without converting anything yourself:

1. Open HX Edit, go to the **Impulses** tab, and drag the `.wav` files from `captures/` into free
   User IR slots (note the slot numbers). Do this with a preset selected that contains no NAM block.
2. On the unit, add **IR → Single → NAM A2 Lite** to a preset and set **Model** to one of those slot
   numbers. The capture's name shows on the strip once it's selected.
3. Set Input, Bass/Mid/Treble/Presence and Ch Vol to 5.0 for the capture as recorded, then adjust.

Each `.wav` is about 8 KB and is not an audio IR: it carries the capture's 1,871 weights behind a
small header. Loading one into the stock 2048‑sample IR block does nothing useful. 

- **HX Edit cannot edit the NAM block.** It shows "Failed to load model (code −8200)" when a preset
  containing one is selected, because its own definition of the 1024‑sample IR block has 5 knobs and
  the unit's now has 8. Edit NAM blocks on the unit; use HX Edit for everything else (IR import works).
- Presets store the slot number, not the capture: moving a capture to another slot means updating the
  presets that use it.
- Only 3‑channel A2 Lite captures fit; standard and A2 Full captures don't.
- The block's DSP cost is declared as 2700 (like a heavy stock block), so the unit greys out other heavy
  blocks beside it.

## Getting the stock firmware

The firmware file is a free download from Line 6 (an account is needed):

1. Go to <https://line6.com/software/>.
2. Set **Hardware** to *HX Effects*, **Software** to *Firmware*, pick your OS, and press **Go**.
3. Download **HX Effects Firmware 3.80.0**. The file is `HX_Effects_v3.80.0_0xd97239907.hxf`
   (about 3.9 MB). Check it: `md5 -q HX_Effects_v3.80.0_0xd97239907.hxf` on macOS, or
   `certutil -hashfile HX_Effects_v3.80.0_0xd97239907.hxf MD5` on Windows, must print
   `7c2ebdf1bffb6bcc5f89dda97f91e40c`.

Line 6 Updater is on the same page: set **Software** to *Line 6 Updater* and download it for your OS.

## Recovery

Read this before you install anything. If the unit shows **"Boot Failure res = …"**, stays on the
splash screen, or boots with the scribble strips dark, it can be put back on stock firmware from the
computer. This build never touches the bootloader, and the bootloader's fail‑safe update mode is what
makes recovery possible. Your presets, IRs and global settings survive a recovery flash.

### What you need ready before flashing

- Line 6 Updater installed (see [Getting the stock firmware](#getting-the-stock-firmware); it is on the
  same download page).
- The stock `HX_Effects_v3.80.0_0xd97239907.hxf` in `firmware/`, MD5 checked.
- A known‑good USB cable, connected straight to the computer (no hub).
- A fresh HX Edit backup of your presets and IRs.

### Step by step

1. **Close HX Edit** and any DAW or other program that talks to the unit over USB.
2. **Power the unit off.** Leave it connected by USB.
3. **Enter fail‑safe update mode:** hold the **right arrow (>)** button and, keeping it held, power the
   unit on. Keep holding for about three seconds after power‑up, then release. In this mode the unit
   shows nothing useful on its strips; that is expected.
4. **Open Line 6 Updater** and sign in. It should list the HX Effects (it may say "update mode" or show
   no version). If it doesn't appear, wait 30 seconds, then unplug the USB, repeat step 3, and try a
   different USB port or cable.
5. Click the unit, choose **Choose File** (not the online update), and pick
   `firmware/HX_Effects_v3.80.0_0xd97239907.hxf`.
6. **Let it finish.** Don't unplug or power off; the flash takes a few minutes and the progress bar may
   pause. When Updater reports success, restart the unit with the power switch.
7. The unit boots stock 3.80.0. Open HX Edit, confirm it connects, and restore your backup if anything
   is missing.

### If that doesn't work

- Updater never sees the unit: try the other USB port on the computer, a different cable, and powering
  on with the **>** button held for longer (up to ten seconds). On macOS, make sure the Line 6 driver was
  allowed in System Settings → Privacy & Security; on Windows, reinstall Line 6 Updater, which carries
  the driver.
- Updater sees the unit but the flash fails: run it again from step 2. Failed flashes are retryable;
  the bootloader is not affected by them.
- Still stuck: Line 6's own instructions for a unit in an unrecoverable state are the same
  **>**‑at‑power‑on procedure ("Fail‑safe update mode" in the
  [Helix/HX reset procedures](https://kb.line6.com/helix-rack-lt-fx-stomp-reset-procedures-and-troubleshooting-tricks)).

### Other power‑on combinations (from the same Line 6 page)

| Hold at power‑on | What it does |
|---|---|
| **>** (right arrow) | Fail‑safe update mode (the one above) |
| **FS6 + TAP** | Factory restore: presets, IRs and globals |
| **FS5 + FS6** | Reset presets only |
| **FS4 + FS5** | Reset global settings |
| **FS3 + MODE** | Clear all presets and IRs |

None of these change the firmware; a boot failure needs the Updater flash above.

## How it works, briefly

- The SHARC kernel is the upstream NAM A2 Lite kernel (`tools/sharc/nam_multi_kernel.asm`), with two
  changes for the HX Effects: it reads captures from the HX Effects' IR store (`0x2a912c`, flags;
  `0x2a99ab`, the top of slot 1) and keeps each block's working memory in a fixed DDR2 region
  (`0x294400 + 0x5000 × slot`) freed by moving the DSP's Heap 6.
- The HX Effects' app never places amp models, so the NAM host graph is built on the **IR block's**
  graph: its convolution member becomes the NAM primitive and the remaining members are parked at the
  IR block's default knob values (low cut 19.9 Hz and high cut 20.1 kHz, both "off"; mix fully wet;
  level 0 dB). Those inits are the `{(member, pid): value}` overrides in `tools/patch_amp.py`.
- The app's boot self‑test rejects any model it doesn't already know, so the NAM block takes over the
  1024‑sample IR block's identity (name, preset id, browser entry) rather than adding a new one.

## Layout

```
build_effects.py          the one-step build
firmware/                 where you put the stock .hxf (git-ignored, never committed)
captures/                 demo NAM A2 Lite captures, already converted to User IR .wav files
.gitignore                keeps firmware/, build/ and every .hxf out of version control
README.md                 this file
build/                    the output (created by the build)
tools/                    hxf.py, l6ia.py, l6ia_verify.py, patch_amp.py, nam2ir.py
tools/flash.py            USB flasher with boot check (see Flashing from the command line)
tools/usb/                usblog.c + build_shim.sh + capture.sh (log Line 6 Updater's USB traffic), decode.py
tools/sharc/              the kernel (nam_multi.py, nam_multi_kernel.asm), nam_lite.py, nam_pack.py,
                          sasm.py and ssim.py (assembler, simulator), entry4_blob.py, recips_table.json
src/sharc/nam_a2.asm      the reference NAM A2 implementation the simulator check compares against
```

## Copyright notice

**No Line 6 / Yamaha Guitar Group code, data or firmware is in this repository, and none is
distributed with it.** Specifically:

- The repository contains only original work: Python tools, a SHARC assembler and simulator, a NAM
  kernel written from scratch in SHARC assembly, and documentation. It is released under the GPL‑3.0,
  as the upstream project is.
- The stock HX Effects firmware is **not** included. Each user obtains their own copy directly from
  Line 6's download site under Line 6's terms, puts it in a folder this repository ignores
  (`firmware/`), and the build reads it on the user's own computer. The `.gitignore` excludes the
  firmware, the build output and every `.hxf` and `.l6ia` file so that none can be committed.
- The build output is Line 6's firmware with modifications. It is a derivative of their copyrighted
  work and **must not be redistributed**: don't upload the built `.hxf`, share it, or post it in
  forums. Each person builds their own from their own copy of the stock firmware.
- "Line 6", "Helix", "HX Effects", "HX Edit" and "Line 6 Updater" are trademarks of Line 6, Inc. /
  Yamaha Guitar Group, Inc., used here only to identify the product the tools work with. "Neural Amp
  Modeler" and "NAM" refer to Steven Atkinson's open‑source project. This project is not affiliated
  with, endorsed by or supported by any of them.
- The tools exist to let an owner run software of their choosing on hardware they own, for personal,
  non‑commercial use. No copy protection, signing or encryption is bypassed: the firmware container
  uses checksums only, which the tools recompute. The offsets and formats documented here were
  determined by inspecting the publicly downloadable firmware file.
- Modifying your unit's firmware may void its warranty and is entirely at your own risk; the authors
  accept no liability for any damage to hardware or data.

If you represent Line 6 or Yamaha Guitar Group and believe any part of this repository infringes
your rights, open an issue or contact the maintainer and it will be addressed promptly.

*This notice describes what the repository contains and how it is meant to be used; it is not legal
advice, and the maintainer is not a lawyer.*

## Thanks

This project exists because of **[nocaseguy](https://github.com/nocaseguy)** and
**[hx-stomp-nam-lite](https://github.com/nocaseguy/hx-stomp-nam-lite)**. Everything hard here is
theirs: the NAM A2 Lite kernel written from scratch in SHARC assembly, the SHARC assembler and
cycle‑accurate simulator with the bit‑exact reference check, the `.hxf`/L6IA container tools, the
idea of smuggling a capture's weights through a User IR slot, and the whole reverse‑engineering of
how the Helix firmware builds a block from its model table, graph library and DSP boot stream. The
HX Effects port is a few hundred lines of offsets and workarounds on top of that foundation; without
it there would have been nothing to port. Thank you.

## Licence

GPL‑3.0‑or‑later, as the upstream project, for the tools and documentation. No Line 6 code or data is
included. The demo captures in `captures/` are my own and may be used freely.
