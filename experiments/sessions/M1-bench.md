# Session M1: one bench sitting for the open hardware questions (planned 2026-11-15; run 2026-11-16, core scope)

> **Run 2026-11-16 with image 0.3.1, core scope:** P1-P5, A1-A9 (A7, A9 skipped), B1, C1, D1, D2, E1, I1, I2, I4, I5, G7, I6, then stock 3.2.174 restored (H0). Not run: D3, D4, E2, F (L1), G1-G6, H1-H2, I3.
>
> **Results:** "Results" at the end of this file; registry HW-52, HW-54 to HW-61; summary in `experiments/README.md`.

**Purpose.** Answer, in one sitting, the questions that code and simulation cannot:

| Part | Question | Claim / doc it settles |
|---|---|---|
| A | Does the audio path work from a bare-metal image (session D3)? | D3-audio.md |
| B | Cache state at the jump to SYSTEM | HW-52 (simulated) |
| C | SPI flash part number | 05-bootloader.md "Open items" |
| D | How often the panel MCU sends each pad channel | the stock's pad hold timings (`pad_hold_update`) |
| E | Physical key bounce (chatter) | HW-51 (stock debounce, simulated; bounce unmeasured) |
| F | LED map: the 101 addresses not yet seen, and the level steps | session L1 (folded in here) |
| G | What the inferred audio pins do electrically | 04-hardware-access.md "Open" 8 and 11 |
| H | Outputs, VOL, speaker mute and PAD on the stock firmware | session D3-audio-pins (folded in here) |
| I | What a CPU read of reserved low memory (`0x0000000C`) returns, and whether the stock's null read there is harmless; added 2026-11-16 for the emulator: misaligned accesses, narrow low reads, USB0's reserved registers, and CyDrums's store into the EMIFA window | emulator/audio-investigation.md "Separate filename-action fault" (the emulator stops there; "reads return zero" is a hypothesis); the emulator's `--usb-reserved-status-zero` assumption and its refusal of misaligned accesses |

Parts A-G, I1-I2 and I4-I6 run on one bring-up image, **0.3.1**. Parts H and I3 run on the stock firmware after the restore. Out of scope:
the meaning of the panel MCU commands (sending the two the stock never sends, `91` and `B0`, is not authorised);
the battery channel (HW-38); USB.

**Status: run 2026-11-16, core scope (see "Results"; D3, D4, E2, F, G1-G6, H1-H2 and I3 not run). Image 0.3.1 built 2026-11-16** (`experiments/D3_audio_0.3.1.bin`, SHA-256 below; spec below,
simulated in the image's test suite).

Device state at start: BOOT 1.0.17, PRESET 2.0.22, SYSTEM 3.2.174, MCU 1.0.6 (the sheet expected PRESET 1.0.11 by
mistake; the unit has had 2.0.22 since 2026-11-08, as H0 shows)
Known deviations from stock: none
Recovery card prepared: card B, official SmplTrek 3.2.174 update as `SmplTrek.bin` (SHA-256 checked on the card)
Second card: card A carries the bring-up image.

## Settings likely to change (named before starting)

- **SYSTEM image:** replaced by 0.3.1 for parts A-G, restored to 3.2.174 from card B before part H.
- **Flash settings and sounds:** the bring-up image writes no flash. Part C sends only `9F`, `05` and `15`.
- **Stock settings in part H** (saved by the stock app at power-off, so put each back before switching off):
  SYSTEM > SPEAKER MUTE; REC SRC source, gain (LOW / NORMAL / HI) and PAD; input monitoring. Not saved, but note and
  restore: the VOL, INPUT L/R gain and mic gain knobs. Write every starting value in the results before part H.
- **SD card:** nothing written by the images. For I3 the operator copies one short WAV to `/SMPLTREK/POOL/AUDIO/`.
- **Stock project in I3:** OK on the filename may load the sample into the current project. Use a scratch project;
  note the current project first and switch back before powering off.

## Image 0.3.1 (built 2026-11-16, not published)

0.3.0 unchanged (status page, D3 tone keys STEP 1-4, the LED sweep on VALUE and D, REC for the pattern page), plus
one new page, **DIAG**, toggled by **MIXER**. DIAG has a main view (items 1-5, CHAT a mode of it) and four
more views, each run by its own key (STOP returns): LOW (item 6, PLAY), MIS (item 7, EDIT), USB (item 8, PROJECT)
and EMIF (item 9, CLR twice); nothing on it writes flash.

1. **CACHE** (part B). The image never writes L2CFG, L1PCFG, L1DCFG or any MAR (crt0.s and cache.c do only block
   operations), so the registers still hold what the bootloader left. Show L2CFG, L1PCFG and L1DCFG (`0x01840000`,
   `0x01840020`, `0x01840040`) in hex, MAR17 and MAR128 PC bits, and MAR192-199 PC bits as an 8-character string
   (`0x01848300` + 4n, bit 0). Read once in `main` before any other set-up and keep the values.
   Expected (HW-52): `0 4 3`, `1 1`, `11110001`.
2. **FLASH** (part C). On SPI0 with the stock's set-up, per device (chip select 0 and 1): `9F` + 3 bytes, `05` + 1,
   `15` + 1. Built so those three opcodes are the only ones the code can send (a table of allowed opcodes checked
   before every transfer; anything else is refused and shown as `REF`). Run once, when DIAG is first opened.
   Device 1 is chip select 1 (CSNR `FD`; inference from SPIPC0 enabling SCS0 and SCS1). A device that never completes
   a byte shows `NO ANSWER`. Expected: manufacturer `C2` (Macronix, inference), capacity `18` per 128 Mbit device, and on device 0 status
   bits 2-3 and configuration bit 3 set (BP = 0011, TB = 1).
3. **PADR** (part D). The UART1 receive path timestamps every `Bn` message with the TSC. Shown, updated once a
   second: all `Bn` messages in the last second; the channel with the highest reading, its message count in the last
   second, and its shortest and longest gap between two of its messages (in µs) over the last second (both messages
   inside that second). Built: the timestamp is taken where the main loop parses the message; UART1 is also read every
   128 SPI1 bytes and before each text string, so a timestamp is late by at most about 120 µs. `OE` counts receive
   FIFO overruns since start: bytes lost, which make the counts low; any rise in OE during a D step invalidates it.
4. **CHAT** (part E), a mode entered with **FUNC** on DIAG. Encoder B selects the key under test (bit 0-47, shown
   by bit and name) before entering. In this mode the normal scan and key handling stop (so STEP 1-4 do not change the
   tone); the image keeps that key's row selected and samples its column every 10 µs. Turning encoder A leaves the
   mode (encoders are read outside the matrix). On each change it records, until the line has been steady
   for 20 ms: the number of edges and the time from the first to the last edge. Shown: the last press (edges, µs),
   the last release (edges, µs), and the largest settle time seen since the mode was entered. Built: `GL` counts
   changes that bounced back to the old level (a glitch, neither press nor release); the page is redrawn only while
   the line is settled (a frame takes about 7 ms, during which nothing is sampled); the power key also leaves.
5. **PIN** (part G), on DIAG outside CHAT. Encoder C selects one of GP4[10], GP4[12], GP4[13], GP4[14], GP4[15],
   GP1[2], GP7[15]; **OK** toggles it; its level is shown. **GP3[8]** (input) is shown live. When GP4[10] returns
   high, the image re-runs the codec writes (so a codec reset is recovered without a restart) and shows the
   audio_init result again. Built: the PIN line shows the driven level (`O`) and the pin's read level (`I`); after
   GP4[10] goes high the 40 codec writes run again and the DAC volume is restored (43/44 = 0); the failed writes show
   on the status page's AUD line. McASP0 is not restarted: the codec is its clock master, and whether the ring resumes
   shows as the AUD line's transmit block count rising again (inference that it does).

6. **LOW** (part I), run only when **PLAY** is pressed on DIAG, never automatically. With interrupts disabled, the
   image reads these 32-bit words with plain CPU loads, twice each, and shows the values: `0x00000000`, `0x4`,
   `0x8`, `0xC`, `0x10`, `0x14` (the stock's null path reads `0xC`, then `0x14` if `0xC` is non-zero), and
   `0x00400000` (deeper in the same reserved range). Control: the first word of the DSP L2 ROM at `0x00700000`
   (exists; value not known, expected non-zero). Around the reads it also shows: INTC EVTFLAG0-3
   (`0x01800000`-`0x0180000C`) before and after (which event flags the reads set, if any), and the CPU's EFR and
   IERR (read with MVC; the image never sets TSR.GEE, so an internal exception is recorded there but cannot trap).
   Nothing is written to low memory. Why it is a plain load: the stock's getter `0xC1616698` is `ldw *+a3(4)`
   with A3 = 8 (from the wrapper `0xC1606EE4`, null + 8); if that word is 0 it returns 0, otherwise it returns
   the word at `0x14`. Built: the loads are `load_word` in `crt0.s` (one `ldw`, so the compiler cannot drop a load
   from address 0); interrupts are off throughout (GIE is cleared at entry and never set); EFR is read before and
   after the loads, IERR after.

Items 7-9 were added on 2026-11-16 at the emulator's request (`src/diag_mem.c`). Each access is one hand-written
instruction in `crt0.s` (`load_half` LDH, `load_byte` LDBU, `load_dword` LDDW, `store_word` STW), so the width and
the address reach the bus as written.

7. **MIS** (part I4), on **EDIT**. A 16-byte buffer in ordinary RAM (8-byte aligned) is filled with `10 11 .. 1F`;
   then one LDDW at buffer+4, one LDW at buffer+2 and one STW of `AABBCCDD` at buffer+2, with EFR and IERR before
   and after. Why: CyDrums does a misaligned LDDW while loading its card data (`0xC2503AA4`, address `0xC3C8345C`);
   the CPU reference says only that addresses "must be aligned". The values show whether the CPU ignores the low
   address bits (then LDDW gives `13121110 17161514`, LDW `13121110`, and the store changes bytes 0-3 to
   `DD CC BB AA`; inference) or does something else. Then the narrow low reads, twice each, with EFR before and after and
   IERR after: LDH at `0x0` (CyDrums `0xC25D16B4`), LDH at `0x10` (Lofi-12 XT with a card, `0xC2C4AC88`), LDBU at
   `0x0` (SmplTrek 1.0.65, `0xC1738CB8`). These settle whether another width returns the same as the LOW word reads.
   Nothing is written outside the buffer.
8. **USB** (part I5), on **PROJECT**. USB0 is brought up as the stock's `usb_dcd_init` (04-hardware-access.md "USB
   device"): CFGCHIP2 = `0x0972`, PSC1 module 1, CTRLR reset, PHY on, a wait (10 ms bound) for USB0PHYCLKGD. No
   SOFTCONN (nothing attaches to a host) and no USB interrupts. Then LDW `0x01E0080C` and `0x01E0084C` (the vendor
   driver's USBIntStatusControl reads: the emulator's `--usb-reserved-status-zero` assumption), STW 0 to
   `0x01E00808` and `0x01E00848` (USBIntDisableControl, which CyDrums calls) and LDW of both back, with EVTFLAG0-3,
   EFR and IERR before and after. `NO PSC` or `NO CLK` means USB0's registers were not touched.
9. **EMIF** (part I6), on **CLR**. CyDrums's three STW of 0 at `0x4630314E`, `+4`, `+8`. Its pointer is misaligned
   and reads as ASCII "N10F" (from a C++ type name); `0x4630314C` is that address rounded down to a word, which is
   one thing item 7 shows whether the CPU does. The address is in EMIFA's chip-select-0 window (`0x40000000`-
   `0x5FFFFFFF`), which nothing on this unit sets up (the boot image does not call the ROM's EMIFA set-up), so the
   store can stall the bus until power is removed; it cannot touch flash. The operator approved it as the last step of
   the session. The first CLR only shows the view (`ARMED`); CLR again makes the three stores (`STORED`), with
   EVTFLAG0-3 and EFR before and after and IERR after; CLR again reads `0x4630314C`, `+4`, `+8` back (`READ`).
   Emulator finding (2026-11-16, study copy, an inference): CyDrums makes this store, after the two USB0 stores of
   item 8 in the same routine, only in its BLANK MEDIA state (a card without `/CyDrums`; about 3 s after start), and
   before it draws the "BLANK MEDIA!" page, the documented first-use screen on real CyDrums units; so the store is
   probably survivable. It also means session C5's CyDrums cross-flash with a card lacking `/CyDrums` would make
   these stores whether or not this step runs.

**Reading the page** (21 characters a line; labels dim, values bright):

| Line | Main view | Meaning |
|---|---|---|
| 1 | `DIAG` seconds | the seconds counter: if it stops, the page froze |
| 2-4 | `L2CFG` x, `M17` b; `P` x `D` x; `M192` 8 bits, `M128` b | L2CFG; MAR17 PC; L1PCFG, L1DCFG; MAR192-199 PC (left = 192); MAR128 PC |
| 5-6 | `F0` / `F1`: three ID bytes, `S` status, `C` configuration | device 0 / 1; `-` before DIAG first opens, `REF` refused |
| 7 | `PADR` total, `OE` n | `Bn` messages in the last second; FIFO overruns since start |
| 8 | `C` channel, count, shortest, longest | the busiest pad channel (hex), its messages, its gaps in µs |
| 9 | `PIN` name, `O` driven, `I` read, `J` GP3[8] | encoder C selects, OK toggles |
| 10 | `KEY` bit name (`CHAT` when in the mode) | encoder B selects, FUNC enters, encoder A leaves |
| 11-13 | `PRS` edges µs; `REL` edges µs; `MAX` µs, `GL` n | last press, last release, largest settle time, glitches |
| 14 | `FN CHAT OK PIN PL LOW` | the keys |

The LOW view, 8-pixel lines: `LOW` run count and seconds; eight lines `00`, `04`, `08`, `0C`, `10`, `14`, `4M`
(`0x00400000`), `7M` (`0x00700000`) with the first and second read (the second dim if it differs); `E0`-`E3`
EVTFLAG0-3 before and after; `EF` EFR before and after; `IE` IERR after; footer `PLAY AGAIN  STOP BACK`.

The MIS view: `MIS` run count; `D4` LDDW lower word, upper word; `W2` LDW; `S0` and `S8` the buffer's 16 bytes after
the store (changed bytes bright, unchanged dim); `EF`, `IE` before and after; `H00`, `H10`, `B00` the narrow reads,
first and second (LDH is sign-extended); `EF` before and after, `IE` after. The USB view: `USB` run count and `OK` /
`NO PSC` / `NO CLK`; `CFG2` CFGCHIP2 after; `80C`, `84C` the reads, `808`, `848` the read-backs after the stores;
`E0`-`E3`, `EF` before and after, `IE` after. The EMIF view: state; `R0`-`R2` the read-backs (after the third CLR);
`E0`-`E3`, `EF` before and after, `IE` after. In every view a second value that differs from the first is dim.

Tests in the image's test suite (classes `Diag`, `DiagPage`): the cache registers read before the first PSC write
and never written; the opcode table refusing `06`, `02`, `20`, `52`, `D8`, `C7`, `01`, `03`, `00` and a third device
with no register touched; the flash IDs with the stock's SPI0 set-up (chip selects, CSHOLD on all but the last
byte, `00` dummies); MIXER opening DIAG and reading them once; the pad counts and gaps in one window; CHAT on a
scripted column (a bouncing press, a clean release, a glitch); the LOW reads with nothing written low; the PIN toggle
and the codec rewrite; MIS writing only its buffer, and the four helpers each one instruction; USB brought up as
the stock then exactly the four reserved accesses (and none if the PHY clock never comes); EMIF storing once, then
only reading; the first CLR on the page only arming it. Not simulated: what the real reserved addresses, flash
parts, pads and keys answer, nor what the CPU does with a misaligned address (the simulator splits it into bytes).

## Files on the cards

| Card | File (as SmplTrek.bin) | SHA-256 | What it is |
| --- | --- | --- | --- |
| A | experiments/D3_audio_0.3.1.bin | `6479376788a7bf96c6d68ddcbb0c51b43c5354508eb93afaf06bea050613f7e6` | bring-up image for parts A-G, I1-I2 and I4-I6 |
| B | official SmplTrek 3.2.174 update | (as on the recovery card) | restore, then part H |

## Equipment and levels

Headphones; a powered speaker or interface on STEREO LINE OUTPUTS (level low); a phone as a line source into INPUT
L/R; a timer or phone stopwatch. **VOL knob at minimum before every power-on.**

## Steps

| # | Action | Expected outcome | If different |
| --- | --- | --- | --- |
| A1 | Install 0.3.1 from card A (HOME + power, BOOT MODE, SYSTEM UPDATE), then run **D3-audio.md steps 2 onward** as written, with 0.3.1 in place of 0.3.0 | as D3-audio.md (0.3.1 only adds a page) | D3-audio.md's own "if different" column. If the audio path does not start, skip part G and continue with B-F |
| B1 | Status page: MIXER. Photograph the CACHE line | `0 4 3`, `1 1`, `11110001` | record every value as seen. Any difference corrects HW-52; do not re-run to "fix" it |
| C1 | Photograph the FLASH line (both devices) | `C2 ..` for each device; no `REF` | `REF` shown: stop part C (the image tried an opcode outside the table), continue with D |
| D1 | No pad touched for 5 s. Record PADR's total per second | the MCU's idle rate (unknown; 0 means it sends only on change) | record |
| D2 | Hold TRK 1 lightly and steadily for 5 s; record total, channel count, shortest and longest gap | a steady per-channel rate | record; widely varying gaps are a finding |
| D3 | Same with TRK 1 pressed hard, then with two pads held (TRK 1 and TRK 8) | per-channel rate unchanged by the second pad if the MCU sends every channel in turn | record |
| D4 | Tap TRK 1 quickly ten times | count rises with each tap | record |
| E1 | Encoder B to bit 32 (STEP 1), FUNC (CHAT). Press STEP 1 20 times, half quick taps and half slow presses. Note the largest settle time | settle well under 6 ms (one stock scan of the key's row) | record the largest; above 6 ms means a two-sample release filter at 6 ms spacing is not enough |
| E2 | Encoder A (leave CHAT), repeat E1 for STEP 16 (bit 47), PLAY, HOME and OK (bits from 04-hardware-access.md "Key matrix") | as E1 | as E1. Note any key whose press also shows multiple edges |
| F1 | DIAG off (MIXER). Run **L1-led-map.md steps 2-5** as written (VALUE and D, its address table) | as L1-led-map.md | L1's own column; fill in its "Seen" column |
| G1 | Tone on both channels (STEP 3), VOL low, headphones and line out connected. DIAG on, PIN on GP4[13]. OK twice (low, then high again); listen | GP4[13] has no known role ("fixed high"): record what changes | record; if the tone stops and does not come back after the second OK, power off and restart |
| G2 | PIN GP4[12], then GP4[14], then GP4[15]: OK (low), listen, OK (high) | each cuts some output (they are the analogue power enables, inference) | record which outputs each one cuts |
| G3 | PIN GP4[10]: OK (low), listen, OK (high), check the AUD line | tone stops while low, comes back after the codec writes (codec reset, inference) | record; AUD result non-zero after high: the codec did not come back; restart |
| G4 | Tone off. Phone into INPUT L. PIN GP7[15]: OK, watch the IN line's even-word peak, OK again | about +10 dB on INPUT L when set (the +10 dB stage, inference) | record the two peaks |
| G5 | PIN GP1[2]: OK, speak near the built-in mic, watch IN, OK again | the mic appears on IN in one state (mic switch, inference) | record |
| G6 | Watch GP3[8] while plugging and unplugging headphones, then a cable in INPUT L | changes with one of the two jacks | record which, and the level with and without the plug |
| I1 | Status page check that every part above is recorded. Then DIAG on, PLAY once. Photograph the LOW view | the page updates; each address shows a value, the two reads agree; `0x00700000` non-zero | **page freezes** (no seconds counter): the read did not complete. That is the finding; recover by removing power (batteries and adapter), then HOME + power, restore from card B, and skip I2 |
| I2 | PLAY again; photograph | the same values as I1 | different values: reserved reads are not stable; record both |
| I4 | EDIT; photograph the MIS view. EDIT again; photograph | EFR and IERR unchanged; the values show what the CPU did with each misaligned address (see item 7); the narrow reads agree with I1's words at `0x0` and `0x10` | page freezes: as I1 |
| I5 | STOP, PROJECT; photograph the USB view. PROJECT again; photograph | `OK`; values recorded; EFR and IERR unchanged | `NO PSC` / `NO CLK`: record, USB0 untouched; page freezes: as I1 |
| G7 | Power off by holding the power key | the image's power-off order | record |
| I6 | Last: power on again (0.3.1 still installed, no card needed). MIXER, CLR (view shows `ARMED`), CLR again; photograph. CLR again; photograph | `STORED`, the seconds counter still running; EFR and IERR recorded; the read-backs recorded | **page freezes**: the store stalled the bus. That is the finding; remove power (batteries and adapter), then go on to H0 |
| H0 | Restore: card B, BOOT MODE, SYSTEM UPDATE, 3.2.174. Start the stock app, check SYSTEM INFO | stock firmware | follow the recovery card procedure |
| H1 | Write down every setting and knob listed under "Settings likely to change" | | |
| H2 | **D3-audio-pins-plan.md steps 1-7** as written | as that plan | that plan's own column |
| I3 | Stock firmware, a scratch project (note the current project first), a short WAV in `/SMPLTREK/POOL/AUDIO/` on the card. From a fresh power-on with nothing playing: FUNC+PROJECT, SAMPLE, Pool, AUDIO, select the WAV, press **OK on the filename** (not in the preview column) | if I1 read 0 at `0xC`: the getter returns 0 and the unit carries on (what the screen then shows is the observation) | hang, reset or garbled screen: record it with video; if hung, remove power and restart. Either way switch back to the noted project before powering off |

What this cannot distinguish:
- B: the cache registers as 0.3.1 sees them, which is the bootloader's state only because 0.3.1 never writes them.
  Nothing in the image can tell whether the bootloader changed them after its start-up (HW-52 found no code that does).
- D: the MCU's sending pattern as received. A message the UART drops would look like a longer gap; the status page's
  dropped count (MSG line, third number) must stay 0 for the gaps to count.
- E: chatter at 10 µs sampling. Bounce shorter than 10 µs is invisible, and the 20 ms window caps the settle time
  it can report.
- G: which output a pin cuts, by ear. It does not show the electrical path (a schematic or probes would).
- I1-I2: what the CPU sees at those addresses from 0.3.1's code, with the image's cache state. A non-zero value could
  come from the cache or the bus; `0x0`-`0x0FFFFFFF` is never cacheable (MAR0-15 are fixed at 0, SPRUFK5A),
  so the stock's read sees the same thing (inference). It cannot tell whether a different access width (byte, DMA)
  would return the same: I4 tests LDH and LDBU (DMA still not). Stores to low memory (the six USB set-up stores the
  emulator discards) are not tested: that needs a separate decision.
- I4: the CPU's handling of a misaligned address for LDDW, LDW and STW in cached RAM; not whether uncached or
  peripheral addresses behave the same.
- I5-I6: one run each, from 0.3.1's state (USB0 never attached, EMIFA never set up). A frozen page in I6 cannot tell
  a bus stall from an exception that stopped the CPU.
- I3: only the stock's visible behaviour on that path, not the value it read.
- F and H: as their own plans say.

## Stop rules

- No flash writes except BOOT MODE's SYSTEM UPDATE (twice: 0.3.1 in, 3.2.174 back). Any `REF` on the FLASH line ends
  part C at once.
- Any unexpectedly loud output, a pop that repeats, or a smell: VOL down, unplug outputs, power off by holding the key.
- Unit does not reach the status page within 10 s: hold the power key, then HOME + power and restore from card B.
- Do not open any card function in the stock app during part H. I3 opens only the SAMPLE pool browser.

## Evidence capture

Photo of the status page and the DIAG page at A1, B1, C1, each D step, the end of each E step, I1, I2, I4, I5 and I6; video for I3; short video for
G1-G6 (sound on). Stills of each. L1's table and D3-audio-pins' results go in their own files.

## Results (filled in during/after)

Session 2026-11-16 (evening, US time; page timestamps 02:40-03:30 UTC 2026-11-17), **core scope** only: P1-P5, A1-A9,
B1, C1, D1, D2, E1, I1, I2, I4, I5, G7, I6, H0, X1, X2. Not run: D3, D4, E2, F (L1), G1-G6, H1-H2, I3. Step ticks and
notes from the bench page; values read from the photos. Image 0.3.1 as installed: SHA-256
`6479376788a7bf96c6d68ddcbb0c51b43c5354508eb93afaf06bea050613f7e6`, rebuilt from source with the same hash.

| # | Observed | Matches expectation? | Evidence |
| --- | --- | --- | --- |
| A | A1-A6 and A8 as D3-audio.md; the splash stages pass very quickly. IN fluctuates around `0002` with nothing connected; AUD block count running (`5780` at the A3 photo). A7 and A9 skipped: no speaker, audio interface or line source on the bench (P4 noted the same). A4-A6 on headphones: STEP 1 left ear only, STEP 2 right only, STEP 3 both (operator, confirmed 2026-11-17; the bench page had them ticked without notes) | yes, for the steps run; even words = left on the headphones (HW-61) | M1_P5, M1_A3, M1_A4 |
| B1 | L2CFG `01010000`, M17 `1`, L1PCFG `00000004`, L1DCFG `00000003`, M192-199 `11110001`, M128 `1` | yes. L2MODE (bits 2:0) is 0 as HW-52 expects; the two set bits are bit 16 and bit 24, which SPRUFK5 gives as the read-only MMID and NUM_MM fields (inference: identity, not configuration). HW-52 stands | M1_B1, M1_D1 |
| C1 | F0 `C2 20 18`, status `0C`, configuration `0F`; F1 `C2 20 18`, status `00`, configuration `07`. No `REF` | yes. Both devices answer with the same ID. Device 0's status has bits 2 and 3 set (block-protect bits on Macronix parts, inference); device 1 has none | M1_B1 |
| D1 | No pad touched: PADR 4192-4196 messages per second; busiest channel `1` at 262 per second, gaps 3688-3962 µs; OE `4` (unchanged through D1 and D2) | the idle rate is not 0: the MCU sends continuously. 4192 / 262 = 16, so each of 16 channels about every 3.8 ms (inference) | M1_D1 |
| D2 | TRK 1 held: PADR 4192, channel `1` 262 per second, gaps 3692-3972 µs, OE `4` | steady per-channel rate, the same as idle: holding a pad does not change how often the MCU sends | M1_D2 |
| D3 | not run (core) | | |
| D4 | not run (core) | | |
| E1 | STEP 1 (bit 32), 20 presses: last press 1 edge / 0 µs, last release 7 edges / 175 µs, largest settle **784 µs**, GL `0` | yes, well under 6 ms. Releases bounce more than presses | M1_E1 |
| E2 | not run (core) | | |
| F | not run (core) | | |
| G1 | not run (core) | | |
| G2 | not run (core) | | |
| G3 | not run (core) | | |
| G4 | not run (core) | | |
| G5 | not run (core) | | |
| G6 | not run (core) | | |
| G7 | power-off by holding the power key: normal | yes | (page tick) |
| H | H0 only: card B, SYSTEM UPDATE, stock app. SYSTEM INFO BOOT 1.0.17, PRESET 2.0.22, SYSTEM 3.2.174, MCU 1.0.6 | yes | M1_H0, M1_X1 |
| I1 | LOW run 1: `00`→`00000000`, `04`→`00000004`, `08`→`00000008`, `0C`→`0000000C`, `10`→`00000010`, `14`→`00000014`, `4M`→`00400000`, `7M`→`00000412`; both reads equal. EVTFLAG0-3 `0000011B 21000010 00000000 94000001` before and after; EFR `0` before and after; IERR `0` | no freeze, no exception, no event flag. But the reserved words read back **as their own address**; only the L2 ROM control (`0x00700000`, real memory) gives a different value. See "Reading I1, I4 and I6" below | M1_I1 |
| I2 | LOW runs 2 and 3: identical to run 1 | yes: stable | M1_i2, M1_I2-2 |
| I3 | not run (core) | | |
| I4 | MIS runs 1-3, identical: D4 (LDDW buffer+4) `13121110 17161514`; W2 (LDW buffer+2) `13121110`; buffer after STW at +2: `DD CC BB AA 14 15 16 17 / 18 .. 1F`. EFR and IERR `0` before and after. Narrow reads: H00 `00001918` twice, H10 `00001918` twice, B00 `00000018` twice; EFR `0`, IERR `0` | misaligned part: yes, exactly the "CPU ignores the low address bits" values: LDDW rounds down to 8, LDW and STW round down to 4, no exception. Narrow reads: **do not** agree with I1's words at `0x0` and `0x10` (`0`, `0x10`); see below | M1_I4, M1_I4-2, M1_I4-3 |
| I5 | USB runs 1-3, identical: `OK`, CFGCHIP2 `00020972` (USB0PHYCLKGD set); `80C` `0`, `84C` `0`, `808` `0`, `848` `0` after the stores; EVTFLAG0-3 unchanged (same four values as I1); EFR `0` before and after; IERR `0` | yes: PHY clock comes up as in the stock; the reserved status words read 0, the stores to the reserved disable words are harmless and read back 0 | M1_I5, M1_I5-2, M1_I5-3 |
| I6 | After a power cycle: `ARMED`, CLR: `STORED` with the page still running (no freeze); EVTFLAG0-3 unchanged, EFR `0` before and after, IERR `0`. CLR: `READ` R0 `00000001`, R1 `00000004`, R2 `00000001`. CLR twice more: R0 `00000002`, R1 `00000004`, R2 `00000002` both times | **the store did not stall the bus**: no freeze, no exception, no event flag. The read-backs are not the stored 0; see below | M1_I6, M1_I6-2, M1_I6-3, M1_I6-4 |

**Reading I1, I4 and I6** (inference from the values and the image's disassembly, `d1.dis` of the build above).
Each low read returns data the CPU had just loaded from elsewhere, not memory at that address:
- I1: in `diag_low_run` each `load_word` call is issued with `ldw *++a11(4),a4` in its delay slots, loading that read's
  address from the `low_addr` table. Every reserved word came back equal to that table entry. The L2 ROM word did not.
- I4: the last loads before the narrow reads are the four `ldw` that copy the 16-byte buffer to `mis_after`; the last
  of them is at buffer+12 and fetches the doubleword `1F1E1D1C 1B1A1918`. LDH at `0x0` and at `0x10` gave `1918`
  (bytes 0-1 of that doubleword), LDBU at `0x0` gave `18` (byte 0).
- One rule fits both: a read of the unmapped low range returns the CPU's last 64-bit load data, with the byte lanes
  picked by the read address's bits 2:0. In I1 each table entry sits at an address with the same bit 2 as the
  address it holds (`low_addr` at `0xC20009F8`), so the lanes always gave back the entry.
- I6 fits only in part: R0 and R2 (addresses `...4C` and `...54`, lanes 4-7) equal `emif_state` (`1`, then `2`),
  the last value loaded before the reads (at `0xC20127B4`, lanes 4-7). R1 (`...50`, lanes 0-3) reads `4` both times,
  which the rule does not explain (it predicts `emif_val[2]`, 0 on the first read).
- Consequence for the stock's null path: the getter reads `0xC` after whatever load came before it, so on hardware
  it is not a fixed 0, and the `0x14` read that follows a non-zero result is not either. Not tested with DMA, and
  not tested for stores to low memory.

Settings restored (list with values): H1 not run (core). Only the stock install was restored; no settings were
changed in this session except by the two system updates.
Device state at end: BOOT 1.0.17  PRESET 2.0.22  SYSTEM 3.2.174  MCU 1.0.6
Claims updated (2026-11-17): HW-52 upgraded to observed-device for the register values; new HW-54 (flash ID and
protection), HW-55 (pad MCU rate), HW-56 (key bounce), HW-57 (misaligned accesses), HW-58 (low reads), HW-59 (USB0
reserved words), HW-60 (EMIFA store); notes added to HW-46 (its 85 per second undercounts) and HW-51.
