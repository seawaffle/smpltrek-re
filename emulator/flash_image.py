#!/usr/bin/env python3
"""Build a factory-like flash image: an official update's preset content where the boot loader writes it.

The stock runner otherwise starts with erased flash, so the firmware has no factory kits, sounds,
patterns or projects. The last SmplTrek update that carries content is 2.0.129: its 'pmtd' header and
partition directory go to 0x440000 and each partition (PKIT, PPRJ, PDPT, PDSN, PISN) to the flash
address the directory names (docs/01-platform-map.md, "SmplTrek's content reads"). Bit 0 of the
header word at +12 is cleared, as the boot loader leaves it once an image is written. Nothing else is
placed: no boot loader, system image or settings sectors.
"""
import argparse
from pathlib import Path
import struct
import sys

from build import ROOT, WORK, digest

CONTENT_UPDATE = ROOT / "firmware/smpltrek/SmplTrek v2.0.129.zip"
SIZE, PMTD, HEADER = 0x2000000, 0x440000, 32


def factory_flash(update=CONTENT_UPDATE):
    """(32 MiB image: CS0 then CS1, {partition tag: (flash address, length)})."""
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import sonicware_integrity as integrity
    finally:
        sys.path.pop(0)
    (_, data), = integrity.inputs([Path(update)])
    if any(stored != calculated for _, stored, calculated in integrity.verify(data, "smpltrek")):
        raise ValueError("update CRC verification failed")
    content = [image for image in integrity.parse(data) if image.tag == "pmtd"]
    if len(content) != 1:
        raise ValueError("expected one 'pmtd' content image in the update")
    image = data[content[0].offset:content[0].offset + content[0].size]
    count = struct.unpack_from("<I", image, 28)[0]
    head = bytearray(image[:HEADER + 12 * count])
    struct.pack_into("<I", head, 12, struct.unpack_from("<I", head, 12)[0] & ~1)
    flash = bytearray(b"\xff" * SIZE)
    flash[PMTD:PMTD + len(head)] = head
    partitions, position = {}, len(head)
    for index in range(count):
        tag, address, length = struct.unpack_from("<4sII", image, HEADER + 12 * index)
        if address + length > SIZE or position + length > len(image):
            raise ValueError("content partition lies outside the flash or the image")
        flash[address:address + length] = image[position:position + length]
        partitions[tag.decode("ascii")] = (address, length)
        position += length
    return bytes(flash), partitions


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--update", type=Path, default=CONTENT_UPDATE)
    parser.add_argument("--output", type=Path, default=WORK / "flash/factory.img")
    args = parser.parse_args(argv)
    flash, partitions = factory_flash(args.update)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(flash)
    for tag, (address, length) in partitions.items():
        print(f"{tag} {address:#010x} {length} bytes")
    print(f"Flash: {args.output} (SHA-256 {digest(flash)})")


if __name__ == "__main__":
    main()
