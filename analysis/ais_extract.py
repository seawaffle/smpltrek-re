#!/usr/bin/env python3
"""Extract the supported AIS subset from the start of a captured C6748 flash.

Read-only towards the input. This parses commands; it never executes them.
Reference: TI SPRAAT2F sections 4.1, 4.6, 4.8, 4.9.
Unsupported commands fail closed. This is not a general AIS interpreter.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

import mmtd2elf

MAGIC = 0x41504954
LOAD, CLOSE, FUNCTION, SEQUENTIAL = 0x58535901, 0x58535906, 0x5853590D, 0x58535963


def parse(data, limit=None):
    limit = len(data) if limit is None else min(limit, len(data))
    position = 0
    commands, sections = [], []

    def words(count):
        nonlocal position
        if position + count * 4 > limit:
            raise ValueError(f"truncated AIS command at {position:#x}")
        values = struct.unpack_from("<" + "I" * count, data, position)
        position += count * 4
        return values

    if words(1)[0] != MAGIC:
        raise ValueError("missing AIS magic at offset zero")
    while position < limit:
        offset = position
        opcode = words(1)[0]
        command = {"offset": offset, "opcode": opcode}
        if opcode == SEQUENTIAL:
            command["kind"] = "sequential_read_enable"
        elif opcode == FUNCTION:
            packed = words(1)[0]
            command.update(kind="function_execute", function=packed & 0xFFFF,
                           arguments=list(words(packed >> 16)))
        elif opcode == LOAD:
            address, size = words(2)
            padded = (size + 3) & ~3
            if not size or address + size > 2**32 or position + padded > limit:
                raise ValueError(f"invalid/truncated section at {offset:#x}")
            if any(address < a + len(d) and a < address + size for a, d in sections):
                raise ValueError("overlapping AIS loads unsupported; cannot flatten safely")
            payload = data[position:position + size]
            command.update(kind="section_load", address=address, size=size,
                           file_offset=position, sha256=hashlib.sha256(payload).hexdigest())
            sections.append((address, payload))
            position += padded
        elif opcode == CLOSE:
            entry = words(1)[0]
            if not any(a <= entry < a + len(d) for a, d in sections):
                raise ValueError("entry point is outside loaded sections")
            command.update(kind="jump_close", entry=entry)
            commands.append(command)
            return {"format": "sonicware-ais-extract/1",
                    "input_sha256": hashlib.sha256(data).hexdigest(),
                    "input_length": len(data), "ais_length": position,
                    "ais_sha256": hashlib.sha256(data[:position]).hexdigest(),
                    "entry": entry, "commands": commands}, sections
        else:
            raise ValueError(f"unsupported AIS opcode {opcode:#010x} at {offset:#x}")
        commands.append(command)
    raise ValueError("no Jump & Close within input limit")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path)
    parser.add_argument("--limit", type=lambda s: int(s, 0), default=0x40000,
                        help="maximum AIS input extent (default boot region 0x40000)")
    parser.add_argument("--out", type=Path, help="new directory for manifest, sections and ELF files")
    args = parser.parse_args(argv)
    try:
        report, sections = parse(args.dump.read_bytes(), args.limit)
        if args.out:
            # Never overwrite an existing extraction or source dump.
            code = {i for i, (a, d) in enumerate(sections) if a <= report["entry"] < a + len(d)}
            elf = mmtd2elf.build_elf(report["entry"], sections, code)
            segments = mmtd2elf.build_segments_only_elf(report["entry"], sections, code)
            args.out.mkdir(parents=True, exist_ok=False)
            for i, (address, data) in enumerate(sections):
                (args.out / f"section-{i:02d}-{address:08x}.bin").write_bytes(data)
            (args.out / "bootloader.elf").write_bytes(elf)
            (args.out / "bootloader.seg.elf").write_bytes(segments)
            (args.out / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        return 0
    except (OSError, ValueError) as error:
        parser.exit(2, f"AIS extraction failed: {error}\n")


if __name__ == "__main__":
    sys.exit(main())
