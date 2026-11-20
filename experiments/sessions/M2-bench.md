# Session M2: the emulator's second set of bench questions (planned and run 2026-11-18)

> **Run 2026-11-18 with image 0.3.2:** parts R, M, L, N, P, W and X; no view froze. Not done: P2 (no batteries), P3 (trigger fault, fixed in 0.3.3, carried to M3), part S (stock), so 0.3.2 stayed installed.
>
> **Results:** "Results" at the end of this file; registry HW-62 to HW-68; summary in `experiments/README.md`.

**Purpose.** Measure, on the unit, the CPU and panel behaviours the emulator now models from inference or from the
manual alone. The questions, their numbering and every predicted value come from a specification written from
the emulator (not published). The predictions are the emulator's output on 2026-11-18, not expectations about the unit: a row that differs
changes the emulator, and the photograph is the evidence.

| Part | Questions | What it settles |
|---|---|---|
| L (LOW2, L8) | 1-5 | what a read of reserved low memory returns: the "previous 64-bit load, lanes by address bits 2:0" rule inferred from M1 I1/I4 (HW-58), and whether an EMIFA read follows it |
| W (LOWW) | 8 | whether stores to reserved low memory complete harmlessly (assumed by every stock check, never measured) |
| M (MIS2) | 9, 10 | LDH, LDHU, STH and STDW at misaligned addresses, in DDR and in L2 RAM (M1 measured LDDW, LDW and STW only, HW-57) |
| X (EMIF2) | 11 | stores at both ends of EMIFA CS0 (M1 measured three words at `0x4630314C`, HW-60) |
| N (NOP, IDLE) | 20 | whether an interrupt is taken inside a multicycle NOP (SPRUFE8B 5.5.4; the emulator changed to this on 2026-11-18), and where IDLE returns |
| R (RCP) | 19 | the unit's RCPSP / RSQRSP / RCPDP / RSQRDP tables (the manual gives only the accuracy) |
| P (PADR) | 12-17 | the panel MCU stream: channel order, idle levels, byte timing, other traffic, start-up bytes, a pad's rise and fall, rates with pads held (M1 D3) |
| S (stock) | 7 | M1 I3: OK on a SAMPLE POOL file name, and INST on a track, on stock 3.2.174 |

Parts L-P run on one image, **0.3.2**. Part S runs on the stock firmware after the restore.

**Status: run 2026-11-18 (evening, US time; photos 23:14-23:29 local), parts R, M, L, N, P, W and X on image 0.3.2
(`experiments/D3_audio_0.3.2.bin`, SHA-256 below, rebuilt from source with the same hash; not published). Not done: P2 (no batteries;
the unit ran on its AC adapter), P3 (P6 could not be armed: see "Results"), part S (stock). No view froze.** Simulated in
the image's test suite, classes `Diag2` and `DiagPage`.

Device state at start: BOOT 1.0.17, PRESET 2.0.22, SYSTEM 3.2.174, MCU 1.0.6 (as at the end of M1; check SYSTEM INFO)
Known deviations from stock: none
Recovery card prepared: card B, official SmplTrek 3.2.174 update as `SmplTrek.bin` (SHA-256 checked on the card)
Second card: card A carries the diagnostic image.

## Settings likely to change (named before starting)

- **SYSTEM image:** replaced by 0.3.2 for parts L-P, restored to 3.2.174 from card B before part S.
- **Flash and card:** the diagnostic image writes neither (as 0.3.1). Its SPI0 driver can send only `9F`, `05`, `15`.
- **Part S (stock):** the current project (use a scratch project; note the current one and switch back before
  powering off); one WAV copied to `/SMPLTREK/POOL/AUDIO/`; the preset instruments on the card if they are not there yet.

## Image 0.3.2 (built 2026-11-18, not published)

0.3.1 with its LOW, MIS, USB and EMIF views (M1 part I, done) replaced by the spec's views. The status page, the tone
keys STEP 1-4, the LED sweep, REC's pattern page and the DIAG main view (CACHE, FLASH, PADR, PIN, CHAT) are
unchanged. Two start-up additions: `_start` reads `0x8` twice before anything else (L9), and the start-up listens to
UART1 for 20 ms before sending its first byte to the MCU (P5).

**Keys on the DIAG page** (MIXER on the status page; nothing runs until its key is pressed). Physical places from the
factory button-test drawing (`docs/10-cross-flash-button-map.md`: bits 8/9 under the screen, 16/31 beside the upper
pad row); if SEL> opens L8 rather than RCP, the two under-screen buttons are the other way round:

| Key | View | Runs |
|---|---|---|
| PLAY | LOW2 (3 pages) | L1-L5 and L7, each twice; L9's words from start-up |
| SEL< (left button under the screen) | L8 | LD then a read at `0x4630314C`, twice |
| EDIT | MIS2 (2 pages: DDR, L2) | M1-M4 twice, in DDR and in L2 RAM at `0x0083FF00` (M5) |
| SEL> (right button under the screen) | RCP (221 pages) | the sweep and the special inputs |
| UP (arrow) | NOP | 4,096 timer interrupts on the `nop 9` loop |
| DOWN (arrow) | IDLE | the same on the `idle` loop, then L6 twice |
| OCT> (button right of the upper pad row) | PADR A (2 pages) | one second of UART1 bytes with time stamps; arms P6 |
| OCT< (button left of the upper pad row) | PADR B | re-arms P6 (no capture) |
| PROJECT | LOWW (3 pages) | first press: ARMED only; each further press runs W1-W3 twice |
| CLR | EMIF2 | first press: ARMED only; the second X1; the third X2 |
| RIGHT / LEFT (arrows), encoder A | | next / previous page of the open view |
| STOP | | back to the main view |

Every probe is one hand-written assembly routine with its loads and stores written out in the spec's order (LD =
`LDDW *D` then `NOP 4`; every load followed by `NOP 4`, as in the spec's prediction scripts). `D`, `E` and `M` are
rewritten before every probe. Interrupts are off except inside the NOP, IDLE and L6 probes. Those use TIMER64P1
(TIM12, continuous, from the 24 MHz AUXCLK) with its event, 40 (`T64P1_TINT12`, StarterWare `interrupt.h`), on CPU
interrupt 4 (NOP, IDLE) or 5 (L6), and a 1 KiB interrupt table of the image's own. NOP's period is 6,452 ticks =
100,006 CPU cycles, 12 mod 17, so the requests walk every phase of the 17-cycle loop. Before GIE is ever set the image
checks that the timer's event arrives (10 ms bound); if not it shows `NO TIMER EVENT` and runs nothing. A timer that
raises the event but never interrupts the CPU would still hang the NOP or IDLE loop: that is a finding.

**Reading the views** (8-pixel lines, 21 characters; labels dim, values bright; a second run that differs from the
first is dim; page number `n/N` top right):

- **LOW2** page 1: `D`, `E` the references; `1A` `1B` `1C` `1D` `2` `7A` `7B`: run 1, run 2. Page 2: two lines per
  two-word probe (`3 1` = L3 run 1, `3 2` = run 2; then L4, L5A-C, L7C), first word then second (L7C: lower, upper).
  Page 3: `E0`-`E3` EVTFLAG0-3, `EF` EFR, `IE` IERR, before and after the whole run; `9` L9's two words.
- **L8**: `D`, `E`; `8` run 1, run 2; flags before and after.
- **MIS2**: `M` the 16 bytes as filled; `H1` LDH +1 and `U3` LDHU +3, run 1 and run 2; `S1`/`S2` M after STH +3,
  `W1`/`W2` M after STDW +5, runs 1 and 2 (changed bytes bright); `EF`, `IE` before and after. Page 2: the same in L2.
- **RCP** page 1: per table, letter, name (`SR` RCPSP, `SQ` RSQRSP, `DR` RCPDP, `DQ` RSQRDP; exponent `0`, `+` = +1,
  `-` = -3), differences from the model's table, results with a bit below the eighth mantissa bit, CRC-32. Letters:
  A-D at e = 0, E-H at +1, I-L at -3, each in the order SR, SQ, DR, DQ. Page 2: the first eight differences: letter,
  k, result (doubles: high word, low word). Pages 3-5: the special inputs (`+0 -0 +I -I NA DN -1 MX`): singles
  (RCPSP, RSQRSP), RCPDP (high, low), RSQRDP (high, low). Pages 6-29: the compact table, two pages per letter in
  order A-L (A = pages 6-7, B = 8-9, C = 10-11, D = 12-13): the eight mantissa bits below the leading one per k, ten to a line,
  from the k in the header. Pages 30-221: full words, sixteen per page, letter and k on every line (letter t, 0 for
  A, has pages 30 + 16t to 45 + 16t).
- **NOP**: lines `+IRP  difference  count`, largest count first (IRP as packets after the loop top, difference
  = handler's TSCL - loop's TSCL); `MORE` counts any further pairs.
- **IDLE**: `A1` the loop's passes; `+IRP count`; `L6` run 1, run 2; `D`, `E`.
- **PADR A**: `BT` / `US` battery or USB power; `S` four lines of 16: the low digit of 64 consecutive status bytes (a
  non-`B` byte bright); `L` four lines: each channel's last level (hex, channels 0-15); `N` four lines: messages per
  channel in the second; `CH` shortest and longest gap between characters inside a message, `MS` between consecutive
  messages, in µs with one decimal; bottom line: bytes in the second, overruns. **PADR B**: `OTH` bytes outside `Bn`
  messages and the first eight; `BOOT` bytes received before the first byte sent, `OE` overruns then, the first 16;
  `HIT` channel, count, `ARMED` / `DONE`, then 32 levels (hex) of the first pad channel above 0 after arming.
- **LOWW**: per page one store (`STW 0`, `STH 10`, `STB 200`, value `A5..`): `D`, `E`, `W` the read-back of run 1 and run 2;
  flags before and after.
- **EMIF2**: state and the seconds counter (still counting = no stall); for each store made, its flags before and after.

## Files on the cards

| Card | File (as SmplTrek.bin) | SHA-256 | What it is |
| --- | --- | --- | --- |
| A | experiments/D3_audio_0.3.2.bin | `a09d1d3df11853e8b8ad5e20f8eb2b51dbd3a188b91fb65252f526909632f090` | diagnostic image for parts L-P |
| B | official SmplTrek 3.2.174 update | (as on the recovery card) | restore, then part S |

## Steps (in the spec's order of risk)

Photograph every page named. Expected values: the spec's tables (they are long; take the spec along or compare later).

| # | Action | Expected outcome (emulator) | If different |
| --- | --- | --- | --- |
| P0 | Install 0.3.2 from card A (HOME + power, BOOT MODE, SYSTEM UPDATE: `V3.2.174 -> V0.3.2`). Status page: version `0.3.2`, MCU `01 00 06` | as 0.3.1 | no status page within 10 s: stop rule |
| R1 | MIXER (DIAG). SEL>; photograph pages 1-5 | spec "View RCP": counts 0 and 0, the twelve CRCs, the special results | counts not 0: photograph pages 6-13 (A-D compact); low bits set: photograph the full pages of every table with low bits (letter t: pages 30 + 16t to 45 + 16t) |
| M1 | EDIT; photograph pages 1-2 | spec "View MIS2" M1-M5 | record; a frozen page: stop rule (freeze) |
| L1 | PLAY; photograph pages 1-3. PLAY again; photograph page 1 | spec "View LOW2" L1-L5, L7, L9 | record every row |
| L2 | SEL<; photograph | the emulator stops on this read; the unit read there in M1 I6 | record |
| N1 | UP; photograph. UP again; photograph | spec "View NOP": nine pairs at +2 with differences 11-19 (or the same shape shifted by a constant) | most of the count on one value at +2 means the NOP was waited out; `NO TIMER EVENT`: record, skip N2; freeze: stop rule |
| N2 | DOWN; photograph | IRP +2 for every interrupt, `A1` 4096; L6 `34333231` | record |
| P1 | No pad touched, on external power (the AC adapter; PADR A shows `US`). OCT>; photograph PADR A and B | spec "View PADR": `B0`-`BF` four times, pad levels 0, messages 238.4 µs apart, no other bytes | record |
| P2 | Optional, needs batteries (skip on the AC adapter alone). Unplug the adapter (on batteries). OCT>; photograph PADR A | channel 15 differs between USB and batteries | record both levels |
| P3 | OCT<, then hit TRK 1 once; photograph PADR B | P6: the level straight up and back | record the 32 levels |
| P4 | Hold TRK 1 pressed hard, OCT> while holding (keep holding 2 s); photograph PADR A. Then hold TRK 1 and TRK 8, OCT>; photograph | P7: every channel's count unchanged by the pads (about 262 each) | record; M1 D3 is answered here |
| W1 | PROJECT (`ARMED`); photograph. PROJECT again; photograph pages 1-3 | read-backs `24232221` (not A5); flags unchanged | a freeze or a changed flag is as much a finding as a value; freeze: stop rule |
| X1 | Last. CLR (`ARMED`); CLR again (X1); photograph. CLR again (X2); photograph | nothing changes; the seconds counter keeps counting | **page freezes**: the store stalled the bus; remove power (batteries and adapter) and go on to S0 |
| S0 | Restore: card B, BOOT MODE, SYSTEM UPDATE, 3.2.174. Start the stock app, check SYSTEM INFO | stock firmware | follow the recovery card procedure |
| S1 | Stock 3.2.174, a scratch project (note the current one first), one WAV in `/SMPLTREK/POOL/AUDIO/`, the preset instruments on the card. FUNC+PROJECT, SAMPLE, Pool, AUDIO, select the WAV, **OK on the file name** | the AUDIO LOADER opens (the emulator needs `--reserved-low-reads` for this) | record what the screen shows; video |
| S2 | INST on a track: load the guitar; play pads | the guitar plays | record; switch back to the noted project before powering off |

What this cannot distinguish:
- L: what the CPU returns at those addresses from this image's code and cache state; not DMA reads. L9 sees whatever
  the bootloader loaded last, which this image cannot know.
- W: whether a store that changes nothing visible was dropped or went somewhere unseen.
- M: one buffer in DDR and one in L2 RAM; not uncached or peripheral addresses.
- N: TSC differences include the unit's interrupt recognition delay; the shape decides, not the absolute numbers.
- R: the results at the sweep and special inputs only.
- P: what UART1 receives, time-stamped by a polling loop (sub-microsecond, the loop does nothing else); P5 only
  what arrives in the 20 ms before the first byte sent, after the bootloader has run.
- X: a frozen page cannot tell a bus stall from an exception that stopped the CPU.

## Stop rules

- No flash writes except BOOT MODE's SYSTEM UPDATE (twice: 0.3.2 in, 3.2.174 back).
- **A view freezes** (the seconds counter on the main view, or the view, stops updating): that is the finding.
  Record which view and step, remove power (batteries and adapter), power on (0.3.2 is still installed) and
  continue from the next step.
- Unit does not reach the status page within 10 s: hold the power key, then HOME + power and restore from card B.
- Part S opens only the SAMPLE pool browser and the INST loader; no other card function.

## Evidence capture

Stills of every page named in the steps; video for S1 and S2.

## Deviations from the spec (2026-11-18)

- L8 has its own key (SEL<), because the emulator stops on that read and its rendering of LOW2 would stop with it.
- L6 runs in the IDLE view (DOWN), with the other interrupt probes, rather than in LOW2: a missing interrupt would
  otherwise freeze the first, read-only view of the session.
- LOWW is armed by its first press, as EMIF2 is (the spec does not ask for it).
- EMIF2 makes X1 and X2 on separate presses, so a freeze says which store caused it.
- P5 listens for 20 ms; the spec gives no length.
- The probes are in `probes.s`, not `crt0.s`.
- **For the emulator:** the image routes TIMER64P1's TINT12 as event 40 (StarterWare
  `include/c674x/c6748/interrupt.h`: `SYS_INT_T64P1_TINT12 40`, `T64P0_TINT34 64`, `T64P1_TINT34 48`, `T64P2_TINTALL 25`,
  `T64P3_TINTALL 86`). The emulator's board raises event `4 + 2 x index` for timers 0-1 and `68 + 2 x (index - 2)` for 2-3
  (`emulator/core/board.cpp`), which is right only for TIMER64P0 TINT12 (4). Until that is corrected the emulator
  will show `NO TIMER EVENT` on NOP, IDLE and L6.

## Results (filled in during/after)

Session 2026-11-18, image 0.3.2 as built (SHA-256 `a09d1d3df11853e8b8ad5e20f8eb2b51dbd3a188b91fb65252f526909632f090`).
Values read from the photos. On the AC adapter throughout.
EFR, IERR and EVTFLAG0-3 (`0000011B 21000010 00000000 94000001`, as in M1) were unchanged before and after every probe
in every view.

| # | Observed | Matches expectation? | Evidence |
| --- | --- | --- | --- |
| P0 | installed; status page 0.3.2 | yes | (operator) |
| R1 | Differences per table A-L: 116, 126, 116, 126, 116, 132, 116, 132, 116, 132, 116, 132 (1,476 in all; the page shows 476, the count kept to three digits); results with a bit below the eighth mantissa bit: 0 in every table. CRC-32 A-L: `24BA9252 B37E28CA 9F40B027 E9F42249 F62922BA 62118BB7 1F67AB74 0F916977 7236A471 D4B23279 3C697084 1F9C6A55`. First differences (RCPSP e = 0): k = 09 `3F778000`, 0A `3F768000`, 0B `3F758000`, 0F `3F720000`, 10 `3F710000`, 13 `3F6E8000`, 14 `3F6D8000`, 17 `3F6B0000`. Specials, single (RCPSP, RSQRSP): +0 `7F800000 7F800000`, -0 `FF800000 FF800000`, +inf `0 0`, -inf `80000000 7FFFFFFF`, NaN `7FFFFFFF 7FFFFFFF`, denormal `7F800000 7F800000`, -1 `BF800000 7FFFFFFF`, max `00000000 1F800000`. RCPDP (high low): `7FF00000 0`, `FFF00000 0`, `0 0`, `80000000 0`, `7FFFFFFF FFFFFFFF`, `7FF00000 0`, `BFF00000 0`, `0 0`. RSQRDP: `7FF00000 0`, `FFF00000 0`, `0 0`, `7FFFFFFF FFFFFFFF`, `7FFFFFFF FFFFFFFF`, `7FF00000 0`, `7FFFFFFF FFFFFFFF`, `1FF00000 0` | **no** for the sweep: the unit **rounds to nearest** where the model truncates. The exact values rounded to nearest at eight mantissa bits (no sweep input falls on a tie) reproduce all twelve unit CRCs and all twelve difference counts, so the compact pages were not needed. Specials: yes for the single forms (as the spec's table) | M2_R1-p1(b) to p5 |
| M1 | DDR and L2 identical: `H1` `00001110` twice, `U3` `00001312` twice; after STH BEEF at +3: `10 11 EF BE 14 .. 1F`; after STDW at +5: `A0 A1 A2 A3 A4 A5 A6 A7 18 .. 1F`; both runs alike | yes: every misaligned width rounds down to its size, in DDR and in L2 RAM | M2_M1-p1, p2 |
| L1 | Page 1, both runs and both presses: `1A` `24232221`, `1B` `28272625`, `1C` `00002423`, `1D` `00000026`, `2` `24232221`, `7A` `25242322`, `7B` `21282726`. Page 2 (first word, second word; both runs alike): L3 `0000011B 0000011B`; L4 `24232221 28272625`; L5a `00000022 24232221`; L5b `00000022 C20004E4`; L5c `28272625 C2002204`; L7c `27262524 23222128`. Page 3: `9` (L9) `00000000 00000000` | L1a-d, L4, L5a, L7a-c, L9: yes. **L2 no** (`24232221`, not `AABBCCDD`: the data is held from the load, not read from RAM). **L3 no** (the EVTFLAG0 load replaced it). **L5b, L5c no**: see "Reading the results" | M2_L1-p1 to p3, M2_L1-run2-p1 |
| L2 | `8` `28272625` twice (LDW at `0x4630314C` after LD) | the emulator stops here; on the unit the EMIFA read returns the held data, lanes 4-7 (address bit 2 = 1), like a low read | M2_L2 |
| N1 | Run 1 (IRP offset, difference, count): `+0 32 1365`, `+1 16 1364`, `+2 20 682`, `+2 25 682`, then `+2 180 1`, `+2 19 1`, `+2 24 1`. Run 2: the same four main rows (`1366` / `1364` / `682` / `682`, read from a soft photo) and `+2 18 1` | **partly**. Interrupts are taken at two points around the NOP (differences 20 and 25, both returning to +2), not only at its end, so a multicycle NOP is not simply waited out. But the requests did not spread over 17 phases: four classes in proportions 2:2:1:1, which 17 equally likely phases cannot give. Not resolved: see "Reading the results" | M2_N1-run1, run2 |
| N2 | `A1` 4096; IRP `+2` for all 4096; L6 `24232221` twice | IDLE: yes. **L6 no**: the handler's `LDDW *E` (on .D2T2) did not replace the held data (`34333231` predicted) | M2_N2 |
| P1 | Status low digits, repeating: `0 4 3 7 B D A E F 2 1 5 9 6 8 C` (all `B`); levels (ch 0-15) `0001 0000 0000 0001 / 0000 0000 0000 0000 / 0001 0000 0003 0000 / 0000 0000 0000 0000`; 262 messages per channel; gap between characters in a message 21.4-21.9 µs; between consecutive messages 64.9-1455.7 µs; 12,576 bytes in the second, 0 overruns. PADR B: 0 bytes outside `Bn` messages; `BOOT 0`, `OE 0` | **no** for the order (not `B0`-`BF`) and the spacing (messages come in bursts: 64.9 µs is three character times back to back, with pauses up to 1.46 ms, though the mean stays 238.5 µs = 4192 a second). Yes: 16 channels, 262 a second each, nothing but `Bn` messages, idle levels 0-4. Nothing received in the 20 ms before the first byte sent | M2_P1-A, M2_P3-B |
| P2 | not done: no batteries (AC adapter only). Channel 15 read `0000`, `0004`, `0006` in the three captures | | |
| P3 | **not completed**: OCT< armed P6 and it fired at once every time (operator's note). The photo shows channel 4 captured at idle levels (`0001` and `0000`): P6 triggered on the first level above 0, and idle noise is 1-4 | image fault: the trigger must be above the idle noise. Fixed in 0.3.3 (`experiments/D3_audio_0.3.3.bin`, SHA-256 `89fa94f7a9962b81b680cd08bb8f9fcfcda20391307d5a93bca2f1a0e6817da5`): trigger at 64, eight levels before it kept; for a later P3 | M2_P3-B |
| P4 | TRK 1 held hard: ch 1 `0CF6`, other channels 0-4, 262 a second each. TRK 1 and TRK 8 held: ch 0 `0CAA`, ch 1 `0CFF`, counts 262-263. Same status order, timing as P1 (12,576 and 12,594 bytes) | yes: holding pads does not change the per-channel rate (M1 D3 answered). TRK 1 = channel 1; TRK 8 = channel 0 (from the levels) | M2_P4-onepad, M2_P4-twopads |
| W1 | Runs 2 and 3 (the armed view and run 1 not photographed): W1 (STW at `0x0`), W2 (STH at `0x10`), W3 (STB at `0x200`) each read back `24232221` twice; flags unchanged | yes: stores to reserved low memory complete with no exception or event and store nothing | M2_W1-run2-p1, M2_W1-run3-p1 to p3 |
| X1 | X1 (`0x40000000`) and X2 (`0x5FFFFFFC`): flags unchanged, seconds counter running (359, then 365) | yes: no stall at either end of EMIFA CS0 | M2_X1-x1, x2 |
| S0-S2 | not done in this sitting | | |

**Reading the results** (inference from the values and the disassembly of the build above, not published):
- **What a low read returns.** Every LOW2, L8 and LOWW value fits one rule: the CPU keeps the data of its loads as
  eight byte lanes, and each load replaces only the lanes it reads (LDBU one, LDW four, LDDW eight). Stores leave them
  alone (L2, LOWW), and so do reads of unmapped low memory (L4) and of the EMIFA window. A low or EMIFA read returns the
  lanes its address picks. The driver loop loads each probe's address from the table `low_fn` (`0xC2015510`, on .D1T1)
  just before the call. L5b: the entry before it, `low_l5a` = `C20004E4`, sits at `…534` (bit 2 set) and filled lanes 4-7;
  LDBU D+1 replaced lane 1 only; the read at `0xC` returned `C20004E4`. L5c: lanes 0-3 held `low_l5b` = `C2000504` from
  `…538`, with lane 1 replaced by L5b's `22`, which gives `C2002204` exactly. L3: a load from a peripheral replaces them
  too. M1's I6 middle value (`4`, HW-60) may fit the same partial-lane rule; not checked.
- **L6 does not fit "the last load of any kind".** The handler's LDDW of E left the held data as D. Every load in the
  probes and the driver that does change it uses .D1T1; the handler's uses .D2T2. The held data is per data path
  (side A / side B), not per CPU: M3's SIDE view (2026-11-19) separated the two and showed it.
- **NOP.** Shares of 1/3, 1/3, 1/6, 1/6 mean the requests met the loop at a few phases only. With a 17-cycle loop and a
  period of 100,006 cycles (12 mod 17) every phase should have come up equally. Either the loop does not take 17 cycles
  on the unit (a length divisible by 6 fits, e.g. 12, 24 or 36 cycles), or the interrupt period in CPU cycles is not what
  the image assumes. This data cannot tell them apart; M3's NOP2 view measured both and found period and loop length
  as assumed, with a request-to-handler delay that varies with loop position (`emulator/README.md`).

Settings restored (list with values): none changed (no stock settings touched; part S not run).
Device state at end: not reported. Part S, which starts with the restore, was not run, so 0.3.2 stayed installed; M3 installed 0.3.4 over it the next day.
Claims updated (2026-11-18): HW-55 and HW-58 notes; new HW-62 (held load data by byte lanes), HW-63 (misaligned narrow
and STDW, DDR and L2), HW-64 (EMIFA both ends; EMIFA reads), HW-65 (stores to low memory), HW-66 (RCP rounds to
nearest), HW-67 (interrupts in NOP and IDLE), HW-68 (panel MCU stream order and timing).
