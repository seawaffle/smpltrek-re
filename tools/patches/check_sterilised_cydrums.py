#!/usr/bin/env python3
"""Check a locally built sterilised CyDrums 1.1.84 image (session C5). Read-only.

This tool builds nothing and writes nothing. It takes the official CyDrums 1.1.84 update and a candidate file
that someone else built, and checks the candidate against the specification in docs/01-platform-map.md,
"The same patch fits CyDrums 1.1.84":

1. The source is the official file (SHA-256 pinned, family word 8, cmtd + mmtd only). There is no CyDrums CRC
   profile, so the hash is the source's only integrity check.
2. In the source, `settings_save` (0xC24C4458) maps through the mmtd section table to file offset 0xACBF8, holds
   the two 16-bit instructions `stw b13` / `stdw b11:b10`, and is followed by the compact header 0xEBC00050.
   Those 8 bytes occur nowhere else in the file.
3. The candidate has the same length and container layout, and both CRCs are valid under the SmplTrek profile.
4. It differs from the source only in the 4 entry bytes (now `mvk .L1 0,a4; bnop .S2 b3,5`), the family word
   (now 5) and the cmtd / mmtd CRC fields. The header after the entry is unchanged.
5. With --decode, the whole 32-byte fetch packet is disassembled with the tic6x binutils (tools/tic6x/bin) in
   the source and the candidate. The entry slots must read as the two new instructions, without `||`, and every
   other line of the packet must read as in the source.

It does not establish device behaviour. Usage:
  python3 -B tools/patches/check_sterilised_cydrums.py firmware/cydrums/CyDrums_v1.1.84.zip CANDIDATE.bin --decode
"""
import argparse
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sonicware_integrity as integrity
import patch_builder

SOURCE_HASH = "e297d23e98b336d40d3e7445a3c98cf4434e9122824793833970cbba0b6e2155"
SOURCE_SIZE = 0x22A72D
SOURCE_FAMILY = 8
FAMILY_OFFSET = 0x10
ENTRY = 0xC24C4458                      # settings_save, CyDrums 1.1.84
ENTRY_OFFSET = 0xACBF8                  # derived from the section table in check(); stated here for the report
PACKET = ENTRY & ~0x1F                  # 0xC24C4440, the compact fetch packet holding the entry
OLD_ENTRY = bytes.fromhex("f7367795")   # stw .D2T2 b13,*b15--(8); stdw .D2T2 b11:b10,*b15--(8)
NEW_ENTRY = bytes.fromhex("2606efa1")   # mvk .L1 0,a4; bnop .S2 b3,5 (p-bits 0: sequential)
HEADER = 0xEBC00050                     # the packet's compact header at ENTRY + 4, must stay
EXPECTED_DECODE = ["mvk .L1 0,a4", "bnop .S2 b3,5"]
BINUTILS = ROOT / "tools" / "tic6x" / "bin"
require = integrity.require


def entry_offset(source, image):
    hits = [off + ENTRY - base for base, off, size in patch_builder.sections(source, image)
            if base <= ENTRY and ENTRY + 8 <= base + size]
    require(len(hits) == 1, f"{ENTRY:#010x} must lie in exactly one section")
    return hits[0]


def source_layout(source):
    """Check the official source; return its mmtd image and the entry's file offset."""
    require(len(source) == SOURCE_SIZE and patch_builder.digest(source) == SOURCE_HASH,
            "source must be the official, unmodified CyDrums 1.1.84 .bin")
    require(integrity.word(source, FAMILY_OFFSET) == SOURCE_FAMILY, "unexpected source family word")
    images = integrity.parse(source)
    require([i.tag for i in images] == ["cmtd", "mmtd"], "source must be a system-only container")
    offset = entry_offset(source, images[1])
    require(offset == ENTRY_OFFSET, f"entry maps to {offset:#x}, expected {ENTRY_OFFSET:#x}")
    require(source[offset:offset + 4] == OLD_ENTRY, "unexpected settings_save entry bytes in the source")
    require(integrity.word(source, offset + 4) == HEADER, "unexpected fetch packet header in the source")
    require(source.count(source[offset:offset + 8]) == 1, "entry + header bytes are not unique in the source")
    return images[1], offset


def check(source, candidate):
    """Return a list of report lines; raise ValueError on the first failed check."""
    lines = []
    src_mmtd, offset = source_layout(source)
    lines.append(f"source: official CyDrums 1.1.84, settings_save {ENTRY:#010x} @ {offset:#x}")
    require(len(candidate) == len(source), "candidate length differs from the source")
    family = integrity.word(candidate, FAMILY_OFFSET)
    require(family == 5, f"family word is {family}, expected 5 (SmplTrek)")

    checks = integrity.verify(candidate, "smpltrek")
    for image, stored, calculated in checks:
        require(stored == calculated, f"{image.tag} CRC invalid under the SmplTrek profile")
        lines.append(f"{image.tag} CRC {stored:08x} valid (SmplTrek profile)")
    images = [item[0] for item in checks]
    require([(i.tag, i.offset) for i in images] == [("cmtd", 0), ("mmtd", src_mmtd.offset)],
            "candidate container layout differs from the source")
    lines.append("family word 5")

    got = candidate[offset:offset + 4]
    require(got == NEW_ENTRY, f"entry bytes {got.hex()}, expected {NEW_ENTRY.hex()}")
    require(integrity.word(candidate, offset + 4) == HEADER, "fetch packet header changed")
    lines.append(f"{ENTRY:#010x} @ {offset:#08x}: {OLD_ENTRY.hex()} -> {NEW_ENTRY.hex()}  "
                 "mvk .L1 0,a4; bnop .S2 b3,5; header ebc00050 kept")

    allowed = set(range(offset, offset + 4)) | set(range(FAMILY_OFFSET, FAMILY_OFFSET + 4))
    for image in images:
        allowed |= set(range(image.offset + 8, image.offset + 12))
    changed = [i for i in range(len(source)) if source[i] != candidate[i]]
    outside = [i for i in changed if i not in allowed]
    require(not outside, "bytes changed outside the specification: "
            + ", ".join(f"{i:#x}" for i in outside[:16]))
    lines.append(f"{len(changed)} bytes differ from the official file: "
                 + ", ".join(f"{i:#x}" for i in changed))
    return lines


def disassemble(packet):
    """Disassemble one 32-byte fetch packet; return (offset, text) per instruction, header included."""
    asm, objdump = BINUTILS / "tic6x-elf-as", BINUTILS / "tic6x-elf-objdump"
    require(asm.exists() and objdump.exists(), "tic6x binutils not found (tools/toolchain/build_tic6x_binutils.sh)")
    require(len(packet) == 32, "a fetch packet is 32 bytes")
    with tempfile.TemporaryDirectory() as tmp:
        src, obj = Path(tmp) / "p.s", Path(tmp) / "p.o"
        src.write_text("".join(f"\t.word 0x{w:08x}\n" for w in struct.unpack("<8I", packet)))
        subprocess.run([str(asm), "-o", str(obj), str(src)], check=True)
        out = subprocess.run([str(objdump), "-d", str(obj)], check=True, capture_output=True, text=True).stdout
    result = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0].strip().endswith(":") and len(parts[1].strip()) in (4, 8):
            result.append((int(parts[0].strip()[:-1], 16), " ".join("\t".join(parts[2:]).split())))
    return result


def decode(source, candidate, offset):
    """Compare the entry's fetch packet in source and candidate; return report lines."""
    start = offset - (ENTRY - PACKET)
    before = disassemble(source[start:start + 32])
    after = disassemble(candidate[start:start + 32])
    slot = ENTRY - PACKET
    new = [text for off, text in after if slot <= off < slot + 4]
    require(new == EXPECTED_DECODE, f"entry decodes as {new}, expected {EXPECTED_DECODE}")
    keep = lambda rows: [(off, text) for off, text in rows if not slot <= off < slot + 4]
    require(keep(before) == keep(after), "rest of the fetch packet decodes differently from the source")
    require(any(off == slot + 4 and "header 0xebc00050" in text for off, text in after),
            "header not decoded as 0xebc00050")
    return [f"{PACKET + off:#010x}: {text}" for off, text in after if off >= slot]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path, help="official CyDrums_v1.1.84 .zip or .bin")
    parser.add_argument("candidate", type=Path, help="the built sterilised .bin to check")
    parser.add_argument("--decode", action="store_true", help="also disassemble the entry's fetch packet")
    args = parser.parse_args(argv)
    try:
        source = patch_builder.read_source(args.source)
        candidate = args.candidate.read_bytes()
        for line in check(source, candidate):
            print(line)
        if args.decode:
            for line in decode(source, candidate, ENTRY_OFFSET):
                print(line)
        print(f"Candidate SHA-256: {patch_builder.digest(candidate)}")
        print("PASS: matches the C5 sterilised-CyDrums specification. "
              "Device behaviour is not established by this check.")
    except (OSError, ValueError, struct.error, subprocess.CalledProcessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
