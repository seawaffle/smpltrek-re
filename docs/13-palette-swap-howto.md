# How to use the palette swap tool

A step-by-step guide to `tools/palette_swap.py`, written for someone who has never used it. No programming is
needed, but you will type two commands and you will be installing unofficial firmware on your device, so read
"Before you decide" first.

## What it does

SmplTrek, Lofi-12 XT and CyDrums are built on the same circuit board. Each device only accepts update files made
for it, and it tells them apart by a few bytes at the start of the file. The palette swap tool takes an official
update for one of the three and rewrites those few bytes (9 of them) so that another of the three will accept it.

It does not change the firmware itself. If you put the Lofi-12 XT firmware on a SmplTrek, you get the Lofi-12 XT
app exactly as Sonicware wrote it, running on a SmplTrek whose buttons are labelled for something else.

The tool only creates a new file on your computer. It never touches your device or your original download.

## Before you decide

**This is unofficial.** Sonicware does not support it, and it may void your warranty. Nobody can promise it is
safe for your unit.

**Everything here was tried on one SmplTrek.** Its SYSTEM INFO page shows `BOOT 1.0.17`. If yours shows a
different BOOT version, none of this has been checked for it.

What has actually been done on that SmplTrek:

| Firmware | Result | Record |
| --- | --- | --- |
| Lofi-12 XT 1.5.205, file straight from this tool | Accepted up to the "Are you sure?" screen, then cancelled. Never installed. | W1 in [experiments/README.md](../experiments/README.md) |
| Lofi-12 XT 1.5.205, with one extra change (below) | Installed and ran. Stock SmplTrek firmware restored afterwards, settings unchanged. | [C3](../experiments/sessions/C3-crossflash.md) |
| CyDrums 1.1.84, with the same extra change | Installed and ran, with working audio playback and editing. Stock SmplTrek firmware restored afterwards, settings fine. | [C5](../experiments/sessions/C5-crossflash-cydrums.md) |

What has not been done:

- **A file straight from this tool has never been installed.** The two firmwares that ran had one extra change:
  the part of the app that saves settings was switched off, so the foreign app could not write its own settings
  over the SmplTrek's. A file from this tool alone leaves that part on. Expect the foreign app to save its
  settings in its own format, and the SmplTrek firmware to misread some of them after you go back. That has been
  predicted from reading the code, not observed.
- **Nothing has been installed on a real Lofi-12 XT or CyDrums.** The tool can make files for them, but whether
  those devices accept the files, and whether their recovery works the same way, is unknown.
- CyDrums 2.0.97 beta has not run on a SmplTrek.

The extra change is described in [tools/patches/README.md](../tools/patches/README.md). For Lofi-12 XT 1.5.205,
`tools/patches/sterilise_lofi.py` builds the exact file that ran in C3, ready for a SmplTrek, so you do not need
the palette swap tool for that one. There is no such builder for CyDrums in this repository.

**The way back** is the device's own BOOT MODE, which installs an official update even when the installed app
does not start. On the SmplTrek this has worked every time it was needed, including with a deliberately broken
app installed. [SAFETY.md](../SAFETY.md) has the full list of what can go wrong and the evidence for each line.

## What you need

- A computer with Python 3.10 or newer ([python.org](https://www.python.org/downloads/)). Nothing else has to
  be installed.
- This repository, downloaded and unpacked. The tool needs the other files in `tools/`, so keep the folder
  together.
- **The official update for the firmware you want to try**, from Sonicware's website. Leave it as the `.zip`
  you downloaded.
- **The official update for the device you own**, also from Sonicware. This is your way back.
- **Two SD cards, FAT32.** One for the converted file, one for the official file of your own device. Do not use
  the card that holds your projects.
- The device's power adapter. Take the batteries out for the whole session: an app that hangs leaves the unit
  frozen with a dead power key, and unplugging is then the only way to turn it off.

## Steps

### 1. Write down what your device shows now

Power on normally and open the version page: press **func + system** to open the SYSTEM MENU, select
**INFORMATION** and press **OK** (the same on all three devices, from their manuals). Note the BOOT and SYSTEM
versions. A photo is enough. Also note any settings you care about. Power off.

### 2. Prepare the recovery card first

Unzip the official update **for your own device**. Inside is one `.bin` file (`SmplTrek.bin`, `Lofi-12 XT.bin`
or `CyDrums.bin`). Copy it to the top level of the second SD card, on its own, without renaming it. Label the
card and put it aside.

Do this before anything else. The converted file in step 4 will have exactly the same name as this one, and the
card is the only way to tell them apart.

### 3. Run the tool

Open a terminal (Terminal on macOS or Linux, PowerShell on Windows), go to the unpacked repository folder, and
run:

```sh
python3 -B tools/palette_swap.py
```

On Windows the command may be `python` or `py` instead of `python3`.

It asks two questions:

1. **The path to the official firmware.** Type or paste the path of the `.zip` you downloaded for the firmware
   you want to try.
2. **Which device it will be installed on.** Type `smpltrek`, `lofi12` or `cydrums`. This is the device you own,
   not the firmware you are converting.

It then shows what it found and a warning. Read it. Type `YES` in capitals to continue; anything else cancels
and nothing is written.

If you prefer, both answers can go on the command line:

```sh
python3 -B tools/palette_swap.py firmware/lofi12/Lofi-12XT_v1.5.205.zip --to smpltrek
```

### 4. Check what it wrote

The tool writes one new file in the folder you ran it from, named the way the target device expects
(`SmplTrek.bin` for a SmplTrek). It ends with something like:

```
Wrote SmplTrek.bin (1,707,049 bytes)
Changed 9 byte(s), header only:
  offset 0x10: family word 12 -> 5
  ...
```

If it says `Refused:` instead, nothing was written. The usual reasons:

| Message | What it means |
| --- | --- |
| "this file bundles a content (pmtd) image" | That release also carries factory sounds and data. The tool only converts system-only updates. Try another release. |
| "It is probably ALREADY a converted file" | You gave it a file that was already converted. Start again from the official download. |
| "output file ... already exists" | A file with that name is already in the folder. Move it away and run the tool again. |
| "Nothing to do" | The firmware is already for the device you named. |

### 5. Put the converted file on the first card

Copy the new file to the top level of the first SD card, on its own, without renaming it. Label this card too.

If you are trying CyDrums: it keeps its sounds on the card and shows only a "download files" page without them.
Unzip Sonicware's CyDrums folder download and copy the `CyDrums` folder to the top level of the same card.
CyDrums writes to this card in normal use.

### 6. Install it

This is the device's ordinary firmware update, as in its manual ("Firmware updates"). The button that starts it
is the fourth button of the upper row on all three devices, and what counts is the device you are holding, not
the firmware on it:

| Device you own | Hold this while pressing the power button |
| --- | --- |
| SmplTrek | **HOME** |
| Lofi-12 XT | **PAD** |
| CyDrums | **PAD** |

Unplug USB. Turn the volume down. Then:

1. Put the first card (the converted file) in the device.
2. Hold the button from the table and press and hold the power button. The device starts in BOOT MODE instead
   of its normal app.
3. Select **SYSTEM UPDATE** and press **OK**.
4. The device checks the file and shows a line such as `SYSTEM: V3.2.174 -> V1.5.205`: the version installed
   now, then the version in the file. **This is the last point where nothing has been written.**
   - If the line is not what you expect, or more than a SYSTEM line is listed, press **CLR** to cancel.
   - If it says the file is invalid, nothing was written. Check that you converted for the right device.
5. Select **YES** and press **OK** to install. It shows Erasing, Writing, Verifying, then `Update completed.`
   Do not remove the card or the power while it works.
6. Press the power button to shut the unit down, then power on normally.

### 7. Use it

The app that starts is the other product's app. The buttons do what that product's buttons do in the same
position on the panel, whatever is printed on yours. [10-cross-flash-button-map.md](10-cross-flash-button-map.md)
lists which SmplTrek button is which for Lofi-12 XT and CyDrums.

Power off at once if you hear loud noise, or notice heat or a smell.

### 8. Go back to the official firmware

1. Power off. Put the recovery card from step 2 in the device.
2. Enter BOOT MODE exactly as in step 6, with the same button. The foreign app does not change this: a SmplTrek
   running the CyDrums app still uses HOME.
3. Select **SYSTEM UPDATE**, check the version line, select **YES** and press **OK**.
4. Shut the unit down, then power on normally. Open the version page and compare with what you noted in step 1.

If you installed a file straight from this tool, check your settings now; some may need setting again.

## If something goes wrong

| What you see | What to do |
| --- | --- |
| "This file is invalid" in BOOT MODE | Nothing was written. Your device is as it was. |
| The update stops or fails at Verifying, or power was lost during it | The app will not start, but BOOT MODE still works. Enter it as in step 6 and install the official file from the recovery card. |
| Frozen on the SONICWARE logo, power key does nothing | The installed app hangs. Unplug the adapter (and remove the batteries if fitted), then enter BOOT MODE as in step 6 and install the official file. |
| The app starts but behaves oddly | Power off and go back to the official firmware (step 8). |
| BOOT MODE does not appear after three tries | Stop. Do not keep trying things. This has not happened on the unit tested here. |

These recoveries are known to work on a SmplTrek with BOOT 1.0.17. On a Lofi-12 XT or CyDrums the way into
BOOT MODE is the one in their manuals (PAD + power), but recovering from unofficial firmware has not been tried
on either.

## More detail

- [SAFETY.md](../SAFETY.md): what each kind of change risks, and the evidence.
- [12-update-container.md](12-update-container.md): the update file format and exactly which bytes the tool
  changes.
- [experiments/sessions/](../experiments/sessions): the full records of the runs on the unit.
