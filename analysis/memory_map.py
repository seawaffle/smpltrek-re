#!/usr/bin/env python3
"""Static memory map of a Sonicware system image: loaded sections, run-time initialised data, gaps.

The TI run-time (CGT 8.3.x EABI) initialises data before main from the copy table walked by
__TI_auto_init: a handler table, then (load address, run address) records up to a limit. Each record's
first load byte selects a handler; SmplTrek uses __TI_decompress_rle24 (also for zero-filled .bss/.far)
and a plain copy. Decoding the records gives the exact extent of every zero-filled and initialised
region, which the image file alone does not show.

__TI_auto_init is found as the function loading three addresses H < B < L with B - H <= 16 (handler
table, records base, records limit), (L - B) % 8 == 0, and every record's first load byte a valid
handler index. Handlers: a function that branches with A6 = 1 to a common core is rle24, A6 = 0 rle,
one that adds 3 and 7 to its load pointer is a copy (size word, then data).

Regions that neither the image nor the copy table covers are reported as "unclaimed" within DDR
(0xC0000000 up to the highest address the image or table touches). Unclaimed is not proven free:
uninitialised (NOLOAD) sections such as heaps or task stacks are invisible here, and code can reach
memory through computed addresses. The report also counts code (MVK/MVKH) and data words pointing into
each unclaimed region, as further evidence.

Usage (from the repository root):
  python3 -B analysis/memory_map.py "firmware/smpltrek/SmplTrek v3.2.174.zip" [-o work/map.json]
"""
import argparse
import collections
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import func_match
import string_refs

DDR = 0xC0000000


class Image:
    def __init__(self, sections):
        self.sections = sorted(sections)

    def at(self, address, size=1):
        for a, d in self.sections:
            if a <= address and address + size <= a + len(d):
                return d, address - a
        return None, None

    def word(self, address):
        d, o = self.at(address, 4)
        return None if d is None else struct.unpack_from("<I", d, o)[0]

    def byte(self, address):
        d, o = self.at(address)
        return None if d is None else d[o]


def rle(image, address, rle24):
    """Decode TI RLE (copy_decompress_rle.c) starting at the delimiter byte; return the output bytes."""
    d, o = image.at(address)
    delim = d[o]
    o += 1
    out = bytearray()
    while True:
        ch = d[o]
        o += 1
        if ch != delim:
            out.append(ch)
            continue
        n = d[o]
        o += 1
        if n == 0:
            n = (d[o] << 8) | d[o + 1]
            o += 2
            if n == 0:
                return bytes(out)
            if rle24 and n <= 0xFF:
                n = (n << 16) | (d[o] << 8) | d[o + 1]
                o += 2
            ch = d[o]
            o += 1
        elif n < 4:
            ch = delim
        else:
            ch = d[o]
            o += 1
        out += bytes([ch]) * n


def handler_kind(program, address):
    """'rle24', 'rle' or 'copy' from the first instructions of a copy-table handler, else None."""
    i = func_match.bisect.bisect_left(program.addresses, address)
    window = program.insns[i:i + 8]
    text = [f"{m} {o}" for _, m, o in window]
    if any(t.startswith("add ") and t.split()[2].startswith("3,") for t in text) and \
            any(t.startswith("add ") and t.split()[2].startswith("7,") for t in text):
        return "copy"
    if window and window[0][1] == "b":
        for _, m, o in window[1:4]:
            if m == "mvk" and o.endswith(" 1,a6"):
                return "rle24"
            if m == "mvk" and o.endswith(" 0,a6"):
                return "rle"
    return None


def find_copy_table(program, image):
    by_function = collections.defaultdict(set)
    for value, mvkh, _ in string_refs.constant_pairs(program.insns):
        f = program.function_of(mvkh)
        if f is not None and (image.word(value) is not None or image.word(value - 4) is not None):
            by_function[f].add(value)  # the records limit may be the end of a section
    for f, values in sorted(by_function.items()):
        vs = sorted(values)
        for h in vs:
            for b in vs:
                if not 0 < b - h <= 16:
                    continue
                for limit in vs:
                    if limit <= b or (limit - b) % 8 or limit - b > 0x400:
                        continue
                    handlers = [image.word(h + 4 * k) for k in range((b - h) // 4)]
                    records = [(image.word(r), image.word(r + 4)) for r in range(b, limit, 8)]
                    if any(x is None for x in handlers) or any(None in r for r in records):
                        continue
                    if all(image.byte(load) is not None and image.byte(load) < len(handlers)
                           for load, _ in records):
                        return f, h, b, limit, handlers, records
    return None


def build_map(path):
    program = func_match.load(path)
    image = Image(program.sections)
    found = find_copy_table(program, image)
    if found is None:
        raise SystemExit("copy table (__TI_auto_init) not found")
    auto_init, handler_table, base, limit, handlers, records = found
    kinds = [handler_kind(program, h) for h in handlers]
    regions = []
    for a, d in program.sections:
        kind = "code" if (a, a + len(d)) == program.image.code else "loaded"
        regions.append({"start": a, "end": a + len(d), "kind": kind})
    for load, run in records:
        kind = kinds[image.byte(load)]
        if kind in ("rle24", "rle"):
            data = rle(image, load + 1, kind == "rle24")
        elif kind == "copy":
            size = image.word(load + 4)
            d, o = image.at(load + 8, size)
            data = bytes(d[o:o + size])
        else:
            raise SystemExit(f"unknown handler for record at {load:#x}")
        regions.append({"start": run, "end": run + len(data),
                        "kind": "zero-filled" if not any(data) else "initialised",
                        "from": load, "data": data})
    return program, auto_init, handler_table, base, limit, kinds, regions


def unclaimed(regions):
    ddr = sorted((r["start"], r["end"]) for r in regions if r["start"] >= DDR)
    top = max(e for _, e in ddr)
    gaps, cursor = [], DDR
    for s, e in ddr:
        if s > cursor:
            gaps.append((cursor, s))
        cursor = max(cursor, e)
    return [(s, e) for s, e in gaps if e - s >= 0x1000], top


def references(program, regions, gaps):
    code = collections.Counter()
    for value, _, _ in string_refs.constant_pairs(program.insns):
        for k, (s, e) in enumerate(gaps):
            if s <= value < e:
                code[k] += 1
    data = collections.Counter()
    blobs = [(r["start"], r["data"]) for r in regions if "data" in r]
    blobs += [(a, d) for a, d in program.sections if (a, a + len(d)) != program.image.code]
    for start, blob in blobs:
        for o in range((-start) % 4, len(blob) - 3, 4):
            v = struct.unpack_from("<I", blob, o)[0]
            for k, (s, e) in enumerate(gaps):
                if s <= v < e:
                    data[k] += 1
    return code, data


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("image", help="official update .zip/.bin")
    parser.add_argument("-o", "--output", help="JSON output (keep under work/)")
    args = parser.parse_args()
    program, auto_init, handler_table, base, limit, kinds, regions = build_map(args.image)
    gaps, top = unclaimed(regions)
    code, data = references(program, regions, gaps)
    print(f"__TI_auto_init {auto_init:#x}: handlers {handler_table:#x} {kinds}, records {base:#x}-{limit:#x}")
    for r in sorted(regions, key=lambda r: r["start"]):
        size = r["end"] - r["start"]
        print(f"  {r['start']:#010x}-{r['end']:#010x} {size:>10} {r['kind']}")
    print(f"unclaimed DDR below {top:#x} (not proven free; see --help):")
    for k, (s, e) in enumerate(gaps):
        print(f"  {s:#010x}-{e:#010x} {(e - s) / 1048576:7.2f} MB  code refs {code[k]}, data refs {data[k]}")
    if args.output:
        Path(args.output).write_text(json.dumps({
            "image": program.label, "sha256": program.sha256, "auto_init": f"{auto_init:#010x}",
            "handlers": kinds,
            "regions": [{"start": f"{r['start']:#010x}", "end": f"{r['end']:#010x}", "kind": r["kind"]}
                        for r in sorted(regions, key=lambda r: r["start"])],
            "unclaimed": [{"start": f"{s:#010x}", "end": f"{e:#010x}", "code_refs": code[k],
                           "data_refs": data[k]} for k, (s, e) in enumerate(gaps)],
        }, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
