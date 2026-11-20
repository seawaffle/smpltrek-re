"""Independent card inspection: real FatFs fixtures plus explicit malformed chains/names."""
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build import WORK
from media import build_card
from fat_image import FatImage


@unittest.skipUnless(shutil.which("gcc"), "host GCC required for independent FatFs fixtures")
class FatInspection(unittest.TestCase):
    def setUp(self):
        WORK.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=WORK, prefix="test-fat-inspection-")
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)

    def fixture(self, size=2):
        payload = bytes(range(251)) * 43
        source = self.work / "payload.bin"; source.write_bytes(payload)
        card = build_card(self.work / f"card-{size}.img", {"/TEST/FILE.BIN": source}, size_mb=size)
        return card.read_bytes(), payload

    def test_fat12_and_fat16_nested_multi_cluster_file_exact_bytes(self):
        for size, bits in ((2, 12), (16, 16)):
            raw, payload = self.fixture(size)
            fat = FatImage(raw)
            self.assertEqual(fat.bits, bits)
            self.assertTrue(fat.entry("test").directory)
            self.assertEqual(fat.read("/test/file.bin"), payload)
            self.assertEqual(fat.data, raw)
            with self.assertRaisesRegex(ValueError, "directory"):
                fat.read("TEST")

    def test_long_names_and_a_card_over_64_mib_are_written_by_real_fatfs(self):
        payload = bytes(range(253)) * 300
        source = self.work / "payload.bin"; source.write_bytes(payload)
        files = {"/Kits/System/Pattern106": source, "/Kits/System/.KitConfig": source, "/SHORT.BIN": source}
        fat = FatImage(build_card(self.work / "long.img", files, size_mb=128, long_names=True).read_bytes())
        self.assertEqual((len(fat.data), fat.bits), (128 * 1024 * 1024, 16))
        for name in files:
            self.assertEqual(fat.read(name), payload, name)
        self.assertEqual(fat.entry("Kits/System/Pattern106").path.rsplit("/", 1)[-1], "Pattern106")  # case kept
        with self.assertRaises(Exception):                 # the default builder still insists on 8.3
            build_card(self.work / "short.img", {"/Kits/Pattern106": source})

    def test_real_vfat_long_name_checksum_and_order(self):
        # A known single-entry VFAT name preceding the real fixture's root directory entry.
        raw, payload = self.fixture()
        data = bytearray(raw)
        fat = FatImage(raw)
        root = fat.fat + fat.fat_size * raw[16]
        short = raw[root:root + 32]
        self.assertEqual(short[:11], b"TEST       ")
        units = "Long Folder".encode("utf-16le") + b"\0\0" + b"\xff\xff"
        lfn = bytearray(32); lfn[0] = 0x41; lfn[11] = 15; lfn[13] = 0x32
        lfn[1:11], lfn[14:26], lfn[28:32] = units[:10], units[10:22], units[22:26]
        data[root:root + 64] = lfn + short
        renamed = FatImage(data)
        self.assertEqual(renamed.read("Long Folder/FILE.BIN"), payload)
        data[root + 13] ^= 1
        with self.assertRaisesRegex(ValueError, "checksum"):
            FatImage(data)

    def test_loop_and_short_file_chains_fail_instead_of_fabricating_bytes(self):
        raw, _ = self.fixture()
        fat = FatImage(raw)
        cluster = fat.entry("TEST/FILE.BIN").cluster
        offset = fat.fat + cluster + cluster // 2
        def replace(value):
            data = bytearray(raw)
            old = struct.unpack_from("<H", data, offset)[0]
            value = (old & 15) | (value << 4) if cluster & 1 else (old & 0xf000) | value
            struct.pack_into("<H", data, offset, value)
            return FatImage(data)
        with self.assertRaisesRegex(ValueError, "looping"):
            replace(cluster).read("TEST/FILE.BIN")
        with self.assertRaisesRegex(ValueError, "shorter"):
            replace(0xfff).read("TEST/FILE.BIN")

    def test_invalid_geometry_and_disagreeing_fat_copies_fail(self):
        raw, _ = self.fixture()
        for offset, value in ((510, b"\0"), (13, b"\x03"), (17, b"\0\0"), (22, b"\0\0")):
            data = bytearray(raw); data[offset:offset + len(value)] = value
            with self.assertRaises(ValueError):
                FatImage(data)
        fat = FatImage(raw)
        data = bytearray(raw[:fat.fat + fat.fat_size] + raw[fat.fat:fat.fat + fat.fat_size] + raw[fat.fat + fat.fat_size:])
        data[16] = 2
        struct.pack_into("<H", data, 19, len(data) // 512)
        data[fat.fat + fat.fat_size + 3] ^= 1
        with self.assertRaisesRegex(ValueError, "copies disagree"):
            FatImage(data)


if __name__ == "__main__":
    unittest.main()
