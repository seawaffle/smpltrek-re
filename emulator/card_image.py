"""Create a synthetic SDSC FAT image from local files."""
import argparse
import json
from pathlib import Path

from build import WORK, digest
from media import build_card


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size-mb", type=int, default=2)
    parser.add_argument("--file", action="append", default=[], metavar="/CARD/PATH=LOCAL",
                        help="add a file; repeat as needed")
    parser.add_argument("--tree", type=Path, help="add every file under this folder, at the same paths on the card")
    parser.add_argument("--long-names", action="store_true", help="write VFAT long names (ASCII only) instead of requiring 8.3")
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    files = {}
    for item in args.file:
        name, separator, local = item.partition("=")
        if not separator or not name.startswith("/"):
            parser.error("--file expects /CARD/PATH=LOCAL")
        files[name] = Path(local)
    if args.tree is not None:
        files.update({"/" + path.relative_to(args.tree).as_posix(): path for path in sorted(args.tree.rglob("*")) if path.is_file()})
    path = build_card(args.output or args.work / "cards/card.img", files, args.size_mb, args.work, args.long_names)
    report = dict(path=str(path), sha256=digest(path.read_bytes()), size=path.stat().st_size)
    path.with_suffix(".json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"Card: {path} ({report['size']} bytes)")


if __name__ == "__main__":
    main()
