#!/usr/bin/env python3
"""Build the sterilised Lofi-12 XT 1.5.205 cross-flash image (run on a SmplTrek in device session C3).

Three changes to the official file, nothing else:
1. The first two 16-bit instructions of `settings_save` (0xC2C8B0F8, the only flash erase/program
   path; both entries land here) become `mvk .L1 0,a4; bnop .S2 b3,5`, so the function returns 0
   before touching the stack and the foreign app can never write flash. The compact fetch packet's
   header is unchanged (docs/01-platform-map.md, "Where the patch has to fit"; claim XF-5).
2. The cmtd family word (offset 0x10) becomes 5 so the SmplTrek bootloader accepts the file.
3. Both CRCs are resealed with the SmplTrek seeds (tools/sonicware_integrity.py).

No device access; outputs are never overwritten. Check the built image by disassembly
(analysis/mmtd2elf.py + tic6x-elf-objdump) before it goes near a card.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sonicware_integrity as integrity
import patch_builder

FORMAT = "sonicware-sterilised-lofi/1"
SOURCE_HASH = "a8bffa65919c0a2d4ff2ce77d16301551af4d2964497b8804deed49ce4198026"
SOURCE_SIZE = 0x1A0C29
ENTRY = 0xC2C8B0F8                      # settings_save, Lofi-12 XT 1.5.205
FAMILY_OFFSET = 0x10
OLD_ENTRY = (0x36F7, 0x9577)            # stw .D2T2 b13,*b15--(8); stdw .D2T2 b11:b10,*b15--(8)
NEW_ENTRY = (0x0626, 0xA1EF)            # mvk .L1 0,a4; bnop .S2 b3,5 (p-bits 0: sequential)
HEADER = 0xEBC00050                     # the packet's compact header at ENTRY + 4, must stay
require = integrity.require
digest = patch_builder.digest


def source_layout(source):
    require(len(source) == SOURCE_SIZE and digest(source) == SOURCE_HASH,
            "source must be the official, unmodified Lofi-12 XT 1.5.205 .bin")
    checks = integrity.verify(source, "lofi12")
    require(all(stored == calculated for _, stored, calculated in checks), "invalid source CRC")
    images = [item[0] for item in checks]
    require(len(images) == 2 and images[1].tag == "mmtd", "requires a system-only container")
    require(integrity.word(source, FAMILY_OFFSET) == 12, "unexpected family word")
    parts = patch_builder.sections(source, images[1])
    offsets = [off + ENTRY - base for base, off, size in parts
               if base <= ENTRY and ENTRY + 8 <= base + size]
    require(len(offsets) == 1, "entry must lie in exactly one section")
    require(integrity.word(source, offsets[0] + 4) == HEADER, "unexpected fetch packet header")
    return offsets[0]


def edits(source):
    """(offset, old bytes, new bytes, reason) for every change except the CRC reseal."""
    entry = source_layout(source)
    out = [(entry, struct.pack("<2H", *OLD_ENTRY), struct.pack("<2H", *NEW_ENTRY),
            "settings_save entry: mvk .L1 0,a4; bnop .S2 b3,5"),
           (FAMILY_OFFSET, struct.pack("<I", 12), struct.pack("<I", 5), "family word Lofi-12 XT -> SmplTrek")]
    for offset, old, new, _ in out:
        require(source[offset:offset + len(old)] == old, f"unexpected source bytes at {offset:#x}")
    return out


def build(source):
    result = bytearray(source)
    records = []
    for offset, old, new, reason in edits(source):
        result[offset:offset + len(new)] = new
        records.append({"offset": offset, "old_hex": old.hex(), "new_hex": new.hex(), "reason": reason})
    output = integrity.reseal(bytes(result), "smpltrek")
    for image, stored, calculated in integrity.verify(output, "smpltrek"):
        require(stored == calculated, f"{image.tag} CRC did not reseal")
        records.append({"offset": image.offset + 8, "old_hex": source[image.offset + 8:image.offset + 12].hex(),
                        "new_hex": output[image.offset + 8:image.offset + 12].hex(), "reason": f"{image.tag} CRC"})
    changed = [i for i in range(len(source)) if source[i] != output[i]]
    covered = {r["offset"] + k for r in records for k in range(len(bytes.fromhex(r["new_hex"])))}
    require(set(changed) <= covered, "output differs outside the recorded edits")
    recipe = {
        "format": FORMAT,
        "source": {"sha256": SOURCE_HASH, "length": SOURCE_SIZE, "product": "Lofi-12 XT", "version": "1.5.205"},
        "entry": {"address": f"{ENTRY:#010x}", "name": "settings_save",
                  "stub": "mvk .L1 0,a4; bnop .S2 b3,5"},
        "replacements": sorted(records, key=lambda r: r["offset"]),
        "output": {"sha256": digest(output), "length": len(output), "profile": "smpltrek", "family_word": 5},
    }
    return output, recipe


def replay(source, recipe):
    require(recipe.get("format") == FORMAT, "unsupported recipe format")
    output, built = build(source)
    require(built == recipe, "recipe does not match this builder's output")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("build", help="write the sterilised image and its recipe")
    cmd.add_argument("source", type=Path, help="official Lofi-12XT_v1.5.205 .zip or .bin")
    cmd.add_argument("output", type=Path)
    cmd.add_argument("recipe", type=Path)
    cmd = sub.add_parser("verify", help="check an image against the recipe and the builder")
    cmd.add_argument("source", type=Path)
    cmd.add_argument("recipe", type=Path)
    cmd.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        source = patch_builder.read_source(args.source)
        if args.command == "build":
            output, recipe = build(source)
            patch_builder.write_new([(args.output, output),
                                     (args.recipe, (json.dumps(recipe, indent=2) + "\n").encode())])
        else:
            recipe = json.loads(args.recipe.read_text())
            output = args.output.read_bytes()
            require(replay(source, recipe) == output, "output differs from exact recipe replay")
        print(f"Source SHA-256: {recipe['source']['sha256']}")
        for edit in recipe["replacements"]:
            print(f"  {edit['offset']:#010x}: {edit['old_hex']} -> {edit['new_hex']} ({edit['reason']})")
        print(f"Output SHA-256: {recipe['output']['sha256']}")
        print("Verified offline: no flash erase/program path remains reachable; device behaviour is not established.")
    except (OSError, ValueError, KeyError, struct.error, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
