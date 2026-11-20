# Lofi-12 XT functions on a SmplTrek panel (button map for cross-flashed firmware)

Which SmplTrek button does what when the Lofi-12 XT 1.5.205 app runs on a SmplTrek, as it did in device session C3
(2026-11-11, `experiments/sessions/C3-crossflash.md`). The panels are physically the same, but the printed labels
differ, which made navigation hard in C3.

**How this was derived (static + manuals; confidence medium-high).**
- **Bit to position.** The factory button-test page (`AppTestControl::draw`) draws the panel from fixed rectangle
  tables, one rectangle per switch bit. Lofi-12 XT runs identical code with identical tables
  (`docs/01-platform-map.md`, "Panel input"). So in both apps the same switch bit belongs to the same place on the
  panel, and the key matrix and its scan code are identical too.
- **Position to label.** Each product's manual ("Names of parts", page 8 in both) gives the printed label at that
  place. SmplTrek's bit-to-label table is in `g_control_switch_state`'s evidence (SmplTrek symbol file).
- **Partly checked in Lofi's own handlers (2026-11-12).** Lofi builds each button mask with
  `set reg,n,n`, not with a constant, so a search for constant masks finds nothing. Example: `0xC2BA079A` builds
  bit 23 (OK).
  - **Page objects.** The static page objects were identified from their constructors in the start-up function
    `0xC2CB7060`:

    | Address | Page |
    |---|---|
    | `0xC2B7F088` | AppSystemMenu |
    | `0xC2B7EFFC` | AppProjectMenu |
    | `0xC2B7F04C` | AppSampleRecording |
    | `0xC2B7E440` | AppMixer |

  - **Where they appear.** All four are referenced next to the masks for bits 20, 21, 22 and 27 in
    `AppFileSelect`'s button handler (`0xC2C31908`, vtable slot 4). That handler compiles a `switch` on the 64-bit
    button word into a predicated binary search, and the pairing of mask to page wasn't settled by hand.
  - **The func branch, read by hand (2026-11-12).** With func held, the handler would open AppSampleRecording on
    bit 22 (agrees with the map: Lofi ● REC / sampling) and AppSystemMenu on bit 27 (disagrees: the map says Lofi
    PAD / project). Bits 20 and 21 reach the page change but set no page. The whole branch is gated by a call to
    `0xC2C31904`, which always returns 0, so it is dead code. SmplTrek's `AppFileSelect` handler (`0xC15E11CC`) has
    the same block without func: home (bit 27) → HomeModeController, project (bit 20) → AppProjectMenu, other
    (mixer) → AppMixer. There it is gated by a real check (`0xC15E11A8`, non-zero result of `0xC154CF14`). Lofi's
    copy was edited, then disabled, so its targets are weak evidence. The device check of bit 27 is step 5b of the
    session plan C4 (`experiments/sessions/C4-relocated-lofi.md`, not run).
    An execute-packet simulator agrees (an earlier scratch version of `analysis/c6sim.py`, checked against
    the hand-read Lofi settings validator; `docs/01-platform-map.md`, "CyDrums reading SmplTrek's settings"). With `0xC2C31904` forced to return 1:
    func + bit 22 stores AppSampleRecording, func + bit 27 stores AppSystemMenu, and bits 20 and 21 reach the
    page switch with no page stored. With the real function, no func + key does anything in this handler.
  - **One row checked in Lofi's code, by simulation (2026-11-12).** `analysis/c6sim.py` ran Lofi's 172
    `.init_array` constructors (boot copy table applied, the run-time-support lock hooks and one PSC1 polling
    routine `0xC2CC2480` stubbed). It then ran the MainDelegate set-up method `0xC2BAC964`, which sets
    `this+104 = this+12`, and made AppMixer the current page (`B14+1064`). A button message for each bit then
    went through `MainDelegate::handle_message`. On the mixer page, **bit 21 runs exactly the same 516 calls as
    CLR (bit 30)**, so it closes the mixer like CLR. That is what Lofi's MIX button should do on its own page,
    and the map puts MIX at bit 21 (SmplTrek's mixer / fx position). The mixer page also reacts to bits 18,
    27 and 8 without func, and to 30, 8 and 9 with func.
  - **Still open in code.** The main screen (the `EditPageController` pages) is not built by the static
    initialisers; it appears later in the app's start-up tasks, which were not run. So func + system → SYSTEM
    MENU from the main screen is unchecked in code; the device check covers it.
  - **Where static reading stops.** The global func + key dispatch goes through `MainDelegate::handle_message`
    (`0xC2BAEB90`). That function first calls through a run-time object at `this+104`, so it can't be followed
    statically without that object's state.
  - **Conclusion.** The map below rests on the identical test-page code plus the manuals. The device check at
    the end decides it; session plan C4 step 5 includes it (not run).
- **One known oddity:** in SmplTrek, AppTuner and AppSystemInfo close on bit 26 (● / sampling in this map) as well
  as on CLR, which is odd for a record button. It doesn't contradict the map, but it is the first place to look if
  the device check disagrees.

## The 2 x 4 function block (left of OK / CLR)

| Position | Switch bit | SmplTrek label | Lofi-12 XT label (shifted function with func) |
|---|---|---|---|
| upper row, 1st | 19 | func | func |
| upper row, 2nd | 26 | ● (rec) / sampling | PTN / save |
| upper row, 3rd | 20 | project / pool | COPY / song |
| upper row, 4th | 27 | home / system | PAD / project |
| lower row, 1st | 22 | ▶ play / ◀◀ | ● REC / sampling |
| lower row, 2nd | 29 | ■ stop / ▶▶ | ▶ Play / system |
| lower row, 3rd | 21 | mixer / fx | MIX / ext src |
| lower row, 4th | 28 | edit / rec src | MUTE / mix tape (☰) |

Under Lofi, the most useful translations (press SmplTrek's buttons):

| Lofi-12 XT action | Press on the SmplTrek |
|---|---|
| Play / stop a pattern | ■ stop |
| Record (REC) | ▶ play |
| SYSTEM MENU (func + system) | func + ■ stop |
| SAMPLING page (func + sampling) | func + ▶ play |
| MIXER (MIX) | mixer (fx) |
| USB & EXT IN page (func + ext src) | func + mixer (fx) |
| MUTE | edit (rec src) |
| MIX TAPE page (func + mix tape) | func + edit (rec src) |
| PATTERN SELECT (PTN) | ● sampling |
| PATTERN SAVE (func + save) | func + ● sampling |
| COPY | project (pool) |
| SONG SELECT (func + song) | func + project (pool) |
| PAD mode (PAD) | home (system) |
| PROJECT MENU (func + project) | func + home (system) |

## CyDrums 1.1.84 on a SmplTrek panel (static + manual, 2026-11-12)

The bit-to-position step holds for CyDrums too: its button-test page is compiled differently but encodes the same
coordinates, bit numbers and masks (`docs/01-platform-map.md`, "Physical buttons and bit map"). CyDrums' manual
("Names of parts", page 8, item 11) prints the same 2 x 4 block as Lofi-12 XT's, in the same order. Only two
shifted functions differ: the 1st lower button is REC / **kit** (Lofi: sampling) and the 4th is MUTE / **perfom**
(sic; Lofi: mix tape).

| Position | Switch bit | SmplTrek label | CyDrums label (shifted function with func) |
|---|---|---|---|
| upper row, 1st | 19 | func | func |
| upper row, 2nd | 26 | ● (rec) / sampling | PTN / save |
| upper row, 3rd | 20 | project / pool | COPY / song |
| upper row, 4th | 27 | home / system | PAD / project |
| lower row, 1st | 22 | ▶ play / ◀◀ | REC / kit |
| lower row, 2nd | 29 | ■ stop / ▶▶ | Play / system |
| lower row, 3rd | 21 | mixer / fx | MIX / ext src |
| lower row, 4th | 28 | edit / rec src | MUTE / perfom |

So SYSTEM MENU is func + ■ stop under CyDrums as under Lofi, and DRUM KIT is func + ▶ play. The rest of the panel
matches the Lofi table below: CyDrums' manual has the same 7 parameter pads, 8 track pads, page switches beside the
upper pad row, two auxiliary buttons, D-pad, OK / CLR, A-D knobs, VALUE (push: TEMPO MENU) and 16 STEPs. Not
checked in CyDrums' handlers; the same device check applies. The firmware-update chord differs: CyDrums' manual says
PAD + power, but on a SmplTrek the boot loader is SmplTrek's, so HOME + power stays the way in.

**Under CyDrums without its card, the panel does nothing useful.** The start-up page with no card (AppNoCard,
"NO CARD / INSERT CARD!") and the one for a card without `/CyDrums/System/SystemCore.bin` (AppNoSystemCore,
"BLANK MEDIA! / DOWNLOAD FILES / FROM THE WEB.") both answer every button, encoder and pad slot with "handled, do
nothing" (vtable slots 4, 6, 7, 8 return 1). Whether the global func + key dispatch still opens SYSTEM MENU over
them is not known (same obstacle as Lofi). See `docs/01-platform-map.md`, "CyDrums start-up and the card".

## Everything else: same place, same role

| Control | SmplTrek | Lofi-12 XT |
|---|---|---|
| OK, CLR | OK, CLR | OK, CLR |
| D-pad (bits 17 up, 18 right, 24 left, 25 down) | direction buttons | D-pad (also re-trigger divisions) |
| Two buttons under the screen (bits 8, 9) | selection buttons | auxiliary buttons |
| Knobs A-D and their pushes (bits 0-3) | control knobs | control knobs |
| VALUE knob and push (bit 4) | VALUE | VALUE (push: TEMPO MENU) |
| 16 STEP buttons (bits 32-47) | STEP 1-16 | STEP 1-16 |
| Buttons left and right of the upper pad row (bits 16, 31) | octave down / up | page switches (scale shift in PAD mode) |
| Upper pad row, 7 pads | TRK 1-7 | parameter pads CFG, SND, FLT, MOD, AMP, EFX, RVB |
| Lower pad row, 8 pads | TRK 8-10, GLOBAL 1-3, USB AUDIO, EXT SRC | track pads TRK 1-8 |
| VOL, mic gain, input gain L/R | analogue knobs | analogue knobs (same roles) |

The pads are the same 15 sensors on the panel controller (channels 0-14) in both products. Which channel is
which pad position is taken from the drawings (two staggered rows of 7 and 8 in both), not from code.

## Device check (no writes; not run)

Under Lofi:
- Press func + ■ stop: SYSTEM MENU should open.
- Press func + home (system): PROJECT MENU should open. SYSTEM MENU here would mean the bit-27 row is wrong.
- Press func + ▶ play: the SAMPLING page should open (leave with CLR, don't start sampling).
- Press ■ stop on its own: pattern playback should start or stop.

If either is wrong, this map's position-to-label step is wrong for that row. The bit-to-position step comes from
identical code and is not in doubt.
