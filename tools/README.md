# Tools

- `palette_swap.py` — rewrap an official SmplTrek / Lofi-12 XT / CyDrums system
  update for a different device of the family: sets the cmtd family word and
  reseals both CRCs with the TARGET device's seeds (9 header bytes total, no
  code changes; exactly the transformation the bootloader accepted in probe
  W1, whose artifact the tests reproduce byte-for-byte). Interactive or
  `python3 -B tools/palette_swap.py FIRMWARE.bin --to smpltrek|lofi12|cydrums`.
  Accepts system-only files (`.bin` or official `.zip`), refuses content-bundled
  files, files that fail seed verification, and already-converted files.
  CyDrums seeds hold across 1.1.84 and 2.0.97 beta (2026-11-18). A CyDrums 1.1.84 image sealed for the SmplTrek
  (sterilised as well, not a plain palette swap) ran on a unit in session C5 (2026-11-20); nothing has been
  flashed to a CyDrums or a Lofi-12 XT.
  Step-by-step guide for newcomers: `../docs/13-palette-swap-howto.md`.
  Tests: `python3 -B -m unittest discover -s tools -p "test_palette*.py"`
- `cydrums_wavetables.py` — list, export and rebuild CyDrums' wavetable bank (`/CyDrums/System/SystemCore.bin`):
  `build SystemCore.bin OUT.bin --set 5=mytable.wav:MyName` replaces slot 5 with your wavetable (2048-sample frames,
  Serum / Vital style, brought to 256 frames). Step-by-step guide: `../docs/18-cydrums-wavetables-howto.md`. Format: `../docs/01-platform-map.md` "CyDrums wavetable bank". Keep the
  bank and anything exported from it local (Sonicware content).
  Tests: `python3 -B -m unittest discover -s tools -p "test_cydrums*.py"` (17, about 20 s); firmware check in the
  emulator: `python3 -B emulator/tests/stock_cydrums_wavetables.py --stock`, then without `--stock`.
- `sonicware_integrity.py` — descriptor-based modern-container parser and recovered
  IEEE CRC-32 verifier. Validated across all eight SmplTrek and three Lofi-12 XT
  releases here. Example:
  `python3 -B tools/sonicware_integrity.py verify --profile smpltrek firmware/smpltrek/*.zip` (profiles: `smpltrek`, `lofi12`, `cydrums`, `elz1play`, `liven8bit`, `livenlofi12`, `livenxfm`; `.syx` inputs are unwrapped first, see below)
  from the repository root. `derive` independently fits per-image seeds;
  `reseal --profile smpltrek INPUT.bin OUTPUT.bin` repairs CRCs into a new local
  file (children before parent), with no device access. Resealed files are
  accepted and run by the bootloader of the test unit (BOOT v1.0.17; proven
  2026-11-08/09, `../experiments/README.md`). Format, seeds and validation:
  `../docs/12-update-container.md`.
- `test_integrity.py` and `verified_corpus.json` — corpus and mutation tests for the
  above, and the recorded SHA-256, length, image offsets and stored/computed CRCs of
  every validated file. `python3 -B -m unittest discover -s tools -p test_integrity.py -v`;
  the whole-corpus tests skip unless every release is in `firmware/`, tests of one file skip when that file is
  missing, and the synthetic tests always run.
- `sonicware_triage.py` — parse cmtd/pmtd/mmtd containers, extract sections, C674x test, RTTI classes.
  Older parser: its `format_rev` label is incorrect and it scans for the
  system-image magic. Use `sonicware_integrity.py` for container boundaries.
- `toolchain/build_tic6x_binutils.sh` — builds GNU binutils 2.42 with the `tic6x-elf` target into `tools/tic6x/`
  (Ubuntu's binutils-multiarch does NOT include TI C6x). No sudo. Skips texinfo docs.
  Disassemble a raw code section:
  `tools/tic6x/bin/tic6x-elf-objdump -D -b binary -m tic6x -EL --adjust-vma=0xC2431C00 CyDrums_sect3.bin > out.dis`
  The script applies `toolchain/patches/binutils-2.42-tic6x-compact-rs.patch` (2026-11-10). Unpatched 2.42 applies a
  fetch-packet header's RS bit (bit 19) to every register field of a compact instruction, so in RS=1 packets it
  printed compact MV with one register 16 too high (a27 for a11, even b38) and the predicate destination of
  compact CMPGT/CMPLT as a16/b16 for A0/B0: about 1% of compact MVs (558 lines in SmplTrek 3.2.174, 346 in
  Lofi-12 XT 1.5.205, 588 in CyDrums 1.1.84, plus 15-20 compares). The patched output matches Ghidra's
  register operands on all 127,204 compact instructions of SmplTrek. Existing builds: rerun the script (it
  rebuilds incrementally) and regenerate `work/*.dis`.
- `find_const_refs.py` — find MVKL/MVKH immediate pairs (how C6x code references strings/globals).
- `checksum_search.c` — brute-force search of ~60 checksum/CRC/hash families × ranges × paddings against
  every image's stored integrity field. `gcc -O2 -o brute checksum_search.c; ./brute manifest.txt mmtd [maxsize] [xf]`
  (manifest line: `path tag img_offset img_size header_len check_decimal`). Its
  zero-match result is superseded: it did not test the recovered CRC seeds.

## C6x assembler and linker

`tools/toolchain/build_tic6x_binutils.sh` builds the full GNU binutils for `tic6x-elf`: `as`, `ld`, `objcopy`,
`objdump`, `readelf`, `nm`, `c++filt`. Round-trip checked on a C674x snippet:

    tic6x-elf-as -mlittle-endian -march=c674x -o t.o t.s
    tic6x-elf-ld -EL -Ttext=0xC1800000 -o t.elf t.o
    tic6x-elf-objcopy -O binary t.elf t.bin
    tic6x-elf-objdump -d t.elf

Notes: a register branch must name a cross path when the register is on the other side
(`B .S2X A4`, not `B .S2 A4`); delay slots are explicit (`NOP 5` after a branch). This is enough for
small hand-written patches and section payloads; C needs TI's cl6x or the GCC in `toolchain/`.
Existing tools still disassemble raw images with
`tic6x-elf-objdump -D -b binary -m tic6x -EL --adjust-vma=<load> code.bin`.

## Liven SysEx updates (2026-11-12)

The Liven products (8bit warps, Lofi-12) are updated over MIDI. Their `.syx` files are the same `cmtd`
container as the SD-card updates, packed into SysEx messages
`F0 00 48 04 00 00 <device> 7F <command> <payload> F7`: command 0 opens with the container length
(4 bytes), command 1 carries data (210 bytes per message), command 2 closes. Payload bytes are packed
seven per group behind one byte holding their top bits (bit 6 for the first byte). The device byte equals
the container's family word (XFM 3, Bass&Beats 4, Lofi-12 7, Mega Synthesis 11, Ambient Ø 13; 8bit warps 2). `sonicware_integrity.py` unwraps `.syx` inputs
(`unwrap_sysex`) and checks that the declared length matches, so `verify`, `derive`, `reseal` and the
corpus tests take them directly. `reseal` writes the resealed bare `cmtd` container; it does not re-pack
it as SysEx. Whether the Liven bootloader checks more than this is unknown: it ships
in no file, and nothing here sends SysEx to any device.
