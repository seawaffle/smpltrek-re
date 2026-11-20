# Session D0: a system image that hangs at boot, then HOME + power (planned and run 2026-11-12)

> **Run 2026-11-12: passed.** The hang image was written; the unit froze on the bootloader's logo; HOME + power reached BOOT MODE; stock 3.2.174 restored.
>
> **Results:** "Results" in this file; summary in `experiments/README.md`.

**Purpose.** The recovery story every later step rests on is "HOME held at power-on reaches BOOT MODE whatever
the SYSTEM image does". It was read from the bootloader's code (`docs/05-bootloader.md`, "Power-on
decision": HOME is tested before the SYSTEM image is loaded) and every restore before D0 had worked, but every
one had started from an app that booted (`SAFETY.md`, "Not known"). D0 flashes an image whose
application never runs anything but a branch to itself, and checks that the unit still recovers. It gates D1 (the first bare-metal
image), which will hang at some point.

**Status: run 2026-11-12, passed.** The hang image was written and booted into; the unit stayed on, frozen on the
SONICWARE logo the bootloader draws, and the power key did nothing (outcome A at step 6); the adapter was pulled;
HOME + power reached BOOT MODE; DIAG read SYSTEM v0.0.1 OK; official 3.2.174 restored and runs. Results below.

**What it added beyond the pass (2026-11-12).** On a normal boot the bootloader initialises the OLED and draws the
SONICWARE logo before it jumps into SYSTEM, so that splash is the bootloader's, not the app's; and its
`power_on_check` latches the power hold GP4[11], since the unit stayed on for minutes with a SYSTEM that executes
one instruction. A hung app therefore leaves the unit on, showing that logo, with the power key dead; removing the
supply is the only way off. For D1 this means the skeleton's first frame replaces a logo, not a dark screen, and
its `oled_init` re-initialises a running panel, as the stock app's does.

## The test file

`experiments/D0_hang_0.0.1.bin`, 16,432 bytes, SHA-256
`68a14455547c1cc8faf133bdf51391a841abe7b5d4dbc83a8ac223e31a608bf1`, built by a deterministic script (not
published). **It contains no Sonicware code**: a `cmtd` container
(family 5, one SYSTEM descriptor, version 0.0.1) around a 16 KiB `mmtd` image (version 0.0.1, entry
`0xC2000000`, one section at `0xC2000000`) whose code is

    c2000000:  00000012   b .S2 c2000000      ; branch to itself
    c2000004:  00008000   nop 5
    (the rest of the section is NOP words)

Both CRCs are sealed with SmplTrek seeds; `tools/sonicware_integrity.py verify --profile smpltrek` reports
2/2 OK. Why 16 KiB: the updater's post-write check CRCs the first 4 KiB of flash as a block before continuing
over the declared size; a shorter image would exercise a path no official file has. Why version 0.0.1: the
confirmation screen will read `SYSTEM: V3.2.174 -> V0.0.1`, unmistakable. Why `0xC2000000`: DDR, far from the
bootloader's own `0xC7020000`-`0xC70B0000`.

Check before it went on a card: `sha256sum` on the card matched the hash above.

## What the offline work says (static unless marked)

- **Acceptance.** The file check is magic, size, outer CRC, family word and descriptor kinds; SYSTEM always counts,
  whatever its version (device: D1 downgrade). Expected confirmation: `SYSTEM: V3.2.174 -> V0.0.1`.
- **Writing.** 4 MiB erased from `0x40000`, the image written, re-read and CRC-checked, then the install marker
  programmed (`05-bootloader.md`, "Writing"). Verifying OK means the marker is set and normal boot will jump in.
- **Normal boot.** Reads the header, requires `mmtd` and the marker, copies the one section to `0xC2000000`,
  branches to it. No CRC. The branch lands on the self-loop; nothing else ever runs.
- **HOME.** Tested by the bootloader from the C6748's own GPIO key matrix before the SYSTEM image is read
  (INT-8). C3 reached BOOT MODE with a foreign app installed, but that app booted, so D0 is the first time this
  ordering is the only thing standing between the unit and no recovery path.
- **Power.** The bootloader runs `power_on_check` itself; the app's version of that function drives the
  power-hold pin GP4[11] once the key has been held about half a second (`01-platform-map.md`, "Power
  management"). Whether the bootloader's copy drives the pin is **open** (answered by the run: it latches the hold before the jump, HW-24). Two outcomes are therefore possible
  at step 6 and both are pre-registered: the unit stays on with a hung app, or it switches off when the key is
  released. Either way: **a hung app has no power-off path.** The key is read by the app, which is not running.
  So the session runs **on the AC adapter with no batteries fitted**, and unplugging the adapter is the
  off switch. Nothing is writing flash at that moment (the image has no code), so cutting power is safe.
- **Screen.** Not predictable. The stock app initialises the OLED itself; whether the bootloader draws
  anything on a normal boot is not traced. Dark, or frozen on whatever the bootloader last drew, are both
  consistent with success. Any SmplTrek UI is not.
- **Flash.** This session writes flash exactly twice, both through the bootloader: the D0 image and the restore.
  The hung image never writes anything. Settings, content and the bootloader are untouched.

**The risk, stated plainly.** If HOME + power does not reach BOOT MODE at step 8, the unit has no software
recovery path: the bootloader is the only updater, and the hardware route (opening the
unit) is out of scope. The static evidence that this cannot happen is specific (the HOME test precedes the load) and
was confirmed in the same code path by C3, so the probability is judged low. But D0 exists precisely because
"judged low" is not "observed".

Device state at start: BOOT 1.0.17  PRESET 2.0.22  SYSTEM 3.2.174  MCU 1.0.6 (confirm on SYSTEM INFO in step 1)
Known deviations from stock: none expected (the last sessions ended on official 3.2.174)
Recovery card prepared: card B, official `SmplTrek.bin` 3.2.174, SHA-256
`3b6848b0f041bcf23c73d4b0357d2f3d6dc9e7e03752b32ff7322e91e6814e53`, verified on the card
Second card: card A carries the D0 file as `SmplTrek.bin`

## Files on the cards (each as `SmplTrek.bin` in the root)

| Card | File | SHA-256 | What it is |
| --- | --- | --- | --- |
| A | `experiments/D0_hang_0.0.1.bin` | `68a14455547c1cc8faf133bdf51391a841abe7b5d4dbc83a8ac223e31a608bf1` | the hang image, no Sonicware code |
| B | official 3.2.174 `SmplTrek.bin` | `3b6848b0f041bcf23c73d4b0357d2f3d6dc9e7e03752b32ff7322e91e6814e53` | the restore |

## Before the session

- Verify both hashes on the cards (not in `experiments/`), and confirm card A's file is the current build.
- Remove the batteries. Use the AC adapter only. Have the camera ready for continuous video from step 3.
- Headphones off, volume at minimum (the hang image makes no sound, but the restore boots the stock app).

## Steps

| # | Action | Expected outcome | If different |
| --- | --- | --- | --- |
| 1 | Power on normally. SYSTEM MENU > SYSTEM INFO; photograph it. Power off with the key. | BOOT 1.0.17, PRESET 2.0.22, SYSTEM 3.2.174, MCU 1.0.6 | Different SYSTEM version: stop; the plan assumes 3.2.174 installed. |
| 2 | Card A in. Hold HOME, press power. | BOOT MODE menu | No BOOT MODE: release, retry holding HOME first. Still none: stop and report (that would be a problem before any write). |
| 3 | SYSTEM UPDATE. Read the check result and the confirmation screen; photograph it. | `Checking... 100%, OK.` then `SYSTEM: V3.2.174 -> V0.0.1`, `Are you sure?` | Any other version line, "invalid", or a PRESET/BOOT line: **CLR**, stop, report. Nothing was written. |
| 4 | **OK.** Video the whole write. | `Erasing... Writing... Verifying... 100%, OK.`, then the restart prompt | **Verifying fails:** the marker is not set and normal boot will refuse the image rather than hang. Continue with steps 5 to 8 anyway (they still test recovery), and record it: it would say the 16 KiB image hit a size path the official files do not. |
| 5 | Power off as the bootloader's prompt says (as in C3 step 9 / D1). Card A out. | unit off | Unit won't switch off: unplug the adapter. Record it. |
| 6 | **Video running.** Press power normally (no HOME) and hold it about one second, then release. Watch for 60 s. | **Outcome A (expected):** the unit stays on, the screen is dark or frozen on a bootloader frame, no SmplTrek logo or UI appears, LEDs idle. **Outcome B:** the unit switches off when the key is released (the bootloader does not latch the power hold). Both are a successful hang. | **SmplTrek UI appears:** the image was not installed or not jumped into. Record and go to step 8; the restore is then a no-op check. Anything drawing or animating: record exactly. |
| 7 | After 60 s: unplug the adapter (outcome A), or nothing (outcome B). Wait 5 s, plug it back in. | unit off, then off | Unit does not go off with the adapter out: it is on batteries; remove them. |
| 8 | **Hold HOME, press power.** Video. | **BOOT MODE menu appears.** This is the result the session exists for. | **No BOOT MODE within 10 s:** release everything, unplug, replug, retry twice more holding HOME firmly *before* pressing power and keeping both held 3 s. **Still none: stop. Do not try other buttons, cards or power sources on a hunch. Report with the video.** |
| 9 | SYSTEM DIAG; photograph. | BOOT OK, PRESET OK, SYSTEM OK (the CRC of the hang image), MCU 1.0.6 | SYSTEM NG: record; continue to the restore. Anything else NG: record and continue. |
| 10 | Card B in → SYSTEM UPDATE → read the confirmation → OK → video the write → power off → card out → power on normally. | `SYSTEM: V0.0.1 -> V3.2.174`; Verifying OK; the stock SmplTrek boots to its UI | Restore refused or Verifying fails: CLR / record, retry once with card B re-verified on a computer. Still failing: stop and report. |
| 11 | SYSTEM INFO and SYSTEM DIAG; photograph. Play a pad; open a project. | BOOT 1.0.17, PRESET 2.0.22, SYSTEM 3.2.174, MCU 1.0.6; DIAG all OK; settings as before | A changed setting: record it (nothing in this session should have written the settings sectors). |

## What this cannot distinguish

- **Outcome A versus a crash.** A dark screen does not tell a tight loop from an exception or a reset loop
  inside the DDR; the image's one instruction makes the loop by far the likeliest, and step 9's SYSTEM OK shows
  the image is intact. For the purpose of D0 it does not matter: anything that is not BOOT MODE is "the app
  did not help".
- **Outcome B versus a brown-out.** If the unit switches off at key release, that says the bootloader's
  `power_on_check` did not latch GP4[11], or latched it and something released it. D1's skeleton will drive
  the pin itself either way; the distinction is recorded, not resolved, here.
- **Step 8 passing** shows HOME recovery with a hung app on *this* bootloader, 1.0.17. It says nothing about
  other bootloader versions.

## Stop rules

- **Exactly two writes are authorised:** the D0 image at step 4 and official 3.2.174 at step 10. CLR out of
  any other confirmation screen.
- **Never** press OK on a confirmation screen whose version line is not the one written in the step.
- **Abort and report** if step 8 fails after three attempts. Do not improvise.
- **Power off immediately** (unplug) on noise, smell or heat.
- No batteries in the unit at any point in this session.

## Evidence capture

Video for steps 4, 6, 8 and 10. Stills (not published), referenced from the results:
SYSTEM INFO before; the D0 confirmation and the end of its write; the screen during step 6 (even if dark);
BOOT MODE at step 8; DIAG at step 9; the restore confirmation and end; SYSTEM INFO and DIAG after. Quote screen
text exactly.

## Results (filled in during/after)

| # | Observed | Matches expectation? | Evidence (photo/video/ref) |
| --- | --- | --- | --- |
| 1 | Not photographed separately; the stock 3.2.174 was running before the session (the step 3 confirmation names V3.2.174 as the installed version). | yes | step 3 photo |
| 2 | BOOT MODE reached (the update in step 3 ran from it). | yes | operator's report |
| 3 | `Check the firmware file. Checking... 100%, OK. SYSTEM: v3.2.174 -> v0.0.1 Are you sure? [CLR]:No / [OK]:Yes` | yes | photo |
| 4 | `>> SYSTEM Erasing... 23%` photographed; the write completed (the image was jumped into at step 6 and read OK at step 9). | yes | photo; no video |
| 5 | Powered off, card A out. | yes | operator's report |
| 6 | **Outcome A.** The unit stayed on, frozen on the SONICWARE logo the bootloader draws at power-on; no SmplTrek UI; the power key had no effect (no reboot, no power-off). | yes (outcome A) | operator's report; no photo |
| 7 | Adapter pulled; unit off. | yes | operator's report |
| 8 | HOME + power: BOOT MODE menu. No retries reported. | **yes** | operator's report; the step 9 photo is from that BOOT MODE |
| 9 | `BOOT: v1.0.17 OK, MCU: v1.0.6 OK, PRESET: v2.0.22 OK, SYSTEM: v0.0.1 Checking... 100%, OK.` | yes | photo |
| 10 | `SYSTEM: v0.0.1 -> v3.2.174`, `Erasing... 100%, done. Writing... 100%, done. Verifying... 42%` photographed; completed; the stock SmplTrek booted. | yes | photo; no video |
| 11 | SYSTEM INFO: BOOT 1.0.17, PRESET 2.0.22, SYSTEM 3.2.174, MCU 1.0.6. Operator reports the unit working correctly afterwards. DIAG after the restore not photographed. | yes | photo |

Device state at end: BOOT 1.0.17  PRESET 2.0.22  SYSTEM 3.2.174  MCU 1.0.6 (photo)
Claims updated 2026-11-12: SAFETY.md row "A SYSTEM image that hangs at boot" is device-observed; INT-8 (HOME
recovery regardless of app state) observed-device; HW-24 added (bootloader draws the logo and latches the power
hold before the jump); HW-8 and XF-8 notes answer the power-hold question (latched by the bootloader). D1 unblocked.
