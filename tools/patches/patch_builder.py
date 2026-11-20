#!/usr/bin/env python3
"""Build, replay and verify one appended section + System Info vtable hook (3.2.174 only)."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import sonicware_integrity as integrity

FORMAT = "sonicware-section-patch/1"
SOURCE_HASH = "3b6848b0f041bcf23c73d4b0357d2f3d6dc9e7e03752b32ff7322e91e6814e53"
SOURCE_SIZE = 0x1DCF91
OLD_TARGET = 0xC1666DA0
SLOT_ADDRESS = 0xC16C5374
SLOT_OFFSET = 0x1CBF9C
# S1.7: static analysis leaves this gap unclaimed; it is NOT a runtime reservation.
CANDIDATE_START, CANDIDATE_END = 0xC16FFA98, 0xC4000000
# The updater erases and writes 4 MiB from flash 0x40000 for SYSTEM (docs/05-bootloader.md, "Writing");
# a larger image would be written over the PRESET area.
SYSTEM_FLASH_CAPACITY = 0x400000
REASONS = {
    0x04: "container size", 0x08: "container CRC",
    0x2C: "system descriptor size", 0x34: "system image size",
    0x38: "system CRC", 0x50: "section count", SLOT_OFFSET: "AppSystemInfo slot 15",
}
require = integrity.require


def digest(data):
    return hashlib.sha256(data).hexdigest()


def keys(obj, expected, label):
    require(isinstance(obj, dict) and set(obj) == set(expected.split()), f"invalid {label} fields")


def integer(value, label):
    require(type(value) is int and 0 <= value < 2**32, f"invalid {label}")
    return value


def address(value):
    require(isinstance(value, str) and re.fullmatch(r"0x[0-9a-f]{8}", value) is not None,
            "addresses must be lowercase 0x + eight hex digits")
    return int(value, 16)


def hex_bytes(value):
    require(isinstance(value, str) and re.fullmatch(r"(?:[0-9a-f]{2})*", value) is not None,
            "invalid byte string")
    return bytes.fromhex(value)


def sections(data, image):
    """Return (load address, payload file offset, length), after integrity.parse validated bounds."""
    pos = image.offset + 36
    out = []
    for _ in range(integrity.word(data, image.offset + 32)):
        base, size = struct.unpack_from("<II", data, pos + 4)
        require(base + size <= 2**32, "section address overflow")
        out.append((base, pos + 12, size))
        pos += 12 + size
    return out


def source_layout(source):
    require(len(source) == SOURCE_SIZE and digest(source) == SOURCE_HASH,
            "source must be the official, unmodified SmplTrek 3.2.174 .bin")
    checks = integrity.verify(source, "smpltrek")
    require(all(stored == calculated for _, stored, calculated in checks), "invalid source CRC")
    images = [item[0] for item in checks]
    require(len(images) == 2 and images[1].tag == "mmtd", "requires a system-only container")
    system = images[1]
    require(system.offset == 0x30 and system.version == (3, 2, 174), "unexpected system layout")
    require(integrity.word(source, system.offset + 28) == 0xC1694580, "unexpected boot entry")
    parts = sections(source, system)
    require(len(parts) == 7, "expected seven source sections")
    offsets = [off + SLOT_ADDRESS - base for base, off, size in parts
               if base <= SLOT_ADDRESS and SLOT_ADDRESS + 4 <= base + size]
    require(offsets == [SLOT_OFFSET], "unexpected vtable slot mapping")
    require(integrity.word(source, SLOT_OFFSET) == OLD_TARGET, "unexpected original vtable pointer")
    return system, parts


def placement(spec, size, parts):
    keys(spec, "load_address entry_offset reserved_region", "placement")
    region = spec["reserved_region"]
    keys(region, "start end evidence", "reserved region")
    load, start, end = address(spec["load_address"]), address(region["start"]), address(region["end"])
    entry = integer(spec["entry_offset"], "entry offset")
    require(isinstance(region["evidence"], str) and bool(region["evidence"].strip()),
            "reserved region needs an evidence note")
    require(CANDIDATE_START <= start < end <= CANDIDATE_END,
            "reserved region must lie in the statically unclaimed DDR gap")
    require(size >= 2 and size % 2 == 0, "payload must contain complete instruction halfwords")
    require(load % 32 == 0, "section load address must be 32-byte aligned")
    require(entry % 2 == 0 and entry + 2 <= size, "entry must be an aligned halfword inside payload")
    require(start <= load and load + size <= end, "payload exceeds reserved region")
    for base, _, length in parts:
        require(load + size <= base or load >= base + length, "payload overlaps an existing section")
    return load, entry


def source_record():
    return {"sha256": SOURCE_HASH, "length": SOURCE_SIZE, "version": "3.2.174", "profile": "smpltrek"}


def hook_record():
    return {"class": "AppSystemInfo", "slot": 15, "address": f"0x{SLOT_ADDRESS:08x}",
            "file_offset": SLOT_OFFSET, "original_target": f"0x{OLD_TARGET:08x}"}


def build(source, payload, spec):
    system, parts = source_layout(source)
    load, entry = placement(spec, len(payload), parts)
    appended = struct.pack("<4sII", b"sect", load, len(payload)) + payload
    require(system.size + len(appended) <= SYSTEM_FLASH_CAPACITY, "system image exceeds the 4 MiB SYSTEM flash area")
    output = bytearray(source + appended)
    updates = {4: len(output), 0x2C: system.size + len(appended),
               system.offset + 4: system.size + len(appended), system.offset + 32: 8,
               SLOT_OFFSET: load + entry}
    for offset, value in updates.items():
        struct.pack_into("<I", output, offset, value)
    output = integrity.reseal(output, "smpltrek")  # child CRC before parent
    recipe = {
        "format": FORMAT, "source": source_record(),
        "payload": {"sha256": digest(payload), "length": len(payload),
                    "placement": json.loads(json.dumps(spec))},
        "hook": hook_record(),
        "replacements": [{"offset": off, "old_hex": source[off:off + 4].hex(),
                          "new_hex": output[off:off + 4].hex(), "reason": reason}
                         for off, reason in sorted(REASONS.items())],
        "append": {"offset": len(source), "old_hex": "", "new_hex": appended.hex()},
        "output": {"sha256": digest(output), "length": len(output)},
    }
    verify(source, recipe, output)
    return output, recipe


def replay(source, recipe):
    """Replay exact byte edits, then independently enforce the semantic change policy."""
    source_layout(source)
    keys(recipe, "format source payload hook replacements append output", "recipe")
    require(recipe["format"] == FORMAT, "unsupported recipe format")
    require(recipe["source"] == source_record(), "recipe source mismatch")
    require(isinstance(recipe["replacements"], list), "invalid replacements")
    output = bytearray(source)
    seen = set()
    for edit in recipe["replacements"]:
        keys(edit, "offset old_hex new_hex reason", "replacement")
        off = integer(edit["offset"], "replacement offset")
        require(off in REASONS and off not in seen, "unexpected or duplicate replacement")
        require(edit["reason"] == REASONS[off], "incorrect replacement reason")
        old, new = hex_bytes(edit["old_hex"]), hex_bytes(edit["new_hex"])
        require(len(old) == len(new) == 4, "replacement must be exactly four bytes")
        require(source[off:off + 4] == old, "old-byte precondition failed")
        output[off:off + 4] = new
        seen.add(off)
    require(seen == set(REASONS), "recipe must record all seven fields")
    addition = recipe["append"]
    keys(addition, "offset old_hex new_hex", "append")
    require(integer(addition["offset"], "append offset") == len(source) and addition["old_hex"] == "",
            "append must start at original EOF")
    output.extend(hex_bytes(addition["new_hex"]))
    output = bytes(output)
    verify_structure(source, recipe, output)
    return output


def verify_structure(source, recipe, output):
    """Check layout, preservation, placement and CRCs without invoking the builder."""
    system, original = source_layout(source)
    require(recipe["hook"] == hook_record(), "recipe hook mismatch")
    keys(recipe["output"], "sha256 length", "output")
    require(integer(recipe["output"]["length"], "output length") == len(output)
            and recipe["output"]["sha256"] == digest(output), "output hash/length mismatch")
    checks = integrity.verify(output, "smpltrek")
    require(all(a == b for _, a, b in checks), "invalid output CRC")
    require(len(checks) == 2 and checks[1][0].tag == "mmtd", "output image set changed")
    child = checks[1][0]
    require(child.offset == system.offset and child.version == system.version, "system descriptor changed")
    require(child.size <= SYSTEM_FLASH_CAPACITY, "system image exceeds the 4 MiB SYSTEM flash area")
    current = sections(output, child)
    require(len(current) == 8 and current[:7] == original, "existing section layout changed")
    # Whole original prefix comparison also protects boot entry, versions, reserved fields and all code/data.
    cursor = 0
    for off in sorted(REASONS):
        require(output[cursor:off] == source[cursor:off], "change outside allowed fields")
        cursor = off + 4
    require(output[cursor:len(source)] == source[cursor:], "change outside allowed fields")
    base, off, size = current[-1]
    require(off == len(source) + 12 and off + size == len(output), "invalid appended section extent")
    payload = output[off:]
    metadata = recipe["payload"]
    keys(metadata, "sha256 length placement", "payload")
    require(integer(metadata["length"], "payload length") == size
            and metadata["sha256"] == digest(payload), "payload hash/length mismatch")
    load, entry = placement(metadata["placement"], size, original)
    require(base == load, "section load address differs from recipe")
    require(integrity.word(output, SLOT_OFFSET) == load + entry, "incorrect replacement vtable pointer")


def verify(source, recipe, output):
    require(replay(source, recipe) == output, "output differs from exact recipe replay")


def read_source(path):
    candidates = list(integrity.inputs([path]))
    require(len(candidates) == 1, "input must contain exactly one update")
    return candidates[0][1]


def write_new(files):
    """Exclusive creation, with cleanup of only our newly created files on failure."""
    paths = [path.resolve() for path, _ in files]
    require(len(set(paths)) == len(paths), "output paths must be distinct")
    require(all(not path.exists() and not path.is_symlink() for path, _ in files),
            "output already exists; choose new paths")
    created = []
    try:
        for path, content in files:
            with path.open("xb") as stream:
                created.append(path)
                stream.write(content)
    except BaseException:
        for path in created:
            path.unlink()
        raise


def report(recipe):
    print(f"Source SHA-256: {recipe['source']['sha256']}")
    for edit in recipe["replacements"]:
        print(f"  {edit['offset']:#010x}: {edit['old_hex']} -> {edit['new_hex']} ({edit['reason']})")
    p = recipe["payload"]
    print(f"Append at {recipe['append']['offset']:#x}: 12-byte section header + {p['length']} payload bytes")
    print(f"Payload SHA-256: {p['sha256']}")
    print(f"Output SHA-256: {recipe['output']['sha256']}")
    print("Verified offline conformance; runtime RAM ownership and device acceptance are not established.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build_cmd = commands.add_parser("build", help="append payload, patch slot, and emit exact recipe")
    build_cmd.add_argument("source", type=Path)
    build_cmd.add_argument("payload", type=Path, help="already linked, self-contained raw binary")
    build_cmd.add_argument("placement", type=Path, help="placement JSON with reserved-region evidence")
    build_cmd.add_argument("output", type=Path)
    build_cmd.add_argument("recipe", type=Path)
    for name in ("verify", "replay"):
        cmd = commands.add_parser(name)
        cmd.add_argument("source", type=Path)
        cmd.add_argument("recipe", type=Path)
        cmd.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        source = read_source(args.source)
        if args.command == "build":
            output, recipe = build(source, args.payload.read_bytes(), json.loads(args.placement.read_text()))
            encoded = (json.dumps(recipe, indent=2, sort_keys=True) + "\n").encode()
            write_new([(args.output, output), (args.recipe, encoded)])
        else:
            recipe = json.loads(args.recipe.read_text())
            if args.command == "verify":
                verify(source, recipe, args.output.read_bytes())
            else:
                output = replay(source, recipe)
                write_new([(args.output, output)])
        report(recipe)
    except (ValueError, OSError, KeyError, TypeError, struct.error, zipfile.BadZipFile) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
