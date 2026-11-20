#!/usr/bin/env python3
"""Validate an offline SmplTrek 3.2.174 default-heap capture.

This reads JSON only; it cannot capture RAM, allocate, free, or prove ownership.
See docs/08-heap-snapshot.md for the capture contract and limitations.
"""
import argparse
from bisect import bisect_right
import json
from pathlib import Path
import struct

SHA256 = "3b6848b0f041bcf23c73d4b0357d2f3d6dc9e7e03752b32ff7322e91e6814e53"
HEAP = 0xC16EE910
START, END = 0xC4000000, 0xC8000000
PROBE_SIZE = 256
MAX_NODES = 65536  # Capture limit, not an estimate of the live number of nodes.


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value):
    require(type(value) in (str, int), "expected an integer or 0x-prefixed integer string")
    return int(value, 0) if isinstance(value, str) else value


class Memory:
    def __init__(self, segments):
        self.segments = sorted((integer(s["address"]), bytes.fromhex(s["hex"]))
                               for s in segments)
        end = 0
        for address, data in self.segments:
            require(data and 0 <= address < address + len(data) <= 2**32,
                    "empty segment or segment outside 32-bit address space")
            require(address >= end, "overlapping capture segments")
            end = address + len(data)
        self.starts = [a for a, _ in self.segments]

    def read(self, address, size):
        out = bytearray()
        while len(out) < size:
            index = bisect_right(self.starts, address) - 1
            require(index >= 0, f"missing captured bytes at {address:#010x}")
            base, data = self.segments[index]
            offset = address - base
            require(offset < len(data), f"missing captured bytes at {address:#010x}")
            part = data[offset:offset + size - len(out)]
            out.extend(part)
            address += len(part)
        return bytes(out)

    def words(self, address, count):
        return struct.unpack("<" + "I" * count, self.read(address, count * 4))


def validate(snapshot):
    require(snapshot["format"] == "smpltrek-heap-snapshot/1", "unsupported snapshot format")
    require(snapshot["firmware_sha256"] == SHA256, "unsupported firmware SHA-256")
    capture = snapshot["capture"]
    require(isinstance(capture["boot_id"], str) and capture["boot_id"].strip(),
            "capture needs a nonempty boot_id")
    require(isinstance(capture["phase"], str) and capture["phase"].strip(),
            "capture needs a nonempty phase")
    require(capture["coherent"] is True and capture["method"] in ("heap-gate", "halted"),
            "capture must attest one coherent heap-gate or halted snapshot")
    memory = Memory(snapshot["segments"])
    fxns, alignment, base, node, size, minimum = memory.words(HEAP, 6)
    require((fxns, alignment, base, size, minimum) ==
            (0xC16C90D0, 8, START, END - START, 8), "unexpected heap configuration")
    nodes = []
    free = largest = previous_end = 0
    while node:
        require(len(nodes) < MAX_NODES, "node capture limit exceeded; result incomplete")
        require(START <= node <= END - 8 and node % 8 == 0,
                f"invalid free-node address {node:#010x}")
        require(not nodes or node > previous_end,
                "free list cycles, descends, overlaps, or contains uncoalesced adjacent blocks")
        following, length = memory.words(node, 2)
        require(length >= 8 and length % 8 == 0 and node + length <= END,
                f"invalid free-node size at {node:#010x}")
        previous_end = node + length
        nodes.append((node, previous_end))
        free += length
        largest = max(largest, length)
        node = following

    stats = {"total_size": size, "total_free_size": free, "largest_free_size": largest}
    if "stats" in snapshot:
        require({k: integer(snapshot["stats"][k]) for k in stats} == stats,
                "captured statistics disagree with the free list")
    probe_status = "not supplied"
    if "probe" in snapshot:
        probe = snapshot["probe"]
        require(probe["boot_id"] == capture["boot_id"], "probe belongs to another boot")
        pointer = integer(probe["pointer"])
        raw = pointer - 8
        require(START <= raw and pointer + PROBE_SIZE <= END and raw % 8 == 0,
                "probe interval is outside the heap or misaligned")
        expected = bytes.fromhex(probe["expected_hex"])
        require(len(expected) == PROBE_SIZE, "expected probe pattern must be exactly 256 bytes")
        require(memory.words(raw, 2) == (raw, PROBE_SIZE + 8), "probe malloc header changed")
        require(all(pointer + PROBE_SIZE <= a or raw >= b for a, b in nodes),
                "probe overlaps a free block")
        require(memory.read(pointer, PROBE_SIZE) == expected, "probe pattern changed")
        probe_status = "header and pattern match; interval is outside captured free list"
    return {"status": "structurally consistent", "boot_id": capture["boot_id"],
            "phase": capture["phase"], "free_nodes": len(nodes), **stats,
            "probe": probe_status, "ownership_proven": False,
            "limitation": "Capture provenance and coherence are caller attestations. "
                          "A reset followed by reallocation can pass these checks. "
                          "This result does not authorize freeing a retained pointer."}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    try:
        result = validate(json.loads(args.snapshot.read_text()))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"snapshot not validated: {error}\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
