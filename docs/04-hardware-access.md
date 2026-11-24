# Hardware access: how the stock firmware drives the board

A register-level reference of how SmplTrek 3.2.174 drives the board: power, the OLED, the key matrix and encoders,
the panel MCU (pads, battery, LEDs), audio in and out (codec, McASP, DMA), MIDI DIN, SYNC, the USB device, the SD
card, the SPI flash and the tick. Everything is read from SmplTrek 3.2.174 and checked against Lofi-12 XT 1.5.205,
CyDrums 1.1.84 and the bootloader 1.0.17, which run on the same board. Parts of it have been reproduced on the unit by
bare-metal test images (not published) that use these register sequences and no Sonicware code; those items are
marked **device**, with their claim IDs and the device session that observed them (session codes such as D0, D1, M1,
M2 are the device runs listed in [`experiments/README.md`](../experiments/README.md), each written up in
`experiments/sessions/<code>-*.md`). Everything not marked device is simulated or static.

## What has been checked on the unit

| Area | Device result | Claims | Session |
|---|---|---|---|
| Boot hand-over | the bootloader has the OLED on, the SONICWARE logo drawn and GP4[11] latched before the jump | HW-24 | D0 |
| Cache state at the jump | L2CFG 0, L1PCFG 4, L1DCFG 3, MAR 17, 128, 192-195, 199 | HW-52 | M1 |
| OLED on SPI1 | the set-up below (SPIPC0 required), polled commands and frames, the pixel layout. The stock's EDMA frame path is simulated only | HW-32, HW-35 | D1 runs 2-6 |
| Panel MCU on UART1 | the set-up below, polled: transmit (LEDs light), receive (`A1` reply, continuous `Bn` stream), message rate and channel order | HW-36, HW-46, HW-55, HW-68 | D1 runs 4-7, M1, M2 |
| Key matrix | rows and columns as below; STEP 1-16 = bits 32-47; contact bounce of STEP 1 | HW-47, HW-56 | D1 run 7, M1 |
| Encoders | pins as below; four quadrature edges per detent (the stock's decode rule is simulated) | HW-47 | D1 run 7 |
| Panel LEDs | `C1 a b c v` addressing, pad colours, 38 addresses seen at their exact address, values 0-10 | HW-47, HW-48 | D1 run 7 |
| Power hold release | GP4[11] low: the unit stays on while the power key is held, off on release | HW-47 | D1 run 7 |
| Audio out | the codec, McASP0 and EDMA ring as below make sound; even words = left on the headphones. Line outputs and the receive side not observed | HW-61 | M1 part A |
| SD card | a minimal polled single-block driver on this controller set-up mounts the card and reads files through FatFs. The stock's interrupt and EDMA path is simulated only | — | D1 run 3 |
| SPI flash | JEDEC ID of both devices, status and configuration (boot-area protection on device 0) | HW-54 | M1 |
| USB0 | PHY bring-up as below reaches USB0PHYCLKGD (no attach) | HW-59 | M1 |
| Timers | TIMER64P0 free-running as a test image sets it (TGCR 5, TCR 0x90) advances; a TIMER64P1 interrupt on CPU interrupt 4 | HW-67 | D1, M2 |
| CPU access behaviour | misaligned accesses, low-memory and EMIFA accesses (see "Hazards") | HW-57, HW-58, HW-60, HW-62 to HW-65 | M1, M2 |

## Same board, same writes: the cross-product check

`analysis/hw_compare.py` runs each bring-up function below in SmplTrek, Lofi-12 XT and CyDrums (counterparts by
symbol name or func_match) and compares the register writes in order. Result (simulated, 2026-11-12): every step
writes the **same registers with the same values in all three products**: SYSCFG unlock, board pin defaults, USB PHY
configuration, SPI0/SPI1, the OLED (commands and frame DMA), the panel UART, encoders, key matrix, SYNC pins, power
hold, the audio power sequence, I2C0, audio start-up (57 register writes and 40 codec register writes), MIDI DIN
UART, USB device start and SD card. The one difference is the audio DMA ring's block length (128 frames in SmplTrek,
96 in the other two), which is product code, not board. Values that are memory addresses (buffers) are not
compared. The bootloader (static) builds the same SYSCFG unlock keys, 186 MHz module clock, SPI rates, panel baud,
CFGCHIP2 value and USB interrupt mask, and none of the audio or MIDI constants (it has no audio). So each board
value below has been written by three independently built apps.

## Evidence levels

- **device:** observed on the unit (claim ID and session given).
- **simulated:** the stock function was run in `analysis/c6sim.py` on the state after SYS/BIOS start-up
  (`analysis/sim_boot.py`, product `smpltrek`), with every peripheral register access logged by
  `analysis/mmio_trace.py`. Register values written are what the code computes. Status registers the code
  polls are answered "ready" by the tracer, and GPIO inputs read 0, so code paths that depend on input values
  show one path only.
- **static:** read from the disassembly (`work/smpltrek-3.2.174.dis`, regenerated locally), not run.
- **inference:** reasoning beyond the code; says so where it is used.
- Register and pin-function names are TI's, from StarterWare 1.20.04.01 `include/hw` (not committed; the
  tracer reads them from a local install).
- **TI documents:** the C6748 Technical Reference Manual SPRUH79C, the data sheet SPRS590G, the bootloader guide
  SPRAB41F, and the TLV320AIC3106 data sheet SLAS509G (Rev. G), read 2026-11-12. Where a meaning below cites a
  document, section or table, it was read there; the PDFs are not committed. Readings corrected against them are
  marked "correction (TI document)".

Reproduce (needs `firmware/`):

```
python3 -B analysis/hw_inventory.py "firmware/smpltrek/SmplTrek v3.2.174.zip" --symbols symbols/smpltrek-3.2.174.json
python3 -B analysis/mmio_trace.py "firmware/smpltrek/SmplTrek v3.2.174.zip" --boot
python3 -B analysis/mmio_trace.py "firmware/smpltrek/SmplTrek v3.2.174.zip" --run 0xC167C7B4 --writes
python3 -B analysis/hw_compare.py -v          # every step in the three products, with every write
```

`test_mmio_trace.py` and `test_hw_compare.py` pin the values below.

## Which peripherals the app touches (static, `hw_inventory.py`)

Every 32-bit constant in the C6748 peripheral space that the code builds, plus base addresses in the initialised
data: INTC, the cache controller, EDMA3 CC0, PSC0, PSC1, SYSCFG0, SYSCFG1, TIMER64P0 to P3 (P2/P3 only in
SYS/BIOS's timer table), I2C0, I2C1, MMCSD0, SPI0, SPI1, UART0 to UART2, McASP0 and USB0. No PLLC, DDR or EMIFA
register is written by the app: the boot ROM and the bootloader set clocks and DDR. Four other constants in that
range are not peripheral addresses: 32,000,000 (the SPI0 rate below), 0x01FFEC00 (the PREX settings flash address),
0x01FF1E1F (the USB0 interrupt mask, below) and 28,800,000 (`0xC16816F4` and two neighbours: the internal sequencer
clock's step threshold, 48,000 x 60 x 10; see "SYNC IN / SYNC OUT").

## State the bootloader leaves, and the clocks

- **Clocks** (three facts that agree, checked against SPRAB41F and SPRUH79C; claim HW-5):
  - the 1 ms SYS/BIOS tick programs TIMER64P0 PRD12 = 24000 (simulated), so the timer input is 24 MHz. The SYS/BIOS
    configuration agrees independently: the exact `Timer_getFreq` (claim LIB-3) returns 24,000,000 Hz (2026-11-14).
    Timer64P0/P1 and I2C0 run from PLL0_AUXCLK, which is the oscillator input without the PLL (SPRUH79 Table 7-1, and
    Table 6-9 "Peripherals": "fed the AUXCLK directly from the oscillator input"), so OSCIN = 24 MHz;
  - the AIS stream calls ROM function 6 with `0x001E0001, 2823, 3` ([05-bootloader.md](05-bootloader.md)). SPRAB41
    Appendix D.7 and D.1 (Figure 29, Table 17): Arg1 = CLKMODE 0 (crystal), PLLM 0x1E, PREDIV 0, POSTDIV 1; Arg2
    `0x000B07` = PLLDIV1 0, PLLDIV3 0x0B, PLLDIV7 7; Arg3 = the clock-configuration argument, in SPI boot the SPIFMT
    PRESCALE (3). The values are register values: multiplier = PLLM + 1 and divider = RATIO + 1 (SPRUH79 Table 7-12
    and the PLLDIVn tables). So PLLOUT = 24 x 31 = 744 MHz, /2 = 372 MHz SYSCLK1 (CPU), SYSCLK2 186 MHz, SYSCLK4
    93 MHz, SYSCLK3 31 MHz (EMIFA), and the boot SPI runs at 186 / 4 = 46.5 MHz. Two cautions: SPRS590 Table 6-4
    ("Allowed PLL Operating Conditions", row PLLOUT) gives 300-600 MHz as the PLL output range, which 744 MHz exceeds
    (observation, not an explanation; the unit runs); and SPRS590 refers C6748 boot to SPRAAT2, not SPRAB41 (the
    OMAP-L138 guide), so the ROM function table is assumed, not confirmed, for this part. The same numbers come out of
    the two facts above and the next, so the decode stands either way;
  - the SPI driver uses a constant module clock of 186,000,000 (`0xC16716E4`), PLL0 SYSCLK2;
    UART1's divisor below gives 465,000 baud from it, within 1% of the 460,800 the app asks for.
  - **Which clock each peripheral uses** (SPRUH79 Table 7-1 and Table 6-2 "System Clock Domains"): PLL0_SYSCLK2:
    UART0, SPI0, MMC/SD0, EDMA, the USB2.0 bus side; ASYNC3 (PLL0_SYSCLK2 unless CFGCHIP3 ASYNC3_CLKSRC = 1, SPRUH79
    Table 10-48): UART1, UART2, SPI1, Timer64P2/P3, McASP0; PLL0_SYSCLK4: GPIO, SYSCFG, PSC; PLL0_AUXCLK: I2C0,
    Timer64P0/P1, the USB2.0 PHY reference. Neither the app nor the bootloader writes CFGCHIP3 (hw_inventory; the
    bootloader is static only), so UART1 and SPI1 see 186 MHz.

  So: OSCIN 24 MHz, CPU 372 MHz, SYSCLK2 186 MHz. The observed divisors fit: UART0 372 gives exactly 31,250 baud
  (MIDI), MMCSD0 CLKRT 232 gives 186 MHz / (2 x 233) = 399 kHz (SPRUH79 MMC/SD "memory clock frequency = function
  clock / (2 x (CLKRT + 1))"; the SD identification limit is 400 kHz), and I2C0's ICPSC 2 gives 8 MHz from 24 MHz.
  The DDR (ROM function 3, SPRAB41 D.4): PLL1 Arg1 `0x18010001` = PLLM 0x18 (x25 = 600 MHz), POSTDIV 1 (/2 = 300
  MHz PLL1_SYSCLK1, the DDR2 PHY clock, so DDR2 at 150 MHz), PLLDIV1 0, PLLDIV2 1; Arg2 PLLDIV3 2; then DRPYC1R
  `0xC4`, SDCR `0x00139822` (one AIS copy `0x00139832`), SDTIMR1 `0x264A3209`, SDTIMR2 `0x3C14C722`, SDRCR 1170
  (7.8 us at 150 MHz, the usual DDR2 refresh interval), Arg8 0 (CLK2XSRC 0). The SDCR / SDTIMR fields are not
  decoded here.
- **Power hold:** `power_on_check` drives GP4[11] high and never sets its direction (simulated). The bootloader runs
  the same function first and has latched the power hold before it jumps to SYSTEM (**device**, HW-24, session D0),
  so GP4[11] is already high when the app starts; that it is already an output is inference (HW-8). Releasing it
  (GP4[11] low) leaves the unit on while the power key is held and switches it off when the key is released
  (**device**, HW-47, D1 run 7).
- **Watchdog:** none. The app uses TIMER64P1 only as a free-running counter for the audio clock measurement, and
  the bootloader addresses no timer at all (static).
- **Cache** at the jump: see [05-bootloader.md](05-bootloader.md) "Cache state at the jump" (**device**, HW-52).
- **Not traced:** which PSC modules the bootloader leaves on. The app enables every module it uses itself (below).

## Power and sleep controller (PSC)

Each module the app uses is enabled the same way (simulated, `0xC1686A70`): MDCTL(n) = 3 (enable), PTCMD = 1
(power domain 0), wait while PTSTAT bit 0 is set, wait until MDSTAT(n) bits 4:0 = 3.

| PSC | Module | Peripheral | Enabled by |
|---|---|---|---|
| PSC0 `0x01C10000` | 0, 1 | EDMA3 CC0, TC0 | board set-up (`0xC169CD20`), again by the SPI and SD set-ups |
| PSC0 | 4 | SPI0 (flash) | SPI set-up (`0xC167C7B4`) |
| PSC0 | 5 | MMCSD0 (SD card) | `sd_card_hw_init` |
| PSC0 | 9 | UART0 (MIDI DIN) | MIDI UART start (`0xC1620EF4`) |
| PSC1 `0x01E27000` | 1 | USB0 | `usb_dcd_init` |
| PSC1 | 3 | GPIO | board set-up (`0xC169CD20`) |
| PSC1 | 7 | McASP0 | audio hardware set-up (`0xC1621854`) |
| PSC1 | 10 | SPI1 (OLED) | SPI set-up |
| PSC1 | 12 | UART1 (panel MCU) | `ADControllerUART::set_baud_rate` |

Checked against SPRUH79 Tables 8-1 and 8-2 (PSC0 / PSC1 default module configuration): every module number above
names the peripheral given. I2C0 is in neither table (it is always on; no PSC write precedes its use), and it runs
from PLL0_AUXCLK.

## Order the stock app brings the board up, and the SYSCFG unlock

MainDelegate's start-up (`0xC154A4AE` onwards, a task) calls, in this order: `0xC16907D4` (SYSCFG unlock: KICK0R
`0x01C14038` = `0x83E70B13`, KICK1R `0x01C1403C` = `0x95A4F1E0`, TI's unlock keys, SPRUH79 section 10.5.5; without
them PINMUX and CFGCHIP writes are ignored), `0xC169CD20` (board set-up: PSC1 module 3 GPIO on, the audio pins' mux,
directions and levels, EDMA3 initialisation), `0xC16907C0` (USB PHY configuration, CFGCHIP2), `0xC1647114` (power
manager, incl. the power pins' mux), the SPI set-up, encoders, sync pins, settings and flash reads, audio pins, the
panel UART, the power-on check, graphics (OLED) and the SD card; USB and MIDI follow. Everything below is written by
these functions. The bootloader has the same unlock keys (static).

## Pin multiplexing (SYSCFG0 PINMUXn, `0x01C14120` + 4n)

The app changes only the nibbles it needs (read-modify-write); nibble k is bits 4k+3..4k. Values below are the
nibbles written, with TI's function names (simulated).

| Register | Nibbles set | Pins | By |
|---|---|---|---|
| PINMUX3 | 0-3 = 1 | SPI0 CLK, ENA, SOMI0, SIMO0 | SPI set-up |
| PINMUX4 | 0, 1 = 1 | SPI0 SCS0, SCS1 (the two flash devices) | SPI set-up |
| PINMUX4 | 6, 7 = 2 | UART1 RXD, TXD | `set_baud_rate` |
| PINMUX5 | 1, 2, 5 = 1 | SPI1 SCS0, CLK, SIMO0 (no SOMI: the display is write-only) | SPI set-up |
| PINMUX5 | 4 = 8 | GP2[11], OLED data/command | `oled_pinmux_init` |
| PINMUX6 | 2-7 = 8 | GP2[0..5], key rows | ControlScan slot 0 (`0xC168F140`) |
| PINMUX7 | 0, 1, 3, 5 = 8 | GP3[15], [14], [12], [10], encoders | `encoder_pinmux_init` |
| PINMUX7 | 4 = 8 | GP3[11], key column 7 | ControlScan slot 0 |
| PINMUX8 | 1-6 = 8 | GP3[6..1], key columns 5..0 | ControlScan slot 0 |
| PINMUX11 | 5, 7 = 8 | GP5[10] (key, active low), GP5[8] (encoder) | `encoder_pinmux_init` |
| PINMUX12 | 0, 2, 3, 5, 7 = 8 | GP5[7], [5], [4], [2], [0], encoders | `encoder_pinmux_init` |
| PINMUX17 | 0, 1 = 8 | GP7[9], GP7[8] (SYNC OUT / IN) | `0xC16720D8` |
| PINMUX8 | 0, 7 = 8 | GP3[7] power source, GP3[0] power key | power manager (`0xC16470B0`) |
| PINMUX9 | 4 = 8 | GP4[11] power hold | power manager |
| PINMUX9 | 0-3, 5 = 8 | GP4[15], [14], [13], [12], [10] (audio) | board set-up |
| PINMUX4 | 4, 5 = 8 | GP1[3], GP1[2] (audio) | board set-up |
| PINMUX5 | 6, 7 = 8 | GP2[9], GP2[8] (audio) | board set-up |
| PINMUX7 | 7 = 8 | GP3[8] (audio, input) | board set-up |
| PINMUX11 | 4 = 8 | GP5[11] (audio) | board set-up |
| PINMUX16 | 2, 3 = 8 | GP7[15], GP7[14] (audio) | board set-up |
| PINMUX4 | 2, 3 = 2 | I2C0 SCL, SDA (codec) | `i2c_open` |
| PINMUX0 | 1, 3, 5, 6 = 1 | McASP0 ACLKX0, AFSX0, AHCLKX0, AMUTE0 | audio hardware set-up |
| PINMUX1 | 1, 2 = 1 | McASP0 AXR14 (receive), AXR13 (transmit) | audio hardware set-up |
| PINMUX3 | 4, 5 = 2 | UART0 RXD, TXD (MIDI DIN) | MIDI UART start |
| PINMUX10 | 0-5 = 2 | MMCSD0 CLK, CMD, DAT0-3 | `sd_card_hw_init` |
| PINMUX10 | 6, 7 = 8 | GP4[1], GP4[0] (SD) | `sd_card_hw_init` |

SYSCFG1 PUPD_ENA (`0x01E2C00C`): the encoder set-up clears bits 19 and 20 (`pupd_set_19_20(0)`, `0xC1690814`) and
the key-matrix set-up clears bits 16 and 17 (`0xC1690840`, same shape) (static). PUPD_ENA resets to `0xFFFFFFFF`
(every group's pull enabled) and PUPD_SEL bits 16, 17, 19 and 20 reset to 1 (pull-up) (SPRUH79 sections
10.5.22-10.5.23, Tables 10-53 to 10-55). The groups, from the SPRS590 terminal tables' "CP[n]" column (GPIO-named
balls only): CP[16] GP2[0], [2], [3], [8], [9] and GP3[9..15]; CP[17] GP3[0..7] and GP4[8..15]; CP[19] GP5[10..15];
CP[20] GP5[0..6]. So the stock app removes the internal pull-ups from the key columns and rows, the encoders, the
power key and source pins, the power hold and every GP4 audio pin (inference: the board has its own pulls on the
inputs, since the keys and encoders work).

Key column 6, GP3[9] (PINMUX7 nibble 6), is not muxed to GPIO by the app or the bootloader. PINMUX7 bits 27:24 reset
to 0, "pin is 3-stated" (SPRUH79 Table 10-29), and SPRS590 section 3.6 says "the input from each pin is always routed
to all of the peripherals that share the pin; the PINMUX registers have no effect on input from a pin". So GPIO
IN_DATA reads the GP3[9] pad without any mux write, which is why column 6 works. The same holds for any pin: input
needs no mux, only output does (HW-19).

## GPIO (`0x01E26000`)

Bank pairs share registers: bank 2n in bits 0-15, bank 2n+1 in bits 16-31 (TI SPRUFL8B). Register offsets per pair n:
DIR 0x10 + 0x28n, OUT_DATA +0x14, SET_DATA +0x18, CLR_DATA +0x1C, IN_DATA +0x20. A DIR bit of 1 is an input
(reset: all inputs).

| Pin | Role | Direction, level (simulated unless noted) |
|---|---|---|
| GP2[0..5] | key-matrix rows | outputs; one high at a time (CLR_DATA 0x3F, SET_DATA 1 << row): rows are active high |
| GP3[1..6], GP3[9], GP3[11] | key-matrix columns 0-5, 6, 7 | inputs (directions left at reset) |
| GP5[10] | one extra key, active low, read with row 0 as bit 4 | input |
| GP3[10], [12], [14], [15]; GP5[0], [2], [4], [5], [7], [8] | encoders | inputs |
| GP2[11] | OLED data (1) / command (0) | output (**device**, D1) |
| GP3[0] | power key, active low | input (simulated, `analysis/input_map.py`: `power_on_check`) |
| GP3[7] | power source: high = batteries (inference) | input (static) |
| GP4[11] | power hold | output, driven 1; latched by the bootloader (**device**, HW-24) |
| GP7[8] | SYNC IN: edge interrupt, edge = POLARITY IN (see "SYNC IN / SYNC OUT") | input, rising edge at set-up (SET_RIS_TRIG) |
| GP7[9] | SYNC OUT: 15 ms pulses, 2 per quarter note, level = POLARITY OUT | output, driven 0 at set-up |
| GP4[0], GP4[1] | SD card detect (low = card) and a second SD pin | input / output 0 (detect simulated: `sd_card_detect_raw` returns 1 with GP4[0] low; GP4[1] static, [01-platform-map.md](01-platform-map.md) "SD card") |

**Audio pins: the state the board set-up puts them in** (simulated, `0xC169CD20` → `0xC16497B8`, identical in all
three products; HW-13, HW-16; roles from the platform map, "Codec set-up", mostly inference):

| Pin | Set-up state | Later | Role |
|---|---|---|---|
| GP4[14], GP4[15], GP4[12] | output, low | the power sequence `0xC1649448(1)` drives GP4[14], then GP4[15], then GP4[12] high (2 and 5 tick waits between), after the codec is set up and unmuted; the app never drives them low again | analogue power / amplifier enables, brought up last (inference) |
| GP4[13] | output, high | — (the board set-up is its only user; no helper, no other read of its handle B14+12) | not identified; fixed high |
| GP4[10] | output, low | `0xC1649654(0)` drives it high (active-low setter) as the first action of both app start paths (MainDelegate `0xC154A5D4`, a second start path `0xC1630DB4`), one tick before the codec is reset over I2C; never low again | candidate: codec RESET (active low on the AIC3106, SLAS509G terminal list) (inference) |
| GP2[8] | output, high | `0xC1649420`: = SYSTEM > SPEAKER MUTE (g_settings+0x48), applied at start-up (`0xC158B7BC`) and on every change (`0xC158D00C`); the factory test page also drives it | speaker mute, active high (high = speaker off); muted from board set-up until the setting is applied |
| GP2[9] | output, high | `0xC1678640(m)` sets GP2[9] = m and codec DAC volume registers 43/44 = muted / 0 dB together: m = 0 at start-up (`0xC154A838`), 1 in the power-off handler (`0xC154AE24`), and on the factory test page | output mute, active high, driven with the DAC mute (inference: an analogue mute after the codec) |
| GP1[2] | output, low | driven high only by the action wrapper `0xC15F1100` (REC SRC 0, built-in mic, simulated) and the test page; driven low by `input_l_gain_apply` and by `0xC158D184` (from settings +0x14) | built-in mic switch (inference from REC SRC 0 being its only setter) |
| GP1[3] | output, high (active-low setter `0xC1649680`: 0 = high, 1 = low) | driven only by the line PAD code (simulated, `analysis/pad_map.py`): low when REC SRC steps to 8 or 10 (PAD on, `pad_apply(1)` `0xC15F1290`, through `0xC15F0E80`) and in the PAD routes 8 and 13 of the input dispatcher `0xC15F1A84`; high when it steps to 7 or 9, when the page leaves 8 or 10, and at start-up while the PAD is off (`0xC158B780`, `0xC158D184`). `0xC15F0E80` runs only for PAD on, not on every input change | line PAD switch, low = PAD on (inference from the code; the manual gives LINE PAD -20 dB; HW-29) |
| GP7[14] | output, high (active-low setter) | the input dispatcher `0xC15F102C(route, gain, hiz)` drives it low when hiz = 1 and high otherwise; hiz = 1 for the INPUT L Hi-Z and mic routes, with or without the GP7[15] stage (routes 2 and 5 leave GP7[15] off) | INPUT L front-end select: low for the INPUT L Hi-Z and mic routes (2-6 in "Input routes"), high for line, PAD and the INPUT R routes (simulated). Electrical meaning inference (manual: INPUT L switchable 10 kΩ / 1 MΩ) |
| GP7[15] | output, low | INPUT L gain presets | INPUT L +10 dB Hi-Z gain stage (high = on) |
| GP5[11] | output, low | INPUT R gain presets | INPUT R mic preamp stage, about +28.8 dB (high = on) |
| GP3[8] | input | read by `audio_mix_input_monitor` (with REC SRC 0 the input is mixed only while it reads high), the tail of `audio_fill_input_block` (with REC SRC 0 and the pin low it stores 2 in the input block's first word), a change watcher `0xC15F12E8` (caches the level at B14+840 and calls a delegate on change) and the page title bar. `input_l_gain_apply` does not read it (simulated, modes 0-7, pin low and high) | a jack detect (inference): the INPUT jack or the headphone jack, which would fit the manual's speaker rule ("Built-in mic and the speaker"); open |

Copying this table and the power sequence reproduces the stock electrical state of the audio path without knowing
every pin's role; the M1 test image did so and made sound (**device**, HW-61). GP2[15] and GP7[11..13] belong to an
LED "frame engine" whose start and stop functions have no caller (LEDs go through the panel MCU on this unit).

**Key matrix** (simulated, `analysis/input_map.py`: the stock `control_switch_poll` run with every one of the 48
keys held alone and with GP5[10] low; `ControlScan::scan` `0xC1691740`, `select_row` `0xC16A1EE0`; layout in the
platform map, "Panel input"; HW-37): select row r by driving GP2[r] high and the other rows low, then read GP3[15:0]
(`IN_DATA` of pair 1, bits 16-31) and form the column byte: bits 0-5 = GP3[1..6], bit 6 = GP3[9], bit 7 = GP3[11].
Key n is row n / 8, column n % 8. In row 0, bit 4 is replaced by NOT GP5[10]. The stock code scans in the 1 ms input
task. The simulation models a held key as its column reading high while its row is driven high, which is how the
code reads it. **Device** (HW-47, D1 run 7): a test image scanning this way reads every key; STEP n is bit 31 + n
(STEP 1-8 = row GP2[4] columns 0-7, STEP 9-16 = row GP2[5] columns 0-7).

**Key timing and debounce** (simulated 2026-11-15, `input_map.py` `Session.key_timing`, claim HW-51): there is no
debounce hardware, and `control_switch_poll` filters only releases. One row is read per poll, so each key is
sampled every 6 ms (the 1 ms input task over 6 rows). In scans of the key's own row, the same at every starting phase:

| Keys | Press | Release | Closed for one scan | Open for one scan while held |
|---|---|---|---|---|
| bits 0-31 (rows 0-3: knob pushes, function and cursor keys) | first closed scan (0-6 ms) | second consecutive open scan (6-12 ms) | registers | ignored |
| bits 32-47 (rows 4-5: STEP 1-16) | first closed scan (0-6 ms) | first open scan (0-6 ms) | registers | release, then a new press |

All 48 keys were run; the split is exactly at the 32-bit word boundary, which suggests the release filter works on
the low word only (inference; the mechanism, apparently a short history of readings from scanner+32, was not
decoded). Auto-repeat follows: 400 ms after a press, then every 100 ms (`control_switch_repeat_*`). So the stock
relies on the 6 ms sample spacing as its press debounce. **Device**, STEP 1 only (HW-56, session M1, 2026-11-16):
presses settle with one edge, releases with up to 7 edges over 175 µs, worst settle 784 µs in 20 presses, so the
6 ms spacing is ample for that key.

**Encoders** (simulated, `analysis/input_map.py`: the stock `encoder_poll_all` `0xC166DA48` run on modelled
pin levels): read GP3 and GP5, pack two quadrature bits per encoder; encoder i is `(word >> 2i) & 3` (phase; bit 0
the first pin) with pins (0) GP3[14]/[15], (1) GP3[12]/[10], (2) GP5[2]/[0], (3) GP5[5]/[4], (4) GP5[7]/[8]; the
test page labels them A, B, C, D, VALUE. Decoding: phase 3 (both high) is rest and clears the direction; the first
phase after rest sets it (1 = first pin high, second low: -1; 2: +1); **every arrival at phase 0 (both low) with a
direction set counts one step**; other changes count nothing. So a clean detent 3-1-0-2-3 is -1 and 3-2-0-1-3 is
+1, one step per detent; a bounce back into phase 0 counts again (3-1-0-1-0-2-3 is -2). The steps are reported to
the delegate every 16 polls if non-zero. An earlier hand reading of `encoder_update` (+1/-1 per quadrature change)
is not what the code does. **Device** (HW-47, D1 run 7): each detent is four quadrature edges, which a test image
counting every edge saw as four counts.

## OLED on SPI1 (`0x01F0E000`)

Set-up (simulated, `0xC167C7B4` then `OLEDDriver::init` `0xC1672298`; HW-6, HW-33), in order:
1. PSC1 module 10 on; PINMUX5 as above (SPI1 SCS0, CLK, SIMO0; GP2[11]); GP2[11] output.
2. SPIGCR0 = 0 (reset), then 1 (out of reset); SPIGCR1 = 3 (master, internal clock); SPIPC0 = `0x0E01`
   (SOMI, SIMO, CLK and SCS0 as SPI function pins, SPRUH79C 28.3.6, Table 28-14; SPI0 gets `0x0E03`, both chip
   selects). **Required** (**device**, HW-32, D1 run 2): without it a polled transfer never completes. The write is
   in the driver build `0xC1626468` → `0xC167140C`. (c6sim missed it until 2026-11-13: it gave a load four
   protected-load NOP cycles from the next fetch packet's header, which moved the store out of the branch's last
   delay slot; SPRUFE8B 3.10.2.2: PROT applies to the loads of its own fetch packet.)
3. SPIFMT0 = `0x00011308`: 8-bit characters, prescale 19 (186 MHz / 20 = 9.3 MHz; the app asks for 9 MHz),
   bit 16 set (clock phase); polarity 0, MSB first. SPIDEF = 0xFF (chip selects idle high).
4. SPIGCR1 = `0x01000003` (enable).
5. Panel commands (D/C low): `B3 F0`, `81 FF`, `A0 07`, `AF`. These fit an SSD1327-family 128 x 128 x 4-bit grey
   controller (inference; no part number seen): display clock, contrast, remap, display on.

Steps 1-5 with polled transfers drive the display on the unit (**device**, D1 runs 2-6).

Command bytes (polled, simulated): GP2[11] low; byte write `0x10` to SPIDAT1+3 (CSHOLD) and `0xFE` to SPIDAT1+2
(CSNR: CS0 active); for each byte, write it to SPIDAT1 (`0x3C`) and read SPIBUF (`0x40`) when it arrives; at the
end write `0x00` to SPIDAT1+3 to release the chip select.

Frame data (simulated, `oled_write_data` `0xC16723A8`, 8192 bytes from `g_oled_framebuffer`): GP2[11] high; chip
select as above; EDMA3 CC0 PaRAM set 19 (event 19, SPI1 transmit): OPT `0x00113000` (TCC 19, completion interrupt),
SRC buffer, A_B_CNT = count << 16 | 1, DST `0x01F0E03C`, SRC BIDX 1, CCNT 1, no link; PaRAM set 18 (event 18, SPI1
receive) drains SPIBUF into one dummy word; events 18 and 19 enabled in shadow region 1 (S_EESR), then SPIINT0 =
`0x00010000` (DMA request enable); the app then waits for the EDMA completion (`0xC16A1BF0` with 1000: a pend with a
1000-tick timeout, inference), then releases the chip select. The buffer is written back from the cache
(`Cache_wb`) first. The polled byte loop sends the same 8192 bytes in about 7 ms at 9.3 MHz (the D1 test images do
this, **device**). The app waits at least 33 ticks between frames (`oled_frame_wait`).

**Pixel format** (**device**, claim HW-35, D1 runs 5 and 6; matches the stock's `draw_text_impl` `0xC167CCA0`,
static): 128 x 128, 4 bits per pixel, **not row-major**. The 8192 bytes are 64 blocks of 128 bytes; block `y >> 1`
holds the row pair (2k, 2k+1). In a block the first 64 bytes are the even columns and the next 64 the odd columns,
one byte per column; the even row is the low nibble (bits 3:0), the odd row the high nibble (bits 7:4):

    byte  = fb[128 * (y >> 1) + 64 * (x & 1) + (x >> 1)]
    shift = (y & 1) ? 4 : 0

The stock draws straight into this layout, with no conversion: in `draw_text_impl` (A4 = frame, A6 = text, B6 = point
{x, y}) the pixel store at `0xC167CDA4`..`0xC167CDEC` adds `128 * (y >> 1)` (`extu`/`shl 7` on y), `64 * (x & 1)`
(`extu b5,31,25`, x in B5) and `x >> 1`, and puts the grey in the high nibble when y is odd (`and 1,a7` → `shl 4`).
Grey 0 is black (inference from clearing to 0). An earlier reading took the frame as row-major, `fb[(y * 128 + x) /
2]` with even x in the low nibble (HW-34, superseded; HW-6's nibble wording is from that reading): it took the parity
from the wrong variable and missed the `64 * (x & 1)` term, and a test image drawing that way showed unreadable text
(D1 runs 3 and 4).

## Panel MCU on UART1 (`0x01D0C000`)

Set-up (simulated, `ADControllerUART::set_baud_rate(&g_ad_controller_uart, 460800)` and the two enables after it;
HW-7): PSC1 module 12 on; PINMUX4 nibbles 6, 7 = 2 (UART1 RXD, TXD); MDR = 0 (16x oversampling); DLL = 25, DLH = 0
(186 MHz / 16 / 25 = 465,000 baud); LCR = 3 (8 data bits, no parity, 1 stop); FCR = 7 then 1 (FIFOs on and cleared,
receive trigger 1 byte); IER = 5 (receive data and line status interrupts); PWREMU_MGMT = `0x2001` then `0x6001`
(URRST | FREE, then UTRST too: receiver, then transmitter out of reset, free-running under emulation) (SPRUH79
Tables 30-12 and 30-24). FCR leaves DMAMODE1 (bit 3) at 0, although SPRUH79 Table 30-12 says "always write 1"; it is
only needed when the EDMA services the UART, which the app does not do. The stock driver sends from a buffer drained
by `uart_isr` (CPU interrupt 9, event 46). **Device** (HW-36, HW-46, D1 runs 4-7): this set-up, polled through LSR
and THR, transmits (`C1` messages light their LEDs) and receives (the UART's internal-loopback self-test passes, an
`A0` is answered by `A1`, the `Bn` stream arrives).

Messages to the MCU (static; each a constant byte at B14+1622..1628, sent by `ADControllerUART` methods; HW-21):

| Bytes | Sent by the app | Meaning |
|---|---|---|
| `90` | start-up, after `set_baud_rate(460800)` and the two enables (`0xC161E790`, `0xC161E6E0`, both with 1) (`0xC161E680`, from `0xC154A8D4`) | not known (inference: start reporting). Sent before `power_on_check`, which reads the power key on GP3[0] directly, so the power check does not depend on it |
| `A0` | start-up, later: from `0xC154A804` in the normal-start function `0xC154A5CC`, which the `90` function (`0xC154A884`, reached through the pointer at `0xC16BAC94`) branches to at `0xC154AA0C`, after `B1` and `sd_card_hw_init` (`0xC161E5C0`) | requests the `A1` version reply (its last three bytes are the MCU version on SYSTEM INFO; **device**: `01 00 06`, HW-46) |
| `B1` | start-up, when `power_on_check` returns 1 (at once, `0xC154A918`) or 2 (after a 10 ms sleep, then a 990 ms sleep, `0xC154A944`) (`0xC161E4A0`) | not known (inference: "staying on, normal running"). Results (simulated, `input_map.py`, HW-38): 0 at once when GP3[0] reads high at entry (key not held), so no `B1`; 1 when it reads low for ten 50 ms checks, after driving GP4[11] high; 2 when the power manager's +28 byte is already set. A key released during the checks makes it release the power hold and never return |
| `B2` | power-off handler, early: right before the `0xC1549C38` check that chooses the power-off path (`0xC161E560`, from `0xC154ADC8`) | not known (inference: shutting down) |
| `C1 a b c v` | `led_set` → `panel_led_command` | set LED (a, b, c) to v; see "Panel LEDs" below |
| `C2` | one byte, no argument (the sender passes length 1). Power-off handler, late: after the DAC mute (`0xC1678640`, or `0xC1672070`) and before `settings_save` (`0xC159CD84`), the wait to 1 s and `power_hold_release` (`0xC15F3724` → `0xC161E72C`, from `0xC154AE5C`); also from `0xC15FBA60` and `0xC15FBC98` (not traced) | not known (inference: LEDs off / MCU standby before the supply is released) |
| `B0`, `91` | never: no call to their senders (`0xC161E500`, `0xC161E620`) and no pointer to them in the image | — |

The bytes are constants at B14+1622..1628 = `90 91 B0 B1 B2 A0 C2` (read from c6sim start-up memory), each sent
alone (length 1) by its own method through the send routine `0xC161E3C0` (buffer B4, length A6). `panel_map.py`
runs each method in the three products (identical; `test_panel_map.py`). The meanings stay inference: nothing in the
DSP code says what the MCU does with them.

**Panel LEDs** (simulated, `analysis/panel_map.py`; identical in SmplTrek 3.2.174, Lofi-12 XT 1.5.205 and
CyDrums 1.1.84; HW-20). `led_set(a, b, c, value)` (`0xC15F2A40`) keeps one byte per LED in `g_led_state[a][b][c]`
(`0xC1500578`, 3 x 6 x 8 = 144 bytes), sends nothing if the value is unchanged, and otherwise sends `C1 a b c value`.
The row-0 LEDs are sent directly (`panel_led_command`, no cache) by helpers that write all three a-planes with the
same value. One-line wrappers (77 in `0xC15F2A98`-`0xC15F3004`, more in `0xC15F30D4`-`0xC15F37B4`) fix (a, b, c) for
one LED each. The three "set everything" functions the app uses to clear the panel (`0xC15FB0E0`, `0xC15FB180`,
`0xC15FB2EC`) call one setter per LED and reach 115 distinct addresses:

| Group | Addresses | How the app drives it |
|---|---|---|
| 6 LEDs, row 0 | (0..2, 0, c), c = 0..5 | all three a-planes at once, same value, uncached (`0xC15F328C`, `0xC15F3324`, ...). **Device** (HW-48): c = 0 VOL L, 1 VOL R, 2 the microphone LED, 3-5 the VALUE encoder's blue, green, red; see "Row-0 LEDs" below |
| 15 pads, 3 channels each | table below | `pad_rgb_set(pad, v1, v2, v3)` (`0xC15F3068`) through three 15-entry setter tables filled at start-up (`0xC16ED668` v1, `0xC16ED628` v2, `0xC16ED5E8` v3); also `0xC15F30A4(pad, uint8_t rgb[3])` |
| 26 LEDs, 2 channels each | (a, b, c) and (a, b, c+1), c even, for (0, 3, 0..6), (1, 3, 0..6), (0, 4, 0..6), (1, 4, 0..6), (0, 5, 0..6), (1, 5, 0..6), (2, 5, 4), (2, 5, 6) | first channel set by the v2 clear, second by the v1 clear; STEP 1-16 and ten buttons (tables below) |

Pads (v1, v2, v3 of `pad_rgb_set`):

| Pad | v1 | v2 | v3 | | Pad | v1 | v2 | v3 |
|---|---|---|---|---|---|---|---|---|
| 0 | 2,1,5 | 2,1,4 | 2,1,6 | | 8 | 1,2,4 | 1,2,3 | 1,2,5 |
| 1 | 2,1,2 | 2,1,1 | 2,1,3 | | 9 | 1,2,7 | 1,2,6 | 1,1,0 |
| 2 | 0,1,5 | 0,1,4 | 0,1,6 | | 10 | 0,2,4 | 0,2,3 | 0,2,5 |
| 3 | 0,1,2 | 0,1,1 | 0,1,3 | | 11 | 2,2,7 | 2,2,6 | 2,1,0 |
| 4 | 1,1,5 | 1,1,4 | 1,1,6 | | 12 | 0,2,1 | 0,2,0 | 0,2,2 |
| 5 | 1,1,2 | 1,1,1 | 1,1,3 | | 13 | 2,2,1 | 2,2,0 | 2,2,2 |
| 6 | 2,2,4 | 2,2,3 | 2,2,5 | | 14 | 1,2,1 | 1,2,0 | 1,2,2 |
| 7 | 0,2,7 | 0,2,6 | 0,1,0 | | | | | |

Reading the channels as n = (5 - b) x 8 + c within each a, every pad takes three consecutive channels of one a (pad 7:
30, 31, 32), v2 the lowest. That fits a = one of three 48-channel LED drivers behind the MCU (inference; no part seen),
and v1/v2/v3 = three colours of an RGB LED. **Device** (HW-47, HW-48): v1 = red, v2 = green, v3 = blue. The
two-channel LEDs are green at even c and red at c + 1.

**STEP LEDs** (simulated 2026-11-14: each function below run in c6sim for steps 0-15 with `panel_led_command`
hooked). The stock keeps a 16-entry table `g_step_led_setters` (`0xC16EB448`, initialised data copied at start-up
from `0xC16FB424`), indexed by step - 1. Each entry is two wrapper pointers: +0 the red setter (odd c) and +4 the
green setter (even c). Five functions take the step index in A4 and use it:
- `step_led_set_rg` (`0xC15F31B4`): red = B4, green = A6;
- `step_led_set_both` (`0xC15F3510`): both = B4;
- `step_led_set_amber` (`0xC15F3568`): red = B4, green = B4 / 3 (multiply by `0x5556`);
- `step_led_set_green` (`0xC15F35F0`): green = B4;
- `step_led_set_red` (`0xC15F3734`): red = B4.

The manual lists the scene (STEP) button states as data loaded lit yellow, playing lit green, playback paused
blinking green, selected lit orange, unavailable or empty unlit (SmplTrek v3 Reference Manual, Home Screen, p. 18).
So `step_led_set_both` gives yellow and `step_led_set_amber` orange (inference from the channel colours; which caller
shows which state was not traced). Callers are the sequencer and step-editing code: scene setting, global track edit,
sample and file assign, and `0xC15D4xxx`-`0xC15D5480`. The six rows marked device are observed at that address
(HW-48). The order is the panel wiring, not the panel order.

| STEP | green (a,b,c) | sweep index 48a + 8b + c | red (a,b,c) | |
|---|---|---|---|---|
| 1 | 1,3,0 | 72 | 1,3,1 | |
| 2 | 1,3,2 | 74 | 1,3,3 | |
| 3 | 0,3,2 | 26 | 0,3,3 | device |
| 4 | 0,3,4 | 28 | 0,3,5 | device |
| 5 | 0,3,6 | 30 | 0,3,7 | device |
| 6 | 0,4,0 | 32 | 0,4,1 | device |
| 7 | 1,4,2 | 82 | 1,4,3 | |
| 8 | 1,4,4 | 84 | 1,4,5 | |
| 9 | 2,5,4 | 140 | 2,5,5 | |
| 10 | 0,3,0 | 24 | 0,3,1 | device |
| 11 | 2,5,6 | 142 | 2,5,7 | |
| 12 | 1,3,4 | 76 | 1,3,5 | |
| 13 | 1,3,6 | 78 | 1,3,7 | |
| 14 | 1,4,0 | 80 | 1,4,1 | |
| 15 | 0,4,2 | 34 | 0,4,3 | device |
| 16 | 0,4,4 | 36 | 0,4,5 | |

(2,5,4) and (2,5,6) are STEP 9 and STEP 11, not mode-button LEDs. Copies of the same setter array sit at `0xC16E5CC0`
and `0xC16E84B8`. The factory LED test page (`AppTestLED` slot +28) walks the array in this order: the four row-0
helpers (0,0,1), (0,0,5), (0,0,4), (0,0,3), then 26 two-channel pairs, then the pads. Its only strings are "LED TEST",
"RED : ", "GREEN: " and "BLUE: ", so it names no LED.

**Button LEDs** (the other ten two-channel LEDs; **device**, HW-48, 2026-11-14: each lit on the unit with the D1
test image's VALUE sweep (index n = 48a + 8b + c), green channel. The red channel at c + 1 is the same LED, not
swept per button).

| green / red | index | button (device) | lit by (`led_callers.py`) | prediction from the code before the check |
|---|---|---|---|---|
| (0,5,2) / (0,5,3) | 42 | HOME (orange: SYSTEM MENU) | home screen (the track edit pages clear it) / system menu, pool type select (clears it) | HOME / SYSTEM: right |
| (0,5,4) / (0,5,5) | 44 | MIXER (orange: FX) | mixer, FX setting / FX setting | MIXER / fx: right |
| (1,5,0) / (1,5,1) | 88 | REC (orange: sample save-as) | sample recording, sample save-as | REC / sampling: right |
| (1,5,2) / (1,5,3) | 90 | PROJECT (orange: pool) | project menu, file pages, drum kit menu / pool type select, file pages | PROJECT / pool: right |
| (1,5,4) / (1,5,5) | 92 | EDIT (orange: rec src) | the track edit pages, audio input setting / audio input setting | EDIT / rec src: right |
| (0,5,0) / (0,5,1) | 40 | FUNC | MainDelegate slot 11 (four calls) / only the clear-all | "FUNC or transport": FUNC |
| (0,5,6) / (0,5,7) | 46 | STOP | MainDelegate slot 11, mixer, sample recording, input and FX setting pages | "PLAY or STOP": STOP |
| (1,5,6) / (1,5,7) | 94 | PLAY | the same group plus `0xC16459B8` | "PLAY or STOP": PLAY |
| (0,4,6) / (0,4,7) | 38 | CLR | only the clear-all | octave button: wrong |
| (1,4,6) / (1,4,7) | 86 | OK | only the clear-all (`0xC15F37B4` = `led_set(1, 4, 6, v)`) | octave button: wrong |

So all 26 two-channel addresses are known: STEP 1-16 and these ten buttons. The octave buttons have no LED address
in the stock code (they are hard black plastic, so no LED is expected).

**All 144 addresses** (2026-11-15, `analysis/led_table.py`, pinned by `test_led_table.py`). The tool joins
`panel_map.py`'s simulated tables (pads, STEP setters, the clear-all groups) with the device evidence above (HW-47 pad
labels, HW-48 colours and anchors, the 2026-11-14 button sweep) and grades every address: 38 seen on the device at that
exact address, 24 whose LED was seen on another channel, 53 known only from the simulation, and 29 the stock never
drives. No device observation contradicts the simulation. The 29 unused addresses are (0,0,6..7), (1,0,6..7),
(2,0,6..7), (0,1,7), (1,1,7), (2,1,7) and the block (2,3,0)..(2,5,3); five of them were seen dark (HW-48), the rest are
untested. Read with the three-drivers inference above (channel n = (5 - b) x 8 + c), the block is driver 2's channels
0-3 and 8-23, and the other unused addresses are channels 39, 46 and 47 of a driver: consistent with three 48-channel
drivers on a panel that uses 115 channels. The remaining 101 addresses and the level-to-brightness steps are the
subject of the session plan L1 (`experiments/sessions/L1-led-map.md`, not run); `led_table.py --check-list` prints
the list.

**What the stock shows on the mode buttons** (SmplTrek 3.2.174, simulated 2026-11-14: each page method below run in
c6sim with every call outside it stubbed and `led_set` hooked). Each page lights its button in slot 13 (vfunc_13,
entering the page) and clears it in slot 1 (vfunc_1, leaving it). A main page sets green 6 and leaves red 0. The page
of the button's FUNC function sets green 3 and red 6, which is orange; the manual says of FUNC + EDIT "The button
lights orange" (SmplTrek v3 Reference Manual, "Selecting the recording source", p. 38), and its parts page lists the
same FUNC pairs (p. 8):

| Button | Main page, green 6 | FUNC page, green 3 + red 6 |
|---|---|---|
| HOME | HomeModeController (also the track edit pages clear it) | AppSystemMenu (SYSTEM MENU) |
| MIXER | AppMixer | AppFXSetting (fx) |
| REC | (sampling page: AppSampleRecording clears both; its slot 4 sets red, not traced) | AppSampleSaveAs |
| PROJECT | AppProjectMenu | AppPoolTypeSelect, AppFileSelect (pool) |
| EDIT | AppGlobalTrackEdit, AppAudioTrackEdit and the other track edit pages | AppAudioInputSetting (rec src) |

So the red channel of these five buttons is not a meaning of its own: in these pages it only mixes with green to
make orange. Pages also clear STEP 9 and 11 ((2,5,4..7)) on entry.

**FUNC, PLAY, STOP, CLR, OK** (SmplTrek 3.2.174, simulated 2026-11-15):
- **Key handler** (`MainDelegate` slot 11, `0xC154B3F8`): the switch message carries the key mask at +4..+11 and the
  state at +12 (1 = press; inference: FUNC lights on 1 and clears on 0). On a press the handler compares
  `g_control_switch_state` (the keys held) with fixed masks. Run with every outside call stubbed, for bits 19 (func),
  22 (play), 29 (stop), 23, 26, 30 and `track_or_sequencer_playing` returning 0 or 1:
  - FUNC pressed: FUNC green 6; FUNC released: FUNC green 0. FUNC's red is only ever cleared.
  - FUNC held + PLAY pressed: PLAY green 3 + red 6 (orange); FUNC held + STOP pressed: STOP green 3 + red 6. The
    manual's parts page gives FUNC + PLAY as rewind and FUNC + STOP as fast forward (p. 8).
  - PLAY or STOP released: both channels of that button cleared, only when nothing is playing.
  - Pressing PLAY or STOP alone sets no LED here.
- **Playback state:** `0xC16459F0` (reached from HomeModeController and AppMixer slot 4), run over all 2048
  combinations of its eleven callees' results, either sets PLAY green 6 with STOP red 6 + green 6 (through
  `stop_led_set_rg` `0xC15F3194`: red = A4, green = B4), or clears all three. The same three-call pattern (6, 6, 6 or
  0, 0, 0) sits in the HomeModeController, AppMixer, AppFXSetting, AppAudioInputSetting and AppSampleRecording
  handlers (static reading). So while playing, PLAY is green and STOP is red + green at equal value, which is
  yellow by the same mix as the scene buttons' "lit yellow" (inference). AppSampleSlice slot 14 uses its own
  pattern (PLAY green with STOP red; read statically only, not simulated).
- **CLR and OK:** no call to their setters and no pointer to them in the image apart from the clear-all functions
  (static). The factory LED test reaches LEDs through a run-time array that was not checked for these two. So the
  app appears never to light them in normal use.

**Row-0 LEDs** (SmplTrek 3.2.174, static and simulated 2026-11-14; HW-49; the device names are from the VALUE sweep,
HW-48). Two functions drive them, each through the row-0 helpers (all three planes, value 6 on, 0 off):
- **c = 0-2, VOL L, VOL R, microphone: `ClippingLED`.** Its `std::function<void(Foundation::PWMEvent)>` lambda
  (call operator `0xC16A9CE0`) passes its captured channel (0 or 1) and the event to `0xC166CC00`. Event 1 sets 6,
  event 0 sets 0, event 3 clears all three. Which LED a channel lights depends on REC SRC (g_settings+0x10, read
  by `0xC158BC30` -> `0xC15950E4`), simulated for all 26 sources:

  | REC SRC | channel 0 | channel 1 |
  |---|---|---|
  | 0 built-in mic | microphone (c = 2) | nothing |
  | 1-3 Gtr on INPUT L | VOL L | nothing |
  | 4-6 dynamic mic on INPUT R | nothing | VOL R |
  | 7, 8 stereo line | VOL L | VOL R |
  | 9, 10 mono line on INPUT L | VOL L | nothing |
  | 11 USB, 12-25 resampling | VOL L | VOL R |

  So each channel lights the LED of the input that feeds it (the same split as "REC SRC, per source"). What triggers
  it (static, 2026-11-15): the input meter `0xC15F1340`, called once per block from `audio_render_main`
  (`0xC159B2E4`) only while REC SRC < 12, and from two more sites at `0xC1599F14` / `0xC1599F64` (not traced). Per
  channel it compares a float peak with 0.70795 (`0x3F353BEF`, -3.0 dBFS) and, when above, calls the trigger
  `0xC166CD90(channel)`. The trigger starts that channel's blink (count 4 at +20, start tick at +16,
  `0xC167C2E0(obj, 1)`) unless one is already running (+24); the two channel objects are 56 bytes each at
  `0xC1281D90`. The meter skips its check until a frame counter (B14+852) reaches 12000 (0.25 s at 48 kHz); the reset
  at `0xC15F1BB0`, called from AppAudioInputSetting slot 8 (the input page's value change), zeroes the counter and
  stops both blinks (`0xC166CD58`). So the VOL L, VOL R and microphone LEDs flash when the input feeding them peaks
  above -3 dBFS (inference from the code; not seen on the device).
- **c = 3-5, the VALUE encoder (blue, green, red): the TEMPO LED.** `0xC15F3684` starts it only when the byte at
  B14+1054 is set. That byte is 1 in the start-up data (c6sim start-up state), and its only writer, `0xC15F3284`, has
  no call, branch or pointer in the image, so the gate is always open (static). The start goes through `0xC1683B68`,
  which stores its argument at B14+1324 and starts a timer. The handler `0xC1683B58` (a plain `void (*)(PWMEvent)`,
  registered at start-up by `0xC1683BC0`) lights on event 1 and clears otherwise. With B14+1324 = 1 it drives blue
  only (c = 3); with any other value it drives all three, so white (inference from the channel colours). Callers of
  the start, each only when the TEMPO LED setting (g_settings+0x108, `0xC1595678` via `0xC158CAAC`) is on: the
  sequencer's precount lambda (mode 1, blue), AppTestMode slot 17 (mode 1, blue), and MainDelegate slot 15 (mode = 1
  unless its first argument is 1 and the word at B4 is not positive; inference: white on the bar's first beat, blue
  on the others).

**Values:** one byte each; the stock uses 0, 3 and 6 on the button LEDs (above), 6 on row 0, and 0, 1, 3, 6 at other
setter call sites (partial static scan). **Device** (HW-47, D1 run 7): one LED takes 0-10; a value of 11 or more also
lights the neighbouring LED.

**Who drives which LED** (`analysis/led_callers.py`: each wrapper's address simulated, its callers static; which
button an LED is under is inference unless the button table above has it from the device). The b = 5 pairs are set
by the page that owns a mode, mostly from the same two page methods (vfunc_13 and vfunc_1 of each App class), which
fits mode-button LEDs:

| LED (a, b, c) | Set by (besides the clear-all functions) |
|---|---|
| (0, 5, 2) | HomeModeController, AppGlobal/Note/Drum/AudioTrackEdit |
| (0, 5, 3) | AppSystemMenu, AppPoolTypeSelect |
| (0, 5, 4), (0, 5, 5) | AppMixer (5, 4 only), AppFXSetting |
| (0, 5, 6), (0, 5, 7), (1, 5, 6) | AppMixer, AppSetRegionPhase, AppAudioInputSetting, AppSampleRecording, MainDelegate and two unnamed functions (`0xC151E538` near HomeModeController, `0xC1532D20` near AppSampleSlice): a shared state, perhaps recording |
| (1, 5, 0), (1, 5, 1) | AppSampleRecording, AppSampleSaveAs |
| (1, 5, 2), (1, 5, 3) | AppFileSelect, AppFileAssign, AppDrumKitEditMenu, AppPoolTypeSelect |
| (1, 5, 4), (1, 5, 5) | the track-edit pages, AppAudioInputSetting |
| (0, 5, 0), (1, 5, 7) | MainDelegate (vfunc_11) |
| row 0, c = 0-2 | `ClippingLED` (`0xC166CC00`) |
| row 0, c = 3-5 | the TEMPO LED (`0xC1683AEC`) |

The rows 1-4 wrappers and (0, 5, 1), (2, 5, 4..7) have no caller except the clear-all functions, so the app drives
those LEDs another way (as the pads, through setter tables; not traced).

**Messages from the MCU** (platform map, "Panel input"; parser simulated, `analysis/panel_rx_map.py`, HW-39): `Bn lo
hi` = analogue channel n (n = 0-15 from the status byte's low nibble), 14-bit `lo | hi << 7` (low byte first);
channels 0-14 are the pads (press at 800, release below 100 in the app), channel 15 the battery voltage; `A1` + six
bytes = MCU information (stored at uart+70..75, no callback). A packet may arrive split across reads (the state is
kept); a new status byte abandons a half-received packet (`B4 05 B5 01 02` gives channel 5 = 257 only); status bytes
of other types (`8x`, `9x`, `Cx`-`Fx`) are ignored. Bytes received while the parser is idle (each status byte, and
stray data bytes) also go to the delegate's slot 0, which is empty in every ADControllerDelegate of 3.2.174
(MainDelegate and the factory AppTestInterface), so the app drops them.

**Device**, the stream:
- Pad channels (HW-47, D1 run 7): 0 = TRK 8, 1 = TRK 1, 2 = TRK 9, 3 = TRK 2, 4 = TRK 10, 5 = TRK 3, 6 = GLOBAL 1,
  7 = TRK 4, 8 = GLOBAL 2, 9 = TRK 5, 10 = GLOBAL 3, 11 = TRK 6, 12 = USB AUDIO, 13 = TRK 7, 14 = EXT SRC.
- Rate (HW-55, session M1, 2026-11-16; HW-68, session M2, 2026-11-18): once streaming, the MCU sends every channel
  continuously whether or not a pad is touched, 4192-4196 `Bn` messages per second, each channel 262-263 times a
  second (every 3.7-4.0 ms), about 12.6 kB/s of the link's 46.5 kB/s, nothing but `Bn` messages. The channels come
  in a fixed repeating order 0 4 3 7 B D A E F 2 1 5 9 6 8 C. Characters inside a message are 21.4-22.0 µs apart;
  messages 64.9-1455.7 µs apart (bursts and pauses, mean 238.5 µs). Idle pad levels are 0-4; holding pads does not
  change any channel's rate. On the AC adapter channel 15 read 0-6; on batteries it is not measured.
- The stock drains the receiver with its receive interrupt. Polled test images: M2's loop doing nothing else saw no
  overrun; M1's polled loop saw a few FIFO overruns, and D1's 85 messages per second suggests its main-loop polling
  lost most messages (inference).
- Start order: the stock sends UART set-up at 460800, the two enables, `90`, the power check, `B1`, then `A0`. An
  `A0` sent about 100 ms after the link set-up went unanswered; one repeated 2 s later was answered (HW-46). Whether
  the MCU needs `90` or `B1` at all is not known.

At power-off the stock order is `B2`, DAC mute, `C2`, `settings_save`, a wait until 1 s has passed,
`power_hold_release` (`MainDelegate::handle_power_message`, `0xC154ADC8`-`0xC154AEA0`).

## Audio: codec, I2C0, McASP0 and the DMA ring

All simulated in the three products (`0xC1621854` audio hardware set-up, then `audio_start` `0xC1621574`); the codec
register writes are recorded at `codec_write`, because the I2C bytes themselves move in `i2c0_isr`. **Device**
(HW-61, session M1 part A, 2026-11-16): the M1 test image ran this sequence (pins, I2C0, the 40 codec writes, McASP0,
the EDMA ring including its 255-word first transfer, unmute, power enables) and played tones on the headphones.

**Clocking** (HW-10, HW-14). The codec is a TI TLV320AIC3106 (identity below) at I2C address 0x18, and it is the
clock master: it makes the bit clock and word clock (48 kHz) from its PLL, and McASP takes both from outside
(ACLKXCTL CLKXM = 0, AFSXCTL FSXM = 0). The receive section runs from the transmit clocks (ACLKXCTL ASYNC = 0; SPRUH79
Table 23-37: "in this mode, the receive bit clock is an inverted version of the transmit bit clock", and ACLKRCTL has
no effect, Table 23-25). AHCLKX0 is muxed but McASP does not drive it (AHCLKXCTL = 0, external). The codec's master
clock (MCLK) must be **24.576 MHz**: with the PLL on and register 102 not written (PLLCLK_IN = MCLK, SLAS509G Table
10-111), P = 2, J = 8, D = 0 and R = 1 (register 11 not written, reset R = 1, Table 10-19), fs(ref) = MCLK x K x R /
(2048 x P) (SLAS509G section 10.3.3.1, equation 2) is 48 kHz only for MCLK = 24.576 MHz; 44.1 kHz (J = 7, D = 3500)
gives the same MCLK, and both settings meet the data sheet's PLL conditions (10-20 MHz after P, J 4-11 with D
non-zero, 80-110 MHz out). The DSP's own 24 MHz would give 46.875 kHz, so MCLK is a separate 24.576 MHz source on the
board (inference; it is not seen in code). TI's StarterWare example for the C6748 EVM (`examples/evmC6748/mcasp/aic31.c`)
programs P = 4, J = 16 for the same 24.576 MHz, and Sonicware's codec functions are a modified copy of that file
(same function shapes; P/J, the dropped writes to registers 98, 101, 102 and 11, and the output set-up differ).

**I2C0** (`0x01C22000`): PINMUX4 nibbles 2, 3 = 2. Set-up `0xC1671E90`: ICMDR = 0 (reset), ICPSC = 2 (24 MHz / 3 =
8 MHz module clock), ICCLKL = ICCLKH = 35 (8 MHz / (2 x (35 + 5)) = 100 kHz), ICSAR = 0x18, ICMDR = 0x20 (IRS: out of
reset), ICEMDR = 0. These are what TI StarterWare's `I2CMasterInitExpClk(base, 24 MHz, 8 MHz, 100 kHz)` computes;
I2C0 runs from PLL0_AUXCLK, the 24 MHz oscillator (SPRUH79 Table 7-1). A register write is a 2-byte transfer: ICCNT =
2, ICMDR = `0x0E00` (STP | MST | TRX: master transmitter, stop when the count is done), ICMDR |= `0x20` (IRS), ICIMR =
`0x30` (SCD | ICXRDY: stop detected, transmit ready), ICMDR |= `0x2000` (STT: start) (bit names SPRUH79 Tables 21-14
and 21-6); the ISR feeds the two bytes (register, value) to ICDXR. EDMA channels 25 and 26 are claimed by `i2c_open`
but codec writes do not use them. Correction (TI document): SPRS590 Table 6-12 has 24 = I2C0 receive, 25 = I2C0
transmit, 26 = I2C1 receive, so the pair is not I2C0's receive/transmit pair (the claim was not re-traced; codec
writes do not use them either way). The app never reads a codec register (no I2C receive transfer was found): the
routing functions keep shadow bytes for registers 19 and 22 (`0xC1502D6D`, `0xC1502D6F`) instead.

**Codec identity.** The writes use MIC3L/R mixing (registers 17, 18), the line-input mixers for both ADCs
(19, 21, 22, 24), the programmable ADC high-pass filter (page 1 registers 65-76 and page 0 register 107), the
DAC_x3 direct line-output path (register 41), and the dormant functions below use the HPLCOM/HPRCOM drivers
(54, 58, 71); all of these are in the AIC3106 register map (SLAS509G section 10.6). Whether the cheaper family members
(AIC3104 / AIC3105) lack any of them was not checked (their data sheets are not here), so "AIC3106" rests on every
register the code uses being an AIC3106 register, not on excluding the others. The part marking has not been read.

**Codec registers**, in the order written (page 0 unless noted; decoded with `analysis/codec_map.py`, SLAS509G
table numbers in brackets; * marks values whose meaning was corrected against the data sheet):

| Step | Writes (register = value): meaning |
|---|---|
| reset | 0 = 0: page 0 (T10-8); 1 = 0x80: software reset, self-clearing (T10-9); one tick |
| interface | 9 = 0x37: I2S, 32-bit words, continuous bit clock, DAC and ADC re-sync with soft mute (T10-17); 10 = 0: data offset 0 (T10-18) |
| rate 48 kHz | 2 = 0: ADC and DAC at fs(ref) (T10-10); 3 = 0xA2: PLL on, Q = 4 (unused with the PLL), P = 2 (T10-11); 4 = 0x20: J = 8 (T10-12); 5 = 0, 6 = 0: D = 0 (T10-13/14); 7 = 0x0A *: fs(ref) = 48 kHz (AGC timing), left DAC plays left, right DAC plays right, no dual rate (T10-15) — register 7 is the datapath set-up, not part of the PLL; 8 = 0xD0 *: BCLK and WCLK outputs (master) **and bit 4: the clocks keep running while the codec is powered down** (T10-16) |
| PGA | 15 = 0, 16 = 0: left and right ADC PGA unmuted, 0 dB (reset is muted, T10-23/24) |
| ADC high-pass (page 1) | 0 = 1; 65-70 and 71-76 = 7F D5 80 2B 7F AA: N0 = 32725, N1 = -32725, D1 = 32682 for the left and right ADC, H(z) = (N0 + N1 z^-1) / (32768 - D1 z^-1) (SLAS509G section 10.3.3.2.1, equation 5; T10-176..187); 0 = 0; 107 = 0xC0: use the programmable coefficients for both channels (T10-116; bits 5:4 = 0 is the reset value) |
| inputs | 17 = 0xFF, 18 = 0xFF: MIC3L and MIC3R not connected to either ADC (T10-25/26); 21 = 0xF8, 24 = 0xF8 *: LINE1R → left ADC and LINE1L → right ADC not connected, **with D7 = 1 (fully differential)**, which the data sheet requires to match the other connection of the same input (T10-29/32); 19 = 0x84, 22 = 0x84: LINE1L → left ADC and LINE1R → right ADC, fully differential, 0 dB, ADC channel powered, PGA soft-step once per fs (T10-27/30) |
| outputs | 37 = 0xC0: both DACs powered, HPLCOM = differential of HPLOUT (unused) (T10-45); 41 = 0x50 *: left DAC → DAC_L3 and right DAC → DAC_R3, the direct paths to the line output drivers that bypass the output mixers (T10-49; section 10.3.5 recommends this path when the DAC only feeds the line outputs); 42 = 0x9C *: output driver power-on delay 800 ms, ramp-up step 4 ms, weak common-mode from the AVDD divider (T10-50); 86 = 0x0B, 93 = 0x0B *: LEFT_LOP/M and RIGHT_LOP/M 0 dB, unmuted; bits 1:0 are read-only status bits in the AIC3106 map (T10-95/102), so the written 1s have no effect (inference) |
| high-pass on | 12 = 0x50: left and right ADC high-pass on (T10-20); with register 107 set, the programmable coefficients apply |
| at start-up, later | 43 = 0, 44 = 0: DAC digital volume 0 dB, unmuted (T10-51/52; reset is muted), written with GP2[9] low by `0xC1678640(0)`; the power-off handler writes 0x80 (muted) with GP2[9] high |

Because register 41 selects DAC_L3/R3, the DAC_L1/R1 mixer paths carry no DAC signal, so the output-mixer routing
registers (47, 54, 64, 71, 82, 85, 92) have no effect in this configuration, and the headphone drivers (HPLOUT,
HPROUT, HPLCOM, HPRCOM) keep their reset state: not powered (D0 of 51, 58, 65, 72 resets to 0, T10-60 and following).
The only codec outputs in use are LEFT_LOP/M and RIGHT_LOP/M (HW-15). The headphone sound on the unit (HW-61)
therefore comes through the board's own amplifier after the line outputs (inference, "Outputs" below).

**Codec functions that write nothing at start-up** (simulated in the three products, identical; none has a caller or
a stored pointer in SmplTrek 1.0.65, 1.1.72, 1.2.86, 1.3.90, 1.4.99, 2.0.129, 3.0.148, 3.2.174, Lofi-12 XT 1.1.156,
1.2.179, 1.5.205 or CyDrums 1.1.84: the same wrapper set exists in every one with the same caller counts):

| Function (wrapper) | Writes | Meaning |
|---|---|---|
| `0xC161D758` (`0xC1678670`) | 82 = 92 = 0x80 \| v | DAC_L1 → LEFT_LOP/M and DAC_R1 → RIGHT_LOP/M, volume step v |
| `0xC161D798` (`0xC1678688`) | 71 = 0x80 \| v | DAC_R1 → HPRCOM, volume step v |
| `0xC161D7D4` (`0xC167869C`) | 54 = 0x80 \| v | DAC_L1 → HPLCOM, volume step v |
| `0xC161D7E8` (`0xC1678714`) | 58 = 0x69 (on) / 0x09 | HPLCOM +6 dB / 0 dB, unmuted, powered |
| `0xC161D894` (`0xC1678728`) | on: 82 = 0, 85 = 0x80; off: 85 = 0, 82 = 0x80 | LEFT_LOP/M from DAC_R1 instead of DAC_L1 |
| `0xC161D964` (`0xC1678768`) | 47 = 0x80 / 0 | DAC_L1 → HPLOUT on / off |
| `0xC161DD08` (`0xC1678700`) | 19 level field | LINE1L → left ADC level 0 to -12 dB |
| `0xC161DC6C`, `0xC161DCA0` | 15 = 16 = v; 17 = 18 = 0xF0 / 0xFF | both PGAs; MIC3R into both ADCs |

None of them would make sound with register 41 = 0x50 except the level and MIC3 ones. ELZ_1 play 3.1.149 (a different
product, possibly a different board) does drive the headphone drivers: its output set-up (static, around
`0xC27EEDD0`) writes 37 = 0xC0, 42 = 0x9C, 47 = 0x80, 51 = 0x09, 64 = 0x80, 65 = 0x09, 54 = 0x80, 58 = 0x09,
71 = 0x80, 72 = 0x09, 82 = 0x80, 86 = 0x0B, 92 = 0x80, 93 = 0x0B and leaves register 41 at reset (DAC_L1/R1, the
mixer path): every output driver on, fed from the DACs. That is StarterWare's `AIC31DACInit` extended to the COM
drivers. So the dormant SmplTrek functions are shared-library code for that kind of board, and the SmplTrek board
feeds its headphone jack and speaker from the line outputs (inference, below).

**McASP0** (`0x01D00000`; PSC1 module 7, SPRUH79 Table 8-2; pins ACLKX0, AFSX0, AHCLKX0, AMUTE0, AXR13 out, AXR14
in), in order (StarterWare's McASP driver functions, which the app contains; fields from SPRUH79 section 23.1):
RGBLCTL = XGBLCTL = 0 (reset); RMASK = XMASK = `0xFFFFFFFF`; RFMT = XFMT = `0x000180F0`: XDATDLY 1 (1-bit delay),
XRVRS 1 (MSB first), XSSZ 0xF (32-bit slot), XBUSEL 0 (data through the DMA port), no rotation (Table 23-35; section
23.0.21.4.1, Table 23-4: "to transmit in I2S format, use MSB first, left aligned, and also select XDATDLY = 01");
AFSRCTL = AFSXCTL = `0x110`: XMOD 2 (2-slot TDM, "I2S mode"), FXWID 1 (frame sync one word wide), FSXM 0 (external),
FSXP 0 (a rising edge starts the frame) (Table 23-36); ACLKRCTL = 0 (ignored, synchronous); ACLKXCTL = `0x80`: CLKXP
1, the transmitter shifts data out on the falling edge of ACLKX so the codec samples it on the rising edge; ASYNC 0;
CLKXM 0, external (Table 23-37); AHCLKRCTL = AHCLKXCTL = 0 (external high clock, not used); RCLKCHK = XCLKCHK =
`0x00FF0005`: clock-check prescaler /32, minimum 0, maximum 255 (Table 23-43, so it never flags a clock failure in
practice); RTDM = XTDM = 3 (slots 0 and 1); SRCTL14 = 2 (receive), SRCTL13 = 1 (transmit); PFUNC = 0, PDIR =
`0x2000` (AXR13 out, all clock pins inputs); XINTCTL = RINTCTL = `0x0F` (error interrupts); then the start: GBLCTL =
2 (RHCLKRST), `0x202` (XHCLKRST), EDMA events enabled, RSTAT = XSTAT = `0xFFFF`, GBLCTL = `0x206` (RSRCLR), `0x606`
(XSRCLR), `0x60E` (RSMRST), `0x61E` (RFRST), `0xE1E` (XSMRST), `0x1E1E` (XFRST). This is SPRUH79's initialisation
procedure (section 23.0.21.1.2) steps 1, 3, 4, 6, 7, 9 and 10 in order; step 5 (bit clock dividers) is skipped, which
the procedure allows when external serial clocks are running, and they are, because the codec is set up first and
register 8 bit 4 keeps its clocks running. The FIFO is not used (WFIFOCTL / RFIFOCTL left at reset). CPU interrupt 6
(event 61) only clears errors. AMUTE0 is muxed but the app writes no AMUTE register.

**Channel order** (simulated with `analysis/audio_slot_map.py` and `rec_src_map.py`, documents as cited; HW-26):
- Transmit (simulated, identical in the three products): `audio_block_process` writes the first plane of the output
  block (+16) to the even words of the TX buffer and the second plane (+16 + 4 x frames) to the odd words.
- Receive (simulated, SmplTrek only; the other products' engines are their own code): `audio_fill_input_block` fills
  input plane 0 from the selector at g_settings+0x1C and plane 1 from +0x20 (1 = even words, 2 = odd words, 0 =
  silence; +0x24 non-zero forces 1, 2). The REC SRC selector sets them per source (table under "Inputs" below).
- **Even words = left, odd words = right.** On the output this is **device** (HW-61, session M1 A4-A6, 2026-11-16,
  confirmed 2026-11-17): even words only are heard in the left ear only, odd only in the right, on the headphones.
  Line out is not observed. On the receive side it rests on the stock's sources: every source that powers one ADC
  reads both planes from one slot, and always the matching one: the built-in mic (MIC3R into the left ADC, right
  ADC powered down, SLAS509G Table 10-30 D2), Hi-Z and mono line (LINE1L, left ADC only) read even words; the dynamic
  mic (LINE1R, right ADC only) reads odd words; stereo line reads even words into plane 0 and odd into plane 1. With
  the opposite order those mono sources would record a powered-down ADC, i.e. silence (inference: a powered-down ADC
  channel sends zeros), and the manual's built-in mic, Hi-Z and mono-line recording would not work. Register 7 =
  0x0A sends the left channel to the left DAC (T10-15).
- The documents read alone point the other way: the AIC3106 puts the left channel after the falling edge of the word
  clock (SLAS509G section 10.3.2.3), and McASP with FSXP = 0 starts a frame on the rising edge (SPRUH79C Table 23-36,
  Figure 23-8), which would make slot 0 the right channel. Why the board behaves otherwise is not known (a frame
  alignment at start-up, an inverted word clock on the board, or a misreading here). An earlier reading of this
  section took the documents' order; the stock and the unit disagree with it.

**DMA ring** (EDMA3 CC0, `0xC1621848`; events 0 and 1 are McASP0 receive and transmit, SPRS590 Table 6-12; the DMA
port `0x01D02000` is "McASP 0 Data" in the SPRS590 memory map; OPT fields SPRUH79 Table 16-15):

| PaRAM set | Role | OPT | SRC → DST | A, B count | Link |
|---|---|---|---|---|---|
| 0 (channel 0, McASP receive event 0) | first receive block | `0x00100201`: TCINTEN, TCC 0, FWID 2 (32-bit), SAM 1 (constant source), A-synchronised | McASP data port `0x01D02000` → RX buffer, DST step 4 | 4, 255 | set 65 |
| 64, 65 | receive ping / pong | same | → RX buffer A / B | 4, 256 | 65 → 64 → 65 |
| 1 (channel 1, McASP transmit event 1) | first transmit block | `0x00001202`: TCC 1, FWID 2, DAM 1 (constant destination), no interrupt | TX buffer → `0x01D02000`, SRC step 4 | 4, 255 | set 67 |
| 66, 67 | transmit ping / pong | same | TX buffer A / B → | 4, 256 | 67 → 66 → 67 |

256 words = 128 stereo frames of 32 bits (SmplTrek; Lofi-12 XT and CyDrums use 192 = 96 frames, otherwise
identical). Events 0 and 1 are enabled in shadow region 1. Each receive completion raises CPU interrupt 5 (EDMA3 CC0,
event 8); the app's handler then processes one block (platform map, "Audio engine interface": the free buffers are
found from the PaRAM link fields, samples are float x 2^31). The buffers are in L1D RAM (`0x11F00000`-`0x11F00FFF`).

**Audio GPIOs**: see the table under "GPIO", and the stock order in "Start sequence" below.

## Audio paths, start sequence, power order, unknowns

How sound gets in and out of this board. "Simulated" = run in c6sim in SmplTrek 3.2.174, Lofi-12 XT 1.5.205 and
CyDrums 1.1.84 with identical results (`analysis/codec_map.py --compare`: 89 of 89 calls, codec functions, input
actions and gain appliers); "static" = read from the listing; "manual" = SmplTrek v3 Reference Manual r2 ("Specs",
"Relationship between built-in speaker and mic", "Selecting the recording source").

**Outputs.** The AIC3106 has seven output drivers (SLAS509G section 10.3.5-10.3.6): HPLOUT, HPROUT, HPLCOM, HPRCOM
(high-power, 16 Ω headphone class), LEFT_LOP/M and RIGHT_LOP/M (fully differential line outputs, at least 10 kΩ load,
1.414 Vrms full scale differential, section 8.5, Electrical Characteristics) and MONO_LOP/M. The stock apps power and
use only LEFT_LOP/M and RIGHT_LOP/M, fed directly from the DACs (register 41 = 0x50). The unit has three outputs
(manual, "Specs"): balanced STEREO LINE OUTPUTS (1/4" TRS, max +6.5 dBV), a PHONES jack (3.5 mm stereo) and a 1.5 W
4 Ω mono speaker; a VOL knob adjusts the headphone and speaker level and is not one of the five encoders the code
reads. So (inference) the line outputs feed the line-out jacks through a buffer, and the VOL pot, a headphone
amplifier and a speaker amplifier sit after them on the board: none of that is visible to code except these pins:
- GP2[9], output mute, active high, driven together with the DAC volume mute (codec registers 43/44);
- GP2[8], speaker mute, active high, = the SYSTEM > SPEAKER MUTE setting; high from the board set-up until settings
  are applied;
- GP4[14], GP4[15], GP4[12], raised in that order (2 and 5 ticks apart) after the codec is running: amplifier /
  analogue power enables (inference); never lowered by the app.

The manual says the speaker turns off when headphones are plugged in. No GPIO, GPIO interrupt (only bank 7, SYNC IN,
is enabled), IOObserver poll or codec headset-detect register (13, 14, 96, 97: never written or read) is involved, so
the switching is in hardware, a switched jack (inference). The manual's other speaker-off case (built-in mic as the
recording source with monitoring, EXT SRC or LOOP / GLOBAL recording on) was not found as a GP2[8] write; GP2[8]'s
only writers are the SPEAKER MUTE paths and the test page, so that case is either handled in the mix or by a path
not traced (open; see "Built-in mic and the speaker").

**Inputs.** The codec's ADC inputs in use are LINE1L and LINE1R, fully differential (registers 19/21/22/24, D7 = 1),
and MIC3R (registers 17/18) for the built-in mic. Each ADC can take LINE1L, LINE1R or MIC3R; the app builds the
layouts from four routing actions (`0xC15F0FC0` R → right ADC, `0xC15F0FD2` R → left ADC, `0xC15F0FEA` L → right ADC,
`0xC15F1004` L → left ADC; each also disconnects the other line input from that ADC) and gain presets (simulated;
HW-17):

| Gain action | Pins | PGA |
|---|---|---|
| `0xC15F0E80` reset | GP1[3] low, GP7[15] low, GP5[11] low | — |
| `0xC15F0EA0` / `0EB2` / `0ECA` / `0EE2` | GP5[11] high (INPUT R mic stage) | right +21 / right 0 / left +21 / left 0 dB |
| `0xC15F0F00` / `0F12` / `0F2A` / `0F42` | GP7[15] high (INPUT L Hi-Z stage) | right +10 / right 0 / left +10 / left 0 dB |
| `0xC15F0F60` / `0F72` | GP5[11] low | right 0 / left 0 dB |
| `0xC15F0F8A` / `0FA4` | GP7[15] low | right 0 / left 0 dB |

The dispatcher `0xC15F102C(route, gain, hiz)` drives GP7[14] low when hiz = 1, high otherwise, then runs both actions;
hiz = 1 accompanies the INPUT L Hi-Z and mic presets, also those that leave GP7[15] off (modes 1 and 4).
`input_r_gain_apply(level)`: 0 and 3 → GP5[11] off, PGA 0 dB; 1 → GP5[11] on, 0 dB; 2 → on, +21 dB (the platform map
had 1 and 2 swapped). `input_l_gain_apply(mode)` 1-6 → (GP7[15], left PGA) off/0, on/0, on/+10, off/0, on/0, and mode
6 off/0 with GP7[14] high; modes 1-5 drive GP7[14] low; all drive GP1[2] low. The manual's levels for comparison:
INPUT R mic LOW 0 / NORMAL +28.8 / HI +50 dB; INPUT L Hi-Z LOW 0 / NORMAL +10 / HI +20, mic LOW 0 / NORMAL +10; LINE
PAD -20 dB.

**REC SRC, per source** (simulated: `rec_src_select` `0xC158B990`, `analysis/rec_src_map.py`; HW-28; names from the
recorded-file prefix function `0xC156C804`, which the manual's "Name of the recorded file" table expands). The
selector stores the source at g_settings+0x10 (range [0,25], default 7) and, per source, the INPUT L mode (+0x14,
`input_l_gain_apply`), the INPUT R level (+0x18, `input_r_gain_apply`) and the two input-plane selectors (+0x1C,
+0x20; 1 = even words / slot 0, 2 = odd words / slot 1, see "Channel order"). End state of the ADC registers
(SLAS509G Tables 10-23..10-32):

| REC SRC | Source (manual) | L mode, R level | Left ADC | Right ADC | Planes from | Pins left by the selector |
|---|---|---|---|---|---|---|
| 0 | BltInMic, built-in mic | 0, 3 | on: MIC3R | off | slot 0, slot 0 | GP1[2] high, GP7[14] high, GP7[15] low, GP5[11] low |
| 1, 2, 3 | Gtr, Hi-Z on INPUT L, LOW / NORMAL / HI | 1 / 2 / 3, 3 | on: LINE1L, PGA 0 / 0 / +10 dB | off | slot 0, slot 0 | GP7[15] low / high / high; GP1[2] low |
| 4, 5, 6 | DyMic, dynamic mic on INPUT R, LOW / NORMAL / HI | 6, 0 / 1 / 2 | off | on: LINE1R, PGA 0 / 0 / +21 dB | slot 1, slot 1 | GP5[11] low / high / high |
| 7, 8 | LineSt, stereo line on INPUT L/R | 6, 3 | on: LINE1L | on: LINE1R | slot 0, slot 1 | GP7[14] high, GP7[15] low, GP5[11] low |
| 9, 10 | LineMn, mono line on INPUT L | 6, 3 | on: LINE1L | off | slot 0, slot 0 | as 7 |
| 11 | USB | 7, 4 | off | on: LINE1R | (not read: the fill gives silence) | GP1[2], GP7[15], GP5[11] low |
| 12-25 | ReSmp, resampling (track choice) | 21, 18 | off | on: LINE1R | (not read) | as 11 |

The mono sources do not route one input to both ADCs; they power one ADC and read both planes from its slot. GP1[2]
is driven high by source 0 only, so it belongs to the built-in mic (inference: a mic power or select switch), not to
the line PAD. The pairs 7/8 and 9/10 leave identical codec, pin and slot state in the selector; the PAD is set by
the REC SRC page around it (below).

**Line PAD** (simulated: `analysis/pad_map.py`, test `test_pad_map.py`; HW-29). REC SRC 8 and 10 are the line sources
with PAD on, 7 and 9 without. The page's value-change handler `0xC153EF40` (a4 = +1 / -1) moves within a source group;
for the line pairs it calls `pad_set(v)` (`0xC158C088`: g_settings+0x24 = (v == 1)) and `pad_apply(v)` (`0xC15F1290`)
with v = 1 on 8 or 10 and 0 on 7 or 9. The group-change handler `0xC153EEA4` lands on a group's first value and calls
`pad_apply(0)` when it leaves 8 or 10. At start-up the settings apply (`0xC158B780`) runs `pad_apply(pad_on())`, with
`pad_on()` = g_settings+0x24 != 0 (`0xC158C644`).

- `pad_apply(0)`: GP1[3] high, nothing else.
- `pad_apply(1)`: GP1[3], GP7[15] and GP5[11] low (`0xC15F0E80`), GP7[14] high. Codec: LINE1L into the left ADC and
  LINE1R into the right, both 0 dB with the ADCs powered (19 = 22 = 0x84), cross paths off (21 = 24 = 0xFC), PGA 0
  (15 = 16 = 0).
- `audio_fill_input_block` forces the input planes to (slot 0, slot 1) while the PAD is on, so LineMn with PAD (10)
  takes both slots, unlike 9. `0xC159A44C` returns 1 with the PAD on and 3 with it off; nothing reads the value
  ([06-audio-engine.md](06-audio-engine.md), simulated).

**Input routes.** The factory AUDIO TEST page (`0xC16140EC`) names 16 input routes (pointer table copied to
`0xC16ED2A8` at start-up) and shows the current pair, left and right ADC, from `0xC16EFC18` / +4. They are the route
numbers of the input dispatcher `0xC15F1A84(adc, route)` (a4: 0 = left ADC, 1 = right; b4: route), which that page and
`0xC158D184` call. Simulated for both ADCs (`pad_map.py`, `routes()`); "own" is LINE1L into the left ADC or LINE1R into
the right (register 19 / 22 = 0x84), "cross" the other jack (21 / 24 = 0x84), all at 0 dB input level:

| Route | Name | ADC input | PGA | Pins |
|---|---|---|---|---|
| 0, 14, 15 | OFF, L USB, R USB | none | 0 | INPUT L stage (GP7[15]) low for the left ADC, INPUT R stage (GP5[11]) low for the right |
| 1 | Built-In MIC | MIC3R (17 / 18 = 0xF0) | — | GP1[2] high |
| 2, 3, 4 | L HiZ Low, L HiZ, L HiZ High | own | 0, 0, +10 dB | GP7[14] low; GP7[15] low, high, high |
| 5, 6 | L D-Mic U-Low, L D-Mic Low | own | 0 | GP7[14] low; GP7[15] low, high |
| 7 | L LineIn | own | 0 | GP7[14] high, GP7[15] low |
| 8 | L LineIn PAD | own | not written | GP7[14] high; GP1[3], GP7[15], GP5[11] low |
| 9, 10, 11 | R D-Mic U-Low, R D-Mic, R D-Mic High | cross | 0, 0, +21 dB | GP7[14] high; GP5[11] low, high, high |
| 12 | R LineIn | cross | 0 | GP7[14] high, GP5[11] low |
| 13 | R LineIn PAD | cross | not written | as 8 |

"L" and "R" in the names are the jacks: the left ADC takes the R jack through the cross path. GP1[3] is one pin for
both jacks, so the PAD is one switch for the whole line input (inference).

No gain scaling reads +0x24, so the -20 dB of the manual is analogue, behind GP1[3] (inference: no digital path
found, and GP1[3] has no other user). PAD on = GP1[3] low with both line inputs routed as above; PAD off = GP1[3]
high.

**Built-in mic and the speaker** (simulated: `rec_src_map.py` `monitor_gate`; HW-30). The manual (v3 r2 p. 201,
"Relationship between built-in speaker and mic") turns the built-in speaker off when the source is the built-in mic
and monitoring is on, EXT SRC is ON or LOOP / GLOBAL is auditioning or recording, and whenever headphones are attached.
No code path does this through a pin or the codec. GP2[8] (speaker mute) is reached only from SPEAKER MUTE
(`0xC158B774`, at start-up and on change) and the test page. GP2[9] is reached only through `0xC1678640` (start-up,
power-off, test page). No data pointer or address load reaches either setter. A diff of every caller of the REC SRC
getter, with monitoring on and source 0 against 7, shows no codec or speaker-pin difference. The one source-0 rule is
in `audio_mix_input_monitor` (`0xC159AA54`): with monitoring on and source 0, the input is mixed only while GP3[8]
reads high. Other sources do not read the pin. The three later conditions of that function (`0xC15C5B00`,
`0xC15C5228`, `0xC15C5910`) apply to every source. Inference: if GP3[8] is the headphone-jack detect, the stock
monitors the built-in mic only into headphones. The headphone switch cuts the speaker in hardware (HW-15), and that
would match the manual's table. The listening session plan `experiments/sessions/D3-audio-pins-plan.md` (step 5, not
run) would tell: with built-in mic and monitoring on, no headphones, does the speaker still play the song while the
mic is silent?

The analogue "Input gain knobs" are not read by the DSP. At the codec, LINE1 input resistance is 20 kΩ at 0 dB input
level (SLAS509G section 8.5, "MIC1L/MIC1R inputs routed to single ADC", MIC1 being the LINE1 pins) and full scale is
0.707 Vrms at 0 dB PGA; the manual's 10 kΩ / 1 MΩ INPUT L impedances are therefore board front-end values. GP3[8]
(input) is read by the input code and draws the title-bar mic icon: INPUT jack detect (inference; it may be the
headphone jack instead, see above).

**USB audio** (static: the descriptors are in initialised data, read after the copy table from c6sim's start-up
memory, `0xC16EF048`-`0xC16EF218`, one descriptor per 16-byte slot; HW-18): Audio Control header (class 1.00, total
0x35, interfaces 1, 2, 3); input terminal 3 (USB streaming, 2 channels, L/R) → output terminal 4 (headphones, 0x0302);
input terminal 5 (microphone, 0x0201, 2 channels, L/R) → output terminal 6 (USB streaming); no feature unit (no host
volume control). Both streaming interfaces: AS general (terminal 3 / 6, PCM), format Type I, 2 channels, 2-byte
subframes, 16-bit, one discrete rate 48,000 Hz; endpoint `0x01` OUT isochronous adaptive and `0x82` IN isochronous
asynchronous, 196 bytes, interval 1 ms; class endpoint descriptor with no controls. 196 bytes = 49 frames: 48 per
ms plus one of slack. This matches the manual's "USB 2.0 Full Speed, 48kHz-16bit, 2 in / 2 out". The sample path
into the mixer (`TrackSound::USBTrack`, `g_usb_audio_event_receiver`) is simulated: HW-40,
[01-platform-map.md](01-platform-map.md) "USB audio sample path".

**The codec PLL trim** (static): `0xC1661230` starts TIMER64P1 (`0x01C21000`) as a free-running counter and sets
B14+560; the USB audio class code calls it when either streaming interface becomes active (B14+764 / +768, at
`0xC15E8FB0`) and stops it with `0xC16612E0` when both are idle. `audio_clock_probe_tick` stores the TIMER64P1 count
for each second of audio (375 blocks). IOObserver calls `0xC1661080(tick_count)` about once a second (its 10-bit
counter at 512), and when 10,000 ticks have passed since the last correction it averages the stored counts and calls
`codec_set_pll_fraction` (K = 8 + trim / 10000, so the rate moves by trim / 80000). TIMER64P1 runs from PLL0_AUXCLK,
the DSP's 24 MHz crystal (SPRUH79 Table 7-1). So while a USB audio stream is open, the codec's sample clock is locked
to the DSP's crystal; it does not follow USB start-of-frame, SYNC IN or MIDI clock (static reading; why the crystal
is the reference for an adaptive OUT endpoint is not explained by the code read).

**Start sequence, line in → line out** (the stock order, with the register values above; copying it reproduces the
stock electrical state; **device**: the M1 test image ran it and played tones on the headphones, HW-61):
1. SYSCFG unlock; PSC1 module 3 (GPIO) on; the audio pin defaults from the GPIO table (mux nibble 8, directions,
   levels: GP4[10], [12], [14], [15] low; GP4[13] high; GP2[8], GP2[9] high (speaker and output muted); GP1[2] low,
   GP1[3] high; GP7[14] high, GP7[15] low; GP5[11] low; GP3[8] input).
2. GP4[10] high, then wait at least one tick (the stock app sleeps 1 ms).
3. PSC1 module 7 (McASP0) on; PINMUX0/1 McASP pins; PINMUX4 I2C0; I2C0 at 100 kHz; EDMA3 PaRAM ring as above.
4. Codec over I2C (0x18): 0 = 0, 1 = 0x80, wait 1 ms; 9 = 0x37, 10 = 0; 2 = 0, 3 = 0xA2, 4 = 0x20, 5 = 0, 6 = 0,
   7 = 0x0A, 8 = 0xD0 (the clocks start here); 15 = 0, 16 = 0; page 1 high-pass coefficients, 107 = 0xC0; 17 = 18 =
   0xFF, 21 = 24 = 0xF8, 19 = 22 = 0x84; 37 = 0xC0, 41 = 0x50, 42 = 0x9C, 86 = 93 = 0x0B; 12 = 0x50.
5. McASP0 configuration and start in SPRUH79's order (section 23.0.21.1.2), with the EDMA events enabled before the
   serializers come out of reset.
6. Unmute: GP2[9] low, then 43 = 44 = 0 (the stock wrapper writes GP2[9] first).
7. Speaker: GP2[8] = SPEAKER MUTE (0 = speaker on).
8. Analogue power: GP4[14] high, 2 ms, GP4[15] high, 5 ms, GP4[12] high (the stock app does this after the power-key
   check, up to 1 s later).

Line in → line out is then a copy from the receive buffer to the transmit buffer in the EDMA completion handler
(both 32-bit I2S words; see "Channel order"; not run on the unit). For INPUT L/R as stereo line, the start-up routing
(step 4) is already LINE1L → left and LINE1R → right at 0 dB, with the Hi-Z and mic stages off.

**Power order: data sheet versus the stock app.** SLAS509G gives: power IOVDD, then AVDD/DRVDD, then DVDD, and keep
RESET low until all supplies are stable (section 12); a RESET low pulse of at least 10 ns after the supplies is
required (section 10.3.1); the DAC soft-steps its volume up from mute at power-up and down to mute before powering
down, and MCLK must stay applied until the DAC power-down flag is set (section 10.3.3.3.4, Audio DAC Digital Volume
Control); output drivers have a programmable power-on delay and ramp (register 42). It gives no register-by-register
power-up table. The stock app: holds GP4[10] low through the board set-up and releases it before the first I2C access
(consistent with GP4[10] being RESET, inference); configures the codec with the output muted (GP2[9] high, DAC
registers at their reset mute); sets an 800 ms driver power-on delay with 4 ms ramp steps; unmutes; and enables the
analogue stage (GP4[14], [15], [12]) last. At power-off it mutes (GP2[9] high, DAC 0x80), saves, waits until 1 s has
passed, and releases the power hold; it never powers down the DACs or drivers, never stops MCLK and never lowers
GP4[12..15] before the supply goes. A quieter power-off would add, before releasing GP4[11]: GP4[12], [15], [14] low
(the reverse order `0xC1649448(0)` implements but nobody calls), then 37 = 0 and a wait for the DAC power-down flag
(register 94, T10-103) before dropping the supply (inference from the data sheet; not tried).

**What stays unknown** (needs a schematic or a listening session, `experiments/sessions/D3-audio-pins-plan.md`, not
run): the electrical roles of GP4[10], GP4[12..15], GP4[13], GP1[2], GP1[3] (code: the line PAD) and GP7[14] (the
readings above are inference); the physical I2S channel order on the receive side and on the line outputs (the
output side is observed on the headphones, HW-61); whether MCLK is a 24.576 MHz oscillator (inference from the PLL
arithmetic); which jack GP3[8] detects (the built-in mic is monitored only while it is high; no speaker-off code
exists); whether the PAD on GP1[3] is the manual's -20 dB (the code has no digital PAD).

## MIDI DIN on UART0 (`0x01C42000`)

Simulated in the three products (MIDI UART start `0xC1620EF4` on `g_midi_stream_uart`; HW-11): PSC0 module 9 on;
PINMUX3 nibbles 4, 5 = 2 (UART0 RXD, TXD); MDR = 0; DLL = `0x74`, DLH = 1 (divisor 372: 186 MHz / 16 / 372 = 31,250
baud exactly); LCR = 3 (8N1); FCR = 7 then 1; IER = 5 (receive and line-status interrupts). CPU interrupt 8 (event
38). DIN input and output are switched in software only (`midi_in_uart_enable` writes no register). UART2 is
addressed by the shared UART driver's base table but no set-up for it was found.

## SYNC IN / SYNC OUT (GP7[8], GP7[9])

Simulated in SmplTrek 3.2.174 (`analysis/sync_map.py`; HW-27, HW-31, HW-41); the GPIO code involved is the same 168
instructions in Lofi-12 XT 1.5.205 and CyDrums 1.1.84 (platform map, "GPIO"). Register names SPRUH79C Table 19-2
(banks 6 and 7: bit 16 + n is GP7[n]); manual: SmplTrek v3 Reference Manual r2, "Setting the clock" (SOURCE INTERNAL
/ MIDI / SYNC, POLARITY IN and OUT, RISE or FALL). Nothing here is observed on the unit.

- **Set-up** (`0xC16720D8`): PINMUX17 nibbles 0 and 1 = 8 (GPIO); GP7[9] output, driven low; GP7[8] input with a
  rising-edge interrupt (SET_RIS_TRIG67 and CLR_FAL_TRIG67 bit 24); the bank interrupt is enabled by
  `0xC1672060` (BINTEN `0x01E26008` |= 1 << 7; called from the settings code at `0xC158CD38` and from `0xC1630E48`)
  and disabled by `0xC1672070` (called from `MainDelegate::handle_power_message`).
  Interrupt: GPIO_B7INT, event 72 (SPRUH79C Table 2-1), on CPU interrupt 7 (platform map, "Interrupts and Swis").
- **POLARITY IN** (g_settings+0x08, applied by `settings_apply_all` through `0xC167208C`): 1 = rising edge
  (SET_RIS_TRIG + CLR_FAL_TRIG), 0 = falling edge (SET_FAL_TRIG + CLR_RIS_TRIG). The set-up value is rising until
  settings are applied, whatever the setting.
- **SYNC IN path**: the ISR (`gpio_bank_isr` `0xC1672134`) clears INTSTAT67 bit 24 and sets a flag; a SYS/BIOS Clock
  object with period 1 tick (1 ms; function `0xC169CCC0`, its function pointer is stored at `0xC16EE248` after the
  words timeout 5, current timeout 5, period 1, active 0, in SYS/BIOS's Clock object field order (inference from that
  order)) calls `0xC1671F80` every millisecond, which passes a pending edge to a delegate (slot 0, with the sync
  object). So edges are timestamped to the 1 ms tick. The delegate and the tempo derivation: "SYNC IN to tempo"
  below.
- **SYNC OUT pulses**: the clock-position handler (`0xC154A264`, a MainDelegate virtual method) gets a position per
  step; it sends MIDI clock (`midi_send_clock`) at positions divisible by 3 and starts a SYNC OUT pulse at positions 0
  and 36. MIDI clock is 24 per quarter note, so the position counts 72 per quarter note and SYNC OUT gives **2 pulses
  per quarter note**. A pulse drives GP7[9] to the active level (high with POLARITY OUT = 0, low with 1; the
  setting is g_settings+0x0C, stored in the sync object), and the 1 ms function returns it to idle after **15 ms**.
  A new pulse starts only when 60 ms have passed since the last start, which caps SYNC OUT at 500 BPM.
- **Where the positions come from** (simulated; app level, recorded because it explains the constant 28,800,000):
  with SOURCE = INTERNAL, `audio_render_main` advances the clock object at `0xC1504310` once per audio block
  (`0xC1681738(obj, frames)`): a phase accumulator (+0) grows by frames x increment (+4), and each time it passes
  28,800,000 the position (+8) steps, wrapping at 72; its delegate (+12) gets slot 0 and then, on a later block, slot 1
  with the position. Tempo is set by `0xC1681874(obj, tempo x 10)`: increment = 72 x tempo x 10, and 28,800,000 =
  48,000 samples/s x 60 s x 10, so the position runs at 72 steps per quarter note at that tempo (120.0 BPM: 144 steps
  in 375 blocks, positions 0-71 twice). `0xC16816F4(steps, tempo x 10)` converts steps to samples (333 per step at
  120.0 BPM). That slot 1 is the clock-position handler above is inference (same arguments; the delegate object was
  not identified). Steps are delivered per audio block, so SYNC OUT and MIDI clock edges sit on block boundaries
  (2.67 ms) unless the handler compensates (not seen). With SOURCE = MIDI or SYNC another object (`0xC1501FE8`,
  advanced by `0xC165F40C`) is used instead.
- **SYNC IN to tempo** (simulated: `sync_map.py` `sync_in_tempo`, test `test_sync_in_tempo`; HW-31). The sync
  object's delegate is MainDelegate's SyncClockReceiverDelegate base (this + 20, installed in `0xC154A620`). Its slot 0
  (`0xC154A224` -> `0xC154A1F0`) passes each edge, unless `0xC1652680()` is non-zero, to `0xC165F5EC` on
  that external-clock object `0xC1501FE8`. The static initialiser `0xC16A1BB8` builds the object with 36 steps per
  edge, and no setting writes it, so SYNC IN is a fixed 2 PPQN like SYNC OUT. Every second edge is a beat
  (`0xC165F214`). The beat interval in ms (`0xC16ACDA0`, 1 ms ticks; last beat at B14+1320) is dropped at 2000 ms
  or more (below 30 BPM). Otherwise it goes into a four-entry ring, and tempo x 10 = 2,400,000 / (sum of the four).
  A change of more than 5.0 BPM refills the ring, so a jump locks within a beat while small jitter is averaged over
  four. The object starts at 120.0 (+40, +44 = 1200), and the first beat is measured from time 0, so its first
  reading is wrong. A changed tempo goes to the object's delegate (+28) slot 2. `0xC1652680()` is non-zero while an
  audio export renders (B14+1088 / B14+1092, set by the export job that `DialogAudioExporting` starts; static, symbol
  file `midi_tx_allowed`), so edges are ignored during a mixdown or stem export, and MIDI output is blocked then too.
- **SYNC IN steps between edges** (simulated: `sync_map.py` `sync_in_steps`, test `test_sync_in_steps`; HW-41). With
  SOURCE not INTERNAL the audio code (`0xC159AC58`) runs `0xC165F40C(0xC1501FE8, 128)` once per block in place of the
  internal clock. Nothing steps before the first beat (second edge). From then on each edge allows 36 steps, spaced at
  the current tempo (72 per beat; at 120 BPM one step every 6.9 ms, so at most one per 2.67 ms block) and sent to the
  object's delegate (+28) slot 1 with the position 0-71. If an edge comes early, the steps still owed are all sent in
  the next block (edges 250 then 200 ms apart: positions 29-36 in one block). If it comes late, the clock stops after
  the 36th step and waits. No step is dropped or added, so the position stays locked to the edges. That costs bursts
  when the clock speeds up and stalls when it slows.
- **In short:** PINMUX17 nibbles 0, 1 = 8; GP7[9] an output idling at the inverse of the active level, a 15 ms pulse
  every 36 steps of a 72-per-quarter clock; GP7[8] an edge interrupt whose flag the stock in effect polls from the
  1 ms tick (INTSTAT67 bit 24). The electrical side (jack wiring, level, any buffer) is not visible to code.

## USB device (USB0, `0x01E00000`)

The stack is TI StarterWare usblib (platform map, "USB"; BSD-licensed). Bring-up, simulated in the three products
(HW-12):
1. `0xC16907C0`: SYSCFG0 CFGCHIP2 = `0x0972`: USB0 reference 24 MHz (REF_FREQ 2), PHY clock from the internal
   mux (USB0PHYCLKMUX = 1: AUXCLK, internally), USB0DATPOL = 1 (D+/D- not swapped), USB0PHY_PLLON = 1 (the PHY keeps
   its 48 MHz clock in suspend), session-end and VBUS comparators on, USB0OTGMODE 0 (no override: the PHY's own
   comparators decide host / device), PHY and OTG not powered down, not in reset (SPRUH79 Table 10-47).
2. `usb_dcd_init` (`0xC158EE00`): PSC1 module 1 on; CTRLR = 1 (reset; clears itself); PHY on (`0xC1694C60`:
   CFGCHIP2 bits 15, 10, 9 cleared, bit 6 PLL on set, then a wait until bit 17 USB0PHYCLKGD reads 1); INTCLRR = 0;
   INTMSKSETR = `0x01FF1E1F` (all endpoint and USB interrupts); MUSB INTRUSBE = `0x2F`, INTRTXE = INTRRXE = `0xFFFF`;
   POWER = `0x40` (SOFTCONN: attach). This clears HSENAB (`0x20`), which the core's reset sets, so the device runs at full speed (12 Mbit/s), which fits the
   descriptors' bcdUSB 1.10.
3. CPU interrupt 12 (event 19); the handler is usblib's `USB0DeviceIntHandler`.

**Device**, steps 1-2 without SOFTCONN or interrupts (HW-59, session M1, 2026-11-16): USB0PHYCLKGD comes up within
10 ms and CFGCHIP2 reads `0x00020972`. The vendor driver's reserved words `0x01E0080C` and `0x01E0084C` read 0, and
stores of 0 to `0x01E00808` and `0x01E00848` (CyDrums) are harmless and read back 0. Enumeration is not observed
from a test image (the stock enumerates as a composite device, experiments/README.md "USB check result").

Descriptors in SmplTrek 3.2.174 (static, from the initialised data; VID and PID are filled in at run time and are
Sonicware's): one composite configuration of 234 bytes, self-powered, four interfaces: IF0 Audio Control; IF1 Audio
Streaming, alt 1 isochronous OUT `0x01` (adaptive), 196 bytes per 1 ms; IF2 Audio Streaming, alt 1 isochronous IN
`0x82` (asynchronous), 196 bytes; IF3 MIDI Streaming, bulk IN `0x83` and OUT `0x03`, 64 bytes. 196 bytes per frame
is 49 stereo 16-bit frames, i.e. 48 kHz with one frame of slack; the format descriptors say 48,000 Hz, 2 channels,
16-bit ("USB audio" under "Audio paths").

The descriptor as the host receives it (simulated: `analysis/usb_desc_map.py`, test `test_usb_desc_map.py`). usblib
builds it from 27 sections (tConfigHeader `0xC16EFB1C`, section array `0xC16EBEB0`); the class-specific sections are
empty in the boot image and filled by the USB start `0xC167C9EC` (composite set-up `0xC165BE20`; audio part
`0xC162A4A0`, MIDI part `0xC162D964`). Assembled, it is 234 bytes, every length consistent: configuration; IF0 Audio
Control (header, IT 3 USB streaming → OT 4 headphones, IT 5 microphone → OT 6 USB streaming); IF1 alt 0 / alt 1 (AS
general, Type I 2 x 16-bit 48 kHz, EP `0x01`, AS endpoint); IF2 the same with EP `0x82`; IF3 MIDI Streaming (header,
total 22; one embedded IN jack 1 and one embedded OUT jack 2 fed by jack 1, no external jacks; EP `0x03` bound to
jack 1, EP `0x83` to jack 2). No interface association descriptor, no feedback endpoint. Card-reader mode uses a
second, one-interface configuration: mass storage, bulk-only, endpoints `0x81` and `0x02`, 64 bytes.

## SD card (MMCSD0, `0x01C40000`)

Simulated in the three products (`sd_card_hw_init` `0xC167270C`; HW-11): PINMUX10 nibbles 6, 7 = 8 (GP4[1], GP4[0]);
GP4[1] output, low; GP4[0] input (card detect, low = card present); PSC0 module 5 on; PINMUX10 nibbles 0-5 = 2 (CLK,
CMD, DAT0-3: 4-bit bus); EDMA channels 16 and 17 (MMCSD0 receive / transmit events) claimed with TCC 16 / 17; MMCCTL
= 3 (data and command lines in reset); MMCCLK = `0xE8` (CLKRT 232: 186 MHz / (2 x 233) = 399 kHz, the identification
rate), MMCTOR = `0x3FFFF`, MMCTOD = `0xFFFF`; MMCCTL = 0 (out of reset); MMCCLK = `0x1E8` (CLKEN: clock on); MMCIM =
`0x7D`: data done, command/response done, read-data and response time-outs, write and read CRC errors (not busy done,
not response CRC) (SPRUH79 MMC/SD chapter, MMCCLK and MMCIM field tables). CPU interrupt 11 (event 15).

**Device** (D1 run 3, 2026-11-13): a minimal polled single-block driver on this controller (see the comparison at
the end of this section) mounts the card and reads files through FatFs on the unit. The stock's own interrupt and
EDMA path below is simulated only.

**Card protocol layer** (static reading and simulation 2026-11-12, `sd_map.py`; HW-23; `0xC15D1F20`-`0xC15D3100`,
reached from `sd_transfer`: op 0 → `0xC1645FA8` → card init `0xC15D2EC8`, then the bus-width step `0xC15D3010` (only
when card+4, `0xC150104C`, is 0), the high-speed step `0xC15D2160` and the status poll `0xC15D1F54`). Card+4
(2026-11-15): card init sets it to 0 right after the CMD55 probe (`0xC15D2F22`, through the card pointer at ctrl+80)
and nothing else in card init changes it (simulated: a card record with +4 = 0x77 comes out of a successful init with
0); the only other address constant for it is the dispatcher's read. So the stock always runs the bus-width step,
then the high-speed step (static, apart from the card-init run). It has the shape of TI StarterWare's AM335x
`mmcsd_proto.c`: a command record {index +0, flags +4, argument +8, ...} (built on the stack at B15+4) handed to the
controller through the function pointers of an `mmcsdCtrlInfo`-style record (below); `MMCSDAppCmdSend`-style CMD55
wrapper `0xC15D23F0` with argument RCA << 16; command send `0xC15D1F20`, which jumps through ctrl+16, with a 1000
timeout. That file is not in the C6748 package, and the C6748 FatFs port (`third_party/fatfs/port/fat_mmcsd.c`) only
calls it, so the origin is inference. Commands, in the order the initialisation issues them (card init `0xC15D2EC8`
calls CMD0 to ACMD51 in this order, stopping at the first failure; ACMD6 and CMD6 follow from `0xC1645FA8`), with the
SD Physical Layer meaning and the MMCCMD word the controller layer writes (simulated; fields from SPRUH79C Table
25-18):

| Function | Command | Argument / data | MMCCMD | Notes |
|---|---|---|---|---|
| `0xC15D2488` | CMD0 GO_IDLE_STATE | 0 | `0x4800` INITCK | no response; the init first clears the 96-byte card record |
| `0xC15D2460` | CMD55 APP_CMD as a probe | 0 | `0xA37` R1 | an answer means an SD card; then CMD0 again |
| `0xC15D24C0` | CMD8 SEND_IF_COND | `0x1AA` (2.7-3.6 V, check pattern AA) | `0xA08` R1 | |
| `0xC15D24EC` | ACMD41 SD_SEND_OP_COND (CMD55 first) | `0x40FF8000` (HCS, 2.7-3.6 V) | `0xE29` R3 | up to 255 tries, 10 ms apart (`task_sleep(10)`), until OCR bit 31 (ready); the OCR word is kept at card+52, bit 30 (CCS, block addressing) as a byte at card+59 |
| `0xC15D2658` | CMD2 ALL_SEND_CID | — | `0xC02` R2 | CID unpacked by `0xC15D25D4` |
| `0xC15D26E4` | CMD3 SEND_RELATIVE_ADDR | — | `0xA03` R1 | RCA = response >> 16, stored at card+8 |
| `0xC15D2A4C` | CMD9 SEND_CSD | RCA << 16 | `0xC09` R2 | CSD unpacked; card+58 is a CSD byte (inference: TRAN_SPEED), card+60 the block length |
| `0xC15D2C24` | CMD7 SELECT_CARD | RCA << 16 | `0xB07` R1 BSYEXP | |
| `0xC15D2C68` | CMD16 SET_BLOCKLEN | 512 | `0xA10` R1 | only for standard-capacity cards (CCS = 0 at card+59) |
| `0xC15D2D18` | ACMD51 SEND_SCR | RCA << 16 (CMD55) | `0x1A233` R1 WDATX DCLR DMATRIG | 8 data bytes by EDMA into `0xC1502080` |
| `0xC15D3010` | ACMD6 SET_BUS_WIDTH | 2 (4-bit) if ctrl+56 bit 2 and SCR bus-widths bit 2 (card+57) are set, else 0 (1-bit) | `0xA06` R1 | then busWidthConfig (ctrl+20): MMCCTL = 0, then 4 (WIDTH0) for 4-bit |
| `0xC15D2160` | CMD6 SWITCH_FUNC | `0x80FFFFF1` (switch, group 1 = high speed) | `0x1A206` R1 WDATX DCLR DMATRIG | 64-byte status into `0xC1502080`; clock choice below |
| `0xC15D1F54` | CMD13 SEND_STATUS | RCA << 16 | `0xA0D` R1 | repeated until the card state (response bits 12:9, mask `0x1E00`) is 4 = tran (`0x800`) |
| `0xC15D1F2C` | CMD12 STOP_TRANSMISSION | 0 | `0x8B0C` R1 BSYEXP DCLR | after every multi-block transfer (from `0xC15D2398` read, `0xC15D2120` write) |
| `0xC15D2288` (read) | CMD17 / CMD18 | block address (CCS = 1) or block x card+60 | `0x1A211` / `0x1A212` | (ctrl, buffer, block, count); CMD18 when count > 1, then CMD12 |
| `0xC15D1FF4` (write) | CMD24 / CMD25 | as for reads | `0x1AA18` / `0x1AA19` (DTRW: write) | CMD25 when count > 1, then CMD12; then CMD13 until tran |

The function addresses are the call targets from `0xC15D2EC8` and `0xC1645FA8`; `0xC15D2A58`, `0xC15D2C28`,
`0xC15D2C6C`, `0xC15D2D64` and `0xC15D2198`, given in earlier versions of this table, are inside those functions.
Every command word also has DTRW (bit 11) set except reads; with WDATX = 0 the bit has no effect (Table 25-18).
**No command sets PPLEN** (bit 7): the stock drives the CMD line open-drain throughout, identification and data
alike (Table 25-18: "0 = push pull driver of CMD line is disabled (open drain)"; HW-25).

**Controller layer** (simulated in the three products, `analysis/sd_map.py`, `test_sd_map.py`). `0xC164620C` fills a
controller record at `0xC14B63A8` laid out like StarterWare's `mmcsdCtrlInfo` (compare `bootloader/src/bl_hsmmcsd.c`
lines 402-419): memBase `0x01C40000`, ipClk 186,000,000, opClk 400,000, ctrlInit `0xC167B4CC` (+12), cmdSend
`0xC1645D1C` (+16; takes a lock, then `0xC167B54C` writes the registers), busWidthConfig `0xC167B670` (+20),
busFreqConfig `0xC167B698` (+24), cmdStatusGet `0xC1645DA8` (+28), xferStatusGet `0xC1645D60` (+32), xferSetup
`0xC1645F20` (+40), intrMask `0x7D` (+52), busWidth 5 = 1- and 4-bit (+56), highspeed 1 (+60), card record
`0xC1501048` (+80). Only cmdStatusGet waits (static, 2026-11-14): it calls `mmcsd_wait`: Event_pend on `0xC14FFD54`
with any bit (orMask -1) and the caller's time-out (B6). xferStatusGet does not wait: it clears record +76 and
disables EDMA channel 16 or 17 (`EDMA3DisableTransfer`).

**The interrupt** (simulated 2026-11-14, `analysis/mmc_isr_map.py`, `test_mmc_isr_map.py`; HW-42; bits from SPRUH79C
Table 25-8, and reading MMCST0 clears them, 25.4.3). `mmcsd0_isr` `0xC166F98C` reads MMCST0 (`0xC165C00C`), handles
the bits and reads it again before returning. It calls a listener (table `0xC16EFBA0`, entry 0) like this:
- RSPDNE: slot 0;
- DATDNE: slot 1;
- TOUTRS: slot 2 with -1;
- TOUTRD: slot 2 with -2;
- CRCWR or CRCRD: slot 2 with -7;
- BSYDNE, CRCRS, DXRDY, DRRDY, DATED, TRNDNE, CCS: nothing.

On RSPDNE it also checks B14+1124: if it is 4, `0xC166F900(0)` sets B14+1120 = 0 and runs
Event_post(`0xC14FFD54`, 4), which wakes `mmcsd_wait`. cmdSend sets B14+1124 to 4 when no data transfer is set up
(record +76 == 0) and to 1 otherwise.

In the stock app the listener table stays empty: its setter `0xC166F978` has no caller or data reference, and entry 0
is 0 after start-up. So the interrupt only posts. It posts on RSPDNE in mode 4, and on DATDNE in mode 1.
`0xC166F90C` is not a separate helper: it is the delay-slot code of `0xC166F900`'s branch to `event_post`, which loads
the mode as the event bits and `0xC14FFD54` as the event.

**How a command completes** (simulated 2026-11-14 with the real ISR run from inside the wait, `mmc_isr_map.py`
`command`, `test_mmc_isr_map.py`; HW-44).
- cmdSend first runs `0xC166F8A4`: it waits, with `task_sleep(1)` in a loop, until the previous command's mode
  (B14+1124) is 0. Then it sets the mode, 4 without data and 1 with data, and calls the register writer
  `0xC167B54C`.
- After writing MMCCMD, the register writer calls cmdStatusGet (record +28) with the caller's time-out. Every
  protocol function passes 1000 Clock ticks. That is 1 s: the tick is 1 ms (TIMER64P0 PRD12 = 24000 at the timer's
  configured 24 MHz input, the value the exact `Timer_getFreq` returns).
- A command without data is released by RSPDNE, a data command by DATDNE. `mmcsd_wait` then clears the mode and
  returns the ISR's status (0), and the command function succeeds.
- A multi-block read is CMD18, released by DATDNE, then CMD12, released by RSPDNE.
- A command the card does not answer posts nothing: TOUTRS, TOUTRD, a missing DATDNE, or no status at all. The
  wait then times out after 1000 ticks, and `mmcsd_wait` returns -3 and still clears the mode. So the command
  fails and the next one is not blocked: nothing stays blocked for good. The cost is one time-out per unanswered
  command.
- The disk layer (simulated 2026-11-14, `test_disk_layer_has_no_retry`; HW-45) has no retry. `disk_read` /
  `disk_write` (`0xC1682378` / `0xC1682320`, FatFs diskio) tail-call the transfer dispatcher `0xC1646020` on the SD
  driver object for drive 0. That dispatcher tail-calls the protocol read `0xC15D2288` or write `0xC15D1FF4`.
  - The functions return 0 (RES_OK) on success. A failed data command, or an unanswered CMD12 after a multi-block
    transfer, gives one 1 s time-out and returns 4. In FatFs's `diskio.h` 4 is RES_PARERR, not RES_ERROR.
  - An unanswered CMD13 status poll after a write is not reported: `disk_write` still returns 0.
  - Drive numbers other than 0 return 4 at once.
  - FatFs turns any non-RES_OK into FR_DISK_ERR. Inside `f_read` / `f_write` it uses `ABORT`, which also sets the
    file object's sticky error, so later calls on that file fail until it is reopened (retrying on the same `FIL`
    does nothing). This is from the FatFs R0.15 source; the stock's FatFs is R0.14a-R0.15a (`src_match.py`) and was
    not run here.

So the stock completes a command on RSPDNE (or DATDNE for data) or by time-out; it ignores the error bits and relies
on the time-out alone. With MMCIM = `0x7D` it enables RSPDNE, DATDNE, the time-outs and the CRC errors, never BSYDNE
(Table 25-10).
- **ctrlInit**: MMCCTL |= 3 (DATRST, CMDRST); MMCCLK = 0; MMCCTL = 3 twice; MMCCLK = `0xE8` (399 kHz);
  MMCTOR = `0x3FFFF`; MMCTOD = `0xFFFF`; MMCCTL = 0; MMCCLK = `0x1E8`. The same as `sd_card_hw_init` above.
- **Each command**: MMCNBLK = 0, then the block count (0 without data); MMCARGHL; MMCCMD (bits from the record's
  flags: response format, BSYEXP, data, direction).
- **Each data command** (xferSetup first): MMCFIFOCTL = 1 (FIFORST), 0, then 4 for reads (FIFOLEV: an EDMA request
  every 64 bytes, FIFODIR read) or 6 for writes (FIFOLEV, FIFODIR write) (Table 25-29); the EDMA PaRAM; MMCBLEN =
  512 (8 for ACMD51, 64 for CMD6); then the command with DMATRIG | DCLR | WDATX.
- **EDMA** (OPT fields from SPRUH79C Table 16-15): reads use PaRAM 16 (OPT `0x00010004`: TCC 16, SYNCDIM = 1
  AB-synchronised, TCINTEN = 0 so no EDMA completion interrupt; the MMC's own DATDNE ends the transfer),
  SRC = MMCDRR `0x01C40028`, ACNT 4, BCNT 16 (64 bytes per event), DST BIDX 4, DST CIDX 64, CCNT = 8 per block;
  writes use PaRAM 17 (OPT `0x00011004`: TCC 17), DST = MMCDXR `0x01C4002C`, SRC BIDX 4, SRC CIDX 64, same counts.
  Then S_SECR, EMCR (clear stale event/miss) and S_EESR (enable event) for the channel. Around each transfer the
  buffer gets cache maintenance: `0xC16ACA00` (buffer, count x 512) before a read, `0xC16ACA20` before a write
  (it waits on `0x01844004`, L2WWC, the L2 write-back word count, SPRUFK5A Table 4-2), `0xC16AC9E0` after the
  ACMD51 and CMD6 reads.
- **Clock after initialisation** (the high-speed step `0xC15D2160`): if card+58 is already `0x5A`, busFreqConfig
  is called with 50,000,000 → MMCCLK = `0x101` (CLKRT 1: 186 MHz / 4 = 46.5 MHz); otherwise with 25,000,000 →
  MMCCLK = `0x103` (CLKRT 3: 186 / 8 = 23.25 MHz), and if the CMD6 status byte 16 low nibble is 1 (group 1 switched)
  card+58 is set to `0x5A` for next time (memory clock = function clock / (2 x (CLKRT + 1)), SPRUH79C 25.2.1).
  Because card init clears the card record and refills card+58 from CMD9, and CMD9 comes after CMD0, the stock runs
  the card at 23.25 MHz in practice (inference: per the SD specification, CMD0 returns a card to default speed and
  its CSD TRAN_SPEED to `0x32`; not observed).
- **Multi-block stop**: an explicit CMD12 (`0x8B0C`, R1b) after CMD18 / CMD25; no auto-stop.

**Stock SD driver against the test images' minimal driver** (the polled single-block driver of the bare-metal test
images, not published; the one that works on the unit, D1 run 3). An earlier version of that driver also waited for
BSYDNE after a write and set PPLEN; neither is what the stock does, and both were removed. Comparison with how the
stock waits and fails (HW-44, HW-45):

| | Stock 3.2.174 | Minimal driver | Note |
|---|---|---|---|
| Waiting | interrupt (MMCIM `0x7D`) and Event_pend, 1 s per command | polled MMCST0, 500 ms per wait | MMCST0 clears on read, so both keep the bits they have seen |
| What releases a command | RSPDNE (no data) or DATDNE (data) | the same | |
| Error bits (TOUTRS, TOUTRD, CRC) | ignored: the command fails only by time-out | fail the wait at once | |
| Unanswered command | fails after 1 s, mode cleared, next command runs | fails after 500 ms with the bits seen | same outcome |
| After a write | DATDNE, then CMD13 until tran; a CMD13 that times out is ignored and the write reported good | DATDNE, then CMD13 until tran (1 s); a failed CMD13 fails the write (-5) | the minimal driver reports an error the stock hides |
| Transfers | CMD17 / CMD18 + CMD12, CMD24 / CMD25 + CMD12, by EDMA (PaRAM 16 / 17) | single-block CMD17 / CMD24 only, by CPU from the FIFO (DRRDY / DXRDY per 64 bytes) | every single-block command pays the card's access time again (inference, not measured) |
| Retry | none at the disk layer; FatFs sees RES_PARERR (4) | none; FatFs sees RES_ERROR (1) | both become FR_DISK_ERR |
| Data clock | 23.25 MHz (CLKRT 3) in practice; 46.5 MHz only for a card already marked high-speed | 23.25 MHz | the same |
| ACMD41 | up to 255 tries, 10 ms apart | up to 2000 tries, 1 ms apart | both about 2 s or more, the SD specification's 1 s minimum |

The minimal driver also skips, as the SD specification allows: the CMD55 probe and the repeated CMD0, CMD16 for
standard-capacity cards, and the SCR check before going 4-bit.

## SPI flash on SPI0 (`0x01C41000`)

Two 16 MiB SPI NOR devices on SPI0 chip selects 0 and 1 (HW-1), SPI0 at 37.2 MHz (prescale 4), SPIFMT0 `0x00010408`.
`HAL::FlashMemoryDriver` (simulated with a recording SPI object, `analysis/flash_cmd_map.py`; HW-22) uses standard
SPI NOR commands with 3-byte addresses: `03` read, `02` page program, `05` read status (busy poll), and three erase
sizes chosen per step by alignment and remaining length in `do_erase` (`0xC15DF060`): `D8` 64 KiB, `52` 32 KiB,
`20` 4 KiB. Every erase or program step is: `05` + one status byte (repeated while busy), `06` alone, then the
command and address in one held transfer; `do_program` (`0xC15DF2F4`, arguments this, addr, buf, len) sends one
256-byte page per `02`. Example: erasing `0x441000` + `0x11000` is seven `20` (0x441000-0x447000), one `52`
(0x448000), two `20` (0x450000, 0x451000); `0x450000` + `0x10000` is one `D8`. **Write enable**: `06`, a data
byte at B14+1630 (not an instruction constant), sent alone in its own transfer by `0xC15DF028` before every erase and
every program step (`0xC15DF09C` in `do_erase`, `0xC15DF340` in `do_program`); `panel_map.py` runs it in the three
products (identical). The driver also has a status-register writer (`0xC15DFC58`: `06` from B14+1629, then `01` +
data, after a busy wait; wrappers `0xC15DFDB8`, `0xC15DFDEC`, `0xC15DFE24`) and a read of register `15`
(`0xC15DFDE0`), but nothing calls them and no pointer to them exists in the 3.2.174 image: the app never changes the
block-protect bits (static). A `15` read-configuration command and a two-byte status write fit Macronix MX25L-family
parts; no `9F` (JEDEC ID) or `90` read is in the driver.

**Device** (HW-54, session M1, 2026-11-16): both devices answer `9F` with `C2 20 18`: Macronix, 128 Mbit each.
Device 0 reads status `0C` and configuration `0F` (block protect BP = 0011 with TB = 1: the boot area is
write-protected in the part, reading the bits by the Macronix register layout, inference), device 1 `00` and `07`
(unprotected). Since the app never calls its status-register writer, a write into device 0's protected range would
be refused by the flash itself (inference). Below `0x441000` on device 0 lie the bootloader (256 KiB), the SYSTEM
image (4 MiB) and the PRESET header sector ([05-bootloader.md](05-bootloader.md), "Writing").

**Reads go by EDMA** (static, 2026-11-15; HW-53). `do_read` (`0xC15DF488`) sends `03` + address through SPIDriver
slot 1, then calls slot 2 (read, `0xC1626A08`) with flag 1, in chunks of at most 65535 bytes, and waits on the
driver's event (1000 ticks) after each. Slot 2 with flag 0 is a polled CPU loop (`0xC1626900`: one dummy byte out,
one byte in, `stb` to the buffer); flag 1 (`0xC1626990`) sets up two EDMA transfers and SPIINT0 bit 16 (DMAREQEN):
- transmit (`0xC1626564`): event 15 (SPI0 XEVT; 19 on SPI1), SRC = the buffer with SRC BIDX 0 (its first byte is
  sent again and again as the dummy), DST = SPIDAT1 (`base + 0x3C`), ACNT 1, BCNT = length, no completion interrupt;
- receive (`0xC1626638`): event 14 (SPI0 REVT; 18 on SPI1), SRC = SPIBUF (`base + 0x40`), DST = the buffer with DST
  BIDX 1, ACNT 1, BCNT = length, TCINTEN set with TCC 14, so the EDMA completion interrupt ends the read.

Neither the SPI driver nor `do_read` does any cache operation; a caller that reads the buffer from the CPU must
invalidate it first (the bootloader's SYSTEM reader does, for its header buffer). The bootloader's flash driver is the
same code (`0xC70869E0`, read slot `0xC708AA88`, DMA path `0xC708AA10`, flag 1; [05-bootloader.md](05-bootloader.md),
"Cache state at the jump").

## Tick, timers and interrupts

- **Tick** (simulated, SYS/BIOS Timer start-up): TIMER64P0 TCR = 0, PRD12 = 24000, TIM12 = 0, then EMUMGT = 0,
  GPINTGPEN = 0, GPDATGPDIR = 0, TGCR = 5 (TIM12RS = 1, TIMMODE = 1: dual 32-bit unchained, SPRUH79 Table 29-18),
  TCR = 0x10 (PWID12 = 1, ENAMODE12 = 0: disabled for now, Table 29-17). SYSCFG0 SUSPSRC = `0x08000000` (TIMER64P0
  stops with the DSP under emulation). The enable (TCR ENAMODE12) is written later by BIOS_start and was not traced;
  continuous mode is the SYS/BIOS default (inference). Interrupt: event 4 (TINT12) on CPU interrupt 14. The app's only
  other TIMER64P0 use, TIM34 (TCR bit 23), belongs to the dormant LED frame engine. **Device** (D1): TIMER64P0 set up
  by a test image as TGCR 5, TCR 0x90 (continuous) runs free and advances on the unit.
- **TIMER64P1**: the codec PLL trim's counter (above). **Device** (HW-67, session M2): a TIMER64P1 interrupt (event
  40 on CPU interrupt 4) is taken and returns as described in the claim.
- **Interrupt routing** (simulated, platform map "Interrupts and Swis"): INTMUX1-3 = `0x483D0824`, `0x0F002E26`,
  `0x00040013`; IER `0x5BF3`. The tick alone needs INTMUX3 field 14 = 4, IER bits 1 and 14, and GIE.
- **Cache** (simulated, platform map "Image layout"): L2 all cache, L1P all cache, L1D 16 KiB cache + 16 KiB RAM;
  MAR 192-199 make DDR cacheable. Anything sent by DMA from DDR must be written back first.

## Hazards and device behaviour

- GP4[11] is the power hold: the stock drives it high early and low only at the end of the power-off path
  (`power_hold_release` after saving).
- SPI0 is the flash, which holds the bootloader: enabling SPI0 or writing PINMUX3/4 nibbles 0-3 touches it.
- Recovery depends on the bootloader reading HOME before it loads SYSTEM (INT-8; **device**, a hang image in session
  D0).
- CPU accesses that look like they should fault do not (**device**, sessions M1 and M2); EFR, IERR and the event flags
  stay clear in all of these, so none of them can be caught after the fact:
  - misaligned LDDW, LDW, STW (HW-57) and LDH, LDHU, STH, STDW (HW-63) are aligned down to the access size silently,
    in cached DDR and in L2 RAM, so a misaligned store overwrites the aligned location below;
  - a read of the unmapped low range (a null pointer) or of the EMIFA CS0 window with EMIFA not set up returns earlier
    load data, not 0 and not a fault: held as eight byte lanes, picked by address bits 2:0 (HW-58, HW-62);
  - stores to reserved low memory store nothing (HW-65), and stores into the EMIFA CS0 window are dropped without a
    stall (HW-60, HW-64).

## Open

1. **LED addresses:** 101 addresses not seen lit on the unit ("Panel LEDs", session plan L1), and the
   level-to-brightness steps.
2. **Panel MCU commands:** the bytes and send points are settled; their meaning to the MCU (`90`, `B1`, `B2`, `C2`)
   is inference, and whether the MCU needs `90` / `B1` before it answers `A0` is not separated (HW-46).
3. **Audio pins' electrical roles:** GP4[10] (codec RESET?), GP4[12..15] (amplifier / analogue power?), GP4[13]
   (fixed high), GP1[2] (built-in mic switch?), GP1[3] (line PAD, low = on, from the code) and GP7[14] (INPUT L Hi-Z
   / mic path select) are inference as to their electrics; the input routes table gives every pin state the stock
   uses per input. The headphone/speaker feed is inferred as line outputs → VOL pot → amplifiers, speaker cut by a
   switched jack. Session plan: `experiments/sessions/D3-audio-pins-plan.md` (not run).
4. **I2S channel order** on the receive side and the line outputs (output observed on the headphones, HW-61), and
   **which jack GP3[8] detects** (the stock gates built-in mic monitoring on it; there is no speaker-off code for the
   built-in mic).
5. **MCLK** as a 24.576 MHz oscillator (inference from the PLL arithmetic).
6. **DDR timing fields** (SDCR, SDTIMR1/2) not decoded; **PSC modules** the bootloader leaves on not traced.
7. **SYNC IN / OUT, MIDI DIN, USB enumeration and the stock SD interrupt path** have no device observation of their
   own.

Resolved, for reference: GP3[9]'s missing pin mux (input never depends on PINMUX, HW-19); the clock decode (with the
two cautions under "State the bootloader leaves"); the PUPD groups; the I2S channel order on the output (HW-61); the
pixel layout (HW-35); the UART1 receiver (HW-46); the SD protocol and controller layers and the MMC interrupt
(HW-23, HW-25, HW-42, HW-44, HW-45); the flash write enable (HW-22) and part (HW-54); USB audio format (HW-18) and
sample path (HW-40); the 28,800,000 constant (the internal clock's step threshold); the TIMER64P0 enable, which test
images write themselves.
