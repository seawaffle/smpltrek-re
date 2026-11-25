# How to put your own wavetables on a CyDrums

A step-by-step guide to `tools/cydrums_wavetables.py`, written for someone who has never used it. No programming is
needed: you will copy one file off the card, type one command, and copy the result back.

## What it does

The CyDrums' 64 oscillator wavetables (the WAVE 1-64 choices on the oscillator page) are not part of the firmware.
They are all in one file on the storage card, `CyDrums/System/SystemCore.bin`. The tool makes a new copy of that file
with the slots you choose replaced by your own wavetables, under names you choose. Every other slot stays exactly
as Sonicware made it.

The tool only creates a new file on your computer. It never changes your original file, the card or the device.

## Before you decide

**This is unofficial and has not been tried on a CyDrums.** It has been checked in this project's emulator: the
CyDrums firmware (1.1.84) started with a custom file and loaded the new wavetable data correctly. Nobody has
listened to a custom wavetable on a real unit yet. A bad file can at worst make sounds wrong or stop the CyDrums
finding its sounds; putting the original file back undoes it.

**What changes on the unit:**

- **Presets that use a slot you replace will sound different.** Sounds remember their wavetable by slot number, and
  the shipped patterns use all 64 slots. Replace the slots you use least, or accept that some presets change.
- **The bank stays at 64 wavetables.** You can replace slots, not add new ones.
- **Keep the slot order.** Moving or swapping the stock tables between slots is not supported; it is not known
  whether the firmware finds a sound's wavetable by number or by an internal name.

**Not yet known:** how the WAVE scan position maps onto the frames of a table, and what the "rate" value stored with
each table does. The tool stores 24000, as most stock tables do. If a custom table plays at an odd pitch or
scan speed, tell us; that is exactly the evidence that is missing.

## What you need

- **Python 3** on your computer (python.org; on Windows tick "Add python.exe to PATH" when installing).
- **This repository**, downloaded or cloned. The commands below are typed in a terminal opened in its folder.
- **Your CyDrums' card**, or the `CyDrums_folder.zip` download from Sonicware, which contains the same file.
- **Your wavetables** as WAV files (next section).

On Windows, type `python` where this guide says `python3`.

## Preparing your wavetables

A CyDrums wavetable is 256 frames, each one cycle of 2048 samples. The tool converts what you give it:

- **Serum and Vital exports work as they are.** Both save wavetables as WAV files of 2048-sample frames; Serum also
  stores the frame size in the file, and the tool reads it.
- **One frame of any other size?** Add `--frame N` (N = samples per frame) and the tool resamples to 2048.
  A single-cycle waveform is fine: it is repeated across all 256 frames, so scanning has no effect.
- **Fewer than 256 frames:** the tool blends smoothly from each frame to the next. A 4-frame file becomes a
  256-step morph through those 4 shapes.
- **More than 256 frames:** 256 evenly spaced positions are taken from first to last frame, blending the two nearest
  frames where a position falls between them.
- **Formats:** 8, 16, 24 or 32-bit PCM, or 32-bit float. Stereo is mixed to mono. The sample rate in the file
  does not matter; only the frame length does.
- **Level:** kept as it is. Normalise in your editor if you want full level; anything over full scale is clipped.

## Step 1: get SystemCore.bin

Either copy `CyDrums/System/SystemCore.bin` off your card (with a card reader, or the CyDrums' CARD READER mode
over USB; manual p. 160), or take it from `CyDrums_folder.zip`.

**Keep a backup copy of the original.** You need it to undo the change, and as the base for every new build.

The file is Sonicware's content. Keep it, and anything you export from it, to yourself.

## Step 2: look at the slots

```
python3 -B tools/cydrums_wavetables.py list SystemCore.bin
```

This prints the 64 slots: slot number (the same as WAVE 1-64 on the unit), name, and where the data sits.
To hear or look at stock tables before choosing, export them as WAV files:

```
python3 -B tools/cydrums_wavetables.py export SystemCore.bin stock-tables --slots 1,2,64
```

Each exported file holds one table as 256 frames of 2048 samples, so wavetable editors that assume 2048-sample frames
(Serum and Vital do by default) open it as a wavetable.

## Step 3: build your file

```
python3 -B tools/cydrums_wavetables.py build SystemCore.bin MySystemCore.bin --set 62=mywave.wav:MyWave
```

- `62` is the slot to replace (1-64).
- `mywave.wav` is your file. Put the path in quotes if it contains spaces.
- `:MyWave` is the name shown on the unit: up to 10 letters, digits or symbols (plain ASCII). Leave it out to use
  the file name (cut to 10 characters).

Replace several slots at once by repeating `--set`:

```
python3 -B tools/cydrums_wavetables.py build SystemCore.bin MySystemCore.bin \
    --set 62=growl.wav:Growl --set 63=glass.wav:Glass --set 64=morph.wav:Morph
```

(`--frame` applies to every file in that command, so build files with different frame sizes in separate passes:
use the first output as the input of the next.)

The tool prints each slot it replaced and the size of the new file, which is always 67,116,544 bytes, like the
original. If it stops with a message instead, nothing was written; the message says what to fix.

To check the result, run `list` on `MySystemCore.bin`: your names should be in the slots you chose.

## Step 4: put it on the card

1. Power the CyDrums off and take the card out (or leave CARD READER mode).
2. On the card, replace `CyDrums/System/SystemCore.bin` with your file, **renamed to `SystemCore.bin`**.
3. Put the card back and power on.
4. Choose a sound, open its oscillator page and turn WAVE to a slot you replaced. Its name should be yours.

## Undo

Copy your backup of the original `SystemCore.bin` back onto the card under the same name. Nothing else on the card
is changed by this tool, so that restores the stock wavetables completely.

## If something goes wrong

- **"BLANK MEDIA!" at start-up:** the CyDrums cannot find `CyDrums/System/SystemCore.bin`. Check the folder and
  the exact file name.
- **A replaced slot sounds wrong** (pitch, scan speed, clicks): please note which file and slot, and how it
  differs. The frame mapping and the rate value are the open questions above.
- **The tool refuses the base file:** it only builds from a file with the stock layout. Start from your backup of
  the original, not from a file another tool changed.

## How it works

The file format, the firmware code that reads it and what is still unknown: [01-platform-map.md](01-platform-map.md),
"CyDrums wavetable bank". The tool's own notes are at the top of `tools/cydrums_wavetables.py`.
