#!/usr/bin/env python3
"""Account for every byte of an A4 flash dump: which image, partition or block each region belongs to.

Host-side and read-only. The regions come from the dump itself: the boot data before the 'bmtd' header,
the 'bmtd' header, the 'mmtd' system image (its declared size), the 'pmtd' header and its partition
directory (tag, flash address, length per entry), and the two settings sectors ('PREF', with 'PREX' at
+0xC00). Each partition is compared with the same partition in the given update files (official files
carrying a 'pmtd' content image). Whatever is left that is not erased (0xFF) is listed as unexplained,
and each such span is compared with every reference partition placed at its own flash address, which is
how stale data from an older content layout shows up.

The fixed offsets are SmplTrek's (the only product dumped so far); see docs/01-platform-map.md,
"SPI flash layout".

usage (from the repository root):
  python3 -B analysis/flash_map.py work/a4/A4DUMP.BIN firmware/smpltrek/*.zip
"""
import argparse
import hashlib
from pathlib import Path
import re
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import sonicware_integrity as integrity  # noqa: E402

SECTOR = 0x1000
BMTD, MMTD, PMTD = 0x3FFE4, 0x40000, 0x440000
SETTINGS = (0x1FFE000, 0x1FFF000)
HEADER = 32  # tag, size, crc, marker, version triplet, count/entry word


def word(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def content_partitions(update):
    """{tag: (flash address, bytes)} from the 'pmtd' image of one update file ({} if it has none)."""
    out = {}
    for image in integrity.parse(update):
        if image.tag != "pmtd":
            continue
        b = update[image.offset:image.offset + image.size]
        count = word(b, 28)
        pos = HEADER + 12 * count
        for k in range(count):
            entry = HEADER + 12 * k
            tag = b[entry:entry + 4].decode("ascii", "replace")
            address, size = word(b, entry + 4), word(b, entry + 8)
            out[tag] = (address, bytes(b[pos:pos + size]))
            pos += size
    return out


def header(data, offset, tag):
    if data[offset:offset + 4] != tag.encode():
        return None
    size, crc, marker, *version = struct.unpack_from("<6I", data, offset + 4)
    return {"size": size, "crc": crc, "marker": marker, "version": tuple(version)}


def regions(data):
    """Known regions (start, end, name) found from the headers in the dump, in address order."""
    out = []
    bmtd = header(data, BMTD, "bmtd")
    if bmtd:
        boot = data[:BMTD].rstrip(b"\xff")
        if boot:
            out.append((0, len(boot), "boot data (AIS image) before the bmtd header"))
        out.append((BMTD, BMTD + 28, "bmtd header (BOOT %d.%d.%d)" % bmtd["version"]))
    mmtd = header(data, MMTD, "mmtd")
    if mmtd:
        out.append((MMTD, MMTD + mmtd["size"], "mmtd system image (SYSTEM %d.%d.%d)" % mmtd["version"]))
    pmtd = header(data, PMTD, "pmtd")
    if pmtd:
        count = word(data, PMTD + 28)
        out.append((PMTD, PMTD + HEADER + 12 * count,
                     "pmtd header and directory (PRESET %d.%d.%d, %d partitions)" % (pmtd["version"] + (count,))))
        for k in range(count):
            entry = PMTD + HEADER + 12 * k
            tag = data[entry:entry + 4].decode("ascii", "replace")
            address, size = word(data, entry + 4), word(data, entry + 8)
            out.append((address, address + size, "partition " + tag))
    for base in SETTINGS:
        if data[base:base + 4] == b"PREF":
            used = data[base:base + SECTOR].rstrip(b"\xff")
            out.append((base, base + len(used), "settings sector (PREF, PREX at +0xC00)"))
    return sorted(out)


def nonerased_spans(data, start, end, gap=64):
    """Spans of non-0xFF bytes in data[start:end], merging spans separated by fewer than gap 0xFF bytes."""
    pattern = re.compile(rb"[^\xff]+(?:\xff{1,%d}[^\xff]+)*" % (gap - 1))
    return [(m.start(), m.end()) for m in pattern.finditer(data, start, end)]


def uncovered(data, known):
    spans, position = [], 0
    for start, end, _ in known:
        if start > position:
            spans += nonerased_spans(data, position, start)
        position = max(position, end)
    return spans + nonerased_spans(data, position, len(data))


def compare(data, address, payload):
    segment = data[address:address + len(payload)]
    sectors = range(0, len(payload), SECTOR)
    equal = sum(segment[i:i + SECTOR] == payload[i:i + SECTOR] for i in sectors)
    return segment == payload, equal, len(sectors)


def explain(data, span, references):
    """References whose partition, at its own flash address, covers the span with equal bytes."""
    start, end = span
    hits = []
    for name, partitions in references:
        for tag, (address, payload) in partitions.items():
            if address <= start and end <= address + len(payload) and \
                    data[start:end] == payload[start - address:end - address]:
                hits.append(f"{name} {tag}")
    return hits


def build(data, references):
    known = regions(data)
    rows = []
    for start, end, name in known:
        row = {"start": start, "end": end, "name": name, "matches": []}
        if name.startswith("partition "):
            tag = name.split()[1]
            for ref, partitions in references:
                if tag in partitions and partitions[tag][0] == start:
                    exact, equal, total = compare(data, start, partitions[tag][1])
                    row["matches"].append((ref, exact, equal, total))
        rows.append(row)
    extra = [{"start": s, "end": e, "explained_by": explain(data, (s, e), references)}
             for s, e in uncovered(data, known)]
    return {"length": len(data), "sha256": hashlib.sha256(data).hexdigest(), "regions": rows, "unexplained": extra}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("dump", type=Path)
    parser.add_argument("updates", type=Path, nargs="*", help="official update ZIP/BIN files to compare content with")
    args = parser.parse_args(argv)
    data = args.dump.read_bytes()
    references = []
    for name, update in integrity.inputs(args.updates):
        partitions = content_partitions(update)
        if partitions:
            references.append((Path(name.split(":")[0]).stem, partitions))
    report = build(data, references)
    print(f"{args.dump}: {report['length']} bytes, sha256 {report['sha256']}")
    for row in report["regions"]:
        print(f"  0x{row['start']:07x}..0x{row['end']:07x}  {row['name']}")
        exact = [m[0] for m in row["matches"] if m[1]]
        if exact:
            print(f"      equals {', '.join(exact)}")
        elif row["matches"]:
            best = max(row["matches"], key=lambda m: m[2])
            print(f"      no exact reference; best {best[0]}: {best[2]}/{best[3]} sectors equal")
    if not report["unexplained"]:
        print("  everything else is erased (0xFF)")
    for span in report["unexplained"]:
        by = ", ".join(span["explained_by"]) or "no reference partition at this address matches"
        print(f"  0x{span['start']:07x}..0x{span['end']:07x}  not in any region above; equals: {by}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
