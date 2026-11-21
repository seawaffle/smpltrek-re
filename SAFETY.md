# Safety: what can and cannot brick a SmplTrek

How updates, boot and recovery work, and what each kind of change risks. Every claim gives its evidence level:
- **device**: observed on the unit in a recorded device session. Session codes cited here (C1, C2, A2a, A2b, A3, W1,
  S2, A4, C3, C5, D0, D1, M1, M2, M3) are among the runs in the session table of
  [experiments/README.md](experiments/README.md), which also lists runs 1 and 2, the USB and Step 1 checks, and the
  planned sessions; per-session files are in [experiments/sessions/](experiments/sessions);
- **static**: read from the code, not tested;
- **file**: checked against the official update files or the flash dump.

Claim IDs refer to `claims.json`.

**Scope.** Everything here comes from **one unit**: BOOT 1.0.17, MCU 1.0.6, PRESET 2.0.22 (installed by run 1 over
the factory 1.0.11), with official SYSTEM 1.0.65 (factory), 2.0.129, 3.0.148 and 3.2.174 run on it. Other production runs, or units serviced by Sonicware, may have a different
bootloader, and none of this is checked for them. If SYSTEM INFO shows another BOOT version, treat this document
as unverified for that unit.

## Short version

| Action | Worst expected outcome | Recovery | Evidence |
| --- | --- | --- | --- |
| Flash an official `SmplTrek.bin` (any version, including older) | settings may look different | none needed | device (A3 same version; D1 downgrade to 3.0.148 and back, 2026-11-11) |
| Flash a modified SYSTEM image with every CRC resealed | the modified app misbehaves | HOME + power, flash an official file | device (run 2 and A3, 2026-11-08/09; S2) |
| Flash a file with a wrong outer CRC or family word | refused at "Checking", nothing written | none needed | device (C1, A2a, A2b, 2026-11-09) |
| Flash a file whose outer CRC is right but whose inner (mmtd) CRC is wrong | old SYSTEM erased, new one fails "Verifying", app won't start | HOME + power, flash an official file | static (INT-7); device only up to the confirmation screen (C2, CLR pressed) |
| Power lost or card pulled during a SYSTEM update | the same as the row above | HOME + power, flash an official file | static |
| Custom code hooked to a UI action that crashes or hangs | app hangs after a normal boot | power cycle | device (S2, A4 probes) |
| A foreign SYSTEM image that boots (sterilised Lofi-12 XT, sterilised CyDrums 1.1.84) | a different app runs; some settings read differently | HOME + power, flash an official file | device (C3, 2026-11-11; C5, 2026-11-20, operator report) |
| A SYSTEM image that hangs at boot | unit stays on, frozen on the bootloader's SONICWARE logo, power key dead | remove the supply (adapter, no batteries), then HOME + power, flash an official file | device (D0, 2026-11-12) |
| A bare-metal test image (no Sonicware code) installed as SYSTEM | it runs, hangs or switches the unit off | HOME + power, flash an official file | device (D1 runs 1 to 7, 2026-11-13/14; M1 2026-11-16; M2 2026-11-18) |
| A file with a BOOT, MCU or MCU Boot section | could replace the bootloader or the panel MCU firmware; a bad one could make the unit unrecoverable by software | possibly none without hardware tools | static; never done in any session here |
| Custom code that writes the SPI flash | could erase the bootloader if it first lifts the boot-area protection; could corrupt content or settings | depends on what it hits | static; no test image here writes flash |

The recovery path everything depends on is **HOME held at power-on, then BOOT MODE > SYSTEM UPDATE with an
official `SmplTrek.bin` on the card**. Keep that file on a second card at all times.

## Why HOME + power works even when the app is broken

- The bootloader lives at flash 0..0x40000. It is a TI AIS image that the C6748's ROM loads at power-on
  (file: A4 dump; static: `docs/05-bootloader.md`). Nothing in a SYSTEM update touches that range.
- It tests HOME (bit 27 of the key-matrix word) **before** it loads the SYSTEM image. The key matrix is on the
  C6748's own GPIO, not on the panel MCU (static, `05-bootloader.md` "Power-on decision"). So the SYSTEM image's
  code never runs on the way into BOOT MODE.
- Normal boot does **not** CRC-check the SYSTEM image. It requires only the `mmtd` magic and bit 0 of header +12
  clear, the install marker (static, `05-bootloader.md` "Normal boot"). So a broken image that still has its marker
  is jumped into. That is why a hang at boot is possible, and why HOME is the way out.
- **Proven on the device (D0, 2026-11-12, [D0-hang-recovery.md](experiments/sessions/D0-hang-recovery.md);
  INT-8):** a SYSTEM image whose only instruction branches to itself was installed and jumped into; HOME + power
  reached BOOT MODE at the first try and official 3.2.174 restored. C3 (2026-11-11) had already reached BOOT MODE
  with a foreign app installed, one that booted.
- **What a hung app looks like (device, D0; HW-24):** the unit stays on, frozen on the SONICWARE logo, and the power
  key does nothing. The bootloader initialises the display, draws that logo and latches the power hold before it
  jumps into SYSTEM; the key is read by the app, which is not running. The way off is removing the supply: run risky
  images on the adapter with no batteries fitted, or be ready to take the batteries out.
- If the magic or marker check fails, the bootloader doesn't jump at all; it sets a flag and stays in its own code
  (static). What the screen shows then has not been observed.

## What an update writes

Order of events (static, `05-bootloader.md` "Update file check" and "Writing"; INT-11):
1. **Battery check.** On batteries below a threshold, it refuses to start.
2. **Whole-file CRC and parse.** The outer CRC must match, magic `cmtd`, family word 5. Otherwise "This file is
   invalid" and nothing is written (device: C1, A2a, A2b).
3. **Which sections count.** SYSTEM always counts, whatever its version (device: D1 downgrade). BOOT, PRESET, MCU
   and MCU Boot count only if strictly newer than what is installed, or if nothing is installed (static).
4. **Confirmation.** It lists each section as installed → file version and asks Yes/No; CLR writes nothing
   (device: C2, W1).
5. **Write each counted section:** erase → program → re-read the flash and recompute the CRC ("Verifying")
   → only then program the install marker. "Verifying" compares with the stored CRC, not with the file.

Consequences:
- **Every official SmplTrek release carries only SYSTEM, or PRESET and SYSTEM** (file: all 8 in `firmware/`). None
  has shipped a BOOT, MCU or MCU Boot section, so official updates never touch the bootloader or the panel MCU (file
  + static, INT-9). The same holds for every modern-layout file of every product (SmplTrek, Lofi-12 XT, Liven,
  CyDrums, ELZ_1 play, MINIMAL; `docs/12-update-container.md`). The one exception in the catalogue is the
  legacy-layout ELZ_1 v6.0, which ships BOOT 1.0.10 as a kind-1 image (INT-15).
- **The inner CRC is not checked before erasing** (static, INT-7). A file with a correct outer CRC and a wrong
  mmtd CRC erases the old SYSTEM, fails Verifying and gets no marker. The bootloader then refuses to boot it.
  Recoverable with HOME + power, but the unit has no working app until then. So always reseal every CRC,
  children first (`tools/sonicware_integrity.py reseal`).
- **An interrupted SYSTEM write** (power, card) ends the same way: no marker, bootloader intact, recoverable
  (static).
- **PRESET (content) can't be rewritten by any official file once 2.0.22 is installed.** No release is newer, and
  same-version sections are skipped (static + file). If the content flash were ever damaged, restoring it would
  need a modified file that sets bit 0 of the container's +12 word to skip the version comparison (static,
  untested). No session here writes content, so this matters only as a warning.

## The boot area is write-protected (with caveats)

The bootloader sets the SPI flash's block-protect bits so that the bottom 256 KiB (the bootloader) is
write-protected. It lifts the protection only around a BOOT section write and re-applies it on every BOOT MODE
entry (static, INT-12).
- Both flash devices answer JEDEC ID `C2 20 18` (Macronix, 128 Mbit), and device 0 reads status `0C` /
  configuration `0F`: BP = 0011, TB = 1, the bottom-area protection the bootloader code sets (device, M1
  2026-11-16; HW-54). Reading those bits as exactly 0..256 KiB follows the Macronix MX25L register layout; the exact
  part suffix is not given by the ID.
- The protection lives in the flash's status register. Any code that sends the write-status command can lift it.
  Whether the flash's WP# pin also locks it in hardware is unknown, so treat the protection as a guard against
  accidents, not against code running on the DSP.

## What the running app writes

The stock app writes flash in exactly one place: its settings writer, which erases and programs the top two 4 KiB
sectors of flash device 1 (0x01FFE000 and 0x01FFF000), with a read-back check and the tag written last (static,
XF-2; the same in SmplTrek, Lofi-12 XT and CyDrums). It never writes the bootloader, the SYSTEM image or content.
The bootloader never reads the settings, so a bad settings block can't stop the unit from booting into BOOT MODE
(static).

A cross-flashed Lofi-12 XT app reads SmplTrek's settings block. It range-checks almost every field, so the result
is wrong-but-valid settings rather than wild values (static, XF-13). The image run in C3 was "sterilised": its
settings writer was patched out (`tools/patches/sterilise_lofi.py`), so the foreign app never wrote flash.

## Custom code

Rules followed for every test image run on the unit, and why each is there:
- **No injected code in the stock app at boot.** Every hook into the stock firmware is behind a UI action (S2
  hooks the SYSTEM INFO page). A crash then happens in an app that already booted normally, and a power cycle
  recovers it (device: S2, A4). Bare-metal test images, which replace the app, were run only after D0 proved
  recovery from an app that never runs.
- **No flash writes from custom code.** The A4 dumper only read flash: it was audited read-only, and two dumps were
  identical (device + file). The bare-metal images of D1, M1, M2 and M3 write nothing; the only flash writes in those
  sessions are BOOT MODE's SYSTEM UPDATE (each session file's checklist).
- **No BOOT or MCU section in a test file**, only SYSTEM (type 3) or content (type 2).
- **Every file's SHA-256 is verified on the card before flashing** and recorded, and each session is
  pre-registered in `experiments/`.

## Health check

BOOT MODE > SYSTEM DIAG recomputes the CRCs of the installed BOOT, PRESET and SYSTEM images and queries the panel
MCU's version (static; device: all OK after A3, under 3.0.148 in D1, and with the D0 hang image installed). It's
the quickest check that flash content is intact. Its "Memory Status" step is a stub in BOOT 1.0.17 that always
passes (static).

## Not known

- What the screen shows when normal boot refuses an image (no marker, or bad magic). Testing it means destroying
  the installed SYSTEM on purpose, so it is left untested.
- Whether WP# hardware-locks the boot area, and the flash's exact part suffix.
- The panel MCU's own boot code. The bootloader can program the MCU but has no command to read it back, so the MCU
  firmware can't be dumped this way (static).
- Units with a bootloader other than 1.0.17.
