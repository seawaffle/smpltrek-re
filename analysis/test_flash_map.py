from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flash_map  # noqa: E402

TOTAL = 32 << 20


def blob(seed, size):
    return bytes((i * 7 + seed) & 0xFF for i in range(size))


def header(tag, size, version, last=0):
    return tag + struct.pack("<7I", size, 0, 0xFFFFFFFE, *version, last)


def pmtd(partitions):
    """A 'pmtd' image: header, directory of (tag, address, size), then the payloads back to back."""
    directory = b"".join(tag + struct.pack("<II", address, len(payload)) for tag, address, payload in partitions)
    body = b"".join(payload for _, _, payload in partitions)
    size = 32 + len(directory) + len(body)
    return header(b"pmtd", size, (2, 0, 22), len(partitions)) + directory + body


def cmtd(image):
    """Minimal container around one 'pmtd' image (descriptor type 2); CRC fields are not checked by parse."""
    total = 24 + 24 + len(image)
    return (b"cmtd" + struct.pack("<5I", total, 0, 0, 5, 1)
            + struct.pack("<6I", 2, 2, 0, 22, 48, len(image)) + image)


NEW = [(b"PKIT", 0x441000, blob(1, 0x1800)), (b"PDPT", 0x1000000, blob(2, 0x2100))]
OLD = [(b"PKIT", 0x441000, blob(3, 0x1000)), (b"PDSN", 0x1000000, blob(4, 0x6000))]


def dump():
    data = bytearray(b"\xff" * TOTAL)
    data[0:0x3000] = blob(9, 0x3000)
    data[flash_map.BMTD:flash_map.BMTD + 28] = header(b"bmtd", 0x40000, (1, 0, 17))[:28]
    data[flash_map.MMTD:flash_map.MMTD + 0x100] = header(b"mmtd", 0x100, (3, 2, 174)) + blob(5, 0xE0)
    image = pmtd(NEW)
    data[flash_map.PMTD:flash_map.PMTD + 32 + 24] = image[:56]
    for _, address, payload in NEW:
        data[address:address + len(payload)] = payload
    # stale OLD PDSN bytes past the new PDPT's last sector, as a sector-wise erase would leave them
    data[0x1003000:0x1006000] = OLD[1][2][0x3000:0x6000]
    for base in flash_map.SETTINGS:
        data[base:base + 4] = b"PREF"
        data[base + 0xC00:base + 0xC10] = b"PREX" + bytes(12)
    return bytes(data)


class FlashMap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = dump()
        cls.refs = [("new", flash_map.content_partitions(cmtd(pmtd(NEW)))),
                    ("old", flash_map.content_partitions(cmtd(pmtd(OLD))))]

    def test_content_partitions_follow_the_directory(self):
        parts = self.refs[0][1]
        self.assertEqual(sorted(parts), ["PDPT", "PKIT"])
        self.assertEqual(parts["PDPT"], (0x1000000, NEW[1][2]))

    def test_regions_come_from_the_headers(self):
        names = [(s, e, n.split(" (")[0]) for s, e, n in flash_map.regions(self.data)]
        self.assertIn((0, 0x3000, "boot data"), names)
        self.assertIn((flash_map.BMTD, 0x40000, "bmtd header"), names)
        self.assertIn((0x40000, 0x40100, "mmtd system image"), names)
        self.assertIn((0x441000, 0x442800, "partition PKIT"), names)
        self.assertIn((0x1000000, 0x1002100, "partition PDPT"), names)
        self.assertIn((0x1FFE000, 0x1FFEC10, "settings sector"), names)

    def test_partitions_matched_and_stale_span_explained(self):
        report = flash_map.build(self.data, self.refs)
        pkit = next(r for r in report["regions"] if r["name"] == "partition PKIT")
        self.assertEqual(pkit["matches"][0][:2], ("new", True))
        self.assertEqual(pkit["matches"][1][:2], ("old", False))
        self.assertEqual(report["unexplained"], [{"start": 0x1003000, "end": 0x1006000, "explained_by": ["old PDSN"]}])

    def test_unknown_span_is_reported_unexplained(self):
        data = bytearray(self.data)
        data[0x1800000:0x1800010] = b"\x01" * 16
        spans = flash_map.build(bytes(data), self.refs)["unexplained"]
        self.assertIn({"start": 0x1800000, "end": 0x1800010, "explained_by": []}, spans)

    def test_short_erased_gaps_merge(self):
        data = b"\xff" * 4 + b"\x01" + b"\xff" * 10 + b"\x02" + b"\xff" * 100 + b"\x03"
        self.assertEqual(flash_map.nonerased_spans(data, 0, len(data), gap=64), [(4, 16), (116, 117)])


if __name__ == "__main__":
    unittest.main()
