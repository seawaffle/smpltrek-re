#!/usr/bin/env python3
"""Name firmware functions by matching a TI object file compiled from known source (e.g. FatFs).

Used when the firmware contains an open-source library built with options we cannot reproduce exactly,
so byte matching (lib_match.py) fails. Each function in the object is compared with the firmware
functions in an address range using func_match's normalised instructions, then assigned one-to-one
by descending similarity. An assignment is reported as "consistent" when the object function's calls
to other functions of the object land, under the same assignment, on functions the firmware function
branches to (all of them, or all but one when there are at least two).

Prepare the object with the same compiler (CGT 8.3.13, -mv6740 --abi=eabi -O2 for SmplTrek 3.2.174).
FatFs, as found in SmplTrek 3.2.174, is R0.14a-R0.15a with ffconf.h changes
  FF_USE_MKFS 1, FF_USE_LFN 2, FF_LFN_UNICODE 2, FF_CODE_PAGE 437, FF_FS_REENTRANT 1 (FF_SYNC_t void*),
  FF_FS_LOCK 4, FF_FS_NORTC 1, FF_USE_FIND 1
(the closest found; weighted similarity 0.54, so Sonicware's build still differs).

Usage (from the repository root):
  python3 -B analysis/src_match.py ff.obj "firmware/smpltrek/SmplTrek v3.2.174.zip" \\
      --range 0xc1505400 0xc150cf60 -o work/fatfs-match.json
"""
import argparse
import collections
import difflib
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import func_match

OBJDUMP = func_match.ROOT / "tools/tic6x/bin/tic6x-elf-objdump"
LINE = re.compile(r"^\s*([0-9a-f]+):\t[0-9a-f]+\s*\t(?:\|\|\s*)?(?:\[!?[ab]\d+\]\s*)?(\S+)(?:\s+(.*))?$")
LABEL = re.compile(r"^[0-9a-f]{8} <([^>]+)>:$")
RELOC = re.compile(r"^\s+([0-9a-f]+): R_C6000_\S+\s+\S+")
LOCAL_TARGET = re.compile(r"\b[0-9a-f]+ <([^>]*)>")
MIN_SIMILARITY = 0.3


def object_functions(path):
    """{name: normalised instructions} and {name: set of called object functions} for a TI .obj."""
    lines = subprocess.run([str(OBJDUMP), "-dr", str(path)], capture_output=True, text=True,
                           check=True).stdout.splitlines()
    relocated = {int(m.group(1), 16) for m in map(RELOC.match, lines) if m}
    stub = object.__new__(func_match.Program)
    stub.strings = {}
    bodies, calls, current = {}, collections.defaultdict(set), None
    for line in lines:
        m = LABEL.match(line)
        if m:
            if not m.group(1).startswith("$"):
                current = m.group(1)
                bodies[current] = []
            continue
        m = LINE.match(line)
        if not m or current is None or m.group(2).startswith("<"):
            continue
        address, mnemonic, operands = int(m.group(1), 16), m.group(2).lower(), m.group(3) or ""
        for t in LOCAL_TARGET.finditer(operands):
            if "+" not in t.group(1) and not t.group(1).startswith("$") and t.group(1) != current:
                calls[current].add(t.group(1))
        operands = LOCAL_TARGET.sub("00000000 <x>", operands)  # same token func_match masks to ADDR
        if address in relocated and mnemonic in ("mvk", "mvkl", "mvkh"):
            operands = re.sub(r"^(\S+ )-?\d+,", r"\g<1>99999,", operands)  # relocated: an address half
        bodies[current].append(func_match.Program._normalise(stub, address, mnemonic, operands))
    return bodies, {k: v & bodies.keys() for k, v in calls.items()}


def firmware_branches(program, f):
    """Functions (other than f) that f calls or branches to."""
    k = program.starts.index(f)
    end = program.starts[k + 1] if k + 1 < len(program.starts) else program.image.code[1]
    out = set()
    i = func_match.bisect.bisect_left(program.addresses, f)
    while i < len(program.insns) and program.insns[i][0] < end:
        _, mnemonic, operands = program.insns[i]
        t = func_match.TARGET.search(operands)
        if t and mnemonic in ("b", "bnop", "callp"):
            g = program.function_of(int(t.group()[:8], 16))
            if g is not None and g != f:
                out.add(g)
        i += 1
    return out


def match(bodies, calls, program, lo, hi):
    candidates = [f for f in program.starts if lo <= f < hi]
    firmware = {f: [x if not x.startswith("mvkh STR:") else "mvkh STR" for x in program.body[f]]
                for f in candidates}
    pairs = []
    for name, body in bodies.items():
        for f, other in firmware.items():
            sm = difflib.SequenceMatcher(None, body, other, autojunk=False)
            if sm.real_quick_ratio() < MIN_SIMILARITY or sm.quick_ratio() < MIN_SIMILARITY:
                continue
            r = sm.ratio()
            if r >= MIN_SIMILARITY:
                pairs.append((r, name, f))
    pairs.sort(key=lambda p: (-p[0], p[1], p[2]))
    assigned, used = {}, set()
    for r, name, f in pairs:
        if name not in assigned and f not in used:
            assigned[name] = (f, r)
            used.add(f)
    rows = []
    for name, (f, r) in sorted(assigned.items(), key=lambda kv: kv[1][0]):
        expected = {assigned[c][0] for c in calls.get(name, ()) if c in assigned}
        hits = len(expected & firmware_branches(program, f))
        consistent = bool(expected) and (hits == len(expected) or (len(expected) >= 2 and hits >= len(expected) - 1))
        rows.append({"name": name, "address": f"0x{f:08x}", "similarity": round(r, 3),
                     "calls_checked": len(expected), "calls_found": hits, "consistent": consistent})
    return rows, sorted(set(bodies) - set(assigned))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("object", help="TI ELF object compiled from the library source")
    parser.add_argument("image", help="official update .zip/.bin")
    parser.add_argument("--range", nargs=2, required=True, metavar=("LO", "HI"),
                        help="firmware address range holding the library")
    parser.add_argument("-o", "--output", help="JSON output (keep under work/)")
    args = parser.parse_args()
    bodies, calls = object_functions(args.object)
    program = func_match.load(args.image)
    lo, hi = (int(x, 16) for x in args.range)
    rows, unassigned = match(bodies, calls, program, lo, hi)
    for r in rows:
        flag = "consistent" if r["consistent"] else ""
        print(f"{r['address']} {r['name']:22} similarity {r['similarity']:.2f} "
              f"calls {r['calls_found']}/{r['calls_checked']} {flag}")
    print("unassigned:", unassigned)
    if args.output:
        Path(args.output).write_text(json.dumps({"object": str(args.object), "rows": rows,
                                                 "unassigned": unassigned}, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
