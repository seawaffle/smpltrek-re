#!/usr/bin/env python3
"""Convert the mmtd system image in a Sonicware update into an ELF32 file.

Each mmtd section becomes one ELF section and one PT_LOAD segment at its load
address. The ELF entry point is the mmtd entry point. The machine is TI C6000
(EM_TI_C6000 = 140), little endian, so Ghidra with the ghidra-c6000 extension
picks C6000:LE:32:default automatically, and tic6x-elf-objdump disassembles it.

Section flags: the section containing the entry point is marked executable
(the code section); all others are data. Override with --exec INDEX.

The output contains Sonicware code: keep it out of the repository (work/
is gitignored).

Usage (from the repository root):
  python3 -B analysis/mmtd2elf.py "firmware/smpltrek/SmplTrek v3.2.174.zip" work/smpltrek-3.2.174.elf
"""
import argparse
import hashlib
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import sonicware_integrity as integrity

EM_TI_C6000 = 140
SHF_WRITE, SHF_ALLOC, SHF_EXECINSTR = 1, 2, 4
PF_X, PF_W, PF_R = 1, 2, 4


def mmtd_sections(data):
    """Return (version, entry, [(load_address, bytes)]) for the container's mmtd image."""
    images = [i for i in integrity.parse(data) if i.tag == "mmtd"]
    integrity.require(len(images) == 1, "expected exactly one mmtd image")
    image = images[0]
    b = data[image.offset:image.offset + image.size]
    entry, count = struct.unpack_from("<2I", b, 28)
    sections, pos = [], 36
    for _ in range(count):
        magic, address, size = struct.unpack_from("<4sII", b, pos)
        integrity.require(magic == b"sect", "invalid section header")
        sections.append((address, bytes(b[pos + 12:pos + 12 + size])))
        pos += 12 + size
    integrity.require(pos == len(b), "sections do not exhaust the mmtd image")
    return image.version, entry, sections


def build_segments_only_elf(entry, sections, exec_indices):
    """ELF with program headers and data only, no section headers or symbols.

    Ghidra maps non-allocated sections (.shstrtab, .symtab, .strtab) as extra memory blocks, and
    ghidra-c6000 v1.2.0's Delayed Calls analyzer crashes on them ("Address Overflow in subtract:
    .shstrtab::0000004a - 0x4b"), which stops call following and leaves most code undiscovered.
    """
    ehsize, phentsize = 52, 32
    offset = ehsize + len(sections) * phentsize
    data_offsets = []
    for _, d in sections:
        offset = (offset + 31) & ~31
        data_offsets.append(offset)
        offset += len(d)
    out = bytearray(offset)
    ident = b"\x7fELF" + bytes([1, 1, 1, 0]) + bytes(8)
    out[0:ehsize] = ident + struct.pack("<HHIIIIIHHHHHH", 2, EM_TI_C6000, 1, entry, ehsize, 0, 0,
                                        ehsize, phentsize, len(sections), 0, 0, 0)
    for i, ((address, d), off) in enumerate(zip(sections, data_offsets)):
        flags = PF_R | (PF_X if i in exec_indices else PF_W)
        struct.pack_into("<8I", out, ehsize + i * phentsize, 1, off, address, address, len(d), len(d), flags, 32)
        out[off:off + len(d)] = d
    return bytes(out)


def build_elf(entry, sections, exec_indices):
    """Lay out: ELF header, program headers, section data, .shstrtab, .symtab, .strtab, section headers."""
    names = [".text" if i in exec_indices else f".sect{i}" for i in range(len(sections))]
    # Disambiguate several executable sections.
    if len(exec_indices) > 1:
        names = [f".text{i}" if i in exec_indices else n for i, n in enumerate(names)]
    shstr = b"\0" + b"".join(n.encode() + b"\0" for n in names) + b".shstrtab\0.symtab\0.strtab\0"
    name_off = {}
    for n in names + [".shstrtab", ".symtab", ".strtab"]:
        name_off[n] = shstr.index(b"\0" + n.encode() + b"\0") + 1
    strtab = b"\0entry\0"
    # Symbols: null, then a global function symbol at the entry point, in the section that holds it.
    entry_shndx = next(i + 1 for i, (a, d) in enumerate(sections) if a <= entry < a + len(d))
    symtab = bytes(16) + struct.pack("<IIIBBH", 1, entry, 0, (1 << 4) | 2, 0, entry_shndx)

    ehsize, phentsize, shentsize = 52, 32, 40
    phnum = len(sections)
    offset = ehsize + phnum * phentsize
    data_offsets = []
    for _, d in sections:
        offset = (offset + 31) & ~31
        data_offsets.append(offset)
        offset += len(d)
    shstr_off = offset
    offset += len(shstr)
    offset = (offset + 3) & ~3
    sym_off = offset
    offset += len(symtab)
    str_off = offset
    offset += len(strtab)
    offset = (offset + 3) & ~3
    shoff = offset
    shnum = len(sections) + 4  # null + sections + shstrtab + symtab + strtab
    shstrndx = len(sections) + 1

    out = bytearray(shoff + shnum * shentsize)
    ident = b"\x7fELF" + bytes([1, 1, 1, 0]) + bytes(8)  # ELFCLASS32, ELFDATA2LSB, EV_CURRENT
    out[0:ehsize] = ident + struct.pack("<HHIIIIIHHHHHH", 2, EM_TI_C6000, 1, entry, ehsize, shoff, 0,
                                        ehsize, phentsize, phnum, shentsize, shnum, shstrndx)
    for i, ((address, d), off) in enumerate(zip(sections, data_offsets)):
        executable = i in exec_indices
        flags = PF_R | (PF_X if executable else PF_W)
        struct.pack_into("<8I", out, ehsize + i * phentsize, 1, off, address, address, len(d), len(d), flags, 32)
        out[off:off + len(d)] = d
    out[shstr_off:shstr_off + len(shstr)] = shstr
    out[sym_off:sym_off + len(symtab)] = symtab
    out[str_off:str_off + len(strtab)] = strtab

    def shdr(index, *fields):
        struct.pack_into("<10I", out, shoff + index * shentsize, *fields)

    for i, ((address, d), off) in enumerate(zip(sections, data_offsets)):
        executable = i in exec_indices
        flags = SHF_ALLOC | (SHF_EXECINSTR if executable else SHF_WRITE)
        shdr(i + 1, name_off[names[i]], 1, flags, address, off, len(d), 0, 0, 32, 0)  # SHT_PROGBITS
    n = len(sections)
    shdr(n + 1, name_off[".shstrtab"], 3, 0, 0, shstr_off, len(shstr), 0, 0, 1, 0)  # SHT_STRTAB
    shdr(n + 2, name_off[".symtab"], 2, 0, 0, sym_off, len(symtab), n + 3, 1, 4, 16)  # SHT_SYMTAB
    shdr(n + 3, name_off[".strtab"], 3, 0, 0, str_off, len(strtab), 0, 0, 1, 0)
    return bytes(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="official update .zip or .bin")
    parser.add_argument("output", type=Path)
    parser.add_argument("--exec", type=int, action="append", metavar="INDEX",
                        help="mark this section index executable (repeatable); default: the one holding the entry")
    parser.add_argument("--segments-only", action="store_true",
                        help="no section headers or symbols (for Ghidra with ghidra-c6000 v1.2.0; see "
                             "build_segments_only_elf)")
    args = parser.parse_args()
    try:
        (name, data), = list(integrity.inputs([args.input]))
        version, entry, sections = mmtd_sections(data)
        exec_indices = set(args.exec or [i for i, (a, d) in enumerate(sections) if a <= entry < a + len(d)])
        integrity.require(exec_indices, "entry point is outside every section; pass --exec")
        builder = build_segments_only_elf if args.segments_only else build_elf
        elf = builder(entry, sections, exec_indices)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(elf)
    except (ValueError, OSError, struct.error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"{name}")
    print(f"  source sha256 {hashlib.sha256(data).hexdigest()}")
    print(f"  mmtd version {'.'.join(map(str, version))}, entry {entry:#010x}, {len(sections)} sections")
    for i, (address, d) in enumerate(sections):
        print(f"  [{i}] {address:#010x}..{address + len(d):#010x} size {len(d):#x}{'  exec' if i in exec_indices else ''}")
    print(f"Wrote {args.output} ({len(elf)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
