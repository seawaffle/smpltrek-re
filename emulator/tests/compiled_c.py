#!/usr/bin/env python3
"""C compiled for the C674x by TI's compiler and by GCC, run in the emulator core and compared with the host.

The functions are those of analysis/c6sim_diff/tests.c (see c6sim_diff.py, which runs them in the
reference simulator): C with defined behaviour, four 32-bit words in and one out, built by cl6x for the
C674x at several optimisation levels and by gcc with UBSan for the host. Every result must be identical.
The compiler supplies what hand-written fixtures cannot: its own SPLOOP, SPLOOPD and SPLOOPW schedules,
delay-slot use, compact instructions, protected loads, 40-bit, 64-bit and floating-point sequences and
the run-time library. `--blocks` repeats each level with compiled blocks installed after one warm-up
pass and requires host code to have run.

The same functions are also built by GCC (tools/tic6x, with libgcc and the few C-library routines of
tests/fixtures/gcc_support.c) at five levels. GCC's code differs from cl6x's in ways that matter here:
its own run-time helpers (integer division fills branch delay slots with a skipped ADDKPC), other
delay-slot and predication habits, and no C library. Each level is built twice:
  - with -fno-reciprocal-math, where every result must equal the host's;
  - with GCC's defaults, under which it divides floats and doubles by a reciprocal estimate (RCPSP,
    RCPDP) refined twice, which is not correctly rounded. A result may then differ from the host only
    where the first build of that level agreed with the host and the reference simulator
    (analysis/c6sim.py) gives the core's value. Such results are counted and printed. What they
    rest on is the estimate both simulators return, the exact reciprocal cut to eight mantissa bits:
    the manual gives its accuracy, not its bits, and the unit has not been measured.

`--interrupts` is a different run of the same images: for a few inputs of every function, one interrupt
is requested at each cycle of the call in turn (at up to 600 evenly spread cycles of a long call). The
handler (tests/fixtures/interrupt_handler.s) pushes registers on the interrupted stack, works with them
and returns, as a compiled handler would. The result must be the uninterrupted one whatever the cycle:
inside branch delay slots, multi-cycle instructions, SPLOOPs and the run-time helpers. GCC levels are
built with -fno-reciprocal-math for this, since only the comparison with the host matters, and with
-fno-schedule-insns2: at -O2 and above GCC 13.3 otherwise releases the stack frame of two of these
functions before their last read of a local array, which no interrupt handler that uses the stack can
survive (see INTERRUPT_SAFE below and the emulator README). The request
is honoured at most once per call; a call that returns before accepting it counts as not interrupted.

Reads no Sonicware files. The TI part needs the TI C6000 code generation tools (default
~/ti/ti-cgt-c6000_8.5.0.LTS, or $TI_CGT); the GCC part needs tools/tic6x/bin/tic6x-elf-gcc; both need
gcc and g++. A part whose compiler is missing is skipped with a note. Not covered: nested loops that
reload the loop buffer (cl6x 8.5 emitted none for any C tried), interrupts, and timing (only results
are compared).

Usage (from the repository root):
  python3 -B emulator/tests/compiled_c.py --levels O2 --gcc-levels O2 --interrupts
  python3 -B emulator/tests/compiled_c.py                  # both compilers, 40 inputs each, with blocks
  python3 -B emulator/tests/compiled_c.py --levels O2 --gcc-levels O2 --inputs 10 --no-blocks
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from build import ROOT
from cpu import CPU, CoreFault
sys.path.insert(0, str(ROOT / "analysis"))
import c6sim_diff

import c6sim

STACK = 0x31000000       # top of a 1 MiB stack outside the image
BUDGET = 5_000_000       # cycles allowed per call
GCC = ROOT / "tools/tic6x/bin/tic6x-elf-gcc"
GCC_LEVELS = ("O0", "O1", "O2", "O3", "Os")
SUPPORT = Path(__file__).resolve().parent / "fixtures/gcc_support.c"


def available():
    return c6sim_diff.available() and shutil.which("g++") is not None


def gcc_available():
    return GCC.exists() and shutil.which("gcc") is not None and shutil.which("g++") is not None


def build_gcc(work, level, exact, extra=()):
    """Link tests.c with GCC at one level; `exact` turns off division by a reciprocal estimate."""
    image = work / f'gcc-{level}{"-exact" if exact else ""}{"".join(extra)}.out'
    subprocess.run([str(GCC), "-march=c674x", "-mlittle-endian", "-std=c99", f"-{level}", "-ffreestanding", "-msdata=none",
                    "-nostdlib", *(["-fno-reciprocal-math"] if exact else []), *extra, str(c6sim_diff.SOURCE), str(SUPPORT), "-lgcc",
                    "-Wl,-Ttext=0xC0000000,-e,t_arith,--defsym=__TI_STATIC_BASE=0", "-o", str(image)],
                   check=True, capture_output=True)
    return image


def reference(image, cases):
    """{case: result or error text} from the reference simulator."""
    program, symbols = c6sim_diff.program(image)
    results = {}
    for name, a, b, c, d in cases:
        machine = c6sim.Machine(program, {"a4": a, "b4": b, "a6": c, "b6": d, "b14": symbols["__TI_STATIC_BASE"]})
        try:
            results[name, a, b, c, d] = machine.run(symbols[name], max_cycles=BUDGET)
        except Exception as error:                           # noqa: BLE001 - every failure is a finding
            results[name, a, b, c, d] = f"{type(error).__name__}: {error}"
    return results


def run_level(work, image, expected, compiled):
    """([(name, a, b, c, d, wanted, got or error text)], cycles in host code) for one linked image."""
    from blocks import compile_blocks
    _, symbols = c6sim_diff.elf(image)
    bad = []
    with CPU(work) as machine:
        machine.load_elf(image)
        machine.map(STACK - 0x100000, 0x100000)

        def call(name, a, b, c, d):
            machine.reset(symbols[name])
            for register, value in dict(a4=a, b4=b, a6=c, b6=d, b15=STACK - 64, b14=symbols["__TI_STATIC_BASE"]).items():
                machine.set_register(register, value)
            try:
                state = machine.run(BUDGET)
            except CoreFault as error:
                return f"fault: {error}"
            return state["registers"]["a4"] if state["status"] == "returned" else f'status {state["status"]}'

        if compiled:
            machine.blocks(True, heat=True)
            for (name, a, b, c, d) in sorted(expected):
                call(name, a, b, c, d)
            compile_blocks(machine, minimum_heat=1)
            machine.blocks(True)
        for (name, a, b, c, d), wanted in sorted(expected.items()):
            got = call(name, a, b, c, d)
            if got != wanted:
                bad.append((name, a, b, c, d, wanted, got))
        return bad, machine.block_state()["block_cycles"] if compiled else 0


HANDLER = Path(__file__).resolve().parent / "fixtures/interrupt_handler.s"
HANDLER_BASE = 0xC8000000
SWEEP = 600              # interrupt request cycles tried per call at most
# GCC 13.3 at -O2, -O3 and -Os may release a function's stack frame before its last read of a local array (two of
# the test functions show it), so a handler that pushes on the interrupted stack corrupts the array: a fault of the
# generated code, on the unit as here. Without its second scheduling pass GCC does not do it.
INTERRUPT_SAFE = ("-fno-schedule-insns2",)


def build_handler(work, gap=0):
    """Assemble and link the interrupt handler; returns its ELF, or None without the DSP binutils."""
    tools = GCC.parent
    if not (tools / "tic6x-elf-as").exists():
        return None
    subprocess.run([str(tools / "tic6x-elf-as"), "-march=c674x", "-mlittle-endian", "--defsym", f"GAP={gap}", "-o", str(work / "handler.o"), str(HANDLER)], check=True, capture_output=True)
    subprocess.run([str(tools / "tic6x-elf-ld"), f"-Ttext={HANDLER_BASE:#x}", "-o", str(work / "handler.elf"), str(work / "handler.o")], check=True, capture_output=True)
    return work / "handler.elf"


def run_interrupts(work, image, handler, expected, compiled):
    """One interrupt at each cycle of each call. Returns ([(name, a, b, c, d, wanted, got, request cycle)],
    calls made, calls in which the interrupt was taken, cycles in host code)."""
    from blocks import compile_blocks
    _, symbols = c6sim_diff.elf(image)
    _, handler_symbols = c6sim_diff.elf(handler)
    counter = handler_symbols["count"]
    bad, calls, taken = [], 0, 0
    with CPU(work) as machine:
        machine.load_elf(image)
        machine.load_elf(handler)
        machine.map(STACK - 0x100000, 0x100000)

        def call(name, a, b, c, d, at):
            machine.reset(symbols[name])
            machine.write(counter, bytes(4))
            for register, value in dict(a4=a, b4=b, a6=c, b6=d, b15=STACK - 64, b14=symbols["__TI_STATIC_BASE"],
                                        csr=0x101, ier=0x13, istp=HANDLER_BASE).items():
                machine.set_register(register, value)
            try:
                state = machine.run(at) if at else None
                if state is None or state["status"] == "budget":
                    if at is not None:
                        machine.set_register("ifr", 0x10)
                    state = machine.run(BUDGET)
            except CoreFault as error:
                return f"fault: {error}", 0, 0
            count = int.from_bytes(machine.read(counter, 4), "little")
            if state["status"] != "returned":
                return f'status {state["status"]}', 0, count
            return state["registers"]["a4"], state["cycles"], count

        if compiled:
            machine.blocks(True, heat=True)
            for (name, a, b, c, d) in sorted(expected):
                call(name, a, b, c, d, None)
                call(name, a, b, c, d, 40)
            compile_blocks(machine, minimum_heat=1)
            machine.blocks(True)
        for (name, a, b, c, d), wanted in sorted(expected.items()):
            got, cycles, count = call(name, a, b, c, d, None)
            if got != wanted or count:
                bad.append((name, a, b, c, d, wanted, got, None))
                continue
            for at in sorted(set(range(cycles)) if cycles <= SWEEP else {index * cycles // SWEEP for index in range(SWEEP)}):
                got, _, count = call(name, a, b, c, d, at)
                calls += 1; taken += count == 1
                if got != wanted or count > 1:
                    bad.append((name, a, b, c, d, wanted, got if count <= 1 else f"handler ran {count} times", at))
                    break
        host = machine.block_state()["block_cycles"] if compiled else 0
    return bad, calls, taken, host


def run_sweep(levels, gcc_levels, inputs, blocks, gap=0):
    """{(label, mode): (differences, calls, calls interrupted, cycles in host code)} for the interrupt sweep.

    With a stack gap the handler leaves `gap` bytes below the interrupted stack pointer alone, and the GCC
    levels are built with GCC's default scheduling."""
    results = {}
    with tempfile.TemporaryDirectory(prefix="smpltrek-compiled-c-irq-") as temporary:
        work = Path(temporary)
        handler = build_handler(work, gap)
        if handler is None:
            return results
        expected = c6sim_diff.host_results(work, c6sim_diff.inputs(inputs))
        images = [(level, c6sim_diff.build(work, level)) for level in levels if available()]
        images += [(f"gcc-{level}", build_gcc(work, level, True, () if gap else INTERRUPT_SAFE)) for level in gcc_levels if gcc_available()]
        for label, image in images:
            for mode in ("interpreter", "blocks") if blocks else ("interpreter",):
                results[label, mode] = run_interrupts(work / f"irq-{label}-{mode}", image, handler, expected, mode == "blocks")
    return results


def run(levels, inputs, blocks):
    """{(level, 'interpreter' or 'blocks'): (differences, runs, cycles in host code)}."""
    results = {}
    with tempfile.TemporaryDirectory(prefix="smpltrek-compiled-c-") as temporary:
        work = Path(temporary)
        expected = c6sim_diff.host_results(work, c6sim_diff.inputs(inputs))
        for level in levels:
            image = c6sim_diff.build(work, level)
            for mode in ("interpreter", "blocks") if blocks else ("interpreter",):
                bad, host = run_level(work / f"core-{level}-{mode}", image, expected, mode == "blocks")
                results[level, mode] = (bad, len(expected), host)
    return results


def run_gcc(levels, inputs, blocks):
    """{(label, mode): (differences, runs, cycles in host code, results differing only by approximate division)}."""
    results = {}
    with tempfile.TemporaryDirectory(prefix="smpltrek-compiled-c-gcc-") as temporary:
        work = Path(temporary)
        expected = c6sim_diff.host_results(work, c6sim_diff.inputs(inputs))
        for level in levels:
            exact_bad = {}
            for exact in (True, False):
                image = build_gcc(work, level, exact)
                label = f'gcc-{level}{"-exact" if exact else ""}'
                for mode in ("interpreter", "blocks") if blocks else ("interpreter",):
                    bad, host = run_level(work / f"core-{label}-{mode}", image, expected, mode == "blocks")
                    approximate = 0
                    if exact:
                        exact_bad[mode] = {row[:5] for row in bad}
                    elif bad:
                        simulated = reference(image, [row[:5] for row in bad])
                        explained = [row for row in bad if row[:5] not in exact_bad[mode] and simulated[row[:5]] == row[6]]
                        approximate, bad = len(explained), [row for row in bad if row not in explained]
                    results[label, mode] = (bad, len(expected), host, approximate)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--levels", nargs="*", default=list(c6sim_diff.LEVELS), choices=list(c6sim_diff.LEVELS),
                        help="cl6x levels (none to skip TI's compiler)")
    parser.add_argument("--gcc-levels", nargs="*", default=list(GCC_LEVELS), choices=list(GCC_LEVELS),
                        help="GCC levels (none to skip GCC)")
    parser.add_argument("--inputs", type=int, default=None, help="inputs per function (default 40, or 4 with --interrupts)")
    parser.add_argument("--no-blocks", action="store_true", help="interpreter only")
    parser.add_argument("--interrupts", action="store_true", help="request an interrupt at each cycle of each call instead")
    parser.add_argument("--stack-gap", type=int, default=0, metavar="BYTES",
                        help="with --interrupts: the handler skips this many bytes (a multiple of 4, up to 32764) below the "
                             "interrupted stack pointer, and GCC keeps its default scheduling")
    args = parser.parse_args(argv)
    if args.stack_gap % 4 or not 0 <= args.stack_gap <= 32764:
        parser.error("--stack-gap must be a multiple of 4 from 0 to 32764")
    if not available() and not gcc_available():
        sys.exit(f"needs {c6sim_diff.CGT / 'bin/cl6x'} or {GCC}, and gcc and g++")
    if args.interrupts:
        problems = 0
        sweep = run_sweep(args.levels, args.gcc_levels, args.inputs or 4, not args.no_blocks, args.stack_gap)
        if not sweep:
            sys.exit(f"--interrupts needs the DSP binutils beside {GCC}")
        for (label, mode), (bad, calls, taken, host) in sweep.items():
            note = f", {host} cycles in host code" if mode == "blocks" else ""
            print(f"{label} {mode}: {calls} interrupted calls ({taken} took the interrupt), {len(bad)} functions differ{note}")
            for name, a, b, c, d, wanted, got, at in bad[:12]:
                print(f"   {name}({a:#x}, {b:#x}, {c:#x}, {d:#x}) request at cycle {at}: want {wanted:#x}, got {got if isinstance(got, str) else hex(got)}")
            problems += len(bad) + (not taken)
        print("PASS" if not problems else "FAIL")
        return 1 if problems else 0
    args.inputs = args.inputs or 40
    rows = {}
    if args.levels and available():
        rows.update({key: (*value, 0) for key, value in run(args.levels, args.inputs, not args.no_blocks).items()})
    elif args.levels:
        print(f"SKIP TI's compiler: {c6sim_diff.CGT / 'bin/cl6x'} not present")
    if args.gcc_levels and gcc_available():
        rows.update(run_gcc(args.gcc_levels, args.inputs, not args.no_blocks))
    elif args.gcc_levels:
        print(f"SKIP GCC: {GCC} not present")
    problems = 0
    for (level, mode), (bad, runs, host, approximate) in rows.items():
        note = f", {host} cycles in host code" if mode == "blocks" else ""
        if approximate:
            note += f"; {approximate} more differ from the host by approximate division only, equal to the reference simulator"
        print(f"{level} {mode}: {runs} runs, {len(bad)} differ{note}")
        seen = set()
        for name, a, b, c, d, wanted, got in bad:
            if name not in seen:
                seen.add(name)
                print(f"   {name}({a:#x}, {b:#x}, {c:#x}, {d:#x}): want {wanted:#x}, got {got if isinstance(got, str) else hex(got)}")
        problems += len(bad)
        if mode == "blocks" and not host:
            print("   no cycle ran in host code")
            problems += 1
    print("PASS" if not problems else "FAIL")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
