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

It also adds effects of our own, each an original algorithm running on the same DSP:

- **Click**, a metronome block ([Click](#click-a-metronome-block))
- **Geiger**, a bit crusher ([Geiger](#geiger-a-bit-crusher))
- **Commander**, an octave fuzz, and **Corrupt**, a tracking square synth ([Commander and Corrupt](#commander-and-corrupt-octave-fuzz-and-tracking-synth))
- **Ottobit**, a sequenced bit crusher with random stutters ([Ottobit](#ottobit-a-sequenced-bit-crusher))
- **Doom Chug**, a low drone generator to feed the glitch effects ([Doom Chug](#doom-chug-a-low-drone-generator))

There are two builds, one command each (see [Build](#build)): `python3 build.py nam` for NAM and Click, and
`python3 build.py full` for NAM, Click and the five other effects. In both, NAM sits under Distortion → Mono
(out of the IR category), so a cab IR can follow it. **The full image is the recommended one**, and it's what
runs on the maintainer's unit (2026‑11‑13). The original NAM‑only build (`build_effects.py`, NAM in the IR
category) is still there.

**You do this at your own risk! Do not attempt it if you are not comfortable with running command line tools and 
potentially having to recover your unit yourself!**

> **Unofficial and experimental.** Not affiliated with, endorsed by or supported by Line 6 or Yamaha
> Guitar Group. Installing modified firmware is at your own risk and may void your warranty. Read
> [Recovery](#recovery) before you start, and keep the stock firmware file to hand.

## What you get

**NAM A2 Lite**, with the knobs:

| Knob | What it does |
|---|---|
| **Model** | Which capture plays: the number of the User IR slot that holds it. A slot holding anything else is silent. |
| **Input** | Gain into the capture, −20 to +20 dB; 0 dB at 5.0 |
| **Bass / Mid / Treble / Presence** | A tone stack after the model, ±12 dB, flat at 5.0 |
| **Ch Vol** | Output level; 0 dB at 5.0, +12 dB at 10 |
| **Polarity** | Normal / Inverted |

Where the block lives depends on the image:

| | All‑in‑one (`build_all.py`, recommended) | NAM only (`build_effects.py`) |
|---|---|---|
| Browser | **Distortion → Mono → NAM A2 Lite**, in place of the mono Regal Bass DI (the stereo one stays) | **IR → Single → NAM A2 Lite**, in place of the 1024‑sample IR block |
| Model knob | User IR slots **1–21**, shown as numbers | User IR slots 1–128, with the capture's name |
| A cab IR after it | Yes: the IR blocks are all stock, so a 2048 IR (or any IR block) can follow NAM | **No**: the unit won't put a NAM block and any other IR block in one preset, in either order |
| NAM blocks at once | 2 (a third passes its input through) | 3 |

The Model knob is limited to 21 slots in the all‑in‑one image because the IR name list exists only on IR
blocks and the unit's ordinary list knobs stop at 21 entries. Keep captures in slots 1–21 there.

Everything else in the firmware stays stock 3.80.0, apart from the blocks the custom effects take over:

| Effect | Browser | Replaces |
|---|---|---|
| Click | Delay → Mono | mono Mod/Chorus Echo |
| Geiger | Distortion → Mono | mono Megaphone |
| Commander | Distortion → Mono | mono Xenomorph Fuzz |
| Corrupt | Distortion → Legacy | Octave Fuzz |
| Ottobit | Distortion → Mono | mono Bitcrusher |
| Doom Chug | Distortion → Mono | mono Pocket Fuzz |
| NAM A2 Lite | Distortion → Mono | mono Regal Bass DI |

The stereo versions of the replaced blocks stay.

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

**2. Set up Python once:**

```
python3 -m venv .venv && source .venv/bin/activate
pip install numpy
```

The kernel checks also need a C compiler (`cc`; on a Mac, `xcode-select --install`).

**3. Build one of the two images:**

| Build | What's in it | Command | Writes |
|---|---|---|---|
| NAM | NAM A2 Lite + Click | `python3 build.py nam` | `build/HX_Effects_v3.80.0_NAM_Click_NamRegal.hxf` |
| Full | the above + Geiger, Commander, Corrupt, Ottobit, Doom Chug | `python3 build.py full` | `build/HX_Effects_v3.80.0_All_Commander_Corrupt_Ottobit_Doomchug.hxf` |

Each command does the whole job:

1. It builds the single NAM image and the single Click image. The verifiers compare against these;
   `--quick` skips this step when both images already exist.
2. It builds the image you asked for. Every DSP kernel is first checked bit for bit in the simulator.
3. It reads the image back with its verifier (`tools/verify/verify_nam_click.py` or `verify_all.py`).
4. It prints the file, its MD5 and the flash command.

Flash only an image that ends `verified ALL OK`; if verification fails, the build says so and exits with an
error. In both images NAM is under **Distortion → Mono** (in place of the mono Regal Bass DI), so a cab IR can
go after it, and Click is under **Delay → Mono**. The NAM build takes a few minutes, the full one about ten
(add about four the first time, for the two single images).

Options after `--` go to the builder, e.g. `python3 build.py full -- --with commander` (fewer effects, see the
table below) or `python3 build.py nam -- --nam-host ir` (NAM back in the IR category). Any build also takes a
path to the stock file as its first argument when it isn't in `firmware/`.

**Or run the builders by hand.** `python3 build_effects.py` builds NAM alone, in the IR category
(`build/HX_Effects_v3.80.0_NAM_A2_Lite.hxf`, about 30 seconds); `python3 build_nam_click.py` builds NAM + Click
(`--nam-host regal` is what `build.py nam` passes). The build checks the firmware's MD5 and refuses any other
file; `--no-check` skips the simulator.

**The full image by hand:**

```
python3 build_all.py                      # NAM + all six effects
python3 tools/verify/verify_all.py        # read the image back and check it
```

This writes `build/HX_Effects_v3.80.0_All_Commander_Corrupt_Ottobit_Doomchug.hxf` in a few minutes:
every kernel is first checked bit for bit in the simulator (`--no-check` skips that). It also needs a C
compiler (`cc`) for those checks. Other combinations:

| Command | Image |
|---|---|
| `build_all.py --with none` | NAM + Click + Geiger |
| `build_all.py --with commander` | … + Commander |
| `build_all.py --with commander,corrupt` | … + Corrupt |
| `build_all.py --with commander,corrupt,ottobit` | … + Ottobit |
| `build_all.py --nam-host ir` | the default set, with NAM back in the IR category (file name ends `_NamIR`) |

Every one of these has been flashed and worked on the unit, though the older ones were tested with NAM
in the IR category.

## Click: a metronome block

Click is a metronome that lives in a preset as an ordinary block: the guitar passes through unchanged
and a synthesised click is added. It takes over the **mono Mod/Chorus Echo** delay, so it is found
under **Delay → Mono → "Click"**; the stereo Mod/Chorus Echo and every other delay stay.

| Knob | What it does |
|---|---|
| **Time** | The delay's own Time knob: one beat in ms, or (press the knob) a note value synced to **tap tempo / the global BPM**. Default synced, 1/4. 15–600 BPM. |
| **Beats/Bar** | 2/4, 3/4, 4/4, 5/4 |
| **Accent** | Off, 1–12 dB louder (and higher) on beat 1 |
| **Sound** | Click, Wood, Beep |
| **Level** | Click level, 0–100 % (the guitar is never changed) |
| **Subdivision** | 1/4, 1/8, 1/8T, 1/16 (subdivisions lower and quieter) |

The footswitch bypasses it as any block. Timing is drift‑free (exact integer arithmetic on the DSP).

Two ways to build it (each also needs a C compiler, `cc`, for the simulator check of the kernel):

```
python3 build_click.py        # build/HX_Effects_v3.80.0_Click.hxf: Click only (no NAM)
python3 build_nam_click.py    # build/HX_Effects_v3.80.0_NAM_Click.hxf: NAM and Click together
```

Both have been flashed and work on an HX Effects. Install the file the same way as the NAM build. The
effect itself (a C reference, tests and the hand‑written SHARC kernel) is in `effects/`; see
[effects/README.md](effects/README.md).

## Geiger: a bit crusher

Geiger reduces the sample rate and bit depth and then shapes the result through one of 16 curves
(original ones: folds, rectifiers, Chebyshev, steps, a spline…). It takes over the **mono Megaphone**
(Distortion → Mono → "Geiger"; the stereo Megaphone stays).

| Knob | What it does |
|---|---|
| **Gain** | Drive into the crusher, 0–36 dB |
| **Sample Rate** | 250 Hz – 48 kHz (sample‑and‑hold; aliasing is part of the sound) |
| **Bit Depth** | 1–16 bits |
| **Curve** | Linear, Soft, Hard, Sine Fold, Tri Fold, Full Wave, Half Wave, Steps, Asym, Cheby 3, Cheby 5, Sine, Root, Spline, Ring, Gate |
| **Tone** | Low‑pass after the curve, 200 Hz – 20 kHz |
| **Output** | −36 to +12 dB |
| **Mix** | Dry/wet |
| **Anti‑Alias** | On filters before the sample‑and‑hold |

It is in every all‑in‑one image (`build_all.py`; `--with none` for just NAM, Click and Geiger). In
those images NAM runs **two** blocks at once instead of three (a third NAM block passes its input
through): that is the DSP memory Geiger uses. Working on the unit since 2026‑11‑04.

## Commander and Corrupt: octave fuzz and tracking synth

**Commander** is a square‑wave octave fuzz: it turns the note you play into a square wave and mixes in
squares one and two octaves below and one octave above. It takes over the **mono Xenomorph Fuzz**
(Distortion → Mono → "Commander"; the stereo Xenomorph stays).

| Knob | What it does |
|---|---|
| **Fuzz** | The square at the note you play |
| **Sub -1 Oct** | A square an octave below |
| **Sub -2 Oct** | A square two octaves below |
| **Octave Up** | A square an octave above |
| **Tone** | Low‑pass, 100 Hz – 10 kHz |
| **Output** | −36 to +12 dB |
| **Gate** | Off, or −84 to −30 dB: below it the fuzz fades out (default −72 dB) |
| **Dry** | 0–100 % of the clean signal mixed back in |

**Corrupt** is a monophonic synth that follows your playing: it measures the pitch of each note and runs
its own square‑wave oscillator at that pitch (or an interval of it), with glide between notes. It takes
over **Octave Fuzz** (Distortion → Legacy → "Corrupt").

| Knob | What it does |
|---|---|
| **Square** | The input squared up, as a fuzz (the raw tracking signal) |
| **Master** | The oscillator |
| **Sub** | A square an octave below the oscillator |
| **Glide** | 0 = jumps to each new note; up to a slow slide |
| **Tone** | Low‑pass, 100 Hz – 10 kHz |
| **Output** | −36 to +12 dB |
| **Root** | The oscillator at −2 Oct, −1 Oct, Unison or +1 Oct |
| **Harmonic** | 1x–8x the root: 2x an octave, 3x a fifth above that, 5x a third, … |

Both like single notes, the neck pickup and the tone rolled back a little; chords make them glitch
(that is part of the sound). Both are in the default all‑in‑one image; `--with commander` builds one
with Commander alone.

To make room, NAM keeps its two blocks but moves more of its working memory to DDR2 (`nam_multi.py
--far-d 17`), and the DSP's boot stream loads the kernels' zeroed state with zero‑fill records instead
of stored zeros: that stream must fit a 512 KiB partition, and with all five blocks it has about 800 bytes
left. In the image with both, Commander and Corrupt share one kernel (one copy of the common parts).
**Both work on the unit** (2026‑11‑04).

## Ottobit: a sequenced bit crusher

Ottobit crushes the signal like Geiger, but a pattern steps its sample rate and filter up and down in
time, and random stutters loop short slices. It takes over the **mono Bitcrusher** (Distortion → Mono →
"Ottobit").

| Knob | What it does |
|---|---|
| **Sample Rate** | 250 Hz – 48 kHz, the base rate the pattern moves around |
| **Bit Depth** | 1–16 bits |
| **Filter** | A resonant low‑pass after the crusher |
| **Pattern** | Off, or 1–8: six‑step patterns of rate and filter multipliers |
| **Speed** | 0.5–16 steps a second |
| **Stutter** | The chance that a step loops a short slice instead |
| **Output** | −36 to +12 dB |
| **Mix** | Dry/wet |

Up to four Ottobit blocks can run at once in the simulator; more than one hasn't been tried on the unit. It runs as an **overlay**: its code and data travel in the
DSP's graph library and a small resident stub copies them into DSP memory, because there was no room
left to load it at boot. Works on the unit (2026‑11‑09).

## Doom Chug: a low drone generator

Doom Chug ignores the guitar (which passes through untouched) and adds a dark drone: four detuned saw
voices on the root, a slightly sharp root, the fifth and the octave, wandering and wobbling, stepping
through a pattern. Every pitch stays between 110 Hz (the open A string) and 440 Hz. It is meant to be
fed into Ottobit, Geiger or Commander. It takes over the **mono Pocket Fuzz** (Distortion → Mono →
"Doom Chug").

| Knob | What it does |
|---|---|
| **Key** | The root note, A to G# |
| **Pattern** | Off, or 1–8: crawl, blue note, flat second, tritone, descent, falling minor, octave riff, lost |
| **Rate** | How often it steps: once every 20 seconds to 8 times a second |
| **Drift** | How far each voice wanders at random, up to half an octave |
| **Warble** | Uneven wobble in each voice's pitch and level |
| **Chug** | Meant to turn the drone into a thud on each step; see [Limits](#limits) |
| **Tone** | Dark to bright |
| **Level** | Drone volume |

Only one Doom Chug works per preset (a second one passes its input through). On load it glides up to
its notes from low A. Works on the unit (2026‑11‑10).

## Tuning the declared DSP cost

The block declares a DSP cost of 2300 (`DSP_COST` in `build_effects.py`; it was 2700 until 2026‑11‑10). That number is bookkeeping
only: the app uses it to decide when to grey out other blocks, and it has no effect on what the DSP
actually does. The kernel was measured in the simulator at about 23% of a block (34,000 of 150,000
cycles per audio block); stock blocks declare costs in roughly hundredths of a percent, so the honest
figure is around 2300. Two NAM blocks and a few effects fit in one preset.

If you want to trade some of that margin for more blocks:

1. `DSP_COST` in `build_effects.py` is already at the 2300 the measurement supports; don't go below it.
   If you change it, rebuild and flash.
2. Build the heaviest preset the unit now allows: two NAM blocks plus whatever was previously greyed
   out (the dynamic reverbs, Shimmer, Poly Pitch, Cosmos Echo are the heavy ones).
3. Stress it: big chords, long reverb tails, and change **Model** on both blocks while notes ring. A
   capture change is the kernel's worst case.
4. Crackling, dropouts or a block going silent means the number is too low: raise it and rebuild.

Declaring too little lets the app accept a chain the DSP can't service; declaring too much only costs
you a block you might have fitted. When in doubt, leave it at 2300.


## Install

**Double check that you have a backed up version of the .hxf firmware file for your unit- you may need it for recovery!**

1. In HX Edit, back up your presets and IRs, then **close HX Edit**.
2. Open Line 6 Updater, choose **Choose File**, pick the image you built:
   `build/HX_Effects_v3.80.0_All_Commander_Corrupt_Ottobit_Doomchug.hxf` (all‑in‑one) or
   `build/HX_Effects_v3.80.0_NAM_A2_Lite.hxf` (NAM only).
3. Let it finish and restart the unit. A normal boot means the install worked; see
   [Recovery](#recovery) if it shows "Boot Failure" or stops at the splash.

**Note- you may find the software says there was a problem, just try again and it should work on the second try (this tends to be 
more likely when recovering from scratch, not when updating an already working firmware.**

### Flashing from the command line

`tools/flash.py` does the same update as Line 6 Updater, over USB, and then checks that the unit boots
back into its main app. Close HX Edit and Line 6 Updater first, then:

```
pip install pyusb libusb-package      # once, in the .venv
.venv/bin/python tools/flash.py flash build/HX_Effects_v3.80.0_All_Commander_Corrupt_Ottobit_Doomchug.hxf
```

It checks the file (product, MD5, every entry's checksum), asks you to type `flash`, then: restarts the
main app into its USB DFU loader, loads the updater app from the `.hxf`, writes all 14 images (about
100 seconds), and waits for the unit to answer as `F15Main`. It ends with `BOOTED` or `BOOT FAILED`
(exit code 0 or 1), so it can follow a build in a script. If it stops partway, the unit is left in
updater mode; run it again, or use Line 6 Updater. `.venv/bin/python tools/flash.py info` shows what the unit is
running without changing anything.

Before writing, it lists images the unit flags. Image 4 is always listed: the updater app flags any
image longer than its partition's declared size, and image 4's partition is declared as 10 MiB while
stock 3.80.0's image 4 is already 12.4 MB (ours is 14.3 MB). The physical space before the next
partition is 15.5 MiB, which is the limit the build checks against. Line 6 Updater rewrites flagged images
first and so does this tool; it is not damage.

"Booted" means the main app came up and answers on USB. It does not yet tell a clean boot from one that
stops at a "Boot Failure" message, so glance at the screen as well.

The protocol was taken from a USB capture of Line 6 Updater 1.28 (`tools/usb/`: `capture.sh` runs the
Updater with a logging libusb shim, `decode.py` reads the log), and `.venv/bin/python tools/flash.py replay
<file.hxf> <log>` checks the tool against such a capture byte for byte. It is tested on 3.80.0 only.

## Use

1. Convert a capture to a User IR:
   ```
   python3 tools/nam2ir.py "My Amp.nam" -o "My Amp NAM.wav"
   ```
   The `.wav` is about 8 KB: it is not a sound, it carries the capture's weights.
2. In HX Edit's **Impulses** tab, import the `.wav` into a User IR slot (say slot 5). Do this with a
   preset selected that has no NAM block in it; HX Edit does not understand the NAM block (see Limits).
3. On the unit, add a block, choose **Distortion → Mono → NAM A2 Lite** (all‑in‑one image) or
   **IR → Single → NAM A2 Lite** (NAM only), and set **Model** to 5.
4. For a cab, add a **2048‑sample IR** block after NAM (all‑in‑one image only) and pick a cab IR in another slot.

Captures and cab IRs share the 128 User IR slots. A layout that's easy to remember helps: for example
captures in slots 1–20 (the all‑in‑one image's Model knob reaches 1–21) and cab IRs from 22.

For a batch, number the output files after the slot each one will go in (`01 Clean.wav`, `02 Lead.wav`, …),
so the file name tells you the Model setting. A capture that holds several sizes (an A2 `.nam` with a
"SlimmableContainer") converts fine: `nam2ir.py` takes its 3‑channel Lite size. Getting the files onto the unit
still needs HX Edit; a USB upload tool like the flasher is on the to‑do list (HANDOVER.md, Open / next).

## Try it quickly: the demo captures

The `captures/` folder holds a few NAM A2 Lite captures **already converted** with `tools/nam2ir.py`,
so you can hear the block without converting anything yourself:

1. Open HX Edit, go to the **Impulses** tab, and drag the `.wav` files from `captures/` into free
   User IR slots (note the slot numbers). Do this with a preset selected that contains no NAM block.
2. On the unit, add NAM A2 Lite to a preset (see [Use](#use) for where it is) and set **Model** to one of
   those slot numbers. In the NAM‑only image the capture's name shows on the strip once it's selected.
3. Set Input, Bass/Mid/Treble/Presence and Ch Vol to 5.0 for the capture as recorded, then adjust.

Each `.wav` is about 8 KB and is not an audio IR: it carries the capture's 1,871 weights behind a
small header. Loading one into the stock 2048‑sample IR block does nothing useful.

## Limits

- **HX Edit cannot edit the NAM block.** It shows "Failed to load model (code −8200)" when a preset
  containing one is selected, because its own definition of the block NAM replaced has fewer knobs than
  the unit's now has. Edit NAM blocks on the unit; use HX Edit for everything else (IR import works).
  The custom effects take over stock blocks the same way, so expect the same in HX Edit for them.
- In the all‑in‑one image the **Model knob reaches slots 1–21** only.
- In the NAM‑only image a preset **can't hold a NAM block and another IR block** (see
  [What you get](#what-you-get)); the all‑in‑one image doesn't have this problem.
- **Two NAM blocks in a split:** with one NAM in each path, the bottom path is much quieter. Not
  investigated.
- **Doom Chug's Chug knob** does almost nothing audible on the unit except lower the level. Not
  investigated yet.
- Presets made with NAM in the IR category load a stock 1024 IR block in its place after switching to
  the all‑in‑one image: add NAM again from Distortion → Mono.
- Presets store the slot number, not the capture: moving a capture to another slot means updating the
  presets that use it.
- Only 3‑channel A2 Lite captures fit; standard and A2 Full captures don't.
- **Line 6's own amps can't be added.** The firmware still holds all of them, and small ones ran as effect
  blocks, but every attempt to run the bigger ones locked the unit's screen (2026‑11‑11 to 13; see
  HANDOVER.md). The idea is dropped.
- The block's DSP cost is declared as 2300 (like a heavy stock block), so the unit greys out other heavy
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
- In the all‑in‑one image NAM takes over the mono Regal Bass DI's identity instead, on the same IR
  graph: Distortion blocks get ordinary knob pages, so Model becomes a plain list knob, and the IR
  category is left stock. On the unit, NAM in the IR category shut out every other IR block; the most
  likely reason is an app rule allowing one IR block type per preset (the check itself hasn't been found).
- Click works the same way on the mono Mod/Chorus Echo's identity, on a copy of the IR block's graph with
  its own primitive (0x0128 in the combined image). A delay host matters: HX draws a delay with ordinary
  knob pages, where an IR block's pages treat knob 1 as the IR selector. Its tempo sync is the stock
  delay's own: the two parameter‑map steps that turn Time, the note value and the global tempo into a
  beat length are copied from Mod/Chorus Echo.
- In the combined images Click's kernel sits in the top of DSP memory block 3, above NAM's, and the DSP's
  graph buffer is larger (so NAM's DDR2 working memory starts higher). Geiger, Commander, Corrupt and
  Doom Chug are packed between NAM and Click. Ottobit is an overlay (see its section).
- The two hard limits are the DSP boot stream (a 512 KiB partition, about 2 KB left in the default
  image) and DSP memory block 3 (a few dozen words left). Another resident effect won't fit without
  freeing space first; further effects would have to be overlays. Details: `docs/baseline-audit.md`.

## Layout

```
build.py                  the two builds in one command each: nam, full (build, verify, print MD5)
build_effects.py          NAM alone, in the IR category
nam_host.py               where NAM sits (Regal Bass DI or 1024 IR), shared by build_all.py and build_nam_click.py
build_all.py              the all-in-one image: NAM and all six effects (--with, --nam-host: other sets)
build_click.py            Click only; build_nam_click.py: NAM and Click
firmware/                 where you put the stock .hxf (git-ignored, never committed)
captures/                 demo NAM A2 Lite captures, already converted to User IR .wav files
.gitignore                keeps firmware/, build/ and every .hxf out of version control
README.md                 this file
HANDOVER.md               the state of play and how things were found, for picking the project up
build/                    the output (created by the build)
tools/                    hxf.py, l6ia.py, l6ia_verify.py, patch_amp.py, nam2ir.py
tools/flash.py            USB flasher with boot check (see Flashing from the command line)
tools/usb/                usblog.c + build_shim.sh + capture.sh (log Line 6 Updater's USB traffic), decode.py
tools/sharc/              the kernel (nam_multi.py, nam_multi_kernel.asm), nam_lite.py, nam_pack.py,
                          sasm.py and ssim.py (assembler, simulator), entry4_blob.py, recips_table.json
src/sharc/nam_a2.asm      the reference NAM A2 implementation the simulator check compares against
tools/verify/             read-back checks of the Click, NAM + Click and all-in-one images
effects/                  custom effects: C references, tests, renderer, SHARC kernels (effects/README.md)
docs/baseline-audit.md    the primitive ABI and memory map, marked observed / modelled / unknown
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
