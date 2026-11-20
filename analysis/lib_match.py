#!/usr/bin/env python3
"""Identify library functions in a Sonicware system image by matching TI library object code.

Reads TI ELF libraries (.lib/.a archives, or single .obj files), takes every defined function symbol in
an executable section, masks the instruction words its relocations patch, and searches the image's code
section for the remaining bytes at the same alignment. TI builds each function in its own 32-byte
aligned ".text:<name>" subsection, so a function linked from the same library version and options
appears byte-identical apart from relocated fields.

The match rate is also evidence about the compiler/RTS version: an exact library version gives many
unique matches; a different version gives few, mostly tiny functions.

Matches are reported as unique (one location) or ambiguous (several). Functions shorter than
--min-size bytes are skipped: they match by coincidence too easily.

Usage (from the repository root):
  python3 -B analysis/lib_match.py "firmware/smpltrek/SmplTrek v3.2.174.zip" \
      ~/ti/ti-cgt-c6000_8.5.0.LTS/lib/rts6740_elf.lib -o work/smpltrek-3.2.174.libmatch.json
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mmtd2elf
import sonicware_integrity as integrity

SHT_SYMTAB, SHT_RELA, SHT_REL = 2, 4, 9
SHF_EXECINSTR = 4
STT_FUNC = 2


def archive_members(path):
    """Yield (name, bytes) for each member of a System V / GNU ar archive, or the file itself."""
    data = path.read_bytes()
    if not data.startswith(b"!<arch>\n"):
        yield path.name, data
        return
    pos, long_names = 8, b""
    while pos + 60 <= len(data):
        header = data[pos:pos + 60]
        name = header[:16].decode("latin-1").rstrip()
        size = int(header[48:58].decode().strip())
        body = data[pos + 60:pos + 60 + size]
        pos += 60 + size + (size & 1)
        if name == "//":
            long_names = body
            continue
        if name in ("/", "/SYM64/", "__.SYMDEF", "__.SYMDEF SORTED"):
            continue
        if name.startswith("/") and name[1:].isdigit():
            start = int(name[1:])
            end = long_names.find(b"\n", start)
            name = long_names[start:end].decode("latin-1")
        yield name.rstrip("/"), body


def elf_functions(blob):
    """Yield (name, section_name, alignment, offset_in_section, code_bytes, mask) for defined functions."""
    if blob[:4] != b"\x7fELF" or blob[4] != 1 or blob[5] != 1:
        return  # only ELF32 little endian
    shoff, = struct.unpack_from("<I", blob, 32)
    shentsize, shnum, shstrndx = struct.unpack_from("<HHH", blob, 46)
    sections = [struct.unpack_from("<10I", blob, shoff + i * shentsize) for i in range(shnum)]
    shstr = sections[shstrndx]

    def name_at(table, offset):
        start = table[4] + offset
        return blob[start:blob.index(b"\0", start)].decode("latin-1")

    masks = collections.defaultdict(set)  # section index -> masked word offsets
    for s in sections:
        if s[1] in (SHT_REL, SHT_RELA):
            entsize = 8 if s[1] == SHT_REL else 12
            for k in range(s[5] // entsize):
                r_offset, = struct.unpack_from("<I", blob, s[4] + k * entsize)
                masks[s[7]].add(r_offset & ~3)
    for s in sections:
        if s[1] != SHT_SYMTAB:
            continue
        strtab = sections[s[6]]
        symbols = [struct.unpack_from("<IIIBBH", blob, s[4] + k * 16) for k in range(s[5] // 16)]
        # Function boundaries. Hand-written assembly and static C functions give their symbols size 0:
        # such a function runs to the next function symbol in its section, or to the section end.
        # Compiler-generated local labels ($C$L1, $C$RL0, ...) and assembly loop labels are not
        # boundaries; a real function symbol is global/weak, or local and not starting with '$'
        # (static functions sit at the start of their own .text:<name> subsection).
        def is_boundary(st_name, value, info):
            if info & 0xF != STT_FUNC:
                return False
            if info >> 4 in (1, 2):  # STB_GLOBAL, STB_WEAK
                return True
            name = name_at(strtab, st_name)
            return not name.startswith("$") and value == 0

        starts = collections.defaultdict(set)
        for st_name, value, _, info, _, shndx in symbols:
            if is_boundary(st_name, value, info):
                starts[shndx].add(value)
        for st_name, value, size, info, _, shndx in symbols:
            if not 0 < shndx < len(sections) or not is_boundary(st_name, value, info):
                continue
            target = sections[shndx]
            if not target[2] & SHF_EXECINSTR or value >= target[5]:
                continue
            if size == 0:
                following = [v for v in starts[shndx] if v > value]
                size = (min(following) if following else target[5]) - value
            # TI's st_size can exceed the subsection (e.g. __TI_printfi: 9124 vs 0x20C0); clamp it.
            size = min(size, target[5] - value)
            if size <= 0:
                continue
            code = blob[target[4] + value:target[4] + value + size]
            mask = bytearray(b"\xff" * size)
            for word in masks[shndx]:
                for b in range(word, word + 4):
                    if value <= b < value + size:
                        mask[b - value] = 0
            yield (name_at(strtab, st_name), name_at(shstr, target[0]), max(target[8], 1), value,
                   code, bytes(mask))


def anchor(code, mask, minimum=8):
    """Longest run of unmasked bytes: (start, length)."""
    best, start = (0, 0), None
    for i in range(len(mask) + 1):
        if i < len(mask) and mask[i]:
            if start is None:
                start = i
        elif start is not None:
            if i - start > best[1]:
                best = (start, i - start)
            start = None
    return best if best[1] >= minimum else None


def find_matches(text, base, code, mask, alignment, offset):
    """Addresses where code (with mask) occurs in text at the function's alignment phase."""
    a = anchor(code, mask)
    if a is None:
        return []
    start, length = a
    needle = code[start:start + length]
    found, pos = [], text.find(needle)
    while pos >= 0:
        begin = pos - start
        address = base + begin
        if begin >= 0 and begin + len(code) <= len(text) and (address - offset) % alignment == 0:
            window = text[begin:begin + len(code)]
            if all(m == 0 or w == c for w, c, m in zip(window, code, mask)):
                found.append(address)
        pos = text.find(needle, pos + 1)
    return found


def match(sections, entry, libraries, min_size):
    base, text = next((a, d) for a, d in sections if a <= entry < a + len(d))
    results, seen = [], set()
    for library in libraries:
        for member, blob in archive_members(library):
            for name, section, alignment, offset, code, mask in elf_functions(blob):
                key = (name, code, mask)
                if len(code) < min_size or key in seen:
                    continue
                seen.add(key)
                hits = find_matches(text, base, code, mask, alignment, offset)
                results.append({"name": name, "library": library.name, "member": member, "section": section,
                                "size": len(code), "masked_bytes": mask.count(0), "matches": hits})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="official update .zip or .bin")
    parser.add_argument("libraries", type=Path, nargs="+", help="TI ELF .lib/.a archives or .obj files")
    parser.add_argument("-o", "--output", type=Path, help="JSON output (keep under work/)")
    parser.add_argument("--min-size", type=int, default=32, help="skip functions smaller than this (bytes)")
    args = parser.parse_args()
    try:
        (name, data), = list(integrity.inputs([args.input]))
        version, entry, sections = mmtd2elf.mmtd_sections(data)
        results = match(sections, entry, args.libraries, args.min_size)
    except (ValueError, OSError, struct.error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    unique = [r for r in results if len(r["matches"]) == 1]
    ambiguous = [r for r in results if len(r["matches"]) > 1]
    print(name)
    for library in args.libraries:
        rs = [r for r in results if r["library"] == library.name]
        u = sum(1 for r in rs if len(r["matches"]) == 1)
        print(f"  {library.name}: {len(rs)} functions >= {args.min_size} bytes, {u} unique matches, "
              f"{sum(1 for r in rs if len(r['matches']) > 1)} ambiguous")
    for r in sorted(unique, key=lambda r: -r["size"])[:15]:
        print(f"    {r['matches'][0]:#010x} {r['size']:5d}  {r['name']}  ({r['member']})")
    if args.output:
        doc = {"source": {"file": name, "sha256": hashlib.sha256(data).hexdigest(),
                          "mmtd_version": ".".join(map(str, version))},
               "libraries": [str(p) for p in args.libraries], "min_size": args.min_size,
               "functions": [{**r, "matches": [f"{m:#010x}" for m in r["matches"]]}
                             for r in results if r["matches"]]}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(doc, indent=1) + "\n")
        print(f"Wrote {args.output} ({len(unique)} unique, {len(ambiguous)} ambiguous)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
