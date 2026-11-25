#!/usr/bin/env python3
"""Compare the products' register-write tables (stock_register_tables.py output for the common scenario).

For each table and phase, each product's rows are reduced to what a driver does: the access (a poll counts as a
read), the register and the value (for the codec: page, register, value; for the SD card: command, argument,
whether it answered). PCs, function names, repeat counts and timing are left out: code addresses differ between
products by construction, and how often an interrupt or poll repeats depends on timing. The sequences are then
aligned (difflib) against the first product's, and the differences listed.

Usage (from the repository root):
  python3 -B emulator/stock_register_diff.py docs/stock-register-writes/common/smpltrek-3.2.174 \\
      docs/stock-register-writes/common/lofi-12xt-1.5.205 docs/stock-register-writes/common/cydrums-1.1.84 \\
      --output docs/stock-register-writes/common/diff.md
"""
import argparse
import collections
import csv
import difflib
from pathlib import Path

TABLES = ("usb0", "i2c0", "codec", "mcasp-edma", "mmcsd", "sd-commands")


def key(table, row):
    if table == "codec":
        return (row["access"], f'{row["page"]}/{row["register"]}', row["value"])
    if table == "sd-commands":
        return (row["command"], row["argument"], row["answered"])
    return ("read" if row["access"] == "poll" else row["access"], row["register"], row["value"])


def load(folder, table):
    phases = collections.OrderedDict()
    path = Path(folder) / f"{table}.csv"
    if path.exists():
        for row in csv.DictReader(open(path)):
            phases.setdefault(row["phase"], []).append(key(table, row))
    return phases


def compare(base_name, base, other_name, other, limit):
    lines, same = [], True
    for phase in list(base) + [p for p in other if p not in base]:
        a, b = base.get(phase, []), other.get(phase, [])
        matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
        blocks = [op for op in matcher.get_opcodes() if op[0] != "equal"]
        if not blocks:
            lines.append(f"- `{phase}`: identical ({len(a)} rows)")
            continue
        same = False
        changed = sum(max(i2 - i1, j2 - j1) for _, i1, i2, j1, j2 in blocks)
        lines.append(f"- `{phase}`: {len(a)} rows in {base_name}, {len(b)} in {other_name}; {len(blocks)} difference(s), "
                     f"{changed} rows")
        shown = 0
        for tag, i1, i2, j1, j2 in blocks:
            if shown >= limit:
                lines.append(f"  - ... {len(blocks) - shown} more")
                break
            left = "; ".join(" ".join(x) for x in a[i1:i2][:6]) + (" ..." if i2 - i1 > 6 else "")
            right = "; ".join(" ".join(x) for x in b[j1:j2][:6]) + (" ..." if j2 - j1 > 6 else "")
            lines.append(f"  - {tag} at row {i1 + 1}: {base_name} `{left or '(none)'}` / {other_name} `{right or '(none)'}`")
            shown += 1
    return same, lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folders", nargs="+", type=Path, help="table folders; the first is the base")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int, default=12, help="differences listed per phase")
    args = parser.parse_args(argv)
    base = args.folders[0]
    out = [f"# Register sequences compared with {base.name}", ""]
    for other in args.folders[1:]:
        out += [f"## {other.name}", ""]
        for table in TABLES:
            same, lines = compare(base.name, load(base, table), other.name, load(other, table), args.limit)
            out += [f"### {table}.csv: {'identical' if same else 'differs'}", ""] + lines + [""]
    text = "\n".join(out)
    if args.output:
        args.output.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
