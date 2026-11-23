# Static profile: ELZ_1 play (1.1.62, 2.0.109, 3.1.149) and deconstruct MINIMAL (1.0.58)

Written 2026-11-23 (static only, no device). Session scripts named below are in
`analysis/other_products/elzplay/` (single-purpose and unmaintained; its README lists their inputs); each fact also
names the repository tool or the address to re-check it.
Addresses are per image; never reuse one across images. "Not found by this method" means the named
scan didn't find it, not that it is absent. Status words follow claims.json: observed-file (parsed or read
directly), inferred-static (read from disassembly, with interpretation).

Session scripts used: `container.py` (cmtd/pmtd/mmtd descriptor dump),
`callargs.py` (constant arguments at every call to a target, built on `packets.py --calls`), `rdiff.py`
(`region_diff.py` with PRODUCTS swapped to ELZ_1 play 3.1.149 and MINIMAL), `hwi.py` (SYS/BIOS Hwi module
state via `init_data.InitData`), `constscan.py` (MVK/MVKH pairs, combined in code as
`((mvkh>>16)<<16)|(mvk&0xffff)`), `ifdesc.py` (USB descriptors in initialised data), `ndiff.py`.

---------------------------------------------------------------------------------------------------------

## ELZ_1 play 3.1.149 (latest)

### A. Image

`elzplay/container.py` on `firmware/other/ELZ_1_play_V3_1_149.zip`; `mmtd2elf.py` for sections.

- Container: `cmtd`, 10,523,193 bytes, product word (+0x10) = 8, 2 images.
  - `pmtd` v3.1.26, 0x64ECB8 bytes, 8 partitions. Each 12-byte entry is (tag, flash address, size):
    PPM1 0x8C3000/0x1C2F8, PPM2 0x8E0000/0x1B09C, PWD8 0x8FC000/0xC7C, PWDG 0x8FD000/0x7530C,
    PWDD 0x973000/0x20700, PPTN 0x994000/0x3ED8, PDPT 0x998000/0x677A8, PKIT 0xA00000/0x515B9C.
    (Content not examined; kinds/sizes only.)
  - `mmtd` v3.1.149, 0x3BA539 bytes, entry `0xC28B0500`, 7 sections:
    `0xC29C6600`-`0xC29DCC08`, `0xC29C5C60`-`0xC29C60E0`, `0xC29C6400`-`0xC29C6600` (ISTP points here),
    code `0xC25C9800`-`0xC28CD300` (3.01 MiB), `0xC25C95E8`-`0xC25C9800`, constants `0xC28CD300`-`0xC29697E9`,
    `0xC29C003C`-`0xC29C3674`. Same seven-section shape as the SmplTrek family (platform-map "Image layout").
- B14 = `0xC29C5678` (MVKL/MVKH to B14 in `_c_int00`, `ELZ_1_play_V3_1_149.dis`).
- `__TI_auto_init` `0xC2899B00`, copy-table records `0xC29DCB80`-`0xC29DCC08` (`memory_map.py`).
  Zero-filled DDR from `0xC0000000` to `0xC25C62B4`; unclaimed after the image to `0xC2E00000`
  (`memory_map.py`, not proven free).
- Toolchain: `lib_match.py` against rts6740_elf.lib of each installed CGT: 8.3.2 111 unique, 8.3.9 112,
  8.3.10 112, 8.3.11 120, 8.3.12 120, 8.3.13 119, 8.5.0 92 (`lib-ELZ_1_play_V3_1_149-*.json`). Same band
  as SmplTrek (LIB-2: CGT 8.3.11-8.3.13). xdc.runtime and boot from bios_6_76_03_01: 44 unique matches,
  as SmplTrek. The SYS/BIOS kernel library match (LIB-3) was not rerun: the custom-built sysbios.ae674 it
  used is no longer on disk.

### B. SYS/BIOS static configuration

- Static tasks: `python3 -B analysis/init_data.py firmware/other/ELZ_1_play_V3_1_149.zip --tasks --b14 0xc29c5678`
  (`tasks-elz3.txt`): 12 Task objects from `0xC29B0C20`. All use the same fxn `0xC28A85C0`
  (TaskHandler entry), except Idle (`0xC28CCDE0`, priority 0). Stack sizes: 64 KiB x 2, 8 KiB x 3,
  4 KiB x 1, 2 KiB x 6. The main task (handle B14+1296, 64 KiB) is static at priority 3, as in SmplTrek.
- Priorities read at `task_handler_set` (`0xC28A8638`, carried name; it is called right after
  `task_handler_bind` `0xC28A8650` with the same object, checked at `0xC28A8580`/`0xC28A858C`):
  AsyncTaskHandler 7 (`0xC28A8590`, B14+1280, 64 KiB); USBTaskHandler 14 (`0xC28C0458`, inside carried
  `usb_task_start` `0xC28C0440`, B14+1312, 8 KiB, where SmplTrek's USB stack is 2 KiB); 11 at `0xC279730C`
  (in the HAL::FlashMemoryDriver code range); 10 at `0xC285DA74` (MIDIStreamUART range). The other
  priorities are passed in registers and were not traced.
- No ADControllerUART task: the class is not in the RTTI (`../other/ELZ_1_play_V3_1_149.rtti.json`).
- Hwis (`hwi.py ... 0xC29C60E0`; module state found from `Hwi_Module_startup` `0xC289E060`, which
  loads `0xC29C60E0` and ISTP from +32 = `0xC29C6400`):

  | Int | Event | Source (StarterWare interrupt.h) | handler |
  |---|---|---|---|
  | 4 | 36 | I2C0 | `0xC27D9004` |
  | 5 | 8 | EDMA3 CC0 completion | `0xC28A1D30` (carried `edma3_completion_isr`) |
  | 6 | 61 | McASP0 | `0xC27D1E10` |
  | 8 | 75 | GPIO bank 8 | `0xC287756C` (SD card detect, see C) |
  | 9 | 38 | UART0 | `0xC27E78D8` |
  | 11 | 15 | MMCSD0 | `0xC286FB6C` (carried `mmcsd0_isr`) |
  | 12 | 19 | USB0 | `0xC289E678` |
  | 14 | 4 | Timer64P0 TINT12 | `0xC28B5060` (clock tick) |

  SmplTrek's int 7 (GPIO bank 7) and int 9 (UART1, the panel MCU) have no counterpart; there is no UART1
  interrupt. The handler is taken as the first code pointer in each handle's object (layout as
  platform-map "Interrupts and Swis"); probable.
- Clock tick: Timer64P0 on int 14, as SmplTrek; the period word was not read.

### C. Hardware use

**Peripheral census and part** (`hw_inventory.py ... --symbols symbols/elz-3.1.149.json`,
`hw-elz3.txt`): INTC, cache, EDMA3 CC0 and **CC1**, PSC0/1, SYSCFG0/1, TIMER64P0/1/**P2**, I2C0/1,
MMCSD0, SPI0/1, UART0-2 (one instance-to-base helper `0xC2892434`), McASP0, USB0, **LCDC**, GPIO,
**eHRPWM1** (`0x01F02000`, 14 sites in `0xC2897A00`/`0xC2897A4C`), DDR2 control. Parts with every peripheral:
C6748 only (INT-16 already records this). SmplTrek 3.2.174's census (`hw_inventory.py "firmware/smpltrek/SmplTrek
v3.2.174.zip"`, run this session) has no EDMA3 CC1, TIMER64P2, eHRPWM or LCDC; platform-map ("SYNC, MIDI, USB,
power, other buses") says the same for TIMER64P2 across the family.

**Clock assumption differs from SmplTrek.** Every module-clock constant in ELZ_1 play is 228,000,000
(`0x0D970100`; 6 sites: LCD `0xC27C3B68`, SD `0xC2829E10`/`0xC2829FA4`, SPI `0xC2869E30`, `0xC28922A8`,
`0xC2897A8C`); SmplTrek 3.2.174 uses 186,000,000 (`0x0B162280`, 4 sites, none of 228 MHz)
(`constscan.py`). On the C6748, SYSCLK2 is SYSCLK1/2, so the app is written for a 456 MHz CPU
where SmplTrek's bootloader sets 372 MHz (04-hardware-access.md). Inference: a different bootloader PLL
setting, so a different board or at least a different clock plan. Same in 1.1.62 and 2.0.109 (6 sites each).

**Display: LCD controller in LIDD mode, not raster** (`Graphics::LCDDriver`, vtable `0xC295F4D8`;
slot 0 `0xC27C3B00` is the init; read with `packets.py ... 0xc27c3b00 --count 7`). The LCDC calls are
StarterWare `lidd.c`/`raster.c` functions matched by body (register offsets against `hw_lcdc.h`):
- PSC1 module 16 on (`0xC27C3B20` -> `0xC2899F80`, INT-16).
- GP8[14] output (`0xC27C3B40`: GPIODirModeSet wrapper `0xC2899E30(143, 0)`; StarterWare pin numbers are
  1-based, 143 = GP8[14]). `0xC27C3AC0(x)` writes GP8[14] = !x: driven low at `0xC27C3B48`, high after a
  10-tick wait (`0xC27C3BC0`/`0xC27C3BC8`). Inference: the panel's reset line.
- `LIDDClkConfig(0x01E13000, 15,000,000, 228,000,000)` at `0xC27C3B64` (`0xC2892240`, divu then
  LCD_CTRL bits 15:8): CLKDIV 15, so the LIDD clock is 15.2 MHz.
- `LIDDModeSet(3)` at `0xC27C3B70` (`0xC2892114`, LIDD_CTRL & 7): 3 = ASYNC_MPU80, an 8080-style parallel bus.
- `LIDDCSTimingConfig(cs0, 0x00220045)` at `0xC27C3B88`: W_SU 0, W_STROBE 1, W_HOLD 1, R_SU 0, R_STROBE 1,
  R_HOLD 1, TA 1 (field masks from `hw_lcdc.h`).
- `LIDDDMACSSet(0)` (`0xC27C3B98`); LCDDMA_CTRL = 0x44 (`0xC2892204`: burst size field 4 = 16, bit 2,
  frame mode 0, little endian).
- Panel commands through `LIDD_CS0_ADDR` (`0xC27C3AD0` -> `0xC2892270`) and data through `LIDD_CS0_DATA`
  (`0xC27C3AE8` -> `0xC2892120`): `0x11`, wait 120 ticks, `0x36` data `0x40`, `0x3A` data `0x5555`
  (low byte 0x55), `0x29` (`0xC27C3BD2`-`0xC27C3C00`). These are MIPI DCS opcodes (sleep out, memory
  access control, pixel format 16 bit/pixel, display on). Inference: an ST7789/ILI9341-class controller
  with its own frame memory; no part number in the image (not found by string scan).
- Frame transfer (slot 2 `0xC27C3D2C`): Cache write-back of 0x25800 bytes (`0xC27C3D44`), then
  `0xC27C3C70`: command `0x2C` (memory write), `RasterDMAFBConfig(base, fb, fb + 0x257FE, 0)`
  (`0xC2892148`), LIDD DMA enable (`0xC2892160`), poll LCD_STAT, disable. No column/page-address
  commands (`0x2A`/`0x2B`) are sent anywhere (every caller of `0xC27C3AD0`: 6 sites).
  `0xC27C3C18` paces frames to 33 ticks (as SmplTrek's OLED flush).
- **Geometry: 0x25800 = 153,600 bytes = 76,800 16-bit pixels = 320 x 240, RGB565.** Orientation from the
  drawing code: `0xC25F6238`-`0xC25F6294` checks x < 320 and y < 240 and multiplies x by 240
  (`(x<<8)-(x<<4)`) for the offset, with halfword stores. Inference: the UI is 320 wide x 240 high and the
  frame buffer is column-major (240 pixels per x), i.e. a 240 x 320 portrait-native panel driven in
  landscape. 319/239 appear 129/167 times as MVK immediates (clipping), 320/240 288/241 times.
- Backlight: LCDDriver slot 6 `0xC27C3DAC` branches to `0xC2897A4C`, the eHRPWM1 set-up (12 sites).
  Inference: PWM backlight, set from `MenuLCDBrightnessDialog` ("LCD BRIGHTNESS", `0xC294A7CC`).
- 1.1.62 and 2.0.109 carry the same constants (15 MHz `0xC12BD598`/`0xC23C69E0`, CS timing
  `0x00220045`, ceiling 0x257FE `0xC12BD7AC`/`0xC23C6BF0`, the same DCS opcode sequence at `0xC12BD612`ff).

**Audio.**
- `mcasp_configure` (SmplTrek `0xC1621364`) is at `0xC27D1878`: `rdiff.py 0xc1621364 0xc16214cc --at
  0xc27d1878 ...` gives 106 vs 106 instructions, 8 moved data addresses, 2 "other" (one MVKH moved within
  its execute packet). So I2S, two 32-bit slots, codec as clock master, AXR14 in / AXR13 out, as SmplTrek.
  Note: func_match's own pairing put it at `0xC27B3380` (wrong function); `--at` was needed.
- `codec_i2c_init` (`0xC27D1810`) and `audio_start_transfers` (`0xC27D19E0`) match up to packet reordering.
- Codec block (SmplTrek `0xC161D560`-`0xC161DF84`) at `0xC27EE980`: 767 vs 785 instructions. The PLL /
  sample-rate writes are the same constants as SmplTrek (registers 3 = 0xA2, 4-8 ...; `callargs.py` on
  `codec_write` `0xC286D8C4`, 107 sites listed in the session). The output set-up differs (already in
  04-hardware-access.md near line 620): 37 = 0xC0, 42 = 0x9C, 47/64 = 0x80, 51/65 = 0x09, 54/71 = 0x80,
  58/72 = 0x09, 82/92 = 0x80, 86/93 = 0x0B, no write to 41 (`0xC27EEDD4`-`0xC27EEE70`): HPLOUT, HPROUT,
  HPLCOM, HPRCOM and both line drivers powered from DAC_L1/R1. `codec_map.py --decode` used for the
  meanings. A codec register 12 write sits at `+0x908` in the block (as SmplTrek 3.x).
- Sample rate: 48,000 appears 32 times as a constant, 44,100 once (`0xC27EE998`, inside the
  sample-rate function), 96,000 11 times. Audio block size: not settled (SmplTrek's `audio_block_isr`
  did not pair; the EDMA PaRAM was not read).
- USB audio: same descriptor template as SmplTrek (below).

**Input.**
- No panel MCU over UART: no `ADControllerUART` class, no UART1 interrupt, and the UART base helper is
  generic. Inference: buttons, keyboard and LEDs are DSP-side, as in the Liven line (INT-14).
- Classes: `ControlScan : Foundation::DynamicScan` (vtable `0xC295E540`), `MusicalKeyboardDelegate`,
  `RotaryEncoderDelegate`, `ControlSwitchDelegate`, test pages TestKeyboard, TestControlSwitch,
  TestRotaryEncoder, TestLED, TestLEDColor (RGB LED test with "R:"/"G:"/"B:" strings).
- GPIO census, 3.1.149 (`callargs.py` on the wrappers; pins 1-based -> GPb[n]):
  - direction wrapper `0xC2899E30` (37 sites): outputs GP5[0..14] and GP4[8..13] (21 pins, one function
    `0xC287A334`-`0xC287A468`), GP0[0..4] (`0xC288F384`ff), GP0[5], GP0[6] (`0xC28B6120`, in ControlScan's
    slot 2 `0xC28B6100`), GP1[0], GP1[1], GP1[7], GP1[10], GP8[12], GP8[14], GP8[15]; inputs GP4[0], GP4[1].
  - pin write `0xC2899EB4` (9 sites): GP1[1], GP1[7], GP8[12]; bank/bit write `0xC2899EE4`: GP1[0], GP1[10],
    GP8[14], GP8[15]; pin read `0xC2899F34`: GP1[2], GP1[3], GP4[0], GP4[1].
  - SmplTrek's key-matrix pins (rows GP2[0..5], columns GP3[1..6,9,11]) and encoder banks 3/5 reads do not
    appear in this census (direct register access was not fully traced).
- **DMA-driven scanning (new against the SmplTrek family).** `0xC28419CC`-`0xC2841A74` program TIMER64P2
  (`0x01F0C000`) and EDMA3 CC1 (`0x01E30000`) channel 24 (EDMA3 driver calls `0xC277F0E0`, `0xC277FA30`,
  `0xC277F760` with base `0x01E30000` and channel 24); `0xC2841718`/`0xC2841614` build a chain of PaRAM
  sets (`EDMA3SetPaRAM` `0xC277EEA4`) whose destination is GPIO base `0x01E26000` + an offset argument
  (`0xC2841670`-`0xC28416A8`), in loops of 6 x 15 and 14. Inference: a timer-paced DMA that writes GPIO
  output registers row by row (LED and/or key multiplexing, `Foundation::DynamicScan`). The exact
  registers and what is scanned were not decoded.
- Release note: 1.1.62 has neither EDMA3 CC1 nor TIMER64P2 in its census and has classes
  `DynamicLightingScan` and `MusicalKeyboard` (Liven-style names); 2.0.109 drops those classes and adds the
  CC1/TIMER64P2 use. So the scan moved to DMA in 2.0 (inference from census + class lists).

**Storage.**
- SD card: `HAL::SDDriver`, MMCSD0 interrupt, FatFs (carried `f_*` names), module clock 228 MHz.
  Card detect: GP8[13] (pin 142) set as a GPIO interrupt (`0xC28774C8`: `GPIOIntTypeSet` `0xC2876BD0`,
  bank-8 interrupt enable `0xC2876D84(8)`), handled on int 8 (event 75); GP4[0] read as card-present
  (`0xC287760C`), GP8[12] driven high at `0xC2877534`. SmplTrek uses GP4[0] (detect) and GP4[1] (output);
  here GP4[0] and GP4[1] are both inputs (`0xC2877840`/`0xC2877848`).
- Card folders (strings referenced from `0xC286148C`-`0xC286152C`): `/Memory`, `/WaveData`,
  `/WaveTableData`, `/Noise`, `/Pattern`, `/Looper`, `/Kit`, `/Backup`. "USB MASS STORAGE MODE", CARD FORMAT.
- SPI: three `HAL::SPIDriver::init` calls (`0xC2807788`) with clocks 16 MHz (`0xC2888060`, `0xC28880F8`)
  and 50 MHz (`0xC28880B4`). Settings tag "PREF" referenced at `0xC26244E8`, `0xC2625DE0`; the string
  "ELZ_1_PREF" is in the image with no code reference found.
- Preset image: a function returns 0x008C2000 (`0xC2846AA4`/`0xC2846AA8`), 4 KiB below the first
  partition address in the pmtd table (0x8C3000). Inference: flash address of the pmtd header copy. The
  eight partition tags are not in the app as strings or MVK constants (`constscan.py`); the carried
  `preset_pdpt_load` (`0xC2818CE4`) reads fixed offsets +68/+80/+84 of the header copy, which in this
  pmtd layout are the PWDG tag and the PWDD entry, not PDPT. So the carried name is doubtful (see
  "Tool and symbol issues").

**USB** (`ifdesc.py`): the static descriptor sections have SmplTrek's shape: Audio Control IF0
(input terminals 3 = USB streaming 0x0101 and 5 = microphone 0x0201), Audio Streaming IF1 and IF2,
MIDI Streaming IF3, plus a one-interface mass-storage configuration (EP 0x81/0x02, 64 bytes, and a
512-byte variant). VID/PID are filled at run time (as SmplTrek); not found by this method. The MSC
configuration's bMaxPower byte reads 250 (500 mA) where SmplTrek's reads 1 (2 mA). The configuration's
wTotalLength is 0 in 3.1.149's static data and 234 in 1.1.62/2.0.109 (filled at run time in 3.1.149,
inference). Product/vendor strings: "ELZ_1 play", "SONICWARE".

**MIDI.** `MIDI::MIDIStreamUART` on the only UART interrupt (UART0, inference), USB-MIDI
(`MIDIStreamUSBDevice`, `MIDIStreamParserUSB` new in 3.1). A MIDI monitor shows "HOST: Connected" /
"HOST: Disconnected" and "HOST THRU: USB-C/DIN" (`0xC277E628`-`0xC277ED90`). Whether the DSP acts as a
USB host was not checked (usblib host functions are linked, e.g. `USBHostEndpointDataAck`).

**Power.** `MenuBattery` with Alkaline/NiMH/Lithium (same three labels as the SmplTrek family);
`TestPowerSupply` shows "TYPE : AC Adaptor" / "TYPE : Battery" (`0xC27C21D0`/`0xC27C21D8`); "LOW BATTERY",
"Shutting down...". Battery voltage source not traced (no panel MCU channel 15 here).

**Same board as SmplTrek? No** (inference, several independent observations): 228 MHz vs 186 MHz module
clock; LCDC in LIDD mode vs SPI OLED; no panel-MCU UART or its interrupt; TIMER64P2 + EDMA3 CC1 +
eHRPWM1 in use (none in the SmplTrek family); a different GPIO census; all four codec headphone/COM
drivers powered vs only the line drivers. Shared: McASP set-up, codec PLL writes, codec I2C, USB
descriptor template, SD on MMCSD0 with GP4[0].

### D. Application

- 496 RTTI classes (SoundEffect 111, SoundOSC 65, Menu* 46, UI 34, Envelope 22, SoundSetting 15,
  Filter 14, Sequencer 13, Test* 12, MIDI 12, AudioEngine 12, HAL 9, Voice 7, Graphics 5).
- Synth engine: oscillator types from the label table `0xC29DA914`-`0xC29DA950`: Standard, Custom, WaveMem,
  WaveMemMorp, WaveMemFM, DNAExplore, SiGRINDER, FMSynth, MaskedNoise, SandFlute, WaveMemDual, WaveMemEnv,
  WaveMemTime, DrumSound, ZTRINGS, SuperOsc; classes `OSCGeneratorWaveMemory*`, `OSCGeneratorFMSynthesis
  <float,4>` (4-operator, ALGO/GACHA strings), `OSCGeneratorGranularExplorer/Grind`, `KarplusStrong`,
  `LoBit`, `NoiseFiltered/Masked`, `WaveTable`. Three layers (LAYER1-3), OSC1-3 with four mod slots,
  ENV1-3, FLT1-3, filter types LPF6/12, HPF6/12, BPF, PEQ, LO/HI EQ, envelopes ADSR / ADSR-C / ADSAR /
  ADSAR-C. Voice modes Poly/Mono/Legato/Unison (UNI1-4), arpeggiator (`Sequencer::ArpeggiatorPlayer`).
- Effects: slots INSERT, EFX I, EFX II, MASTER; about 45 effect classes (chorus, flanger, phaser,
  tremolo, vibrato, ring mod, auto-wah, bit crusher, formant, isolator, rack comp, tape echo, ping-pong /
  reverse / stereo delays, reverbs incl. Ambient Hall/Room/Infinity, Arena, Tunnel, Mirage, granular FX,
  cassette tape, analog record).
- Looper (`Looper::AppLooperEditor`, LOOP1-4, REC TRIGGER, OVERDUB, one-shot/loop), sequencer with
  patterns, STK DRUMMER, AUX IN mixer (stereo / dual mono), macros (`AppMacroSetting`), patch tags
  ("Up to 4 tags can be set."), MEMORY A-D banks.
- SYSTEM menu items (`0xC294A770`-`0xC294A856`): MEMORY, PATTERN, LOOPER, WAVEDATA, MIDI, CLOCK, KEYBOARD,
  AUX IN, MASTER TUNE, MASTER EFX RESET, CARD, LCD BRIGHTNESS, AUTO POWER OFF, BATTERY TYPE, MEMORY CHANGE
  ALERT, PLAYMODE SCROLL, PLAYMODE OSC VIEW, TEMPO LED, USB AUDIO, RESET, SPECIAL THANKS, SYSTEM INFORMATION.
  System info shows BOOT, PRESET, SYSTEM versions (`0xC27A0168`-`0xC27A0484`; pmtd/mmtd/bmtd getters at
  `0xC2846B80`-`0xC2846E00`, carried names, same scheme as the family).
- Test mode (`TestMode`): Audio (Sine 110/880/3520 Hz, AUX IN), Keyboard, Control Switch, Rotary
  Encoder, LCD, LED, LED Color, Power Supply, USB, USB Device.

### E. Formats visible in code (formats only)

- Card file extensions (filter table `0xC29DC7F8`ff): `*.e1m` (memory export), `*.e1p` (pattern export),
  `*.wav`; `*.stk` (`0xC279E7B0`; also present in SmplTrek and Lofi-12 XT); `.bmp` (`0xC27B4B94`, use not
  traced); `/SlotList.lst` (`0xC2724E50`).
- WAV handling: RIFF/WAVE/fmt; LIST/INFO/ICMT and a custom `LoFM` chunk (`0xC286DB88`-`0xC286DD78`,
  `AudioEngine::LobitFMWaveFile`); `ACTG`, `AILS` (`0xC286FD60`/`0xC286FE60`; also in SmplTrek); `WFDT`
  (`0xC2699648`).
- Content bank: `/PresetWaveTable.bin` and " Contents.bin" (`0xC27CD6E4`, `0xC27CDC38`), checked for a
  `WTLS` tag (`0xC27CD998`, `0xC27CDE60`). 2.0.109's separate `ELZ_1 play Contents.bin` (48 MiB) starts
  `WTLS` <u32 len> <u32 0> <u32> then `WTDT` ... `WTNM` ... with a file name: the same tag set CyDrums'
  code names (WTLS/WTDT/WTNM strings in CyDrums 1.1.84; ELZ_1 play's code names only WTLS).
  "CONTENTS COPY" and `copyPresetWavetableFile()` (RTTI lambda) copy it to the card.
- Backup: `ArchiveSave`/`ArchiveImport`, `Asset::Backup::importFile` (RTTI), "BACKUP DATA IMPORT".
- SysEx: no Sonicware SysEx header (`F0 00 48`) found in data by byte search; not found by this method.

### F. Release history

| | 1.1.62 | 2.0.109 | 3.1.149 |
|---|---|---|---|
| pmtd | v1.0.17, 7 partitions (no PWDD) | v2.0.24, 8 | v3.1.26, 8 |
| mmtd entry / B14 | `0xC12FEF60` / `0xC154CCE8` | `0xC24251E0` / `0xC26006A0` | `0xC28B0500` / `0xC29C5678` |
| code | 1.93 MiB | 2.28 MiB | 3.01 MiB |
| sections | 7 (first is 1.16 MiB of data) | 6 | 7 |
| EDMA3 CC1, TIMER64P2 | not found | yes | yes |
| RTTI classes (non-std) | 409 | 447 | 468 |
| LCD init constants | same | same | same |
| extra files in zip | none | 48 MiB Contents.bin, a PDF | none |

- 1.1 -> 2.0 added: wavetable oscillator and loaders (`OSCGeneratorWaveTable`, `WaveTableDataLoader`,
  `WaveTableAudioFile`), granular FX (5 generators), Formant, Isolator, (M)RackComp, Mirage, EnvelopeDelay,
  ResourceLoader, PitchBendComponent, MenuTempoLED, MenuPlaymodeScroll; removed `DynamicLightingScan`,
  `MusicalKeyboard`, `WaveFileService::*`, `UI::PlayWindow`, `ZTRINGSAnimation`.
- 2.0 -> 3.1 added: macros, OSC status view, patch tags and change alert, MIDI transpose, pitch-bend and
  velocity dialogs, EFX reset, `MenuUSB`, `TestLEDColor`, `MIDIStreamUSBDevice`/`MIDIStreamParserUSB`
  (replacing `MIDIStreamUSB`), modal views.
- 1.1.62 and 2.0.109 carry a UTF-16 USB string descriptor "SmplTrek" in data (`0xC1541A20`,
  `0xC25F4870`) next to the "ELZ_1 play" ones; 3.1.149 has none. Use not traced (likely a leftover).

### G. Relation to SmplTrek and CyDrums

- func_match against SmplTrek 3.2.174: 843 functions paired (776 with similarity >= 0.9), against 2,393 for
  CyDrums and 2,895 for Lofi-12 XT (`work/match-3.2.174-*.json`).
- Class names shared: 95 with SmplTrek 3.2.174, 84 with CyDrums 1.1.84, 85 with Lofi-12 XT, 77 with
  MINIMAL. Shared with CyDrums but not SmplTrek: LaunchAnimation, NoteHoldDelegate, ResourceLoader,
  Sequencer::ArpeggiatorPlayer, SoundEffect::FxFilter, MRackComp, OverDrive, UI::Dialog.
- Verified-identical code with SmplTrek: `mcasp_configure` (above); near-identical: codec I2C init, audio
  start, codec PLL writes.
- Product number 8 shared with CyDrums: the code says nothing about it. The app never compares the
  family word (the only header readers are the version-string getters). What the two share that the rest
  of the family doesn't: the WTLS/WTDT/WTNM content-bank format, and the eight classes above. That fits
  the existing reading (CyDrums inherits from the ELZ_1 play project) without proving it. Open.

---------------------------------------------------------------------------------------------------------

## deconstruct MINIMAL 1.0.58

### A. Image

- `cmtd`, 1,416,001 bytes, product word 16, **one image**: `mmtd` v1.0.58, 0x159B11 bytes, entry
  `0xC0A24720`, 7 sections: `0xC0AB6720`-`0xC0AB77D8`, `0xC0AB6310`-`0xC0AB63FC`, `0xC0AB6400`-`0xC0AB6600`,
  code `0xC0959C00`-`0xC0A312C0` (862 KiB), `0xC0959970`-`0xC0959C00`, constants `0xC0A312C0`-`0xC0AB1859`,
  `0xC0AB5514`-`0xC0AB5D20`. No preset image. B14 = `0xC0AB5D20`. File name in the zip: `DECONSTRUCT_MINIMAL.bin`.
- Toolchain: rts6740_elf 8.3.2 123, 8.3.9 124, 8.3.10 124, 8.3.11 132, 8.3.12 132, 8.3.13 133, 8.5.0 95
  unique; xdc.runtime 44. Same band as SmplTrek.

### B. SYS/BIOS

- 8 static tasks (`init_data.py --tasks --b14 0xc0ab5d20`, `tasks-min.txt`), fxn `0xC0A18C00` except Idle
  (`0xC0A30D80`). The 64 KiB task (`0xC0AB39D0`, B14+1008) is static at **priority 5** (SmplTrek family and
  ELZ_1 play: 3). Others 2 KiB. Priorities read at `task_handler_set` `0xC0A18CAC`: 14 (`0xC0A2CC98`, USB
  task start), 13 (`0xC0A18190`), 7 (`0xC0A22678`, AsyncTaskHandler), 2, 1 and 0 (`0xC09EDF74`,
  `0xC0A2B540`, `0xC09E7DA8`; handler classes not traced).
- Hwis (`hwi.py ... 0xC0AB617C`, from the function at `0xC0A1AA60` that loads ISTP from +32): int 4 ev 36
  I2C0 `0xC09E19C4`; int 5 ev 8 EDMA3 CC0 `0xC0A1CC10`; int 6 ev 61 McASP0 `0xC09E11D0`; int 7 ev 75 GPIO
  bank 8 `0xC0A0DFE0`; int 8 ev 38 UART0 `0xC09E43F8`; int 12 ev 19 USB0 `0xC0A1D5E4`; int 14 ev 4 Timer64P0
  `0xC0A28360`. **No MMCSD interrupt** and no UART1.

### C. Hardware use

- Census (`hw-min.txt`): as ELZ_1 play minus LCDC, eHRPWM and **MMCSD0**; with EDMA3 CC1 and
  TIMER64P2. Parts: C6746 or C6748 (INT-16). The "unknown 0x01E84000" hit is not a peripheral: it is
  0x01E84800 = 32,000,000 passed as an SPI clock to `HAL::SPIDriver::init` (`0xC0A0E1E0`).
- Module clock 228,000,000 (`0xC0A08570`, `0xC0A15728`), as ELZ_1 play.
- Audio: `mcasp_configure` at `0xC09E0C24`: 106 vs 106 instructions, 8 moved data addresses, 2 "other"
  (same as ELZ_1 play); codec I2C init `0xC09E0BB4` and audio start `0xC09E0D8C` match up to reordering.
  Codec PLL writes as SmplTrek. Own output set-up (`0xC09E4E54`-`0xC09E4EF0`): 37 = 0xE0 (HPLCOM
  single-ended), 38 = 0x10, 41 = 0x02 (DAC_L1/R1 mixer path), 42 = 0x9C, 47 = 0x80 and 50 = 0x80 (DAC_L1
  and DAC_R1 to HPLOUT), 54/58 HPLCOM on, 71/72 HPRCOM on, 82/86 and 92/93 line drivers on (0x80/0x09); 51
  (HPLOUT level) is not written there. A switch function `0xC09E4F08(arg)`: arg 0 -> 86 = 9, 93 = 9, 108 =
  0; arg != 0 -> 86 = 0, 93 = 0, 108 = 0x33. Register 108 is not decoded by codec_map.py; on the
  TLV320AIC3106 it is the passive analog bypass selection during power-down (inference: a hard-wired
  input-to-line-out pass-through mode; check SLAS509G before relying on it).
- **Display: segment-style characters, not a pixel display** (inference). No LCDC, no OLED driver class;
  UI strings are at most 8 characters with embedded dots ("PWR.OFF", "LP.O.OFF", "D.K.RENM", "S.FLT"),
  a six-space string (`0xC0AA9659`), and a 256-entry character map (`0xC0AAB0F4`, used at `0xC097A7A0`)
  that keeps space, '.', digits and letters, folding lower to upper case; the loop at `0xC097A7B0`
  treats '.' (46) specially (attached to the previous character). So 6 characters plus decimal points
  (inference from string lengths). Driven by GPIO: 37 outputs set in one function (`0xC0A05280`-
  `0xC0A054A8`): GP6[8..14], GP4[0..14], GP5[0..14]; plus EDMA3 CC1 / TIMER64P2 (functions `0xC09FAE14`-
  `0xC09FB174`). Inference: a DMA-multiplexed LED/segment matrix, `DispFuncion` (RTTI lambda) and
  `TempoLED`.
- Input: `ControlSwitchScan : Foundation::DynamicScan`, `VRReaderDelegate`, `VRMedianFilter`,
  `VRFluctuationFilter`, `HAL::ADHandlerComponent`, `BatteryLevelChecker : VRFluctuationFilter`,
  `HAL::PowerLevelChecker<int,3>`: pots and the battery are read through one analogue path. The C6748 has
  no ADC, so an external converter (bus not identified). No panel MCU UART.
- Other GPIO: outputs GP8[8] (also written), GP7[14], GP7[15], GP8[15], GP0[4], GP0[5], GP1[2], GP1[3],
  GP1[10..15]; bank/bit writes GP0[5], GP0[4], GP8[15].
- **Storage: FatFs on a 40 MiB RAM disk, no SD.** `disk_read`/`disk_write` (`0xC0A1E184`, `0xC0A1E128`)
  memcpy (`0xC0A249A0`) to/from `0xC1500000 + sector * 512` (`0xC0A2B5F0` returns
  `0xC1500000 + arg`); `disk_ioctl` (`0xC0A1E1E0`) answers GET_SECTOR_COUNT 0x14000 and GET_SECTOR_SIZE
  512: 81,920 x 512 = 40 MiB (`0xC1500000`-`0xC3CFFFFF`). The USB mass-storage configuration is present
  (below), so the RAM disk is probably what a computer sees (inference). How it is filled and saved
  (`HAL::FlashDrv : HAL::FlashMemoryDriver`, `FlashDelagate`, SPI at 16 / 32 MHz) was not traced.
  Volume string "0:MINIMAL" (`0xC09F06D0`).
- USB: same descriptor template as ELZ_1 play and SmplTrek (Audio Control with terminals 3 and 5, two AS
  interfaces, MIDI streaming IF3, an MSC configuration); strings "deconstruct MINIMAL", "SONICWARE".
- MIDI: UART0 (only UART interrupt), USB-MIDI (`MIDIStreamUSB` with `send_sysex_chunk` `0xC09EA660`, 3
  callers), `AppCCDispatcher`, `MIDINoteMap`, `MIDIChSetting`.
- Same board as SmplTrek: no (no SD, no display controller, different GPIO census, 228 MHz clock). Shares
  with ELZ_1 play: the 228 MHz assumption, GP5[0..14] as outputs, EDMA3 CC1 + TIMER64P2, GPIO bank-8
  interrupt, UART0-only. Inference: a sibling platform of ELZ_1 play rather than of SmplTrek.

### D. Application

- 206 RTTI classes. Groove box: drum (`DataStructureDrum` x6, `OSCDrumInst`), bass (`OSCTB303Generator`,
  `TB303Slope`, `TB303AccSlope`, `TB303FilterSlope`; strings ACCENT, GLIDE, ACC-H/ACC-S, RETRIG, SOLO),
  sample synth (`OSCSampleSynth`, `DataStructureSample` x4, `QuickSampling`), wavetable synth.
- Sequencer: step and real-time recorders, host controller, parameter locks
  (`DataStructurePrmLockTrackTemplate` with 20 and 14 locks), 11 sequence properties, pattern banks.
- Effects: Compressor, DJFilter, MIsolator, ModDelay, OverDrive, Phaser, Plate/Hall/Room, SlipRoll,
  TapeEcho, MasterEffect. `FFTObserver` task class.
- `BackupHandler` (a MenuItem), `FactoryResetHandler`, `TestMode`.

### E. Formats

- Files on the RAM disk: `/Audio/S8`, `/Audio/S4`, `/Audio/S2` (sample folders), `/Pattern/BANK`, `.mnp`
  (pattern), `/Kit`, `.mnk` (kit), `*.wav`, `Preferences/Preferences.dat` (`0xC097A4C0`-`0xC097DC54`).
  Settings tag "PREF" referenced at `0xC09885E4`.
- Archivers: `Asset::DataArchiverPattern`, `...PatternName`, `...String`, `...Track`,
  `Foundation::Serializable<Asset::ContainerStructure>`.
- SysEx: no static Sonicware header found; BackupHandler's transport not traced.

---------------------------------------------------------------------------------------------------------

## Could not settle

- Audio block size (frames per EDMA block) in both: SmplTrek's block ISR did not pair and PaRAM wasn't read.
- What the EDMA3 CC1 / TIMER64P2 scan writes, exactly (GPIO registers, row count, LED vs key read).
- ELZ_1 play key matrix and encoder pins; MINIMAL's analogue converter bus.
- How MINIMAL's RAM disk is loaded from and saved to flash.
- VID/PID (filled at run time in both; the SmplTrek route was simulation, `usb_desc_map.py`, which is
  hard-wired to SmplTrek addresses).
- Task-to-handler mapping beyond the priorities listed.
- Why CyDrums and ELZ_1 play share product number 8.
- The panel controller part number (only the DCS command set is visible).

## Tool and symbol issues met

- `hw_inventory.py` counts clock constants as peripherals: 0x01E84800 (32 MHz, an SPI init argument) is
  reported as "unknown 0x01e84000" in MINIMAL (and in SmplTrek 3.2.174, which has the same constant at
  `0xC167C768`/`0xC167C7F8`); 0x01B77400 (= 28,800,000) is reported as "unknown 0x01b77000"
  in both products (use not checked; probably a clock value too).
- func_match pairs SmplTrek `mcasp_configure` with the wrong function in both images (region_diff without
  `--at` reported 179/165 differences at `0xC27B3380`/`0xC09E823C`); with `--at` the real function is
  identical.
- `region_diff.py`, `codec_map.py`, `sd_map.py`, `usb_desc_map.py` hard-code the three main products; a wrapper
  that swaps `PRODUCTS`/`IMAGES` works for region_diff (`rdiff.py`).
- Carried symbols to distrust: `preset_pdpt_load` in elz-3.1.149 (reads entries that are PWDG/PWDD in this
  pmtd layout); `Task_unblockI` at `0xC28BB080` encloses a USB0 base constant per hw_inventory (either the
  name or the function start is wrong). Names relied on here were checked by body or call context:
  task_handler_bind/set, GPIO wrappers (decoded), codec_write, HAL::SPIDriver::init, memcpy (by use).
- `ELZ_1 play` 3.1.149 `Hwi_Module_startup` (`0xC289E060`) loads two constants: `0xC29C3678` (8 KiB ISR stack,
  not readable through init_data) and `0xC29C60E0` (module state). The first one looked like the module state
  and isn't.
