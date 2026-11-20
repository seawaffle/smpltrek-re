#!/usr/bin/env python3
"""Compare a range of SmplTrek 3.2.174 code with the same code in Lofi-12 XT and CyDrums, constants included.

func_match pairs functions by normalised bodies, which hide immediates. This tool answers the next
question for shared code: is it called with the same values? It disassembles the range in each image
(the other images' start is found through the func_match result, from the matched function at or before
the start), lines the instructions up and reports differences in three groups:

  moved data address  an MVK/MVKL/MVKH whose register also receives an MVKH of a high half >= 0x11000000
                      (DDR or L2), i.e. half of a data address that moved between builds;
  data-page offset    a B14-relative load/store/ADDA whose offset differs (same variable, other layout);
  other               anything else: a real difference in code or constants.

Branch and call targets are replaced by their offset when inside the range, else EXT.

Usage (from the repository root; needs work/*.elf from mmtd2elf.py and the match files):
  python3 -B analysis/region_diff.py 0xC161D560 0xC161DF84
"""
import argparse
import bisect
import difflib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OBJDUMP = ROOT / "tools/tic6x/bin/tic6x-elf-objdump"
SOURCE_ELF = ROOT / "work/smpltrek-3.2.174.elf"
SOURCE_IMAGE = ROOT / "firmware/smpltrek/SmplTrek v3.2.174.zip"
PRODUCTS = [  # (label, elf, func_match result against SmplTrek 3.2.174)
    ("Lofi-12 XT 1.5.205", ROOT / "work/lofi-1.5.205.elf", ROOT / "work/match-3.2.174-Lofi-12XT_v1.5.205.json"),
    ("CyDrums 1.1.84", ROOT / "work/cydrums-1.1.84.elf", ROOT / "work/match-3.2.174-CyDrums_v1.1.84.json"),
]
IMAGES = [ROOT / "firmware/lofi12/Lofi-12XT_v1.5.205.zip", ROOT / "firmware/cydrums/CyDrums_v1.1.84.zip"]  # as PRODUCTS
LINE = re.compile(r"^\s*([0-9a-f]{8}):\s+[0-9a-f]+\s+(.*)$")
TARGET = re.compile(r"\b([0-9a-f]{8}) <[^>]*>")
NOP_SUFFIX = re.compile(r"\s*\|\| nop \d+$")
MVKH = re.compile(r"\bmvkh \.S[12] (\d+),([ab]\d+)")
MVK = re.compile(r"\bmvk[lh]? \.[SL][12] -?\d+,([ab]\d+)")
B14 = re.compile(r"b14")


def parse(text, start, length):
    """objdump -d text -> [(offset, instruction)] with in-range targets as offsets, others as EXT."""
    out = []
    for line in text.splitlines():
        m = LINE.match(line)
        if not m or "fetch packet" in line:
            continue
        ins = NOP_SUFFIX.sub("", m.group(2))

        def target(t):
            a = int(t.group(1), 16)
            return f"+{a - start:#x}" if start <= a < start + length else "EXT"
        out.append((int(m.group(1), 16) - start, TARGET.sub(target, ins)))
    return out


def disassemble(elf, start, length):
    text = subprocess.run([str(OBJDUMP), "-d", f"--start-address={start:#x}",
                           f"--stop-address={start + length:#x}", str(elf)],
                          capture_output=True, text=True, check=True).stdout
    return parse(text, start, length)


def address_registers(insns):
    regs = set()
    for _, ins in insns:
        m = MVKH.search(ins)
        if m and int(m.group(1)) >= 0x11000000:
            regs.add(m.group(2))
    return regs


def classify(line, regs):
    """'address', 'b14' or 'other' for one +/- diff line ('+0x0124 mvk .S1 -5584,a10')."""
    ins = line.split(" ", 1)[1] if " " in line else line
    m = MVK.search(ins)
    if m and m.group(1) in regs:
        return "address"
    if B14.search(ins):
        return "b14"
    return "other"


def compare(base, other):
    """Diff two parsed ranges; return (counts by class, list of 'other' lines)."""
    regs = address_registers(base) | address_registers(other)
    # Align on instruction text only: one inserted instruction shifts every later offset, and diffing
    # offset-prefixed lines would then report the whole rest of the range. Offsets are added back for display.
    sm = difflib.SequenceMatcher(None, [i for _, i in base], [i for _, i in other], autojunk=False)
    diff = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        diff += [f"-{o:#06x} {i}" for o, i in base[i1:i2]] + [f"+{o:#06x} {i}" for o, i in other[j1:j2]]
    counts = {"address": 0, "b14": 0, "other": 0}
    others = []
    for d in diff:
        kind = classify(d, regs)
        counts[kind] += 1
        if kind == "other":
            others.append(d)
    return counts, others


def locate(match_file, start, end):
    """Start in the other image via the matched function at or before start; None when the matched
    functions at both ends of the range disagree on the delta (the code is laid out differently)."""
    pairs = sorted((int(m["a"], 16), int(m["b"], 16)) for m in json.loads(Path(match_file).read_text())["matches"])
    keys = [a for a, _ in pairs]
    i = bisect.bisect_right(keys, start) - 1
    j = bisect.bisect_right(keys, end - 1) - 1
    if i < 0 or j < 0:
        return None
    d = pairs[i][1] - pairs[i][0]
    if pairs[j][1] - pairs[j][0] != d:
        return None
    return start + d


CONST_LO = re.compile(r"\bmvk[l]? \.[SL][12] (-?\d+),([ab]\d+)")
CONST_HI = re.compile(r"\bmvkh \.S[12] (\d+),([ab]\d+)")


def address_constants(insns):
    """Full 32-bit addresses built by MVK(L)+MVKH pairs on one register, in order of the MVKH, for high
    halves >= 0x11000000 (DDR or L2)."""
    low, out = {}, []
    for _, ins in insns:
        m = CONST_LO.search(ins)
        if m:
            low[m.group(2)] = int(m.group(1)) & 0xFFFF
        m = CONST_HI.search(ins)
        if m and int(m.group(1)) >= 0x11000000 and m.group(2) in low:
            out.append((int(m.group(1)) & 0xFFFF0000) | low.pop(m.group(2)))
    return out


def load_image(path):
    """string_refs.Image of an official update (for reading data)."""
    sys.path.insert(0, str(ROOT / "tools"))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import mmtd2elf
    import sonicware_integrity
    import string_refs
    (_, data), = list(sonicware_integrity.inputs([Path(path)]))
    _, entry, sections = mmtd2elf.mmtd_sections(data)
    return string_refs.Image(sections, entry)


def read(image, address, length):
    located = image.locate(address)
    if located is None:
        return None
    a, d = located
    return bytes(d[address - a:address - a + length])


def compare_data(base_insns, other_insns, base_image, other_image, length):
    """Pair the address constants of both ranges in order and compare `length` bytes at each.
    Returns [(base address, other address, equal or None when unreadable)]; None overall when the
    constant counts differ (the pairing would be meaningless)."""
    ca, cb = address_constants(base_insns), address_constants(other_insns)
    if len(ca) != len(cb):
        return None
    out = []
    for a, b in zip(ca, cb):
        x, y = read(base_image, a, length), read(other_image, b, length)
        out.append((a, b, None if x is None or y is None else x == y))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("start", type=lambda s: int(s, 0))
    ap.add_argument("end", type=lambda s: int(s, 0))
    ap.add_argument("--show", type=int, default=40, help="max 'other' lines to print per product")
    ap.add_argument("--at", type=lambda s: int(s, 0), nargs=len(PRODUCTS), metavar="ADDR",
                    help="start addresses in the other products (when the layout differs)")
    ap.add_argument("--data", type=int, default=0, metavar="N",
                    help="also compare N bytes at every address constant (paired in order)")
    args = ap.parse_args()
    length = args.end - args.start
    base = disassemble(SOURCE_ELF, args.start, length)
    base_image = load_image(SOURCE_IMAGE) if args.data else None
    for k, (label, elf, match) in enumerate(PRODUCTS):
        where = args.at[k] if args.at else locate(match, args.start, args.end)
        if where is None:
            print(f"== {label}: range not laid out identically (matched functions at the two ends disagree)")
            continue
        other = disassemble(elf, where, length)
        counts, others = compare(base, other)
        print(f"== {label} at {where:#010x}: {len(base)} vs {len(other)} instructions; differences: "
              f"{counts['address']} moved data address, {counts['b14']} data-page offset, {counts['other']} other")
        for line in others[:args.show]:
            print("  " + line)
        if args.data:
            pairs = compare_data(base, other, base_image, load_image(IMAGES[k]), args.data)
            if pairs is None:
                print("  data: address constant counts differ; not compared")
            else:
                bad = [(a, b) for a, b, eq in pairs if eq is False]
                unread = sum(1 for _, _, eq in pairs if eq is None)
                print(f"  data: {len(pairs)} address constants, {len(pairs) - len(bad) - unread} with equal "
                      f"{args.data} bytes, {len(bad)} different, {unread} not in the image (zero-filled)")
                for a, b in bad:
                    print(f"    {a:#010x} vs {b:#010x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
