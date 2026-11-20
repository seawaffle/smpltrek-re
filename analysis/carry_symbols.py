#!/usr/bin/env python3
"""Carry a symbol file from one Sonicware image to others, through func_match.

Functions move with the function matching. Data symbols move through the address constants (MVK/MVKH
pairs) of matched functions: if a function in the source loads the symbol's address as its k-th
constant, the matched function's k-th constant is the address in the target, provided both functions
load the same number of constants. All such votes must agree.

Confidence never rises. A carried function keeps the source confidence when the two normalised bodies
are at least 0.9 similar, becomes at most "probable" from 0.6, and "speculative" below that. Carried
data symbols are at most "probable".

Usage (from the repository root):
  python3 -B analysis/carry_symbols.py symbols/smpltrek-3.2.174.json \\
      "firmware/smpltrek/SmplTrek v3.2.174.zip" firmware/smpltrek/*.zip firmware/lofi12/*.zip ...
Writes symbols/<product>-<version>.json for every other image (the source image is skipped).

Per-product findings that cannot be carried (code compiled differently, product-only code) go in a
hand-written symbols/hand/<product>-<version>.json with the same format and the target image's
sha256. Its entries are merged into the generated file: a hand entry replaces a carried one with the
same name or address, others are added. A hand file may also list "rejected": [{"name", "reason"}] for
carries that were checked and are wrong; those names are dropped from the generated file.
"""
import argparse
import collections
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import func_match
import symfile
import string_refs

RANK = {"speculative": 0, "probable": 1, "confirmed": 2}


def cap(confidence, ceiling):
    return min(confidence, ceiling, key=RANK.get)


def file_stem(label, version):
    """'.../SmplTrek v3.0.148.zip:...' -> 'smpltrek-3.0.148'; 'Lofi-12XT_v1.5.205.zip' -> 'lofi-12xt-1.5.205'."""
    name = Path(label.split(":")[0]).stem
    product = re.split(r"[ _]v?\d", name)[0]
    return f"{product.lower()}-{version}"


def constants_by_function(program):
    out = collections.defaultdict(list)
    for value, mvkh, _ in string_refs.constant_pairs(program.insns):
        f = program.function_of(mvkh)
        if f is not None:
            out[f].append(value)
    return out


def carry_data(address, match, ca, cb):
    votes = collections.Counter()
    for x, y in match.ab.items():
        la, lb = ca.get(x, []), cb.get(y, [])
        if len(la) == len(lb):
            votes.update(lb[k] for k, v in enumerate(la) if v == address)
    if len(votes) == 1:
        (value, n), = votes.items()
        return value, n
    return None, 0


def carry(symbols, source_name, match):
    a, b = match.a, match.b
    ca, cb = constants_by_function(a), constants_by_function(b)
    out = []
    for entry in symbols["symbols"]:
        x = int(entry["address"], 16)
        if entry["kind"] == "function":
            y = match.ab.get(x)
            if y is None:
                continue
            similarity = match.similarity(x)
            ceiling = "confirmed" if similarity >= 0.9 else "probable" if similarity >= 0.6 else "speculative"
            base, data = b.image.locate(y)
            carried = {k: v for k, v in entry.items() if k not in ("address", "prefix_sha256", "evidence", "confidence")}
            carried.update(
                address=f"0x{y:08x}",
                confidence=cap(entry["confidence"], ceiling),
                prefix_sha256=symfile.prefix_hash(data[y - base:y - base + symfile.PREFIX_LEN]),
                evidence=[f"Carried from {source_name} {entry['address']} by func_match "
                          f"({match.method[x]}, body similarity {similarity}). See the source entry "
                          f"for what is known about it."])
        else:
            y, votes = carry_data(x, match, ca, cb)
            if y is None:
                continue
            carried = {k: v for k, v in entry.items() if k not in ("address", "evidence", "confidence")}
            carried.update(
                address=f"0x{y:08x}",
                confidence=cap(entry["confidence"], "probable"),
                evidence=[f"Carried from {source_name} {entry['address']}: loaded as the same-position "
                          f"address constant by {votes} matched function(s). See the source entry."])
        out.append(carried)
    return out


def merge_hand(entries, hand_path, sha256):
    """Merge a hand-written per-product symbol file into carried entries (hand wins by name or address)."""
    if not hand_path.exists():
        return entries
    hand = json.loads(hand_path.read_text())
    if hand["source"]["sha256"] != sha256:
        sys.exit(f"{hand_path} does not describe this image")
    names = {e["name"] for e in hand["symbols"]} | {r["name"] for r in hand.get("rejected", [])}
    addresses = {e["address"] for e in hand["symbols"]}
    kept = [e for e in entries if e["name"] not in names and e["address"] not in addresses]
    added = [dict(e, evidence=e["evidence"] + [f"Hand-written in symbols/hand/{hand_path.name}."])
             for e in hand["symbols"]]
    return sorted(kept + added, key=lambda e: int(e["address"], 16))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("symbols", help="source symbols JSON")
    parser.add_argument("source", help="update .zip/.bin the symbols describe")
    parser.add_argument("targets", nargs="+", help="update .zip/.bin files to carry them to")
    parser.add_argument("--out-dir", default=str(ROOT / "symbols"))
    args = parser.parse_args()

    symbols_path = Path(args.symbols)
    symbols = json.loads(symbols_path.read_text())
    a = func_match.load(args.source)
    if a.sha256 != symbols["source"]["sha256"]:
        sys.exit(f"{args.source} is not the image {symbols_path.name} describes")
    for target in args.targets:
        b = func_match.load(target)
        if b.sha256 == a.sha256:
            continue
        match = func_match.Matching(a, b)
        match.run()
        version = ".".join(map(str, b.version))
        entries = carry(symbols, symbols_path.stem, match)
        entries = merge_hand(entries, Path(args.out_dir) / "hand" / f"{file_stem(b.label, version)}.json", b.sha256)
        if not entries:
            print(f"{b.label}: nothing carried, no file written")
            continue
        document = {
            "format": symbols["format"],
            "source": {"file": b.label.split(":", 1)[-1], "sha256": b.sha256, "mmtd_version": version},
            "notes": [f"Generated by analysis/carry_symbols.py from {symbols_path.name}; do not edit by "
                      f"hand. Add findings to a hand-written file instead."] + symbols["notes"][1:],
            "symbols": entries,
        }
        out = Path(args.out_dir) / f"{file_stem(b.label, version)}.json"
        out.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
        print(f"{out.name}: {len(entries)}/{len(symbols['symbols'])} carried "
              f"({', '.join(e['name'] + ':' + e['confidence'][0] for e in entries)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
