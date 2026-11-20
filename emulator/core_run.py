#!/usr/bin/env python3
"""Run the compiled C674x core demo or a bounded ELF function harness."""
import argparse
import json
from pathlib import Path
import sys

from build import WORK
from core_demo import demo, symbols
from cpu import CPU, CoreFault


def mapping(text):
    try:
        fields = text.split(":")
        if len(fields) not in (2, 3):
            raise ValueError()
        address, size = int(fields[0], 0), int(fields[1], 0)
        permissions = fields[2] if len(fields) == 3 else "rw"
        if not permissions or any(char not in "rwx" for char in permissions):
            raise ValueError()
        flags = sum(bit for char, bit in (("r", 1), ("w", 2), ("x", 4)) if char in permissions)
        return address, size, flags
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected BASE:SIZE[:rwx], with integer addresses and sizes") from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", type=Path, help="linked C6000 ELF; the default runs the copied-code demo")
    parser.add_argument("--entry", help="ELF entry symbol or integer address")
    parser.add_argument("--map", action="append", default=[], type=mapping, dest="maps", help="additional RAM, e.g. 0x30ff0000:0x10000:rw")
    parser.add_argument("--register", action="append", default=[], help="initial register, e.g. b15=0x30fffff8")
    parser.add_argument("--cycles", type=int, default=100000, help="maximum guest cycles in ELF mode")
    parser.add_argument("--slice-cycles", type=int, default=10000, help="maximum cycles per native run call")
    parser.add_argument("--no-return-sentinel", action="store_true", help="do not install a synthetic caller return address in B3")
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--output", type=Path, help="JSON report file")
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.slice_cycles <= 1000000 or not 1 <= args.cycles <= 1000000000:
            raise ValueError("slice cycles must be 1..1000000 and total cycles 1..1000000000")
        if args.elf is None:
            if args.entry or args.maps or args.register or args.no_return_sentinel:
                raise ValueError("entry, map and register options require --elf")
            report, destination = demo(args.work, args.slice_cycles)
            print(f'C++ core: copied RAM code returned {report["copied_code"]["result"]}; replacement returned {report["replaced_code"]["result"]}')
            print(f'Warm loop: {report["benchmark"]["packets_per_second"]:,.0f} packets/second (decoder startup excluded)')
        else:
            fault = None
            with CPU(args.work) as machine:
                entry = machine.load_elf(args.elf)
                if args.entry:
                    try:
                        entry = int(args.entry, 0)
                    except ValueError:
                        names = symbols(args.elf)
                        if args.entry not in names:
                            raise ValueError(f"unknown entry symbol {args.entry!r}")
                        entry = names[args.entry]
                for address, size, flags in args.maps:
                    machine.map(address, size, flags)
                machine.reset(entry, return_address=None if args.no_return_sentinel else 0xDEAD0000)
                for specification in args.register:
                    name, separator, value = specification.partition("=")
                    if not separator:
                        raise ValueError("register options must look like a4=123")
                    machine.set_register(name, int(value, 0))
                try:
                    while machine.state()["cycles"] < args.cycles:
                        state = machine.run(min(args.slice_cycles, args.cycles - machine.state()["cycles"]))
                        if state["status"] != "budget":
                            break
                except CoreFault as error:
                    fault = str(error)
                report = {"backend": "c++", "mode": "c674x-function-harness", "manifest": machine.manifest,
                          "artifacts": machine.artifacts, "memory_regions": machine.regions,
                          "return_sentinel": not args.no_return_sentinel, "state": machine.state(), "error": fault}
            destination = args.work / "core-run/result.json"
            print(f'C++ core: {report["state"]["status"]}, {report["state"]["cycles"]} cycles, A4={report["state"]["registers"]["a4"]:#010x}')
        destination = args.output or destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(f"Report: {destination}")
        if report.get("error"):
            print(report["error"], file=sys.stderr)
            return 1
        return 0
    except (ValueError, RuntimeError, OSError) as error:
        print(f"compiled core: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
