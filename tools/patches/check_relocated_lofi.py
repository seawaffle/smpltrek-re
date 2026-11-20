#!/usr/bin/env python3
"""Check a locally built relocated-settings Lofi-12 XT 1.5.205 image (claim XF-15, session C4). Read-only.

This tool builds nothing and writes nothing. It takes the official Lofi-12 XT 1.5.205 update and a candidate
file that someone else built, and checks the candidate against the specification in
docs/01-platform-map.md, "Relocated-settings variant":

1. The source is the official file (SHA-256 pinned).
2. The candidate has the same length and every CRC is valid under the SmplTrek profile.
3. It differs from the source only in the eight instruction words below, the family word (5) and the
   cmtd / mmtd CRC fields. Each of the eight words has exactly the new value, and no other byte changed.
4. Each listed file offset really holds the listed load address (derived from the mmtd section table, not
   taken from the table below).
5. With --decode, the eight new words are disassembled with the tic6x binutils
   (tools/tic6x/bin) and must read as the expected instructions.

It does not establish device behaviour. Usage:
  python3 -B tools/patches/check_relocated_lofi.py firmware/lofi12/Lofi-12XT_v1.5.205.zip CANDIDATE.bin --decode
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

SOURCE_HASH = "a8bffa65919c0a2d4ff2ce77d16301551af4d2964497b8804deed49ce4198026"
SOURCE_SIZE = 0x1A0C29
FAMILY_OFFSET = 0x10
BINUTILS = ROOT / "tools" / "tic6x" / "bin"

# (load address, file offset, old word, new word, expected disassembly of the new word, meaning)
WORDS = [
    (0xC2C8B144, 0x11FB10, 0x02119888, 0x02119788, "set .S1 a4,12,23,a4", "erase sector A 0xFFF000"),
    (0xC2C8B164, 0x11FB30, 0x02119888, 0x02119788, "set .S1 a4,12,23,a4", "write A+0"),
    (0xC2C8B16C, 0x11FB38, 0x02115889, 0x02115789, "set .S1 a4,10,23,a4", "write A+0xC00"),
    (0xC2C8B178, 0x11FB44, 0x0211B888, 0x0211B788, "set .S1 a4,13,23,a4", "erase sector B 0xFFE000"),
    (0xC2C8B194, 0x11FB60, 0x0211B889, 0x0211B789, "set .S1 a4,13,23,a4", "write B+0"),
    (0xC2C8B1A8, 0x11FB74, 0x0200FFE8, 0x02007FE8, "mvkh .S1 16711680,a4", "write B+0xC00 (high half 0x00FF)"),
    (0xC2C8B238, 0x11FC04, 0x02119888, 0x02119788, "set .S1 a4,12,23,a4", "load A"),
    (0xC2C8B29C, 0x11FC68, 0x0211B888, 0x0211B788, "set .S1 a4,13,23,a4", "load B"),
]
require = integrity.require


def file_offset(data, image, address):
    hits = [off + address - base for base, off, size in patch_builder.sections(data, image)
            if base <= address and address + 4 <= base + size]
    require(len(hits) == 1, f"{address:#010x} must lie in exactly one section")
    return hits[0]


def check(source, candidate):
    """Return a list of report lines; raise ValueError on the first failed check."""
    lines = []
    require(len(source) == SOURCE_SIZE and patch_builder.digest(source) == SOURCE_HASH,
            "source must be the official, unmodified Lofi-12 XT 1.5.205 .bin")
    src_images = [item[0] for item in integrity.verify(source, "lofi12")]
    require(len(src_images) == 2 and src_images[1].tag == "mmtd", "source must be a system-only container")
    require(len(candidate) == len(source), "candidate length differs from the source")

    checks = integrity.verify(candidate, "smpltrek")
    for image, stored, calculated in checks:
        require(stored == calculated, f"{image.tag} CRC invalid under the SmplTrek profile")
        lines.append(f"{image.tag} CRC {stored:08x} valid (SmplTrek profile)")
    images = [item[0] for item in checks]
    require([(i.tag, i.offset) for i in images] == [(i.tag, i.offset) for i in src_images],
            "candidate container layout differs from the source")
    require(integrity.word(candidate, FAMILY_OFFSET) == 5, "family word is not 5")
    lines.append("family word 5")

    allowed = set(range(FAMILY_OFFSET, FAMILY_OFFSET + 4))
    for image in images:
        allowed |= set(range(image.offset + 8, image.offset + 12))
    for address, offset, old, new, _, meaning in WORDS:
        require(file_offset(source, src_images[1], address) == offset, f"offset table wrong at {address:#010x}")
        require(integrity.word(source, offset) == old, f"source word at {offset:#x} is not {old:08x}")
        got = integrity.word(candidate, offset)
        require(got == new, f"{address:#010x} ({meaning}): {got:08x}, expected {new:08x}")
        allowed |= set(range(offset, offset + 4))
        lines.append(f"{address:#010x} @ {offset:#08x}: {old:08x} -> {new:08x}  {meaning}")

    changed = [i for i in range(len(source)) if source[i] != candidate[i]]
    outside = [i for i in changed if i not in allowed]
    require(not outside, "bytes changed outside the specification: "
            + ", ".join(f"{i:#x}" for i in outside[:16]))
    instr = [i for i in changed if any(o <= i < o + 4 for _, o, *_ in WORDS)]
    require(len(instr) == 8, f"expected exactly 8 changed instruction bytes, found {len(instr)}")
    lines.append(f"{len(changed)} bytes differ from the official file: "
                 + ", ".join(f"{i:#x}" for i in changed))
    return lines


def decode(words):
    """Disassemble 32-bit words with the tic6x binutils; return one text per word."""
    asm, objdump = BINUTILS / "tic6x-elf-as", BINUTILS / "tic6x-elf-objdump"
    require(asm.exists() and objdump.exists(), "tic6x binutils not found (tools/toolchain/build_tic6x_binutils.sh)")
    with tempfile.TemporaryDirectory() as tmp:
        src, obj = Path(tmp) / "w.s", Path(tmp) / "w.o"
        src.write_text("".join(f"\t.word 0x{w:08x}\n" for w in words))
        subprocess.run([str(asm), "-o", str(obj), str(src)], check=True)
        out = subprocess.run([str(objdump), "-d", str(obj)], check=True, capture_output=True, text=True).stdout
    texts = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0].strip().endswith(":") and len(parts[1].strip()) == 8:
            texts.append(" ".join("\t".join(parts[2:]).replace("||", "").split()))
    require(len(texts) == len(words), "unexpected objdump output")
    return texts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path, help="official Lofi-12XT_v1.5.205 .zip or .bin")
    parser.add_argument("candidate", type=Path, help="the built relocated-settings .bin to check")
    parser.add_argument("--decode", action="store_true", help="also disassemble the eight new words")
    args = parser.parse_args(argv)
    try:
        source = patch_builder.read_source(args.source)
        candidate = args.candidate.read_bytes()
        for line in check(source, candidate):
            print(line)
        if args.decode:
            for (address, _, _, new, expected, _), text in zip(WORDS, decode([w[3] for w in WORDS])):
                require(text == expected, f"{address:#010x}: decodes as '{text}', expected '{expected}'")
                print(f"{address:#010x}: {text}")
        print(f"Candidate SHA-256: {patch_builder.digest(candidate)}")
        print("PASS: matches the XF-15 specification. Device behaviour is not established by this check.")
    except (OSError, ValueError, struct.error, subprocess.CalledProcessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
