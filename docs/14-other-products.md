# Other Sonicware products

Static profiles of every Sonicware update obtained outside the SmplTrek / Lofi-12 XT / CyDrums family
(2026-11-23). Nothing here was run on a device, and none of these images is meant for this unit. Earlier work
on these files covered the container, the CRC seeds and the class names only (INT-4, INT-13 to INT-17).

| Profile | Releases | Claims |
| --- | --- | --- |
| [Liven line](15-liven.md): 8bit warps, XFM, Bass&Beats, Lofi-12, Mega Synthesis, Ambient Ø | 10 (SysEx) | LIV-1..LIV-12 |
| [ELZ_1 play and MINIMAL](16-elz1-play-minimal.md) | 3 + 1 | ELP-1..ELP-13, MIN-1..MIN-6 |
| [Original ELZ_1](17-elz1.md) | 7 (legacy container) | ELZ-1..ELZ-14 |

Each profile has the same sections (A image, B SYS/BIOS, C hardware use, D application, E formats and
protocols, F release history, G relation to SmplTrek), an open list and tool notes. The session scripts behind
them are in [analysis/other_products/](../analysis/other_products/README.md). Since 2026-11-23
`mmtd2elf.mmtd_sections` reads the legacy ELZ_1 container, so every analysis tool can read the sections of all 24
images (the CRC checker still rejects that layout, [UNKNOWNS.md](../UNKNOWNS.md); some subsystem maps still know
only the three main products, see "Tool issues found").

The Liven **Lofi-12** (product 7, a SysEx update, `LIVEN_LOFI_SYSTEM*.syx`) is a different product on a different
board from the **Lofi-12 XT** of the SmplTrek family (product 12). In these profiles "Lofi-12" alone is always
the Liven one; the SmplTrek-family product is always written "Lofi-12 XT".

## Side by side

From the claims named; "?" = not settled statically. SmplTrek family values are from `01-platform-map.md`.

| | Liven (6 products) | Original ELZ_1 | ELZ_1 play | MINIMAL | SmplTrek family |
| --- | --- | --- | --- | --- | --- |
| Product number | 2, 3, 4, 7, 11, 13 | 1 | 8 | 16 | 5, 12, 8 |
| Peripheral clock in code | not found by constant search | 186 MHz (ELZ-3) | 228 MHz (ELP-5) | 228 MHz (ELP-5) | 186 MHz |
| Audio rate, block | 48 kHz (8bit, XFM, Lofi-12, Mega) or 32 kHz (Bass&Beats, Ambient); 64 frames (8bit) or 128 (LIV-4, LIV-5) | 48 kHz, 64 frames (ELZ-4) | ? | ? | 48 kHz, 128 or 96 frames |
| I2S clock master | DSP (LIV-3) | DSP, medium (ELZ-5) | as SmplTrek's `mcasp_configure` (ELP-9) | as ELZ_1 play (ELP-9) | codec |
| Display | segment LED, inference (LIV-10) | LCDC LIDD, 320 x 240 RGB565 (ELZ-3) | LCDC LIDD, 320 x 240 RGB565 (ELP-3, ELP-4) | segment/character display, inference (MIN-3) | 128 x 128 OLED |
| Panel input | DSP GPIO scan (LIV-1) | DSP GPIO scan task, 5x8 + 4x4 (ELZ-6) | DSP; Timer2 + EDMA CC1 to GPIO from 2.0 (ELP-6, ELP-7) | as ELZ_1 play (ELP-7) | panel MCU over UART1 |
| Pots, battery | ? (LIV-11) | ? | ? | one external-ADC path (MIN-4) | via panel MCU |
| Storage | SPI1 NOR only (LIV-10) | FatFs on SPI0 NOR, 8 MB (ELZ-7) | SD card (ELP-11) | 40 MiB RAM-disk FatFs (MIN-2) | SD card |
| USB | none (LIV-10) | mass storage, MIDI (ELZ-8) | audio + MIDI, SmplTrek shape (ELP-10) | mass-storage config | audio + MIDI |
| MIDI | DIN, UART0 (LIV-10) | USB only as far as seen | USB; a UART0 Hwi exists, its role not traced (ELP-6) | ? | USB, DIN |
| Runtime library | CGT 8.3.2-8.3.10 form (LIV-8) | no installed CGT matches (ELZ-12) | CGT 8.3.11-8.3.13 (ELP-2) | CGT 8.3.11-8.3.13 (ELP-2) | CGT 8.3.11-8.3.13 |

## What this adds to the family picture

- Three hardware lines share the C674x SYS/BIOS framework (INT-14), not one board: the Liven boards (no USB,
  no SD, no display controller, DSP clock master, DIN MIDI), the ELZ_1 / ELZ_1 play colour-LCD boards, and the
  SmplTrek box (OLED, panel MCU). ELZ_1 play and MINIMAL also differ from SmplTrek in the clock they assume (228
  against 186 MHz) and in DMA-driven GPIO scanning, so neither is the SmplTrek board (ELP-8).
- The Liven SysEx backup protocol shares the update's framing and 210-byte chunking (LIV-6); the apps ignore
  the update category, so the Liven bootloader alone receives updates (LIV-7, 8bit warps 3.0.76 fully shown).
- ELZ_1 play's application layer descends from the original ELZ_1 by class design, not by shared binaries
  (ELZ-13). The original ELZ_1 never moved to the modern framework namespaces (HAL::, MIDI::, AudioEngine::),
  even in v7.0 (ELZ-14).
- Why ELZ_1 play and CyDrums share product number 8 is still not answered by any code (ELP-12, open).

## Tool issues found

The analysis-tool bugs met while writing these profiles (not fixed) are listed in
[analysis/README.md](../analysis/README.md), "Known issues".
