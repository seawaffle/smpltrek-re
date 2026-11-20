#!/usr/bin/env python3
"""List addresses quoted in a symbol file's evidence that the image does not explain.

Hand-decoding an MVK/MVKH pair is error-prone (the high half was mis-read several times: 0xC16E3500 for
0xC16D3500, 0xC16DE850 for 0xC16CE850, ...). This tool collects every address quoted in the evidence
strings (and every entry address) and reports those that are none of:
  - an instruction address in the objdump listing,
  - an address the code builds with an MVK/MVKH pair, or such an address plus 0..252 (a field),
  - a 32-bit word stored in the image (pointer tables, .init_array),
  - a symbol in the file,
  - B14 + 0..32767 (data-page addressing), when --b14 is given.
What remains is either a typo / mis-decoded address or a value derived some other way (a string at an odd
address, a bare high half such as 0xC14F0000, a computed table entry). Read each one; nothing here is
proof of an error.

usage (from the repository root):
  python3 -B analysis/evidence_audit.py "firmware/smpltrek/SmplTrek v3.2.174.zip" work/smpltrek-3.2.174.dis \\
      symbols/smpltrek-3.2.174.json --b14 0xC16F3320
"""
import argparse
import json
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import func_match  # noqa: E402

PAIR = r"^([0-9a-f]+):\s+\S+\s+(?:\|\|\s*)?(?:\[!?[ab]\d+\]\s*)?{op}\s+\.\S+\s+(-?\d+),([ab]\d+)"
MVK = re.compile(PAIR.format(op="mvk"))
MVKH = re.compile(PAIR.format(op="mvkh"))


def listing_facts(dis_path):
    """(instruction addresses, MVK/MVKH-built constants) from an objdump listing."""
    lines = Path(dis_path).read_text().splitlines()
    instructions, constants = set(), set()
    for i, line in enumerate(lines):
        m = re.match(r"^([0-9a-f]{8}):", line)
        if m:
            instructions.add(int(m.group(1), 16))
        m = MVKH.match(line)
        if not m:
            continue
        for j in range(i - 1, max(0, i - 40), -1):
            k = MVK.match(lines[j])
            if k and k.group(3) == m.group(3):
                constants.add(((int(m.group(2)) & 0xFFFFFFFF) >> 16 << 16) | (int(k.group(2)) & 0xFFFF))
                break
    return instructions, constants


def image_words(image):
    words = set()
    for _, data in func_match.load(image).sections:
        words.update(struct.unpack_from("<%dI" % (len(data) // 4), data))
    return words


def audit(image, dis, symbols, b14=None):
    instructions, constants = listing_facts(dis)
    words = image_words(image)
    doc = json.loads(Path(symbols).read_text())
    named = {int(e["address"], 16) for e in doc["symbols"]}
    tops = [int(e["address"], 16) >> 24 for e in doc["symbols"]]
    hi = max(set(tops), key=tops.count) if tops else 0xC1  # the image's code/data region (0xC1 or 0xC2)
    pattern = re.compile(r"\b0x%02X[0-9A-F]{6}\b" % hi, re.I)

    def explained(a):
        return (a in instructions or (a & ~1) in instructions or a in words or a in named
                or any(a - off in constants for off in range(0, 256, 4))
                or (b14 is not None and 0 <= a - b14 < 32768))

    # an address quoted as the wrong side of a correction ("X -> Y", "not X", "recorded as X", "gave X")
    superseded = re.compile(r"(?:\bnot |recorded as |\bgave )0x[0-9A-F]+(?: / 0x[0-9A-F]+)*|0x[0-9A-F]+(?= -> )", re.I)
    report = {}
    for e in doc["symbols"]:
        texts = [superseded.sub("", ev) for ev in e["evidence"]]
        quoted = [e["address"]] + [h for ev in texts for h in pattern.findall(ev)]
        bad = sorted({h.upper().replace("0X", "0x") for h in quoted if not explained(int(h, 16))})
        if bad:
            report[e["name"]] = bad
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("image")
    ap.add_argument("dis", help="objdump -d listing of the same image (work/<product>.dis)")
    ap.add_argument("symbols", help="symbol file (generated or hand) describing the image")
    ap.add_argument("--b14", type=lambda s: int(s, 0), help="data page pointer, to accept B14-relative addresses")
    args = ap.parse_args()
    report = audit(args.image, args.dis, args.symbols, args.b14)
    for name, addresses in report.items():
        print(f"{name}: {' '.join(addresses)}")
    print(f"{len(report)} entries with unexplained addresses", file=sys.stderr)


if __name__ == "__main__":
    main()
