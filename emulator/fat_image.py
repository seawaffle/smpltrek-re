"""Read-only FAT12/16 superfloppy inspection, independent of guest or host FatFs.

Used to inspect the private synthetic cards, not to implement guest file operations.
MBR partitions and FAT32 deliberately remain unsupported here.
"""
from dataclasses import dataclass
import struct


@dataclass(frozen=True)
class Entry:
    path: str
    short_name: str
    directory: bool
    cluster: int
    size: int


class FatImage:
    def __init__(self, data):
        self.data = bytes(data)
        if len(self.data) < 512 or self.data[510:512] != b"\x55\xaa":
            raise ValueError("missing FAT boot signature")
        self.sector = self.u16(11)
        self.spc, reserved, copies = self.data[13], self.u16(14), self.data[16]
        roots, fat_sectors = self.u16(17), self.u16(22)
        total = self.u16(19) or self.u32(32)
        if (self.sector != 512 or not self.spc or self.spc & (self.spc - 1) or self.spc > 128
                or not reserved or copies not in (1, 2) or not roots or not fat_sectors
                or total * self.sector > len(self.data)):
            raise ValueError("unsupported or invalid FAT12/16 superfloppy geometry")
        self.fat = reserved * self.sector
        self.fat_size = fat_sectors * self.sector
        root = self.fat + copies * self.fat_size
        root_size = roots * 32
        self.first_data = root + (root_size + 511) // 512 * 512
        self.cluster_size = self.spc * self.sector
        self.clusters = (total * self.sector - self.first_data) // self.cluster_size
        self.bits = 12 if self.clusters < 4085 else 16
        if self.clusters <= 0 or self.clusters >= 65525:
            raise ValueError("unsupported FAT cluster count")
        needed = ((self.clusters + 2) * self.bits + 7) // 8
        if needed > self.fat_size:
            raise ValueError("FAT is too small for its data region")
        if copies == 2 and self.data[self.fat:self.fat + self.fat_size] != self.data[self.fat + self.fat_size:root]:
            raise ValueError("FAT copies disagree")
        self.entries = {}
        self._visited_directories = set()
        self._directory(self.data[root:root + root_size], "", 0)

    def u16(self, offset):
        return struct.unpack_from("<H", self.data, offset)[0]

    def u32(self, offset):
        return struct.unpack_from("<I", self.data, offset)[0]

    def chain(self, cluster):
        if cluster < 2 or cluster >= self.clusters + 2:
            raise ValueError("invalid FAT start cluster")
        seen = set()
        end = 0xff8 if self.bits == 12 else 0xfff8
        while cluster < end:
            if cluster < 2 or cluster >= self.clusters + 2 or cluster in seen:
                raise ValueError("invalid or looping FAT cluster chain")
            seen.add(cluster)
            yield cluster
            if self.bits == 12:
                value = self.u16(self.fat + cluster + cluster // 2)
                cluster = (value >> (4 if cluster & 1 else 0)) & 0xfff
            else:
                cluster = self.u16(self.fat + cluster * 2)

    def _content(self, cluster):
        return b"".join(self.data[self.first_data + (c - 2) * self.cluster_size:
                                  self.first_data + (c - 1) * self.cluster_size]
                        for c in self.chain(cluster))

    @staticmethod
    def _checksum(short):
        value = 0
        for byte in short:
            value = (((value & 1) << 7) + (value >> 1) + byte) & 255
        return value

    def _directory(self, data, parent, depth):
        if depth > 16:
            raise ValueError("FAT directory depth exceeds inspection limit")
        parts, checksum, following = {}, None, 0
        for offset in range(0, len(data), 32):
            raw = data[offset:offset + 32]
            if len(raw) != 32 or raw[0] == 0:
                break
            if raw[0] == 0xe5:
                parts, checksum, following = {}, None, 0
                continue
            if raw[11] == 15:
                index = raw[0] & 31
                if raw[0] & 64:
                    parts, checksum, following = {}, raw[13], index
                if not index or index != following or raw[13] != checksum or raw[12] or raw[26:28] != b"\0\0":
                    raise ValueError("invalid FAT long-name sequence")
                parts[index] = raw[1:11] + raw[14:26] + raw[28:32]
                following -= 1
                continue
            short = raw[:8].decode("ascii").rstrip()
            extension = raw[8:11].decode("ascii").rstrip()
            short_name = short + ("." + extension if extension else "")
            name = short_name
            if parts:
                if following or checksum != self._checksum(raw[:11]):
                    raise ValueError("FAT long-name checksum mismatch")
                units = list(struct.unpack("<" + "H" * (13 * len(parts)), b"".join(parts[i] for i in sorted(parts))))
                if 0 in units:
                    units = units[:units.index(0)]
                name = struct.pack("<" + "H" * len(units), *units).decode("utf-16le")
            parts, checksum, following = {}, None, 0
            if raw[11] & 8 or short in (".", ".."):
                continue
            if not name or "/" in name or "\\" in name:
                raise ValueError("invalid FAT entry name")
            entry = Entry(parent + "/" + name, short_name, bool(raw[11] & 16),
                          struct.unpack_from("<H", raw, 26)[0], struct.unpack_from("<I", raw, 28)[0])
            key = entry.path.casefold()
            if key in self.entries or len(self.entries) >= 4096:
                raise ValueError("duplicate FAT name or inspection entry limit exceeded")
            self.entries[key] = entry
            if entry.directory:
                if entry.cluster in self._visited_directories:
                    raise ValueError("cross-linked FAT directories")
                self._visited_directories.add(entry.cluster)
                self._directory(self._content(entry.cluster), entry.path, depth + 1)

    def entry(self, path):
        return self.entries["/" + str(path).strip("/").casefold()]

    def read(self, path):
        entry = self.entry(path)
        if entry.directory:
            raise ValueError("cannot read a FAT directory as a file")
        data = self._content(entry.cluster) if entry.cluster else b""
        if len(data) < entry.size:
            raise ValueError("FAT file is shorter than its directory size")
        return data[:entry.size]
