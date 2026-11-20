#!/usr/bin/env python3
"""palette_swap.py -- rewrap a Sonicware firmware update for a different device.

Takes an official system firmware update for one of

    Sonicware SmplTrek      (family word 5)
    Sonicware Lofi-12 XT     (family word 12)
    Sonicware CyDrums       (family word 8)

and produces a copy that the *target* device's bootloader will accept, by
changing ONLY three header words and nothing else:

    1. the "family" word in the cmtd container header (file offset 0x10)
       is set to the target device's value, and
    2. both integrity fields (the outer cmtd CRC and the inner mmtd CRC)
       are recomputed with the TARGET device's per-product CRC-32 seed.

No code, data, section, entry point, version number or any other byte of the
firmware is modified. The bootloader of the target device checks exactly the
family word and the outer CRC before showing its confirmation screen (verified
on a SmplTrek: probe W1 in experiments/README.md), and validates the installed
system image's own CRC with the device's seeds afterwards, which is why the
inner CRC is resealed too.

Everything below is plain Python 3 standard library (zlib, struct, argparse,
hashlib, zipfile) so the whole program can be read top to bottom.

Usage:
    python3 palette_swap.py                          # interactive
    python3 palette_swap.py FIRMWARE.bin --to smpltrek
    python3 palette_swap.py "SmplTrek v3.2.174.zip" --to lofi12 --yes
    python3 palette_swap.py --help

Exit codes: 0 = file written, 1 = refused or cancelled, 2 = error.
"""

import argparse
import hashlib
import struct
import sys
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sonicware_integrity  # noqa: E402  (the full structural parser: sections, partitions, exact extents)

# --------------------------------------------------------------------------
# Known devices.
#
# "family"  is the cmtd header word at offset 0x10. It is checked by the
#           bootloader against the device (probe A2a/A2b, 2026-11-09).
# "seeds"   are zlib-convention CRC-32 seeds per image type: the stored
#           integrity field of an image equals
#               zlib.crc32(image bytes with its own +8..+11 zeroed, seed)
#           over the image's declared extent (docs/12-update-container.md).
# "sd_name" is the file name each device looks for on the SD card (the name
#           inside the official update archives).
# "proof"   states how well the seeds and this direction are validated.
# --------------------------------------------------------------------------

DEVICES = {
    "smpltrek": {
        "label": "Sonicware SmplTrek",
        "family": 5,
        "seeds": {"cmtd": 0x6D2DCD30, "mmtd": 0x1FC67D2F},
        "sd_name": "SmplTrek.bin",
        "proof": ("seeds validated across 8 official releases; a Lofi-12 XT "
                  "image rewrapped this way reached the confirmation screen on "
                  "a real SmplTrek (probe W1, 2026-11-09)."),
    },
    "lofi12": {
        "label": "Sonicware Lofi-12 XT",
        "family": 12,
        "seeds": {"cmtd": 0x8061B03E, "mmtd": 0x2929E2B7},
        "sd_name": "Lofi-12 XT.bin",
        "proof": ("seeds validated across 3 official releases; this direction "
                  "has NOT been tried on a real Lofi-12 XT."),
    },
    "cydrums": {
        "label": "Sonicware CyDrums",
        "family": 8,
        "seeds": {"cmtd": 0x9763BE13, "mmtd": 0x2C577CBB},
        "sd_name": "CyDrums.bin",
        "proof": ("seeds validated across 2 official releases (1.1.84 and "
                  "2.0.97 beta); this direction has NOT been tried on a real "
                  "CyDrums."),
    },
}

# Where each product's mmtd sections load in DDR, from the platform map
# (docs/01-platform-map.md). Used ONLY as a sanity check that the payload
# matches the product the file is sealed as -- never to modify anything.
PAYLOAD_RANGES = [
    ("smpltrek", 0xC0000000, 0xC2000000),
    ("cydrums", 0xC2000000, 0xC2A80000),
    ("lofi12", 0xC2A80000, 0xC3000000),
]


class Refused(Exception):
    """The request was understood but will not be carried out."""


def word(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


# --------------------------------------------------------------------------
# Container parsing (same rules as tools/sonicware_integrity.py).
# --------------------------------------------------------------------------

def parse_system_update(data):
    """Validate a modern cmtd container and return its mmtd descriptor.

    Only system-only files (exactly one descriptor, of type 3 = mmtd) are
    accepted. Content-bundled files (type 2 = pmtd) are refused: flashing a
    foreign *content* image writes ~13 MB of factory data into the target
    device's flash partitions, which is a completely different and untested
    risk from a system-only swap.
    """
    if len(data) < 24 or data[:4] != b"cmtd":
        raise Refused("not a Sonicware 'cmtd' update container")
    if word(data, 4) != len(data):
        raise Refused("header size does not match file size (unsupported or legacy layout)")
    count = word(data, 20)
    if count < 1 or 24 + count * 24 > len(data):
        raise Refused("implausible descriptor count")
    descriptors = []
    end = 24 + count * 24
    for index in range(count):
        kind, major, minor, build, offset, size = struct.unpack_from("<6I", data, 24 + 24 * index)
        descriptors.append((kind, (major, minor, build), offset, size))
        if not (offset == end and offset + size <= len(data)):
            raise Refused("descriptor bounds are inconsistent")
        end = offset + size
    if end != len(data):
        raise Refused("container does not end where the descriptors say")
    kinds = [d[0] for d in descriptors]
    if count != 1 or kinds != [3]:
        if 2 in kinds:
            raise Refused(
                "this file bundles a content (pmtd) image.\n"
                "  Palette swap only handles system-only updates: flashing foreign\n"
                "  content partitions to another device has never been tested and is\n"
                "  not just a header change. Use a system-only release.")
        raise Refused("unsupported descriptor layout")
    kind, version, offset, size = descriptors[0]
    image = data[offset:offset + size]
    if size < 36 or image[:4] != b"mmtd" or word(image, 4) != size:   # 36: the mmtd header read below
        raise Refused("mmtd image does not match its descriptor")
    if struct.unpack_from("<3I", image, 16) != version:
        raise Refused("descriptor and image versions disagree")
    if word(image, 32) < 1 or 36 + 12 * word(image, 32) > size:
        raise Refused("implausible mmtd section count")
    try:
        sonicware_integrity.parse(data)   # walks every section header and length
    except ValueError as error:
        raise Refused(f"malformed container: {error}")
    return {"version": version, "mmtd_offset": offset, "mmtd_size": size,
            "entry": word(image, 28), "sections": word(image, 32)}


def read_firmware(path):
    """Read a .bin, or find the single cmtd .bin inside an official .zip."""
    path = Path(path)
    blob = path.read_bytes()
    if path.suffix.lower() == ".zip":
        try:
            archive = zipfile.ZipFile(path)
        except zipfile.BadZipFile:
            raise Refused("not a readable zip archive")
        found = None
        for name in archive.namelist():
            if name.startswith("__MACOSX/") or not name.lower().endswith(".bin"):
                continue
            with archive.open(name) as member:
                prefix = member.read(4)
                if prefix == b"cmtd":
                    if found is not None:
                        raise Refused("zip contains more than one update file")
                    found = (name, prefix + member.read())
        if found is None:
            raise Refused("no Sonicware update (.bin starting with 'cmtd') inside this zip")
        name, blob = found
        print(f"Using {name} from {path.name}")
    return blob


# --------------------------------------------------------------------------
# Integrity fields.
# --------------------------------------------------------------------------

def image_crc(data, offset, size, seed):
    """CRC-32 of an image's declared extent with its own +8..+11 zeroed."""
    crc = zlib.crc32(data[offset:offset + 8], seed)
    crc = zlib.crc32(b"\x00" * 4, crc)
    return zlib.crc32(data[offset + 12:offset + size], crc)


def matches_profile(data, mmtd_offset, mmtd_size, seeds):
    """True if both stored CRCs equal the ones computed with these seeds."""
    return (image_crc(data, 0, len(data), seeds["cmtd"]) == word(data, 8)
            and image_crc(data, mmtd_offset, mmtd_size, seeds["mmtd"])
            == word(data, mmtd_offset + 8))


def identify(data, info):
    """Return the device whose family word AND seeds fit this file.

    The family word alone is not enough: it is 8 for both CyDrums and the
    ELZ_1 play, which use different seeds. A file only counts as, say, a
    SmplTrek update if its CRCs actually verify under the SmplTrek seeds.
    """
    family = word(data, 16)
    hits = []
    for key, device in DEVICES.items():
        if device["family"] == family and matches_profile(
                data, info["mmtd_offset"], info["mmtd_size"], device["seeds"]):
            hits.append(key)
    if not hits:
        raise Refused(
            "this file's integrity fields do not verify as an unmodified\n"
            "official SmplTrek / Lofi-12 XT / CyDrums system update.\n"
            "  (Corrupted download, an already-modified file, a different\n"
            "  Sonicware product, or a content-only update. Palette swap only\n"
            "  converts verified stock system firmware.)")
    return hits[0]  # family word differs per device here, so at most one hit


def sniff_payload(info):
    """Guess the product from where the mmtd sections load (heuristic)."""
    for key, low, high in PAYLOAD_RANGES:
        if low <= info["entry"] < high:
            return key
    return None


# --------------------------------------------------------------------------
# The conversion itself: three header words, nothing else.
# --------------------------------------------------------------------------

def convert(data, info, target_key):
    """Rewrap `data` for `target_key`. Returns (new_bytes, changed_offsets)."""
    target = DEVICES[target_key]
    result = bytearray(data)
    # 1. family word
    struct.pack_into("<I", result, 16, target["family"])
    # 2. inner mmtd CRC with the TARGET's mmtd seed (children first: ...)
    struct.pack_into("<I", result, info["mmtd_offset"] + 8,
                     image_crc(result, info["mmtd_offset"], info["mmtd_size"],
                               target["seeds"]["mmtd"]))
    # 3. ...then the outer cmtd CRC, which covers the words written above
    struct.pack_into("<I", result, 8, image_crc(result, 0, len(result),
                                                target["seeds"]["cmtd"]))
    new = bytes(result)
    allowed = set(range(8, 12)) | set(range(16, 20)) | set(
        range(info["mmtd_offset"] + 8, info["mmtd_offset"] + 12))
    changed = [i for i in range(len(data)) if data[i] != new[i]]
    if not set(changed) <= allowed:
        raise Refused("internal error: bytes outside the header changed; nothing written")
    if not matches_profile(new, info["mmtd_offset"], info["mmtd_size"], target["seeds"]):
        raise Refused("internal error: resealed file does not verify; nothing written")
    return new, changed


# --------------------------------------------------------------------------
# Interactive bits.
# --------------------------------------------------------------------------

def ask_device(prompt):
    names = ", ".join(f"{key} ({device['label']})" for key, device in DEVICES.items())
    while True:
        answer = input(f"{prompt} [{names}]: ").strip().lower().replace("-", "").replace(" ", "")
        for key in DEVICES:
            if answer == key or answer == key.replace("12", "12xt") or answer.startswith(key):
                return key
        aliases = {"lofi12xt": "lofi12", "lofi": "lofi12", "xt": "lofi12",
                   "smpl": "smpltrek", "trek": "smpltrek", "cy": "cydrums", "drums": "cydrums"}
        if answer in aliases:
            return aliases[answer]
        print("  not recognised; try one of:", ", ".join(DEVICES))


def show_warning(source_key, target_key):
    source, target = DEVICES[source_key], DEVICES[target_key]
    print()
    print("=" * 74)
    print("WARNING -- READ THIS BEFORE CONTINUING")
    print("=" * 74)
    print(f"This will produce a {source['label']} firmware prepared for a")
    print(f"{target['label']}. The firmware's own code is NOT adapted to the")
    print("target device in any way; only the container header and its checksums")
    print("are rewritten so the target bootloader will accept the file.")
    print()
    print("* The safety of your device is NOT guaranteed when running this")
    print("  firmware.")
    print("* Neither the author of this tool nor Sonicware Inc. is responsible")
    print("  for anything that happens to your device as a result of flashing")
    print("  or running this firmware. Flashing it is entirely at your own")
    print("  risk and may void your warranty.")
    print()
    print("Known specifics from reverse engineering this firmware family:")
    print(f"* Target {target['label']}: {target['proof']}")
    print("* The foreign application writes its own settings format to the")
    print("  device's settings flash sectors. After restoring official")
    print("  firmware, saved settings may be misread (most fields fall back")
    print("  to safe defaults; a few are not range-checked).")
    print("* Behaviour after the confirmation screen, and what a normal boot")
    print("  does with a foreign system image, is not fully characterised.")
    print("* Keep the OFFICIAL firmware for this device on a separate SD card")
    print("  before you flash anything unofficial.")
    print("=" * 74)


# --------------------------------------------------------------------------
# Main.
# --------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="palette_swap.py",
        description="Rewrap a Sonicware SmplTrek / Lofi-12 XT / CyDrums system "
                    "firmware update for a different device of the family "
                    "(family word + integrity fields only; no code changes).",
        epilog="Run with no arguments for fully interactive use.")
    parser.add_argument("firmware", nargs="?", help="official update .bin or .zip "
                        "(omitted = will be asked)")
    parser.add_argument("--to", dest="target", choices=sorted(DEVICES),
                        help="device the firmware will be flashed to (omitted = asked)")
    parser.add_argument("-o", "--output", type=Path,
                        help="output file (default: the target device's SD-card "
                             "update name in the current directory)")
    parser.add_argument("--yes", action="store_true",
                        help="skip the confirmation prompt (for scripting)")
    args = parser.parse_args(argv)

    interactive = sys.stdin.isatty()
    try:
        if args.firmware is None:
            if not interactive:
                parser.error("firmware path required when not running interactively")
            args.firmware = input("Path to the official firmware (.bin or .zip): ").strip().strip('"').strip("'")
        if args.target is None:
            if not interactive:
                parser.error("--to is required when not running interactively")
            args.target = ask_device("Flash it onto which device")
    except EOFError:
        return 1

    try:
        data = read_firmware(args.firmware)
        info = parse_system_update(data)
        source_key = identify(data, info)
        source = DEVICES[source_key]
        version = ".".join(map(str, info["version"]))
        print(f"\nSource firmware : {source['label']}, system version {version}")
        print(f"                 {info['sections']} sections, entry point "
              f"0x{info['entry']:08X}, {len(data):,} bytes")
        print(f"Sealed for      : {source['label']} (family word {source['family']}, "
              f"CRCs verified with its seeds)")

        payload = sniff_payload(info)
        if payload is not None and payload != source_key:
            raise Refused(
                f"this file is sealed as {source['label']} but its code loads at\n"
                f"0x{info['entry']:08X}, which looks like {DEVICES[payload]['label']}.\n"
                "  It is probably ALREADY a converted file. Start from a fresh\n"
                "  official firmware instead of converting twice.")

        if args.target == source_key:
            print(f"\nNothing to do: this firmware is already sealed for the "
                  f"{source['label']}.")
            return 1

        show_warning(source_key, args.target)
        if not args.yes:
            try:
                if input("\nType YES to continue (anything else cancels): ").strip() != "YES":
                    print("Cancelled; nothing was written.")
                    return 1
            except EOFError:
                print("\nCancelled; nothing was written.")
                return 1

        new, changed = convert(data, info, args.target)
        target = DEVICES[args.target]
        output = args.output or Path(target["sd_name"])
        if output.exists():
            raise Refused(f"output file {output} already exists; move it away or "
                          "pass -o with a new name (nothing was overwritten)")
        output.write_bytes(new)

        print(f"\nWrote {output} ({len(new):,} bytes)")
        print(f"SHA-256: {hashlib.sha256(new).hexdigest()}")
        print(f"Changed {len(changed)} byte(s), header only:")
        print(f"  offset 0x10: family word {source['family']} -> {target['family']}")
        print(f"  offset 0x08: outer cmtd CRC  -> 0x{word(new, 8):08X}")
        print(f"  offset 0x{info['mmtd_offset'] + 8:X}: inner mmtd CRC  -> "
              f"0x{word(new, info['mmtd_offset'] + 8):08X}")
        print("Every other byte, including all code and data sections, is")
        print("identical to the file you supplied.")
        print(f"\nTo flash: copy {output} alone to the root of a FAT32 SD card,")
        print("put the card in the target device, hold HOME while powering on,")
        print("choose SYSTEM UPDATE, read the version lines carefully, and")
        print("confirm with OK only if you accept the risks above.")
        print(f"Recovery: re-flash the official {target['label']} firmware.")
        return 0
    except Refused as reason:
        sys.stdout.flush()
        print(f"\nRefused: {reason}", file=sys.stderr)
        return 1
    except OSError as reason:
        print(f"\nError: {reason}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
