#!/usr/bin/env python3
"""Differential check of c6sim against real compiled code: the C functions in c6sim_diff/tests.c are built with
TI's C6000 compiler for the C674x at several optimisation levels and run in c6sim, and the same C is built with
the host gcc; every result must be identical. Read-only; needs no Sonicware files.

Every test function is C with defined behaviour (gcc's UBSan checks the host build), taking four 32-bit words
and returning one. The compiler supplies the instruction forms and schedules: delay-slot use, compact
instructions and PROT fetch packets, SPLOOP/SPLOOPD/SPLOOPW, 40-bit and double-precision operations, CALLP
with A3, and the run-time library (division, 64-bit and floating-point helpers). The images are linked with
--ram_model into 0xC0000000, so initialised data is in the loaded segments and each function can be called
directly with B14 = __TI_STATIC_BASE.

Needs the TI C6000 code generation tools (default ~/ti/ti-cgt-c6000_8.5.0.LTS, or $TI_CGT) and gcc.

Usage (from the repository root):
  python3 -B analysis/c6sim_diff.py                 # six optimisation levels, 80 inputs each (slow)
  python3 -B analysis/c6sim_diff.py --levels O2 --inputs 10
"""
import argparse
import os
from pathlib import Path
import random
import re
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import c6sim       # noqa: E402
import memory_map  # noqa: E402
import packets     # noqa: E402

SOURCE = HERE / "c6sim_diff" / "tests.c"
CGT = Path(os.environ.get("TI_CGT", Path.home() / "ti/ti-cgt-c6000_8.5.0.LTS"))
LEVELS = {"O0": ["-O0"], "O2": ["-O2"], "O3": ["-O3"], "O3s": ["-O3", "-ms3"], "O3sp": ["-O3", "--opt_for_speed=5"],
          "O2s2": ["-O2", "-ms2"]}
LINK = """MEMORY { DDR: o = 0xC0000000, l = 0x00800000 }
SECTIONS { .text > DDR  .const > DDR  .switch > DDR  .data > DDR  .bss > DDR  .far > DDR  .neardata > DDR
           .rodata > DDR  .fardata > DDR  .cinit > DDR  .stack > DDR  .sysmem > DDR  .init_array > DDR }
"""
EDGE = [0, 1, 2, 3, 7, 31, 32, 33, 63, 255, 0x7FFF, 0x8000, 0xFFFF, 0x10000, 0x7FFFFFFF, 0x80000000, 0x80000001,
        0xFFFFFFFF, 0xFFFFFFFE, 0x12345678, 0xDEADBEEF]


def available():
    # cl6x builds the code, gcc the host reference, and tools/tic6x's objdump decodes the result for c6sim.
    return ((CGT / "bin/cl6x").exists() and shutil.which("gcc") is not None
            and (HERE.parent / "tools/tic6x/bin/tic6x-elf-objdump").exists())


def names():
    return re.findall(r"^T\((\w+)\)", SOURCE.read_text(), re.M)


def inputs(n):
    """n input tuples: half from edge values, half random (fixed seed)."""
    rnd = random.Random(6748)
    half = n // 2
    return ([tuple(rnd.choice(EDGE) for _ in range(4)) for _ in range(half)]
            + [tuple(rnd.getrandbits(32) for _ in range(4)) for _ in range(n - half)])


def host_results(work, cases):
    """{(name, a, b, c, d): result} from the gcc build (UBSan on, aborting on any undefined behaviour)."""
    main = ['#include <stdio.h>', '#include <stdint.h>', 'typedef uint32_t u32;']
    main += [f"u32 {n}(u32,u32,u32,u32);" for n in names()]
    main += ['int main(void){ unsigned a,b,c,d; while (scanf("%u %u %u %u",&a,&b,&c,&d)==4) {']
    main += [f'printf("{n} %u %u %u %u %u\\n",a,b,c,d,{n}(a,b,c,d));' for n in names()]
    main += ['} return 0; }']
    (work / "host_main.c").write_text("\n".join(main) + "\n")
    subprocess.run(["gcc", "-std=c99", "-O1", "-fsanitize=undefined", "-fno-sanitize-recover=all", str(SOURCE),
                    str(work / "host_main.c"), "-o", str(work / "host")], check=True)
    out = subprocess.run([str(work / "host")], input="".join(f"{a} {b} {c} {d}\n" for a, b, c, d in cases),
                         capture_output=True, text=True, check=True).stdout
    return {tuple([w[0]] + [int(x) for x in w[1:5]]): int(w[5]) for w in (l.split() for l in out.splitlines())}


def build(work, level):
    """Link tests.c for the C674x at one optimisation level; returns the image path."""
    d = work / level
    d.mkdir()
    (work / "link.cmd").write_text(LINK)
    retain = [f"--retain={n}" for n in names()]
    subprocess.run([str(CGT / "bin/cl6x"), "-mv6740", "--abi=eabi", "--c99", *LEVELS[level], f"-I{CGT / 'include'}",
                    str(SOURCE), "-z", "--ram_model", "-e", "t_arith", *retain, f"-i{CGT / 'lib'}",
                    "-l", "rts6740_elf.lib", str(work / "link.cmd"), "-o", "t.out"],
                   cwd=d, check=True, capture_output=True)
    return d / "t.out"


def elf(path):
    """(PT_LOAD [(address, bytes)], {symbol: value}) of a little-endian ELF32 image."""
    d = Path(path).read_bytes()
    e_phoff, e_shoff = struct.unpack_from("<II", d, 28)
    e_phentsize, e_phnum, e_shentsize, e_shnum = struct.unpack_from("<HHHH", d, 42)
    segs = []
    for i in range(e_phnum):
        p_type, p_offset, p_vaddr, _, p_filesz, p_memsz = struct.unpack_from("<6I", d, e_phoff + i * e_phentsize)
        if p_type == 1 and p_memsz:
            segs.append((p_vaddr, d[p_offset:p_offset + p_filesz] + bytes(p_memsz - p_filesz)))
    shdrs = [struct.unpack_from("<10I", d, e_shoff + i * e_shentsize) for i in range(e_shnum)]
    syms = {}
    for sh in shdrs:
        if sh[1] == 2:                                   # SHT_SYMTAB
            strtab = shdrs[sh[6]]
            for k in range(sh[5] // 16):
                name, value = struct.unpack_from("<II", d, sh[4] + 16 * k)
                s = d[strtab[4] + name:d.index(b"\0", strtab[4] + name)].decode()
                if s:
                    syms[s] = value
    return sorted(segs), syms


def program(path):
    """A c6sim.Program for a linked image, and its symbols."""
    segs, syms = elf(path)
    p = c6sim.Program.__new__(c6sim.Program)
    p.name, p.entry, p.sections = Path(path).name, syms["t_arith"], segs
    p.image = memory_map.Image(segs)
    p.text = packets.listing(segs, p.entry)
    p.cache = {}
    return p, syms


def check(image, expected):
    """[(name, a, b, c, d, wanted, got or exception text)] for every case that differs."""
    prog, syms = program(image)
    bad = []
    for (name, a, b, c, d), want in sorted(expected.items()):
        m = c6sim.Machine(prog, {"a4": a, "b4": b, "a6": c, "b6": d, "b14": syms["__TI_STATIC_BASE"]})
        try:
            got = m.run(syms[name], max_cycles=5_000_000)
        except Exception as ex:                          # noqa: BLE001 - every failure is a finding
            got = f"{type(ex).__name__}: {ex}"
        if got != want:
            bad.append((name, a, b, c, d, want, got))
    return bad


def run(levels, n_inputs):
    """{level: differences}."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        expected = host_results(work, inputs(n_inputs))
        return {lv: check(build(work, lv), expected) for lv in levels}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--levels", nargs="+", default=list(LEVELS), choices=list(LEVELS))
    ap.add_argument("--inputs", type=int, default=80)
    args = ap.parse_args()
    if not available():
        sys.exit(f"needs {CGT / 'bin/cl6x'} and gcc")
    total = 0
    for level, bad in run(args.levels, args.inputs).items():
        print(f"{level}: {len(names()) * args.inputs} runs, {len(bad)} differ")
        for name, a, b, c, d, want, got in bad[:10]:
            print(f"   {name}({a:#x}, {b:#x}, {c:#x}, {d:#x}): want {want:#x}, got {got if isinstance(got, str) else hex(got)}")
        total += len(bad)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
