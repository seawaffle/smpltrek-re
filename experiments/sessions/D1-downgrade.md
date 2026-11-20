# Session D1-downgrade: official downgrade 3.2.174 → 3.0.148, then back (planned and run 2026-11-11)

> **Run 2026-11-11, 21:29-21:33: passed.** 3.0.148 was written, booted and passed DIAG; 3.2.174 was restored from it.
>
> **Results:** "Results" at the end of this file; summary in `experiments/README.md`. (Not the same session as D1, the bare-metal image in `D1-hello.md`.)

**Purpose.**
- Prove on the device that an older SYSTEM image is written, verified and boots.
- Prove that the normal upgrade back to 3.2.174 works from it.

This separates the version question from the foreign-app question before C3, which writes Lofi-12 XT
1.5.205 (a lower version number *and* a foreign app). Until now a downgrade has only been *offered*
(W1, CLR pressed) and *predicted* from the code: claim INT-11 and `docs/05-bootloader.md` say SYSTEM
is written whatever its version. (This paragraph states the position before the run.) Both files are untouched official Sonicware releases.

## Before the session

Device state at start (expected): BOOT 1.0.17  PRESET 2.0.22  SYSTEM 3.2.174  MCU 1.0.6.
Check it on SYSTEM INFO before flashing and photograph it. If anything differs, stop and record it.

Known deviations from stock: none (restored to official 3.2.174 on 2026-11-11, operator report).

Recovery card prepared: official 3.2.174 `SmplTrek.bin`, SHA-256 `3b6848b0f041bcf23c73d4b0357d2f3d6dc9e7e03752b32ff7322e91e6814e53`.
Check the hash on the card before the session (`sha256sum`).

Second card: the same recovery file. The test card also holds it later (step 7); a separate card means a
dead test card can't block recovery.

## Files on the card (as SmplTrek.bin, one at a time)

| File | SHA-256 | What it is |
| --- | --- | --- |
| `firmware/smpltrek/SmplTrek v3.0.148.zip` → `SmplTrek v3.0.148/SmplTrek.bin` | `098bdaccd0c9c3276d121238d2876570e0f1e8613b34309c36f182bfb8fb47ba` | official 3.0.148, one SYSTEM section (kind 3) 3.0.148, every CRC valid (`tools/sonicware_integrity.py verify`) |
| `firmware/smpltrek/SmplTrek v3.2.174.zip` → `SmplTrek v3.2.174/SmplTrek.bin` | `3b6848b0f041bcf23c73d4b0357d2f3d6dc9e7e03752b32ff7322e91e6814e53` | official 3.2.174, the restore target |

## Offline checks done before writing this plan (2026-11-11, static)

- **Bootloader** (`docs/05-bootloader.md`): a SYSTEM section is always written, with no version
  comparison. The file has no PRESET, BOOT or MCU section, so only flash 0x40000..0x440000 is erased and
  written. The install marker is programmed only after the post-write CRC check passes.
- **Settings.** In 3.0.148, `settings_load` and `settings_pref_fill` are identical code to 3.2.174 (region
  diff: only moved data addresses). Both copy the same 284-byte 'PREF' block.
  - `settings_validate` was rebuilt between the versions. 3.2.174 clamps an extra group of fields
    (limits 50..70 that 3.0.148's validator lacks), and the two differ in other constants.
  - So 3.0.148 will read 3.2.174's settings, clamp the fields it knows, and leave bytes it doesn't validate
    as they are (inference: the copy is whole-block).
  - PREX handling (`settings_prex_fill`) also differs, so the USB AUDIO / EXT SRC track settings may come
    up changed or defaulted.
  - Worst expected effect: some settings look different under 3.0.148, or after returning to 3.2.174.
    This is not a boot risk: settings are app data, and the bootloader never reads them.
- **Content.** 3.0.148 shipped without a PRESET section and required a unit already on 2.0 (Sonicware's
  note). The installed PRESET is 2.0.22, so content matches what 3.0.148 expects.

## Steps

| # | Action | Expected outcome | If different |
| --- | --- | --- | --- |
| 1 | Power on normally; open SYSTEM INFO. Photograph. | BOOT 1.0.17, PRESET 2.0.22, SYSTEM 3.2.174, MCU 1.0.6 | Stop; record; do not flash. |
| 2 | Copy 3.0.148 to the card root as `SmplTrek.bin` and check its hash on the card. Power off. | hash `098bdacc…bfb47ba` | Re-copy; never flash a file whose hash is not checked. |
| 3 | Hold HOME and power on → BOOT MODE → SYSTEM UPDATE. Photograph each screen. | "Checking... 100%, OK", then a confirmation listing only `SYSTEM: V3.2.174 -> V3.0.148`, then the Yes/No prompt | **Rejected or "invalid":** the bootloader enforces version order after all, so the static reading (INT-11) is wrong; press nothing, record, stop. C3 then needs rethinking. **Lists PRESET, BOOT or MCU:** stop with CLR (the file has none, so that would be a parse surprise). |
| 4 | Press OK. Photograph or film Erasing / Writing / Verifying and the end screen. | progress to "100%, OK" and "Update completed" | **"Update failed" or NG:** do not power-cycle for a different try. Re-enter SYSTEM UPDATE with the 3.2.174 card (step 7); record the exact text. |
| 5 | Power off, then cold boot normally (no HOME). | the app starts; SYSTEM INFO shows SYSTEM 3.0.148, BOOT 1.0.17, PRESET 2.0.22, MCU 1.0.6. Photograph SYSTEM INFO. | **No app (blank or hang, or straight to BOOT MODE):** record what's shown; then HOME + power → restore 3.2.174 (step 7). That would be the first observation of a failed normal boot (an open bootloader item). |
| 6 | Under 3.0.148: run SYSTEM DIAG (photograph the result); press a few pads and play a project or sample; open the SD browser. Note any settings that look different (MIDI channels, input settings, auto power off). | DIAG all OK; pads, audio and SD normal; settings possibly changed (see offline checks) | **DIAG NG on SYSTEM:** record which line; restore (step 7). Odd settings alone are not a failure; just write them down. |
| 7 | Copy 3.2.174 to the card as `SmplTrek.bin` and check its hash. HOME + power → SYSTEM UPDATE. Photograph the confirmation, press OK, photograph the end screen. | confirmation `SYSTEM: V3.0.148 -> V3.2.174`, then "100%, OK" / "Update completed" | **Rejected:** use the second card; if that also fails, stop and report. Nothing else is written. |
| 8 | Cold boot; SYSTEM INFO (photograph); SYSTEM DIAG (photograph); quick pad, playback and SD check; compare the settings noted in step 6. | back to BOOT 1.0.17, PRESET 2.0.22, SYSTEM 3.2.174, MCU 1.0.6; DIAG OK | Record any settings that didn't come back. If the unit misbehaves, a settings reset is the next step (not part of this plan; ask first). |

**What this cannot distinguish.**
- A successful step 5 shows that a lower SYSTEM version is written and boots. It doesn't separate "no
  version check at all" from "a check that allows downgrades"; only the code reading (INT-11) says which.
- It says nothing about foreign load addresses or foreign apps (C3).
- A blank screen at step 5 can't by itself tell a refused install from an app that fails early. The
  step 5 photo, plus whether HOME still reaches BOOT MODE, narrows it down.

## Stop rules

- Writes authorised in this plan: exactly two SYSTEM updates, 3.0.148 at step 4 and 3.2.174 at step 7.
  Nothing else; CLR out of any other confirmation screen.
- Abort if the confirmation lists any section other than SYSTEM, or if any screen shows text not
  covered above. Record the text exactly, and don't improvise a third write.
- Abort if HOME + power stops reaching BOOT MODE at any point. That would be a recovery-path failure;
  report it before doing anything else.

## Evidence capture

Video per screen where possible. Stills (not published) of SYSTEM INFO before, confirmation,
end of update, SYSTEM INFO under 3.0.148, DIAG under 3.0.148, confirmation and end of the restore,
SYSTEM INFO and DIAG after). Quote screen text exactly in the results.

## Results (filled in during/after)

Run by the operator on 2026-11-11, about 21:29-21:33 (photo timestamps). The operator's report: "full run
through done. flashed 3.0.148, tested, flashed back to 3.2.174". Four photos were taken. They keep their
camera names rather than the `D1_<seq>` names planned above. Rows without a photo rest on the operator's
report alone and say so.

| # | Observed | Matches expectation? | Evidence (photo/video/ref) |
| --- | --- | --- | --- |
| 1 | Not photographed. The device was on stock 3.2.174 from the A4 restore earlier the same day. | presumably | operator report; ledger step 5 |
| 2 | Not recorded separately. | — | operator report |
| 3 | Confirmation listed only the SYSTEM line (operator, not photographed). The update was accepted: step 5 shows 3.0.148 installed. | yes | operator report; indirect: photo |
| 4 | Written; end screen not photographed. | yes | indirect: photo |
| 5 | The app boots. SYSTEM INFO: `BOOT 1.0.17`, `PRESET 2.0.22`, `SYSTEM 3.0.148`, `MCU 1.0.6`. | yes | photo |
| 6 | BOOT MODE SYSTEM DIAGNOSTICS under 3.0.148: `>> BOOT : v1.0.17`, `>> MCU : v1.0.6`, `>> PRESET : v2.0.22`, `>> SYSTEM : v3.0.148`, each `Checking... 100%, OK.` Operator: "tested". No settings change noticed, but not every setting was checked (operator, asked afterwards; the plan did not list which settings to look at). | yes | photo; operator report |
| 7 | `$ systemupdate` / `Check the firmware file.` / `Checking... 100%, OK.` / `SYSTEM:` / `V3.0.148 -> V3.2.174` / `Are you sure?` / `[CLR] : No / [OK] : Yes`. OK pressed; end screen not photographed. | yes | photo |
| 8 | SYSTEM INFO: `BOOT 1.0.17`, `PRESET 2.0.22`, `SYSTEM 3.2.174`, `MCU 1.0.6`. DIAG after the restore not photographed. | yes | photo |

Device state at end: BOOT 1.0.17  PRESET 2.0.22  SYSTEM 3.2.174  MCU 1.0.6 (photo, 21:33).

**What this establishes (observed on the device).**
- An official older SYSTEM image (3.0.148) is accepted, written and verified, and it boots on a unit
  whose other images are BOOT 1.0.17, PRESET 2.0.22 and MCU 1.0.6.
- The bootloader's own diagnostics then check the installed 3.0.148 image as OK.
- An upgrade back to 3.2.174 from it works, so the recovery path is now proven from a lower version as
  well as from the same version (A3).
- Nothing other than SYSTEM changed (BOOT, PRESET and MCU versions are identical before and after),
  as expected for a file with only a SYSTEM section.

**Gaps.**
- No photo of the downgrade confirmation screen; "only SYSTEM listed" rests on the operator's report and the
  unchanged BOOT/PRESET/MCU versions.
- No photo of either end screen, or of DIAG after the restore.
- Settings: no change noticed, but no specific list was checked, so this does not test the
  `settings_validate` / PREX differences found offline. Future plans should name the settings to look at
  before the session.

Claims updated: INT-11 (the SYSTEM-always-written half is now observed for a downgrade); the ledger in `experiments/README.md`.
