# SmplTrek bootloader (BOOT 1.0.17)

Static trace (from 2026-11-11) of the bootloader captured in the flash dump of device session A4 (`work/a4/A4DUMP.BIN`,
not committed; [`experiments/README.md`](../experiments/README.md) "A4 flash dump"; session codes such as A3, D0, D1
and M1 are the device runs listed there). This covers one unit and one bootloader version. Every claim below says
how it was checked:
- **device**: observed on the unit (session and claim given);
- **file**: checked against the dump or the update files in `firmware/`;
- **static**: read from the disassembly, not run;
- **inference**: reasoning beyond what the code shows.

## Reproduce

```
python3 -B analysis/ais_extract.py work/a4/A4DUMP.BIN --out work/a4/boot-1.0.17
```

`ais_extract.py` parses the AIS stream at flash offset 0 (it never runs it) and writes:
- the 11 loaded sections;
- an ELF;
- a manifest.

The AIS stream does the following:
1. Sequential-read enable.
2. ROM function 6 (PLL and clock setup), then ROM function 3 (DDR setup).
3. 11 section loads into DDR, 0xC7074628..0xC70AEA60.
4. Jump & Close to 0xC70A1160.

The stream ends at 0x36B3C. The rest of the boot area, up to the `bmtd` header at 0x3FFE4, is 0xFF.

The bootloader is built from the same code base as the app. `func_match.py` pairs 711 of its 1261
functions with functions in SmplTrek 3.2.174, and 125 of the pairs carry names from
`symbols/smpltrek-3.2.174.json`. The matched code includes:
- FatFs;
- StarterWare EDMA3 and GPIO;
- the SPI, flash, SD, OLED and UART drivers;
- the power manager, `ControlScan` and `ADControllerUART`.

RTTI names the bootloader-only classes: `BootLoader`, `BootDelegate`, `UpdateMode`, `DiagnosticsMode`,
`Foundation::SystemUpdater`, `RomHandler`, `RomHandlerMCU`, `CatMetaData::ROMSection` and
`SystemVerify`.

## Power-on decision (static)

`BootDelegate` slot 3 (0xC7089F44) runs `power_on_check`, then tests bit 27 of the switch word at
0xC706F278. That word is offset +64 of the key-matrix scanner at 0xC706F238, which is set up
just before, and the same field as the app's `g_control_switch_state`. The scanner reads the
C6748's own GPIO key matrix, not the panel MCU.
- **Bit clear:** the bootloader reads the SYSTEM image from flash (next section).
- **Bit set:** it sets the panel UART to 460800 baud (the app's rate) and starts the BOOT MODE screens:
  SYSTEM UPDATE, SYSTEM DIAG, USB MSC and STORAGE FORMAT.

Bit 27 is HOME in the button map recovered from the app's test page (`g_control_switch_state`). The
manual says to hold a button while pressing power; its icon doesn't survive text extraction. So
"HOME" comes from the bit map, not from the manual.

## Normal boot: loading SYSTEM (static)

`BootLoader` slot 1 (0xC7094E40) is a callback-driven reader:
1. It reads 128 bytes at flash 0x40000.
2. It requires the magic `mmtd` and **bit 0 of header +12 clear**.
3. It takes the entry point from +28 and the section count from +32.
4. For each section it reads a 12-byte `sect` header (tag, load address, length), then reads the data
   straight to its load address.

**Hand-over.** When the last section has been read, the reader calls its delegate's slot 0 with the
entry point. In `BootDelegate` that callback (0xC7089C50) posts message 3 {status 0, entry}. The
handler for that message, `BootDelegate` slot 7 (0xC708A0C8), loads the entry point and branches to it
when it is non-zero (0xC708A0B4).

**Failure.** If the magic or the marker test fails, the reader calls delegate slot 1 instead
(0xC7089C24). That posts message 3 with status 1, and slot 7 then only sets the byte flag at
0xC707444A, which `UpdateMode` also uses. No jump happens. What the unit shows after that isn't
traced.
- The same byte is set to 1 at the end of a successful update, right after "Please restart." is printed
  (`UpdateMode`, 0xC70845F0). A third store is at 0xC7084C50.
- The failed-boot path prints nothing before setting it.
- **Device** (session D0, 2026-11-12): by the time of the jump the bootloader has initialised the OLED, drawn the SONICWARE
  logo and latched the power hold GP4[11]. A SYSTEM that never runs leaves the unit on, showing that logo, with the
  power key dead (HW-24, `experiments/sessions/D0-hang-recovery.md`). Which code draws the logo is not traced.
- Inference: the flag means "done, waiting for power-off". So a refused image probably leaves a
  screen with no app on it, and the unit idles until it is switched off; HOME + power then reaches BOOT MODE as
  usual.
- No reader of the byte was found: no address constant for it except the three stores, and no byte load at a
  matching offset from the nearby bases 0xC7074444 / 0xC707442C was identified.

This path calls **no CRC routine**. The only callers of the CRC-32 routine (0xC709F320) are:
- the update file check;
- the per-image checks (0xC708CFA4..0xC708D6A0). The updater runs these after writing (through
  0xC7096C28), and SYSTEM DIAG's `SystemVerify` runs them (0xC7097DF0..0xC7097E70). So
normal boot trusts any image whose magic is right and whose install marker is cleared.

**The install marker.** Header word +12 is 0xFFFFFFFF in every update file and 0xFFFFFFFE in flash
(see 01-platform-map.md, "SPI flash layout"). Boot refuses an image with bit 0 set. The updater programs
the marker as the **last** step of each SPI-flash section, after the post-write check passes; see
"Writing" below.

## Cache state at the jump (simulated and static 2026-11-15; observed on the unit 2026-11-16, HW-52)

The bootloader has its own SYS/BIOS cache start-up (0xC70996A0, start-up table entry at 0xC70A7C28; no other
caller). `analysis/boot_cache.py` runs it in c6sim (`test_boot_cache.py` pins the result). Decoded with TI
SPRUFK5A Tables 2-2, 3-2 and 4-4. The "Bootloader leaves" column is also what a test image read first thing on the
unit (**device**, session M1, HW-52):

| Register | Bootloader leaves | Stock SmplTrek 3.2.174 then sets (01-platform-map.md) |
|---|---|---|
| L2CFG | 0: no L2 cache, all 256 KiB of L2 is RAM (also the reset value) | 4: all L2 is cache |
| L1PCFG | 4: 32 KiB L1P cache | 4 |
| L1DCFG | 3: 16 KiB L1D cache, 16 KiB L1D RAM at `0x11F00000`-`0x11F03FFF` | 3 |
| MAR with PC set | 17, 128, 192-195, 199 | 17, 128, 192-199 |

- The three sizes are constants in the code (helpers 0xC709BDA0, 0xC709D420, 0xC709D2E0 are each called only
  from the start-up); the MAR bits come from a table in the loaded data.
- MAR 196-198 (`0xC4000000`-`0xC6FFFFFF`) are **not** cacheable at the jump. MAR 199 covers the bootloader itself.
- The bootloader has MAR-change functions besides the start-up (thunks 0xC70A32AC on, 0xC70A32B8 off, both
  branching to 0xC70A3FA0), but nothing calls or points to them (static: no call site, no pointer in the
  loaded sections). So the start-up values are still in force at the jump (inference: no other writer found).
- **No cache operation at the hand-over** (static): `BootDelegate` slot 7 loads the entry point and branches to
  it (0xC708A0B4) with no cache call on the way.
- **During loading** (static): the reader (0xC7094E40) invalidates only its own 128-byte header buffer at 0xC70ACE00
  (Cache_inv thunk 0xC70A4660, called on two of its entry paths) before reading headers into it. Section data is
  requested straight to its load address (0xC7087000) with no cache call in the reader.
- **The flash read is EDMA** (static, 2026-11-15): the bootloader's flash `do_read` (0xC70869E0) sends `03` + address,
  then calls SPIDriver slot 2 (vtable 0xC70A8908, slot 2 0xC708AA88, DMA path 0xC708AA10) with flag 1, in chunks of at most 65535 bytes,
  waiting 1000 ticks on an event after each. That is the same code as the app's (`04-hardware-access.md`, "SPI flash
  on SPI0": receive on EDMA event 14 from SPIBUF into the destination, transmit on event 15), with no cache
  operation anywhere on the path. So the loaded SYSTEM reaches DDR directly, not through the CPU or L1D. With L2
  cache off, the only ways to fetch a stale copy would be L1D or L1P lines already holding SYSTEM addresses, and
  the bootloader's code, data and stack are at 0xC70xxxxx (inference: its heap and buffers were not searched, so a
  CPU access to SYSTEM's range before the jump is not ruled out). Stock SYSTEM boots through the same path, so any image loaded this way starts exactly as
  coherent as stock.
- **On-chip RAM** (static): no instruction builds an L2 (`0x118xxxxx`) or L1D (`0x11Fxxxxx`) address. The stack
  (B15 = 0xC70ABE30 after alignment) and every loaded section are in DDR at `0xC70xxxxx`.

Cache wrappers recognised on the way (each calls `Cache_block` 0xC709AF80 with one block register): Cache_inv
0xC70A6300 (L2IBAR), Cache_wbInv 0xC70A6320 (L2WIBAR), Cache_wb 0xC70A6340 (L2WBAR). Short thunks reach them
(0xC70A3280-0xC70A32A0, 0xC70A4660-0xC70A4678); the SD driver (0xC707Fxxx, 512-byte sectors) is one caller.

## Update file check (static, with file checks where marked)

`UpdateMode` (0xC70850B0) runs these steps in order:

1. **Battery.** If `power_source_read` returns 2 (batteries) and panel channel 15 (UART object +66,
   the battery voltage) is below 2951, it stops with "replace the batteries".
2. **Card.** It detects and mounts the card, then opens `SmplTrek.bin` in the root folder. Separate
   errors cover no card, an unreadable format and a missing file.
3. **Whole-file CRC.** It loads the file into RAM and runs the CRC (0xC709D1A0, the "Checking...%"
   progress). On a mismatch it shows the "file is invalid" error.
4. **Parse** (0xC7090C88). The parser requires:
   - magic `cmtd`;
   - **family word +16 == 5**;
   - a descriptor count at +20, with 24-byte descriptors {kind, version triplet, offset, size}.

   It records which kinds the file contains. A wrong magic or family, or no known kind, gives
   "invalid". This matches the device results in claims INT-5 and INT-6 (family-12 files rejected).
5. **Anything to do?** (0xC7090B14) A SYSTEM section always counts. For BOOT, PRESET, MCU and MCU Boot,
   the installed version is compared with the file's (0xC7090840). The section counts only if **the
   file's version is strictly newer**, unless bit 0 of the container's +12 word is set, which skips the
   comparison. A section also counts when nothing is installed. If nothing counts, the file is
   "invalid".
   - The comparison works through major, minor and build in order. At the first word that differs it
     returns 1 if installed < file (unsigned), otherwise 0; equal versions give 0. Read from the loop
     at 0xC7090864.
   - So a BOOT, PRESET or MCU section with the same or an older version is skipped silently. SYSTEM is
     always written. That fits the same-version restore seen on the device (session A3), and it means a SYSTEM
     downgrade is accepted too. Read from the code, and confirmed on the device on 2026-11-11 (session
     D1): official 3.0.148 was written over 3.2.174 and booted, then 3.2.174 was written back.
   - Bit 0 of +12 is 0 in all 11 SmplTrek and Lofi-12 XT files (file).
6. **Confirm.** The screen lists each section to be written as installed version → file version, then
   asks Yes/No.

### Section kinds

| kind | name | handler | installed version read from |
| --- | --- | --- | --- |
| 1 | BOOT (`bmtd`) | SPI flash `RomHandler` (0xC70745E0) | flash header at 0x3FFE4 |
| 2 | PRESET (`pmtd`) | SPI flash `RomHandler` | flash header at 0x440000 |
| 3 | SYSTEM (`mmtd`) | SPI flash `RomHandler` | flash header at 0x40000 |
| 4 | MCU | `RomHandlerMCU` (0xC70743B8) | the panel MCU's reply (below) |
| 5 | MCU Boot | `RomHandlerMCU` | the panel MCU's reply (below) |

A flash header counts as installed only when bit 0 of its +12 word is clear (static, 0xC7095758).
The kind numbers come from the parser's jump table (0xC70ADA74) and the confirmation screen, which
pairs each kind with its label (static). Kinds 2 and 3 agree with the file format already known
(INT-1).

**Every SmplTrek release in `firmware/` contains only kinds 2 and 3** (file):
- 1.0.65 to 2.0.129 carry PRESET and SYSTEM;
- 3.0.148 and 3.2.174 carry SYSTEM only.

No SmplTrek release, and no modern-layout file of any product, has shipped a BOOT, MCU or MCU Boot section; the
legacy ELZ_1 v6.0 does ship a kind-1 BOOT image (see "A second bootloader sample" at the end). The update functions
exist in 1.0.17, named by RTTI lambda types: `SystemUpdater::updateBootSection`, `updatePresetSection`,
`updateMainSection`, `updateMCUSection` and `updateMCUBootSection`.

## CRC rule, recovered (file)

The bootloader doesn't zero the CRC field and add a seed. It computes a plain zlib CRC-32 (start value
0) over the whole image, with the 4-byte CRC field at +8 **replaced by a fixed constant**:

| image | constant | where in the code | checked against |
| --- | --- | --- | --- |
| cmtd (container) | 0xF2970822 | 0xC709D1C4 | 8/8 SmplTrek files |
| pmtd (PRESET) | 0xB02C53FD | 0xC708D2AC | 6/6 |
| mmtd (SYSTEM) | 0x88E83CEB | 0xC708D4F0 | 8/8; also the installed image in the dump, with +12 put back to 0xFFFFFFFF |
| bmtd (BOOT) | 0xE255264C | 0xC708D630 | the dump: CRC over the 28-byte header (+12 put back to 0xFFFFFFFF) followed by flash 0..0x3FFE4 |

All 22 update-file images match. The constants came from the code, not from fitting, so this
independently confirms the per-image seeds in `tools/sonicware_integrity.py`. For a fixed field
position the two formulations are equivalent (`tools/test_integrity.py` checks this; see `12-update-container.md`).

The BOOT row also shows how a BOOT section is laid out in flash: a 0x3FFE4-byte AIS area, followed by
its 28-byte header, which ends exactly at 0x40000. The CRC covers the header first, but the section in an
update file is the flash image as it lies. The BOOT writer copies it unchanged to flash 0 (see
"Writing").

## Writing (static)

The updater (0xC70860CC) walks the file's descriptors in order. It dispatches on kind through the
jump table at 0xC70ADA88. Each kind is written only if step 5 above said it counts; SYSTEM always is.
The SPI-flash writers share one sequence, implemented in 0xC70855EC and the per-kind functions:
1. erase;
2. program from the file buffer in RAM;
3. **post-write check**: re-read flash and recompute the image CRC (0xC7096C28);
4. only if the check passes, program the 4-byte value 0xFFFFFFFE over header +12 (0xC7085A94). The
   value comes from the initialised global at 0xC70AD8C4, decoded from the copy table.

| kind | erase | program | marker written at |
| --- | --- | --- | --- |
| 3 SYSTEM (0xC7085F74) | 4 MiB from 0x40000 | the image at 0x40000 | 0x4000C |
| 2 PRESET (0xC7085AB4) | the 4 KiB at 0x440000, then each partition's own range from the directory | header + directory at 0x440000, then each payload at its own address | 0x44000C |
| 1 BOOT (0xC7085E10) | 256 KiB from 0 | the section at 0 | 0x3FFF0 |

**What "Verifying" compares.** The post-write check reads the image back from flash and recomputes its
CRC; it does not compare against the file bytes. For SYSTEM, 0xC708D410 does this:
1. reads 4 KiB at 0x40000 and checks `mmtd`;
2. in its copy, sets bit 0 of +12 and puts the fill constant into +8;
3. CRCs the copy, continues over flash from 0x41000 for the rest of the declared size, and compares the
   result with the stored CRC.

Setting bit 0 makes the check give the same answer before and after the marker is written.

**A bad inner CRC (claim INT-7).** No writer checks the file's inner CRC before erasing. For SYSTEM, a
file whose mmtd CRC is wrong would therefore be erased and written in full, fail the post-write check
and never get its marker. Normal boot then refuses it (marker bit set), and the old system is already
gone. This is read from the code, not tested. An interrupted SYSTEM update ends the same way: no
marker. In both cases the unit still has its bootloader and HOME + power, so a good file can be
written again.

**PRESET erase granularity.** Erasing each partition's own range explains the stale 1.x PDSN span
seen in the dump (01-platform-map.md, "SPI flash layout").

**Boot-area write protection.** Flash commands 0x05 (read status) and 0x15 (read configuration)
appear; 0x01 writes status alone or status + configuration.
- Before a BOOT write, 0xC7095110 clears the block-protect bits (status & 0xC3).
- Afterwards, 0xC70952CC sets configuration bit 3, then sets status bits 2-3 and clears 4-5 (BP = 0011).
- On every entry to BOOT MODE, the boot delegate checks this state (0xC7095394) and re-applies it
  if it's missing (0xC70952CC).

Reading 0x15 and writing it as the second byte of 0x01 is the Macronix convention, with configuration
bit 3 = TB (protect from the bottom). On a 128 Mbit Macronix part, BP = 0011 with TB = 1 protects the
bottom 256 KiB, exactly the boot area. The commands and bits are read from the code. **Device** (session M1,
2026-11-16, HW-54): both devices answer `9F` with `C2 20 18`, 128 Mbit Macronix; device 0 reads status `0C` and
configuration `0F` (BP = 0011, TB = 1), the state this section describes; device 1 reads `00` / `07` (no
protection).

**MCU sections** go to `RomHandlerMCU` with Cortex-M flash addresses:

| kind | sequence |
| --- | --- |
| 4 MCU (0xC7085934) | begin command; erase and program the whole section from **0x08003FE0**; end command; check (command 8) |
| 5 MCU Boot (0xC7085764) | begin; erase and program the section minus its first 32 bytes from **0x08000000**; erase the 1 KiB page at 0x08003800 and program those 32 bytes at **0x08003BE0**; end; check |

Each section's 32-byte header ends a 1 KiB page: MCU Boot's at 0x08003BE0..0x08003C00 and MCU's at
0x08003FE0..0x08004000, so the MCU app proper would start at 0x08004000. That mirrors the BOOT header
at the end of the C6748 boot area. The panel MCU is identified elsewhere in the repository as an
Artery AT32F421 (from photos of a public teardown of the panel board). Its flash starts at 0x08000000, and on the
64 KiB parts it is erased in 1 KiB sectors. Both fit these addresses (an earlier reading said "STM32";
AT32F421 is the documented part). No marker is written for MCU
sections. The header written last plays that role for MCU Boot (inference).

## Panel MCU programming (static)

`RomHandlerMCU` talks to the panel MCU over the panel UART (UART object 0xC70734B0, the same
`ADControllerUART` class the app uses). While it works, it takes over that UART's receive delegate.

**Frames from the C6748.** Each frame is 0xF0, a command byte, raw 8-bit payload bytes, then 0xF7. The
payload is not 7-bit encoded, so despite the framing this is not MIDI SysEx.

The sender sets a wait bit before each command, and the matching reply clears it:

| sent | payload | answered by |
| --- | --- | --- |
| command 4, erase | start address rounded down to 1 KiB, then the length counted from that rounded start; u32 each, little-endian | reply 5 with a non-zero fourth byte; reply 5 with fourth byte 0 is a progress report passed to the delegate |
| command 6, program | address u32, then up to 256 data bytes; one frame per 256-byte block | reply 7 (a non-zero second byte releases the wait) |
| command 8 | none | reply 9; used by the updater's check of a written MCU or MCU Boot section |
| the single byte 0x93, unframed | | reply 12; used by SYSTEM DIAG's MCU check |

Replies 1 and 3 answer two more commands that go out through 0xC708B4F4. The updater calls the
wrappers 0xC7096B6C and 0xC7096BA0 before and after writing. For kind 4 (MCU) these send the two
commands. For kind 1 (BOOT) they go to SPI-flash code instead (0xC7095110, 0xC70952CC). For other kinds
they do nothing. The two command bytes are not decoded.

**Replies** are dispatched by their first byte (0xC708B38C). Depending on their fourth byte, replies 9
and 12 either store a 3-byte version or set a pass/fail flag. They feed the MCU and MCU Boot lines and
the checks. The handlers for replies 9 (0xC708B264) and 12 (0xC708B1D8) are the same instructions at two
addresses; both work on the handler object they are given and test byte 3 first. So the reply number does not
decide which line a version feeds; the request that was sent does (static, 2026-11-14).

**The bootloader cannot read the MCU's flash.**
- The `RomHandler` interface has four slots. In the SPI-flash handler, slot 2 (0xC7094058) is a
  chunked read through the flash driver.
- In `RomHandlerMCU`, slot 2 (0xC708AE0C) only counts 256-byte blocks and returns 0. It sends nothing
  on the UART.
- No other frame or command asks the MCU for memory contents.

So the panel MCU's firmware can't be dumped through anything this bootloader sends. Whether the MCU's
own boot code would answer a read command it never receives is unknown.

## SYSTEM DIAG memory status (static)

SYSTEM DIAG first calls 0xC7089328 and shows "Memory Status Error" if it returns non-zero. In 1.0.17
that function is a stub that always returns 0, so the error can't appear. The repair behind it
(0xC70894D0, "Repairing...") calls 0xC70952CC, the boot-area protection above. Boot mode already
applies that protection on every entry. The image checks DIAG does run are `SystemVerify`'s CRC
recomputation for BOOT, PRESET and SYSTEM, and the 0x93 query for the MCU.

## Open items

- What the unit shows after a failed normal boot (flag 0xC707444A set, no jump). Observing it needs a marker-less
  SYSTEM, i.e. a deliberately failed update, which leaves the unit without a SYSTEM until a good file is written
  again; not done for this alone.
- The two MCU begin and end command bytes, and which request yields which version line. Not followed further: they
  belong to the panel MCU programming exchange, and a wrong MCU write could leave the panel MCU without firmware,
  which may not be recoverable without hardware tools (`SAFETY.md`).
- That the bootloader does no cache operation at the hand-over is static; the cache state itself is observed
  (below).

Resolved on the unit (session M1, 2026-11-16): the flash part (HW-54, "Boot-area write protection" above) and the
cache state at the jump (HW-52: L2CFG mode 0, L1PCFG 4, L1DCFG 3, MAR 17, 128, 192-195 and 199 cacheable, read first
thing by an image that never writes them; "Cache state at the jump" above).

## A second bootloader sample: ELZ_1 BOOT 1.0.10 (file, 2026-11-12)

ELZ_1 v6.0 (legacy container layout, `firmware/other`) carries a kind-1 image of exactly 0x40000 bytes:
a TI AIS boot image followed by padding and a trailing 28-byte `bmtd` header, i.e. the boot area as
it sits in flash. Image SHA-256 `d61e63762d23bcf88df5d555f7bfd5dd99f2e4404e926a59a252fc350cb53cda`
(scratch extraction only; the image is Sonicware's and is not committed). `analysis/ais_extract.py`
parses it with the same supported subset as the A4 dump:

| | ELZ_1 BOOT 1.0.10 | SmplTrek BOOT 1.0.17 (A4 dump) |
| --- | --- | --- |
| AIS length | 170224 | 224060 |
| section loads | 8 (0xC2C550A0..0xC2C80260, end exclusive), 166 KiB in total | 11 (0xC7074628..0xC70AEA60, end exclusive), 219 KiB in total |
| entry | 0xC2C77CC0 | 0xC70A1160 |
| function_execute 6 (PLL) | 1966081, 2823, 3 | same |
| function_execute 3 (DDR) | 402718721, 2, 196, 1296418, 642396681, 1007994658, 1170, 0 | same except 1296434 |
| header | version 1.0.10 first, then size 0x40000, CRC, marker | size, CRC, marker, then version |
| header CRC | plain CRC-32, header first, field zeroed (seed 0) | zlib CRC-32 from 0 with the field filled with 0xE255264C |

Same strings as 1.0.17: the `[ELZ_1]$ systemupdate` / `storageformat` / `usbmsc` / `systemdiagnostic`
console lines, `BOOT MODE`, `SYSTEM UPDATE`, `Verifying... ***%, OK`, `Please restart.`, the
`BootLoader` / `UpdateMode` / `BootDelegate` / `UpdateMessageHandler` RTTI names and the SYS/BIOS
runtime (114 strings in common). Differences: its updaters are `USBMSC::SystemUpdater` and
`USBHID::SystemUpdater` (the ELZ_1 updates over USB: "Running USB mass storage mode...") where 1.0.17
has `Foundation::SystemUpdater` over the SD card; it has `> Update BOOT/PRESET/SYSTEM section:` lines
and no MCU or MCU Boot strings at all (the ELZ_1 has no panel MCU); 1.0.17 adds `DiagnosticsMode`,
`SystemVerify`, `RomHandlerMCU`, the `>> MCU Boot` line and the `.kernel_heap` section. So this is an
older build of the same bootloader for an earlier product, with the legacy container format and no
per-product CRC seeds. What it offers: a second sample for the static claims
above (which checks are old, which arrived with the seeded format), and the only field evidence that
the kind-1 BOOT update path has ever run on a shipped product. What it does not offer: anything about
this unit's BOOT 1.0.17 beyond what the dump already shows, and nothing flashable.
