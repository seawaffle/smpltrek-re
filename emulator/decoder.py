"""Decode current guest RAM with existing binutils; never use an app ELF as an instruction source."""
import base64
import ctypes
import json
import os
from pathlib import Path
import re
import struct
import sys
import zlib

from build import HERE, ROOT, digest
from ir import Instruction, instruction

CACHE_ENV = "SMPLTREK_DECODE_CACHE"


def decode_version():
    """Identity of everything that turns page bytes into installed packets, except the
    disassembler binary itself: clear the cache after changing that."""
    sources = [HERE / "decoder.py", HERE / "ir.py", HERE / "core/core.h"]
    sources += [ROOT / "analysis" / name for name in ("packets.py", "string_refs.py", "memory_map.py")]
    return digest(b"".join(digest(path.read_bytes()).encode() for path in sources))[:16]


class Decoder:
    def __init__(self, machine):
        self.machine = machine
        self.text = {}
        sys.path.insert(0, str(ROOT / "analysis"))
        try:
            import memory_map
            import packets
        finally:
            sys.path.pop(0)
        self.Image, self.packets = memory_map.Image, packets
        # Decoding one page costs tens of milliseconds. Its result depends only on the page
        # bytes, their address and the decoding sources, so it is kept across runs.
        setting = os.environ.get(CACHE_ENV)
        self.cache = None if setting == "off" else Path(setting or machine.work / "decode-cache") / decode_version()
        self.cache_hits = self.cache_misses = 0

    def populate(self, pc):
        base = pc & ~4095
        data = self.machine.read(base, 4096)
        # An execute packet can continue into the next fetch packet/page.
        try:
            tail = self.machine.read(base + 4096, 32)
        except ValueError:
            tail = b""
        entry = self.cache and self.cache / (digest(struct.pack("<I", base) + data + tail) + ".json.z")
        if entry and self.replay(entry, pc):
            self.cache_hits += 1
            return
        self.cache_misses += 1
        record = []
        self.decode(pc, base, data, tail, record)
        if entry:
            entry.parent.mkdir(parents=True, exist_ok=True)
            pending = entry.with_name(f"{entry.name}.{os.getpid()}.pending")
            stored = dict(text={str(a): t for a, t in self.page_text.items()}, packets=record)
            pending.write_bytes(zlib.compress(json.dumps(stored).encode(), 1))
            pending.replace(entry)

    def replay(self, entry, pc):
        try:
            stored = json.loads(zlib.decompress(entry.read_bytes()))
            packets = [(row[0], row[1], row[2], row[3], row[4], base64.b64decode(row[5])) for row in stored["packets"]]
            text = {int(address): value for address, value in stored["text"].items()}
        except (OSError, ValueError, KeyError, IndexError, TypeError, zlib.error):
            return False
        # A page whose requested packet did not decode takes the ordinary path for its error.
        if not any(address == pc for address, *_ in packets) or any(len(raw) % ctypes.sizeof(Instruction) for *_, raw in packets):
            return False
        self.text.update(text)
        for address, next_pc, protected, start, size, raw in packets:
            instructions = (Instruction * (len(raw) // ctypes.sizeof(Instruction))).from_buffer_copy(raw)
            self.machine.install(address, next_pc, protected, start, size, instructions)
        return True

    def decode(self, pc, base, data, tail, record):
        sections = [(base, data + tail)]
        image = self.Image(sections)
        text = self.packets.listing(sections, pc)
        self.page_text = dict(text)
        self.text.update(text)
        installed = set()
        for fetch in range(base, base + 4096, 32):
            for address, _, _ in self.packets.fetch_packet(image, fetch):
                try:
                    items, next_pc, protected, end = self.packet(image, text, address)
                    sizes = {a: size for fetch_base in range(address & ~31, end, 32)
                             for a, size, _ in self.packets.fetch_packet(image, fetch_base)}
                    compiled_items = []
                    for at, assembly in items:
                        size = sizes[at]
                        raw, offset = image.at(at, size)
                        bits = int.from_bytes(raw[offset:offset + size], "little")
                        # GNU's SPKERNEL disassembly searches backwards for SPLOOP. A loop
                        # can begin on the previous decode page, outside this ELF snapshot.
                        # Recognize the ISA encoding directly; the core interprets the field
                        # using the active loop's ii, including compact encodings.
                        kernel = (bits & 0xf03ffffe == 0x00034000 if size == 4
                                  else bits & 0x3c7e == 0x1c66)
                        compiled = instruction(at, "spkernel 0,0" if kernel else assembly)
                        if kernel:
                            field = (bits >> 22) & 63 if size == 4 else ((bits >> 7) & 7) | (((bits >> 14) & 3) << 3) | ((bits & 1) << 5)
                            compiled.reserved |= 0x10000 | (field << 8)
                            self.text[at] = self.page_text[at] = "spkernel (raw stage/cycle field)"
                        compiled_items.append(compiled)
                    instructions = (Instruction * len(compiled_items))(*compiled_items)
                    self.machine.install(address, next_pc, protected, address & ~31, end - (address & ~31), instructions)
                    installed.add(address)
                    record.append([address, next_pc, bool(protected), address & ~31, end - (address & ~31),
                                   base64.b64encode(bytes(instructions)).decode()])
                except (ValueError, StopIteration):
                    if address == pc:
                        raise
        if pc not in installed:
            raise ValueError(f"{pc:#010x} is not a decodable instruction start")

    def packet(self, image, text, start):
        items, address, protected = [], start, False
        while len(items) < 8:
            units = self.packets.fetch_packet(image, address)
            index = next(i for i, unit in enumerate(units) if unit[0] == address)
            for at, size, parallel in units[index:]:
                value = text.get(at)
                if value is None:
                    data, offset = image.at(at, size)
                    if size == 4 and struct.unpack_from("<I", data, offset)[0] == 0:
                        value = "nop"
                    else:
                        value = "unsupported"
                items.append((at, value))
                protected |= self.packets.protected(self.packets.header_of(image, at)) and bool(re.search(r"\bld\w+\b", value))
                if len(items) > 8:
                    raise ValueError("execute packets longer than eight instructions are unsupported")
                if not parallel:
                    following = next((unit[0] for unit in units if unit[0] > at), (at & ~31) + 32)
                    return items, following, protected, (at & ~31) + 32
            address = (address & ~31) + 32
        raise ValueError("unterminated execute packet")
