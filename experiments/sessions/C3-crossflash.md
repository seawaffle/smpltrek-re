# Session C3: sterilised Lofi-12 XT 1.5.205 on the SmplTrek, then back (planned and run 2026-11-11)

> **Run 2026-11-11 (evening): passed.** The foreign app was written, booted and ran; BOOT MODE was reached with it installed; stock 3.2.174 restored; SmplTrek settings unchanged.
>
> **Results:** "Results" at the end of this file; summary in `experiments/README.md`.

**Purpose.** First write of a foreign system image. Does a Lofi-12 XT app boot and run on SmplTrek
hardware, and does HOME + power still recover the unit afterwards? This is also the first time the boot path is
not Sonicware's own SmplTrek app, so it is the first real test of recovery when the app might hang at boot
(`SAFETY.md`, "Not known").

**Test file** (built 2026-11-11): `experiments/Lofi12XT_1.5.205_sterilised_family5_smpltrekseeds.bin`,
SHA-256 `67d8a6b07f84b32ab987a4dc07bb0def5370c0074d95d0128724d13f4c7ea2fb`, built by `tools/patches/sterilise_lofi.py`
from the recipe below; every check below passed (`experiments/README.md`, "C3 sterilised Lofi-12 XT image").

## What the offline work says (static unless marked)

- **Acceptance.** A Lofi image rewrapped as family 5 with SmplTrek seeds reaches the confirmation screen
  (device: W1, 2026-11-09, never written). SYSTEM is written whatever its version (device: D1). Expected
  confirmation: `SYSTEM: V3.2.174 -> V1.5.205`.
- **Loading.** The bootloader copies each section to its load address and jumps to the entry
  (`docs/05-bootloader.md`). Lofi loads into `0xC2B809E8`-`0xC2DBC698`. The bootloader itself runs from
  `0xC702xxxx`-`0xC70Bxxxx`, so no overlap. Normal boot does no CRC check.
- **Board pins.** Lofi-12 XT configures the same GPIO pins, in the same directions, with the same constant writes,
  through code identical to SmplTrek's (XF-14). So no new electrical conflict is expected.
- **Pads.** Same press/release thresholds and velocity curves, plus continuous pressure (XF-14). The panel MCU is
  SmplTrek's (1.0.6). Its pad scaling vs a Lofi panel MCU is unknown, so pads may feel different.
- **Flash.** Lofi-12 XT reads only the settings sectors and the 'bmtd' / 'mmtd' headers (XF-3). It writes only
  through `settings_save`, which the sterilised image disables (XF-5). So this session writes flash only
  through the two authorised updates below.
- **Settings.** Lofi reads SmplTrek's settings block and range-checks it. Wrong-but-valid settings are
  expected: see the checklist in step 6 (XF-13). Nothing is saved back, so SmplTrek's settings should be
  exactly as before after the restore.
- **Not settled statically:**
  - whether Lofi's own bootloader sets different clocks (UART, tick);
  - whether audio pitch could change (MCLK source not traced);
  - LED addressing;
  - which SmplTrek button carries each Lofi function (the bit map is shared, the printed labels are not).

## The test file

Source: official `firmware/lofi12/Lofi-12XT_v1.5.205.zip` → `Lofi-12XT_v1.5.205/Lofi-12 XT.bin`, SHA-256
`a8bffa65919c0a2d4ff2ce77d16301551af4d2964497b8804deed49ce4198026`.

Recipe:
1. **Sterilise.** At file offset `0x11FAC4` (`settings_save` at `0xC2C8B0F8`), replace bytes `f7 36 77 95` with
   `26 06 ef a1`. That is two 16-bit instructions: `mvk .L1 0,a4` then `bnop .S2 b3,5`. **Leave the next four bytes
   (`50 00 c0 eb` at `0x11FAC8`, the fetch-packet header) unchanged.** The earlier three-instruction form doesn't fit
   here; see `docs/01-platform-map.md`, "Where the patch has to fit".
2. **Wrap.** Set the container word at offset 0x10 to 5, as for W1.
3. **Reseal** every CRC with SmplTrek seeds, children first: `tools/sonicware_integrity.py reseal --profile smpltrek`.
4. Save it as `experiments/Lofi12XT_1.5.205_sterilised_family5_smpltrekseeds.bin` (gitignored) and record its SHA-256 here.
   Built: SHA-256 `67d8a6b07f84b32ab987a4dc07bb0def5370c0074d95d0128724d13f4c7ea2fb` (13 bytes from stock: 0x08, 0x10, 0x38, 0x11FAC4).

Checks before it goes on a card (all must pass):
- `tools/sonicware_integrity.py verify` reports every CRC valid under the SmplTrek profile.
- **Diff against the official file: exactly 13 differing bytes, at most:**
  - the 4 patch bytes at `0x11FAC4`;
  - the family word;
  - the 4-byte mmtd CRC;
  - the 4-byte cmtd CRC.

  W1 differed in 9 bytes; this file adds the 4 patch bytes. Any other difference: don't use it.
- Disassemble the patched system image with `analysis/mmtd2elf.py` and the tic6x objdump, as for the
  other images. The listing at `0xC2C8B0F8` must read `mvk .L1 0,a4`, then `bnop .S2 b3,5`, then the same
  fetch packet header `0xebc00050`. Everything after `0xC2C8B0FC` must be identical to the official listing.

Second, independent check of the built file (2026-11-11, read-only, not using the builder):
- `verify --profile smpltrek`: cmtd `56ead7e0` OK, mmtd `986b2c3a` OK.
- Byte diff: 13 bytes, at 0x08-0x0B, 0x10, 0x38-0x3B and 0x11FAC4-0x11FAC7; the header bytes at 0x11FAC8 are unchanged.
- Disassembly: only `0xC2C8B0F8` and `0xC2C8B0FA` differ from `work/lofi-1.5.205.dis`.

## Before the session

Device state at start (expected): BOOT 1.0.17, PRESET 2.0.22, SYSTEM 3.2.174, MCU 1.0.6. Check it on SYSTEM INFO
and photograph it. If anything differs, stop.

Known deviations from stock: none (D1 ended on official 3.2.174, 2026-11-11).

Cards:
- **Card A (test):** the C3 file only, as `SmplTrek.bin`. Check its hash on the card (`67d8a6b0…7ea2fb`). The Lofi app may create its
  own folders on any card it sees, so use a card with nothing you need on it.
- **Card B (recovery):** official 3.2.174 `SmplTrek.bin`, SHA-256
  `3b6848b0f041bcf23c73d4b0357d2f3d6dc9e7e03752b32ff7322e91e6814e53`, hash checked on the card. Keep it out of the
  unit until step 9.

Power: mains USB charger or fresh batteries, not a computer. The bootloader refuses to update on low batteries,
and a computer would see a Lofi-12 XT USB device. Don't connect the unit to a computer at any point.

Listening: headphones **off your ears** and every volume at minimum before the first boot under Lofi.
Lofi-12 XT has its own volume handling and may start loud.

## Settings to note before flashing (SmplTrek, step 1)

Write down the current value of each, so step 10 can confirm they come back unchanged:

| SmplTrek setting | Where | Value before | Value after restore |
| --- | --- | --- | --- |
| AUTO POWER OFF | SYSTEM | | |
| BATTERY TYPE | SYSTEM | | |
| QUANTIZE | SYSTEM | | |
| TEMPO LED | SYSTEM | | |
| PAD VELOCITY | SYSTEM | | |
| POLARITY IN / OUT | SYSTEM | | |
| METRONOME VOLUME / PRECOUNT | tempo | | |
| INPUT FROM / OUTPUT TO | MIDI CONFIG | | |
| PROJECT / AUTO / PC CHANNEL | MIDI | | |

## Steps

| # | Action | Expected outcome | If different |
| --- | --- | --- | --- |
| 1 | Power on normally. SYSTEM INFO (photograph). Fill in "Value before" above. Power off. | BOOT 1.0.17, PRESET 2.0.22, SYSTEM 3.2.174, MCU 1.0.6 | Stop; record; don't flash. |
| 2 | Card A in. Hold HOME, power on → BOOT MODE → SYSTEM UPDATE. Photograph the confirmation. | `Checking... 100%, OK.`, `SYSTEM:` `V3.2.174 -> V1.5.205`, `Are you sure?` | **NG or "invalid":** the file is wrong; nothing was written; stop and check the build. **Any line besides SYSTEM:** CLR, stop. |
| 3 | Press OK. Film or photograph to the end. | Erasing / Writing / Verifying, then "Update completed" | **Verifying fails or "Update failed":** the old SYSTEM is gone and no marker was written. Don't retry with card A. Go to step 9 with card B; record the exact text. |
| 4 | Power off. Remove card A. Cold boot (no HOME, no card). Watch for 60 s; film it. | the Lofi-12 XT start-up screen, then its main screen | **Blank, frozen, garbage, or restarting:** film it, wait the full 60 s, power off, go to step 8 (the recovery test). This is a valid result, not a failure of the session. |
| 5 | Lofi running, everything at minimum volume. Open the SYSTEM MENU (Lofi manual: func + system; on SmplTrek's panel the same bits may carry other labels, so try func + system first and note which buttons work). Open INFORMATION; photograph it. | SYSTEM 1.5.205, BOOT 1.0.17, MCU 1.0.6 (Lofi has no PRESET row) | Note what it shows. Odd versions alone are not a stop. |
| 6 | **First check AUTO POWER OFF**, then the rest of the checklist below. Note the values; don't change any of them. | values as in the checklist | Different values: just note them. They tell us how well the static reading worked. |
| 7 | Short functional check, under 10 minutes in all. **Display:** readable, nothing stuck. **Knobs:** turn each of the five; does a value move? **Pads:** tap a few lightly, then firmly; note whether sound and LEDs respond. **Audio:** headphones still off your ears, raise volume slowly while tapping a pad; then put them on at low volume. **Card:** insert card A; does the Lofi browser list it? Don't format, save, update, or open card-reader mode. | display, knobs, pads and audio work; pads may feel harder or softer | Anything not working: note it and continue. **Loud noise, burning smell, heat, a hiss that rises:** power off at once and unplug. Stop the session and report. |
| 8 | Power off. Cold boot once more without HOME (repeatability), then power off. Then hold HOME and power on. | same start-up as step 4; then BOOT MODE appears | **BOOT MODE doesn't appear:** try twice more, holding HOME firmly before power. If it still doesn't appear, **stop and report before anything else**; don't improvise. |
| 9 | In BOOT MODE: SYSTEM DIAG (photograph). Then card B in → SYSTEM UPDATE (photograph the confirmation) → OK → photograph the end. | DIAG: SYSTEM v1.5.205 Checking OK, the others as before; confirmation `V1.5.205 -> V3.2.174`; "Update completed" | DIAG NG on SYSTEM: record it and continue with the restore. **Restore rejected:** check card B's hash; if it is right and still rejected, stop and report. Nothing else is written. |
| 10 | Remove card B, cold boot. SYSTEM INFO (photograph), SYSTEM DIAG (photograph), quick pad, playback and card check. Fill in "Value after restore". | BOOT 1.0.17, PRESET 2.0.22, SYSTEM 3.2.174, MCU 1.0.6; DIAG all OK; settings equal to before | **A setting changed:** record it. That would mean something wrote the settings sector despite the patch: an important finding. Don't reset anything; report it. |

## Lofi-12 XT checklist (step 6)

Predicted from SmplTrek's settings as they were on the A4 dump (2026-11-11, before D1); later changes on the unit
change these. "Expected" is the static prediction. Label meanings are inference from the Lofi manual's option order.

| Lofi-12 XT setting | Where (Lofi manual) | Expected | Validator fallback | Note |
| --- | --- | --- | --- | --- |
| AUTO POWER OFF | SYSTEM MENU | value 4 of 0-4: Off or a timer (20 min to 6 h), order not decoded | 0 | If it shows a timer, the unit may switch itself off when idle; that's not a crash. |
| PAD VELOCITY | SYSTEM MENU > PAD | SOFT | LINEAR | |
| P-COUNT (precount) | TEMPO MENU, D knob | 4 | 4 | |
| CASSETTE type | MIX TAPE, A knob | index 0 of 6 (which name not decoded) | index 5 | |
| TEMPO LED | SYSTEM MENU | on | on | |
| BAT.TYPE | SYSTEM MENU > POWER | first option | first option | |
| MIDI IN FROM | MIDI CONFIG | MIDI (DIN) only | both | |
| MIDI OUT TO | MIDI CONFIG | 0, probably no output | both | |
| Track MIDI channels | MIDI | each track one channel higher than Lofi's default | track n = channel n | |
| Input / recording level (if a setting shows it) | | possibly very low (an unlabelled word reads 1 instead of 100) | | Note it if recording is near-silent. |

## What this cannot distinguish

- **A blank screen at step 4** can't tell "the bootloader refused the image" from "Lofi started and stopped
  early". The DIAG in step 9 narrows it: SYSTEM OK means the image is intact and was jumped into.
- **Working pads and knobs** show that the input layer is compatible. They don't show that every Lofi feature
  maps to a SmplTrek button.
- **Settings equal at step 10** show that nothing wrote the settings sector during this session, i.e. the patch
  held for the paths exercised. Paths not exercised (for example a Lofi factory reset) aren't tested.

## Stop rules

- **Exactly two writes are authorised:** the C3 file at step 3 and official 3.2.174 at step 9. CLR out of any
  other confirmation screen. No third write.
- **Never use these under Lofi:** firmware update, format, card-reader mode, factory reset, or a computer
  connection.
- **Power off immediately** on noise, smell or heat, and report.
- **Abort and report** if HOME + power stops reaching BOOT MODE. That is the one outcome this whole plan is built
  to detect early.
- **Any screen text not covered above:** record it exactly and don't improvise.

## Evidence capture

Video for steps 3, 4 and 8. Stills (not published):
- SYSTEM INFO before;
- the C3 confirmation and its end screen;
- Lofi INFORMATION and each checklist value;
- DIAG under Lofi;
- the restore confirmation and its end screen;
- SYSTEM INFO and DIAG after.

Quote screen text exactly.

## Results (filled in during/after)

| # | Observed | Matches expectation? | Evidence (photo/video/ref) |
| --- | --- | --- | --- |
| 1 | Not photographed in this session. D1 ended on stock 3.2.174 earlier the same day (photo). | presumably | operator report |
| 2 | `$ systemupdate` / `Check the firmware file.` / `Checking... 100%, OK.` / `SYSTEM:` / `V3.2.174 -> V1.5.205` / `Are you sure?` / `[CLR] : No / [OK] : Yes` | yes | photo |
| 3 | `>> SYSTEM` / `Erasing... 100%, done.` / `Writing... 100%, done.` / `Verifying... 100%, OK.` / `Update completed.` / `Please restart.` | yes | photo |
| 4 | The Lofi-12 XT app booted (operator: "experiment successful"). | yes | operator report; next row |
| 5 | Lofi's SYSTEM INFO page: `LoFi-12 XT`, `BOOT 1.0.17`, `SYSTEM 1.5.205`, `MCU 1.0.6` (no PRESET row, as predicted) | yes | photo |
| 6 | Operator-reported values: AUTO POWER OFF 6h, MIDI OUTPUT TO off, PROJECT / AUTO / PC CHANNEL 16 / 1 / 2 (SmplTrek before: Off, MIDI, 14 / 16 / 15). These equal the static prediction for Lofi's reading of SmplTrek's block exactly (stored 15 / 0 / 1 = channels 16 / 1 / 2; AUTO POWER OFF value 4; OUT TO 0). Confirmed by the operator afterwards: these were the values **under Lofi**; SmplTrek's own settings were unchanged after the restore. Decodes one unknown: Lofi's AUTO POWER OFF value 4 = 6 h. Other checklist rows not reported. | yes, where reported | operator report |
| 7 | Operator: recorded a sample and played it back, navigated several screens; no audio or display problems. Navigation was hard because the button layout is very different (Lofi functions on SmplTrek-labelled buttons). Knobs, pads, LEDs and card not reported separately, but recording and playback imply the input, audio-out and pad or button paths work. | yes | operator report |
| 8 | BOOT MODE reached with the Lofi app installed; SYSTEM DIAG: `BOOT : v1.0.17`, `MCU : v1.0.6`, `PRESET : v2.0.22`, `SYSTEM : v1.5.205`, each `Checking... 100%, OK.` | yes | photo |
| 9 | Restore: `Checking... 100%, OK.` / `SYSTEM:` / `V1.5.205 -> V3.2.174` / `Are you sure?`; OK pressed; end screen not photographed. | yes | photo |
| 10 | SmplTrek SYSTEM INFO: `BOOT 1.0.17`, `PRESET 2.0.22`, `SYSTEM 3.2.174`, `MCU 1.0.6`; SYSTEM DIAG all four `Checking... 100%, OK.` Settings after the restore: back to the original values (operator): AUTO POWER OFF Off, OUTPUT TO MIDI, channels 14 / 16 / 15. | yes | photos |

**What this establishes (device).**
- A foreign system image, official Lofi-12 XT 1.5.205 with 4 patched bytes, rewrapped and resealed, is written,
  verified, booted and run by the SmplTrek bootloader on SmplTrek hardware. Cross-flashing works.
- BOOT MODE is reached by HOME + power with a foreign app installed, and BOOT MODE's DIAG accepts the foreign
  image. The official restore from it works.
- The settings values reported match XF-13's prediction exactly.

**What it does not establish.**
- Recovery from an app that **hangs** at boot: the foreign app booted, so this session does not test that path;
  session D0 (2026-11-12) does.
- That every Lofi feature works on this panel. Recording, playback, display and menus worked; the rest wasn't checked item by item.
- Settled: the settings sector was not written. SmplTrek's settings were unchanged after the restore, so the
  sterilised writer held for everything exercised (no Lofi factory reset was tried).

Device state at end: BOOT 1.0.17  PRESET 2.0.22  SYSTEM 3.2.174  MCU 1.0.6 (photos 22:41, 22:43).

Claims to update afterwards:
- XF-1 (write and boot, not only acceptance);
- XF-13 and XF-14 (checklist observed);
- INT-8 (HOME + power with a foreign app);
- `SAFETY.md` "Not known";
- the ledger in `experiments/README.md`.
