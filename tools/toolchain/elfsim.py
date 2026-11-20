#!/usr/bin/env python3
"""Run a function from a linked tic6x ELF in the C674x simulator (analysis/c6sim.py).

The simulator was written for Sonicware system images; this module gives it a Program built from an
ordinary ELF executable instead (every SHF_ALLOC section, NOBITS sections zero-filled), with symbols
read by tic6x-elf-nm. Standard library plus the repository's own tools only.

    from elfsim import load, call
    program, symbols = load("test.elf")
    machine = call(program, symbols["abi_driver"], a4=0x40000000)
    words = machine.mem.read(0x40000000, 4 * machine.g("a4"))
"""
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analysis"))
import c6sim          # noqa: E402
import memory_map     # noqa: E402
import packets        # noqa: E402

NM = ROOT / "tools" / "tic6x" / "bin" / "tic6x-elf-nm"
SHF_ALLOC = 2
SHF_EXECINSTR = 4
SHT_NOBITS = 8


def elf_sections(data):
    """(entry, [(address, bytes)], [code section addresses]) of a little-endian ELF32 file.

    Every allocated PROGBITS section is loaded. NOBITS sections (.bss, stack, heap) are left out: the
    simulator reads unmapped memory as zero and keeps writes in an overlay, which is the same thing.
    """
    if data[:4] != b"\x7fELF" or data[4] != 1 or data[5] != 1:
        raise ValueError("not a little-endian ELF32 file")
    entry, shoff = struct.unpack_from("<II", data, 24)[0], struct.unpack_from("<I", data, 32)[0]
    shentsize, shnum = struct.unpack_from("<HH", data, 46)
    sections, code = [], []
    for i in range(shnum):
        name, kind, flags, addr, off, size = struct.unpack_from("<IIIIII", data, shoff + i * shentsize)
        if not flags & SHF_ALLOC or size == 0 or kind == SHT_NOBITS:
            continue
        sections.append((addr, bytes(data[off:off + size])))
        if flags & SHF_EXECINSTR:
            code.append(addr)
    return entry, sections, code


class ElfProgram(c6sim.Program):
    """c6sim.Program over an ELF executable instead of a Sonicware update."""

    def __init__(self, path, extra=()):
        """`extra`: further ELF files whose sections are loaded too, e.g. a module the firmware will copy
        into memory at run time: the simulator fetches instructions from these sections, not from memory
        written during the run, so code loaded at run time must be present here as well."""
        data = Path(path).read_bytes()
        self.name = Path(path).name
        self.entry, self.sections, code = elf_sections(data)
        for other in extra:
            _, more, more_code = elf_sections(Path(other).read_bytes())
            self.sections += more
            code += more_code
        self.image = memory_map.Image(self.sections)
        # packets.listing disassembles the one section holding the address it is given; the GNU
        # linker keeps TI's runtime helpers in sections of their own, so disassemble each code section.
        self.text = {}
        for address in code:
            self.text.update(packets.listing(self.sections, address))
        self.cache = {}


def symbols(path):
    out = subprocess.run([str(NM), str(path)], capture_output=True, text=True, check=True).stdout
    table = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3:
            table[parts[2]] = int(parts[0], 16)
    return table


def load(path):
    return ElfProgram(path), symbols(path)


def call(program, address, max_cycles=2000000, **regs):
    """Run the function at `address` with the given registers (a4=..., b4=..., b14=...) and return the Machine."""
    machine = c6sim.Machine(program, {k.lower(): v & 0xFFFFFFFF for k, v in regs.items()})
    machine.run(address, max_cycles=max_cycles)
    return machine
