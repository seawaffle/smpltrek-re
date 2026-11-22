# SmplTrek emulator

An emulator for the SmplTrek's TI C6748 DSP and its board, built to run the unmodified stock
firmware. The [C++ C674x core](core/README.md) executes original DSP binaries, instruction by
instruction and cycle by cycle, with models of the board's peripherals: timers and interrupts,
EDMA, SPI1 and the OLED panel, I2C0 and the TLV320AIC3106 codec, McASP0 audio, MMC/SD with a FAT
card image, the SPI NOR flash, UART1 to the panel MCU, UART0 with a MIDI IN sender and timestamped
MIDI OUT, USB0 as a device with a scripted full-speed host, and the GPIO key matrix, encoders and SYNC pins. It runs SmplTrek, Lofi-12 XT and CyDrums updates (one board, the same panel) and a linked
DSP program (ELF) you supply. It starts where the bootloader hands over to the SYSTEM image; the
bootloader itself is not run. The emulator builds no firmware of its own, and no Sonicware code is
in this repository: download the updates into `firmware/` (layout in `firmware/README.md`).

Requirements: Linux, Python 3.10 or newer and a C++20 host compiler (`g++` or `clang++` on the
path, or `CXX`). Decoding new code pages needs the patched `tic6x-elf-objdump` under
`tools/tic6x/bin` (build it with `tools/toolchain/build_tic6x_*.sh`). Commands below run from the
repository root; generated files (core build, caches, cards, reports) go to the ignored
`work/emulator/`, and most scripts take `--work` to use another folder.

## Run the stock firmware

Interactive panel, at real-time pace:

```sh
python3 -B emulator/stock_ui.py                       # SmplTrek 3.2.174 from firmware/
python3 -B emulator/stock_ui.py --card card.img --flash flash.img
python3 -B emulator/stock_ui.py --profile lofi12 --firmware firmware/lofi12/<update>.zip
```

Open **http://127.0.0.1:8766**: live display, every button, the five encoders, the pads, the panel
LEDs and 48 kHz audio (press **Enable audio**). Start-up to the sequencer takes about four guest
seconds. The panel compiles hot guest code to host code in the background, and with it a generated
song plays at about 1.2× real time on the development host; heavier projects run late, never
wrong. Details: [Stock firmware panel](#stock-firmware-panel).

Headless, with a JSON report (hashes, checkpoints, CPU state, recent MMIO), the display as
`frame.png` and the audio as `audio.wav`:

```sh
python3 -B emulator/stock.py --cycles 250000000 --until-frame        # stop at the first frame
python3 -B emulator/stock.py --cycles 1800000000 --reserved-low-writes
```

`stock.py` is strict by default: anything not modelled, and any access the unit was not measured
for, stops with a diagnostic. The stock SmplTrek start-up stops that way at cycle 1,333,972,500, at
a null-pointer byte store to `0x00000008` in USB audio class setup
([USB investigation](usb-investigation.md)); `--reserved-low-writes` discards such stores, as the
unit does (measured in device session M2, `experiments/sessions/M2-bench.md`), and start-up then
reaches the sequencer by cycle 1.5 billion. `--reserved-low-reads` applies the measured rule for
reads of reserved low memory (needed by CyDrums from its start, and by Lofi-12 XT with a card). The
panel enables both unless `--strict` is given. `--card` and `--flash` take private copies of an SD
card image and a 32 MiB flash image; `card_image.py`, `flash_image.py` and `project_card.py` build
them. Details: [Stock runs in detail](#stock-runs-in-detail).

## Run your own program

```sh
python3 -B emulator/custom.py --elf path/to/program.elf
python3 -B emulator/custom.py --elf program.elf --cycles 372000000 --break main --watch status_word \
    --card work/emulator/cards/card.img --export-card
```

The input is a linked little-endian ELF32 C6000 executable whose sections lie in the RAM the stock
bootloader hands over (DDR2 at `0xC0000000`, L2, L1P/L1D or shared RAM). Execution starts at the ELF
entry with no stack set up. The board, the strict stops and the report are the stock runner's.
Details, including link constraints: [Custom DSP programs](#custom-dsp-programs). A complete update
in the stock container format (for example one resealed with `tools/sonicware_integrity.py`) runs
through `stock.py --firmware` or `stock_ui.py --firmware` instead.

## What is and isn't modelled

Modelled, from TI's manuals ([SPRUFE8B](https://www.ti.com/lit/ug/sprufe8b/sprufe8b.pdf) for the
CPU, [SPRUH79C](https://www.ti.com/lit/ug/spruh79c/spruh79c.pdf) for the peripherals) and checked
against the stock firmware's behaviour:

- **CPU:** the whole C674x instruction set (fixed and floating point, compact packets, SPLOOP
  hardware loops with reload and interrupts, `IDLE`, exceptions), pipeline delays, branch delay
  slots and interrupts inside multicycle NOPs. A second, independent simulator
  (`analysis/c6sim.py`) is the reference; compiled C from TI's cl6x and from GCC is run in both and
  compared with the host ([CPU model](#cpu-model-loops-compiled-c-and-the-instruction-set)).
- **Board:** interrupt event routing, PSC, pin mux, GPIO, the four timers, EDMA3, SPI0 (NOR) and
  SPI1 (OLED), I2C0 and the codec's control registers, McASP0 and its DMA ring, MMCSD0 with PIO and
  EDMA (SD 2.0 SDSC, single and multiblock), UART0 (MIDI DIN) and UART1, the SYNC IN and SYNC OUT
  pins ([MIDI and SYNC](#midi-and-sync-2026-11-20)), USB0 as a full-speed device with a scripted
  host ([USB device](#usb-device-and-scripted-host-2026-11-20)), the DDR controller's status registers, and the cache control registers
  (memory is coherent). One guest clock drives everything: 372 MHz CPU, 24 MHz timer 0/1 input.
- **Unit measurements** from device sessions M1 to M3 (`experiments/README.md`): misaligned
  accesses, the USB reserved words, EMIFA stores, the cache hand-off state, reserved low-memory
  reads and stores, the reciprocal-estimate tables, and the panel MCU's report stream (order and
  rate) ([Bench results applied](#bench-results-applied)).

Not modelled, or modelled from assumption:

- the bootloader and the AIS boot path (the run starts from a documented hand-off state);
- analogue audio (codec analogue stages, gain knobs), physical channel routing beyond the
  headphones check in M1 (even words = left, HW-61), and key bounce, ghosting and settling;
- the panel MCU beyond its analogue report stream: no `A1` version reply, no jitter or bursts, an
  untouched pad reads 0 (0 to 4 on the unit);
- SD erase, high speed, SDIO and hot-plug; NOR program/erase timing and the part number; USB
  DMA traffic, high speed and host mode; DMA accesses to reserved memory; cache timing;
- the places where the model continues with an unmeasured value, listed in
  [What the model assumes without stopping](#what-the-model-assumes-without-stopping).

An emulator result never upgrades a claim to `observed-device` in `claims.json`; electrical
behaviour, exact panel timing, physical routing and performance need the unit.

## Test

```sh
python3 -B emulator/tests/verify.py                # every check, in parallel (about 8 minutes on 16 cores)
python3 -B emulator/tests/verify.py --tier fast    # while editing (about 2 minutes)
python3 -B -m unittest discover -s emulator/tests -p "test_*.py"
```

The unit tests use only source-built and synthetic inputs; those that assemble or compile guest
code need the DSP toolchain under `tools/tic6x/bin` and skip without it. The stock checks
(`tests/stock_*.py --conditional`) need the updates under `firmware/` and skip without them; each
compares display, audio, card traffic and faults with a saved result under `tests/fixtures/`.
Details: [Validation](#validation).

The rest of this page is the detailed record, with the date each result was obtained. Throughput
figures from before the fast-forward work of 2026-11-15 are kept in
[the performance notes](performance-investigation.md#throughput-history-2026-11-14-to-2026-11-15).

## Stock runs in detail

`stock.py` verifies the container CRCs, loads the original SYSTEM sections, and executes the original
entry without guest function hooks. Unsupported behaviour stops with a diagnostic. The report,
`work/emulator/stock/result.json` (or `--output`), holds hashes, reached checkpoints, CPU state and
recent MMIO; `frame.bin` and `frame.png` are written beside it, and `--until-frame` stops after the
first complete stock frame (the SmplTrek splash, visually inspected). Budget exhaustion alone is not
a boot result. The runner accepts up to ten billion cycles and records throughput over each
execution window. It holds the power key for 600 guest milliseconds to exercise the stock power-on
sequence; `--power-held-ms 0` starts with the key released.

**Start-up on the empty-card, erased-flash profile (SmplTrek 3.2.174).** MMC/SD controller
initialisation completes with an empty socket, settings are read from SPI NOR through EDMA, the
codec is configured through its real I2C ISR, and the audio-render task runs through clocked
McASP/EDMA. A three-second start-up delay follows (`tests/stock_smoke.py --startup-delay` checks it
completes with audio still active). Then, at cycle 1,333,972,500, USB audio class setup writes the
vendor ID through a null descriptor pointer: a byte store to `0x00000008`, PC `0xc162a4f0`. It
loads the pointer from `0xc16ecfd4 + 48`, which is zero in the independently decoded copy-table
data and stays zero through all 147 guest constructors. Composite setup updates its own valid
descriptor first; the audio class's descriptor and configuration pointers are both null, and the
same initialised fields and store pattern occur in 1.0.65, 3.0.148 and 3.2.174: a longstanding
composite-class adaptation fault in the firmware. TI's
[C6748 datasheet, section 3.4](https://www.ti.com/lit/ds/symlink/tms320c6748.pdf) calls reserved
accesses potentially undefined, so the model does not guess: strict mode stops there, and
`python3 -B emulator/usb_probe.py` reproduces the fault and its pointer trace
([USB investigation](usb-investigation.md)). Neither a guest patch nor RAM at address 0 has been
added.

`--reserved-low-writes` discards CPU stores to reserved low memory, without mapping RAM there, as
the unit does (M2, rows W1-W3: such stores store nothing and raise nothing). The six stores of USB
setup are logged. The two USB status reads that follow (`0x01e0080c`, `0x01e0084c`) return 0 and the
stores of 0 to `0x01e00808` and `0x01e00848` are ignored, as measured in session M1 (row I5); this is
built in. `tests/stock_smoke.py --usb-reset` checks USB0's reset and PHY clock-good polling.

```sh
python3 -B emulator/tests/stock_boot.py --conditional
```

With the low-store option the unmodified start-up routine returns at cycle 1,372,170,255 and the
sequencer screen is visible by cycle 1.5 billion. The check then verifies USB return, the codec
unmute, PLAY/STOP scanning, FUNC+HOME, VALUE encoder navigation, changing METRONOME through the guest
UI and returning home. It sends synthetic MCU-info and pad press/release bytes through UART1 and
checks the values the original parser stores; these are test inputs, not an emulated MCU reply.
Reports, raw frames and PNGs are under `work/emulator/stock-boot/`. Reports mark such runs
`conditional_execution: true`, with no guest hooks. Digital output is silent in this empty-project
profile. See [the boot investigation](boot-investigation.md).

**Other images (2026-11-16, start-up only).** SmplTrek 1.1.72 through 3.2.174 reach the same
sequencer screen with the low-store option; 1.0.65 stops at a low read after its splash screen.
`stock.py --profile lofi12 --firmware firmware/lofi12/<update>.zip` runs a CRC-checked Lofi-12 XT
image on the same board model: all three releases draw their splash screen and, with no card, reach
"INSERT CARD!". With a card they stop at a low read (`0x10`) unless `--reserved-low-reads` is given.

`--profile cydrums` (2026-11-18) accepts the two CyDrums updates, 1.1.84 and 2.0.97 beta: their
checksum seeds were confirmed when the second release recovered the same two as the first
(`tools/sonicware_integrity.py`). The profile is the checksum profile and nothing else: CyDrums runs
on the same board model. Both releases stop 0.6 s after start at a read of address 0, with or
without a card, so `stock.py` needs `--reserved-low-reads` for them, as `stock_ui.py` has by
default. With it both reach their main screen with a card built from the 1.1.84 card contents
(`stock_ui.py --profile cydrums --labels drum --firmware firmware/cydrums/<update>.zip --card <image>`);
whether 2.0 expects other card contents was not looked into. No CyDrums unit has been compared with
any of this.

**Flash.** Stock mode defaults to two erased 16 MiB SPI NOR chips. Supply a local 32 MiB image with
`--flash /path/to/flash.img` (CS0 then CS1); the runner copies it into private memory. Guest writes
affect only that copy. `--export-flash` saves `flash.img` beside the report. The report records the
input hash and per-chip transactions, bytes read, completed programs/erases and WIP/WEL status.
The physical flash part number and real program/erase timing are not modelled.

**Card.** `stock.py --card /path/to/card.img` inserts a private SD 2.0 SDSC image (a power-of-two size
from 2 MiB to 1 GiB). `card_image.py --size-mb 128 --long-names --tree FOLDER` builds one from a
folder; `--long-names` writes VFAT long names (ASCII only), which the default 8.3 builder refuses.
`--export-card` saves the private state beside the report. The controller supports identification,
synthetic CID/CSD, byte-addressed single/multiblock reads/writes and a clocked 64-byte FIFO with PIO
or EDMA service; MMCST0 clears every read status flag on read, as TI specifies. EDMA channels 16/17
handle reads/writes, including short final transfers; CMD6 negotiation advertises default speed.
Erase, high speed, SDIO and hot-plug are not modelled. The empty socket is the default.

**Audio output.** Both `stock.py` and `custom.py` export `audio.wav` alongside `audio.pcm32`. The WAV
holds the captured signed 32-bit words at 48 kHz; its two channels are McASP slots 0 and 1.
Incomplete stereo frames at the rolling capture's edges are trimmed and recorded in the report. No
gain or analogue codec processing is applied. The capture window holds up to 65,536 words (about
0.683 seconds), not the whole run. `audio.pcm32` is little-endian, alternating raw slots 0/1; the
report records the first slot, cycles and counts so truncated captures can be aligned.

**Audio input.** `stock.py --cycles 250000000 --audio-input /path/to/adc.pcm32 --loop-audio-input`
supplies digital ADC data: raw little-endian 32-bit slot pairs at 48 kHz, up to 64 MiB, copied
privately before the first RX slot. Words are signed sample bits as delivered by the codec, with no
host resampling, gain or analogue filtering. EOF supplies zeros unless looping is selected.
Consumption follows modelled receive clocks, beginning with slot 0. Reports record the source hash,
loop/position, consumed words, padding and nonzero receive counts. `performance.py` accepts the
same options. `tests/stock_smoke.py --audio-input` creates a two-slot +0.125/-0.25 fixture and
checks its passage through original RX DMA and stock input processing: the guest first programs a
short 255-word RX descriptor, then repeating 256-word ping/pong descriptors, so the short one
changes the stream's pair phase; both settled buffers and both floating-point planes keep the
distinct signs and the 2:1 level ratio. Stock's monitor output is silent in that start-up window.

## Stock checks

`python3 -B emulator/tests/stock_midi.py --conditional` checks the MIDI and SYNC models against
3.2.174; what it drives and what it found are under [MIDI and SYNC](#midi-and-sync-2026-11-20).
`python3 -B emulator/tests/stock_usb.py --conditional` plugs a host into 3.2.174, enumerates it and
exchanges USB MIDI ([USB device](#usb-device-and-scripted-host-2026-11-20)).
`python3 -B emulator/tests/stock_usb_audio.py --conditional` streams USB audio both ways with 3.2.174
(same section, "Isochronous streams").

`python3 -B emulator/tests/stock_survey.py --conditional` repeats the start-up survey above as a
regression check: all thirteen SmplTrek, Lofi-12 XT and CyDrums updates, each with no card and with a blank
card, booted and given MIXER and HOME. The display after each stage, the audio output, the card traffic and any
fault must match `tests/fixtures/stock_survey.json`; `--record` rewrites that file. Faults that are
expected (1.0.65, Lofi-12 XT with a card, and CyDrums always) are recorded there with their
instruction and cycle, so a change in either direction shows up. All nine are reads of reserved low
memory, so each is run again with `--reserved-low-reads` as a separate saved result (since
2026-11-17): with that assumption 1.0.65 reaches its sequencer, the three Lofi-12 XT releases their
main screen, and the two CyDrums releases run through all three stages with no fault.
`--blocks` repeats the 35 runs with compiled blocks against the same interpreter results (about ten
minutes, most of it host compilation).

`python3 -B emulator/tests/stock_fuzz.py --conditional --seeds 6 --seconds 20` is a soak with
seeded random panel input (keys, FUNC chords, knob detents, pad hits) on 3.2.174 with a blank card.
Each seed runs on the interpreter and with compiled blocks; the two must end in the same CPU state,
display, audio, card contents and device trace, and a guest fault is reported with the inputs that
preceded it.
`--samples` starts the soak from a card with four WAV files in the sample pool.
`--project FUNK` starts it from a generated project card with the factory-like flash (see below), so
the random input also reaches playback of a real song, saving and loading.
`--reserved-low-reads` applies the measured low-read rule ([Bench results applied](#bench-results-applied)),
so that a seed goes on past the strict faults on such reads; the default stays strict.

A longer soak on 2026-11-18, 60 guest seconds a seed with the panel stream unless noted, seeds
100 upward, after the change to interrupts inside multicycle NOPs:

| Starting card | Seeds | Inputs applied | Interpreter and blocks agree | Guest faults |
| --- | --- | --- | --- | --- |
| blank, strict | 12 | 10,953 | 12 | 1 |
| four samples, strict | 6 | 5,349 | 6 | 1 |
| four samples, low reads | 16 | 15,224 | 16 | 0 |
| FUNK project, low reads | 12 | 11,386 | 12 | 0 |
| FUNK project, low reads, no stream | 6 | 6,626 | 6 | 0 |

Both faults are the known strict one, a read of address 8 at `0xc163ac44`. No audio underrun in
any seed. A seed of this length holds 0.9 GB to 1.9 GB, and twelve at once ran a 16 GB host out
of memory, the more so because each machine with compiled blocks started up to fifteen host
compilers. Since then the default number of machines is limited by the memory available when
the run starts, and programs that run several machines (`stock_fuzz.py`, `stock_survey.py`)
divide the CPUs among their host compilers. Eight project seeds of 60 seconds with those
defaults finished with 2.5 GB to spare at the lowest point, before the allowance per machine
was raised once more.

**Factory content and generated projects (2026-11-17).** `flash_image.py` builds a factory-like
flash image from the 2.0.129 update's preset content, so the stock firmware has its kits, sounds and
patterns instead of erased flash. `project_card.py --genre FUNK --seed 1` then builds a card with a
playable project:

- the stock firmware itself, run with that flash and a blank 256 MiB card, is driven through SYSTEM
  MENU > CARD > DUPLICATE PRESETS > DRUM KIT and writes the fifteen factory kits and their drum
  sounds (about 39 MB, cached under the work folder);
- `projects/make_config.mjs` writes a project `Config` from a seeded generated song, using the npm
  packages `smpltrek-builder` and `drum-pattern-engine` (MIT, by Alexander Schornberg), pinned in
  `projects/package-lock.json` and installed with `npm ci` into the work folder, not the repository.

It prints the `stock_ui.py --card ... --flash ...` command to open the result in the panel.
`python3 -B emulator/tests/stock_song.py --conditional` loads that project, presses PLAY and
checks ten guest seconds of playback against `tests/fixtures/stock_song.json` (display, audio, card
traffic); `--blocks` repeats it with compiled blocks. On this host the song plays at 0.6× real time
on the interpreter and 2.1× with compiled blocks, which the panel uses by default.

**A project with every track type (2026-11-16).**
`python3 -B emulator/tests/stock_multitrack.py --conditional` has the stock firmware build a
project through the emulated panel on a card that holds only the factory kits: the track-type dialog
makes two DRUM tracks (two kits, each with one of the kit's patterns), an INST and a MIDI track with
step-recorded notes, and an empty LOOP and SHOT track; PROJECT MENU > SAVE writes it. A second
machine then starts from the saved card, reloads the project and plays six guest seconds. The result
is compared with `tests/fixtures/stock_multitrack.json`; `--blocks` repeats all of it with compiled
blocks. Playback runs at 0.5× real time on the interpreter and 1.7× with compiled blocks on this host.

Only the DRUM tracks sound. Under the strict low-memory policy two firmware paths stop, and both
are firmware logic, not device state:

- **Assigning a sample (LOOP and SHOT tracks).** OK on a file name in SAMPLE POOL reads through a
  null object (`0xc16166a0`, address `0xc`), with or without a preview running. `0xc1640b0c` asks
  whether a stream is playing (`0xc1625bf8`, state word at B14+884); when none is, it calls
  `0xc16262d0` with no stream, which passes the empty current-stream pointer (B14+880) plus eight to
  the getter. The check pins this stop.
- **Creating an INST track when the preset instruments are on the card** (DUPLICATE PRESETS > INST).
  The WAV chunk code near `0xc163a92c` reaches its `labl` case (the preset WAVs carry a
  `LIST`/`adtl`/`labl` chunk, "Marker 1"), sets A14 to zero (`mvk 0,a14` at `0xc163abec`) and copies
  14 bytes from that address (first read at `0xc163ac44`, address `0x8`). Where the copy ends up
  was not traced: an earlier note here said it is written into a WAV on the card, but saving the
  project writes only its `Config`, which names the preset WAV by path (checked 2026-11-17).
  Without the preset instruments the INST track is created with no instrument and stays silent.
  `python3 -B emulator/tests/stock_inst.py --conditional` pins this stop, then repeats the
  presses with `--reserved-low-reads`: the track gets A.Guitar.wav, two step-recorded notes play
  audibly, and the only low reads are the label copy's four, five times over
  (`tests/fixtures/stock_inst.json`; `--blocks` for compiled blocks).

Both stops are strict-policy results. What the firmware reads there on the unit was not measured
for these two code paths (the stock parts of sessions M1 to M3 were not run); the low-read option
applies the bench's general rule to them.

**Card-reader mode and the USB DMA set-up registers (2026-11-16).** SYSTEM MENU > CARD > CARD READER
programs the CPPI 4.1 DMA before any transfer: the endpoint mode register (`0x01E00010`), a generic
RNDIS size (`0x50`), transmit and receive channel configuration (`0x1800`-`0x187F`), the scheduler
control and table (`0x2000`, `0x2800`-`0x28FC`), the queue manager's linking RAM (`0x4080`-`0x4088`)
and a descriptor memory region (`0x5000`, `0x5004`). `core/usb.cpp` now holds these registers with
the field masks of SPRUH79C section 33.4; registers whose fields are write-only accept writes and
fault on reads, a channel teardown faults, and queues, revision and pending registers stay
unimplemented. DMA traffic is not modelled (also not with the host of 2026-11-20), so nothing is transferred that way. `tests/test_usb.py` covers this.

The stock firmware does not reach that set-up under the repository's policy: it first writes zero
to the reserved offset `0x01E00808` (PC `0xc15e2264`), which still faults. In a study copy of the
core that discards that write and its twin at `0x848`, card-reader mode shows its page and CLR
leaves it again with these registers and no further gap.

`python3 -B emulator/tests/stock_project.py --conditional` verifies a complete stock project
persistence path on a private FAT card. Original UI input creates Project002, changes its tempo
from 120 to 121 BPM and confirms SAVE. An independent read-only FAT12/16 inspector checks the
guest's 5,924-byte CONFIG and project list. A fresh stock boot loads 121 BPM from the exported
card, with byte-identical CONFIG data and no changes to either input image. Reports and stage
frames are under `work/emulator/stock-project/`. This uses the low-store option;
no guest filesystem, allocation or UI function is hooked. See
[the storage regression](storage-investigation.md).

`python3 -B emulator/tests/stock_audio.py --conditional` verifies nonzero stock sample-pool
playback. It builds a private card with a two-second stereo PCM16 WAV, navigates the original UI
to its preview column, and checks the exact 750/1500 Hz output samples, stop/restart, a quieter
second half and the return to the first half on looping. Original filesystem, WAV reader, mixer,
EDMA and McASP code run without hooks. Reports, frames, raw captures and playable WAV snapshots
are under `work/emulator/stock-audio/`. It is a digital result: the analogue stages are not
modelled. Complete slot-0/1 frames show a one-frame source-channel offset, an open I2S/DMA phase
question. OK on a file name (the filename action) faults on a null-object read, described above
under the six-track project; the documented preview-column action works. See
[the audio investigation](audio-investigation.md).

`python3 -B emulator/tests/stock_smoke.py --sd-card` builds an empty FAT card and verifies that
the original stock driver/filesystem creates `SMPLTREK/PROJECT` and `SMPLTREK/POOL` through EDMA.
It stops at the minimum startup-delay checkpoint and exports the private image for inspection. With the generated
HELLO card, stock reads 36,936 bytes and writes 30,208 bytes by the time start-up reaches the USB
setup described above; the input image stays unchanged.

For a shorter scheduler/key-scan check, run `python3 -B emulator/tests/stock_smoke.py`; add
`--first-frame` to validate display transfer too.

`python3 -B emulator/tests/stock_smoke.py --storage` also checks 384 parameter bytes from NOR
chip 0, both 4096-byte settings sectors from chip 1 and the guest settings buffer, stopping before
the first I2C0 access. This proves the actual read path on erased backing, not a complete boot.

`python3 -B emulator/tests/stock_smoke.py --codec` verifies the 40 codec writes, 80 acknowledged
I2C data bytes, PLL/interface/routing registers and both ADC filter coefficient sets, stopping before
McASP0. The report includes the bounded codec write trace and register state.

`python3 -B emulator/tests/stock_smoke.py --audio` verifies stock audio-render task entry and
multiple McASP/EDMA blocks at a modelled 48 kHz with digital-silence input and zero under/overruns.

## CPU model: loops, compiled C and the instruction set

**Hardware loops: the SPLOOPW exit rule, reload, and interrupts (2026-11-16).** Checking the
remaining loop-buffer gaps against TI's manual and compiler found an error in a case that was
thought finished. An SPLOOPW ended on the current value of its condition register; SPRUFE8B 7.10.2
says the condition is read 3 cycles before the stage boundary, and TI's compiler depends on it. The
C loop `do { sum += *x++ * *y++; n -= m; } while (n >= 0);`, compiled by cl6x 8.5 with ii 3, returned
wrong sums in the reference simulator (37 of 1,360 compiled-C runs at `-O2`); with the rule
corrected in `analysis/c6sim.py`, in the core's interpreter and in its compiled loop code, all
six optimisation levels agree with the host. A static scan suggests about 47 of the 1,206 SPLOOPW
loops in SmplTrek 3.2.174 exit at a different boundary under the corrected rule. Whether any of
them changed a result the stock checks observe is in the list below.

The same work added what was refused before: a body ending in SPKERNELR, a reload with RILC = 0
(the invocation is skipped), and interrupts during a loop, which now drain the loop and pipe it up
again on return instead of waiting for it to finish (SPRUFE8B 7.13; details and remaining
differences in [the core documentation](core/README.md)). `tests/test_loops.py` runs each case in
the core and in the reference simulator, on assembled fixtures that include two loops copied from
cl6x output, and requests an interrupt at every cycle of ten loop cases in turn: the result must be
the uninterrupted one and cycle counts, registers and return address must match the reference. The
core and the reference were written from the same reading of the manual, so their agreement shows
consistent implementation, not a correct reading; the independent evidence is the compiled C (for
the exit rule) and the requirement that an interrupt changes no result.

What changed in the stock checks, each compared with the result saved before the change:

- The stock firmware takes interrupts inside loops: 546 of 19,983 over boot plus five seconds of the
  six-track project, with no fault.
- `stock_boot`, `stock_forward`, `stock_project`, `stock_audio` and both `stock_fuzz` runs pass
  unchanged. In `stock_survey`, 17 of 22 runs are identical; the other five stop at the same fault,
  PC and display, 67 to 1,334 cycles later (one of them has sent one more audio word by then).
- `stock_song`: audio and card traffic are bit-identical. The frames at 8 and 10 seconds differ in
  the output level meter only: sampled every 10 ms, the meter runs one step apart for about 600 ms
  from 7.7 seconds, and counter, scene and clips are the same. Either change alone leaves all
  frames identical, so this is the meter being read at a slightly different instant.
- `stock_multitrack`: build, saved project, frames and audio are identical; the pinned null read
  comes 12 cycles later. The INST-track null read (`0xc163ac44`) was retested and is unchanged.

The three saved results were recorded again on that basis. No observed display, audio or card
result changed because of the SPLOOPW rule, so none of the firmware stops listed above was an
artifact of it.

**TI-compiled C in the core (2026-11-16).** `python3 -B emulator/tests/compiled_c.py` builds the
functions of `analysis/c6sim_diff/tests.c` (58 then, 78 now) with TI's cl6x at six optimisation levels, runs
them in the core, once interpreted and once with compiled blocks, and compares every result with
the same C built by gcc for the host; `analysis/c6sim_diff.py` does the same for the reference
simulator. Before this the core met only two compiler-generated loops, both transcribed by hand.
The source gained 25 loop functions: trip counts from zero, 8, 16 and 32-bit elements, 64-bit and
saturating sums, nested loops, loops that end on data, and single-precision loops. At `-O3` the
compiler turns them into 13 SPLOOP, 31 SPLOOPD and 3 SPLOOPW loops.

What it found: no wrong result. The compiler used five instructions the core refused (`MPYLH`,
`MPYLHU`, `DOTP2`, `MPY2`, `DPACK2`); none occurs in the SmplTrek 3.2.174 or Lofi-12 XT 1.5.205
image. They are now implemented in the core and the reference, with hand-worked values in
`tests/test_core.py`. Putting the old SPLOOPW exit rule back makes this check fail, so it would
have caught that error. Limits: the compiler emitted no loop-buffer reload for any C or option
tried, so reload still rests on the hand-derived CyDrums case and the assembled fixtures; only
results are compared, not cycle counts; and interrupts are not part of it.

**GCC-compiled C in the core (2026-11-17).** The same check now also builds the functions with GCC
(`tools/tic6x`, GCC 13.3 with libgcc) at `-O0`, `-O1`, `-O2`, `-O3` and `-Os`. Until now every
compiled-code comparison used TI's compiler, and a fault found the same day had sat exactly where
only GCC's output goes: its integer division helpers fill branch delay slots with a skipped
`ADDKPC`, whose wait the core dropped (see `core/README.md`). The source gained four functions
that take a quotient or a remainder alone, signed and unsigned, because the existing division
function reaches GCC's combined divide-and-remainder helpers, which do not use that pattern;
with them, putting the fault back makes the GCC part fail.

What it found: no wrong result in the core or the reference simulator at any level. One thing a
firmware author should know: **with GCC's default options, float and double division is not
correctly rounded.** GCC divides by a reciprocal estimate (`RCPSP`, `RCPDP`) refined twice, and a
result can be one unit in the last place off; TI's compiler calls an exact routine.
`-fno-reciprocal-math` makes GCC call libgcc's exact routine instead. The check builds each level
both ways: with that option every result must equal the host's, and with the defaults a result
may differ from the host only if the exact build agreed and the reference simulator returns the
core's value (16 of 2,480 results at `-O2` with 40 inputs). Those results rest on the estimate
itself. Since the 2026-11-18 bench session (M2) both simulators round the exact value to nearest at
eight mantissa bits, as the unit does: `RCPSP`, `RSQRSP`, `RCPDP` and `RSQRDP` there gave exactly
those results for the 256 mantissas 1 + k/256 at exponents 0, +1 and -3, and for the special inputs
(`tests/test_core.py` holds the unit's twelve checksums). Before, both cut the value off, which was
wrong in 116 to 132 of every 256. The 2026-11-19 session (M3, image 0.3.4) measured inputs with
mantissa bits below the eighth: the unit gave the same tables again, so only the top eight mantissa
bits of the input count, as in a table, and both simulators now drop the rest first. Before that
they used the whole input, which was wrong in 78 to 212 of every 256 such inputs.

**Instructions GCC emits that were missing (2026-11-17).** Running every instruction form found in
real code alone in both simulators (a scratch audit: 887 forms, 21,000 runs with random registers,
skipped and executed) showed no supported instruction misbehaving, but also that GCC's own machine
description can emit about 30 instructions that the core and the reference simulator refused,
because the stock firmware and TI's compiler output never needed them. Plain C is enough:
`(a >> 16) * (b >> 16)` becomes `MPYH`. The stop was a clean "unsupported instruction", never a
wrong result. Now implemented in both, 39 instructions in all:

- the 16 x 16 multiplies of chosen halves (`MPYH`, `MPYHU`, `MPYHUS`, `MPYHSU`, `MPYHL`, `MPYHLU`,
  `MPYHULS`, `MPYHSLU`, `MPYLUHS`, `MPYLSHU`);
- saturating arithmetic (`SADD`, `SSUB`, 32 and 40-bit; `SMPY`, `SMPYH`, `SMPYHL`, `SMPYLH`,
  `SMPY2`);
- packed 16-bit and 8-bit arithmetic (`ADD2`, `SUB2`, `ADD4`, `SUB4`, `SADD2`, `SSUB2`, `SADDU4`,
  `SADDUS2`, `SADDSU2`, `ABS2`, `AVG2`, `AVGU4`, `MAX2`, `MIN2`, `MPYU4`, `MPYSU4`, `MPYUS4`,
  `DPACKX2`);
- `BITR`, `SWAP4`, `SHLMB`, `SHRMB`.

With them comes the saturation flag, which was not modelled at all: `CSR.SAT` and the unit's bit
in `SSR` are set one cycle after a clipped result is written, also for the already supported
`SAT` and `SSHL`. `SHL` of a 32-bit source into a register pair now keeps 40 bits; it kept 32.
In the reference simulator, `RCPSP`, `RSQRSP` and `SPDP` of a NaN now give the manual's NaN_out,
as the core did, and `MAXU4`, `MINU4` and `NOT` exist.

How they are checked: the manual's worked examples for each instruction that has one, and values
worked from its definitions for the six that have none (`tests/test_core.py`); the core against
the reference simulator on random operands (the audit); and C in which each DSP compiler's
intrinsic executes the instruction while the host computes the manual's definition in plain C
(`tests.c`, six more functions). cl6x's output contains 32 of them and GCC's 19. Neither compiler
emitted `MPYHSU`, `MPYHLU`, `SMPYLH`, `SADDSU2`, `MPYUS4` or `DPACKX2`, which rest on the first
two checks.

**A GCC fault found on the way, for firmware authors:** GCC 13.3's `_smpyh`, `_smpyhl` and
`_smpylh` intrinsics (`c6x_intrinsics.h`) all emit `SMPY`, the product of the two low halves,
whatever halves they name. It is visible in the disassembly and has nothing to do with the
emulator; `_smpy` itself is right. The test source does not use those three with GCC.

**The rest of the instruction set (2026-11-17).** The instructions of the manual that were still
refused are now in both simulators, 51 more: the packed comparisons and masks (`CMPEQ2`, `CMPEQ4`,
`CMPGT2`, `CMPGTU4`, `XPND2`, `XPND4`, `BITC4`), packing (`PACKH2`, `PACKH4`, `UNPKHU4`,
`UNPKLU4`, `SPACK2`, `SPACKU4`, `RPACK2`), `SHRU2`, `SUBABS4`, `ADDSUB2`, `SADDSUB`, `SADDSUB2`,
the dot products (`DOTPN2`, `DOTPNRSU2`, `DOTPRSU2`, `DOTPSU4`, `DOTPU4`, `DDOTP4`, `DDOTPH2`,
`DDOTPH2R`, `DDOTPL2`, `DDOTPL2R`), the complex multiplies (`CMPY`, `CMPYR`, `CMPYR1`), the
rounded and wide multiplies (`MPY2IR`, `MPYHIR`, `MPYLIR`, `SMPY32`, `MPYI`, `MPYID`), `SSHVL`,
`SSHVR`, `DEAL`, `SHFL`, `SHFL3`, the Galois field multiplies (`GMPY`, `GMPY4`, `XORMPY`),
`RSQRDP`, and the register forms of `SET` and `CLR`. No compiler here has emitted any of them;
hand-written assembly or a library could.

They are checked against the manual's worked examples, 85 of them (`tests/test_core.py`), and the
core against the reference simulator on random operands with `CSR.SAT` and `SSR` read back
afterwards (a scratch run: all 89 instructions added this week, 60 runs each, no difference).
Three things rest on a reading rather than on an example:

- Two of the manual's examples disagree with its own stated operation and are taken as misprints:
  `RPACK2` (it prints FDBAh where the operation gives FDB9h) and one `SSHVL` result.
- `GMPY4` is exemplified only for the field the CPU has after reset (8 bits, polynomial 1Dh);
  other field sizes in `GFPGFR` follow the usual shift-and-reduce and are unverified.
- `RSQRDP`, like the other reciprocal estimates, follows the unit's rule measured in sessions M2
  and M3 (above): the top eight mantissa bits of the input, the exact result rounded to nearest at
  eight mantissa bits.

The assembler's pseudo-operations (`CMPLT2`, `CMPLTU4`,
`SWAP2`, `DOTPUS4`, `DOTPRUS2`, `DOTPNRUS2`, `MPYIH`, `MPYIHR`, `MPYIL`, `MPYILR`) need nothing:
the disassembler prints the real instruction they stand for.

**Interrupts in compiled code (2026-11-17).** `compiled_c.py --interrupts` runs the same compiled
functions with one interrupt requested at each cycle of the call in turn (up to 600 evenly spread
cycles of a long call). The handler pushes registers on the interrupted stack, works with them and
returns, as a compiled handler does. Whatever the cycle, the result must be the uninterrupted one:
inside branch delay slots, multi-cycle instructions, SPLOOPs and the run-time helpers. At `-O2`,
cl6x and GCC, interpreted and with compiled blocks: 238,000 interrupted calls, no function
differs. After interrupts became possible inside multicycle NOPs (below) it was run at every
level of both compilers, six of cl6x and five of GCC, interpreted and with compiled blocks:
106,000 to 149,000 interrupted calls each, no function differs. `verify.py` runs it at `-O2`,
`-O3` and `-O3 -ms3` for cl6x and at `-O1`, `-O2`, `-O3` and `-Os` for GCC.

**A second GCC fault found on the way, and this one matters to any firmware with interrupts.** At
`-O2`, `-O3` and `-Os`, GCC 13.3 can release a function's stack frame before its last read of a
local array: in two of the test functions the stack pointer is raised (`addk 32,b15`) several
instructions before a load that still reads the array, now below the stack pointer. An interrupt
in that window, whose handler pushes onto the interrupted stack as handlers do, overwrites the
array and the function returns a wrong value. The emulator is right to show it; the unit would do
the same. Measured over all 78 functions (about 90,000 interrupted calls per build):

| GCC options | Functions giving a wrong result under interrupts |
| --- | --- |
| `-O1` | none |
| `-O2`, `-O3`, `-Os` | two (`t_bytes`, `t_halves`) |
| the same with `-fno-schedule-insns2` | none |
| the same with `-fno-omit-frame-pointer` or `-fno-delayed-branch` | two or three: no help |

So code that runs with interrupts enabled should be built with `-fno-schedule-insns2` (or at
`-O1`), or every interrupt handler should leave the bytes just below the interrupted stack pointer
alone. The sweep builds its GCC images with the flag. The flag's cost in speed was not measured
here; it turns off GCC's second scheduling pass, which matters on this CPU. cl6x's output showed
no such problem.

The second way was checked too. `compiled_c.py --interrupts --stack-gap 16384` builds the GCC
levels with GCC's default scheduling and has the handler move the stack pointer 16 KiB down
before its first push and back as it returns. At `-O2`, `-O3` and `-Os`, interpreted and with
compiled blocks (114,000 to 121,000 interrupted calls each), no function differs. With a gap of 8
bytes the same two functions fail again, so it is the gap that protects them. A gap protects
only frames smaller than itself, so a build that relies on it should refuse larger frames,
variable-length arrays and `alloca`. `verify.py` runs it at `-O2`.

**`IDLE` and `SWENR` (2026-11-17)** complete the instruction set in the core. `IDLE` waits until
an interrupt is entered (the handler returns to the instruction after it) or a branch already in
flight lands. `SWENR` enters at `REP`, sets `TSR.IB` and leaves `NRP` and `NTSR` alone. The
reference simulator has `IDLE`; it has no exceptions at all, so `SWENR` (like `SWE`) is checked
only by the core's own tests.

**Interrupts inside a multicycle NOP (2026-11-17).** The core used to hold an interrupt until a
`NOP n` had finished. SPRUFE8B 5.5.4 says otherwise: a multicycle NOP is interrupted like any
instruction, and once its first cycle has run the return address is the next packet's, so the
rest of the NOP is never executed. The core and the reference simulator now both do that (waits
that are the delay slots of a branch, a `BNOP` or a `CALLP` stay protected, as before). They agree
on cycle count and return address for a request at each of 40 cycles of a function holding a
load, `NOP 9` and `IDLE` (`tests/test_loops.py`), and the loop interrupt tests, which disagreed
by one or two cycles while only the core had changed, agree again. In the stock runs nothing
changed except the cycle at which five strict-mode survey runs and the strict rows of
`stock_inst` and `stock_multitrack` reach their fault: 1 to 8 cycles from where it was, at the
same instruction and address, with the same audio. Those saved cycles were recorded again. On the
unit (M2, row N1) interrupts were also taken inside the NOP, at two points; the request-to-handler
delay there varies with the loop position in a pattern the core does not reproduce (M3, N3; see
[What the model assumes without stopping](#what-the-model-assumes-without-stopping)).

**A whole program (2026-11-17).** `tests/test_app.py` builds a small synthesiser with GCC
(`tests/fixtures/app/`): Timer 0's interrupt renders one block at a time through an oscillator, a
filter, a delay and a clipper, the main program does unrelated work and then sleeps in `IDLE`.
The result is compared with a host build that renders the blocks in a loop, for 14 timer periods
at two levels, so the interrupts fall on different instructions each time, and once with compiled
blocks. GCC for this CPU ignores `__attribute__((interrupt))`, so the handler is entered through
an assembly stub that saves the registers a C function may change. What this does not cover is
the audio path itself (McASP, EDMA and the codec), which the stock checks drive.

**Audio kernels (2026-11-17).** The compiled-C comparison gained ten block-processing kernels of
the kind a synthesiser or effect is built from, with their state in structs: a biquad, a state
variable filter, a one-pole, an FIR, a wavetable oscillator with interpolation, a shaped ramp
oscillator, a modulated delay line, a soft clipper, a ramped stereo mix and noise with conversion
to 16-bit samples. Both compilers, every level, interpreted and with compiled blocks: no
difference from the host.

The manual's other rules that hold whatever the predicate says were read against the core and the
reference simulator the same day: BNOP's wait, the block on interrupts in the delay slots of a
branch that is not taken, and a skipped load still counting as a protected load were already
right; BDEC does not decrement when its predicate is false, as the manual has it.

## Bench results applied

Device sessions M1 (2026-11-16, image 0.3.1; rows B1, I1, I4, I5 and I6 of
`experiments/sessions/M1-bench.md`), M2 (2026-11-18, image 0.3.2, `M2-bench.md`) and M3 (2026-11-19,
image 0.3.4, `M3-bench.md`; its values are recorded here and in the tests, not in the sheet) answered
questions this emulator had left as stops or assumptions. In M1 each value below was the same in
three runs, with no exception and no event flag.
- **Misaligned accesses.** An aligned-form load or store (`LDH`, `LDW`, `LDDW`, `STH`, `STW`,
  `STDW`) at a misaligned address in RAM ignores the low address bits instead of stopping.
  Measured: `LDDW`, `LDW` and `STW` in cached DDR (M1); `LDH`, `LDHU`, `STH` and `STDW` in DDR and
  in L2 RAM (M2, rows M1: every misaligned width rounds down to its size). Such an access to a peripheral, or to low memory under a low-memory
  option, still stops. The reference simulator `analysis/c6sim.py` does the same, and
  `tests/test_loops.py` compares the two on one fixture.
- **USB reserved words.** `0x01e0080c` and `0x01e0084c` read 0 and stores of 0 to `0x01e00808` and
  `0x01e00848` are ignored, as on the unit with USB0 clocked, the PHY ready and no host attached
  (the only USB profile here). This is now the model's behaviour, not an option: the
  `--usb-reserved-status-zero` flag and its interrupt-routing guards are gone. The accesses are
  still counted and the first 4096 logged. A non-zero store, a narrower or DMA access, or an
  access before the PHY is ready still stops.
- **EMIFA.** CPU stores to chip select 0 (`0x40000000`-`0x5fffffff`, nothing fitted) are dropped and
  counted (`emifa` in the run report). The unit was measured at three words from `0x4630314c`
  and, in the 2026-11-18 session, at both ends of the range (`0x40000000`, `0x5ffffffc`); the rest is
  assumed to behave alike. Reads there stop unless `--reserved-low-reads` is given (next but one item).
- **Cache hand-off.** `L2CFG` starts as `0x01010000` (it was 4 here, which was a guess) and `MAR17`,
  `MAR128`, `MAR192`-`195` and `MAR199` as 1.
- **Reads of reserved low memory and of EMIFA chip select 0** (opt-in, `--reserved-low-reads`; strict
  stays the default). On the unit such a read returns data the CPU loaded earlier, with no exception
  or event flag. The rule the 2026-11-18 bench session (M2, image 0.3.2) established is used: the data
  of the CPU's loads is held as eight byte lanes; each load replaces the lanes it reads (one for
  `LDBU`, four for `LDW`, eight for `LDDW`, by address bits 2:0); a load from a device counts; stores,
  low reads and EMIFA reads leave the data alone; the read returns the lanes its own address picks.
  `tests/test_reserved.py` holds the bench's sequences and values, and the image itself, run here,
  shows the unit's values in its LOW2, L8 and LOWW views, including two (`C20004E4`, `C2002204`) that
  come from the image's own table loads. Every read is counted and the first 4096 logged with PC and
  value. Limits:
  - Each data path holds its own data (2026-11-19 session, M3, image 0.3.4, view SIDE): a load into
    a side A register (path T1) and a load into a side B register (T2) replace different data, and
    a read returns the data of the path of its own destination register. The side of the address
    register plays no part, and a load made in an interrupt handler counts like any other. All
    twelve of that session's sequences are reproduced (eleven in `tests/test_reserved.py`).
  - Side A's data is 0 after reset, as the unit's first two reads showed. Side B's first value was
    not measured and is taken to be 0 too. What the boot loader really leaves in either is not
    known.
  - A misaligned aligned-form low or EMIFA read still stops (not measured); `LDNW` and `LDNDW` at
    odd low addresses were measured and work.
  - The one read-back of 4 in the M1 session (I6) is still unexplained.
  The panel enables the option together with the low-store option unless `--strict` is given.
- **A period written to a running timer.** In the 2026-11-19 session a handler rewrote `PRD12` of a
  timer running in continuous mode on each of 4,096 interrupts and the unit's period did not
  change. The board model applies a written period to the running count. It is left that way: when
  the unit takes a written period up was not measured, and no stock image writes the period of a
  running timer in any run of the stock checks (logged once, 2026-11-19). Only the diagnostic
  image's own varied-period view (NOP2, N4) differs from the unit because of it.
- **Stores to reserved low memory** (`--reserved-low-writes`). Measured on the unit in the same
  session: `STW`, `STH` and `STB` at `0x0`, `0x10` and `0x200` store nothing and set no exception or
  event flag, so the event flags can now be read after such a store. The option's other guards
  (exception masks, event routing) are unchanged.

An independent review of these changes (2026-11-17) found one real fault, since fixed: a compiled
block that left a packet holding both a low read and a RAM load had already recorded that packet's
load, so the low read then saw its own neighbour's data instead of the previous load's
(`tests/test_reserved.py` reproduces it). Also from the review: with the board on, RAM can no
longer be mapped in the EMIFA range (a store there was kept or dropped depending on the path
taken), enabling the board again clears the EMIFA count, and a low read after a load whose
doubleword is not all RAM now stops with a message that says so.

With `--reserved-low-reads`, run by hand on 2026-11-17 (start-up, MIXER, HOME, PLAY; 4.9 × 10⁹
cycles, no stop): SmplTrek 1.0.65 reaches its sequencer; Lofi-12 XT 1.1.156, 1.2.179 and 1.5.205
with a blank card reach their main screen; CyDrums 1.1.84 (integrity check bypassed in a scratch
script, since it had no checksum profile then) shows INSERT CARD with no card, BLANK MEDIA with a blank
card and its main screen with its own card. In these runs some low reads return non-zero leftover
data (for example a pointer-like word, 109 times, in Lofi-12 XT), so their results depend on the
model's details in a way the SmplTrek 3.2.174 checks do not.

## Custom DSP programs

The emulator does not build firmware, but it runs a DSP program you supply on the same board model:

```sh
python3 -B emulator/custom.py --elf path/to/program.elf
python3 -B emulator/custom.py --elf program.elf --cycles 372000000 --break main --break my_loop \
    --watch status_word --card work/emulator/cards/card.img --export-card
```

The input is a linked little-endian ELF32 C6000 executable (`ET_EXEC`). Its loadable sections must
lie in the RAM the stock bootloader hands over, at global addresses: DDR2 (`0xC0000000`, 128 MiB),
L2 (`0x11800000`, 256 KiB), L1P/L1D (`0x11E00000`, `0x11F00000`) or shared RAM (`0x80000000`); the
local L2/L1 aliases are mapped for execution but an ELF cannot load there. Zero-filled sections count
too: GNU ld's default tic6x script adds a 32 MiB `.heap` and a 1 MiB `.stack`, which fit only in
DDR2, so link anything else with your own script. Execution starts at the ELF entry with no stack
set up, so the program's startup code must set B15 itself.
`--handoff gpio` (the default) leaves the GPIO functional clock enabled, so a program can drive the
power hold before its own clock setup; `--handoff stock` is exactly the stock SYSTEM handoff.
Unsupported MMIO, reads below the L2 (unless `--reserved-low-reads`) and other undefined behavior
stop with a diagnostic, as for stock. Symbols are read from the ELF itself, so no DSP toolchain is
needed to run a program: `--break SYMBOL` records the cycle each symbol is first reached (default
`main`, when present) and `--watch SYMBOL` reports the 32-bit word there after the run.

The report, `work/emulator/custom/result.json` (or `--output`), holds the program hash, CPU state,
checkpoints, watched words, recent MMIO, codec transactions, SD counts and audio slot timing; the
display is saved as `frame.bin`/`frame.png` once a complete frame arrives, and transmitted audio as
`audio.pcm32` and `audio.wav`. `--card` takes a private copy of a power-of-two SDSC image (see
`card_image.py` above) and `--export-card` saves the program's changes beside the report. The same
`--audio-input`/`--loop-audio-input` options as stock supply digital ADC data. From Python,
`custom.Custom(elf, ...)` gives the same session with `key_input(bit, down)` for the key matrix
(row-aware GPIO with edge interrupts; contact bounce, ghosting and settling are not modeled).

A complete update in the stock container format (`.bin`, `.zip` or `.syx` with valid CRCs, for
example one resealed with `tools/sonicware_integrity.py`) runs through the stock path instead:
`python3 -B emulator/stock.py --firmware path/to/update.bin` or `emulator/stock_ui.py --firmware ...`.
Checkpoints named after stock functions are only set when the image matches the 3.2.174 symbols.

On the audio path, the initial 255-word TX descriptor a program programs changes the slot phase:
settled even buffer words reach modelled slot 1, odd words slot 0. On the unit even words are the
left headphone channel (session M1, HW-61); line outputs were not checked. GPIO row output mux/direction and edge interrupts are modeled; input pads remain
readable regardless of pin mux, as SPRS590G section 3.6 requires.

## Stock firmware panel

```sh
python3 -B emulator/stock_ui.py
```

Open **http://127.0.0.1:8766**. The page shows the stock display as the guest draws it and plays
the McASP output once you press **Enable audio** (browsers require a click before sound). Start-up
to the sequencer takes about four guest seconds; the first run also decodes about 320 code pages
(roughly ten more seconds), which later runs read from `work/emulator/decode-cache/`.

Speed on the development host (2026-11-15, interpreter with fast-forward of repeating guest state):
the stock WAV preview about real time and warmed start-up audio about 1.15× (from 0.14× and 0.17×
before fast-forward), the idle project screen about 0.8×; anything that needed more than about 9% of
stock's cycles ran below real time, which the compiled blocks described below address. Evidence:
[the performance notes](performance-investigation.md#fast-forward-and-the-lean-path).

The page draws the instrument's panel: the display, the two selection buttons, knobs A to D
and VALUE, the direction keys, the eight function keys, OK and CLR, STEP 1 to 16 in two rows, and
the fifteen pads in their two staggered rows. Session controls and technical read-outs are in the
column beside it.

- **Buttons** are the 48 switch bits, placed after the stock test page's panel map. Hold with the
  mouse, or Shift-click to latch a button for combinations such as FUNC + HOME. The keyboard works
  too; the page lists it.
- **Knobs** turn by dragging up or down or with the scroll wheel (`[` and `]` for VALUE), and a
  click without a drag is the knob's push switch. They send complete quadrature sequences on the
  encoder GPIO pins, two stock polls per phase. Encoders 0 to 4 are A, B, C, D and VALUE, as the
  stock encoder test page labels them. The VOL knob and the speaker grille control the page's own
  sound; the input-gain and microphone knobs are drawn but not emulated.
- **Pads** send the panel MCU's analogue report (`Bn lo hi`) on UART1 at the stock byte rate, with
  the chosen pressure on press and zero on release. Analogue channel n is assumed to be pad n of
  the stock pad LED numbering (lower row even, upper row odd). That agrees with the channel order
  noted in device session D1 (run 7: index 0 = TRK 8, 1 = TRK 1, 2 = TRK 9, ...) and with M2's
  levels for TRK 1 (channel 1) and TRK 8 (channel 0); the other pads were not checked by level. The battery slider sends channel 15. Since 2026-11-17 the panel runs the continuous
  report stream described under "Panel MCU stream" below, as the unit's MCU does, and a press
  sets the level its channel reports; drum pads play. With `--no-panel-stream` one report is sent
  per change instead, which is faster but plays nothing on a drum pad (`tests/stock_pad.py`).
- **MIDI** (side column, **Connect MIDI devices**; a browser with Web MIDI, such as Chrome, Edge or
  Firefox). Every MIDI input the browser offers plays the emulated MIDI IN jack through the paced
  sender described under [MIDI and SYNC](#midi-and-sync-2026-11-20), and the bytes the firmware
  sends on MIDI OUT go to every MIDI output, cut into whole messages. So a keyboard plays the
  firmware's tracks and its clock or notes drive a synth. Input timing inside the guest is exact;
  output leaves when the page receives it, each emulation slice (2 ms) plus the page's own delay,
  so it is late and uneven by a few milliseconds: fine for playing, not for measuring clock
  jitter. System exclusive passes only if the browser grants it. The page's message assembly and
  the server path are tested (`tests/stock_ui_smoke.js`, `tests/test_stock_ui.py`); no MIDI
  hardware was connected to it.
- **Panel LEDs** light the control they belong to: the `C1 a b c value` commands stock transmits
  to the panel MCU are mapped through the table that `analysis/led_table.py` prints (keys and
  steps green and red, pads and the VALUE knob red, green and blue). The raw 144 addresses are
  still shown in the side column.
- **Panel labels** in the side column chooses the printing. The default, Generic, is meant for
  work on other firmware and names nothing product-specific. The function
  keys read F1 to F8 (left to right, upper row first: switch bits 19, 26, 20, 27, then 22, 29, 21,
  28) with no icons or shifted functions, the pads PAD 0 to 14 (the analogue channel, lower row even and upper row odd), then the steps,
  knobs A to D, VALUE, OK and CLR. Sampler, Lo-fi sampler and Drum synth give the SmplTrek,
  Lofi-12 XT and CyDrums printing; the three panels are physically the same and only the function
  keys and pads are printed differently (`docs/10-cross-flash-button-map.md`). The browser remembers
  the choice and `--labels` sets what a fresh browser starts with. `--profile lofi12` runs a
  Lofi-12 XT image.
- **Pause**, **Power key** and **Save display** are in the side column, with guest time, the share
  of idle cycles skipped, the achieved speed and the audio underrun count.

`--card image` and `--flash image` supply media; private copies are used. `--no-panel-stream`
turns off the panel MCU's continuous reports (see "Panel MCU stream"). `--state directory`
loads `card.img` and `flash.img` from that directory when present and writes them back on **Save
card & flash** and at exit, so settings and projects persist between runs. `--speed`, `--port`,
`--slice-ms` and `--no-fast-forward` are also available.

The panel compiles hot guest code with the host C++ compiler while it runs, in the background, and
switches to it as each batch is ready (about 20 s after start for most of it the first time a
firmware is run; later runs find the blocks compiled before and have them within a second or two
of the code turning hot). This is on by default
since 2026-11-17; `--no-blocks` interprets everything, and the panel falls back to that with a notice
if no host compiler is found or a build fails. Compiled code leaves the same state as the interpreter
(checked by `stock_survey.py --blocks`, `stock_fuzz.py` and `stock_song.py --blocks`) and is three to
four times faster. A playing project needs it: the interpreter alone runs the generated test song at
about 0.6× real time. See [the performance notes](performance-investigation.md).

The page starts stock with the low-store and low-read options (the `CONDITIONAL BOOT` badge),
because strict mode stops in USB start-up. `--strict` keeps the faults. Inputs are external signals
only; no guest function is hooked. Not verified against a device: which knob is which encoder index,
and the line outputs' left/right (slot 1 is played left, which matches the unit's headphones, HW-61;
the page can swap them). The panel MCU stays silent apart
from its analogue reports (or, with `--no-panel-stream`, what you send), so stock receives no
`A1` version reply. Analog codec behaviour is not modeled.

When the host cannot keep up the speed figure turns red and audio breaks up; the emulation stays
exact and simply runs late. Heavier projects will do this on any current host.

**Other systems.** The page needs only a current browser. The emulator itself needs Python 3.10+
and a C++20 compiler: `g++` or `clang++` on the path, or `CXX`. Linux with GCC is the developed
and tested configuration. `core_build.py` selects macOS and Windows (MinGW-w64) linker flags and
drops warnings-as-errors there, but those builds have not been run. Decoding new code pages needs
the patched `tic6x-elf-objdump` under `tools/tic6x/bin`; a `decode-cache` directory copied from a
machine that has it lets a machine without it run the same firmware and media.

`python3 -B emulator/tests/stock_forward.py --conditional` compares a fast-forwarded run of the
WAV-preview scenario with one that executes every cycle. `tests/test_stock_ui.py` checks the
server's input encoding, stream and pacing against a recording stand-in, and runs the page's
script in a DOM harness when Node is available.

## Validation

```sh
python3 -B emulator/tests/verify.py                # every check, side by side
python3 -B emulator/tests/verify.py --tier fast    # while working on a change
python3 -B -m unittest discover -s emulator/tests -p "test_*.py"
```

Requirements: Linux, Python 3.10 or newer and host `g++` with C++20 support. The unit tests that
assemble or compile guest code need the DSP binutils/GCC under `tools/tic6x/bin` (build them with
`tools/toolchain/build_tic6x_*.sh`) and skip themselves without them; the stock checks need the
stock update under `firmware/` and skip themselves without it. Node is optional and used only to run
the stock panel's script in a DOM harness.

`verify.py` runs everything described in this README as separate processes at once: each unit test
file, every stock check on the interpreter and with compiled blocks, the compiled-C comparison per
compiler and level, and the reference simulator's own comparison and tests under `analysis`
(the count follows the test files present). Each has its own output folder under `work/emulator/verify/`, and the caches they
share (the core, the preset cards, the project tools) are built before any of them starts. On the
16-core host used here the full set takes about 8 minutes; run one after another it took about
110. Two full passes gave the same results as the serial run. `--tier fast` (the unit files,
`stock_boot` and one compiled level per compiler; about 2 minutes) is for use while editing; `--only`, `--skip`
and `--list` select steps by name. Speeds printed by individual checks are lower under this load
and are not compared; measure speed with the check on its own.

Generated files (the core build, block caches, cards, reports) go to the ignored `work/emulator/`;
most scripts take `--work` to use another folder.

## Language boundary

Python loads images, drives sessions, builds cards and serves the stock panel; JavaScript draws the
panel and sends inputs. The **C++** CPU backend (try `python3 -B emulator/core_run.py`; see
[the core documentation](core/README.md) for supported instructions, binary execution and timing
checks) has a narrow C interface and runs bounded slices without Python in the execution loop.
The Python `c6sim` under `analysis/` remains a semantic reference and differential oracle; its
synthetic throughput was about 190000 packets/second, far too slow for interactive firmware or audio.
Production CPU stepping, peripheral events and audio processing stay in the compiled core.

## Panel MCU stream (2026-11-17; on in the panel, opt-in elsewhere)

On the unit the panel MCU sends its analogue channels all the time, touched or not: 4,192 to 4,196
`Bn lo hi` messages a second, 262 a second on one channel (M1 bench D1, D2). `--panel-stream`
(`stock.py`, `stock_ui.py`; `Stock(panel_stream=True)`; `c6_panel_stream` in the core) adds that
peer to UART1. It is timed in guest cycles inside the board model, so a run with it is as
repeatable as one without, and compiled blocks give the interpreter's result
(`tests/stock_pad.py --blocks`). Levels are set with `Stock.panel_level(channel, value)`; while
the stream is on, bytes cannot also be injected into UART1.

Measured (M1, and M2 on 2026-11-18): the total rate; 262 to 263 messages a second on each of 16
channels, with pads held or not; the fixed channel order `0 4 3 7 B D A E F 2 1 5 9 6 8 C`, which
the model now sends (it sent 0 to 15); nothing but `Bn` messages in a second of idle traffic. Not
as the unit: messages are evenly spaced here, where the unit sends them in bursts (64.9 to
1,455.7 µs apart, 238.5 µs on average); characters are spaced at the rate the firmware programs
into UART1 (21.4 to 22.0 µs on the unit); an untouched pad reads 0 here and 0 to 4 on the unit;
the battery channel starts at 12000 until set (on the AC adapter the unit read 0 to 6; batteries
were not measured). The MCU's other messages (`A1`) are still not sent.

What it changes, on 3.2.174:

- **Pads work.** With a DRUM track and the Rock kit, raising channel 0 to 9000 for 150 ms plays
  the drum (output RMS 0.060). Without the stream, the one report with the level and one with 0
  that the checks and the panel send play nothing. `tests/stock_pad.py` pins both.
- **Interrupt load.** The firmware takes about nine times as many interrupts at the idle
  sequencer (148,740 against 15,880 in the first 10.6 guest seconds).
- **Speed, on this host, idle sequencer:** interpreter 0.69× real time without the stream, 0.49×
  with it; compiled blocks 2.16× and 1.27×. With the stream off the board does no extra work, and
  the saved results of every other check are unchanged. It therefore stays off by default in
  `stock.py` and the checks.
- **Playing, with compiled blocks:** the six-track project plays at 1.14× with the stream (1.80×
  without; `stock_multitrack`'s playback step run by hand). The panel process itself, paced at
  `--speed 4` with no browser attached, plays the generated FUNK song at a median 1.18× with the
  stream (1.84× without); in the first second of playback, while that code is still being
  compiled, it dipped to 0.96×. The audio differs slightly from a run without the stream
  (interrupt timing), with no underruns.
- **With a browser on the page and its audio on** (headless Chromium, 2026-11-17): unpaced, the
  same song plays at a median 1.11× with the stream. At the normal pace the page shows 1.00×
  and counts no audio underrun during playback, with the stream or without; its buffer fell to
  215 ms once in the seconds after PLAY. The only underruns are in the first 15 to 25 seconds
  after start, before the compiled code is ready, and those happen without the stream too.
- **Random input:** `tests/stock_fuzz.py --panel-stream` gives the same final state on the
  interpreter and with compiled blocks.

The panel turns the stream on by default since it holds real time on this host and pads need it;
`--no-panel-stream` turns it off. The margin is small: on a slower host, or without compiled
blocks, the panel's speed figure will show it falling behind, and that switch is the remedy.

Where the cost is (measured 2026-11-17, compiled blocks, idle sequencer, four guest seconds): the
firmware takes 50,000 more interrupts and executes 67 million more guest cycles (its UART handler
and the message handling behind it), in 14 million entries into host code instead of 8 million.
That is work the unit's CPU also does. Two attempts to make it cheaper were measured against the
unchanged core and dropped because neither helped; they are described in
[the performance notes](performance-investigation.md).

## MIDI and SYNC (2026-11-20)

MIDI DIN is UART0 and the SYNC jacks are GP7[8] (in) and GP7[9] (out)
(`docs/04-hardware-access.md`). The board model has a peer for each, all timed in guest cycles
inside the core, so a run is identical whatever the slice size, with fast-forward or without.
From Python (`cpu.py`):

| Call | What it does |
|---|---|
| `midi_in(data)` | Queue bytes from a sender on MIDI IN. They arrive back to back, one per character time of the divisor and format the guest programmed (119,040 cycles: 31,250 baud 8N1), the first starting now on an idle line. |
| `uart_receive(0, data)` | The unpaced path, unchanged: every byte at once, for deliberate overruns. |
| `midi_loopback(on)` | A cable from MIDI OUT to MIDI IN: each byte UART0 transmits is received at the cycle it finishes. `midi_in` is refused meanwhile. |
| `midi_state()` | `queued`, `delivered`, `ignored` (receiver held in reset), `looped`, `fifo` (bytes waiting in the receive FIFO), `overruns` (bytes lost to a full FIFO, cumulative), `line_errors` (what LSR would report now; reading this does not clear it), `character_cycles`, `next_cycle`. |
| `uart_sent(index, since, cycles=True)` | `(bytes, total, cycles)`: each transmitted byte with the cycle its last stop bit ended at. Without `cycles` it returns `(bytes, total)` as before. |
| `gpio_schedule(bank, pin, high, cycle)` | An external pin level applied at a guest cycle; `gpio_schedule_clear(bank, pin)` drops the ones not yet applied, `gpio_scheduled()` counts them. |
| `sync_in(bpm, pulses, start=None, per_quarter=2, width_ms=15, active_high=True)` | A pulse train on SYNC IN. Returns the cycle the next pulse would start at: pass it as `start` to carry on at another tempo; schedule nothing more for a clock that stops, or call `sync_in_stop()` to stop one mid-train. |
| `gpio_trace(since)` | `(rows, total)`: level changes of watched output pins as `bank`, `pin`, `high`, `cycles`. GP7[9] is watched from the start; `gpio_watch(bank, pin)` adds a pin. A pin's first row is the level it drives on becoming an output. |

`Stock.midi_in` is `midi_in` with the input recorded in the run report. The traces keep the latest
4,096 bytes or changes; read them with `since` often enough.

What the model does and does not claim:

- The MIDI IN sender takes its bit rate from the guest's own divisor and format. A real sender keeps
  31,250 baud whatever the guest programmed, and a wrong divisor shows as framing errors on the
  unit; here it shows only as `character_cycles` differing from 119,040. No framing, parity or
  break error is ever produced, so `line_errors` can only show an overrun.
- The loopback has no opto-isolator or cable delay: a byte is received in the cycle its
  transmission ends.
- SYNC OUT is recorded when GP7[9] is an output and PINMUX17 puts it on its pin (nibble 0 = 8), so
  firmware that forgets the pin mux shows no pulses. Other watched pins are recorded from the GPIO
  registers alone. Jack wiring, levels and any buffer between pin and jack are not modelled; if the
  board inverts SYNC IN, pass `active_high=False`.
- USB MIDI goes through the USB host below, not through these calls.

**Against the stock firmware.** `tests/stock_midi.py --conditional` runs 3.2.174 with the generated
drum project and sets CLOCK OUT, OUT/THRU, COMMAND and the clock SOURCE through the firmware's own
menus. Results at 104 BPM, all in emulation (nothing here was measured on a unit):

- *MIDI IN.* A note on channel 1 (track 1's channel) plays the drum track (rms 0.057) and on a
  channel no track uses nothing sounds. (Channel 16, the AUTO channel, also played it in a run by
  hand; the check does not cover that.) A 300-byte SysEx dump
  followed by a note is received with no overrun and the note plays; the same 300 bytes through
  `uart_receive` lose 284 to the 16-byte FIFO.
- *MIDI OUT.* Nothing is sent with the factory settings. With CLOCK OUT on, `0xF8` goes out 24 times
  per quarter note (9 or 10 audio blocks apart, 2.67 ms each, never further than one block from the
  nominal spacing), running or stopped; with COMMAND = RX/TX, PLAY sends `0xFA` 8 ms after the key
  and STOP sends `0xFC`. With OUT/THRU = THRU the jack repeats MIDI IN (a byte's retransmission starts about
  1 µs after it arrived) and the unit's own clock is not sent.
- *SYNC OUT.* GP7[9] is driven low at set-up and pulses high twice per quarter note, running or
  stopped, on audio block boundaries, for 14.3 to 14.9 ms: the firmware ends a pulse on the
  fifteenth 1 ms tick after it starts. Twelve MIDI clocks go out per pulse, and the clock of a
  pulse's position is written 3.4 µs before the pin rises.
- *SYNC IN.* With SOURCE = SYNC the firmware enables the bank 7 interrupt (BINTEN bit 7), and its
  handler acknowledges every scheduled edge. Sixteen pulses at 140 BPM and then sixteen at 90: the
  firmware's external-clock tempo (`0xC1501FE8` + 40) reads 139.8 half a second in and 140.0 after
  two seconds, 89.9 to 90.0 from 0.7 s after the change, and keeps its last reading when the pulses
  stop.
- One thing to check on a unit: with POLARITY IN at its default, which the CLOCK page shows as
  RISE, the firmware arms the *falling* edge of GP7[8] (FAL_TRIG67 bit 24; setting value 0). Either
  the board inverts SYNC IN between jack and pin or the label is the other way round from the pin.
  The tempo results above do not depend on it.

These agree with the static findings HW-11, HW-27, HW-31 and HW-41; they do not raise any of them
to `observed-device`.

## USB device and scripted host (2026-11-20)

USB0 is modelled as SPRUH79C chapter 33 describes it: the TI wrapper at `0x01E00000`, the MUSB core
in peripheral mode at `0x01E00400`, and the PHY status in CFGCHIP2. On the cable is a scripted
full-speed host, timed in guest cycles inside the core like the MIDI and SYNC peers, so a run is
identical with fast-forward or without. From Python (`cpu.py`):

| Call | What it does |
|---|---|
| `usb_attach()` | Plug the cable in: VBUS now (DEVCTL `0x99`, CFGCHIP2 USB0VBUSSENSE). When the device's pull-up shows (SOFTCONN with PSC1 module 1 on and the PHY clock good) the host debounces for 100 ms, resets the bus for 10 ms and enables the port; the first transfer starts 10 ms later. |
| `usb_detach()` | Unplug: the session ends (INTRUSB DISCON), a transfer under way ends as `"disconnected"`. |
| `usb_reset()` | Reset an enabled port again. |
| `usb_sof(on)` | The 1 ms start-of-frame (372,000 cycles), on by default from the end of reset. Off, an idle bus suspends the device 3 ms after the last packet and the next packet resumes it. |
| `usb_control(setup, data_or_length)` | SETUP, data stage, status stage. `setup` is the 8 bytes, or `(bmRequestType, bRequest, wValue, wIndex)` with wLength taken from the data or length. Returns a result (below); a STALL in any stage gives `status == "stall"`. |
| `usb_out(ep, data)`, `usb_in(ep, max_length)` | Bulk or interrupt transfers in packets of the endpoint's size, retried while the device answers NAK. `usb_in` ends at `max_length` bytes or a short packet. |
| `usb_enumerate(address=1)` | Waits for the port, then: 8 bytes of the device descriptor, SET_ADDRESS, the device descriptor, the configuration descriptor (9 bytes, then all of it), SET_CONFIGURATION. Returns the descriptors, vendor, product, the endpoints found and each step's result; raises `UsbError` if a step fails. Later transfers use the packet sizes it read. |
| `usb_set_interface(interface, alternate)` | SET_INTERFACE, as a host does to open (1) or close (0) an audio streaming interface. Any other request goes through `usb_control`. |
| `usb_iso_stream_out(ep, packets)` | Queue payloads for an isochronous OUT endpoint, one packet per frame. See "Isochronous streams" below. |
| `usb_iso_stream_in(ep, frames)`, `usb_iso_collect(ep)` | Ask an isochronous IN endpoint for a packet in each of the next frames; returns them with their frame numbers. |
| `usb_iso_state(ep)`, `usb_iso_stop(ep)` | One stream's counts; drop what is queued. |
| `usb_state()` | `port` (`detached`, `powered`, `debounce`, `reset`, `enabled`), `address` and `configuration` (the host's), `device_address` (what the controller answers to), `naks`, `stalls`, `errors`, `toggle_errors`, `bus_resets`, `sofs`, `frame`, `suspended`, `interrupt_mode`, `fifo_overflows`, `fifo_underflows`, and for each of endpoints 1 to 4 its packet sizes, FIFO placement, waiting packets and stall state. |

Every transfer call takes `timeout_ms` (default 1000, in guest time) and `wait`. With `wait=True`
the call runs the guest until the transfer has finished and returns
`dict(status, data, sent, naks, submitted, completed)`: `status` is `ok`, `stall`, `timeout`,
`disconnected` or `error` (no answer, or a packet that broke the protocol); `submitted` and
`completed` are guest cycles. With `wait=False` it returns an id at once; the host works through
queued transfers one at a time while the guest runs, `usb_result(id)` reads one and `usb_wait(id)`
runs until it is done. The guest stops within 1,024 cycles of a transfer finishing.

**Timing.** One bit is 31 cycles (372 MHz / 12 Mbit/s). A transaction takes effect at the cycle its
handshake would end: 161 bit times for a SETUP, 97 + 8 per byte for an OUT, 58 for an IN that is
NAKed or stalled and 97 + 8 per byte more for one that returns data; 4 bit times separate
transactions. Bit stuffing is not counted. A NAKed transaction is retried back to back (every 62
bit times for an IN); the retries between a NAK and the firmware's next access to USB0 are counted,
not run, so NAK counts and completion cycles are exact while an idle wait costs nothing. After
SET_ADDRESS the host waits 2 ms.

**What the controller model covers** (register behaviour from SPRUH79C 33.2.6, 33.2.7.1 and 33.4):

- Endpoint 0 and endpoints 1 to 4 through INDEX (`0x410`) and directly (`0x500` + 16 per endpoint),
  a byte, half-word or word at a time; the FIFO registers at `0x420` + 4 per endpoint, where an
  access loads or unloads as many bytes as it is wide.
- The 4 KiB FIFO RAM with TXFIFOSZ/RXFIFOSZ/TXFIFOADDR/RXFIFOADDR. Packets are stored in that RAM at
  the programmed place, so overlapping FIFOs corrupt each other as they would; endpoint 0 has 64
  bytes at address 0. Double packet buffering holds two packets (TXPKTRDY then clears at once with
  an interrupt, FIFOFULL shows two received). Loading past a FIFO's packet size or unloading an
  empty one is counted in `usb_state()` and otherwise ignored.
- Endpoint 0's handshake: RXPKTRDY and COUNT0 for SETUP and OUT data, SERV_RXPKTRDY, TXPKTRDY,
  DATAEND, SENDSTALL and SENTSTALL, SETUPEND and SERV_SETUPEND, FLUSHFIFO. A status stage is NAKed
  until DATAEND is set; a token the stage does not expect is answered with STALL, as in 33.2.7.1.1.5.
- On endpoints 1 to 4: TXPKTRDY, FIFONOTEMPTY, RXPKTRDY, FIFOFULL, RXCOUNT, SENDSTALL/SENTSTALL,
  FLUSHFIFO, CLRDATATOG, AUTOSET and AUTOCLEAR. Both ends keep the DATA0/DATA1 toggle: a packet
  with the wrong one is acknowledged and dropped as a repeat and counted in `toggle_errors`, which
  is how a missing CLRDATATOG after SET_CONFIGURATION shows. The host restarts its toggles after
  SET_CONFIGURATION, CLEAR_FEATURE(ENDPOINT_HALT) and, for endpoints `usb_enumerate` found,
  SET_INTERFACE.
- FADDR: the controller answers to the new address from the end of the status stage of the control
  transfer during which it was written; written between transfers, at once. Both orders in use
  (write on decoding SET_ADDRESS, or after the status-stage interrupt as SPRUH79C says) work.
- POWER (SOFTCONN; RESET reads 1 during bus reset, SUSPENDM while suspended; HSEN is held and has
  no effect), DEVCTL, FRAME (the last SOF's number), INTRTX/INTRRX/INTRUSB with their enables.
  Bus reset clears FADDR, INDEX, the FIFOs and the CSRs and keeps packet sizes and FIFO placement.
- The wrapper: CTRLR (RESET, UINT), INTSRCR, INTSETR, INTCLRR, INTMSKR and its set and clear
  registers, INTMASKEDR, EOIR, and event 19.
- CFGCHIP2: USB0PHYCLKGD 64 cycles after the PLL is switched on (a functional delay, not a measured
  lock time) and USB0VBUSSENSE while the cable is in.

**Isochronous streams (2026-11-21).** An endpoint direction whose ISO bit is set (TXCSR or RXCSR
bit 14) is served by streams instead of transfers. Each 1 ms frame, right after the SOF, the host
goes through endpoints 1 to 4 in order: one OUT packet if the endpoint has payloads queued, then one
IN token if frames were asked for. There are no handshakes, no retries and no data toggles, so
nothing here adds to `naks` or `toggle_errors`.

- `usb_iso_stream_out(ep, packets, wait=False)` queues one payload per frame (0 to 1023 bytes each;
  an empty one is a zero-length packet) behind any still queued. A frame with nothing queued carries
  no packet. It returns `usb_iso_state(ep)`.
- `usb_iso_stream_in(ep, frames, wait=True, max_packet=None, short_below=0)` sends an IN token in
  each of the next `frames` frames and returns one row per token: `frame` (the SOF's frame number,
  as FRAME reads it), `cycles` (when the transaction ended), `data` and `status`: `data`, `empty` (a
  zero-length packet) or `error`. With `wait=False`, fetch the rows later with `usb_iso_collect(ep)`.
- `usb_iso_state(ep)` (address with bit 7 for IN) gives `queued`, `sent`, `packets`, `bytes`,
  `missed`, `short`, `errors`, `waiting` and `dropped`. For OUT, `missed` are packets lost because
  the FIFO was full and `errors` packets the device could not take at all (not listening, the
  endpoint not isochronous, or the packet above RXMAXP or the FIFO). For IN, `missed` are
  zero-length answers, `short` data packets under `short_below` bytes, and `errors` tokens with no
  answer (not listening, or the endpoint not isochronous) or with a packet above `max_packet`.
- `usb_state()` adds `iso_errors` and `iso_missed` (the streams' sums), `iso_underruns` and
  `iso_overruns` (how often the device set UNDERRUN or OVERRUN), and `tx_underrun` / `rx_overrun`
  per endpoint. A zero-length packet the firmware loaded on purpose counts as `missed` at the host
  but is no underrun.
- `usb_sof(False)`, a bus reset or unplugging stops the streams; the last two also empty them.
  `usb_out` and `usb_in` refuse an isochronous endpoint.

What the device does, from SPRUH79C 33.2.7.1.4:

- *OUT.* With room in the FIFO the packet is stored, RXPKTRDY is set and the endpoint interrupt is
  raised, as for bulk. With no room the packet is lost and OVERRUN (RXCSR bit 2) is set until
  software writes it 0. Double packet buffering holds two.
- *IN.* A loaded packet is sent; TXPKTRDY clears and the interrupt is raised at the end of the data
  packet. With nothing loaded the device sends a zero-length packet and sets UNDERRUN (TXCSR bit 2).
  SENDSTALL has no effect.
- *POWER.ISOUPDATE.* A packet loaded into an isochronous IN FIFO is held back until the next SOF;
  an IN token before that gets a zero-length packet, with no UNDERRUN.
- *SOF.* INTRUSB SOF is latched every millisecond from the end of bus reset, configured or not, and
  FRAME holds that SOF's number, so a handler can pace its packets on it.

Timing: an OUT packet of n bytes ends 78 + 8n bit times after the SOF (or after the transaction
before it in the frame); an IN token ends 39 bit times after, and its data packet 39 + 8n more. For
48 kHz stereo at 192 bytes that puts the OUT packet in the FIFO 0.13 ms into the frame.

Two things the manual leaves open, and how the model reads them: UNDERRUN and OVERRUN raise no
interrupt of their own (firmware must not wait for one), and DATAERROR and PID_ERROR are never set
because the cable has no bit errors. The streams are not scheduled around a control or bulk transfer
that is under way at the SOF; both happen at their own cycles.

**Which interrupt registers to read (CTRLR.UINT).** SPRUH79C says this much:

- UINT = 0 ("PDR interrupt handler enabled", the reset state): status is in INTSRCR, or INTMASKEDR
  for the enabled part; a source is cleared by writing its bit to INTCLRR; the interrupt is
  acknowledged by writing 0 to EOIR, and "while EOIR is not written, the interrupt from the USB
  controller remains asserted" (33.2.8.13.1). INTSRCR bits 0 to 4 are endpoint 0 and TX endpoints
  1 to 4, bits 9 to 12 RX endpoints 1 to 4, bits 16 to 23 INTRUSB, bit 24 DRVVBUS (33.4.9). The
  core registers must not be read: "Performing a read clears the pending interrupt" (33.4.23,
  33.4.24, 33.4.27).
- UINT = 1: "you need to use the interrupt status/flag from the core register space" (33.4.9 to
  33.4.15), that is INTRTX, INTRRX and INTRUSB, each cleared by reading it.
- The example initialisation (33.3.1) uses UINT = 0 and programs both layers: INTRTXE = `0x1F`,
  INTRRXE = `0x1E`, INTRUSBE = `0xFF` and INTMSKSETR = `0x01FF1E1F`.

It does not say how events get from the core into INTSRCR, whether the core's enable registers gate
that, or what EOIR does with UINT = 1. The model fills those in as follows, and this part is a
reading, not a documented or measured fact:

- The core always latches events in INTRTX/INTRRX/INTRUSB.
- UINT = 0: an event enabled in INTRTXE/INTRRXE/INTRUSBE moves at once from the core register to
  INTSRCR. An event that is not enabled there stays in the core register and never reaches INTSRCR
  (it does when the enable is set later). Event 19 is raised once when INTSRCR & INTMSKR becomes
  non-zero and again on a write to EOIR while it still is, so a handler reads INTSRCR (or
  INTMASKEDR), writes that to INTCLRR, serves it and writes EOIR; anything that arrived meanwhile
  raises the event again. A core register read returns and discards only events that were not
  enabled.
- UINT = 1: INTSRCR gets nothing from the core. Event 19 is raised when the enabled, latched core
  events go from none to some, so a handler must read all three registers until all read 0: an
  event that arrives while another is unread raises nothing new. A write to EOIR raises the event
  again if something is still latched. Bits set through INTSETR still interrupt through the mask.

For Enaga this means: use UINT = 0 as the stock does, enable every endpoint and bus event you
want in both the core enables and INTMSKSETR, read INTSRCR, clear with INTCLRR, end with EOIR = 0,
and leave INTRTX/INTRRX/INTRUSB alone. That sequence is the one with evidence behind it: it is the
manual's example and what the stock firmware does on the unit. The model is deliberately the
stricter one where the manual is silent (no core enable, no interrupt), so firmware that passes
here does not depend on the open points. One difference from the manual to be aware of: after a
controller reset the model's INTRTXE, INTRRXE and INTRUSBE read `0x0001`, 0 and 0 (kept from the
earlier model), where SPRUH79C gives `0x1F`, `0x1E` and `0x06`; program them rather than rely on
either.

**Limits.**

- Full speed only. DMAEN faults: CPPI DMA has set-up registers only, so the stock card-reader mode
  (mass storage over DMA) cannot run.
- An isochronous stream carries exactly what the test queued, one packet a frame. The host does
  not adapt its rate, and its clock is the guest's, so host and device cannot drift apart: rate
  matching (an asynchronous IN endpoint's varying packet sizes, the stock PLL trim) is not exercised.
- The host is one device on a root port: no hub, one transfer at a time in the order queued, no
  frame scheduling around the SOF, no bit errors, no retries after a missing handshake (the transfer
  ends as `error`). Its timings (100 ms debounce, 10 ms reset, 10 ms recovery) are fixed.
- UNDERRUN is never set on a bulk endpoint, FLUSHFIFO raises no interrupt and FRCDATATOG is held
  without effect: the manual does not settle them. Resume signalling from the device (POWER.RESUME)
  faults.
- The two reserved words the StarterWare driver reads (`0x01E0080C`, `0x01E0084C`) still read 0 with
  a cable in; that was measured on the unit only with no host.

**Against the stock firmware.** `tests/stock_usb.py --conditional` runs 3.2.174 with the generated
drum project, plugs the host in once the sequencer is up and drives the firmware through its own
menus. Results, all in emulation (nothing here was measured on a unit):

- *Enumeration.* All six steps succeed with no STALL, error or toggle error: vendor `0x2fd7`,
  product `0x0004`, bcdUSB 1.10, 64-byte endpoint 0, and a 234-byte configuration descriptor equal
  byte for byte to the one `analysis/usb_desc_map.py` rebuilds statically (HW-12, HW-18): audio
  control, two audio streaming interfaces (isochronous `0x01` and `0x82`, 196 bytes), MIDI streaming
  on bulk `0x03` and `0x83` at 64 bytes. The firmware answers most requests before the host's
  first IN (no NAK) and NAKs a few times while it prepares the configuration descriptor. It runs with
  UINT = 0 and takes the SOF interrupt every millisecond.
- *After SET_CONFIGURATION* it programs endpoint 3 for 64-byte packets with single-packet FIFOs at
  RAM addresses 832 (IN) and 896 (OUT), and 256-byte FIFOs for the audio endpoints (OUT `0x01`
  double-buffered at 64, IN `0x82` at 576) whose packet sizes stay 0 until an alternate setting is
  chosen.
- *Control.* A GET_DESCRIPTOR for a type it does not have is answered with STALL, and the next
  request (GET_STATUS) succeeds. A second bus reset is followed by a second, identical enumeration.
- *Bulk OUT.* The USB MIDI event `09 90 24 6E` (note-on, channel 1) on endpoint `0x03` plays the
  drum track at the same level as the note on MIDI IN (rms 0.057); on a channel no track uses
  nothing sounds. Neither packet is NAKed.
- *Bulk IN.* With CLOCK OUT on and COMMAND = RX/TX, PLAY puts `0F FA 00 00` on endpoint `0x83` 5 ms
  after the key and then `0F F8 00 00` 24 times per quarter note (62 in 1.5 s at 104 BPM), and STOP
  puts `0F FC 00 00`. Stopped, the firmware sends no clock over USB and loads nothing into the FIFO,
  where its DIN jack keeps sending `0xF8` ([MIDI and SYNC](#midi-and-sync-2026-11-20)); with the
  factory settings endpoint `0x83` stays silent.

`tests/stock_usb_audio.py --conditional` then opens the two audio streaming interfaces and streams
both ways (emulation only, like the rest):

- *Interfaces.* GET_INTERFACE answers 0; SET_INTERFACE 1 succeeds on interfaces 1 and 2 and
  GET_INTERFACE then answers 1. The firmware makes endpoint 1 an isochronous OUT endpoint and
  endpoint 2 an isochronous IN endpoint of 196 bytes, each when its own interface is opened, and
  uses FIFO access (no DMA).
- *OUT.* 13,600 packets of 192 bytes (a 1 kHz tone, 48 kHz 16-bit stereo), one per frame: all
  stored, no OVERRUN. The tone is silent until the USB AUDIO track is switched on with its pad
  (panel channel 12 on the home screen) and then reaches the line output at unity (amplitude 0.3661
  for 12000 / 32768). With the track on and no more packets, the output keeps repeating the last
  128-frame block, as HW-40 describes. A second pad press switches it off.
- *IN.* The firmware answers every frame with a 192-byte packet, after one zero-length packet that
  it loads itself when the interface opens; there is no UNDERRUN. The packets carry the mix: the
  tone comes back at the same level.
- *Trim.* While a streaming interface is open TIMER64P1 runs as a 64-bit counter (TGCR `0x13`,
  both periods all ones) at exactly 24,000,000 counts a second, and stops when both interfaces are
  back at 0. In 12 s of streaming the firmware does not write the codec at all: with the emulator's
  one exact clock there is nothing to correct, so the trim arithmetic itself is not exercised.
- *After closing.* Endpoint 2 stays isochronous at alternate setting 0: further IN tokens get one
  left-over packet, then zero-length packets with UNDERRUN (recorded, not judged).

These agree with the static findings HW-12, HW-18 and HW-40; they do not raise any of them to
`observed-device`.

## Backlog

- **Panel MCU stream cost and detail.** The stream above costs about 40% of speed. What is left
  to try is general host-code overhead, which would help every run: host code is entered about
  every 19 guest cycles, and each entry pays for a table lookup, a code-unchanged check and an
  ordinary tick. The channel order is measured (above); jitter and idle levels are not modelled.
- **Low reads and stores by DMA** were not measured; only the CPU's were (M1 to M3).

- **GP3[8]** has an explicit level in a stock session (`Stock(gp3_8_high=...)`, low by default as
  before). Every product uses the built-in microphone only while the pin reads high. With it low
  SmplTrek 3.2.174 draws a speaker in the title bar and with it high headphones (x 93), so the pin
  reads as headphone detection; the unit was not measured, and the panel has no control for it yet.
- **Held pads in the other products.** With the pad stream on and a level held, CyDrums 1.1.84 (on
  the product's card contents) runs its pad-pressure path once per report: in one second of hold
  the pad handler (`0xC24CD4A0`) was entered 261 times, and for channels 0, 8 and 14 so were the
  hand-over to the pads' internal MIDI stream (`0xC2578014`), `on_midi_channel_pressure`
  (`0xC24E29F8`) and its per-track function (`0xC24E2970`); for channels 1 and 5 only the handler
  ran, as it should for a pad with no track. With nothing held none of them ran. The messages stay
  inside the firmware, so nothing is expected on MIDI out (UART0), and nothing was sent there.
  Not tried: the same in 2.0.97, and Lofi-12 XT's pressure baseline.

### What the model assumes without stopping

As of 2026-11-19. Where something is not implemented the core stops with a message. These are the places where it
carries on with a value or a timing that was not measured, or that the unit is known to do
differently. Each needs the unit to settle.

| Assumption | What is known | Who is affected |
|---|---|---|
| Held load data of side B is 0 until the first side B load | side A's was 0 at the image's first two reads (M2 L9) | a low read into a side B register before any side B load; no firmware seen does it |
| Held load data starts at 0 when an image starts | the boot loader's last loads would really be there | the first low read of an image, if before its own loads |
| A period written to a running timer applies at once | the unit kept its period through 4,096 writes (M3 N4); when it takes one up is not known | none of the stock images in the stock checks; the diagnostic image's N4 |
| The delay from an interrupt's request to its handler follows the core's own rule | on the unit it varies with the loop position by up to five cycles in another pattern (M3 N3: a repeat of six where the core gives five); period and loop length agree | code that depends on the exact cycle of an interrupt |
| `EVTFLAG0`-`3` hold only events the models raise | the unit showed `0000011B`, `21000010`, `00000000`, `94000001` under the diagnostic image, here `0`, `00000010`, `0`, `0`; which are left by the boot loader is not known | code that polls event flags |
| Combined events 0 to 3 are never raised, and `EVTMASK` resets to all ones | the unit's `EVTFLAG0` had bits 0, 1 and 3 set with flags in groups 0, 1 and 3; TI's library masks every event before using the combiner | firmware that routes a combined event; no stock image in the checks does |
| NOR status register protection bits read 0 | the unit's device 0 reads `0C` (M1) | code that checks block protection |
| A pad's level is whatever the caller sets, in one step | on the unit an untouched pad reads 0 or 1; a soft hit peaked on its second sample (`02D3`) and was back at 0 after 15; a firm press was still rising after 24 (`0C55`) (M3 P3, 262 samples a second). Replayed into stock 3.2.174 here, the firm trace plays the drum and the soft one plays nothing; whether that soft tap sounds on the unit is not known | velocity taken from the shape of a hit |

Unexplained on the unit, and not modelled: one read-back of 4 in M1 (I6); the change of N4's
pattern after its first 32 interrupts (M3).
