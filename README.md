# SmplTrek family firmware reverse engineering

Reverse engineering of the Sonicware SmplTrek, Lofi-12 XT and CyDrums. All three are one board: a TI
TMS320C6748 (C674x VLIW DSP) running TI SYS/BIOS, DDR2, two 16 MiB SPI NOR flashes, a codec whose register
use matches the TI TLV320AIC3106 on McASP0, and an Artery AT32F421 panel MCU on a UART that reads the pads and drives the LEDs.
The firmware is unencrypted C++ (TI C6000 compiler, RTTI intact), and the three products share one hardware
layer and C++ framework. ELZ_1 play, MINIMAL and the Liven line use the same update
container, and their images are built for the same TI device class (INT-17); which exact part each product uses is not
confirmed. The original ELZ_1's updates use an older container layout.

Everything here was recovered from Sonicware's public update files, a software read of one unit's flash,
and non-invasive bench sessions on that unit. No unit was opened. No Sonicware binaries, manuals or code
extracts are in this repository: it holds tools, recovered facts (addresses, names, hashes, protocols)
and the records of every run on the device. Not affiliated with or endorsed by Sonicware.

The headline result: an update file is a `cmtd` container whose integrity fields are seeded IEEE CRC-32s
with per-product seeds. Rewrapping one product's system image with another product's family word and seeds
makes the bootloader accept it: [tools/palette_swap.py](tools/palette_swap.py) does this for any pair of the
three products. **The Lofi-12 XT 1.5.205 firmware has installed, booted and run on a SmplTrek** (device session C3,
[experiments/sessions/C3-crossflash.md](experiments/sessions/C3-crossflash.md)),
rewrapped this way with its settings writer disabled first
([tools/patches/sterilise_lofi.py](tools/patches/sterilise_lofi.py)) so it could not write over the SmplTrek's
own settings blocks; the unit was then restored to stock. The other directions are built and checked offline
but have not run on a unit.

## Start here

- [Overview](docs/00-overview.md): the platform in one page, and the index to the other docs.
- [Safety](SAFETY.md): what can and cannot brick a unit, recovery (HOME + power reaches BOOT MODE), and the
  evidence for each claim. Read it before flashing anything.
- [Update container and integrity](docs/12-update-container.md): `cmtd`/`pmtd`/`mmtd`, descriptors, family
  words, the CRC seeds, and what the bootloader checks.
- [Platform map](docs/01-platform-map.md): settings, tasks, interrupts, power, SD, USB, MIDI, audio and the
  per-product differences, by address, for SmplTrek 3.2.174 with Lofi-12 XT and CyDrums alongside.
- [Hardware access](docs/04-hardware-access.md): register-level use of every peripheral the firmware touches.
- [Bootloader](docs/05-bootloader.md): BOOT 1.0.17, traced from the flash read.
- [Open questions](UNKNOWNS.md) and [the claims registry](claims.json): what is established, at which
  evidence level (device, static, file), and what is still open.
- [Device records](experiments/README.md): every run on the unit, with hashes, procedure and result.

## Repository layout

- [docs/](docs/00-overview.md): numbered subsystem write-ups.
- [symbols/](symbols): per-release symbol files (functions, globals, classes, with evidence) for eight
  SmplTrek, three Lofi-12 XT, one CyDrums, ELZ_1 play and MINIMAL releases; `symbols/hand/` holds the
  hand-named seeds they are carried from.
- [analysis/](analysis/README.md): the static-analysis and simulation pipeline: container and section
  extraction, RTTI recovery, library and source matching, function matching between releases, and `c6sim`, a
  small C674x simulator that runs single firmware functions against modelled peripherals.
- [tools/](tools/README.md): container parser and CRC verifier/resealer, the cross-product
  [palette swap](tools/palette_swap.py), section patch tools ([tools/patches/](tools/patches/README.md)),
  and the GNU `tic6x-elf` binutils/GCC build scripts with ABI checks ([tools/toolchain/](tools/toolchain/README.md)).
- [emulator/](emulator/README.md): a C6748 board emulator that boots the stock SmplTrek firmware to its UI,
  with display, panel, SD card, USB and audio models, and loads user-supplied DSP programs.
- [ghidra/scripts/](ghidra/scripts): headless Ghidra scripts that apply the symbol files;
  [analysis/ghidra_import.sh](analysis/ghidra_import.sh) imports a release.
- [experiments/](experiments/README.md): the device log and per-session records.
- `firmware/`: ignored; Sonicware's update files go here ([layout](firmware/README.md)).
- `work/`: ignored; regenerated listings, ELFs and Ghidra projects (they contain Sonicware code).

## Reproduce

Run everything from the repository root with Python 3.10 or later; host `gcc` and `g++` are needed for the
emulator and some analysis tests. Each step adds coverage, and a test whose inputs are missing skips with the
reason instead of failing.

```bash
# 1. Fresh clone, nothing else: synthetic and self-contained tests run, the rest skip.
python3 -B -m unittest discover -s tools -p "test_*.py"
python3 -B -m unittest discover -s tools/patches -p "test_*.py"
python3 -B -m unittest discover -s analysis
python3 -B -m unittest discover -s emulator/tests -p "test_*.py"

# 2. Put Sonicware's update files in firmware/ (layout in firmware/README.md), then:
python3 -B tools/sonicware_integrity.py verify --profile smpltrek firmware/smpltrek/*.zip   # 22/22 fields
python3 -B tools/palette_swap.py firmware/lofi12/Lofi-12XT_v1.5.205.zip --to smpltrek      # writes a new file only

# 3. Build the tic6x toolchain into tools/tic6x/ (no root; binutils is enough for the analysis pipeline,
#    GCC adds the compiled-code tests), then regenerate work/ (ELFs, listings, RTTI, matches; about 30 s):
tools/toolchain/build_tic6x_binutils.sh
tools/toolchain/build_tic6x_gcc.sh
analysis/make_work.sh

# Then rerun the four suites of step 1.
```

With all three steps, every test runs except those that need what this repository cannot provide:

- a 32 MiB flash read of a unit (`work/a4/`): the bootloader extraction, boot-cache and one settings-block test;
- TI's C6000 compiler and StarterWare headers (`~/ti`, or `$TI_CGT`): the differential checks of `c6sim` against
  TI-compiled code and the pin-mux names in `mmio_trace`.

The analysis suite takes about 20 minutes with everything present; the emulator suite about 6.

## Safety status

Proven on one unit (BOOT 1.0.17, MCU 1.0.6): official updates of any version, including downgrades, install
and restore; resealed modified system images are accepted and run; a system image that never boots is
recovered with HOME + power, which enters BOOT MODE and installs an official file from the card;
a Lofi-12 XT system image rewrapped for the SmplTrek installs, boots and restores. Nothing here writes the
bootloader, and no recovery path is known if the bootloader itself is damaged. Other production runs may
ship a different bootloader. [SAFETY.md](SAFETY.md) gives the evidence and the limits of each claim.

## External references

- [TI TMS320C6748 technical reference manual (SPRUH79)](https://www.ti.com/lit/pdf/spruh79) and
  [datasheet](https://www.ti.com/product/TMS320C6748): register maps for every peripheral named here.
- [TI C6748 StarterWare](https://www.ti.com/tool/STARTERWARE-DSPARM): driver sources the firmware's HAL is
  built from; functions were matched against it by body.
- [TI SYS/BIOS](https://www.ti.com/tool/SYSBIOS) and the C6000 code generation tools: the runtime and the
  RTS library the analysis matches against.
- [GNU binutils](https://www.gnu.org/software/binutils/) `tic6x-elf`: patched here for compact-instruction
  register decoding ([tools/toolchain/patches/](tools/toolchain/patches)).
- [FatFs](http://elm-chan.org/fsw/ff/): the filesystem the firmware links (identified by source matching).
- [FM-1-RE](https://github.com/AL-255/FM-1-RE): the layout this repository follows.

## Use at your own risk

This is independent research, not affiliated with or endorsed by Sonicware. The tools here write new files only;
putting one on a unit is your decision. Installing modified or cross-product firmware can make a unit misbehave or
need recovery, is not supported by Sonicware, and may void your warranty. What is and is not known about recovery is
in [SAFETY.md](SAFETY.md); the code comes with no warranty ([LICENSE](LICENSE)).

This repository contains none of the products' built-in content (samples, sound patches, presets or patterns).
Sonicware's manuals forbid redistributing that content, so get the update files from Sonicware yourself
([firmware/README.md](firmware/README.md)).

## License

MIT ([LICENSE](LICENSE)), except FatFs under `emulator/third_party/fatfs/` (its own licence) and the GNU binutils
patch under `tools/toolchain/patches/` (GPL-3.0-or-later, like binutils).
