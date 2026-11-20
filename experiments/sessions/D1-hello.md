# Session D1: the hello skeleton, a firmware with no Sonicware code, on the SmplTrek (planned 2026-11-12; runs 1 to 6 on 2026-11-13, run 7 on 2026-11-14)

> **Run seven times, 2026-11-13 to 2026-11-14, images 0.2.3 to 0.2.9:** the display, keys, encoders, card, app loader, LEDs and the panel MCU link all work from an image with no Sonicware code; 0.2.9 was left installed after run 7.
>
> **Results:** the run sections below and "Results" at the end; summary in `experiments/README.md`. The steps and expectations further down are the pre-registration, kept as written for run 7.

**Purpose.** First boot of a firmware with no Sonicware code. Does a GCC-built bare-metal image that
drives the display, the key matrix, the encoders and the panel MCU from the register sequences in
`docs/04-hardware-access.md` run on the hardware? Every outcome short of "it works" is informative and
pre-registered below; none is dangerous, because the image never writes flash and the bootloader reads HOME
before loading it.

**Gate: session D0 must have passed** (`D0-hang-recovery.md`: HOME + power reaches BOOT MODE with an app that
never runs). D0 passed on 2026-11-12, before run 1.

**Outcome per run** (details in the run sections below; each run wrote the next image over the previous one):

| Run | Date | Image | Outcome |
|---|---|---|---|
| 1 | 2026-11-13 | 0.2.3 | hung on the bootloader's logo before the first frame; four unbounded waits, so no way to say where |
| 2 | 2026-11-13 | 0.2.4 | switched itself off about 15 s after the logo, fault 3: the image runs, the PSC transition completes, the first OLED command byte never completes on SPI1. Cause, found the same day in the stock's disassembly: its driver build (`0xC1626468`) writes SPIPC0 = `0x0E01` (CLK, SIMO, SOMI and SCS0 as SPI function pins) through `0xC167140C` right after the master-mode write, outside the register set-up function first traced; after SPIGCR0's reset every SPI register is at its reset value (SPRUH79C 28.2.15.1), so without that write the pins are GPIO and the master never completes a transfer. (So the stock does write the pin control register, from the driver constructor, contrary to a pre-registered note below.) |
| 3 | 2026-11-13 | 0.2.5 | boots to the status page and loads the hello app from the card: display, key matrix, encoders, SD driver, FatFs and loader work. Text unreadable (every pixel pair swapped); nothing seen from the panel MCU |
| 4 | 2026-11-13 | 0.2.6 | UART1 transmit reaches the MCU (TRK 8 bright blue at start, TRK 10 dimmer; the VALUE sweep lights LEDs); text still unreadable with the nibble order reversed |
| 5 | 2026-11-13 | 0.2.7 | the test pattern's photograph gives the pixel order: 64 blocks of 128 bytes, one row pair per block, even columns in the first half and odd in the second, the even row in the low nibble (HW-35), not row-major; MCU silent |
| 6 | 2026-11-13 | 0.2.8 | pattern exactly as drawn, border complete on all four sides, 1 x text legible (HW-35 confirmed, no shift): the display is done. Nothing received on UART1 (`RX 0 00`) with pads pressed and `A0` sent |
| 7 | 2026-11-14 | 0.2.9 | MCU link works: `LP OK`, the `A1` reply parsed (`MCU 01 00 06`, the version DIAG shows), 8,123 bytes and about 2,500 pad messages in 30 s; the first `A0` (about 100 ms after the link set-up) unanswered, the second (2 s later) answered, which explains runs 3 to 6 (HW-46). STEP 1-8 in the low byte and 9-16 in the high byte of bits 32-47, four encoder counts per detent (the stock counts one), the neighbouring LED lighting from value 11, `BYE` staying until the power key is released (HW-47). 0.2.9 left installed |

Every D1 input works on the device after run 7. The clean-up planned as 0.2.10 (encoder detents, LED value range,
per-channel pad rate) went into 0.3.0 with the audio path (session D3, run as part A of M1).

## Run 1, 2026-11-13 (0.2.3 with `/APPS/APP.BIN` on card A): hung before the first frame

Operator report: the update was written; on the normal boot the SONICWARE logo appeared and the unit hung there; the
power key was dead; the supply had to be pulled. That is the pre-registered "logo frozen, no `D1 HELLO`" outcome:
the image never completed its first frame. Nothing in the run says whether the code ran at all, because 0.2.3 had
four unbounded waits before the first frame (the PSC transition for SPI1, twice; the SPI receive flag per byte, for
the four OLED commands and the 8192-byte frame; and, in `delay_us`, TIMER64P0 advancing, whose enable value the
stock trace never showed) and no way to tell a wait from a crash. The flat image was checked against the ELF
after the run: its 41,936 bytes are exactly `.text`, `.rodata` and `.data`, so the device ran what the simulator ran.

## Runs 2 and 3 (0.2.4, 0.2.5): where it stopped

0.2.4 keeps everything from 0.2.3 and adds: time from the CPU time-stamp counter (TSCL, 372 MHz), which needs no
peripheral; every wait bounded; a stage that fails before the display works calls `fault(code)`, which releases
the power hold code x 5 s later; and a proof-of-life check first thing in `main`, before any peripheral register is
touched: a key matrix key (any button except HOME; not a pad) held while the unit starts makes the firmware switch
the unit off at once. TIMER64P0 is only observed now (`TIMER OK` / `TIMER DEAD` on the splash).

Two boots with a stopwatch or video, decoded as follows (T = time from the logo appearing; the bootloader's own
time before the jump is the same on both boots):

| Boot | What you see | Reading |
| --- | --- | --- |
| A: power on with a button held (e.g. PLAY) | unit switches off within a moment of the logo | **the image runs**; go to boot B |
| A | logo stays, power key dead | the code never ran or crashed before its first instruction took effect: bootloader hand-over or image placement; unplug, HOME + power, restore |
| B: power on normally | `D1 HELLO / STARTING`, then `TIMER OK` or `TIMER DEAD`, `MCU`, `CARD`, `APP`, then the status page | the display works; continue with the steps |
| B | switches off about 10 s after the logo | fault 2: SPI1's PSC enable never completed |
| B | switches off about 15 s after the logo | fault 3: an OLED command byte never completed on SPI1 |
| B | switches off about 20 s after the logo | fault 4: the splash frame never completed |
| B | logo stays, no switch-off (boot A switched off) | a crash between the proof of life and the first frame: `timer_init`, `encoders_init` or the OLED set-up registers; unplug, HOME + power, restore |
| B | splash shown, then stuck on a stage word | the stage after that word stalled (MCU: UART1 PSC; CARD: card init; APP: loader); each is bounded, so wait 10 s before concluding |

Boot A ends with the unit off, nothing written: switch on again for boot B.

Run 2 result (2026-11-13, 0.2.4): boot B switched the unit off about 15 s after the logo, fault 3 (operator report, normal boot only;
boot A, the key-held boot, was not run). Run 3 used 0.2.5 with the SPIPC0 write: the normal boot reached the status
page (next section), so the SPIPC0 reading was right. Boot A stays optional from run 4 on: a timed switch-off or a
status page already proves the image runs, and the key-held boot only adds a check of the key scan.

## Run 3, 2026-11-13 (0.2.5 with `/APPS/APP.BIN` on card A): it runs; pixel pairs swapped; nothing from the MCU

Operator report, with two photographs (the status page, the
hello app's page): the update was written over 0.2.4 (which had stayed installed after run
2); the normal boot showed the splash and then the status page; the app loaded from the card and its page appeared;
numbers changed when keys were pressed and encoders turned; the text was garbled and could not be read; no pad LED
was noticed while turning VALUE; no pad press was seen on the page. The key-held boot was not run.

What the photographs settle:

- **The line layout is right and the glyphs are at their places**: `D1 HELLO V0.2.5` can be made out on the first
  line, the page's rows are in order from the top to `LED ... ENC E/D` at the bottom, and the app page's two
  headline lines are where the hello app draws them. So the frame transfer, the row stride and the display
  orientation are as assumed.
- **Within each glyph the pixels are scrambled with full brightness, no half-grey ghosts.** Rendering the simulated
  frame under candidate corruptions and comparing with the photograph: a one-bit shift of the SPI stream leaves the
  text readable with grey ghosts (not what the photo shows); swapping the two nibbles of every byte reproduces the
  photo's shapes (the `D` turns into a crossed shape, `1` into `!`, `H` into `+|`, `L` keeps its stem one pixel
  right). So the unit shows the HIGH nibble as the left pixel of each pair. The skeleton put even x in the low
  nibble, following `docs/04-hardware-access.md` "Pixel format", a static reading of the stock's `draw_text_impl`
  that has the parity the other way round; the device decides (claim HW-33). The remap command sent is the stock's
  (`A0 07`), and the bootloader initialised the panel before the jump, so the display state is the stock's.
- **Keys and encoders work** (numbers changed), though their values could not be read.
- **The panel MCU link showed nothing**: no LED on the sweep, and the MCU / MSGS lines were unreadable, so transmit
  and receive are both unproven. The sweep is a weak test (it starts at address (0,0,0), a row-0 LED, on one of the
  three planes at value 3, which may be invisible), and the page's counters would have answered but could not be
  read. Run 4 lights the three channels of the stock's pad index 0 at value 6 right after the three start-up bytes,
  and shows how many bytes the transmitter never accepted (`DROP` on the MSGS line).

0.2.6 changes: even x in the high nibble in the graphics code (the hello app draws through the image's API, so it
needs no change); `main.c` sends `C1 2 1 5 6`,
`C1 2 1 4 6`, `C1 2 1 6 6` after `90 B1 A0` (the stock's pad index 0, table in 04-hardware-access.md "Panel LEDs");
`uart1.c` counts bytes dropped after the 10 ms transmitter wait; the status page shows `UP` on the BAT line and
`DROP` on the MSGS line. Tests: pixel order pinned on the splash frame; the start-up bytes include the LED messages;
no byte dropped in the simulator (26 tests).

Reading run 4 (after the text is legible):

| What you see | Reading |
| --- | --- |
| one pad lit from the splash on (note which) | UART1 transmit reaches the MCU and the LED address table is right |
| no pad lit, `DROP 0` | bytes left the UART; the MCU did not act on them (baud, pin, the MCU's state after the bootloader, or the LED address) |
| no pad lit, `DROP` > 0 | the transmitter never became ready: PSC1 module 12 or the UART set-up |
| `MCU` line not all zero (01 00 06 at the end) | receive works: the `A0` request was answered |
| `PAD` values move when a pad is pressed, `MSGS` first number counts up | pad messages arrive |
| text legible | the pixel order is settled (claim HW-33 observed-device) |

## Run 4, 2026-11-13 (0.2.6 with `/APPS/APP.BIN` on card A): LEDs work; text still unreadable

Operator report with three photographs (the pads, the app
page, the status page): the update was written over 0.2.5; the pad lit from
the start is TRK 8, bright blue, and TRK 10 also shows a dimmer blue; turning VALUE on the status page lights LEDs,
jumping around the panel rather than in order; the text is still garbled on both pages and the MCU line cannot be
found. So:

- **UART1 transmit reaches the MCU** and the `C1 a b c v` message does what the stock's `led_set` does. The three
  channels sent, (2,1,5), (2,1,4), (2,1,6) at value 6, were the stock's "pad index 0"; they lit TRK 8 brightly and
  TRK 10 dimly, so either that table groups channels of two pads or one value-6 channel is a dim colour on the
  neighbour. The sweep jumping about is expected: address order `a x 48 + b x 8 + c` is not panel order. Settling
  which address is which needs the index readable, which the 2 x page gives.
- **The pixel fault is not a nibble swap.** 0.2.5 (even x low nibble) and 0.2.6 (even x high) are both unreadable
  with the lines in the right places and the glyphs scrambled at the one- or two-pixel scale. A per-row shift, a
  bit-order change or a stride other than 64 bytes would each show differently from what the photographs show,
  but the photographs cannot be read pixel by pixel (grid recovery from them failed: the dots blur together).
  Claim HW-34 is downgraded accordingly.

0.2.7: after the `TIMER OK` splash stage the firmware draws a test pattern and waits for any key
but HOME; then the MCU, CARD and APP stages follow and the status page is drawn with every font pixel as a 2 x 2
block (12 characters by 9 lines). Pattern (all grey 15 unless said): a one-pixel border; single-pixel vertical lines
at x = 16 (even) and x = 49 (odd) from y = 8 to 119; a two-pixel bar at x = 32-33 and a three-pixel bar at x = 64-66;
at x = 72-123: row 16 every pixel, row 20 even x only, row 24 odd x only, row 28 alternate byte pairs; a 45-degree
line of single pixels from (80, 40); a staircase of single pixels four columns per row from (80, 60); a grey ramp
2..14 in four-pixel steps at rows 72-75; an eight-pixel checkerboard at rows 80-119. What it tells: the shape of the
x = 16 line is the per-row shift function; rows 20 and 24 against row 16 show where each nibble lands; the 45-degree
line and the staircase show how single pixels move; the ramp shows whether the grey bits are in order; the
checkerboard is a coarse reference that survives any one-pixel scramble.

Run 5 steps differ from run 4 only in step 4b: after `TIMER OK`, the pattern page appears and stays. Photograph it
from straight ahead, as close and sharp as the phone allows (the whole panel filling the frame, no flash), then press
any button except HOME. The MCU / CARD / APP stages follow and the 2 x status page appears; photograph it, press a
pad firmly and photograph again, turn VALUE a few clicks and photograph again.

Status page, 2 x font (each line 12 characters wide):

```
0.2.7  12  H          version, seconds since start, H while HOME is held
MCU 01 00 06          the last three bytes of the A1 reply (MCU 1.0.6)
MSG 123 1 0           pad messages (mod 1000), A1 replies (mod 100), UART bytes never sent (mod 10)
PAD 3 1FFF            the pad with the highest reading (hex index 0-E) and its 14-bit reading
KEY 00000000          the low 32 bits of the switch word
ENC 0 0 0 0 0         the low hex digit of each encoder count (A B C D VALUE)
CARD OK               the card mount, as before (NO CARD, NOT FAT, E-n xxxx, FR nn)
APP HELLO             the loader result (NO APP FILE when the file is missing)
LED 143 257 6         the sweep: index, a b c, value; OFF before VALUE is turned
```


## Run 5, 2026-11-13 (0.2.7 with `/APPS/APP.BIN` on card A): the pixel order read from the pattern; MCU silent

Operator report with three photographs (the pattern page, the
app page, the 2 x status page): the update was written over 0.2.6; the
pattern page appeared; the app page's 1 x text is still garbled; the 2 x status page reads clearly: `0.2.7 37`,
`MCU 00 00 00`, `MSG 0 0 0`, `PAD 0 0000`, `KEY 0000000` (the eighth digit cut off by the right edge), `ENC 0 0 0 0`,
`CARD OK`, `APP HELLO`, `LED OFF`; turning VALUE changed the LED line but lit no LED this time; pressing pads did not
change the PAD line.

**The pixel order, from the pattern photograph** (9.7 photo pixels per display pixel; dot centres and widths measured
from brightness profiles, then checked by rendering the drawn frame through the candidate mapping). What the
photograph shows: a row of `FF` bytes is a row of dots at a two-pixel pitch, while a column of `FF` bytes (x = 32-33)
is a continuous bar and a column of `F0` or `0F` bytes (x = 16, 49, 66) a column of beads at a two-row pitch; the
even-x row (20) and the odd-x row (24) put their dots at the same x, the odd-x row one row higher; the staircase's
odd-row pixels sit one row up and one column right of where they were drawn, pairing with the even-row pixel before
them; the 45-degree line comes out as eight short dashes tilted the other way, the odd pixel of each pair one row
above and one column right of the even one. One mapping fits all of it: frame byte k, nibble n (0 = high) lights
panel pixel X = 2 (k mod 64) + ((k div 64) mod 2), Y = 2 (k div 128) + (1 - n). In drawing terms: **the frame is 64
blocks of 128 bytes, block y >> 1 holding the row pair (2k, 2k+1); the first 64 bytes of a block are the even
columns, the next 64 the odd columns, one byte per column; the even row of the pair is the low nibble, the odd row the
high nibble** (byte 128 (y >> 1) + 64 (x & 1) + (x >> 1)). That is a 128-segment by 128-common controller mounted with
its segments running down the screen, its memory written column by column (vertical address increment) with the
common lines split odd/even; `A0 07` with that wiring. Drawing the 0.2.7 pattern in the old row-major order and
viewing it through this mapping reproduces every feature of the photograph: dotted border, beaded single lines,
solid two-pixel bars, paired staircase, reversed dashes. The 2 x font survived because a 2 x 2 block maps onto a
2 x 2 block. Not settled by the photograph: a uniform one-row or one-column shift of the whole picture (the border
positions cannot be read to that accuracy); 0.2.8's pattern page shows it as a missing border line if there is
one. Claim HW-35; HW-34 (even x in the high nibble, row-major) was wrong and is superseded, as is the static
"Pixel format" reading in `docs/04-hardware-access.md` (corrected the
same day: the stock's `draw_text_impl` writes exactly this byte, the earlier reading took
the parity from the wrong variable).

**The MCU link**: nothing received at all (MCU 00 00 00, no replies, no pad messages), and no LED lit on the sweep
either, although in run 4 the same `C1` messages lit LEDs. The difference between the runs: 0.2.7 set the link up
only after the pattern page, tens of seconds after power-on; 0.2.6 within a second of it. Whether TRK 8 lit at the
`MCU` stage in run 5 was not reported. Hypotheses, in the order 0.2.8 tests them: (1) the MCU accepts the link only
within a window after power-on, or needs traffic to stay awake: 0.2.8 sets the link up before the pattern page
again, so the pattern page's wait then tells whether a long silence loses it (TRK 8 lit at the MCU stage, then the
sweep on the status page); (2) the receive side: nothing arriving (pin, level, the MCU not sending) against bytes
arriving that the parser does not recognise: 0.2.8 counts every received byte and shows the last one (`RX n xx`).

0.2.8: `gfx_pixel` writes the order above (everything drawn through it follows, the apps' `text`
and `pixel` included); the MCU stage comes before the pattern page; the pattern page polls the UART while it waits;
the status page's ENC line is replaced by `RX` (bytes received mod 10000, last byte in hex) and the KEY line shows
the low 28 bits (the 32-bit field overran the 12-character line). The 2 x page stays this run so it reads even if a
shift remains. Simulator tests: the splash and pattern frames checked in the new byte order.

Run 6 steps are run 5's with the version strings `V0.2.7 -> V0.2.8` and `V0.2.8 -> V3.2.174`. In step 4b note whether
TRK 8 lights at the `MCU` stage, which now comes before the pattern page. Photograph the pattern page straight on as
before: it should now be exactly the drawing (a one-pixel frame on all four sides, five continuous vertical lines, a
straight diagonal, a smooth ramp); any missing border line or doubled line is the shift to report. Then press a key:
the app page's small text should read. HOME; the 2 x page: photograph; press a pad; turn VALUE a few clicks and say
whether an LED lights and what the RX line shows.

Status page, 2 x font, 0.2.8 (differences from 0.2.7 below): line 5 `KEY 0000000` (28 bits); line 6 `RX 0 00` (bytes
received, the last one in hex) in place of ENC.

## Run 6, 2026-11-13 (0.2.8 with `/APPS/APP.BIN` on card A): the pixel order confirmed; UART1 receives nothing

Operator report with three photographs (the pattern page, the
app page, the 2 x status page): the pattern page is exactly the drawing: a
one-pixel border on all four sides, the five continuous vertical lines (x = 16, 32-33, 49, 64-66), the three dotted
rows, a straight 45-degree line, the staircase, the ramp and the checkerboard. The app page's 1 x text reads (`HELLO
FROM AN APP` / `LOADED FROM THE CARD` / `LAST KEY 23 UP` / `ENC SUM +0` / `PADS HIT 0` / `HOME: BACK TO MENU` / `ON DC`).
The 2 x page: `0.2.8 82`, `MCU 00 00 00`, `MSG 0 0 0`, `PAD 0 0000`, `KEY 0000000`, `RX 0 00`, `CARD OK`, `APP HELLO`,
`LED OFF`. TRK 8 lit at start; the VALUE sweep lit LEDs (in one of several restarts it did not, not reproducible);
the RX line never changed and the PAD line never changed whatever pads were pressed; the STEP buttons did not show on
the KEY line; encoder D changes the brightness of the lit LED, and at high values the LED of the neighbouring button
lights as well; the start-up stages pass too fast to be seen before the pattern page.

**Settled:** the display, fully: claim HW-35 is observed a second time with no residual shift (the border is complete
on all four sides), the 1 x font reads, so the API's `text` and `pixel` draw correctly for apps. The STEP buttons are
not missing: they are bits 32-47 of the 48-bit switch word (`docs/10-cross-flash-button-map.md`) and the 2 x page
showed bits 0-27 only; the app page's `LAST KEY 23` shows the matrix read works. The fast boot is expected: nothing
waits before the pattern page any more.

**Open: the receive side of the MCU link.** Four runs (3, 4, 5, 6), with the link set up early (3, 4, 6) and late (5),
pads pressed each time and `A0` sent each time, delivered not one byte: `RX 0 00` means LSR never showed data ready.
The transmit side works (TRK 8 at start, the sweep). Two hypotheses: (a) the image's receiver set-up never delivers (the
reset release, the FIFO, the RXD pin mux: every value is the stock's traced one, but a trace can miss a write, as
SPIPC0 showed in run 2); (b) the MCU does not send to the image: it may need something the stock does between `90`, `B1` and
`A0` (the power check and the card set-up sit there, tens to a thousand milliseconds), or it answered `A0` before the image's
receiver was ready, or it reports on a line the image does not read. 0.2.9 separates them: `uart1_init` ends with the UART's
internal loopback (MCR LOOP: the transmitter feeds the receiver inside the peripheral, the TXD pin held high, so the
MCU sees nothing); a byte that comes back proves the receiver, FIFO and status path, shown as `LP OK` or `LP BAD` on
the status page. For (b) the start messages go out 50 ms apart with the UART polled in between, and `A0` is repeated
every 2 s while no `A1` reply has come, with the count shown, so an MCU that starts late is still asked. Not tested
(run 7 made it unnecessary): the RXD pin's level as a GPIO (which GPIO shares the pin is not mapped) and any enable or level shifter
between the MCU and the DSP (none known).

**The LED value:** the stock sends 0, 1, 3 and 6; the sweep allows 0-15. A high value lighting the neighbouring
button's LED too suggests the MCU keeps a narrower field per channel than a byte, or a range of about 0-7, with the
excess spilling into the next channel (inference). Run 7 asks at which value it starts (the LED line shows the value).
The intermittent "no LED on the sweep" after one restart is recorded, not explained; the dropped-byte count (MSG's
third number) and the `LP` result on the status page are the two things to read if it happens again.

0.2.9: the loopback self-test and `uart1_loopback_ok`; the start messages spaced and polled;
`A0` repeated every 2 s while unanswered (`a0_sent`); the status page back at 1 x (21 characters by 14 lines) with the
whole 48-bit switch word (`KEY hhhh hhhhhhhh`, STEP 1-16 in the first field), the five encoder counts, `RX n xx LP OK`,
and `A0 n` on the MCU line; no pattern wait at start (the app loads straight away); the pattern page is shown by REC
on the status page (REC again or HOME returns); `timer_ms` catches up by a constant division instead of one
subtraction per elapsed millisecond. Simulator tests: the model echoes THR into the receive FIFO under MCR
LOOP and, with `mcu_answers`, answers `A0` with `A1 12 34 56 01 00 06`; the REC key is modelled (row 3, GP3[3]).

Run 7 steps are run 6's with the version strings `V0.2.8 -> V0.2.9` and `V0.2.9 -> V3.2.174`. Step 4b: the splash
stages, then the app page straight away (no pattern page). HOME: the 1 x status page; photograph it; read `LP OK` or
`LP BAD` and the `A0` count (it grows by one every 2 s while the MCU stays silent). Press pads: does `RX` move? Press a
STEP button: the first KEY field. REC: the pattern page (a display check; REC again returns). Turn VALUE to a pad LED
and D upwards: the value at which the neighbouring LED first lights.

Status page, 1 x font, 0.2.9:

```
0.2.9  82           H     version, seconds since start, H while HOME is held
MCU 00 00 00 A0 1         A1 reply bytes 3-5 (01 00 06 expected); A0 requests sent (one at start, +1 per 2 s unanswered)
MSG 0 0 0                 pad messages, A1 replies, bytes the transmitter never accepted
RX 0 00 LP OK             bytes received (any value), the last one in hex; the receiver self-test (LP BAD = the set-up)
PAD 0 0000                the pad with the highest reading, and that reading
KEY 0000 00000000         the 48-bit switch word: bits 47-32 (STEP 1-16) then bits 31-0 (HOME 27, REC 26)
ENC 0 0 0 0 0             A B C D VALUE counts, last two digits, signed
CARD OK
APP HELLO
LED OFF                   or `n a b c v` while the sweep has an LED lit
VALUE LED  D VALUE        hints
HOME APP  REC PATTERN
```

## Run 7, 2026-11-14 (0.2.9 with `/APPS/APP.BIN` on card A): the MCU link receives; STEP bytes, encoder steps, LED range

Operator report with two photographs (the 1 x status page 30 s after power-on,
SYSTEM DIAG). The page reads `0.2.9 30 / MCU 01 00 06 A0 2 / MSG 506 1 0 /
RX 8123 00 LP OK / PAD 2 0002 / KEY 0000 00000000 / ENC 0 0 0 0 0 / CARD OK / APP HELLO / LED OFF`. The RX count and
the PAD line moved constantly; pad readings at rest fluctuate between 0 and 2; each encoder detent gives four counts;
REC shows the pattern page; the STEP buttons change the first KEY field, STEP 1 = `0001`, STEP 2 = `0002`, STEP 3 = `0004`, STEP 8 = `0100`, STEP 9 =
`0200` and so on (operator; STEP n = bit 31 + n of the switch word); the pads are labelled TRK 1-10, GLOBAL 1-3, USB AUDIO and EXT SRC, and their channel indices run left to right
alternating bottom and top: index 0 = TRK 8, 1 = TRK 1, 2 = TRK 9, 3 = TRK 2, 4 = TRK 10, 5 = TRK 3, 6 = GLOBAL 1, 7 = TRK 4, 8 = GLOBAL 2, 9 = TRK 5, 10 = GLOBAL 3, 11 = TRK 6, 12 = USB AUDIO, 13 = TRK 7, 14 = EXT SRC (operator, from the PAD
line; corrected 2026-11-14 after a first write-up that invented labels TRK 8-14). The odd indices are TRK 1-7, the even ones TRK 8-10,
GLOBAL 1-3, USB AUDIO, EXT SRC, which is the stock's track table order (tracks 0-9, GLOBAL 10-12, USB 13, EXT 14 in
01-platform-map.md) interleaved; TRK 8 lighting at start as the stock's pad 0 LED fits; the neighbouring LED lights from value 0xB (11); `BYE` stays on the screen until
the power key is released. DIAG: BOOT 1.0.17 OK, MCU 1.0.6 OK, PRESET 2.0.22 OK, SYSTEM 0.2.9 OK. Stock was not restored
afterwards: the operator kept 0.2.9 installed since everything works (card B stays the recovery path).

**Settled: the receive side works, and HW-36 is answered.** `LP OK` is the receiver set-up delivering a byte. `MCU 01
00 06` with one reply counted is the `A1` message parsed by the image's parser, and the version equals DIAG's MCU 1.0.6: first
device evidence for the A1 layout (bytes 3-5 = version, HW-39) and for the stock's start bytes doing what the static
reading inferred. 8,123 bytes in 30 s is about 270 bytes/s; `MSG` shows pad messages modulo 1000, and 8,116 bytes
after the 7-byte reply is about 2,700 three-byte messages, so the count is 2,506 (the rest were bytes the parser
resynchronised on, not counted): about 85 pad messages per second with nothing pressed. The MCU streams channels
continuously, not only on change (inference from the rate at rest); how the 16 channels share it is not counted
(0.2.10 counts per channel). (An undercount: session M1 measured 4192 pad messages per second, about 262 per
channel, HW-55; the polling here lost most of them, inference.) `A0 2` is the discriminating observation: the first `A0`, sent about 100 ms after the UART
set-up (50 ms after `90`, 50 ms after `B1`), was not answered within 2 s; the second was. In runs 3, 4 and 6 the only
`A0` went out at once after the set-up, and in run 5 after a wait but with the sweep showing nothing either; none got a
byte. So hypothesis (b) of run 6 holds in its first form: the MCU does not act on a request sent that early after
the link is brought up, and the stock never sends one that early (its `A0` follows the power check and the card
set-up, 0.5 s or more after `90`). Hypothesis (a), the receiver set-up, is excluded by `LP OK` before the first `A0`
and by the reception that followed. Not separated: whether `90` and `B1` are needed at all, whether pad streaming
starts without an `A0`, how long after power-on the MCU listens (somewhere between 0.1 s and 2.1 s), and whether the
loopback toggle itself played a part (the receiver set-up is otherwise identical to 0.2.8; a build without the
self-test would show it; low priority, since repeating `A0` is the stock-like behaviour anyway).

**Other observations.** (1) Encoders: `encoders_poll` adds one count per quadrature edge, and a detent is a full
four-edge cycle, so four per detent; the stock counts one per detent (HW-37). 0.2.10 reports detents. (2) STEP keys:
STEP n is bit 31 + n: bits 32-39 are STEP 1-8 and bits 40-47 STEP 9-16, which in the matrix (bit 8r + c) is row GP2[4],
columns 0-7 = STEP 1-8, and row GP2[5], columns 0-7 = STEP 9-16. (3) Pads:
readings at rest 0-2 of 14 bits; the stock's press threshold is 800 and release 100, so the noise is far below both.
(4) LED values: the neighbouring LED lights from 11, so one LED takes values 0-10 (inference: eleven brightness
levels, or an eleven-entry table whose overflow runs into the next channel); 0.2.10 limits the sweep to 0-10. (5)
Power-off: after `power_hold_release` the unit stays on while the key is held, so the key feeds the supply in parallel
with the hold line (inference; the stock's 1 s wait before releasing the hold is unrelated to this). Not a fault.

**0.2.10 (to build):** encoder detents (count at phase 0 with a direction, as the stock), the sweep's value range
0-10, a per-channel message counter and the time of the first received byte and of the `A1` reply on the status page
(to bound the MCU's readiness window without another request schedule), and the pad index shown with its reading.
No start-order change: `90`, `B1`, `A0` 50 ms apart and `A0` repeated every 2 s until answered stays.

### LED address table (started 2026-11-14 with 0.2.9, VALUE sweep index n = 48a + 8b + c, D at a value below 11)

Operator's readings so far (`?` = nothing lit):

| n | (a, b, c) | lit | n | (a, b, c) | lit |
| --- | --- | --- | --- | --- | --- |
| 0 | 0,0,0 | VOL L | 9 | 0,1,1 | TRK 2 green |
| 1 | 0,0,1 | VOL R | 10 | 0,1,2 | TRK 2 red |
| 2 | 0,0,2 | microphone | 11 | 0,1,3 | TRK 2 blue |
| 3 | 0,0,3 | VALUE blue | 12 | 0,1,4 | TRK 9 green |
| 4 | 0,0,4 | VALUE green | 13 | 0,1,5 | TRK 9 red |
| 5 | 0,0,5 | VALUE red | 14 | 0,1,6 | TRK 9 blue |
| 6, 7 | 0,0,6 / 0,0,7 | ? | 15 | 0,1,7 | ? |
| 8 | 0,1,0 | TRK 4 blue | 16 | 0,2,0 | USB AUDIO green |
| 24 | 0,3,0 | STEP 10 green | 27 | 0,3,3 | STEP 3 red |
| 25 | 0,3,1 | STEP 10 red | 28 | 0,3,4 | STEP 4 green |
| 26 | 0,3,2 | STEP 3 green | 48-55 | 1,0,0..7 | the same as 0-7 (plane 1 of row 0 repeats plane 0) |
| 30 | 0,3,6 | STEP 5 green | 32 | 0,4,0 | STEP 6 green |
| 34 | 0,4,2 | STEP 15 green | | | |

**All nine pad readings equal the static pad table** (04-hardware-access.md "Panel LEDs", `panel_map.py`) once the pad
channel is read through the run-7 channel table (channel 7 = TRK 4, 3 = TRK 2, 2 = TRK 9, 12 = USB AUDIO), and they fix
the colours: `pad_rgb_set`'s v1 = red, v2 = green, v3 = blue. (0,1,7) is in no pad and lit nothing, as the table
predicts. So the 45 pad addresses count as observed through the table (claim HW-48) and need no further sweeping. The
row-0 LEDs on plane a = 0: VOL L, VOL R, microphone, then the VALUE encoder's blue, green, red at c = 3, 4, 5; (0,0,6)
and (0,0,7) nothing, as the six-LED reading predicts. The static reading says planes 1 and 2 of row 0 are always written
with the same value; plane 1 (indices 48-55) lights the same six LEDs as plane 0 (operator), so a single plane drives them;
plane 2 unobserved. The first STEP readings show the two-channel LEDs are green at even c and red at c + 1, and that
the STEP order on the chip is not the panel order (STEP 10, 3, 4 at c = 0, 2, 4 of (0,3,x)): the step-to-address table
is wired, not computed, so it has to be read off the unit or traced from the stock's step LED setter table (not
traced statically yet; the wrappers for rows 3 and 4 had no direct caller).

Closed the same evening by static work (04-hardware-access.md "Panel LEDs"): the stock
keeps a 16-entry table `g_step_led_setters` (0xC16EB448) of red/green wrapper pairs, run in c6sim; all six device
anchors land in place, and (2,5,4) / (2,5,6) are STEP 9 and 11. The operator then checked the ten remaining two-channel
LEDs on the unit against the page predictions: CLR, FUNC, HOME, MIXER, STOP, OK, REC, PROJECT, EDIT, PLAY (the green
channel; red is the same LED). So all 144 addresses are accounted for: 45 pad channels, 6 row-0 LEDs (planes 1 and 2
repeat plane 0), 16 STEP pairs, 10 button pairs, the rest unused. Spot check, later the same evening: index 36 = STEP 16 green, 72 = STEP 1 green, 140 = STEP 9 green, all as the
table says, so nine of sixteen STEP LEDs are seen on the device, including both plane-2 entries; the table is settled.
The operator also notes that many plane-2 addresses (indices 96 and up) light only dimly and some light several buttons:
at 140, (2,5,4), the EDIT LED, whose green is (1,5,4), glowed faintly as well. Same (b, c), different plane:
crosstalk between the planes (inference: the three a-planes are time-multiplexed groups of one LED driver, not three
chips, which also fits the stock writing all three planes of the row-0 LEDs with one value). No firmware consequence
beyond keeping values in the stock's range. Expected pairs (c even = one channel, c + 1 the other): rows 3 and 4 of planes 0 and 1 = STEP 1-16
(inference), b = 5 = mode buttons (the `led_callers.py` hints in 04-hardware-access.md), (2,5,4) and (2,5,6) two more.
Indices 48-71 and 96-119 (planes 1 and 2, b = 0-2) can be skipped: pads known, row 0 optional.

## The test file

`experiments/D1_hello_0.2.9.bin` (0.2.0 superseded 2026-11-12 after the code review, 0.2.1 superseded 2026-11-13 after a static
finding about its SD writes, both from code reviews of the image; 0.2.2 replaced 2026-11-13 by 0.2.3,
which added the LED sweep, the card error report, the splash stages, the MCU byte order and the power-key rule below;
0.2.3 ran once, hung, and was replaced by 0.2.4 with bounded waits and the fault codes above; 0.2.4 ran once, reported
fault 3, and was replaced by 0.2.5 with the SPIPC0 write; 0.2.5 ran once, reached the status page with the pixel
pairs swapped, and was replaced by 0.2.6 with the pixel order reversed, a pad lit at start and the dropped-byte count; 0.2.6 ran
once, lit the pad and still showed unreadable text, and was replaced by 0.2.7 with the pattern page and the 2 x status page;
0.2.7 ran once, its pattern gave the pixel order, and was replaced by 0.2.8 drawing in that order, with the MCU link set up
before the pattern page and the received-byte count; 0.2.8 ran once, confirmed the order and received nothing, and was
replaced by 0.2.9 with the receiver self-test, spaced start messages, repeated A0, the 1 x page and the pattern page on REC),
SHA-256 recorded in `experiments/README.md` ("D1 hello skeleton image"), built deterministically with GCC (source
not published). SmplTrek-sealed SYSTEM update, version 0.2.9, one section at `0xC2000000`, entry `_start`. Checks
passed: `sonicware_integrity.py verify --profile smpltrek` 2/2 OK; the image's own test suite (30 tests: build; the register traffic in the simulator matches the stock app's set-up
with no card; the UART1 loopback self-test, the spaced start messages, the repeated and the answered A0; with a
simulated card the SD identification, mount, module load and app callbacks).

Before it went on a card: `sha256sum` on the card matched the ledger.

## What to expect on screen

1. Immediately after the bootloader hands over: `D1 HELLO` / `STARTING` in the middle of the display.
   (2026-11-12, after D0: the bootloader has already initialised the OLED and drawn its SONICWARE logo by then, so
   the splash replaces that logo; the screen is never dark on the way in.) Under STARTING the words `TIMER OK` (or
   `TIMER DEAD`: TIMER64P0 did not advance, which only falsifies the 24 MHz tick-clock inference), `MCU`, `CARD`
   and `APP` appear in turn as each stage starts; if the splash stays, the last word visible says where it stalled
   (card initialisation can take a few seconds when a command times out: each wait is bounded at 500 ms).
2. Within a second, the status page, refreshed 20 times a second:

(The 1 x status page of 0.2.3 to 0.2.6, below, is replaced in 0.2.7 by the 2 x page listed under "Run 4", and that
by the 1 x page of 0.2.9 listed under "Run 6".)

```
D1 HELLO V0.2.6
NO SONICWARE CODE
KEYS  0000 00000000         48-bit switch word, hex; HOME is bit 27
ENC   0 0 0 0 0             encoder counts A B C D VALUE, signed, one per quadrature step
PAD   000 000 ...           15 pad readings / 4, three hex digits each, three rows of five
BAT   0000  DC|BATT  UP s   battery channel, the power source pin, seconds since start
MCU   00 00 00 00 00 00     the A1 reply; the last three bytes are the MCU version (1.0.6 expected: 01 00 06)
MSGS  n m  DROP d           pad messages, MCU replies received, bytes the UART transmitter never accepted
CARD  OK|NO CARD|NOT FAT|E-n xxxx|FR nn   the SD card mount (card A carries the D1 update only, so NO CARD or OK).
                            E-n: sd_init failed at step n (1 no card detect, 2/4 ACMD41 refused, 3/5 ACMD41 never
                            ready, 6 CMD2, 7 CMD3, 8 CMD7, 9 CMD16); xxxx the MMCST0 bits it saw (0010 response
                            time-out, 0080 response CRC error, 0008 read time-out). FR nn: another FatFs result.
APP   status                the app loader: NO APP FILE when no /APPS/APP.BIN, HELLO when the hello app runs
LED   OFF  ENC E/D          the LED sweep: OFF until encoder VALUE (E) is turned; then `n a.b.c Vv`, the lit
                            address n = a x 48 + b x 8 + c (0-143) and the value v sent (encoder D, 0-15, default 3);
                            the word HOME at the right while HOME is held
```

Card A may also carry `/APPS/APP.BIN`, a small hello app loaded by the image (record its SHA-256).
Then, after the splash, the hello app's page replaces the status page: `HELLO FROM AN APP` and the last key,
encoder sum and pad hits. HOME returns to the status page (APP shows the loader result); HOME again reloads it.
Without the file, the status page shows `APP NO APP FILE` and HOME retries. A card that does not mount is
informative, not dangerous (the SD driver's identification sequence past CMD0 is written from the specification,
not traced).

3. Pressing any key changes KEYS and lights LED (0, 0, 0), whichever one that is (04-hardware-access.md open 4).
   Releasing every key turns it off. Turning encoder VALUE one detent at a time lights one LED address at a time
   and clears the previous one: note, for every index at which something lights, the index and a.b.c shown, the
   LED that lit and its colour (the 15 pads take three consecutive addresses each, one per colour; the 26 two-channel
   LEDs two); encoder D changes the value, which should change brightness or colour. Indices nothing answers to are
   expected (29 of the 144 are unused by the stock). Turning a knob changes its ENC count. Tapping a pad changes its PAD value
   (the stock treats a raw 800 and above as pressed: 0C8 and above on this page). UP counts seconds; if it counts at the wrong rate, the 24 MHz
   timer-clock inference is wrong by that factor.
4. Holding the power key for one second (after it has been released at least once since switching on; a hand
   still on it from the power-on press does not count) shows `BYE`, sends B2 to the MCU, releases the power hold: the unit
   switches off.

## Pre-registered outcomes other than the above

| Outcome | Reading | Next |
| --- | --- | --- |
| Unit switches off when the power key is released at start | the bootloader does not latch GP4[11]; D0 should have shown the same | D1.1: drive GP4[11]'s direction too, earlier |
| Screen stays dark, unit stays on | OLED init insufficient (the stock's four commands may rely on the bootloader's own display init), or the SPI pin control register needs writing, or SPI1 clocking differs | A4 dump: trace the bootloader's display path; add its commands; try SPIPC0 (2026-11-13: run 2 showed the transfer itself never completes without SPIPC0; 0.2.5 writes it as the stock does) |
| Text visible but garbled or mirrored | pixel packing or remap reading wrong | adjust `gfx.c` from the photograph |
| Page shows, KEYS never changes | key-matrix read wrong (GP3[9] mux, row timing) | compare with `ControlScan::scan` timing; try a longer settle |
| Page shows, PAD and MCU stay 0, MSGS 0 | the MCU needs a different start-up or the UART rate is off | try the stock's `power_on_check` placement; check 465,000 vs 460,800 |
| Page shows, LED never lights | LED addressing (a, b, c) wrong | the stock LED wrappers |
| CARD shows E-n, FR nn or NOT FAT with a known-good FAT32 card | SD identification or data path differs from the stock's after CMD0; E-n names the step and the controller's error bits | re-seat the card and press HOME (retries the mount); then compare the step with the stock's command table (04-hardware-access.md "Card protocol layer"); try 1-bit bus and 399 kHz |
| Nothing at all and no power-off on the key | the image hung before the display; D0's recovery applies | HOME + power |

Any of these: photograph it, then go to the restore. Do not improvise fixes on the device.

Re-read after D0 (2026-11-12, HW-24): the bootloader latches the power hold and initialises the display before the
jump. So the first row would now mean the skeleton released a latched hold (it only sets GP4[11]; it never clears
it before `BYE`), and the second row would mean the skeleton's SPI1 or OLED set-up disturbed a working panel, not
that the panel was never initialised. The logo frozen on screen with no `D1 HELLO` means the image hung before its
first frame: unplug, then HOME + power, as in D0.

Device state at start: BOOT 1.0.17  PRESET 2.0.22  SYSTEM 3.2.174  MCU 1.0.6 (after D0's restore)
Known deviations from stock: none
Recovery card prepared: card B, official `SmplTrek.bin` 3.2.174, SHA-256
`3b6848b0f041bcf23c73d4b0357d2f3d6dc9e7e03752b32ff7322e91e6814e53`, verified on the card
Second card: card A carries the D1 file as `SmplTrek.bin`

## Before the session

- D0 passed and is written up. Hashes verified on both cards; card A's file confirmed as the current build.
- AC adapter, no batteries (the image has a power-off path, but if it hangs before the loop, unplugging is
  the only way off, as in D0). Headphones off; the image makes no sound.

## Steps

| # | Action | Expected outcome | If different |
| --- | --- | --- | --- |
| 1 | Power on normally; SYSTEM INFO; photograph; power off. | BOOT 1.0.17, PRESET 2.0.22, SYSTEM 3.2.174, MCU 1.0.6 | Stop if SYSTEM is not 3.2.174. |
| 2 | Card A in. HOME + power → BOOT MODE → SYSTEM UPDATE; photograph the confirmation. | `SYSTEM: V0.2.8 -> V0.2.9` (run 6's image stayed installed; `V3.2.174 -> V0.2.9` if stock was restored), `Are you sure?` | Anything else: **CLR**, stop, report. |
| 3 | **OK.** Video the write. | Erasing, Writing, Verifying 100% OK, restart prompt | Verifying fails: continue (normal boot will refuse the image; recovery as D0). |
| 4a (optional) | Power off per the prompt; card A out. Hold a button (PLAY, say; not HOME, not a pad) and power on. | Logo, then the unit switches off by itself within a moment | Logo stays: the image never ran ("Run 2" table); unplug, HOME + power, go to step 8. |
| 4b | **Video running, with a clock in view or the recording's timer.** Power on normally. | `D1 HELLO / STARTING`, `TIMER OK`, `MCU` (TRK 8 lights), `CARD`, `APP` (too fast to read, as in run 6), then the hello app's page; HOME: the 1 x status page (photograph; read `LP OK` / `LP BAD` and the `A0` count) | Switches off by itself: note the seconds from the logo, read the fault from the "Run 2" table, go to step 8. Logo stays: unplug, HOME + power, go to step 8. |
| 5 | Press and release a few keys (HOME last: it toggles the app); turn each knob a few detents both ways; tap three pads lightly then firmly; photograph the page after each. Then turn VALUE slowly from index 0 upwards and record which LED lights at which index (photograph a few, note colours); turn D at a lit LED. | KEYS changes per key; HOME shows the word; ENC counts move (note steps per detent); PAD values move; LED (0,0,0) lights while a key is down; one panel LED lights per sweep index, the previous one going out | Record exactly which inputs respond. If CARD shows E-n: re-seat the card and press HOME once, note whether the code changes. |
| 6 | Read the MCU line and UP; time UP against a watch for 30 s; photograph. | MCU bytes end in 01 00 06; UP advances one per second | A different rate: note the ratio. |
| 7 | Hold the power key one second. | `BYE`, then the unit switches off | Doesn't switch off: unplug the adapter. Record. |
| 8 | HOME + power → BOOT MODE → SYSTEM DIAG; photograph. | BOOT OK, PRESET OK, SYSTEM OK, MCU 1.0.6 | Record and continue. |
| 9 | Card B → SYSTEM UPDATE → confirmation → OK → restart → stock boots. | `SYSTEM: V0.2.9 -> V3.2.174`; SmplTrek UI | Refused or failing: retry once with card B re-verified; else stop and report. |
| 10 | SYSTEM INFO, DIAG, a pad, a project; photograph. | all as in step 1; settings unchanged | A changed setting: record (nothing here writes settings). |

## What this cannot distinguish

- A dark screen does not separate "SPI1 never clocked" from "the controller needs more initialisation"; only
  a scope or the bootloader's display code (A4 dump) does. The session records it and stops.
- Pad values changing shows the UART receive path; it does not show that the stock's thresholds or curves apply.
- ENC steps per detent is an observation to record, not a pass/fail item.

## Stop rules

- Exactly two writes: the D1 image at step 3 and official 3.2.174 at step 9. CLR out of anything else.
- Abort and report if HOME + power does not reach BOOT MODE after three tries (as in D0).
- Unplug on noise, smell or heat.

## Evidence capture

Video for steps 3, 4, 7 and 9; stills of every status page state in step 5 and 6, the confirmation screens,
DIAG and SYSTEM INFO after. Quote screen text exactly.

## Results (filled in during/after)

| # | Observed | Matches expectation? | Evidence |
| --- | --- | --- | --- |
| run 1, 2-3 (2026-11-13, 0.2.3) | update written (operator report; confirmation and write not photographed) | yes | operator's report |
| run 1, 4 | SONICWARE logo, then hung; power key dead; supply pulled to recover | pre-registered: hung before the first frame | operator's report |
| run 1, 5-7 | not reached | — | — |
| run 1, 8-10 | supply pulled; HOME + power; stock 3.2.174 restored from card B (operator report, no photos) | yes | operator's report |
| run 2, 2-3 (2026-11-13, 0.2.4) | update written (operator report) | yes | operator's report |
| run 2, 4a | not run (operator booted normally only) | — | — |
| run 2, 4b | unit switched itself off about 15 s after the logo: fault 3, first OLED command byte never completed on SPI1 | pre-registered ("Runs 2 and 3" table) | operator's report, timing by eye |
| run 2, 5-10 | not reached; 0.2.4 stayed installed (operator, 2026-11-13) | — | — |
| run 3, 2-3 (2026-11-13, 0.2.5, with `/APPS/APP.BIN`) | update written over 0.2.4 (operator report) | yes | operator's report |
| run 3, 4a | not run | — | — |
| run 3, 4b | splash, status page, then the app's page: the image runs through to the loader. Text unreadable: every pixel pair swapped | partly: pre-registered "it works" except the pixel order, which the pre-registration took from the static reading | photos; render comparison ("Run 3") |
| run 3, 5 | numbers changed with keys and encoders (unreadable); no LED noticed on the VALUE sweep; no pad press seen (page unreadable) | keys, encoders yes; MCU link unproven | operator's report |
| run 3, 6-10 | not reported; 0.2.5 left installed | — | — |
| run 4, 2-3 (2026-11-13, 0.2.6, with `/APPS/APP.BIN`) | update written over 0.2.5 (operator report) | yes | operator's report |
| run 4, 4b | splash, status page, app page; text still unreadable with the nibble order reversed | no: the fault is not a nibble swap | photos |
| run 4, 5 | TRK 8 lit bright blue from the start, TRK 10 a dimmer blue; VALUE sweep lights LEDs out of panel order; MCU line unreadable | transmit yes; receive and pads unproven | photo, operator's report |
| run 4, 6-10 | not reported; 0.2.6 left installed | — | — |
| run 5, 2-3 (2026-11-13, 0.2.7, with `/APPS/APP.BIN`) | update written over 0.2.6 (operator report) | yes | operator's report |
| run 5, 4b | pattern page shown and photographed; app page 1 x text still garbled; 2 x status page legible | pattern: yes; the photograph decoded the order (not a nibble swap: row pairs in 128-byte blocks, HW-35) | photos |
| run 5, 5 | MCU 00 00 00, MSG 0 0 0, PAD unchanged by pads, VALUE changes the LED line but no LED lights | no: nothing received, and this time transmit showed nothing either (link set up after a long wait) | photo, operator's report |
| run 5, 6-10 | not reported; 0.2.7 left installed | — | — |
| run 6, 2-3 (2026-11-13, 0.2.8, with `/APPS/APP.BIN`) | update written over 0.2.7 (operator report) | yes | operator's report |
| run 6, 4b | stages too fast to read; TRK 8 lit; pattern page exactly as drawn, border complete (photo) | yes: HW-35 confirmed, no shift | photograph |
| run 6, 5 | app page's 1 x text legible (photo); 2 x page `0.2.8 82 / MCU 00 00 00 / MSG 0 0 0 / PAD 0 0000 / KEY 0000000 / RX 0 00 / CARD OK / APP HELLO / LED OFF` (photo); VALUE lit LEDs (once after a restart it did not); D changed brightness and at high values lit the neighbouring LED; pads changed nothing; RX stayed 0; STEP buttons not on the 28-bit KEY line | display yes; MCU receive no | photographs, operator's report |
| run 6, 6-10 | not reported; 0.2.8 stayed installed (operator, 2026-11-13) | — | — |
| run 7, 1-2 (2026-11-14, 0.2.9, with `/APPS/APP.BIN`) | update written over 0.2.8 (operator report) | yes | operator's report |
| run 7, 3-6 | app page straight away; status page at 30 s: `MCU 01 00 06 A0 2`, `MSG 506 1 0`, `RX 8123 00 LP OK` | yes: receiver works, A1 parsed; the first A0 unanswered, the second answered (HW-46) | photo |
| run 7, 7 | RX and PAD lines move constantly; pads at rest read 0-2 | yes: pads stream | operator's report |
| run 7, 8 | STEP buttons show in the first KEY field: STEP 1 `0001`, 2 `0002`, 3 `0004`, 8 `0100`, 9 `0200`, ... | yes: STEP n = bit 31 + n | operator's report |
| run 7, 9 | four counts per detent on every encoder | observation: the stock counts one per detent; 0.2.10 fixes | operator's report |
| run 7, 10 | REC shows the pattern page and returns | yes | operator's report |
| run 7, 11 | the neighbouring LED lights from value 11 | threshold recorded (HW-47) | operator's report |
| run 7, 12 | the run-6 "no LED after restart" case did not recur (not mentioned) | — | — |
| run 7, 13 | `BYE`, off once the power key is released; the screen stays while it is held | yes, with the note in "Run 7" (5) | operator's report |
| run 7, 14 | DIAG: BOOT 1.0.17, MCU 1.0.6, PRESET 2.0.22, SYSTEM 0.2.9, all OK | yes | photo |
| run 7, 15-16 | not run: the operator kept 0.2.9 installed (everything works; card B remains the recovery path) | operator's choice | operator's report |

Device state at end: BOOT 1.0.17  PRESET 2.0.22  SYSTEM 0.2.9 (run 7 DIAG; left installed by choice)  MCU 1.0.6
Claims updated: (on a pass: every "simulated" line in 04-hardware-access.md that D1 exercises becomes observed-device;
the timer-clock inference, the pixel format, the MCU start-up bytes and the LED address get their first device evidence)
