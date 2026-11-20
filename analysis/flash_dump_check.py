#!/usr/bin/env python3
"""Summarise an A4 flash dump (A4DUMP.BIN) and locate known content in it.

Host-side only. It reads the dump and, optionally, the official update file the
device was running, and reports: the dump size, erased (0xFF) and zero runs by
4 KiB sector, the image headers the app expects ('bmtd' at 0x3FFE4, 'mmtd' at
0x40000, 'pmtd' at 0x440000), the settings tags, and where each section of the
official system image appears in the dump (device 0 is the first 16 MiB, device 1
the second). It does not decide that a dump is
complete or that the device is healthy; two independent dumps with equal hashes
are the completeness check (device session A4, experiments/README.md).
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools/patches"))
import sonicware_integrity as integrity  # noqa: E402
import patch_builder as patch  # noqa: E402

DEVICE = 0x01000000
TOTAL = 2 * DEVICE  # the app's 32 MiB space: device 0, then device 1 (settings in its top two sectors)
SECTOR = 0x1000
HEADERS = {"bmtd": 0x3FFE4, "mmtd": 0x40000, "pmtd": 0x440000}
TAGS = (b"bmtd", b"mmtd", b"pmtd", b"PREF", b"PREX", b"sect")
NEEDLE = 64


def runs(data, sector=SECTOR):
    """Contiguous runs of all-0xFF and all-0x00 sectors as (kind, start, end)."""
    out, current = [], None
    for start in range(0, len(data), sector):
        chunk = data[start:start + sector]
        kind = "erased" if chunk == b"\xff" * len(chunk) else "zero" if chunk == b"\x00" * len(chunk) else None
        if current and current[0] == kind:
            current[2] = start + len(chunk)
        else:
            if current and current[0]:
                out.append(tuple(current))
            current = [kind, start, start + len(chunk)]
    if current and current[0]:
        out.append(tuple(current))
    return out


def header(data, offset):
    """Header fields: marker at +12, version triplet at +16/+20/+24."""
    block = bytes(data[offset:offset + 128])
    if len(block) < 32:
        return None
    words = struct.unpack_from("<8I", block, 0)
    # 2026-11-11 dump: +4 size, +8 CRC, +12 is 0xFFFFFFFE, +16..+24 the version triplet
    # (the same layout as the update file's image header); +12 is not the version.
    return {"offset": f"0x{offset:x}", "tag": block[:4].decode("ascii", "replace"),
            "words": [f"0x{w:08x}" for w in words], "size": words[1], "crc": f"0x{words[2]:08x}",
            "version": list(words[4:7]), "marker": f"0x{words[3]:08x}"}


def find_all(data, needle, limit=16):
    out, pos = [], data.find(needle)
    while pos >= 0 and len(out) < limit:
        out.append(pos)
        pos = data.find(needle, pos + 1)
    return out


def locate(data, name, payload):
    """Where a known blob sits in the dump: candidates by a short needle, then a full compare."""
    hits = []
    for pos in find_all(data, payload[:NEEDLE]):
        same = sum(1 for a, b in zip(data[pos:pos + len(payload)], payload) if a == b)
        hits.append({"offset": f"0x{pos:x}", "matching_bytes": same, "length": len(payload),
                     "exact": same == len(payload) and pos + len(payload) <= len(data)})
    return {"name": name, "hits": hits}


def official_parts(source):
    """(name, bytes) for the whole system image and each of its sections, from the official file."""
    images = integrity.parse(source)
    system = next(image for image in images if image.tag == "mmtd")
    parts = [("mmtd image", bytes(source[system.offset:system.offset + system.size]))]
    for index, (base, off, size) in enumerate(patch.sections(source, system)):
        parts.append((f"section {index} @0x{base:08x}", bytes(source[off:off + size])))
    return parts


def compare_installed_system(data, reference):
    """Compare flash mmtd to a known update, reporting the marker change separately.

    Normalization is an in-memory comparison only, not a repair or validation rule.
    It recognizes just the observed FF->FE change and never edits the dump.
    """
    system = next(i for i in integrity.parse(reference) if i.tag == "mmtd")
    expected = bytes(reference[system.offset:system.offset + system.size])
    start = HEADERS["mmtd"]
    actual = bytes(data[start:start + system.size])
    result = {"reference_sha256": hashlib.sha256(reference).hexdigest(),
              "flash_offset": hex(start), "length": system.size,
              "reference_mmtd_sha256": hashlib.sha256(expected).hexdigest(),
              "raw_exact": actual == expected,
              # a reference of another size is compared only over its own length; say so explicitly
              "installed_declared_size": integrity.word(data, start + 4) if len(data) >= start + 8 else None}
    result["size_matches"] = result["installed_declared_size"] == system.size
    if len(actual) != len(expected):
        return {**result, "error": "truncated installed image", "marker_only_difference": False}
    normalized = bytearray(actual)
    observed_marker_change = actual[12:16] == b"\xfe\xff\xff\xff" and expected[12:16] == b"\xff" * 4
    if observed_marker_change:
        normalized[12:16] = expected[12:16]
    result.update(stored_marker=f"0x{integrity.word(actual, 12):08x}",
                  reference_marker=f"0x{integrity.word(expected, 12):08x}",
                  marker_only_difference=observed_marker_change and normalized == expected,
                  other_differing_bytes=sum(a != b for a, b in zip(normalized, expected)))
    if integrity.word(reference, 16) == integrity.FAMILY_WORD["smpltrek"]:
        image = integrity.Image("mmtd", 0, len(expected))
        seed = integrity.PROFILES["smpltrek"]["mmtd"]
        result.update(stored_crc=f"0x{integrity.word(actual, 8):08x}",
                      raw_crc=f"0x{integrity.checksum(actual, image, seed):08x}",
                      marker_normalized_crc=f"0x{integrity.checksum(normalized, image, seed):08x}",
                      reference_crc_valid=integrity.checksum(expected, image, seed) == integrity.word(expected, 8))
    return result


def summarise(data, source=None, installed=None):
    data = bytes(data)
    report = {"length": len(data), "sha256": hashlib.sha256(data).hexdigest(),
              "complete": len(data) == TOTAL,
              "runs": [{"kind": kind, "start": f"0x{s:x}", "end": f"0x{e:x}"} for kind, s, e in runs(data)],
              "headers": {tag: header(data, offset) for tag, offset in HEADERS.items()},
              "tags": {tag.decode(): [f"0x{p:x}" for p in find_all(data, tag)] for tag in TAGS}}
    for tag in ("bmtd", "mmtd", "pmtd"):
        found = report["headers"][tag]
        report["headers"][tag + "_ok"] = bool(found) and found["tag"] == tag
    if source is not None:
        report["official"] = [locate(data, name, payload) for name, payload in official_parts(source)]
    if installed is not None:
        report["installed_reference"] = compare_installed_system(data, installed)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path, help="A4DUMP.BIN read from the card")
    parser.add_argument("--official", type=Path, help="official update ZIP/BIN the device was running")
    parser.add_argument("--installed", type=Path, help="exact update ZIP/BIN installed when captured (e.g. A4 probe)")
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = parser.parse_args(argv)
    try:
        data = args.dump.read_bytes()
        source = patch.read_source(args.official) if args.official else None
        report = summarise(data, source, patch.read_source(args.installed) if args.installed else None)
    except (OSError, ValueError, StopIteration) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    print(f"{args.dump}: {report['length']} bytes ({report['length'] / 2**20:.3f} MiB), "
          f"sha256 {report['sha256']}")
    if not report["complete"]:
        print(f"  not a complete 32 MiB image of both devices (expected {TOTAL} bytes)")
    else:
        print("  expected 32 MiB length present; this is not an independent second-dump verification")
    for run in report["runs"]:
        print(f"  {run['kind']:6} {run['start']}..{run['end']}")
    for tag in ("bmtd", "mmtd", "pmtd"):
        found = report["headers"][tag]
        status = "OK" if report["headers"][tag + "_ok"] else "MISSING"
        if found:
            print(f"  {tag} @{found['offset']}: {status}, size 0x{found['size']:x}, crc {found['crc']}, "
                  f"version {'.'.join(map(str, found['version']))}")
        else:
            print(f"  {tag} @{HEADERS[tag]:#x}: beyond the dump")
    for tag, positions in report["tags"].items():
        print(f"  '{tag}' at {', '.join(positions) if positions else 'none'}")
    for item in report.get("official", []):
        if item["hits"]:
            for hit in item["hits"]:
                print(f"  {item['name']}: at {hit['offset']} {hit['matching_bytes']}/{hit['length']} bytes"
                      f"{' exact' if hit['exact'] else ''}")
        else:
            print(f"  {item['name']}: not found")
    if "installed_reference" in report:
        print("  installed reference: " + json.dumps(report["installed_reference"], sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
