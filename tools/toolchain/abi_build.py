#!/usr/bin/env python3
"""Build and run the cl6x versus GCC interoperability test.

    python3 -B tools/toolchain/abi_build.py [OUTDIR]        # default work/abi (gitignored)

Compiles abi_driver.c and abi_funcs.c with TI cl6x (-mv6740 --abi=eabi -O2) and with GCC tic6x-elf
(-march=c674x -O2), links six pairings with the GNU linker, runs each in the C674x simulator through
abi_check.py, and prints a static comparison. Pairings (driver + callees + runtime library):

    ti_ti           cl6x + cl6x + TI rts6740_elf.lib       the reference
    gcc_gcc         GCC  + GCC  + libgcc                   GCC on its own
    ti_gcc          cl6x + GCC  + libgcc                   a cl6x skeleton calling GCC apps
    gcc_ti          GCC  + cl6x + TI rts                   a GCC app calling cl6x code
    gcc_gcc_tirts   GCC  + GCC  + TI rts                   GCC code on TI's runtime helpers
    ti_ti_libgcc    cl6x + cl6x + libgcc                   cl6x code on GCC's runtime helpers

Tool locations: cl6x from $TI_CGT_C6000/bin (default ~/ti/ti-cgt-c6000_8.3.13), GCC and binutils
from tools/tic6x/bin (tools/toolchain/build_tic6x_binutils.sh, tools/toolchain/build_tic6x_gcc.sh).
"""
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import abi_check  # noqa: E402

TI = Path(os.environ.get("TI_CGT_C6000", Path.home() / "ti" / "ti-cgt-c6000_8.3.13"))
CL6X = TI / "bin" / "cl6x"
TI_RTS = TI / "lib" / "rts6740_elf.lib"
BIN = ROOT / "tools" / "tic6x" / "bin"
GCC = BIN / "tic6x-elf-gcc"
LD = BIN / "tic6x-elf-ld"
OBJDUMP = BIN / "tic6x-elf-objdump"
SIZE = BIN / "tic6x-elf-size"
LIBGCC = ROOT / "tools" / "tic6x" / "lib" / "gcc" / "tic6x-elf"

CL6X_FLAGS = ["-mv6740", "--abi=eabi", "-O2"]
GCC_FLAGS = ["-march=c674x", "-mlittle-endian", "-O2", "-ffreestanding", "-fno-builtin"]
TEXT_BASE = "0xC2000000"

PAIRINGS = {
    "ti_ti": ("ti", "ti", "tirts"),
    "gcc_gcc": ("gcc", "gcc", "libgcc"),
    "ti_gcc": ("ti", "gcc", "libgcc"),
    "gcc_ti": ("gcc", "ti", "tirts"),
    "gcc_gcc_tirts": ("gcc", "gcc", "tirts"),
    "ti_ti_libgcc": ("ti", "ti", "libgcc"),
}


def tools_present():
    return CL6X.exists() and GCC.exists() and LD.exists()


def libgcc():
    hits = sorted(LIBGCC.glob("*/c674x/libgcc.a"))
    if not hits:
        raise FileNotFoundError("no c674x libgcc.a under " + str(LIBGCC))
    return hits[-1]


def sh(args, cwd):
    subprocess.run([str(a) for a in args], cwd=cwd, check=True)


def compile_all(out):
    """Compile both sources with both compilers plus the abort stub; returns {("ti"|"gcc", name): path}."""
    objs = {}
    for name in ("abi_driver", "abi_funcs"):
        src = HERE / f"{name}.c"
        ti_obj = out / f"ti_{name}.obj"
        sh([CL6X, *CL6X_FLAGS, "-c", f"--include_path={TI / 'include'}", f"--output_file={ti_obj}", src], out)
        gcc_obj = out / f"gcc_{name}.o"
        sh([GCC, *GCC_FLAGS, "-c", "-o", gcc_obj, src], out)
        objs[("ti", name)] = ti_obj
        objs[("gcc", name)] = gcc_obj
    stub = out / "gcc_abi_stubs.o"
    sh([GCC, *GCC_FLAGS, "-c", "-o", stub, HERE / "abi_stubs.c"], out)
    objs["stub"] = stub
    return objs


def link_all(out, objs):
    elfs = {}
    for name, (driver, funcs, lib) in PAIRINGS.items():
        elf = out / f"{name}.elf"
        library = TI_RTS if lib == "tirts" else libgcc()
        # the abort stub satisfies libgcc's unwinder (pulled in by its division helpers' unwind tables)
        sh([LD, "-EL", f"-Ttext={TEXT_BASE}", "-e", "abi_driver", f"-Map={out / name}.map", "-o", elf,
            objs[(driver, "abi_driver")], objs[(funcs, "abi_funcs")], objs["stub"], library], out)
        elfs[name] = elf
    return elfs


def static_report(objs):
    """Text size, 16-bit instruction count and SPLOOP use of each compiler's abi_funcs object."""
    rows = []
    for compiler in ("ti", "gcc"):
        obj = objs[(compiler, "abi_funcs")]
        size = subprocess.run([str(SIZE), str(obj)], capture_output=True, text=True, check=True).stdout
        text = int(size.splitlines()[1].split()[0])
        dis = subprocess.run([str(OBJDUMP), "-d", str(obj)], capture_output=True, text=True, check=True).stdout
        compact = len(re.findall(r"^ *[0-9a-f]+:\s+[0-9a-f]{4}\s", dis, re.M))
        sploops = len(re.findall(r"\bsploop", dis))
        b14 = len(re.findall(r",b14\s*$", dis, re.M))
        rows.append((compiler, text, compact, sploops, b14))
    print("\nstatic (abi_funcs): compiler, .text bytes, 16-bit instructions, SPLOOPs, writes to B14")
    for row in rows:
        print("   ", *row)


def main(argv):
    out = Path(argv[0]) if argv else ROOT / "work" / "abi"
    if not tools_present():
        print("missing tools: need cl6x at", CL6X, "and GCC at", GCC)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    objs = compile_all(out)
    elfs = link_all(out, objs)
    print("pairings (driver + callees + runtime), simulator results:")
    status = abi_check.main([str(elfs[n]) for n in PAIRINGS])
    static_report(objs)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
