# Factory test mode (SmplTrek 3.2.174)

The stock firmware has a factory test menu with eight pages. It is part of the normal `SmplTrek.bin`, not a separate
image. Found 2026-11-15 by static reading, then run in the repository's emulator (`emulator/`, unmodified stock, no
guest hooks). **Not seen on the unit.** Claim HW-50.

## Entry and exit

- **Enter:** hold **FUNC** while powering on. The start path (`0xC154A9C0`) tests bit 19 of `g_control_switch_state`
  (`0xC1501DF0`) at about 0.58 s, during the power-key hold. With it set, it opens `AppTestMode` (object
  `0xC15035C0`) instead of the normal start, skipping the startup delay and the USB start.
- **Leave a page:** press **CLR**. `AppTestMode`'s button handler (`0xC1630EE0`) closes the open page on a CLR press
  (event code 1) and passes every other button event, presses and releases, to the page. In one emulator run, CLR
  pressed straight after a VALUE turn and OK did not close LED TEST. Every other run closed it, and this one is not
  explained.
- **Leave test mode:** power off. The menu itself has no exit.

## Menu

A 3 x 3 grid: TEST MODE (title), LED, SWITCH / ENC, ADC, AUDIO / CARD, USB MSC, MIDI. The selection (object +32) starts
on LED. **Up / down** move by 3 and **left / right** by 1, wrapping. **OK** opens the page from the table at
`0xC16DE190`, and the page pointer is kept at object +36. Encoders and the other buttons do nothing on the menu.

## Pages

Page handlers are virtual slots of each `AppTest*` class: 0 open, 1 close, 4 button, 7 encoder `(encoder, delta)`,
12 draw. Controls below were read from the slots and checked by pressing every labelled button and turning every
encoder in the emulator.

| Page | Class | Shows | Controls | Side effects |
|---|---|---|---|---|
| LED | `AppTestLED` | LED TEST: MANUAL / AUTO, RED, GREEN, BLUE levels | **Up / down**: MANUAL or AUTO (object +0x10). With nothing selected, **knobs A / B / C** set the red / green / blue level for all pads, 0-6, wrapping (+0x14, +0x18, +0x1C; table `0xC16EF078` applies them). **Pressing a button selects it** (`B14+0x3B8` = switch bit - 16: FUNC 3, PROJECT 4, MIXER 5, PLAY 6, OK 7, left 8, REC 10, HOME 11, EDIT 12, STOP 13, octave right 15, STEP 1-16 16-31). Knobs **A / B** then set that button's two LED levels, 0-6 (+0x20 + 8 x selection, +4). | LEDs only |
| SWITCH | `AppTestControl` | the panel diagram; each held button is filled in | none; the button handler only redraws | none |
| ENC | `AppTestEncoder` | a scrolling log, one line per detent: knob letter (A, B, C, D, V) and +1 / -1 | turn any of the five encoders | none |
| ADC | `AppTestADC` | the 15 pad channels 0-14 and BT (battery) as values and bars; a "Threshold" (default 3000) | **knobs A / B / C / D** change the threshold by 1 / 10 / 100 / 1000 (a pop-up shows it). What the threshold marks is not traced. | none |
| AUDIO | `AppTestAudio` | AUDIO TEST: an `L-` and an `R-` row, each with a source name | **knob A** steps the left row and **knob B** the right row through 16 sources: OFF, Built-In MIC, L HiZ Low, L HiZ, L HiZ High, L D-Mic U-Low, L D-Mic Low, L LineIn, L LineIn PAD, R D-Mic U-Low, R D-Mic, R D-Mic High, R LineIn, R LineIn PAD, L USB, R USB (values at `0xC16EFC18`; starts L LineIn / R LineIn). Buttons are ignored. | On open: looks for `SmplTrekTestAudio.wav` on the card (read only; with no such file nothing plays), starts USB (the composite device) and unmutes the codec. On close: mutes and stops USB. Whether the file is played is inference. |
| CARD | `AppTestSDCard` | ">> Card inserted", capacity in bytes, write and read time (ms) | **OK** runs the write / read timing test | **Writes the card**: creates `Loop001.wav` in the root, writes and reads about 1 MB, deletes it. Emulator, 8 MiB FAT12 card: afterwards only the root directory sector differs (the deleted entry) and fsck finds the file system clean. A card that already has `Loop001.wav` in its root would lose it. |
| USB MSC | `AppTestUSBMSC` | USB MSC TEST | none found | Opening it starts USB mass storage: the card is offered to a connected computer. Emulator: stops at unmodelled USB0 registers. |
| MIDI | `AppTestMIDI` | MIDI TEST and a log of incoming messages | none (its slots 14 / 15 add a line and redraw) | Starts USB on open (its MIDI interface); stops on close. Message sources not traced (DIN and USB, inference). |

## Use

- **On the unit:** stock 3.2.174 must be installed. LED, SWITCH, ENC and ADC are display-only and safe. Run CARD only on
  a spare card. AUDIO: VOL low, since it unmutes and routes inputs to the outputs. Keep USB MSC unconnected.
- **For mapping:** SWITCH checks every button bit, and the LED selection order above repeats the button-to-LED pairing
  of the stock tables (04-hardware-access.md "Panel LEDs"). ADC shows raw pad values and the battery.
- **For the emulator:** LED, SWITCH, ENC, ADC and CARD run in strict mode. AUDIO and MIDI need the logged
  reserved-low and USB status assumptions, and USB MSC stops at unmodelled USB0 registers. These runs are from
  2026-11-15; the emulator models the measured USB0 reserved words since 2026-11-17 (HW-59), and these three pages
  have not been re-run with it.

## Evidence

- Static: `dis6x` of `0xC154A9C0`-`0xC154AA1C` (the gate), `0xC1549B40` (the `AppTestMode` constructor) and
  `0xC1630EE0`-`0xC1631300` (menu and dispatch). Ghidra decompiles (`ghidra/scripts/DecompileAt.java`, read-only
  run) of the pages' slots 0, 1, 4, 7 and 12. Strings from `work/smpltrek-3.2.174.strings.json` (regenerated locally).
- Emulator, scratch scripts (not committed): each page opened from a FUNC boot, every labelled switch bit pressed and
  each encoder turned both ways, frames compared; the LED page's object (`0xC14FAB38`) and `B14+0x3B8` read after every
  input; AUDIO and CARD run with an empty 8 MiB FAT card, the card exported and checked with `fsck.fat`.
- Not checked: pads on the ADC and MIDI pages (the emulator has no panel MCU model), what AUTO does on the LED page,
  the AUDIO page with the test file present (the card builder cannot write long file names), and anything on the unit.
