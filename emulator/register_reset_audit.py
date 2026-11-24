#!/usr/bin/env python3
"""Compare the emulator's register values after reset with SPRUH79C's reset values (register_map.json).

A fresh board is read register by register, with the register's own width: first PSC0, PSC1 and SYSCFG0 as
they are at power-on, then (after the stock's PSC enables: PSC1 modules 1 and 7, PSC0 modules 0-2 and 5) USB0,
I2C0, McASP0, MMCSD0 and the EDMA3 channel controller. Only the bits whose reset the TRM gives are compared.
Each register is reported as: match, mismatch (both values), or not readable in the emulator (with the reason:
a register the model does not implement faults on access). Registers the stock touches in the register
capture are marked, so the list can be narrowed to what matters.

Usage (from the repository root):
  python3 -B emulator/register_reset_audit.py [--touched work/register-capture/raw.json] [--all]
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build import WORK
from cpu import CPU, CoreFault
from ir import Instruction, instruction

BEFORE_CLOCKS = ("PSC0", "PSC1", "SYSCFG0")
AFTER_CLOCKS = ("USB0", "I2C0", "McASP0", "MMCSD0", "EDMA3CC0")
ENABLES = [(0x01E27000, 1), (0x01E27000, 7), (0x01C10000, 0), (0x01C10000, 1), (0x01C10000, 2), (0x01C10000, 5)]


def touched_registers(raw):
    found = set()
    for run in json.loads(Path(raw).read_text()):
        for phase in run["phases"]:
            for access in phase["mmio"]:
                found.update(range(access["address"], access["address"] + access["size"]))
    return found


def audit(register_map, touched):
    rows = []
    with tempfile.TemporaryDirectory(dir=WORK, prefix="reset-audit-") as work:
        cpu = CPU(Path(work), decode=False)
        cpu.enable_board()
        cpu.map(0xc2100000, 4096, 7)   # an idle loop, so time can pass for the PSC transitions
        for i, text in enumerate(("b .S1 c2100000", "nop 5")):
            pc = 0xc2100000 + 4 * i
            cpu.install(pc, pc + 4, False, pc & ~31, 32, (Instruction * 1)(instruction(pc, text)))
        cpu.reset(0xc2100000, return_address=None)

        def read(address, width):
            return int.from_bytes(cpu.read(address, width // 8), "little")

        def check(peripherals):
            for key, entry in register_map["soc"].items():
                if entry["peripheral"] not in peripherals or "reset" not in entry or not entry.get("known"):
                    continue
                address, width = int(key, 16), entry.get("width", 32)
                row = dict(address=f"{address:#010x}", register=entry["name"], peripheral=entry["peripheral"], width=width,
                           reset=f'{entry["reset"]:#x}', known=f'{entry["known"]:#x}',
                           touched=any(a in touched for a in range(address, address + width // 8)))
                try:
                    value = read(address, width)
                except (CoreFault, ValueError, OSError, RuntimeError) as error:
                    row.update(result="not readable", emulator=str(error).split(":")[0][:80])
                else:
                    differs = (value ^ entry["reset"]) & entry["known"]
                    row.update(result="mismatch" if differs else "match", emulator=f"{value:#x}",
                               differing_bits=f"{differs:#x}" if differs else "")
                rows.append(row)

        check(BEFORE_CLOCKS)
        for base, module in ENABLES:   # the stock's enables, so the peripherals' registers can be reached
            cpu.write(base + 0xA00 + 4 * module, (3).to_bytes(4, "little"))
            cpu.write(base + 0x120, (1).to_bytes(4, "little"))
        cpu.run(64)
        check(AFTER_CLOCKS)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--map", type=Path, default=HERE / "register_map.json")
    parser.add_argument("--touched", type=Path, default=WORK / "register-capture" / "raw.json")
    parser.add_argument("--all", action="store_true", help="list matching registers too")
    parser.add_argument("--json", type=Path, help="write every row here")
    args = parser.parse_args(argv)
    touched = touched_registers(args.touched) if args.touched.exists() else set()
    rows = audit(json.loads(args.map.read_text()), touched)
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1) + "\n")
    for result in ("mismatch", "not readable", "match"):
        selected = [row for row in rows if row["result"] == result]
        print(f"{result}: {len(selected)} ({sum(row['touched'] for row in selected)} touched by the stock)")
        if result == "match" and not args.all:
            continue
        for row in selected:
            print(f'  {"*" if row["touched"] else " "} {row["address"]} {row["peripheral"]:8} {row["register"]:22} '
                  f'TRM {row["reset"]:>10} (bits {row["known"]}) emulator {row["emulator"]}')


if __name__ == "__main__":
    main()
