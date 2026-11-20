# Session C4: Lofi-12 XT 1.5.205 with relocated settings, on the SmplTrek, then back (planned 2026-11-12, not run)

> **Not run.** A plan only: no image has been built from it, and the unit has never run it.
>
> **Results:** none.

**Purpose.** C3 showed a cross-flashed Lofi-12 XT runs on the SmplTrek. Its image was sterilised, so nothing could be
saved. C4 tests the relocated-settings variant (claim XF-15). It is official Lofi-12 XT 1.5.205 with eight instruction
words changed, so its stock settings writer saves to the free top of flash device 0 (`0x00FFE000` / `0x00FFF000`)
instead of SmplTrek's settings sectors (`0x01FFE000` / `0x01FFF000`). The questions:
1. Does Lofi save and reload its own settings there?
2. Are SmplTrek's settings untouched, and is SYSTEM DIAG still all OK after returning?
3. Optional: do Lofi's settings survive a round trip through SmplTrek?

The session also runs the one-minute button-map check (`docs/10-cross-flash-button-map.md`).

**Gate.** Unlike C3, this image **writes flash from the app**: Sonicware's own settings
writer, at a changed address. That is not custom code, but every session so far has kept flash writes to the two
BOOT MODE updates (`SAFETY.md`, "Custom code"), so C4 would be a deliberate exception. The write review below is the offline evidence for one.

Check any image built from the specification with
`tools/patches/check_relocated_lofi.py` before it goes near a card.

## Write review (static and file evidence, 2026-11-12)

What the app writes, and why it can't reach anything else:
- **Writer and addresses.** Lofi forms its settings addresses only in `settings_save` / `settings_load`: seven
  `set ..,24` sites plus one `mvkh 0x01FF`. This was rechecked 2026-11-12 by scanning the whole listing:
  - The only other `mvkh 0x01FF0000` (`0xC2CD9858`) builds `0x01FF1E1F`, a non-aligned constant stored into a
    peripheral structure next to PSC1 setup. It is not a flash address.
  - No other `set` produces a `0x01FFxxxx` value.

  All erase and program call sites are in `settings_save` and its helper (XF-2). The eight words are listed in
  `docs/01-platform-map.md`, "Relocated-settings variant".
- **Device selection.** `flash_select_address` (`0xC2C35920`) selects device 0 for addresses below `0x01000000`, at
  the same offset, and device 1 above, at offset − `0x01000000`. Lofi already reads device 0 through the same
  path (the `bmtd` / `mmtd` headers, XF-3). So `0x00FFF000` is device 0, offset `0xFFF000`.
- **Erase size.** `do_erase` (`0xC2C1ECE0`) picks the command per step:
  - `0xD8` (64 KiB) only at 64 KiB-aligned addresses with at least 64 KiB left;
  - `0x52` (32 KiB) only at 32 KiB-aligned addresses with at least 32 KiB left;
  - otherwise `0x20`, a 4 KiB erase.

  `settings_save` asks for 4096 bytes at `0xFFF000` and `0xFFE000`, which are neither 32 KiB nor 64 KiB
  aligned. So each erase is exactly one 4 KiB sector.
- **The target is free.** In both A4 dumps, `0x0FC7C18` to `0x1000000` is erased (`0xFF`), and no `pmtd` directory
  entry covers it (PPRJ ends at `0x0FC7C18`).
  - A SYSTEM update erases only `0x40000`-`0x440000`.
  - No official file can rewrite PRESET (SAFETY.md).
  - No SmplTrek 3.2.174 read reaches it: content reads are bounded by the directory.
- **SYSTEM DIAG is unaffected.** The PRESET CRC covers only the `pmtd` header and each partition's own bytes. That was
  checked on the dump: CRC-32 over the header (CRC field set to `0xB02C53FD`, `+12` set to `0xFFFFFFFF`) and then the five
  partitions in directory order gives exactly the stored `0xCA1D0801`. So bytes at `0xFFE000` can't change DIAG.
- **Boot-area protection.** It covers the bottom 256 KiB of device 0 (BP = 0011, TB = 1, inference about the
  part; INT-12). Since 2026-11-16 the bits themselves are read on the unit: device 0 status `0C`, configuration `0F`
  (HW-54); their meaning still comes from the Macronix register layout. If the part instead protected the top 256 KiB, the erase and program would be ignored. Lofi's
  read-back check fails, it does not retry, and nothing else happens (writer described under XF-5 / HW-2). The
  visible symptom would be "Lofi forgets its settings at power-off". That is harmless, and a finding about the
  flash part.
- **When Lofi writes:**
  - On a normal power-off: `MainDelegate::handle_power_message` (`0xC2BAD5E0`) calls `settings_save` at
    `0xC2BAD7B8`, which writes only if a setting changed since the last load or save.
  - Immediately, on SYSTEM MENU > RESET (`DialogFactoryReset`'s action `0xC2CACD60` calls
    `settings_reset_and_save`).

  Removing the batteries or USB power without a normal power-off saves nothing.

## What to expect

**First Lofi boot.** Both relocated sectors are erased, so `settings_load` finds no tag. Its result is ignored
(`0xC2BACA38`), and `g_settings` stays as zero-filled RAM (`init_data`: all 101 words 0) after the range clamps. This is
how any Lofi-12 XT with erased settings sectors boots. It is **not** Lofi's factory default; RESET in step 6
writes that. Predicted (static; labels are inference from the manual's option order, as in C3):

| Lofi-12 XT setting | Stored | Predicted display | After RESET (validator fallbacks; `settings_set_defaults` stores the same channel and note values) |
| --- | --- | --- | --- |
| AUTO POWER OFF | 0 | Off | Off |
| MIDI OUT TO | 0 | off (C3: 0 = off) | value 3 |
| MIDI IN FROM | 0 | first option | value 3 |
| PROJECT / AUTO / PC CHANNEL | 0 / 0 / 0 | 1 / 1 / 1 | 14 / 16 / 15 |
| Track MIDI channels | all 0 | all channel 1 | track n = channel n |
| PAD CH | 0 | channel 1 | OFF |
| P-COUNT | clamped | 4 | 4 |
| PAD VELOCITY | clamped | LINEAR | LINEAR |
| TEMPO LED | 0 | off | on |
| Pad note map | all 0 | every pad note 0 | 36, 38, 47, 39, 58, 42, 46, 49 |
| Unlabelled word +0x110 | 0 | perhaps a level; recording may be near-silent | 100 |

Coincidence to keep in mind: SmplTrek's own PROJECT / AUTO / PC CHANNEL on this unit is also 14 / 16 / 15. After
the restore, check them on the SmplTrek side; they don't distinguish anything under Lofi.

## Before the session

Device state at start (expected): BOOT 1.0.17, PRESET 2.0.22, SYSTEM 3.2.174, MCU 1.0.6. Known deviations from
stock: none (C3 ended on official 3.2.174, 2026-11-11).

Cards:
- **Card A (test):** the C4 file only, as `SmplTrek.bin`, from a blank card (Lofi may create its own folders).
  Record its SHA-256 here, check it on the card, and keep `check_relocated_lofi.py`'s PASS output with it.
- **Card B (recovery):** official 3.2.174 `SmplTrek.bin`, SHA-256
  `3b6848b0f041bcf23c73d4b0357d2f3d6dc9e7e03752b32ff7322e91e6814e53`.

Power: mains USB charger or fresh batteries, never a computer. Headphones off your ears and all volumes at minimum
before the first Lofi boot.

## Settings to note before flashing (SmplTrek, step 1)

| SmplTrek setting | Where | Value before | Value after restore |
| --- | --- | --- | --- |
| AUTO POWER OFF | SYSTEM | | |
| BATTERY TYPE | SYSTEM | | |
| QUANTIZE | SYSTEM | | |
| TEMPO LED | SYSTEM | | |
| PAD VELOCITY | SYSTEM | | |
| INPUT FROM / OUTPUT TO | MIDI CONFIG | | |
| PROJECT / AUTO / PC CHANNEL | MIDI | | |

These must all be unchanged at step 11. Any change means something wrote SmplTrek's sectors.

## Steps

| # | Action | Expected outcome | If different |
| --- | --- | --- | --- |
| 1 | Power on normally. SYSTEM INFO (photograph). Fill in "Value before". Power off. | BOOT 1.0.17, PRESET 2.0.22, SYSTEM 3.2.174, MCU 1.0.6 | Stop; don't flash. |
| 2 | Card A in. HOME + power → BOOT MODE → SYSTEM UPDATE. Photograph the confirmation. | `SYSTEM:` `V3.2.174 -> V1.5.205` only | Any other line: CLR, stop. "invalid": stop, check the build. |
| 3 | OK. Photograph the end screen. | Erasing / Writing / Verifying, `Update completed.` | Verifying fails: go to step 10 with card B. |
| 4 | Power off, card A out, cold boot. | Lofi start-up, then its main screen (as C3) | Blank or frozen for 60 s: film, power off, go to step 9. |
| 5a | **Button-map check.** Press **func + ■ stop** (SmplTrek labels). Leave with **CLR** only. | SYSTEM MENU opens | Note what opened instead, then try func + each key of the lower row and note which opens SYSTEM MENU. |
| 5b | Press **func + home (system)**. Look, don't select anything; leave with **CLR**. | PROJECT MENU opens (the map: this key is Lofi's PAD / project) | **SYSTEM MENU opens:** the map is wrong for this key. Lofi has dead code that would send func + this key to SYSTEM MENU (see below). Note it exactly. |
| 5c | Press **func + ▶ play**. Look only; leave with **CLR**. Don't press ▶ play, ● sampling or a pad while it's open (that starts sampling). | SAMPLING page opens (the map: this key is Lofi's ● REC / sampling) | Note what opened instead. |
| 6 | In SYSTEM MENU, read and photograph the first-boot values in the table above (AUTO POWER OFF, MIDI CONFIG, channels, TEMPO LED). Then **RESET → YES** (Lofi manual p. 166). | first-boot values as predicted; RESET returns to the main screen | Values different: just note them. RESET shows an error, hangs or restarts: note it exactly, power off, go to step 9. |
| 7 | Read the same settings again; photograph. Then change **one** setting to a distinctive value: **AUTO POWER OFF → 6 h** (6 h, so it can't switch the unit off during the session). Leave SYSTEM MENU. | after RESET: the "After RESET" column; then AUTO POWER OFF 6 h | Note any difference. |
| 8 | **Normal power-off** with the power switch (not by pulling power). Wait 5 s. Cold boot. SYSTEM MENU: read AUTO POWER OFF and one MIDI channel. | AUTO POWER OFF **6 h** is kept, and the RESET values are still there: Lofi saved to and reloaded from `0xFFF000` | **Back to Off and first-boot values:** the write or the read didn't take (possible protection on the top sectors; see the write review). Note it and continue; it isn't a hazard. |
| 9 | Power off. HOME + power. | BOOT MODE | If BOOT MODE doesn't appear after three tries: stop and report before anything else. |
| 10 | SYSTEM DIAG (photograph). Card B in → SYSTEM UPDATE → OK → end screen (photograph). | DIAG: all four `Checking... 100%, OK.` (PRESET included); `V1.5.205 -> V3.2.174`, `Update completed.` | DIAG NG on PRESET: record it exactly and continue with the restore (static says impossible; important finding). |
| 11 | Card B out, cold boot. SYSTEM INFO, SYSTEM DIAG (photographs). Fill in "Value after restore". | stock 3.2.174; DIAG all OK; every SmplTrek setting unchanged | A changed SmplTrek setting: record it, don't reset anything, report. |

**Why 5b and 5c (static, 2026-11-12).** Lofi's file-browser key handler (`AppFileSelect`, `0xC2C31908`) has a
func + key branch that would open AppSampleRecording on bit 22 and AppSystemMenu on bit 27. The map puts bit 22 at
▶ play (Lofi ● REC / sampling, agrees) and bit 27 at home (Lofi PAD / project, disagrees). The branch runs only if
`0xC2C31904` returns non-zero, and that function always returns 0, so it is dead code in Lofi. SmplTrek's handler
(`0xC15E11CC`) has the same block. There it runs without func, sends home → HomeModeController, project →
AppProjectMenu and mixer → AppMixer, and is gated by a real check (`0xC15E11A8`). So Lofi's copy was edited, then
disabled. Its targets carry little weight, but the disagreement on bit 27 is worth one key press. Step 5 opens pages
only; nothing is saved.

**Optional part B: do Lofi's settings survive a round trip?** This is the real point of relocation. It costs two
more writes, so it's a separate decision.

| # | Action | Expected outcome |
| --- | --- | --- |
| B1 | Card A in, HOME + power, SYSTEM UPDATE → `V3.2.174 -> V1.5.205` → OK. Power off, card out, cold boot. | Lofi boots |
| B2 | SYSTEM MENU: AUTO POWER OFF and channels. | still **6 h** and the RESET values: a SYSTEM update doesn't touch `0xFFE000`-`0xFFFFFF` |
| B3 | Power off. HOME + power, card B, restore 3.2.174, cold boot, SYSTEM INFO + DIAG + SmplTrek settings. | stock, all OK, settings unchanged |

## Stop rules

- **Authorised writes:** C4 at step 2 and 3.2.174 at step 10 (plus B1 and B3 if part B is approved). Under Lofi,
  only the RESET at step 6 and the setting change at step 7. CLR out of any other confirmation.
- **Never use these under Lofi:**
  - firmware update;
  - format;
  - card-reader mode;
  - a computer connection;
  - project save, sample save or any card write. Keep the card out from step 4 to step 9.
- **Power off immediately** on noise, smell or heat.
- **Abort and report** if HOME + power stops reaching BOOT MODE.
- Any screen text not covered above: record it exactly and don't improvise.

## What this cannot distinguish

- If step 8 shows the settings were not kept, that alone can't tell a refused write (block protection) from a failed
  read. The next A4-style dump of `0xFFE000` would settle it. That needs a separate, read-only session.
- A pass shows the paths exercised (RESET, one setting, power-off save). It doesn't show every Lofi setting
  round-trips.

## Evidence capture

Stills:
- SYSTEM INFO before;
- the C4 confirmation and end;
- step 5 (what func + ■ stop, func + home and func + ▶ play each opened);
- first-boot values;
- after-RESET values;
- step 8;
- DIAG under Lofi;
- the restore confirmation and end;
- SYSTEM INFO and DIAG after.

Quote screen text exactly.

## Results (filled in during/after)

| # | Observed | Matches expectation? | Evidence |
| --- | --- | --- | --- |
| | | | |

Claims to update afterwards:
- XF-15 (relocation works);
- XF-13 (first-boot values);
- INT-12 (if step 8 fails);
- the button map;
- `SAFETY.md`, which gains a row for app writes to `0xFFE000` / `0xFFF000`;
- `experiments/README.md`.
