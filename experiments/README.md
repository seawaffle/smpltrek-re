# Device log

Records of every run on one SmplTrek, in date order: official and modified updates, cross-flashes, and bare-metal
test images run from the SD card, each with its file hash, the protocol and what was seen. `sessions/` holds the
pre-registered plans and results of the later sessions. The test images themselves and their sources are not
published; only official files and files derived from them with the tools in `tools/` are named here, and those are
regenerated locally (`experiments/*.bin` is git-ignored). Photographs taken at the bench are not published either.
"Operator report" below means a verbal report from the person at the bench, with no photograph.

Integrity fields are IEEE CRC-32 with per-product seeds (`docs/12-update-container.md`, verified
independently 2026-11-08; `tools/sonicware_integrity.py`). The unit was factory-fresh at the
start (2026-11-08): BOOT 1.0.17, MCU 1.0.6, PRESET 1.0.11, SYSTEM 1.0.65, never updated. You need an SD
card (the unit has none); the update guide only requires the `.bin` at the card root. Every result in
this file is from that one unit and that one bootloader version.

## Sessions

Every write to the unit was a BOOT MODE > SYSTEM UPDATE from the card. "Pre-write" means the file was read and
the confirmation screen reached, then CLR pressed: nothing written.

| Code | Date | What was run | Outcome | Record |
|---|---|---|---|---|
| Run 1 | 2026-11-08 | official 2.0.129 over factory 1.0.65 (PRESET 1.0.11 → 2.0.22) | written, boots | [Run 1 result](#run-1-result-nov-8-2026) |
| Run 2 | 2026-11-08 | official 3.2.174 with the `SYSTEM INFO` label patched to `CUSTOM INFO`, resealed | written, boots, label shows: patch → reseal → flash works | [Run 2 result](#run-2-result-nov-8-2026-accepted) |
| USB | 2026-11-08, 11-09 | USB host check in BOOT MODE and under 3.2.174 | no USB device in BOOT MODE; the app exposes audio and MIDI | [USB check](#usb-check-result-nov-8-2026), [USB MIDI](#usb-midi-result-nov-9-2026-modified-32174-running-no-flashing) |
| Step 1 | 2026-11-09 | smoke test and SYSTEM DIAG on the modified 3.2.174 | normal; DIAG accepts the resealed image | [Step 1](#step-1-result-2026-11-09-modified-32174-installed-nothing-flashed) |
| C1 | 2026-11-09 | pre-write: one bit flipped in the outer (cmtd) CRC | rejected: outer CRC enforced | [Step 2](#step-2-results-2026-11-09-pre-write-probes-clr-never-needed-where-rejected) |
| C2 | 2026-11-09 | pre-write: inner (mmtd) CRC wrong, outer resealed | reaches confirmation: inner CRC not checked before it | [Step 2](#step-2-results-2026-11-09-pre-write-probes-clr-never-needed-where-rejected) |
| A1 | — | pre-write: 2.0.129 with one byte changed, CRCs stale | optional, not run | [probe table](#pre-write-safety-probes-run-2026-11-09) |
| A2a, A2b | 2026-11-09 | pre-write: family word 12, SmplTrek / Lofi-12 XT seeds | both rejected: family word checked against the device | [Step 2](#step-2-results-2026-11-09-pre-write-probes-clr-never-needed-where-rejected) |
| A3 | 2026-11-09 | official 3.2.174 over the modified 3.2.174 | passed: stock restored | [Step 3](#step-3-result-a3-same-version-restore-2026-11-09-passed) |
| W1 | 2026-11-09 | pre-write: Lofi-12 XT 1.5.205 wrapped as family 5, SmplTrek seeds | reaches confirmation `V3.2.174 -> V1.5.205`: acceptance is family word + outer CRC only | [W1](#cross-flash-pre-write-probes-w1-run-2026-11-09) |
| S2 pass-through | 2026-11-09 | 3.2.174 with an appended section and a vtable hook that only passes through | SYSTEM INFO opens, DIAG OK (negative control only) | [S2](#session-s2-pass-through-result-2026-11-09) |
| S2 hello | 2026-11-10 | the hook draws a text line at (10,34) | text drawn, partly behind the logo: the appended code runs | [S2 drawing](#session-s2-drawing-result-2026-11-10) |
| S2 layout v2 | 2026-11-11 | the same, text at (10,116) | text readable; repeated cold boots | [S2 ledger](#s2-results-ledger-2026-11-09-to-2026-11-11) |
| S2 restore | 2026-11-11 | official 3.2.174 | stock restored, DIAG OK | [S2 ledger](#s2-results-ledger-2026-11-09-to-2026-11-11) |
| A4 rev. 1 | 2026-11-11 | flash-dump probe on the S2 hook | dump path works; read device 1, stopped at 5 MiB on `A4 READ DIFF` | [A4](#revision-1-result-2026-11-11-the-dump-path-works-but-it-read-device-1) |
| A4 rev. 2 | 2026-11-11 | the dump probe with device selection | two identical 32 MiB dumps; then 3.2.174 restored | [A4](#revision-2-built-and-run-2026-11-11) |
| D1-downgrade | 2026-11-11 | official 3.0.148 over 3.2.174, then 3.2.174 back | passed: older SYSTEM written, boots, DIAG OK; upgrade back works | [sessions/D1-downgrade.md](sessions/D1-downgrade.md) |
| C3 | 2026-11-11 | Lofi-12 XT 1.5.205 with its settings writer stubbed, as family 5, then 3.2.174 back | passed: foreign app written, boots, runs; BOOT MODE reached; settings unchanged | [sessions/C3-crossflash.md](sessions/C3-crossflash.md) |
| C5 | 2026-11-20 | CyDrums 1.1.84 with its settings writer stubbed, as family 5, then 3.2.174 back | passed, with deviations (test card left in; then run with the CyDrums folder on it): foreign app written, boots, runs with audio; BOOT MODE reached; settings unchanged. Operator report, no photographs | [sessions/C5-crossflash-cydrums.md](sessions/C5-crossflash-cydrums.md) |
| D0 | 2026-11-12 | a SYSTEM image that branches to itself, then 3.2.174 back | passed: HOME + power reaches BOOT MODE with an app that never runs | [sessions/D0-hang-recovery.md](sessions/D0-hang-recovery.md) |
| D1 run 1 | 2026-11-13 | bare-metal image 0.2.3 | hung on the logo before its first frame; stock restored | [sessions/D1-hello.md](sessions/D1-hello.md) |
| D1 run 2 | 2026-11-13 | 0.2.4 | switched itself off, fault 3: SPI1 never transferred (SPIPC0 unwritten) | [sessions/D1-hello.md](sessions/D1-hello.md) |
| D1 run 3 | 2026-11-13 | 0.2.5 | runs to the status page, loads the app from the card; pixel pairs swapped; nothing from the panel MCU | [sessions/D1-hello.md](sessions/D1-hello.md) |
| D1 run 4 | 2026-11-13 | 0.2.6 | UART1 transmit reaches the MCU (LEDs); text still unreadable | [sessions/D1-hello.md](sessions/D1-hello.md) |
| D1 run 5 | 2026-11-13 | 0.2.7 | test pattern gives the panel's pixel order (HW-35); MCU silent | [sessions/D1-hello.md](sessions/D1-hello.md) |
| D1 run 6 | 2026-11-13 | 0.2.8 | display correct; UART1 receives nothing | [sessions/D1-hello.md](sessions/D1-hello.md) |
| D1 run 7 | 2026-11-14 | 0.2.9 | MCU link works both ways (HW-46); every input works; 0.2.9 left installed | [sessions/D1-hello.md](sessions/D1-hello.md) |
| M1 | 2026-11-16 | bench image 0.3.1: audio path (session D3's steps), cache, flash ID, pad rate, key bounce, low reads; then 3.2.174 back | core scope run; first sound from a bare-metal image; stock restored | [sessions/M1-bench.md](sessions/M1-bench.md) |
| M2 | 2026-11-18 | diagnostic image 0.3.2: low reads and stores, misaligned access, EMIFA, NOP/IDLE, reciprocal tables, panel MCU stream | parts R, M, L, N, P, W, X run; P2, P3 and the stock part S not done; 0.3.2 left installed | [sessions/M2-bench.md](sessions/M2-bench.md) |
| M3 | 2026-11-19 | diagnostic image 0.3.4: per-path held load data, interrupt timing, reciprocal input bits, pad hit shape | views SIDE, NOP2, RCP2 and PADR B run; results recorded in `emulator/README.md`; stock part K and the end state not reported | [sessions/M3-bench.md](sessions/M3-bench.md) |

Planned, not run: C4 (Lofi-12 XT with relocated settings, [sessions/C4-relocated-lofi.md](sessions/C4-relocated-lofi.md)),
L1 (LED map,
[sessions/L1-led-map.md](sessions/L1-led-map.md); folded into M1 part F, not run), D3-audio-pins (outputs on the stock
firmware, [sessions/D3-audio-pins-plan.md](sessions/D3-audio-pins-plan.md); folded into M1 part H, not run). Session D3
([sessions/D3-audio.md](sessions/D3-audio.md)) ran as M1 part A.

**Current device state:** stock SmplTrek 3.2.174, restored from card B after M3 (operator, 2026-11-20). M3's part K
results were not reported. The last SYSTEM INFO photograph of the stock state is from M1 (2026-11-16).

## Log

Entries in date order. The run tables in the first sections are the 2026-11-08 plan, kept for provenance.

## Run order (plan of 2026-11-08)

Runs 1 and 2 were done the same day; the optional runs 3 and 4 were not run.

| # | File on the card as `SmplTrek.bin` | Purpose | Expected / what it tells us |
| --- | --- | --- | --- |
| 1 | official `firmware/smpltrek/SmplTrek v2.0.129.zip` → `SmplTrek.bin` | control; real upgrade 1.0.65→2.0.129, PRESET 1.0.11→2.0.22 | accepted; proves card + procedure; leaves a known-good, content-complete state |
| 2 | `SmplTrek_3.2.174_custominfo_resealed.bin` | **the real test**: official 3.2.174 with the system-menu label `SYSTEM INFO` changed to `CUSTOM INFO`, CRCs recomputed | accepted and the SYSTEM menu shows `CUSTOM INFO` ⇒ the whole chain works (patch → reseal → bootloader accepts → runs). Rejected ⇒ the bootloader checks more than the CRCs |
| 3 (optional) | `SmplTrek_2.0.129_onebyte_test.bin` | stale CRCs (cmtd, pmtd wrong; mmtd right) | expected `Checking` error ⇒ CRC enforcement confirmed |
| 4 (optional) | `SmplTrek_2.0.129_onebyte_resealed.bin` | content-partition edit, resealed, same version as installed | tests same-version re-flash and content edits |

Sonicware's download page says a unit must be on 2.0 before installing 3.x. Run 1 satisfies that (3.x files are
system-only and rely on the 2.0.22 content image, e.g. the PDPT drum-pattern partition added in 2.0). Do not skip it.
If run 2 is rejected, note whether the message mentions the version rather than the check, since the
2.0 prerequisite suggests the bootloader (or the file) carries a minimum-content-version rule.

Restore to stock at any time with official 3.2.174 (system) and official 2.0.129 (content).

## File provenance (all verified with `cmp -l` against the official files)

- `SmplTrek_3.2.174_custominfo_resealed.bin`: 11 bytes differ. 3 string bytes at zero-based file offsets
  0x1CF78C (S→C), 0x1CF78D (Y→U), 0x1CF790 (E→O), turning `SYSTEM INFO` into `CUSTOM INFO` (label starts at
  0x1CF78C, load address 0xC16C8B64, mmtd section 5 .const). Plus 4 bytes cmtd CRC at 0x8 and 4 bytes mmtd CRC
  at 0x38. (These are file offsets; `cmp -l` prints one-based positions, one higher.) The label is NUL-terminated, 11 chars both ways, no format
  specifiers; neighbours are the System Info labels `VERSION BOOT PRESET SYSTEM`. cmtd CRC 7D5CFB11→82EDF15B,
  mmtd CRC 939CE727→2BE93F77. SHA-256 914d538c2143d3413d509a3d8343efb5ec13376e95d6598d1bd862b70775e0e8.
- `SmplTrek_2.0.129_onebyte_resealed.bin`: 9 bytes differ: one WAV byte at 0x1266CD4 (C0→BF, first WAV in
  PISN, flash 0x1800000 partition), cmtd 5E8E8BB1→A87E7FCD, pmtd CA1D0801→AA02B7AF.
  SHA-256 3b7aae1b5fdd8adc27ae7bf3e3749c5f202f6428b7603305237af93d7a43e81f.
- `SmplTrek_2.0.129_onebyte_test.bin`: 1 byte differs (0x1266CD4), CRCs stale.
  SHA-256 d827d1ac028cab2a44b905bef8eadb13f30509f0294faf044b170624978d9c73.

## Procedure (per run)

1. Exactly one file at the SD root named `SmplTrek.bin`. AC adapter.
2. Hold **HOME** (house icon), press and hold power → `BOOT MODE v1.0.17` menu.
3. `SYSTEM UPDATE` → OK. Photograph the screen after `Check the firmware file / Checking...` and the
   `PRESET:`/`SYSTEM:` version lines. Confirm with OK, let `Erasing / Writing / Verifying` finish, power off, power on.
4. After run 2: open the SYSTEM menu and photograph the entry that should now read `CUSTOM INFO`; open it and
   photograph the version screen. Also run `SYSTEM DIAG` once more and photograph it (all four images should still say OK).
5. If USB is handy: in BOOT MODE with USB connected to a PC, check `lsusb` / `dmesg -w` for an enumerated device.

## USB check result (Nov 8 2026)

In BOOT MODE with USB connected, the Windows host saw no device and no plug-and-play event. Control on the
same cable and port, normal boot: the app enumerated as `USB\VID_2FD7&PID_0004` (one audio-class function;
see "USB MIDI result" below for why this did not rule out MIDI).
So the bootloader does not start USB at the menu, and the SD card is the only update channel. The
SYSTEM UPDATE screen (showing "ERROR: No card" with no SD card) was also checked: still nothing on USB.

## USB MIDI result (Nov 9 2026, modified 3.2.174 running, no flashing)

Plug and Play shows one composite device `USB\VID_2FD7&PID_0004` with a single function `MI_00`
(class 01 subclass 01, driver usbaudio, "USB Audio Device") whose children are the Headphones and
Microphone endpoints. That view is blind to MIDI: the legacy usbaudio driver handles a MIDI-streaming
interface inside the same function and exposes it only as a port. Queried through winmm
(`midiInGetDevCaps` / `midiOutGetDevCaps`), the host lists MIDI IN "SmplTrek" (mid 1, pid 103) and
MIDI OUT "SmplTrek" (mid 1, pid 102, technology 1 = MIDI port). So 3.2.174 does expose USB MIDI. The MIDI CONFIG page's INPUT FROM / OUTPUT TO were set to USB&MIDI
before this query. Toggled back to the default MIDI and re-plugged: the ports are still present. So the
USB MIDI interface is always exposed and the MIDI CONFIG setting only routes traffic inside the app. The interface node ID was
unchanged throughout.

## Card used (Nov 8 2026)

4 GB SDHC, MBR, partition 1 FAT32 (type 0x0C, label SD), partition 2 a 32 MB FAT16 Ventoy EFI partition
left in place. The app's own formatter writes FAT32 ("MSDOS5.0" / "FAT32   " boot sector) and the firmware
contains no exFAT support, so FAT32 is the right choice. The bootloader tolerates the second partition
(run 1). Run 1 file placed at the root as `SmplTrek.bin`, SHA-256
df0e1520e4132fa74baa22b4315ffdab598ed4c9065a9d8189ed4bb96f1fbb40 (verified on the card).

## Run 1 result (Nov 8 2026)

Accepted. "Checking... 100%, OK.", confirmation screen listed PRESET v1.0.11 -> v2.0.22 and SYSTEM
v1.0.65 -> v2.0.129, both images erased/written/verified, SYSTEM INFO after restart: BOOT 1.0.17, PRESET
2.0.22, SYSTEM 2.0.129, MCU 1.0.6. The two-partition card was fine. Photographed.

## Run 2 staged (Nov 8 2026)

`SmplTrek_3.2.174_custominfo_resealed.bin` copied to the card root as `SmplTrek.bin`, replacing the run 1
file. SHA-256 on the card 914d538c2143d3413d509a3d8343efb5ec13376e95d6598d1bd862b70775e0e8 (matches).
The 2.0.129 app had created `SmplTrek/` on the card at first boot (Project/Project001/{Audio,Config},
Project/Project.lst, Pool/{Audio,Kit,SMF}); left in place.

## Run 2 result (Nov 8 2026): ACCEPTED

"Checking... 100%, OK.", confirmation listed SYSTEM v2.0.129 -> v3.2.174 only, erase/write/verify OK,
and after restart the info page title reads **CUSTOM INFO** (BOOT 1.0.17, PRESET 2.0.22, SYSTEM 3.2.174,
MCU 1.0.6). The patch → reseal → flash chain is proven end to end. Photographed.
The unit ran the modified 3.2.174 until A3 restored the official file the next day.

## Pre-write safety probes (run 2026-11-09)

Prepared 2026-11-08 and 2026-11-09; results under "Step 2" below.

Run with the official 3.2.174 `SmplTrek.bin` on a second card as the recovery path.

| # | File on the card as `SmplTrek.bin` | What it is | Reading the result |
|---|---|---|---|
| C1 | `SmplTrek_3.2.174_ctrl_outer_crc_bad.bin` | official 3.2.174 with one bit flipped in the cmtd CRC word (1 byte differs, offset 0x8); mmtd untouched | "Checking" must fail. Same version as installed, so no downgrade policy can confound it. Accepted ⇒ the outer CRC is not checked. CLR out. |
| C2 | `SmplTrek_3.2.174_ctrl_inner_crc_bad.bin` | official 3.2.174 with one bit flipped in the mmtd CRC word (offset 0x38), cmtd CRC recomputed so the outer check passes (5 bytes differ) | "Checking" must fail. Accepted ⇒ the inner CRC is not checked before the confirmation prompt. CLR out. |
| A1 | `SmplTrek_2.0.129_onebyte_test.bin` | official 2.0.129 with one WAV byte changed and CRCs left stale | "Checking" should fail, but a rejection is confounded by downgrade policy (installed is 3.2.174); C1/C2 are the clean controls. Optional. If it is accepted, the CRC is not what gates acceptance and everything above needs rethinking. Do not press OK if it is somehow accepted; CLR out. |
| A2a | `SmplTrek_3.2.174_family12_smpltrekseeds.bin` | official 3.2.174, cmtd family word 5→12, resealed with SmplTrek seeds (5 bytes differ: family word + cmtd CRC; mmtd untouched) | Accepted ⇒ the family word is neither checked against the device nor used to pick CRC seeds. |
| A2b | `SmplTrek_3.2.174_family12_lofiseeds.bin` | same, resealed with Lofi-12 XT seeds (9 bytes differ: family word, cmtd CRC, mmtd CRC) | Accepted (and A2a rejected) ⇒ the bootloader selects CRC seeds by family word and does not check the word against the device. Both rejected ⇒ the family word is checked against the device, or the seeds are tied to the device rather than the file. |

Both A2 payloads are byte-identical stock SmplTrek 3.2.174 system images, but the stored mmtd CRC in A2b
is a Lofi-seed value. If the bootloader validates the *installed* system image at boot with device-fixed
seeds, an installed A2b could fail that check and leave the unit sitting in boot mode until reflashed.
So for A1, A2a and A2b: **read the Checking result and the confirmation screen, photograph them, then
press CLR. Do not press OK.** Pre-write acceptance is the information sought; nothing is gained by
writing. SHA-256:
`90f6d74f18ba3b62d31bdefd8835317b605d44d154191b4ea45ee80dfe447b71` (A2a),
`5779655c1d6415c77eed17fc3d42157b9e9f7a8bccf6445c8c900138a40f4756` (A2b),
`25ef7ff7c7238d93d9a7c687cc805acb2e07aa1a3410140e56dfa55694ba8ae2` (C1),
`0dc15a716f522c9c15818810b5636e9c854f96cffe166cd55481d8e436cada6c` (C2).
Official 3.2.174 `SmplTrek.bin` (the recovery file): `3b6848b0f041bcf23c73d4b0357d2f3d6dc9e7e03752b32ff7322e91e6814e53`.
Regenerate: `tools/sonicware_integrity.py reseal --profile smpltrek --allow-family-mismatch` /
`--profile lofi12` on official 3.2.174 with the word at offset 0x10 set to 12.

### Step 1 result (2026-11-09, modified 3.2.174 installed, nothing flashed)

Smoke test passed: sampling, navigation, playback, saving all normal. Menu item reads CUSTOM INFO and
shows BOOT 1.0.17, PRESET 2.0.22, SYSTEM 3.2.174, MCU 1.0.6. BOOT MODE menu (three items: SmplTrek,
SYSTEM UPDATE, SYSTEM DIAG; version 1.0.17 shown) > SYSTEM DIAGNOSTICS: all four images check OK with
the same version numbers. So the bootloader's installed-image CRC check accepts the resealed SYSTEM
image: the seeds and algorithm in `tools/sonicware_integrity.py` are the ones it uses, not just the ones the update path uses.
USB MIDI: see "USB MIDI result" above.

### Step 2 results (2026-11-09, pre-write probes, CLR never needed where rejected)

| # | Bootloader output | Reading |
|---|---|---|
| C1 | `Check the firmware file.` / `Checking... 100% NG` / `ERROR: This file is invalid` | **Outer (cmtd) CRC is enforced.** One flipped bit in the CRC word, same version as installed, nothing else differs. The acceptance of the resealed files was the CRC, not luck. |
| C2 | `Checking... 100% OK` / `SYSTEM:` / `V3.2.174 -> V3.2.174` / `Are you sure? [CLR] No / [OK] Yes` (CLR pressed) | **The inner mmtd CRC is not checked before the confirmation prompt.** The inner CRC was wrong and the file was accepted up to that screen. What happens after OK was not tested (the file was never written): whether "Verifying" compares flash against the file bytes or recomputes per-image CRCs is unknown. SYSTEM DIAGNOSTICS does check the installed image's own CRC (Step 1), so a file with a bad inner CRC might be written and then fail diagnostics, and possibly boot. Always reseal both CRCs; never hand-patch only the outer one. Also: a same-version update (3.2.174 -> 3.2.174) is offered, and a system-only file lists only SYSTEM (no PRESET line). |
| A2a | `Checking... 100% NG` / `ERROR: This file is invalid` | Family word 12 with SmplTrek seeds is rejected. Either the word is compared with the device, or it selects the CRC seed (so the SmplTrek-seed CRC no longer matched). A2b decides. |
| A2b | `Checking... 100% NG` / `ERROR: This file is invalid` | Family word 12 with Lofi-12 XT seeds is also rejected. **The family word is checked against the device** (simplest reading; the alternative, that word 12 selects an unknown seed, is not excluded but changes nothing in practice). A SmplTrek must be given family word 5 and SmplTrek seeds; a foreign system image would have to be rewrapped and resealed, which `sonicware_integrity.py reseal` can do. |

The A2 pair as a deduction, not a guess: if the bootloader picked its CRC seeds from the file's family word,
A2b (word 12, Lofi seeds) would have computed the Lofi-seed CRC, matched, and passed. It did not, so seed
selection keyed on the file's family word is excluded. What remains is either a comparison of the word with
the device, or a seed table with no entry for a foreign family. Both give the same operative rule, which W1
then confirmed: to flash X on device Y, wrap with Y's family word and reseal with Y's seeds.

Conclusions from these probes: *before the confirmation prompt* acceptance is gated by the family word and the
outer CRC only. The inner CRC is enforced by the installed-image check in SYSTEM DIAGNOSTICS; whether the
post-OK "Verifying" step or a normal boot also checks it was not tested on the device (nothing with a bad inner
CRC has been written). Same-version updates are offered. All four probes were stopped before any write.

### Step 3 result: A3 same-version restore (2026-11-09), passed

Official 3.2.174 (`SmplTrek.bin`, SHA-256 `3b6848b0…6814e53`, verified against the file inside the
Sonicware zip) flashed over the modified 3.2.174 via BOOT MODE > SYSTEM UPDATE, `V3.2.174 -> V3.2.174`,
OK, Erasing/Writing/Verifying, restart. Cold boot: menu reads SYSTEM INFO (the CUSTOM label is gone),
versions unchanged (BOOT 1.0.17, PRESET 2.0.22, SYSTEM 3.2.174, MCU 1.0.6), SYSTEM DIAGNOSTICS all OK,
sampling/playback/saving normal. **The recovery path from a modified system image back to stock is
proven.** Device state at the end of the session: stock 3.2.174.

Later sessions extended the recovery path: from an older version (D1-downgrade, 2026-11-11: official 3.0.148
written, booted, DIAG all OK, 3.2.174 restored), from a foreign app (C3, 2026-11-11: the sterilised Lofi-12 XT
1.5.205 written, booted and run, BOOT MODE reached with it installed, 3.2.174 restored, DIAG all OK), and from an
app that never runs (D0, 2026-11-12: a SYSTEM image that branches to itself; HOME + power reached BOOT MODE and
3.2.174 restored).

### Session order of 2026-11-09 (the plan; results above)

Device state at the start: modified+resealed 3.2.174 (CUSTOM INFO) installed and booting.

1. No flashing. Normal boot, plug USB into the PC: check whether 3.2.174 enumerates a MIDI interface
   (the config descriptor has one). Smoke test: pads, sample playback, record, save a project to the
   card. Then BOOT MODE, SYSTEM DIAGNOSTICS, photograph: does the bootloader's installed-image CRC
   check accept the resealed SYSTEM image?
2. Pre-write probes, CLR at the confirmation screen, never OK: C1, C2, A2a, A2b (A1 optional). Photograph
   the Checking result and, if reached, the version lines on the confirmation screen.
3. A3 same-version restore: official 3.2.174 as `SmplTrek.bin`, OK, let it write, restart. Cold boot:
   SYSTEM INFO (not CUSTOM) in the menu, SYSTEM DIAGNOSTICS, smoke test. Device ends on stock.

## Cross-flash pre-write probes (W1 run 2026-11-09)

Same rule as the safety probes: **read the Checking result and the confirmation screen, press CLR, never OK.**

| # | File on the card as `SmplTrek.bin` | What it is | Reading the result |
|---|---|---|---|
| W1 | `Lofi12XT_1.5.205_wrapped_family5_smpltrekseeds.bin` | official Lofi-12 XT 1.5.205 with the family word set to 5 and both CRCs resealed with SmplTrek seeds (9 bytes differ from the Lofi file: family word, cmtd CRC, mmtd CRC). System image is byte-identical stock Lofi, loading at 0xC2B8..0xC2DC. | Reaches the confirmation screen ⇒ acceptance is only family word + outer CRC; note the version line (3.2.174 -> 1.5.205). Rejected ⇒ the bootloader also checks something inside the mmtd (load addresses, version order, ...). |
| D1 | official SmplTrek 3.0.148 `SmplTrek.bin` (from `firmware/`) | genuine older SmplTrek release, untouched | Confirmation screen shown ⇒ downgrades are offered. Rejected ⇒ version ordering is enforced; separates that from whatever W1 shows. |

SHA-256: W1 `ed72341d53dc68e97acd747c3dcfae18cf5159ebd91d324ac5ff88cb827488d7`;
D1 `098bdaccd0c9c3276d121238d2876570e0f1e8613b34309c36f182bfb8fb47ba`;
official Lofi-12 XT 1.5.205 `a8bffa65919c0a2d4ff2ce77d16301551af4d2964497b8804deed49ce4198026`.
Regenerate W1: set the word at offset 0x10 to 5 in the official Lofi file, then
`tools/sonicware_integrity.py reseal --profile smpltrek`.

**W1 result (2026-11-09):** `Checking... 100% OK`, `SYSTEM: V3.2.174 -> V1.5.205`, `Are you sure?`; CLR
pressed, nothing written. So the bootloader's acceptance check **before the confirmation prompt is family
word + outer CRC, and nothing else**: it did not object to section load addresses in a different DDR range
(0xC2B8.. instead of 0xC15..), nor to a lower version number. So downgrades are offered, and the D1 pre-write
probe was not needed; it was run later as a full write-and-boot test (D1-downgrade,
`experiments/sessions/D1-downgrade.md`). The version line comes from the mmtd header. Getting a foreign image
*accepted* is therefore a matter of wrapping. Getting one to *run safely* is not; the risks named at this point
were: (1) a cross-flashed app is the boot path, so the "nothing of ours runs at boot" rule
cannot protect it, and the recovery premise that the bootloader reads HOME before the app runs is inferred
from screen timing, not from code; (2) the foreign app's boot-time flash *reads* (its own settings and
factory data at its own offsets) are unmapped, unlike its writes; (3) the panel-MCU message interpretation
is app code and may differ per product. (All three were worked before C3; see `docs/01-platform-map.md`.)

Why W1 itself was never written, and C3 used a patched image instead: the only flash erase/program path in both apps is
one shared helper writing two 4 KiB blocks at the top of flash (2026-11-09; `docs/01-platform-map.md` "Flash use by
the app"). A foreign app would overwrite SmplTrek's settings blocks with its own format. Checked 2026-11-09
(`docs/01-platform-map.md` "Settings block"): SmplTrek validates only a 4-byte tag per block ("PREF" / "PREX"), and Lofi-12 XT and
CyDrums use the same tags with different layouts, so SmplTrek would accept a Lofi-written block and rely on
its per-field clamps. A crash on reading such a block would not be fixed by a reflash, because updates do
not touch that area. Fix before any foreign flash: a "sterilised" image whose settings writer returns at
once (preferred first), or a "tagged" image with the literals changed so neither product reads the other's
blocks. The sterilised patch must set its return value explicitly (`mvk 0, a4` before the `b b3`, or
whatever the writer's caller treats as success); a bare return leaves A4 holding the first argument, a
pointer that reads as a negative error code, and what the caller (SmplTrek 0xC154AE60, Lofi 0xC2BAD7B8) does on
error was not read, so the stub returns 0 (C3's patch does). Also, a foreign app runs at boot, so a hang there would be
the first real test of HOME + power with a hung app; D0 later tested that on its own (2026-11-12).

## Session S2 pass-through result (2026-11-09)

Session S2 tested code execution through the update path: official 3.2.174 with an eighth mmtd section appended at
0xC3F00000 (4 KiB) and one vtable slot of the SYSTEM INFO page redirected to code in it, resealed. Two variants: a
pass-through that only calls the original title function, and a "hello" that also draws a text line.

The operator reported flashing the pass-through image and opening SYSTEM INFO successfully. Playback and button
presses seemed unaffected; SYSTEM DIAGNOSTICS showed all OK. Image (local build, not published): SHA-256
`b53c531231cdddcf764af410e9388a63c71d980cdb5f35348bbc04471d4416fa`; this is the build hash, not a read-back from the
card.

This supports loading the eighth mmtd section at 0xc3f00000 and executing its pass-through callback into the
original title function. There is no visible marker in this control; execution is inferred from the patched slot
and the successfully opened page. Diagnostics also accepted the installed image. It does not establish exclusive
RAM ownership or exercise the hello probe's cache call, sentinel checks or custom drawing (see the hello runs below).

## Session S2 drawing result (2026-11-10)

The operator flashed the hello variant. The probe text (on screen `SDK S2 OK`) is visible, but overlaps the
SmplTrek logo and is readable only in the logo's negative space (photographed 2026-11-11). SYSTEM DIAGNOSTICS
reports OK and machine behaviour seems unaffected. Image (local build, not published): SHA-256
`a22061584b53a7ed9987ff03659c5ce63c03180f9958cbbd0885a706a691e79c`.

The visible custom text establishes execution of the injected drawing path. Since the cache wrapper precedes
drawing, it returned on this run; this does not independently test its invalidation effect. The partially obscured
text is not a reliable readout of every sentinel-status character. Exclusive RAM ownership remains an inference.

Layout: the original Point {10,34} falls in the logo area. The second revision changes only its y coordinate to 116,
below the last stock divider at y=114 (built at 0xc16670a8..0xc16670e4 in the stock page body; placement from
objdump, confirmed on the unit 2026-11-11). y=116 is the stock soft-button legend row, so the probe text overdraws
the left-hand "back" arrow; harmless for a probe, but a mod that wants a clean line should pick another spot.
Second-revision image (local build, not published): SHA-256
`08d01ae4694e619d1cd16c179db9aaa6ed51a83f354aff85ac38227bd3cb4ec6`. Offline checks before the run: all 8 of the
probe's tests and recipe/CRC verification pass; the raw payloads differ in exactly one byte (offset 0x100: 34 to
116); executable bytes are identical.

## S2 results ledger (2026-11-09 to 2026-11-11)

What was flashed, in order, with the evidence level of each result. "Operator report" means a verbal report with
no photograph, no hash read back from the card, and a single boot.

| Date | File flashed (local build SHA-256) | Observed | Evidence |
|---|---|---|---|
| 2026-11-09 | A3: official 3.2.174, `3b6848b0…6814e53` | stock restored, SYSTEM INFO label back, diagnostics OK | photographs and hash verified on the card |
| 2026-11-09 | pass-through, `b53c5312…d4416fa` | SYSTEM INFO opens, diagnostics OK, playback and buttons apparently normal | operator report; **no marker, so this cannot show the hook ran** (see below) |
| 2026-11-10 | hello, first revision, `a2206158…691e79c` | `SDK S2 OK` text visible at (10,34), partly behind the logo; diagnostics OK | **photographed 2026-11-11** (SYSTEM INFO: the first letters of the probe line show at the left edge, the rest under the logo; BOOT 1.0.17, PRESET 2.0.22, SYSTEM 3.2.174, MCU 1.0.6; `systemdiagnostics`: BOOT, MCU, PRESET, SYSTEM all `100%, OK`). Hash on the card not read back; single boot. Positive evidence of entry and drawing |
| 2026-11-11 | hello, second revision, `08d01ae4…3cb4ec6` | `SDK S2 OK` fully readable at (10,116) under the bottom divider, logo clean, version table unchanged. The strip below the divider is the stock soft-button legend for the two buttons under the screen (a curved "back" arrow at the left, a bar at the centre; see the first-revision photo), so the text overdraws the back arrow and the bar remains visible after `OK` | **photographed 2026-11-11**. Operator reports repeated cold boots with the same display every time (not photographed). Hash on the card not read back; diagnostics not re-photographed on this image |
| 2026-11-11 | restore: official 3.2.174, `3b6848b0…6814e53` | SYSTEM INFO back to stock (no probe line, soft-button legend back arrow and bar intact, BOOT 1.0.17 / PRESET 2.0.22 / SYSTEM 3.2.174 / MCU 1.0.6); `systemdiagnostics` BOOT, MCU, PRESET, SYSTEM all `100%, OK` | **photographed 2026-11-11**: SYSTEM INFO and diagnostics. Hash on the card not read back this time |

After every flash in this ledger the operator played back a sample from the SD card (which exercises the card
reader as well as the audio path) and tried assorted buttons; nothing abnormal was reported on any image.

The pass-through control is a negative control for catastrophic damage only: "the page opened" is consistent
with the hook running and tail-branching correctly, and equally with the hook never being called (wrong slot,
title drawn by another path, a RAM copy of the vtable shadowing the patched one). Only the hello runs are
evidence that the appended section executes. Later no-op probes carry a one-pixel marker so that they are
positive controls.

The safety probes set the evidence bar (photographs, hash verified on the card, transcripts quoted); the S2 results
are below it in places. S2 was closed on 2026-11-11 with: a photograph of the hello result (the diagnostics photo
also shows that the resealed inner CRC of the appended-section image passes the installed-image check, not only the
bootloader's pre-write check); the second revision photographed, the one-byte y change behaving as the objdump
placement predicted; repeated cold boots on it at operator-report level, with card playback and button checks after
each flash; and the restore of official 3.2.174 photographed (SYSTEM INFO and DIAG), with playback from the card and
buttons checked (operator report). Remaining gaps: the pass-through run stays a negative control, the card hash was
never read back after a flash (the local build hashes are recorded instead), and exclusive ownership of the 4 KiB
section at 0xC3F00000 rests on inference (EXE-4).

## A4 flash dump (2026-11-11: full 32 MiB dump obtained twice)

Software only, no clip read (2026-11-11). The dumper is a small hand-written assembly probe (not published,
with model tests and a build audit for read-only flash access). It reuses session S2's hook and section
(0xC3F00000, guard words `A4G1` / `A4G2`), only ever reads flash, and appends flash to a file at the
card root per visit to SYSTEM INFO, reading each 32 KiB chunk twice and comparing before writing.

### Revision 1 result (2026-11-11): the dump path works, but it read device 1

| Date | File flashed | Observed | Evidence |
|---|---|---|---|
| 2026-11-11 | revision 1 filetest image, `0adb9869…4a2428` (payload `f168b09d…932200`) | `A4 FILE 00/16 MiB`; empty `A4FLASH.BIN` created at the card root; diagnostics OK, playback and buttons normal | photographed; operator report for the file and the checks |
| 2026-11-11 | revision 1 dump image, `7e6fedac…2cf354` (payload `3fe9a32d…82fe9b`) | five visits appended 1 MiB each; from the sixth visit on, `A4 READ DIFF` on every entry and the file stopped at exactly 5 MiB | photographed; the 5 MiB file is kept locally (not published), SHA-256 `235b7622…54bef7` |

What the 5 MiB file holds (offline, 2026-11-11): no 'bmtd' / 'mmtd' / 'pmtd' anywhere and no byte of the
3.2.174 system image; instead preset names (`4 KICK`, `BALLAD 01`, `BRKBEATS 1`). Compared with the
content ('pmtd') image of the 2.0.129 update: bytes 0..0x68174 equal the **PDPT** partition exactly
(426,356 of 426,356) and bytes 0x100000..0x500000 equal the first 4 MiB of **PDSN** exactly. Those
partitions live at app addresses 0x01000000 and 0x01100000, i.e. **device 1 from offset 0**.
Cause, from the code: `request_read` takes a 24-bit address on whichever device the driver has
selected (`this+32`); every stock caller first calls `flash_select_address(addr)` (0xC15FDEC0), which
selects device 0 or 1 and returns the address on that device. Revision 1 skipped that call, and after
boot the selected device is 1 (the settings read is the last boot-time access). So the read, double
read, compare and FatFs write chain is proven correct over 160 chunks, with the one wrong input.

Consequences: device 1 is reachable (an earlier reading took the 24-bit limit as "unreachable above 16 MiB"; the
limit is per device, and the selection is a separate call), so revision 2 dumps the full 32 MiB. The `A4 READ DIFF`
at device 1 offset 0x500000 (inside PDSN; the reference content there is ordinary sample data) is **not explained**:
the two reads of that chunk disagreed on every visit while the 160 chunks before it agreed. Revision 2 reports the
position (`A4 DIFF nn/32 MiB`), writes both copies of the chunk to `A4DIFF.BIN`, and invalidates the cache over each
buffer after its read (in case the SPI driver fills the buffer by DMA). Revision 2 read that chunk without a
difference, twice, and its bytes equal the 2.0.129 content image (step 4 below), so the revision 1 difference did not
recur and its cause is not known.

### Revision 2 (built and run 2026-11-11)

Deterministic build outputs (local, not published; the build record carries the full hashes and the audited
call-target list, twelve entries including `flash_select_address` and `Cache_inv`):

| Variant | Output `SmplTrek.bin` SHA-256 | Payload SHA-256 |
|---|---|---|
| filetest | `ddbc621e…97ef8a` | `b2b649e7…` |
| dump | `b0f675b9…cfbfdc3` | `3a89e82c…` |

Runs, in order, with the evidence level:

| Step | File | Expect | Result |
|---|---|---|---|
| 1 | (done with revision 1) | FatFs wrappers from the graphics task | done, see above |
| 2 | revision 2 dump image | `A4 DUMP 02/32 MiB` on the first visit, `A4 DONE 32 MiB` after 16; a 32 MiB `A4DUMP.BIN`; on a mismatch `A4 DIFF nn/32 MiB` and `A4DIFF.BIN` | **done 2026-11-11**: the page redraws by itself while open, so one visit ran several 2 MiB batches; the first screen the operator caught read `A4 DUMP 06/32 MiB`, the second visit went from 30 to 32 and ended on `A4 DONE 32 MiB`. No `A4 DIFF` at all this time. `A4DUMP.BIN` is 33,554,432 bytes, SHA-256 `3767d6ad…e4c8d5`, kept locally (not published) |
| 3 | (no flash) | `analysis/flash_dump_check.py` finds 'bmtd' at 0x3FFE4, 'mmtd' at 0x40000, 'pmtd' at 0x440000, the official sections, and PDPT at 16 MiB; file hashed | **done 2026-11-11**: all three headers found where the app reads them, with the version triplet at +16 (1.0.17 / 3.2.174 / 2.0.22; the word at +12 is 0xFFFFFFFE, not the version as an earlier inference had it); the seven system-image sections are laid out verbatim from 0x40030 and equal official 3.2.174 except the four bytes of the hooked vtable slot (the unit was running the probe image); 'PREF' / 'PREX' at 0x1FFE000 / 0x1FFF000 (+0xC00) as mapped; a TI AIS boot image (`TIPA` magic) at offset 0; erased runs 0x37000..0x3F000, 0x21E000..0x440000, 0xFC8000..0x1000000, 0x1749000..0x1800000, 0x1F7F000..0x1FFE000 |
| 4 | same dump image | second dump after deleting the file; hash equal to the first | **done 2026-11-11**: the operator took a second full dump (kept locally, not published). It is 33,554,432 bytes, SHA-256 `3767d6ad…e4c8d5`, identical to the first (`cmp`: 0 differing bytes). Earlier partial checks also agree: device 1 bytes 0..5 MiB equal the revision-1 file exactly (an independent read, including the chunk revision 1 had flagged), and every content partition (PKIT, PPRJ, PDPT, PDSN, PISN) equals the 2.0.129 content image byte for byte. The settings sectors did not change between the two dumps. The file system records no real time (both files are dated 2022-01-01), so the files alone can't show how far apart the dumps were taken; that rests on the operator's account |
| 5 | official 3.2.174 `3b6848b0…6814e53` | stock restore, as S2 closure | **done 2026-11-11** (operator report, no photo) |

Stop conditions: any `A4 RAM CHANGED`, `A4 DIFF` twice at the same position (copy `A4DIFF.BIN` off the
card first), a freeze, or diagnostics not OK. Restore stock rather than retrying blindly.

## C3 sterilised Lofi-12 XT image (built 2026-11-11; written and run the same evening)

The first cross-flash candidate: official Lofi-12 XT 1.5.205 with its settings writer
stubbed, rewrapped as family 5 and resealed with the SmplTrek seeds. The stub is the one specified in
`docs/01-platform-map.md` ("Where the patch has to fit") and claim XF-5: the two 16-bit instructions at
the entry of `settings_save` (0xC2C8B0F8) become `mvk .L1 0,a4; bnop .S2 b3,5`, so both entries
(the direct call and `settings_reset_and_save`) return 0 before the stack or the flash driver is
touched. The compact packet header stays as it is. Everything else is byte-identical stock Lofi-12 XT.

Build and check (deterministic; refuses to overwrite):

```sh
python3 -B tools/patches/sterilise_lofi.py build firmware/lofi12/Lofi-12XT_v1.5.205.zip \
  experiments/Lofi12XT_1.5.205_sterilised_family5_smpltrekseeds.bin \
  experiments/Lofi12XT_1.5.205_sterilised_family5_smpltrekseeds.recipe.json
python3 -B tools/patches/sterilise_lofi.py verify firmware/lofi12/Lofi-12XT_v1.5.205.zip \
  experiments/Lofi12XT_1.5.205_sterilised_family5_smpltrekseeds.recipe.json \
  experiments/Lofi12XT_1.5.205_sterilised_family5_smpltrekseeds.bin
```

| File | SHA-256 |
|---|---|
| official `Lofi-12 XT.bin` 1.5.205 (source) | `a8bffa65919c0a2d4ff2ce77d16301551af4d2964497b8804deed49ce4198026` |
| `Lofi12XT_1.5.205_sterilised_family5_smpltrekseeds.bin` | `67d8a6b07f84b32ab987a4dc07bb0def5370c0074d95d0128724d13f4c7ea2fb` |

Differences from the source: 13 bytes (cmtd CRC at 0x08, family word at 0x10, mmtd CRC at 0x38, and
`f7 36 77 95` → `26 06 ef a1` at 0x11FAC4). Differences from W1: 12 bytes (the two CRCs and the stub).
Checked 2026-11-11: builder replay and `sonicware_integrity.py verify --profile smpltrek` pass; the image
converted with `mmtd2elf.py` and disassembled with `tic6x-elf-objdump` differs from the stock listing
(`work/lofi-1.5.205.dis`) in exactly two lines, `0xC2C8B0F8: mvk .L1 0,a4` and
`0xC2C8B0FA: bnop .S2 b3,5`; the header at 0xC2C8B0FC and the packets before and after decode unchanged.
No erase or program call site is reachable: all four sit inside `settings_save` and its helper.

These checks establish offline conformance. The device run is in `experiments/sessions/C3-crossflash.md`: C3
passed (written, booted, run, BOOT MODE reached with it installed, stock restored, settings unchanged). A sterilised
app cannot save settings, so it is a proof of boot, not a usable firmware; a variant that saves to a free flash
area is session C4 (planned, not run).

## D0 hang-recovery image (run 2026-11-12: passed)

`experiments/D0_hang_0.0.1.bin`, 16,432 bytes, SHA-256
`68a14455547c1cc8faf133bdf51391a841abe7b5d4dbc83a8ac223e31a608bf1` (not published). A SmplTrek-sealed SYSTEM update
(version 0.0.1, family 5) whose only code is `b .S2 $ ; nop 5` at `0xC2000000`, so it contains no Sonicware bytes.
`sonicware_integrity.py verify --profile smpltrek` 2/2 OK. Purpose and protocol:
`experiments/sessions/D0-hang-recovery.md`: does HOME + power still reach BOOT MODE
when the installed app never runs? Two authorised writes in that session: this file, then official 3.2.174.

**Run 2026-11-12, passed** (session file, results table). Confirmation `SYSTEM: v3.2.174 -> v0.0.1`, written; on the
normal boot the unit stayed on, frozen on the SONICWARE logo the bootloader draws, power key dead; adapter pulled;
HOME + power reached BOOT MODE; DIAG BOOT/MCU/PRESET OK and SYSTEM v0.0.1 OK; restore `v0.0.1 -> v3.2.174`; SYSTEM
INFO after: BOOT 1.0.17, PRESET 2.0.22, SYSTEM 3.2.174, MCU 1.0.6 (photographed). New facts: the bootloader initialises the display, draws the logo and latches the
power hold before the jump (HW-24). Device state: stock 3.2.174, PRESET 2.0.22, MCU 1.0.6.

## D1 hello skeleton image (runs 1-7, 2026-11-13 and 2026-11-14)

A bare-metal image with no Sonicware code, built with GCC, carrying an SD card driver and a loader for an app module
on the card (`/APPS/APP.BIN`). Each run below wrote the next image version over the previous one; the image history
is at the end of this section.

**Run 1, 2026-11-13, with 0.2.3 (SHA-256 `ba9c7885…109275`, 42,032 bytes) and `/APPS/APP.BIN` on card A: the update
was written; on the normal boot the SONICWARE logo appeared and the unit hung, power key dead, supply pulled**
(operator report, no photos; `experiments/sessions/D1-hello.md` "Run 1"). Hung before its first frame; which of the
four unbounded waits, or whether the code ran at all, the image could not say. 0.2.4 below can.

**Run 2, 2026-11-13, with 0.2.4 (SHA-256 `30d346ea…c8fd7`, 44,368 bytes): the unit switched itself off about 15 s
after the logo, fault 3** (operator report): the image runs, SPI1's PSC transition completes, and the first OLED command
byte never completes. Cause: SPIPC0 never written (the stock's driver build writes `0x0E01`; the first trace missed it).
0.2.5 below adds it.

**Run 3, 2026-11-13, with 0.2.5 (SHA-256 `41faddcd…0faed6`, 44,400 bytes) and `/APPS/APP.BIN` on card A: splash,
status page, app loaded from the card; text unreadable, every pixel pair swapped; keys and encoders change the
numbers; nothing seen from the panel MCU** (operator report; photographs; `experiments/sessions/D1-hello.md` "Run 3"). The unit shows the high nibble
of a framebuffer byte as the left pixel; the skeleton had even x in the low nibble, from the static reading of the
stock's text drawing. 0.2.6 below reversed it and added two MCU-link checks.

**Run 4, 2026-11-13, with 0.2.6 (SHA-256 `e88b1d3c…02c143`, 44,720 bytes) and `/APPS/APP.BIN`: TRK 8 lit bright blue
from the start (TRK 10 a dimmer blue), the VALUE sweep lights LEDs, so UART1 transmit reaches the MCU; the text is
still unreadable with the nibble order reversed, so the pixel fault is not a nibble swap** (operator report; photographs; `experiments/sessions/D1-hello.md` "Run 4"). 0.2.7 below
adds a display test pattern and a 2 x status page.

**Run 5, 2026-11-13, with 0.2.7 (SHA-256 `17bf0a2b…bf9f03`, 45,552 bytes) and `/APPS/APP.BIN`: the test pattern
photographed and decoded: the panel takes the frame as 64 blocks of 128 bytes, one row pair per block, even columns in
the first half and odd columns in the second, the even row in the low nibble (claim HW-35), not row-major at all; the
2 x status page reads; nothing received from the panel MCU (MCU 00 00 00, no pad messages) and no LED lit on the
sweep, with the link set up only after the long pattern-page wait** (operator report; photographs; `experiments/sessions/D1-hello.md` "Run 5"). 0.2.8 below writes that order.
**D1 run 6, 2026-11-13, image 0.2.8: the pattern page exactly as drawn with its border complete on all four sides and the
1 x text legible (HW-35 confirmed, no shift); TRK 8 lit at start and the VALUE sweep lit LEDs; not one byte received on
UART1 (`RX 0 00`) with pads pressed and `A0` sent; at high values the sweep lights the neighbouring LED too** (operator
report; photographs; "Run 6" in the session file).
0.2.9 below adds the receiver self-test.

`experiments/D1_hello_0.2.9.bin`, 47,080 bytes, SHA-256
`e2f4b9584f5d548d7eb14a6587366a8da4bdd065820c064cc60185f75d2be1cf` (not published). Built with GCC tic6x-elf: a
SmplTrek-sealed SYSTEM update (version 0.2.9, family 5), one section at
`0xC2000000`, no Sonicware bytes (FatFs, BSD, is the only third-party code). Power hold, OLED, key matrix, encoders,
panel MCU link, status page; mounts the SD card and loads `/APPS/APP.BIN` through a versioned API; one-second power-key hold switches off. Checks: `sonicware_integrity.py
verify` 2/2 OK; the image's test suite (30 tests: register traffic equals the stock set-up with no card, the UART1
loopback self-test and the start messages, with a simulated card the identification sequence, the mount, the load and the app's callbacks, a sector written and read
back with the stock's command words, and the loader's header checks on crafted modules). Protocol: `experiments/sessions/D1-hello.md`.
**D1 run 7, 2026-11-14, image 0.2.9: `LP OK`; the `A1` reply parsed (`MCU 01 00 06`, DIAG's MCU 1.0.6); 8,123 bytes and
about 2,500 pad messages received in 30 s; the first `A0` (about 100 ms after the link set-up) unanswered and the second
(2 s later) answered, which explains runs 3 to 6 (HW-36 answered, HW-46); STEP n = bit 31 + n (STEP 1 `0001` ... STEP 9 `0200` in the
first KEY field); four encoder counts per detent; the neighbouring LED lights from value 11; `BYE` stays until
the power key is released (HW-47); DIAG all OK with SYSTEM 0.2.9** (operator report; photographs; "Run 7" in the session file). Pad channel indices (pads labelled TRK 1-10, GLOBAL 1-3, USB AUDIO, EXT SRC): index 0 = TRK 8, 1 = TRK 1, 2 = TRK 9, 3 = TRK 2, 4 = TRK 10, 5 = TRK 3, 6 = GLOBAL 1, 7 = TRK 4, 8 = GLOBAL 2, 9 = TRK 5, 10 = GLOBAL 3, 11 = TRK 6, 12 = USB AUDIO, 13 = TRK 7, 14 = EXT SRC (operator). The clean-up planned as 0.2.10 (encoder detents, LED range 0-10, per-channel pad counts) was
built the same evening into 0.3.0, together with the audio path.

`experiments/D3_audio_0.3.0.bin`, 54,232 bytes, SHA-256
`38cb0e391d56d69e66971f74a37705d9412cccfc6f5fdd7344d7ef47cc3dfc96` (built 2026-11-14, not published; never run: its successor
0.3.1 ran in session M1 on 2026-11-16, below). The same
skeleton as 0.2.9 plus the audio path in the stock's order (04-hardware-access.md "Audio: codec, I2C0, McASP0 and the DMA
ring", traced 2026-11-14): audio GPIOs, EDMA3 ring with the stock's 255-word first transfer, McASP0, the TLV320AIC3106's
40 register writes over polled I2C0, unmute, the three analogue power enables; a 750 Hz -20 dBFS tone on the even
words / odd words / both from STEP 1 / 2 / 3 (silence and the speaker muted at start; STEP 4 unmutes the speaker); the
receive ring's peaks on the page; encoders one count per detent; the LED sweep's value stops at 10; the power-off order
gains the DAC mute and `C2`. Checks: `sonicware_integrity.py verify` 2/2 OK; the image's test suite, 38 tests (the 30 of 0.2.9 plus the audio GPIO order, the I2C0 set-up and codec sequence, the
McASP0 register order with the EDMA event arming in place, the six PaRAM sets, the power sequence after the unmute,
silence at start and the ring polled, STEP 1 filling the even words, the power-off order, the encoder detent rule).
Protocol: `experiments/sessions/D3-audio.md` (run as M1 part A).

**Image history.** The 0.1.0 image (no card support) and
0.2.0 (SHA-256 `ac8e46c8…268c64`; superseded 2026-11-12 after a code review: the SD
driver could lose a completion flag and the loader's bounds check could wrap) are superseded, and so is 0.2.1
(SHA-256 `27e54418…9b21d4`; superseded 2026-11-13: its SD writes waited for BSYDNE, which the controller raises only
for a command sent with BSYEXP, so every write would have timed out; it also set PPLEN, which the stock never does;
found by checking the driver against SPRUH79C). 0.2.2 (SHA-256 `57dd8890…611bd`, 40,248 bytes)
was replaced the same day, 2026-11-13, by 0.2.3, which adds what makes the session more informative rather than
fixing a bug: the power key must be seen released once before a one-second hold switches off (a hand still on it
from switching on no longer looks like a lost power hold), a failed card init shows its step and MMCST0 bits
(`CARD E-n xxxx`), the MCU start-up bytes go in the stock's corrected order 90 B1 A0, the splash shows MCU / CARD /
APP as each stage starts, and with no app loaded encoder VALUE sweeps the 144 panel LED addresses one at a time
(encoder D the value) to settle which LED is which. 0.2.3 hung on the device (run 1 above) and 0.2.4 replaces it:
time from the CPU time-stamp counter instead of TIMER64P0 (now only observed), every wait bounded, a failed stage
before the display works switches the unit off 5 s x its code later (2 PSC, 3 OLED command, 4 splash frame), and a
matrix key held at power-on switches the unit off at once as proof the image runs. 0.2.4 ran once and reported fault 3 (run 2 above); 0.2.5 adds the SPIPC0 = `0x0E01` write after the
master-mode write, as the stock's driver build does. 0.2.5 ran once (run 3 above) and 0.2.6 replaces it: even x in the
high nibble of the framebuffer byte (the device's order), the stock's pad index 0 lit at value 6 right after the
start-up bytes (a transmit check that needs no legible page), and a count of UART bytes the transmitter never
accepted on the status page. 0.2.6 ran once (run 4 above): the LEDs answered, the text did not. 0.2.7 replaces it:
after the splash a display test pattern (single-pixel lines, even/odd rows, a grey ramp, a checkerboard) stays until
a key is pressed, and the status page is drawn in a 2 x font (12 characters by 9 lines: version and uptime, MCU
version bytes, message / reply / dropped counts, the highest pad reading, keys, encoders, card, app, LED sweep) so its
counters can be read through the scrambling. 0.2.7 ran once (run 5 above): the pattern photograph gave the pixel order
and the 2 x page read. 0.2.8 replaces it: `gfx_pixel` writes the panel's order (row pairs in 128-byte blocks, even and
odd columns in separate halves, the even row in the low nibble), the MCU link is set up before the pattern page (as in
0.2.6, whose LEDs answered), the pattern page polls the UART while it waits, and the status page shows the bytes
received (`RX`, count and last byte) in place of the encoder line. 0.2.8 ran once (run 6 above): the pattern exact, the
text legible, nothing received. 0.2.9 replaces it: `uart1_init` ends with the UART's internal-loopback self-test (`LP OK`
/ `LP BAD` on the status page), the start messages `90`, `B1`, `A0` go out 50 ms apart with the UART polled between
them, `A0` is repeated every 2 s while no reply has come (count shown), the status page is back at 1 x with the whole
48-bit switch word and the encoder counts, the start no longer waits on the pattern page (REC shows it when no app is
loaded). None of the ten earlier images went on a card again.

## M1 bench session (image 0.3.1, run 2026-11-16, core scope)

`experiments/D3_audio_0.3.1.bin`, 68,704 bytes, SHA-256
`6479376788a7bf96c6d68ddcbb0c51b43c5354508eb93afaf06bea050613f7e6` (built 2026-11-16, not published;
rebuilt from source with the same hash). 0.3.0's audio path plus a DIAG page: cache registers, the SPI0 flash ID
(opcodes `9F`, `05`, `15` only), the panel MCU's per-channel rate, key bounce at 10 µs, a pin toggle, low-memory reads,
misaligned accesses, USB0's reserved registers and the EMIFA store. Nothing in it writes flash. Protocol and results:
`experiments/sessions/M1-bench.md`; photographs.

Run on card A, then stock 3.2.174 restored from card B (H0); SYSTEM INFO afterwards BOOT 1.0.17, PRESET 2.0.22,
SYSTEM 3.2.174, MCU 1.0.6. Core scope only: D3, D4, E2, F (L1), G1-G6, H1-H2 and I3 not run. Results in the registry:
HW-52 (observed), HW-54 to HW-60.

## M2 bench session (image 0.3.2, run 2026-11-18)

`experiments/D3_audio_0.3.2.bin`, SHA-256 `a09d1d3df11853e8b8ad5e20f8eb2b51dbd3a188b91fb65252f526909632f090` (built
2026-11-18, not published; rebuilt from source with the same hash). The bench image plus views for reserved low
memory (reads and stores), misaligned LDH/LDHU/STH/STDW, stores at both ends of EMIFA CS0, interrupts during a
multicycle NOP and IDLE, the reciprocal-estimate tables, and the panel MCU stream. Nothing in it writes flash.
Protocol and results: `experiments/sessions/M2-bench.md`; photographs.

Parts R, M, L, N, P, W and X run on card A; no view froze. Not done: P2 (no batteries), P3 (the pad trigger fired on
idle noise; fixed in 0.3.3, SHA-256 `89fa94f7a9962b81b680cd08bb8f9fcfcda20391307d5a93bca2f1a0e6817da5`, never run on its
own), and the stock part S, which starts with the restore, so 0.3.2 stayed installed. Results in the registry: HW-55
and HW-58 notes, HW-62 to HW-68.

## M3 bench session (image 0.3.4, run 2026-11-19)

`experiments/D3_audio_0.3.4.bin`, SHA-256 `c314d0db55a9711432e5b486cffbe3240b70c822767d6694f46278394ee75787` (built
2026-11-19, not published). 0.3.3 plus three views: SIDE (held load data per data path), NOP2 (interrupt period and
timing) and RCP2 (reciprocal estimates on inputs with low mantissa bits set). Protocol:
`experiments/sessions/M3-bench.md`; photographs.

Run 2026-11-19 (photos 16:56-17:05 local) on card A over 0.3.2. The session sheet's results table was not filled in;
the values are recorded where the emulator uses them (`emulator/README.md`): SIDE, each data path holds its own load
data, and a load in a handler counts; RCP2, only the top eight mantissa bits of the input count; NOP2, period and loop
length agree with the image, the request-to-handler delay varies with loop position (N3), a period written to a
running timer was not taken up in 4,096 writes, and N4's pattern changed after its first 32 interrupts (unexplained);
PADR B (P3), the shape of a soft and a firm pad hit at 262 samples a second. P2 and the stock part K were not
reported, nor the device state at the end.
