# Liven line: static profile (8bit warps, XFM, Bass&Beats, Lofi-12, Mega Synthesis, Ambient Ø)

Static analysis of the ten Liven SysEx updates in `firmware/other/` (2026-11-23). Nothing here was run on a device.
Status words as in `docs/01-platform-map.md`: **simulated** = the routine was executed in `c6sim` and the
values read from the run; **read** = instructions read by hand at the address given; **matched** = `func_match`
paired the code (normalised body, constants hidden), values not compared; **inference** = reasoning beyond what
the code shows, marked as such. "Not found by this method" means a search that can miss things came back empty.

Session scripts named below without a path are in `analysis/other_products/liven/` (single-purpose and unmaintained;
its README lists their inputs); each fact also names the repository tool or the address to re-check it. Repo tools are run from the repo root with `python3 -B`. Addresses built from
MVK/MVKH pairs were computed as `((mvkh>>16)<<16)|(mvk&0xffff)` in code.

Reference releases (latest of each product, read in depth): 8bit warps 3.0.76, XFM 3.0.46, Bass&Beats 1.1.27,
Lofi-12 2.1.65, Mega Synthesis 1.1.37, Ambient Ø 1.5.45. Earlier releases (8bit 1.1.62, 2.0.67; XFM 2.0.43;
Lofi-12 2.0.55 = `LIVEN_LOFI_SYSTEM.syx`) appear as differences (section F). Internal code names, from the
application delegate class: 8bit warps `LizardDelegate` (+ `LizardTest`), XFM `BayfmDelegate`, Bass&Beats
`BumblebeeDelegate`, Lofi-12 / Mega / Ambient `MainDelegate` (+ `TestMode`).

## Summary

- One board design under all six products. Every image addresses the same peripheral set (UART0, I2C0, SPI1,
  McASP0, GPIO, PSC0/1, SYSCFG0/1, EDMA3 CC0, Timer0, INTC, cache; INT-16), and three independent simulations give
  the same values in all ten images: the pin multiplexing, the interrupt map, and the codec start-up (except one
  sample-rate register). The McASP set-up differs only in one clock divider.
- Two platform generations sit side by side: **48 kHz** (8bit warps, XFM, Lofi-12, Mega) and **32 kHz** (Bass&Beats,
  Ambient). The codec divider (register 2: fs(ref)/2 against /3), the McASP high-clock divider (÷8 against ÷12) and
  the DSP's float constants (48000.0f against 32000.0f) all agree (C.1).
- Unlike the SmplTrek family, the DSP is the I2S clock master (ACLKX/AFSX outputs, codec register 8 never written),
  audio uses McASP serialisers 0 (out) and 1 (in), the codec PLL is not used, and there is no USB, SD card, panel
  MCU, OLED or second UART. MIDI is DIN only on UART0 at 31250 baud.
- The app's SysEx handling is a backup/transfer protocol in the same framing as the firmware update:
  `F0 00 48 04 00 00 <product> 60 <cmd> <7-bit packed payload> F7`, commands 1 begin (kind, length), 2 data (≤210
  bytes), 3 end (CRC-32). The app ignores category 0x7F (the update), so updates are received by the bootloader
  only, which ships in no Liven file (E).
- Toolchain: TI CGT RTS in its pre-8.3.11 form (8.3.2-8.3.10 identical), SYS/BIOS kernel code byte-identical to
  6.76.03.01 rebuilt with that compiler (A.3). The SmplTrek family uses 8.3.11-8.3.13.

## A. Image

### A.1 Container and sections

`container.py` (unwraps with `tools/sonicware_integrity.py`, prints descriptors and partition tables) and
`analysis/mmtd2elf.py` (section table; logs in `*.elf.log`):

| Release | .syx bytes / messages | cmtd bytes | Images in the container | Entry | Code (`.text`) | Sections |
|---|---|---|---|---|---|---|
| 8bit 1.1.62 | 681499 / 2728 | 572437 | mmtd 1.1.62 | `0xC055E160` | `0xC04E3800`-`0xC0566640` (524 KiB) | 7 |
| 8bit 2.0.67 | 685022 / 2742 | 575397 | mmtd 2.0.67 | `0xC055ED20` | `0xC04E3800`-`0xC05671A0` | 7 |
| 8bit 3.0.76 | 1290867 / 5166 | 1084301 | **pmtd 2.0.7** (PMEM 27388 B, PPTN 435724 B) + mmtd 3.0.76 | `0xC056A0E0` | `0xC04E4800`-`0xC0572C60` (569 KiB) | 7 |
| XFM 2.0.43 | 1184504 / 4740 | 994961 | mmtd 2.0.43 | `0xC106DAE0` | `0xC0FDB800`-`0xC1077320` | 7 |
| XFM 3.0.46 | 1186376 / 4748 | 996529 | mmtd 3.0.46 | `0xC106E740` | `0xC0FDBC00`-`0xC1077DE0` (625 KiB) | 7 |
| Bass&Beats 1.1.27 | 1497830 / 5994 | 1258149 | mmtd 1.1.27 | `0xC141E180` | `0xC137CC00`-`0xC1427E00` (684 KiB) | 7 |
| Lofi-12 2.0.55 | 989463 / 3960 | 831125 | mmtd 2.0.55 | `0xC215F620` | `0xC20D3C00`-`0xC2168F60` | **6** |
| Lofi-12 2.1.65 | 1010637 / 4045 | 848909 | mmtd 2.1.65 | `0xC1F634C0` | `0xC1ED3800`-`0xC1F6CF60` (614 KiB) | **6** |
| Mega 1.1.37 | 838344 / 3356 | 704181 | mmtd 1.1.37 | `0xC2038E20` | `0xC1FA5000`-`0xC20435C0` (634 KiB) | 7 |
| Ambient 1.5.45 | 2073165 / 8295 | 1741433 | **pmtd 2.0.5** (PPT2 620828 B) + mmtd 1.5.45 | `0xC16B8100` | `0xC162CC00`-`0xC16C1140` (594 KiB) | 7 |

- The cmtd family word (header word 4, `+0x10`) equals the SysEx device byte in all ten (2, 3, 4, 7, 11, 13; INT-13).
- Section structure is the SmplTrek one (three small high sections, `.text`, a small section below `.text`,
  constants, data), except Lofi-12, which has no section below `.text` (6 sections). Constants are large in the
  products with built-in sound tables (XFM `0x558D1`, Bass&Beats `0x85D81`, Ambient `0x7B679` bytes) and small in
  8bit warps (`0x5C29`) and Mega (`0xBBE1`); Lofi-12's first section is 194 KiB of initialised data (`0x2F8A0`).
- Partition kinds only (contents not examined): 8bit warps 3.0.76 is the first 8bit release to carry a PRESET
  (`pmtd`) image; Ambient's has one partition `PPT2`. The other files carry the system image only. Every app reads
  a `pmtd` image from its own flash (string `pmtd` referenced by code in all ten; 8bit 3.0.76 reads its header at
  flash offset `0x240000`, `0xC051F114`, section C.6).
- B14 / boot stack (entry code, `b14.py`, `b14.txt`): 8bit 3.0.76 B14 `0xC057E530`, XFM 3.0.46
  `0xC10D1200`, Bass&Beats `0xC14AFE30`, Lofi-12 2.1.65 `0xC1FA4E00`, Mega `0xC2053200`, Ambient `0xC173E528`.
  Bass&Beats and Ambient start with the stack in L1D RAM (`0x11F03F9C`, `0x11F03E8C`); the others in DDR.

### A.2 Run-time memory (copy table)

`analysis/memory_map.py` (`*.memmap.txt`): `__TI_auto_init` uses `rle24` and `copy` handlers in all
ten (Bass&Beats, Lofi-12 2.1.65 and Mega list a third, unrecognised handler). Zero-filled DDR reaches
`0xC3FFFFF8` in 8bit warps (all three releases: `0xC1000000`-`0xC3FFFFF8`, 48 MiB) and `0xC4000000` in Bass&Beats
(`0xC1E00000`-`0xC4000000`), so those images assume at least 64 MiB of DDR; XFM and Lofi-12 claim nothing above
their image (about 17 and 32 MiB used), Ambient up to `0xC3000000`. L1D initialised data: 5.5 KiB (8bit) to 9.6 KiB.

### A.3 Toolchain and SYS/BIOS

- **RTS** (`analysis/lib_match.py` against `rts6740_elf.lib` of CGT 8.3.2, 8.3.9, 8.3.10, 8.3.13, 8.5.0;
  `rtsver.py`): in all ten images 8.3.2 = 8.3.9 = 8.3.10 give the most unique matches (e.g. 8bit 3.0.76:
  107 functions / 14692 bytes; 8.3.13: 102 / 10756; 8.5.0: 86), and the functions that only the older libraries
  match are `powf`, `tanf`, `__TI_readmsg` (all ten) plus `cot`, `cotl`, `cotf`, `__c6xabi_divlli` in some. No
  function matches only 8.3.13. So the Liven RTS is the pre-8.3.11 form; SmplTrek's is 8.3.11-8.3.13
  (the same method as LIB-2). 8.3.3-8.3.8 are not installed, so the lower bound is open.
- **SYS/BIOS**: no version string (only `xdc.runtime.Error.raise: terminating execution` and
  `xdc.runtime.Startup: 'maxPasses' exceeded`). The repo's `analysis/sysbios_match.cfg` built with
  SYS/BIOS 6.76.03.01 and **CGT 8.3.10** (`bios/`) gives 66 unique kernel matches in 8bit (all three), XFM
  (both), Lofi-12 (both) and Mega, and 77 in Bass&Beats and Ambient; the same library gives SmplTrek 3.2.174 only
  62 (69 with the 8.3.13 build, LIB-3). So the kernel is SYS/BIOS 6.76.03.01 code or a release with identical
  code, compiled with the older CGT; other SYS/BIOS releases were not tried.
- All ten are configured for the DA850 device class (INT-17) and need no peripheral the C6742 lacks (INT-16):
  the firmware cannot name the part.

## B. SYS/BIOS static configuration

### B.1 Tasks

`analysis/init_data.py --tasks --b14` (`*.tasks.txt`) and the priority set-up read at each
`task_handler_set` call (`analysis/packets.py --calls`; `task_handler_set`/`task_handler_bind` carried from
SmplTrek by `func_match`, hash and calls passes, `*.carried.txt`). Every task has a 2 KiB stack and the
common `task_handler_entry` fxn, mode 4 (inactive), priority -1 until the app sets it, except one static task at
priority 1 and Idle at 0.

| Handler | Priority | Set at (8bit 3.0.76) | Other products |
|---|---|---|---|
| `HAL::FlashMemoryDriver` | 14 (constant in the callee) | `0xC0525E18` | same in all ten |
| `MIDI::MIDIStreamUART` | 13 | `0xC0537BD4` | same |
| `IOObserver` (object `0xC04E4518`) | 13 | `0xC055D498` | same |
| `AsyncTaskHandler` (object `0xC04E467C`) | 7 | `0xC05687AC` | same |
| `ResourceLoader` | 1 | — (class absent) | Lofi-12 `0xC1F49F02`, Mega `0xC2020FCA`, Bass&Beats `0xC13EF0A0`; Ambient passes a variable (A10, `0xC1698DE0`) |
| static task, bound in `application_run` (`0xC056CE10`, no set call) | 1 | | same pattern |
| Idle | 0 | | |

Task objects: 6 in 8bit and XFM, 7 in Lofi-12, Mega and Ambient. Bass&Beats has 6 static objects although it
starts a ResourceLoader too (its vtable is stored at `0xC13EEF8C`, in the same function as the set call); that
task's handle comes from a call (`0xC140CDD0` / `0xC14147C8`), not read further. There is no panel, USB, graphics or LED task. The four platform tasks have SmplTrek 3.2.174's priorities (14, 13,
13, 7), one above Lofi-12 XT and CyDrums; the static main task runs at 1 here against 3 in the SmplTrek family.

### B.2 Interrupts, Swis, clock

- **Hwi map, simulated** (`hwisim.py`: runs the SYS/BIOS INTMUX writer, e.g. 8bit 3.0.76 `0xC0562778`,
  with the copy table applied): identical in all ten. INTSEL 4 = 36 (I2C0), 5 = 8 (EDMA3 CC0 completion),
  6 = 61 (McASP0), 7 = 75 (GPIO bank 8), 8 = 38 (UART0), 14 = 4 (Timer64P0 TINT12), the rest 0; IER `0x41F3`
  (NMI, interrupts 4-8, 14). Event names per StarterWare `interrupt.h`.
- **Hwi objects** (`hwiobj.py`: module state found by its INTMUX1 value, dispatch table at +44): handlers in
  8bit 3.0.76: int 4 `0xC0549E00`, int 5 `0xC0563F10` (= `edma3_completion_isr`, hash-matched), int 6
  `0xC052BDD0`, int 7 `0xC05552CC`, int 8 `0xC0530F00`, int 14 `0xC056C600`; per-image addresses in the script
  output. The GPIO bank 8 handler (read) tests one pin whose number is a run-time global (B14+28), clears it and
  calls a delegate through the object at `0xC04E4684`; its role is not settled.
- A second INTMUX writer exists inside a large function of the test-mode code (8bit `0xC053C0AC`, in the
  `LizardTest` area); not simulated.
- **Swis**: `Swi_post` (hash-matched) has exactly two call sites in each image: the clock function and the audio
  block ISR (8bit 3.0.76 `0xC056C650`, `0xC052B960`), the same two-Swi design as SmplTrek.
- **Clock**: a timer object with period 1000, periodType 0 (µs), intNum 14 exists in all ten (8bit 3.0.76
  `0xC057B530`, fxn `0xC056C600`), the same shape as SmplTrek's `g_clock_timer_period`: a 1 ms tick (probable,
  field layout as in platform-map "Clock tick").

## C. Hardware use

### C.1 Audio

Board-level set-up, 8bit 3.0.76 `0xC052C300` (read): PSC enables (PSC1 module 7, PSC0 modules 0 and 1),
`EDMA3Init`, `edma3_callback_register`, I2C slave address **0x18** (`0xC054A174(0x01C22000, 24)` at
`0xC052C3B8`), then the codec start-up `0xC052C06C`, McASP set-up `0xC052C0D8`, transfer start `0xC052C24C`.

**Codec, simulated** (`codec_sim.py`: runs the codec start-up with `codec_write` hooked; outputs
`*.codec.txt`, decoded with `analysis/codec_map.decode`). `codec_write` here takes (I2C base, register
B4, value A6) like SmplTrek's and stores the pair before an I2C send (`0xC0549FC8`, read). 42 writes, identical
in all ten except register 2:

- reset (reg 1 = 0x80); reg 9 = 0x30 (I2S, 32-bit words), reg 10 = 0;
- **reg 2 = 0x22** (ADC and DAC at fs(ref)/2) in 8bit, XFM, Lofi-12, Mega; **0x44** (fs(ref)/3) in Bass&Beats and
  Ambient; reg 7 = 0x0A;
- ADC programmable high-pass coefficients (page 1, regs 65-76), reg 107 = 0xC0, reg 12 = 0x50; LINE1L/LINE1R to
  the left/right ADC at 0 dB (regs 19, 22 = 0x04), MIC3 not connected; DACs routed to HPLOUT/HPLCOM/HPRCOM and
  both line outputs at 0 dB (regs 37-93).
- Not written: reg 8 (so BCLK/WCLK are inputs: the codec is a clock slave), regs 3-6 and 11 (PLL off). Every
  register used is in the AIC310x map, and the slave address is 0x18: the same codec family as SmplTrek
  (probable; same identification argument as `symbols` `codec_write`).

**McASP0** (read, StarterWare McASP driver hash-matched; all ten checked at the call sites with
`packets.py --calls`): I2S, two 32-bit slots, DMA port (`McASP{Rx,Tx}FmtI2SSet(32, 32, 0)`); TX frame sync
internal, rising edge (`McASPTxFrameSyncCfg(2, 16, 2)`), RX frame sync external with TX/RX clocks synchronised;
`McASPTxClkCfg(MCASP_TX_CLK_INTERNAL 0x8020, CLKXDIV 0, HCLKXDIV n)` with **n = 7 (÷8)** in 8bit, XFM, Lofi-12,
Mega and **n = 11 (÷12)** in Bass&Beats and Ambient; serialiser 0 transmit, 1 receive; PDIR outputs
`0x14000001` (AXR0, ACLKX, AFSX), inputs `0xA0000002` (AXR1, ACLKR, AFSR). So the DSP generates bit and frame
clock (64 bit clocks per frame): fs = AUXCLK / 512 or / 768.

**Sample rate.** Float constants built in code (`consts.py` census, `*.consts.json`): 48000.0f is the
dominant rate constant in 8bit (41 sites in 3.0.76), XFM (26), Lofi-12 (80 in 2.1.65), Mega (14) with 1/48000
(4-12 sites); Bass&Beats and Ambient have 32000.0f (25 and 29 sites) and 1/32000 (9 and 5) instead. The three
independent ratios agree (codec /2 against /3, McASP ÷8 against ÷12, 48000 against 32000): **48 kHz** in the first
group and **32 kHz** in Bass&Beats and Ambient, if AUXCLK and the codec's master clock are both 24.576 MHz (then
fs(ref) = MCLK / (128 × Q) with the reset Q = 2 is 96 kHz). That clock value is an inference: no code names it.

**Block size** (EDMA PaRAM templates, read with `init_data.py`, source/destination `0x01D02000` = McASP0 DMA port):
8bit warps BCNT 128 four-byte words = **64 stereo frames** per block (1.33 ms at 48 kHz), buffers
`0x11F00000`/`0x200`/`0x400`/`0x600` (templates 3.0.76 `0xC0576924`-`0xC057698C`); XFM, Lofi-12, Mega BCNT 256 =
**128 frames** (2.67 ms), Bass&Beats and Ambient 128 frames at 32 kHz (4 ms), buffers `0x11F00000`-`0x11F00C00`.
Link fields differ between the two generations (`0x4800`-`0x4860` against `0x4F80`-`0x4FE0`).

### C.2 Pins (simulated)

`pinmux.py` runs every function that addresses SYSCFG0/1, SPI1 or UART0 in isolation (no arguments) and
logs the register writes; `pmdecode.py` names each 4-bit field from StarterWare's
`hw_syscfg0_C6748.h`. Identical in all ten (`*.pinmux.dec`):

- McASP0: ACLKX0, AFSX0, AHCLKX0, AMUTE0, AXR0_0, AXR0_1
- UART0 RXD/TXD; I2C0 SCL/SDA
- SPI1: CLK, SIMO0, SOMI0, **SCS0 only**, ENA
- GPIO: GP0[0-3], GP1[8, 10-15], GP2[0-1], GP3[8, 10, 15], **GP4, GP5, GP6 all 16 pins**, GP8[8, 9, 15]
- SYSCFG0 KICK0/1 unlock; SYSCFG1 `+0xC` (PUPD_ENA) written 0.

Limit: helpers that take arguments run with zeros, so a branch-dependent write can be missed (one helper with seven
PINMUX12 sites logged one write).

### C.3 Panel input and LEDs

- No panel MCU (INT-14): the scans are DSP code. `KeyboardScan`, `ControlSwitchScan` and `DynamicLightingScan`
  derive from `Foundation::DynamicScan`; the first slots of `KeyboardScan` and `DynamicLightingScan` (8bit 3.0.76
  `0xC056AA00`, `0xC0568A60`, read; `ControlSwitchScan`'s not read) enable PSC1 module 3 (GPIO) and drive GPIO
  through the `gpio_write`/`gpio_read` helpers. With 48 GPIO pins of banks 4-6
  muxed as GPIO (C.2) this is a matrix scan of keys, switches and LEDs (inference from the pin count).
- `IOObserver` (task, priority 13) reads GPIO bank 2 (`gpio_read_bank16(2)`, 8bit `0xC055D634`) (inference:
  the encoder input, `RotaryEncoderDelegate`).
- Pots: `VRReaderDelegate`, `VRMedianFilter`, `VRFluctuationFilter`, `HAL::ADHandlerComponent` and
  `HAL::PowerLevelChecker<int, 3>` (battery, base `ADHandlerComponent`) exist in all ten, but **no ADC was found by
  this method**: the C674x has none, SPI1 has one chip select and its only delegate is the flash driver, and no
  other converter peripheral is addressed. How the analogue values reach the DSP is open.
- `TempoLED` drives an LED from a `Foundation::PWMEvent` (lambda class names, all ten).

### C.4 Display

No display driver class (no OLED, LCD, Graphics class in any image; `*.classes.txt`). The UI strings are
four characters with dots folded in (`BT.LO`, `D.ERR`, `R.DLY`, `P.OFF`, `RX.CH`, `LVN.8`), the vocabulary of a
four-digit segment LED display (inference; the segment font and digit drive were not located). Longer strings
(`SAMPLERATE CRUSHER`, `REVERSE DELAY`) also exist; their consumer was not traced.

### C.5 MIDI

DIN only: `MIDI::MIDIStreamUART` over `HAL::UARTDriver` on UART0 (the only UART addressed, pinmuxed and
interrupt-mapped). The MIDI stream set-up passes 31250 (`mvk 31250,b4`, one site in each image; 8bit 3.0.76
`0xC0537C0C`). Menu strings include `RX.CH`, `TX.CK`, `TX.PC`, `RX.PC`, `TX.CC`, `M.CMD`, `M.OUT`, `THRU`.
No USB: no USB0 address, no USB class, no USB interrupt (all ten).

### C.6 Storage

SPI NOR flash only (no MMC/SD address, no FatFs, no card class). `HAL::FlashMemoryDriver` runs as a task on SPI1.
Traced in 8bit 3.0.76:
- PRESET image: `0xC051F114` reads 44 bytes at flash `0x240000` (a pmtd header plus one partition entry), compares
  the tag `pmtd`, then looks up `PMEM` and `PPTN` (strings referenced at `0xC051F214`-`0xC051F288`).
- Backup data: `BackupHandler::vfunc_0` (`0xC0529BE8`) reads flash `0x640000` into the kind-4 buffer before export.
- Further flash-sized constants (`0x641000`, `0x651000`, `0x671000`) are built in code but not traced
  (`flashrefs.py`). Other products use different offsets (XFM up to `0x661000`; Bass&Beats up to
  `0xE7F000`, which would need at least a 16 MiB part; Ambient up to `0xD80000`); none traced.
- Settings and data are tagged: `PREF` in all six products, plus four-letter tags (8bit: `ACOE`, `APOF`, `BTYP`,
  `SCHM`, `CSRC`, `MCMD`, `MRCH`, `PTRN`, `LVSQ`, `SEQN`, `SPL8`, `L8PM`, `L8WD`, `WAV8`, ...); layout not decoded.

### C.7 Power and battery

`BatteryLevelChecker`, `HAL::PowerLevelChecker<int, 3>`, `PowerManagerDelegate` in all ten; UI strings `BATT`,
`ALKL`, `NIMH`, `LTHM` (battery type), `BT.LO`, `P.OFF` (auto power-off; tag `APOF`). The battery measurement path
shares the open ADC question (C.3).

## D. Application

Class counts (RTTI, `*.classes.txt`): 8bit 146/146/153, XFM 153/151, Bass&Beats 169, Lofi-12 165/167,
Mega 178, Ambient 165. 79 non-library classes are common to all six latest releases (platform: HAL, MIDI,
Sequencer, Menu framework, `BackupHandler`, `DataExport`, `FactoryResetHandler`, base oscillators, voice
assigners, `SoundEffect::OverDrive`, `SamplerateCrusher`). Product-only classes (absent from the other five):

Classes found in that product only (the other five latest releases lack them), then notable classes shared
with some but not all products (`*.classes.txt`):

| Product | Only here | Shared with some others |
|---|---|---|
| 8bit warps | `SoundOSC::OSCGenerator<float, 4, 0..4>` and `OSCObject<float, 4, 0..4, 6>` (five generator kinds), `Envelope::EnvelopeGenerator`/`EnvelopeObject`/`TypeGenerator`, `Modulation::PropertyEditor`, `Looper::LooperEngineDelgate`, `AutoWah`, `Phaser`, `Tempo::BPMSyncSource`, `WaveCapture`, `WaveEdit`, `WaveEditor` (`NormalEditor`, `SimpleEditor`), `WaveCopy`, `WaveSave`, `WaveExport` | `CassetteTape` (Lofi), `Infinity`, `Tunnel` (Lofi, Ambient), `StereoDigialDelay` (XFM, BnB, Mega) |
| XFM | `FMSynthesisGenerator<float, 1/2, 4>`, `FMSingleGenerator`, `FMEditGenerator`, `FMAttackProcess`, `FMMorphProcess`, `FMWarpProcess` (UI `WARP`, `FM`, `MRPH`, `ATK`), `SoundCapture` | `SoundExport` (BnB), `Isolator` |
| Bass&Beats | `OSCDrumInst`, `OSCDrumInstGenerator`, `OSCWaveTableSynthBass`, `DrumKitDelegate`, `WaveTableSynthDelegate`, `Compressor`, `DrumEffect`, `DrumKit*` (Edit, Load, Save, Select, Export, BankSave), `WaveTableBankSave`, `WaveTableSampleSave` | `WaveTableTransfer` (Ambient), `ResourceLoader` |
| Lofi-12 | `AnalogRecord`, `HiGain`, `OSCObject<float, 0, 1/2, 10>`, `VoiceAssignerChopMono`, `EditedSampleSelect` | `SampleEdit`, `BankExport`, `RackComp`, `HoldDelay`, `VoiceAssignerChop` (Mega), `QuickSampling` (Mega, Ambient), `CassetteTape` (8bit) |
| Mega | `SampleBoySynthesisCore/Generator<float, 1/2>`, `VoiceAssigner`, `VoiceAssignerFM`, `VoiceAssignerPCM`, `VoiceAssignerDCSG`, `VoiceAssignerShot`, `FMSound*` (Load, Save, Export), `FMBank*`, `SampleImport`, `ImportedSampleSave` | `SampleEdit`, `BankExport`, `RackComp`, `HoldDelay` (Lofi) |
| Ambient Ø | `SignalGenerator`, `SingleSignalGenerator`, `StreamSignalGenerator`, `RampPlus`/`RampMinus`, `VoiceAssignerUnison`, `HallHi/Mid/Low`, `RoomHi/Mid/Low`, `DriveEffect`, `Chorus`, `WaveTable*` and `Noise*` (Select, Import, Export, Rename), `SoundEngine::TuneAllDelegate`, `SoundOSC::LoadSampleDelegate` | `WaveTableTransfer` (BnB), `QuickSampling`, `TiltFilter` |

Every product has a step sequencer (`Sequencer::SequencerPlayer`, `ArpeggiatorPlayer`, `Metronome`,
`SequencerPrecount`), MIDI sync (`SyncClockGenerator/ReceiverDelegate`, UI `SYNC`, `S.I.PO`, `S.O.PO`), a test mode
(`LizardTest` / `TestMode`, UI `TEST`) and a factory reset (`F.RST`). Menu strings of 8bit 3.0.76 (short UI
strings, `LIVEN_8SYSTEM_3_0_76.ui.txt`) include oscillator shapes (`SINE`, `SAW`, `R.SAW`, `TRI`, `SQAR`,
`LOG`, `R.LOG`, `RAND`), voice modes (`POLY`, `MONO`, `ARP`, `P+M`), filter types (`LPF`, `BPF`, `HPF`), effect
names (`TAPE`, `INF`, `TNNL`, `PLAT`, `ARNA`, `ROOM`, `HALL`, `R.DLY`, `A.WAH`, `R.MOD`, `TRML`, `PHSR`, `DIST`, `CRSH`,
`DLY`, `FLNG`, `CHRS`), sequencer (`QNTZ`, `LEN`, `TRPS`, `MTRO`, `P.CNT`, step lengths `1/32`-`1/1`).

## E. SysEx protocol (backup, transfer) and the update path

Read in 8bit 3.0.76; the transport functions are hash-matched (normalised bodies identical) in all ten images by
`func_match` from 8bit 3.0.76 with my names (`liven8-3.0.76.syms.json`, results `l8-*.fm.json`).
Per-product values (header byte, accepted kind) were read in each image.

**Message framing.** `F0 00 48 04 00 00 <dev> <cat> <cmd> <payload, 7-bit packed> F7`, the update's framing. The
7-byte header template is stored twice in each image (8bit 3.0.76 `0xC0578518` receive, `0xC0578520` send) and its
device byte is the product number: 2 (8bit, all three), 3 (XFM), 4 (Bass&Beats), 7 (Lofi-12), 11 (Mega), 13
(Ambient). Packing (`pack7` `0xC0555360`, `unpack7` `0xC0550720`, read): groups of seven bytes behind one byte that
holds their top bits, bit 6 for the first, as `sonicware_integrity.unpack7`.

**Receive.** `MIDIStreamUART::parse` delivers SysEx to `MIDIInputPortDelegate` slot 7 in chunks with a flag
(0 whole, 1 first, 2 middle, 3 last; platform-map "MIDI receive"). Two delegates forward it:
- `BackupHandler` slot 7 (thunk `0xC052A3B8` → `0xC052A360`, `receiveSystemExclusiveMessage`, name from the lambda
  type name) builds a `std::function` and calls `sysex_rx_feed` `0xC05507E8` on the shared receiver object
  `0xC04E4568`;
- the app delegate's slot (`LizardDelegate::vfunc_31` `0xC0502A00`) calls the same feed with a plain callback
  `0xC0544BEC`.
`sysex_rx_feed` (jump table `0xC057E320` on the flag) compares the first seven bytes with the header template,
keeps byte 7 (category) and byte 8 (command), unpacks the rest into `0xC04E2DD0`, and at the end calls the callback
with (category, command, data, length). **Both callbacks return unless category = 0x60** (`mvk 96`: BackupHandler
lambda target `0xC052A080`, main callback `0xC0544BEC`). (The app-delegate callback was read in 8bit 3.0.76 only; in the other images the BackupHandler and WaveTableTransfer callbacks were checked, `sysexlam.py`.) No third caller of the feed was found (code references to
`0xC04E4568`: `0xC0502A40`, `0xC052A38C`, `0xC0544A54`, the last a reset).

**Commands (category 0x60).**

| cmd | Payload (raw) | Receiver (BackupHandler, `0xC052A080`) | Sender |
|---|---|---|---|
| 1 begin | 8 bytes: u32 kind, u32 total length | stores both (`0xC057B9C8`); kind ≠ expected → `D.ERR` | `0xC054ED10` (8 bytes from the export header) |
| 2 data | up to 210 bytes | copies to the kind's buffer at the running offset (B14+16), shows 100 × offset / total | `0xC054EB88`, driven by `DataExport` slot 0 `0xC054EB98`, chunk = min(210, remaining) |
| 3 end | u32 CRC | recomputes and compares; equal → save, else `D.ERR` | `0xC054EB70` |

- CRC: `crc32_update` `0xC0565DE0` is a bitwise reflected CRC-32 (polynomial `0xEDB88320`, inverted in and out:
  zlib's `crc32`). The sender seeds it with the CRC of a 4-byte per-kind constant (`kind_magic` `0xC0544A6C`,
  kinds 0-4, a switch of 32-bit constants) and continues over the data; the receiver does the same.
- 210 raw bytes pack to 240, so a data message is 250 bytes: the same chunk size as the firmware update.
- Accepted backup kind (begin check) per product: 8bit 4; XFM 3; Lofi-12 1; Mega 3; Bass&Beats 6; Ambient 1, 3 or
  6, chosen from a BackupHandler field (`0xC167BA00`: +24 = 1 → 1, = 2 → 3, else 6). `WaveTableTransfer`
  (Bass&Beats, Ambient) has its own handler with kind 7 (`sysexlam.py`).
- 8bit 3.0.76 kind 4 lives at `0xC04CB848` (`kind_buffer` `0xC0544E14`) and is read from flash `0x640000` before an
  export (C.6).

**Firmware update.** The update uses category 0x7F (INT-13). The app's only SysEx consumers drop every category but
0x60, so **the app does not receive firmware updates** (fully shown for 8bit 3.0.76); that is the bootloader's job, and no Liven file carries a
bootloader image (INT-14). How the unit enters the bootloader (key combination at power-on, say) is not in the app
code read here.

## F. Release history

Function-level match between consecutive releases (`func_match`, `l8a.fm.txt`, `l8-LIVEN_8SYSTEM_2_0_67`,
`xfm.fm.txt`, `lofi.fm.txt`): 8bit 1.1.62 → 2.0.67 94% of functions matched, 2.0.67 → 3.0.76 88%, XFM 2.0.43 →
3.0.46 96%, Lofi-12 2.0.55 → 2.1.65 90%. The platform parts simulated above (codec writes, pinmux, Hwi map,
McASP dividers, PaRAM shapes, task priorities) are identical between releases of each product.

- **8bit 1.1.62 → 2.0.67**: same class set; new menu strings `PC.CH`, `TX.PC`, `MPCH`, `MRPC`, `CNTR`, `ADSR`
  (program-change and MIDI settings).
- **8bit 2.0.67 → 3.0.76**: six effect classes added (`AutoWah`, `OverDrive`, `Phaser`, `ReverseDelay`,
  `RingModulator`, `Tremolo`; UI `A.WAH`, `DIST`, `PHSR`, `R.DLY`, `R.MOD`, `TRML`), `RX.PC`, `CN.LP`, `LOOP`,
  `SCHM`; `ADSR`, `PC.CH`, `TX.CH` dropped; code grew 42 KiB; and the update now carries a PRESET image (PMEM, PPTN).
- **XFM 2.0.43 → 3.0.46**: same class set; strings ` SPK`, `CN.LP`, `LOOP`, `SCHM`, class name `EditedSoundSelect`
  (string only) added.
- **Lofi-12 2.0.55 → 2.1.65**: `SoundEffect::HiGain` added; strings `NGEN`, `NS.GT`, `S.MAX`, `CN.LP`, `LOOP`,
  `SCHM`.
- `CN.LP`, `LOOP` and `SCHM` arrive in the latest release of 8bit, XFM and Lofi-12 and are present in Bass&Beats,
  Mega and Ambient: a shared feature added across the line (meaning not read).

## G. Relation to SmplTrek and between the Liven products

- **Shared with SmplTrek 3.2.174**: 55-68 class names per product (SmplTrek RTTI `work/smpltrek-3.2.174.rtti.json`);
  `func_match` from SmplTrek pairs 479-612 of its functions (5-7%; `*.fm.txt`): TI drivers (StarterWare
  EDMA3, McASP, GPIO, I2C, UART), SYS/BIOS, the task framework (`task_handler_set/bind`,
  `async_task_handler_start`), `MIDIStreamUART`, `MIDIInputPort::handle_channel_message`, `FlashMemoryDriver`
  helpers, and the codec functions (`codec_reset` hash-matched; `codec_write`, `codec_set_audio_interface`,
  `codec_input_init` carried by the calls pass at low similarity and not relied on; `codec_set_sample_rate` is a
  different, fixed-divider body here). Hardware differences from the SmplTrek board: DSP is the I2S master (SmplTrek:
  codec master, PLL from 24.576 MHz MCLK), serialisers 0/1 (SmplTrek AXR13 out / AXR14 in), no UART1, MMC/SD, USB,
  panel MCU or OLED; same codec family at the same I2C address.
- **Between Liven products**: `func_match` from 8bit 3.0.76 pairs 31-37% of its functions in the other five
  (`l8-*.fm.txt`), against 84-88% for its own earlier releases. The six apps are one codebase with a
  product-specific sound engine and data menus (section D).
- **Two platform generations**, by every simulated or read hardware value: (a) 8bit warps, XFM, Lofi-12, Mega:
  48 kHz, boot stack in DDR, SYS/BIOS match 66; (b) Bass&Beats, Ambient: 32 kHz, boot stack in L1D, SYS/BIOS match
  77, code-built Timer64P0 TCR/TGCR accesses (`+0x20`, `+0x24`; also in Mega, which is otherwise group a).
  8bit warps alone uses a 64-frame block.

## Open

- How pots and battery voltage are converted (C.3): no ADC peripheral or SPI chip select found.
- Role of the GPIO bank 8 interrupt pin (B.2) and of the second INTMUX writer.
- Flash layout beyond the two traced reads; settings (`PREF`) record layout; meaning of the per-kind constants.
- The absolute sample rate rests on an assumed 24.576 MHz clock.
- The display driver and segment font were not located.
- `CN.LP` / `LOOP` / `SCHM` feature meaning.

## Tool notes

- `hw_inventory.py` lists two "unknown" peripherals, `0x01B77000+0x400` and `0x01E84000+0x800`: they are the
  integers 28,800,000 and 32,000,000 built in code (8bit `0xC0565EEC`, `0xC0553680`), not addresses.
- `region_diff.py` and `codec_map.py` are fixed to SmplTrek / Lofi-12 XT / CyDrums, so Liven comparisons used
  `func_match` plus the simulation harnesses here.
- `func_match.py --symbols` raises `KeyError: 'prefix'` for symbol entries without a `prefix` field.
- `init_data.py --tasks` reports a false Task record in Bass&Beats (`0xC14AE708`, priority -1052068944).
- `string_refs.Image.data_words` scans loaded sections only, so values that live in copy-table data (Hwi module
  state, task objects) need `init_data`.
- `mmtd2elf.py`'s help names only .zip/.bin inputs; .syx works.
