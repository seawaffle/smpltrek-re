#!/usr/bin/env python3
"""Decode C64x+ fetch and execute packets of a Sonicware system image, and show call-site set-up.

objdump's listing is not enough on its own where the exact packet structure matters:
  - the rest of a call's execute packet is printed as "||" lines AFTER the CALLP, but those
    instructions run in the same cycle (argument set-up such as "|| mvk .L2 12,b4");
  - execute packets can cross fetch-packet boundaries, and a branch's five delay slots can continue
    past a "<fetch packet header>" line (SmplTrek usb_start loads A4 there);
  - objdump appends "|| nop N" text to every instruction of a fetch packet whose header has the PROT
    bit set (exactly those packets: 1325 of 1325 in SmplTrek 3.2.174, 1284 of 1284 in CyDrums 1.1.84),
    and ghidra-c6000's listing can omit instructions (it skipped a SET and compact MVKs at SmplTrek
    0xC164C320).

PROT (header bit 20) selects protected mode: the CPU waits after a load until its result is written,
so a protected packet can use a loaded value in the next instruction (SmplTrek 0xC1646E94 loads a vptr
and 0xC1646E98 loads a slot through it). Count delay slots with that in mind; this tool marks such
packets "PROT" (the exact pipeline rules are in TI SPRU732, not restated here).

A fetch packet is 32 bytes. If its last word has 0b1110 in bits 31-28 it is a header: bits 27-21 mark
which of words 0-6 hold two 16-bit (compact) instructions (bit 21 = word 0), bits 13-0 are the p-bits
of the 14 half-words (bit 0 = first half-word). A 32-bit instruction carries its p-bit in bit 0.
p = 1 means the next instruction executes in parallel; p = 0 ends the execute packet.

Usage (from the repository root):
  # p-bits of the fetch packets at an address
  python3 -B analysis/packets.py "firmware/smpltrek/SmplTrek v3.2.174.zip" 0xC1676600 --count 3
  # every call/branch to a target, with the execute packets around it (objdump text, "|| nop N" removed)
  python3 -B analysis/packets.py firmware/lofi12/Lofi-12XT_v1.5.205.zip --calls 0xC2C5C7F0
"""
import argparse
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import memory_map
import mmtd2elf
import sonicware_integrity as integrity
import string_refs

NOP_SUFFIX = re.compile(r"\s*\|\| nop \d+$")


def protected(header):
    """True when a fetch-packet header has the PROT bit (bit 20) set."""
    return header is not None and bool(header >> 20 & 1)


def header_of(image, address):
    """The fetch packet's header word, or None when the packet has none."""
    fp = address & ~31
    d, o = image.at(fp, 32)
    if d is None:
        raise ValueError(f"{fp:#x} is not in a loaded section")
    header = struct.unpack_from("<I", d, o + 28)[0]
    return header if header >> 28 == 0xE else None


def fetch_packet(image, address):
    """[(address, size, p)] for the fetch packet containing address (image: memory_map.Image)."""
    fp = address & ~31
    header = header_of(image, fp)
    d, o = image.at(fp, 32)
    words = struct.unpack_from("<8I", d, o)
    if header is None:
        return [(fp + 4 * i, 4, w & 1) for i, w in enumerate(words)]
    layout, pbits = (header >> 21) & 0x7F, header & 0x3FFF
    units = []
    for i in range(7):
        if layout >> i & 1:
            units += [(fp + 4 * i + 2 * h, 2, pbits >> (2 * i + h) & 1) for h in range(2)]
        else:
            units.append((fp + 4 * i, 4, words[i] & 1))
    return units


def execute_packets(image, start, end):
    """Execute packets (lists of instruction addresses) overlapping [start, end), from start's fetch packet.

    A packet still open at the end of a fetch packet continues into the next one.
    """
    packets, current, fp = [], [], start & ~31
    while fp < end or current:
        for address, _, p in fetch_packet(image, fp):
            current.append(address)
            if not p:
                if current[-1] >= start:
                    packets.append(current)
                current = []
        fp += 32
    return packets


def load(path):
    (name, data), = list(integrity.inputs([Path(path)]))
    version, entry, sections = mmtd2elf.mmtd_sections(data)
    return name, entry, sections, memory_map.Image(sections)


def listing(sections, entry):
    """{address: instruction text} from objdump, with predicates and without '|| nop N' tails."""
    out = {}
    for address, mnemonic, operands, predicate, _ in string_refs.disassemble(sections, entry, details=True):
        if mnemonic.startswith("<"):
            continue
        text = f"{predicate} {mnemonic} {operands}".strip()
        out[address] = NOP_SUFFIX.sub("", text)
    return out


def call_sites(text, target):
    pattern = re.compile(rf"\b{target:08x} <")
    return sorted(a for a, t in text.items() if pattern.search(t))


def around(image, address, before, after):
    """The execute packet holding address, with `before` packets before it and `after` after it."""
    packets = execute_packets(image, address - 32 * (before + 1), address + 32 * (after + 1))
    k = next(i for i, p in enumerate(packets) if address in p)
    return packets[max(0, k - before):k + after + 1], k - max(0, k - before)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("image", help="official update .zip/.bin")
    parser.add_argument("address", nargs="?", help="show the fetch packet(s) at this address")
    parser.add_argument("--count", type=int, default=1, help="number of fetch packets (default 1)")
    parser.add_argument("--calls", metavar="TARGET", help="show every call or branch to TARGET")
    parser.add_argument("--before", type=int, default=2, help="execute packets before each site (default 2)")
    parser.add_argument("--after", type=int, default=5, help="execute packets after each site (default 5, "
                        "enough for a branch's delay slots)")
    args = parser.parse_args()
    if not args.address and not args.calls:
        parser.error("give an address or --calls TARGET")
    name, entry, sections, image = load(args.image)
    text = listing(sections, entry)
    if args.address:
        start = int(args.address, 16) & ~31
        for fp in range(start, start + 32 * args.count, 32):
            header = header_of(image, fp)
            print(f"fetch packet {fp:#010x} " + (f"header {header:#010x}" if header is not None else "(no header)")
                  + (" PROT" if protected(header) else ""))
            for address, size, p in fetch_packet(image, fp):
                end = "" if p else "   <- ends execute packet"
                print(f"  {address:08x} {size * 8:2d}-bit p={p}  {text.get(address, '')}{end}")
    if args.calls:
        target = int(args.calls, 16)
        for site in call_sites(text, target):
            print(f"== {site:#010x}")
            packets, k = around(image, site, args.before, args.after)
            for i, packet in enumerate(packets):
                mark = ">>" if i == k else "  "
                print(f" {mark} {packet[0]:08x}  " + " || ".join(text.get(a, "?") for a in packet))
    return 0


if __name__ == "__main__":
    sys.exit(main())
