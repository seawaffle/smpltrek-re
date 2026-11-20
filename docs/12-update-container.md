# Update container and integrity scheme

The format of Sonicware's SD-card update files (`SmplTrek.bin`, `Lofi-12 XT.bin`, `CyDrums.bin`, and the same
container in other products' updates), the CRC scheme that protects it, and what the SmplTrek bootloader checks.
All integers are 32-bit little-endian. Evidence levels as in `SAFETY.md`: **file** (checked against the official
files in `firmware/`), **static** (read from BOOT 1.0.17), **device** (observed on one unit, BOOT 1.0.17).

Tools: `tools/sonicware_integrity.py` (parse, verify, derive, reseal), `tools/palette_swap.py` (rewrap for another
product of the family), `tools/test_integrity.py` with `tools/verified_corpus.json` (corpus record and tests).

## Layout at a glance

```
cmtd container  (24-byte header + N x 24-byte descriptors)
├── pmtd  content image   (descriptor type 2; optional; factory kits, projects, sounds)
└── mmtd  system image    (descriptor type 3; the DSP program)
```

Images follow the descriptors contiguously and exhaust the file: no gaps, no trailing bytes (file, all 14
modern-layout files, INT-1). The SmplTrek 1.0.65 to 2.0.129 updates carry both images; 3.0.148 and 3.2.174 carry
only `mmtd`. Lofi-12 XT and CyDrums updates obtained so far are system-only.

## cmtd container

| Offset | Meaning |
|---|---|
| `0x00` | magic `cmtd` |
| `0x04` | container byte length (= file size) |
| `0x08` | outer CRC |
| `0x0C` | flags word; 0 in every file. The bootloader reads bit 0 as "skip the version comparison" (static, `05-bootloader.md` "Update file check") |
| `0x10` | family word (product number, below) |
| `0x14` | descriptor count N |
| `0x18 + 0x18*i` | descriptor i |

Descriptor: six words `(type, major, minor, build, file_offset, byte_length)`. Type 2 = `pmtd`, type 3 = `mmtd`
(file); the bootloader's parser also knows 1 BOOT (`bmtd`), 4 MCU and 5 MCU Boot (static, INT-9), which no
modern-layout file carries. In every file the descriptor's version equals the version in the image it points to,
and offset and length select exactly that image.

Corrections to an earlier reading of this header (INT-1, 2026-11-08): there is no fixed 48-byte header with a
"format revision". The `2` / `3` at `0x18` is the first descriptor's image type, not a 2023 / 2025 revision;
`0x1C` is the first image's version, not a package version; `0x2C` is the first image's length, not its offset.
A parser that scans for the `mmtd` magic instead of following descriptors can lock onto a payload string;
`tools/sonicware_triage.py` is the older parser and still scans.

### Family word (product number)

| Word | Product | Word | Product |
|---|---|---|---|
| 1 | ELZ_1 (legacy header) | 8 | CyDrums, ELZ_1 play |
| 2 | Liven 8bit warps | 11 | Liven Mega Synthesis |
| 3 | Liven XFM | 12 | Lofi-12 XT |
| 4 | Liven Bass&Beats | 13 | Liven Ambient Ø |
| 5 | SmplTrek | 16 | deconstruct MINIMAL |
| 7 | Liven Lofi-12 | | |

It equals the SysEx device byte of the Liven updates, so it reads as Sonicware's product number in release order,
not a hardware family (file, INT-13). CyDrums and ELZ_1 play share 8 but differ in hardware and in seeds; the
seeds, not the family word, keep their updates apart. The SmplTrek bootloader requires `+0x10 == 5` (static;
device: family-12 files rejected, INT-5).

## pmtd content image

Header: `pmtd`, size, CRC (`+8`), `+12` flags word (`0xFFFFFFFF` in files), version triplet (`+16..+27`),
partition count (`+28`), then 12-byte entries `(4-char tag, flash offset, size)`; the partition data follows
contiguously and exhausts the image (file). SmplTrek 2.0.129:

| Tag | Flash offset | Content |
|---|---|---|
| PKIT | `0x00441000` | drum kits |
| PPRJ | `0x00451000` | factory projects (about 12 MB) |
| PDPT | `0x01000000` | preset drum patterns (added in 2.0; absent in 1.4.99) |
| PDSN | `0x01100000` (`0x01000000` in 1.x) | drum sounds, RIFF WAV |
| PISN | `0x01800000` | instrument sounds, RIFF WAV |

The flash offset is where the partition goes in SPI flash, not where it sits in the file: in 2.0.129, PDSN occupies
file bytes `[0xBEEA0C, 0x12378C4)` and PISN `[0x12378C4, 0x19B5DF2)`. The flash layout is in `01-platform-map.md`
"SPI flash layout"; the content is Sonicware's and is not reproduced here.

## mmtd system image

Header (`0x24` bytes): `mmtd`, size, CRC (`+8`), `+12` flags word (`0xFFFFFFFF` in files), version triplet
(`+16..+27`), entry point (`+28`), section count (`+32`). Then `count` sections back to back, each `sect`, load
address, byte size and raw bytes (no compression). `tools/sonicware_integrity.py` requires the sections to end
exactly at the declared size. `analysis/mmtd2elf.py` turns an image into an ELF at the load addresses.

### The `+12` word and versions

In update files `+12` is `0xFFFFFFFF`. Installed images in flash carry `0xFFFFFFFE`: the bootloader programs bit 0
clear as the last step of a write, as the install marker, and normal boot requires it clear (static, INT-11,
INT-7; the A4 flash dump agrees). The image CRC is computed with `+12` as in the file, `0xFFFFFFFF`.

Versions are three unsigned words compared major, minor, build in order. SYSTEM is always written, so downgrades
are accepted (device, 2026-11-11, session D1: 3.0.148 over 3.2.174 and back). BOOT, PRESET, MCU and MCU Boot are
written only when strictly newer than the installed version or when nothing is installed (static, INT-11).

## Integrity: seeded IEEE CRC-32

Every image (the container and each child) carries one CRC word at its own `+8` (file and device, INT-2):

```python
import zlib
def integrity(image: bytes, seed: int) -> int:
    return zlib.crc32(image[:8] + b"\0" * 4 + image[12:], seed)
```

- `image` is the image's full declared extent: magic, size, flags, metadata and payload. For `cmtd` that is the
  whole file, including the children's stored CRC words.
- Only the image's own CRC word is zeroed. No padding, byte swap or extra final XOR.
- The seed is a constant per (product, image type), in zlib's API convention: reflected polynomial `EDB88320`
  (normal `04C11DB7`); a bitwise implementation starts its register at `seed ^ FFFFFFFF` and complements at the end.
- Reseal order: children (`pmtd`, `mmtd`) first, then `cmtd`, because the outer CRC covers the children's CRC
  words. Repairing the outer CRC first leaves it wrong.

The bootloader computes the equivalent form: a plain zlib CRC-32 from 0 with the CRC field **replaced by a fixed
constant** instead of zeroed and seeded (static, BOOT 1.0.17; `05-bootloader.md` "CRC rule"):

| Image | SmplTrek zlib seed | Bootloader fill constant | Where in BOOT 1.0.17 |
|---|---|---|---|
| `cmtd` | `6D2DCD30` | `F2970822` | `0xC709D1C4` |
| `pmtd` | `05C3029C` | `B02C53FD` | `0xC708D2AC` |
| `mmtd` | `1FC67D2F` | `88E83CEB` | `0xC708D4F0` |
| `bmtd` | (not in any SmplTrek file) | `E255264C` | `0xC708D630` |

For a fixed field position the two forms are equivalent (`tools/test_integrity.py` checks this). The constants came
from code, not from fitting, so they confirm the file-level seeds independently: all 22 SmplTrek update images and
the dump's installed BOOT and SYSTEM images match. The seeds are not CRCs of any obvious product or tag string.

How the seeds were found (2026-11-08): an earlier brute force over about 60 checksum families
(`tools/checksum_search.c`) only tried CRC initial registers 0 and `FFFFFFFF` and found nothing. Solving the GF(2)
linear system for an arbitrary initial value and final XOR instead gave, for SmplTrek `cmtd` and `mmtd` fitted to
the first three releases, a full-rank solution with final XOR zero; the five other releases then matched without
refitting.

### Seeds per product

Cross-validated: each seed recovered identically from more than one release (file, INT-3, INT-4, INT-13), and
offered as a `--profile` by `tools/sonicware_integrity.py`:

| Profile | Product | `cmtd` | `pmtd` | `mmtd` | Releases |
|---|---|---|---|---|---|
| `smpltrek` | SmplTrek | `6D2DCD30` | `05C3029C` | `1FC67D2F` | 8 (preset image: 2 distinct, repeated in 6) |
| `lofi12` | Lofi-12 XT | `8061B03E` | | `2929E2B7` | 3 |
| `cydrums` | CyDrums | `9763BE13` | | `2C577CBB` | 2 (1.1.84, 2.0.97 beta; 2026-11-18) |
| `elz1play` | ELZ_1 play | `F21764BC` | `09528EF7` | `2F06AE24` | 3 (2026-11-11) |
| `liven8bit` | Liven 8bit warps | `F79228D4` | `B46329DD` | `743A0A9F` | 3 (`pmtd` from 3.0.76 only) |
| `livenlofi12` | Liven Lofi-12 | `042ECEE9` | | `617E460F` | 2 |
| `livenxfm` | Liven XFM | `D6D0F0EB` | | `B7B66668` | 2 |

Single-release fits, recorded for later cross-validation and deliberately **not** offered as profiles. Any one
(message, CRC) pair admits a fitted seed, so these are exact by construction and carry no weight on their own:

| Product | `cmtd` | `pmtd` | `mmtd` |
|---|---|---|---|
| deconstruct MINIMAL 1.0.58 | `02AED03F` | | `75AE3897` |
| Liven Bass&Beats 1.1.27 | `16A49780` | | `98EB9D96` |
| Liven Mega Synthesis 1.1.37 | `E2E19B2E` | | `53346B44` |
| Liven Ambient Ø 1.5.45 | `6FDEF156` | `9CA23844` | `2D84003D` |

The legacy ELZ_1 layout (seven releases, 2.0.93 to 7.0.124) uses the same rule with seed 0 for every image, i.e. a
plain CRC-32 with the field zeroed; its header order differs (product number, zero, CRC at `0x0C`, count at `0x10`,
descriptors from `0x14`) and `tools/sonicware_integrity.py` rejects it rather than misparse it (INT-15).

### Liven SysEx updates

The Liven products are updated over MIDI. Their `.syx` files carry the same `cmtd` container in messages
`F0 00 48 04 00 00 <device> 7F <command> <payload> F7`: command 0 opens with the 4-byte container length, command 1
carries data (210 bytes per message), command 2 closes. Payload bytes are packed seven per group behind one byte
holding their top bits (bit 6 for the first byte). `sonicware_integrity.py` unwraps `.syx` inputs (`unwrap_sysex`)
and checks the declared length (file, INT-13). Nothing here sends SysEx to a device.

## What the SmplTrek bootloader checks

Order in `UpdateMode` (static, BOOT 1.0.17; `05-bootloader.md` "Update file check"), with the device results:

1. Battery level, card, `SmplTrek.bin` in the card's root.
2. **Outer CRC** over the whole file ("Checking...%"). A 1-bit flip in the outer CRC is rejected (device, probe C1).
3. **Parse**: magic `cmtd`, **family word 5**, descriptors. Family-12 files are rejected whether they carry
   Lofi-12 XT or SmplTrek seeds (device, probes A2a / A2b), so the seeds are selected on the device side, not keyed
   from the file's family word (INT-6).
4. **Anything to write?** SYSTEM always; other kinds only if strictly newer.
5. **Confirmation screen** (installed version → file version per section).

A wrong inner `mmtd` CRC does not stop the file reaching the confirmation screen (device, probe C2, CLR pressed;
INT-5). After OK the writers erase, program, recompute the CRC from flash ("Verifying") and program the install
marker; nothing checks the file's inner CRC before erasing, so a bad inner CRC destroys the installed SYSTEM and
leaves an image without a marker that normal boot refuses (static, INT-7). Normal boot checks only the `mmtd` magic
and the marker, not the CRC. BOOT MODE > SYSTEM DIAG recomputes the installed images' CRCs (device). Practical
rule: reseal every CRC, children first (`SAFETY.md`).

Device confirmations of the scheme (one unit, BOOT 1.0.17; device sessions in `experiments/README.md`): a 3.2.174
with its SYSTEM INFO label changed and both CRCs resealed was accepted, installed and ran (run 2, 2026-11-08), and
SYSTEM DIAG passed it (2026-11-09); a Lofi-12 XT image rewrapped with family word 5 and SmplTrek seeds reached the
confirmation screen (probe W1, 2026-11-09) and its sterilised variant was written and ran (session C3, XF-1).

## Tools that use it

**`tools/sonicware_integrity.py`** (standard library only, no device access):
- `verify --profile P FILES` parses by descriptors (never by magic scan), checks bounds, tags, versions and that
  sections or partitions exhaust each image, refuses a family word that differs from the profile unless
  `--allow-family-mismatch`, and prints stored against computed CRC per image. Inputs: `.bin`, official `.zip`
  (its `cmtd` `.bin` members), Liven `.syx`.
- `derive FILES` fits one seed per image with the final XOR fixed at zero; labelled as a single-sample fit. Seeds
  count only when different releases give the same value.
- `reseal --profile P IN OUT` recomputes child CRCs then the outer CRC into a new file (refuses to overwrite).

**`tools/palette_swap.py`** rewraps an official system-only update of SmplTrek (family 5), Lofi-12 XT (12) or
CyDrums (8) for another of the three. It identifies the source by family word **and** by both CRCs verifying
under that product's seeds (family 8 alone would also match ELZ_1 play), then changes exactly three header words:
the family word at `0x10`, the `mmtd` CRC with the target's `mmtd` seed, and the outer CRC with the target's
`cmtd` seed, in that order. It asserts that no other byte changed and that the result verifies, and refuses
content-bundled files (a foreign `pmtd` would write the target's content partitions), files that fail
verification, and already-converted files. The SmplTrek direction is the transformation the bootloader accepted
in W1 (`tools/test_palette_swap.py` reproduces that artifact byte for byte); the Lofi-12 XT and CyDrums
directions have not run on a unit.

## Validation corpus

`tools/verified_corpus.json` records, for each validated file, its SHA-256, byte length, profile and every image's
offset, size, stored and computed CRC: 23 files, 56 fields, all matching (8 SmplTrek, 3 Lofi-12 XT, 2 CyDrums,
3 ELZ_1 play, 3 Liven 8bit warps, 2 Liven Lofi-12, 2 Liven XFM). `tools/test_integrity.py` checks the record against
the files, so it cannot drift from them. Reproduce with the official files placed in `firmware/` (layout in
`firmware/README.md`):

```sh
python3 -B tools/sonicware_integrity.py verify --profile smpltrek firmware/smpltrek/*.zip   # 22/22
python3 -B tools/sonicware_integrity.py verify --profile lofi12 firmware/lofi12/*.zip       # 6/6
python3 -B tools/sonicware_integrity.py derive firmware/lofi12/*.zip
python3 -B -m unittest discover -s tools -p test_integrity.py -v
```

The tests cover the modern container structures, every validated release, byte-identical resealing of the
originals, a one-byte sample mutation and a system-payload mutation, nested repair order, malformed and legacy
rejection, seed recovery validated on a different release, the bootloader's fill-constant form, and an independent
bitwise CRC over the whole SmplTrek 3.2.174 system image. Synthetic tests run without `firmware/`.

## Open

- Whether the Lofi-12 XT and CyDrums bootloaders check the same fields (only the SmplTrek's is read and tested).
- Single-release seeds (table above) until a second release agrees.
- What the Liven bootloader checks: it ships in no file.
- Bootloaders other than 1.0.17 (every device result is from one unit).
