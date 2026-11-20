# Overview

## The platform

| | SmplTrek | Lofi-12 XT | CyDrums |
| --- | --- | --- | --- |
| Family word (update container) | 5 | 12 | 8 |
| Releases analysed | 1.0.65 … 3.2.174 (eight) | 1.1.156, 1.2.179, 1.5.205 | 1.1.84, 2.0.97 beta |
| Reference image | 3.2.174 | 1.5.205 | 1.1.84 |

One board serves all three:
- a TI TMS320C6748 DSP under SYS/BIOS, running from DDR2 at `0xC0000000`;
- two 16 MiB SPI NOR flashes, which the driver presents as one 32 MiB space;
- a codec whose registers match the TLV320AIC3106, on I2C and McASP0;
- an SD card on MMCSD0;
- USB 2.0 device (audio and MIDI);
- MIDI DIN on UART0, SYNC in and out on GPIO;
- an OLED on SPI;
- an Artery AT32F421 panel MCU on UART1, which scans the pads and the battery and drives the LEDs.

The key matrix and encoders are read directly on GPIO. Each product is one statically linked C++ application.
The C++ framework and the hardware layer have the same class names in all three, but each product links
at a different DDR base, so their addresses differ.

The bootloader (BOOT 1.0.17) lives in the protected bottom of flash and is never in an update file. It checks an
update's CRCs, writes the system image to flash, verifies it, and jumps to it. HOME + power enters its BOOT MODE,
which installs an update from the card even when the installed system does not start.

## Docs

| Doc | What it covers |
| --- | --- |
| [01-platform-map](01-platform-map.md) | The main reference: memory, settings blocks, tasks, interrupts, power, SD, USB, MIDI, SYNC, audio and panel, by address, for the three products, with the per-product differences |
| [02-platform-symbols](02-platform-symbols.md) | Generated: every named platform function in each product |
| [03-platform-shared](03-platform-shared.md) | Generated: how much code the three products share, by area |
| [04-hardware-access](04-hardware-access.md) | Register-level bring-up of every peripheral: what code with no Sonicware parts has to do to drive the board |
| [05-bootloader](05-bootloader.md) | BOOT 1.0.17: AIS boot, update checks, flash writes, BOOT MODE, protection |
| [06-audio-engine](06-audio-engine.md) | The SmplTrek mix, effects, file player, metronome and render order |
| [07-ram-allocation](07-ram-allocation.md), [08-heap-snapshot](08-heap-snapshot.md) | The default heap, its allocator, and checking captured heaps |
| [09-factory-test-mode](09-factory-test-mode.md) | The hidden eight-page factory test menu (FUNC + power) |
| [10-cross-flash-button-map](10-cross-flash-button-map.md) | What each SmplTrek button does when the Lofi-12 XT app runs on it |
| [11-abi](11-abi.md) | The C6000 calling convention as the stock code uses it, for callbacks into the firmware |
| [12-update-container](12-update-container.md) | The update file format and its seeded CRC-32 integrity fields |

Evidence levels used throughout:
- **device**: seen on the unit (recorded in [experiments/](../experiments/README.md));
- **simulated**: the firmware's own function run in `analysis/c6sim.py`;
- **static**: read from the disassembly;
- **file**: checked against the update files or the flash read.

Each established fact has an ID in [claims.json](../claims.json). Open questions are in
[UNKNOWNS.md](../UNKNOWNS.md).
