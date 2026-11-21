# Session C5: sterilised CyDrums 1.1.84 on the SmplTrek, then back (planned 2026-11-12, run 2026-11-20)

> **Run 2026-11-20: passed, with deviations from the plan.** The CyDrums app was written, booted and ran,
> including with its own card content (not part of the plan); BOOT MODE was reached with it installed; stock
> 3.2.174 restored; SmplTrek settings unchanged. Operator report only: no photographs or film are recorded.
>
> **Results:** "Results" at the end of this file. The plan below is kept as written before the run.

**Test file** (built 2026-11-20): SHA-256 `da1b34acc92fbb80bb55ca6fde418ae00f708f96902e8883daa0bae6399f2f44`,
2,271,021 bytes, built locally from the specification with a scratch script on the repo's `sonicware_integrity`
and `patch_builder` modules (not in the repository; there is still no CyDrums builder here).
`check_sterilised_cydrums.py ... --decode` printed PASS: 13 bytes differ from the official file (entry
`0xACBF8`, family word, both CRCs; cmtd CRC `9fe3bb92`, mmtd CRC `0770811f`).

**Purpose.** Second foreign app on the unit, after Lofi-12 XT in C3. Does the CyDrums app boot and draw on SmplTrek
hardware, and does HOME + power still recover the unit? CyDrums differs from Lofi in one way that shapes this
session: it keeps its sounds on the card (`/CyDrums/System/SystemCore.bin`) and does almost nothing without them.

The image would be built like C3's, with the patch specified in
`docs/01-platform-map.md` ("The same patch fits CyDrums 1.1.84"). Before an image goes on card A, run
`python3 -B tools/patches/check_sterilised_cydrums.py firmware/cydrums/CyDrums_v1.1.84.zip <image> --decode`; it must
print PASS. Record the candidate SHA-256 it prints. Like C3, this session writes flash only through the two updates
(CyDrums in, 3.2.174 back).

## What the offline work says

- **Acceptance and loading.** As C3: family word 8 → 5, both CRCs resealed with the SmplTrek seeds. CyDrums
  loads into `0xC24318B8`-`0xC26CBC48`, clear of the bootloader (`0xC702xxxx`-`0xC70Bxxxx`). Normal boot does no
  CRC check. Expected confirmation: `SYSTEM: V3.2.174 -> V1.1.84`.
- **Hardware set-up.** Same GPIO pins and constant writes (XF-14), and the same interrupt routing, IER and cache
  configuration as SmplTrek (simulated: XF-7, platform map "Image layout").
- **Flash.** CyDrums reads only the settings sectors and the two headers (its device-1 readers are unreachable).
  It writes only through `settings_save`, which the patch disables (XF-5, XF-2).
- **Card (XF-16).**
  - **No card:** it starts on "NO CARD / INSERT CARD!" (AppNoCard).
  - **A card without `/CyDrums`:** it starts on "BLANK MEDIA! / DOWNLOAD FILES / FROM THE WEB." (AppNoSystemCore),
    the manual's QR page.
  - **Card writes, simulated:** on start-up, card insertion and that page, the only card calls are a mount and one
    `f_stat` of `SystemCore.bin` (`analysis/cydrums_card_check.py`). User actions, USB card-reader mode and
    other tasks are not covered.
- **Buttons.** Both start-up pages swallow every button, knob and pad. Whether func + system still opens SYSTEM
  MENU over them is not known. If it does, it is func + ■ stop on the SmplTrek panel
  (`docs/10-cross-flash-button-map.md`, CyDrums section).
- **Settings (XF-17).** CyDrums accepts SmplTrek's settings block and clamps it. Values it would show are listed
  below; nothing is saved back.
- **Not settled statically:** pad feel (CyDrums' pad processing is its own code; same thresholds), LED
  addressing, audio clocking, what the display shows beyond the two pages above.

## Settings likely to change (named before the session)

**On the SmplTrek after the restore: none expected.** The patch stops CyDrums from writing the settings sectors.
Note these SmplTrek values before flashing (step 1) and compare after (step 10): AUTO POWER OFF, BATTERY TYPE,
QUANTIZE, TEMPO LED, PAD VELOCITY, INPUT FROM / OUTPUT TO, PROJECT / AUTO / PC CHANNEL.

**Under CyDrums (only readable if SYSTEM MENU opens; static prediction from the A4 block, XF-17):**

| CyDrums setting | Predicted | CyDrums default |
|---|---|---|
| AUTO POWER OFF | 6 h | Off |
| MIDI OUT TO | off | (3) |
| PROJECT / AUTO / PC CHANNEL | 16 / 1 / 2 | 14 / 16 / 15 |
| per-track MIDI channels | one channel up | |
| MIDI NOTE MAP pad channel / notes | 1 / all 0 | 10 / 36, 38, 47, 39, 58, 42, 46, 49 |
| metronome volume | 3 | 10 |
| P-COUNT / PAD VELOCITY / TEMPO LED | 4 / index 128 / on | same |
| an unlabelled input-related word | 1 | 100 (may make inputs very quiet) |

## Before the session

- **Card A:** the CyDrums image (built locally from the specification) at the root, nothing else. Card B: stock 3.2.174, as in C3.
- **Optional card S (part B only):** a spare card, FAT32, empty, never the SmplTrek card or card A/B.
- **USB unplugged** for the whole session. Headphones off your ears until step 7. Volume at minimum.
- **Photos** of every screen named below.

## Steps (part A: no card under CyDrums)

| # | Action | Expected | If different |
|---|---|---|---|
| 1 | Power on normally. SYSTEM INFO (photograph); note the settings listed above. Power off. | BOOT 1.0.17, PRESET 2.0.22, SYSTEM 3.2.174, MCU 1.0.6 | Stop; don't flash. |
| 2 | Card A in. HOME + power → BOOT MODE → SYSTEM UPDATE. Photograph the confirmation. | `SYSTEM:` `V3.2.174 -> V1.1.84` only | Any other line: CLR, stop. "invalid": stop, check the build. |
| 3 | OK. Photograph the end screen. | Erasing / Writing / Verifying, `Update completed.` | Verifying fails: go to step 9 with card B. |
| 4 | Power off, **card A out**, cold boot. Watch 60 s; film it. | CyDrums start-up, then "NO CARD / INSERT CARD!" | Blank, frozen or restarting for 60 s: film, power off, go to step 8. A different screen: photograph it. |
| 5 | Press **func + ■ stop** once (CyDrums func + system). Then CLR. | probably nothing (the page ignores input); SYSTEM MENU if global shortcuts still work | **SYSTEM MENU opens:** photograph it, read the values in the table above without changing any, CLR out. |
| 6 | Press a few pads and turn a knob. | nothing on screen | Note any reaction. |
| 7 | Headphones at low volume near your ears: any noise? | silence | Hiss that rises, loud noise, smell, heat: power off at once, unplug, stop, report. |
| 8 | Power off. Cold boot once more without HOME, then power off. Then HOME + power. | same start-up; then BOOT MODE | BOOT MODE doesn't appear after three tries: stop and report before anything else. |
| 9 | SYSTEM DIAG (photograph). Card B in → SYSTEM UPDATE → OK → end screen (photograph). | DIAG all four OK (SYSTEM v1.1.84); `V1.1.84 -> V3.2.174`, `Update completed.` | Restore rejected: check card B's hash; if right and still rejected, stop and report. |
| 10 | Card B out, cold boot. SYSTEM INFO, SYSTEM DIAG (photographs), compare the settings with step 1. | stock 3.2.174, DIAG all OK, settings unchanged | A changed setting: record it, don't reset anything, report. |

## Optional part B: a blank card under CyDrums (separate decision)

Between steps 7 and 8, with CyDrums on "NO CARD": insert **card S**. Expected: the screen changes to "BLANK MEDIA!
/ DOWNLOAD FILES / FROM THE WEB." (the QR page). Photograph it, press nothing, wait 10 s, remove card S, check
whether "NO CARD" comes back. Then continue at step 8. Simulation says nothing is written to card S on this path;
afterwards, a listing of card S on a computer (should be unchanged, still empty) checks that.

Not in this session: a card prepared with the CyDrums folder. CyDrums would then load its sounds and run fully, and
it writes to its card in normal use (configs, projects, `filedb.bin`). That is a separate decision.

## Stop rules

- **Authorised writes:** CyDrums at step 2, 3.2.174 at step 9. Under CyDrums: none (no saves, no CARD menu, no
  firmware update, no format, no card-reader mode, no USB).
- **Card A and card B never go in while CyDrums runs.** The SmplTrek card never goes in at all.
- **Power off immediately** on noise, smell or heat.
- **Abort and report** if HOME + power stops reaching BOOT MODE.
- Any screen text not covered above: record it exactly and don't improvise.

## What this cannot distinguish

- A frozen screen at step 4 could be a CyDrums hang or a page that is simply waiting; the 60 s film and step 5's
  key press help, but cannot separate the two.
- Pads, audio and LEDs are barely exercised: without its card CyDrums offers no playable screen.

## Results (run 2026-11-20; operator report, given 2026-11-21)

Everything here is what the operator reported afterwards. No photographs or film are recorded, and steps not listed
were not reported.

**Deviations from the plan.**
- The card holding the test image stayed in for the first CyDrums boot (the plan removes card A at step 4 and its
  stop rules keep it out while CyDrums runs). So the first page seen was BLANK MEDIA, not NO CARD.
- The unit was then switched off, the CyDrums folder was copied onto that same card on a computer, and CyDrums was
  booted with it. The plan excluded a prepared card ("a separate decision"). CyDrums writes to its card in normal
  use; what it wrote to this one was not examined.

| # | Observed | Matches expectation? | Evidence |
|---|---|---|---|
| 1 | not reported | | |
| 2 | Confirmation read `V3.2.174 -> V1.1.84` | yes | operator report |
| 3 | Update completed (implied by the boot that followed; end screen not reported) | yes | operator report |
| 4 | With the card that held only the test image in: the "download files" page (BLANK MEDIA / DOWNLOAD FILES FROM THE WEB) | yes, for a card without `/CyDrums` (XF-16); NO CARD not observed | operator report |
| 5 | SYSTEM MENU over the start-up pages: not reported | | |
| 6, 7 | On the start-up page: not reported | | |
| extra | After copying the CyDrums folder to the card: CyDrums ran. Audio playback and editing worked; "nothing odd" apart from the button mapping, which is very different from the SmplTrek's labels | not predicted (outside the plan) | operator report |
| 8 | BOOT MODE reached with CyDrums installed | yes | operator report (implied by step 9) |
| 9 | SYSTEM DIAG "all expected results"; 3.2.174 restored | yes | operator report |
| 10 | Stock 3.2.174 runs; settings "fine after recovery" | yes | operator report |

**What this establishes (device, one unit, operator report).** A sterilised CyDrums 1.1.84 image is accepted,
written and booted by BOOT 1.0.17 on a SmplTrek; it runs with its card content, with working audio playback and
editing; HOME + power still reaches BOOT MODE; the stock restore works and SmplTrek's settings survive.

**Not established.** The NO CARD page; whether func + system opens SYSTEM MENU over the start-up pages; the
predicted settings values under CyDrums (XF-17); pad feel, LEDs, inputs and sampling in any detail; what CyDrums
wrote to the card; anything about CyDrums 2.0.97 beta, which has not run on a unit.
