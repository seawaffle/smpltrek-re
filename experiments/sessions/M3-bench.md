# Session M3: the emulator's follow-up probes after M2 (planned and run 2026-11-19)

> **Run 2026-11-19 with image 0.3.4** (photos 16:56-17:05 local): views SIDE (S1-S12), NOP2 (N3, N4), RCP2 (all eight tables) and PADR B (P3). P2 and part K were not reported. End state: stock 3.2.174 restored (operator, 2026-11-20).
>
> **Results** were recorded in the emulator, not in the table at the end of this sheet: `emulator/README.md` (reciprocal estimates; reserved low reads, "Each data path holds its own data"; "A period written to a running timer"; "What the model assumes without stopping"), `emulator/tests/test_reserved.py` (the S rows), `emulator/tests/test_core.py` (RCP2) and `emulator/core/core.cpp`. Summary in `experiments/README.md`, "M3 bench session".

**Purpose.** M2 (image 0.3.2, 2026-11-18) left three questions open that the emulator needs answered. The probes,
their numbering and every expected value come from a request written from the emulator (not published). The
"emulator" values are its output on 2026-11-19, not expectations about the unit. A row that differs changes the emulator, and
the photograph is the evidence.

| Part | Probes | What it settles |
|---|---|---|
| S (SIDE) | S1-S12 | whether held load data is kept per data path (T1 / T2), or whether L6's handler load did not count because it ran in a handler; what a low or EMIFA read into a side B register returns (stock code does this all the time: the INST path, 1.0.65, LoFi-12, CyDrums) |
| N (NOP2) | N3, N4 | the interrupt period in CPU cycles and the loop's length (M2's 2:2:1:1 NOP pattern fits neither model); whether an interrupt is taken inside `NOP 9` when the requests are spread |
| R (RCP2) | 8 tables | whether the reciprocal estimates use the whole input (X) or only its top eight mantissa bits (T); GCC's division uses them on arbitrary inputs |
| P (PADR) | P3, P2 | carried over from M2: a pad hit's rise and fall (P6, with 0.3.3's trigger), and channel 15 on batteries (optional) |
| K (stock) | M2 part S | carried over: M1 I3 on stock 3.2.174 |

Parts S, N, R and P run on one image, **0.3.4**. Part K runs on the stock firmware after the restore.

Simulated in the image's test suite, class `Diag2`; the emulator ran the image and produced its screens before the
session.

Device state at start: as at the end of M2. M2's part S was not run, so the unit still had **0.3.2** installed
(check the status page). BOOT 1.0.17, PRESET 2.0.22, MCU 1.0.6.
Known deviations from stock: SYSTEM is the diagnostic image 0.3.2.
Recovery card prepared: card B, official SmplTrek 3.2.174 update as `SmplTrek.bin`.
Second card: card A carries the diagnostic image (now 0.3.4).

## Settings likely to change (named before starting)

- **SYSTEM image:** 0.3.2 replaced by 0.3.4 for parts S-P, then 3.2.174 restored from card B before part K.
- **Flash and card:** the diagnostic image writes neither, as 0.3.2.
- **Part K (stock):** the current project (use a scratch project; note the current one and switch back before powering
  off); one WAV copied to `/SMPLTREK/POOL/AUDIO/`; the preset instruments on the card if they are not there yet.

## Image 0.3.4 (built 2026-11-19, not published)

0.3.3 (0.3.2 with P6's trigger fixed) plus three views. Everything in 0.3.2 is unchanged and on the same keys, except
that the timer set-up now picks the INTSEL register by CPU interrupt (INTMUX1 for 4-7, INTMUX2 for 8). The NOP, IDLE
and L6 probes write the same values to the same registers as before.

**Keys on the DIAG page** (MIXER on the status page; nothing runs until its key is pressed). The STEP buttons are the
ones STEP 1-4 already use (tone, speaker); STEP 5-7 do nothing outside the DIAG page.

| Key | View | Runs |
|---|---|---|
| STEP 5 | SIDE (2 pages) | S1-S11 twice each; then S12 twice |
| STEP 6 | NOP2 (10 pages: N3 pages 1-5, N4 pages 6-10) | N3, 4,096 interrupts at a fixed period; then N4, 4,096 with the period varied. About 2.2 s in all |
| STEP 7 | RCP2 (18 pages) | the four estimates on the H and F inputs |
| OCT< | PADR B | arms P6 (0.3.3's trigger) |
| OCT> | PADR A | one second of UART1 bytes; also arms P6 |
| RIGHT / LEFT (arrows), encoder A | | next / previous page of the open view |
| STOP | | back to the main view |

### SIDE

Every probe is one routine in `probes.s` (`side_s1` to `side_s12`). `D` = `21 22 .. 28` and `E` = `31 32 .. 38` are
rewritten before every probe. `NOP 4` follows every load. Interrupts are off except in S12.

- `LDA` = `LDDW .D1T1 *D, A9:A8`; `LDB` = `LDDW .D2T2 *E, B7:B6`. Low address `0x8`; EMIFA `0x4630314C`.
- **The driver.** Each probe first sets its address registers with register moves only, then makes its loads in the
  request's order. So every value a probe reads was loaded inside the probe. **Nothing is loaded between a probe's
  read and its return** (a read into B4 is moved to A4 in the return's delay slot).
  - The driver's last load before each probe is `LDW .D2T1` of the probe's address from its table (`side_fn`).
  - `refs_set`'s stores come before that.
  - S9 is the one probe that does not load side A. Its read is on side B, after its own `LDB` and `LDBU`.
- **S12** is L6 exactly (`LD`, `IDLE`, then `LDW .D1T1 *0x8` after the handler returns), on CPU interrupt 6. Its
  handler is `LDDW .D1T1 *E, A7:A6`.
- **Flags:** EVTFLAG0-3, EFR and IERR before and after S1-S11.

| # | Sequence | Per path | Handler | Emulator now |
|---|---|---|---|---|
| S1 | `LDA`; `LDB`; `LDW .D1T1 *0x8,A4` | `24232221` | `34333231` | `24232221` |
| S2 | `LDA`; `LDB`; `LDW .D2T2 *0x8,B4` | `34333231` | `34333231` | stops |
| S3 | `LDB`; `LDA`; `LDW .D2T2 *0x8,B4` | `34333231` | `24232221` | stops |
| S4 | `LDB`; `LDA`; `LDW .D1T1 *0x8,A4` | `24232221` | `24232221` | `24232221` |
| S5 | `LDA`; `LDDW .D1T2 *E,B7:B6`; `LDW .D1T1 *0x8,A4` | `24232221` if T, `34333231` if D | `34333231` | `24232221` |
| S6 | `LDA`; `LDDW .D2T1 *E,A7:A6`; `LDW .D1T1 *0x8,A4` | `34333231` if T, `24232221` if D | `34333231` | `34333231` |
| S7 | `LDA`; `LDB`; `LDW .D2T1 *0x8,A4` | `24232221` if T | `34333231` | `24232221` |
| S8 | `LDA`; `LDB`; `LDW .D1T2 *0x8,B4` | `34333231` if T | `34333231` | stops |
| S9 | `LDB`; `LDBU .D2T2 *D+1,B5`; `LDW .D2T2 *0x8,B4` | `34332231` | `34332231` | stops |
| S10 | `LDA`; `LDB`; `LDW .D2T2 *0x4630314C,B4` | `38373635` | `38373635` | stops |
| S11 | `LDA`; `LDB`; `LDW .D1T1 *0x4630314C,A4` | `28272625` | `38373635` | `28272625` |
| S12 | L6, handler `LDDW .D1T1 *E` | `34333231` | `24232221` | `34333231` |

S1 and S12 separate the two explanations on their own. S5-S7 say whether "side" means the data path (T) or the
address unit (D). A value that fits neither column is a finding.

### NOP2

The 0.3.2 loop itself (`nop_loop`: `MVC TSCL`; `NOP 9`; `ADD`; `B`; `NOP 5`, 17 cycles), TIMER64P1 TIM12 in continuous
mode, event 40. N3 is on CPU interrupt 7 and N4 on 8; both start at PRD12 = 6,451 (6,452 ticks).

- **Records.** Each handler also stores (A1, its TSCL) per interrupt in a second buffer.
- **N3's handler** (`nop3_isr`) has 0.3.2's execute packets exactly: the two extra stores run in parallel with its
  second store and its SUB. So it takes the same cycles unless the extra stores stall (they go to DDR, as the first
  two do). **This is the one change from M2's NOP that could move the pattern.** The recorded cycles between entries
  show the period actually seen either way.
- **N4's handler** (`nop4_isr`) is N3's, followed by six serial instructions. They write PRD12 = 6,451 + 2 × (n mod 17),
  where n is the interrupt's index from 0, so its handler is about six cycles longer than N3's.
  - **When a PRD12 write takes effect on the unit is not known** (at once, or at the next match). The emulator re-reads
    the register at every compare. The cycles between entries show what the unit did.
  - The handler writes about 2 ticks after the match, when TIM12 is near 0, so the new period (≥ 6,451) is never below
    the count. A write below the count would run TIM12 to 2³² (about 3 minutes).

| | Emulator model (`nop_model.py`, not a run of the image) |
|---|---|
| N3 | as M2's emulator rows; cycles between entries 100,004 (twice in five), 100,005, 100,006, 100,011, summing to five periods of 100,006 |
| N4 | `+2` at nine differences, 17-25 (240-482 each), `+0 32` 723, `+1 16` 241, `+3 26` 482 |

If the unit waits the NOP out, N4 has one `+2` value; if it takes the interrupt inside the NOP, `+2` spreads over many
differences. The sum of cycles between entries over the whole run (page 3, `SC`) divided by the intervals gives the
period in CPU cycles without assuming the clock ratio. Cycles divided by passes, less the handler's share, gives the
loop's length.

### RCP2

The four instructions at exponent 0, k = 0-255, on two input variants:

- **H:** the bit just below the eighth mantissa bit set (single `k << 15 | 0x4000`; double `k << 44 | 1 << 43`).
- **F:** every bit below the eighth set (single `k << 15 | 0x7FFF`; double `k << 44 | (1 << 44) - 1`).

The image carries both rules' tables (generated by `hosttools/rcp_model.py`, which reproduces the request's CRCs
independently) and marks each table's CRC `X`, `T` or `-`.

| Table | CRC under X | CRC under T | Entries where X and T differ |
|---|---|---|---|
| SRH (RCPSP H) | `4B4BA4EB` | `24BA9252` | 122 |
| SRF (RCPSP F) | `9931D42E` | `24BA9252` | 212 |
| SQH (RSQRSP H) | `4F0CDFC1` | `B37E28CA` | 78 |
| SQF (RSQRSP F) | `4AC0B0B8` | `B37E28CA` | 150 |
| DRH (RCPDP H) | `101D82F2` | `9F40B027` | 122 |
| DRF (RCPDP F) | `26CA1CC6` | `9F40B027` | 212 |
| DQH (RSQRDP H) | `20A58DEE` | `E9F42249` | 78 |
| DQF (RSQRDP F) | `E31777B0` | `E9F42249` | 150 |

The emulator (and c6sim) give X on all eight.

### Reading the views

Lines are 8 pixels with 21 characters; labels are dim and values bright; a second run that differs from the first is
dim; the page number `n/N` is at the top right.

- **SIDE** page 1: `S1`-`S12`, run 1 and run 2 (`S12 NO TIMER EVENT` if the timer never raised its event); `D`, `E`.
  Page 2: `E0`-`E3`, `EF`, `IE` before and after S1-S11; `D`, `E`.
- **NOP2:**
  - Pages 1-5 are N3 and pages 6-10 are N4, with the same layout.
  - Page 1: `+IRP  difference  count`, largest first, as M2's NOP, top 14 (`MORE`: further pairs, and pairs beyond 48).
  - Page 2: the next 14.
  - Page 3: `CY` the six most frequent cycle counts between consecutive handler entries, with their counts; `PA` the same
    for loop passes between them (a leading `+n` on the last line: n more values not shown); `SC` the sum of cycles
    between entries over the run, and the number of intervals (4,095); `SP` the sum of passes.
  - Pages 4-5: the first 32 interrupts in order, one per line: index, `+IRP`, difference, cycles since the previous
    entry, passes since the previous entry (blank for index 0).
- **RCP2:**
  - Page 1: per table, name, CRC, `X` / `T` / `-`.
  - Page 2: per table, entries equal to rule X, entries equal to rule T, and the k = 0 result (doubles: high word).
  - Pages 3-18: the compact table, two pages per table in the order SRH, SRF, SQH, SQF, DRH, DRF, DQH, DQF. Each shows
    the eight mantissa bits per k, ten to a line, from the k in the header.
- **PADR B** (P3): as 0.3.3: `HIT` channel, count, `ARMED` / `DONE`, then 32 levels: the 8 before the trigger dim, then
  from the first level of 64 or more.

## Files on the cards

| Card | File (as SmplTrek.bin) | SHA-256 | What it is |
| --- | --- | --- | --- |
| A | experiments/D3_audio_0.3.4.bin | `c314d0db55a9711432e5b486cffbe3240b70c822767d6694f46278394ee75787` | diagnostic image for parts S-P |
| B | official SmplTrek 3.2.174 update | (as on the recovery card) | restore, then part K |

## Steps

Photograph every page named.

| # | Action | Expected outcome (emulator) | If different |
| --- | --- | --- | --- |
| A0 | Install 0.3.4 from card A (HOME + power, BOOT MODE, SYSTEM UPDATE: `V0.3.2 -> V0.3.4`). Status page: version `0.3.4` | as 0.3.2 | no status page within 10 s: stop rule |
| R1 | MIXER (DIAG). STEP 7; photograph pages 1-2 | all eight `X` (the emulator's rule) | any `T` or `-`: photograph that table's two compact pages (table t, 0 = SRH: pages 3 + 2t and 4 + 2t) |
| S1 | STEP 5; photograph pages 1-2. STEP 5 again; photograph page 1 | the "Emulator now" column, S2/S3/S8/S9/S10 unknown | record every row; a freeze: stop rule |
| N1 | STEP 6 (wait about 3 s for the view); photograph all 10 pages | see NOP2 above | `NO TIMER EVENT` on N3 or N4: record; freeze: stop rule |
| N2 | STEP 6 again; photograph pages 1, 3, 6 and 8 | as N1 | record |
| P3 | OCT<, then hit TRK 1 once firmly; photograph PADR B. OCT<, hit TRK 1 softly; photograph | `DONE`, channel 1, 8 dim idle levels then the rise and fall | `ARMED` still: hit harder (the trigger is level 64; a press read about 3300 in M2); record |
| P2 | Optional, needs batteries. On batteries only, OCT>; photograph PADR A | channel 15 differs from AC (0-6 in M2) | record |
| K0 | Restore: card B, BOOT MODE, SYSTEM UPDATE, 3.2.174. Start the stock app, check SYSTEM INFO | stock firmware | follow the recovery card procedure |
| K1 | M2 S1: stock 3.2.174, a scratch project (note the current one first), one WAV in `/SMPLTREK/POOL/AUDIO/`. FUNC+PROJECT, SAMPLE, Pool, AUDIO, select the WAV, **OK on the file name** | the AUDIO LOADER opens | record what the screen shows; video |
| K2 | M2 S2: INST on a track: load the guitar; play pads | the guitar plays | record; switch back to the noted project before powering off |

What this cannot distinguish:
- S: as M2's L: the CPU's reads from this image's code and cache state; not DMA.
- N: TSC differences include the interrupt recognition delay. The cycles between entries are exact, and the IRP shows
  where each request was taken.
- R: the results at these inputs only (exponent 0).

## Stop rules

- No flash writes except BOOT MODE's SYSTEM UPDATE (twice: 0.3.4 in, 3.2.174 back).
- **A view freezes** (the seconds counter on the main view, or the view, stops updating): that is the finding.
  Record which view and step, remove power, power on (0.3.4 is still installed) and continue from the next step.
  N1 shows nothing for about 2-3 s while it runs; a freeze is longer than 10 s.
- The unit does not reach the status page within 10 s: hold the power key, then HOME + power and restore from card B.
- Part K opens only the SAMPLE pool browser and the INST loader; no other card function.

## Evidence capture

Stills of every page named in the steps; video for K1 and K2.

## Deviations from the request (2026-11-19)

- SIDE runs S1-S11 in the table's order, both runs, then S12 twice. Flags are taken around S1-S11 only: S12's
  interrupt sets and clears event 40 itself.
- S12 uses CPU interrupt 6 (L6 uses 5), so 0.3.2's L6 stays as it was.
- NOP2 runs N3 and N4 on one key, one after the other, on interrupts 7 and 8 (0.3.2's NOP stays on 4).
- NOP2 shows the first 32 interrupts in order (the request asked for 16), so that one N4 cycle of 17 is on the pages.
- RCP2 also counts the entries equal to each rule (page 2), so a partial match is visible without the compact pages.

## Results

Not transcribed here; see the header for where the values are recorded.
