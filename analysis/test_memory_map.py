"""memory_map checks. Run: python3 -B -m unittest discover -s analysis -v

The corpus test needs the official updates in firmware/ (not tracked) and skips when they are absent.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import memory_map

IMAGE = ROOT / "firmware/smpltrek/SmplTrek v3.2.174.zip"


class RleTests(unittest.TestCase):
    def decode(self, data, rle24=True):
        return memory_map.rle(memory_map.Image([(0x1000, bytes(data))]), 0x1000, rle24)

    def test_formats_from_copy_decompress_rle_c(self):
        d = 0x97  # delimiter
        stream = [d, 1, 2,              # literals
                  d, 5, 0x41,           # 8-bit run: 5 x 'A'
                  d, 2,                 # run < 4: the delimiter itself, twice
                  d, 0, 0x01, 0x00, 0,  # 16-bit run: 256 x 0
                  d, 0, 0, 1, 0, 0, 7,  # 24-bit run (rle24): 0x010000 x 7
                  d, 0, 0, 0]           # end
        out = self.decode(stream)
        self.assertEqual(out[:2], b"\x01\x02")
        self.assertEqual(out[2:7], b"A" * 5)
        self.assertEqual(out[7:9], bytes([d, d]))
        self.assertEqual(out[9:265], bytes(256))
        self.assertEqual(out[265:], bytes([7]) * 0x10000)


# The corpus tests decode code with tools/tic6x objdump (tools/toolchain/build_tic6x_binutils.sh).
OBJDUMP_OK = (Path(__file__).resolve().parents[1] / "tools/tic6x/bin/tic6x-elf-objdump").exists()


@unittest.skipUnless(IMAGE.exists() and OBJDUMP_OK, "official updates not present in firmware/ (or tools/tic6x objdump missing)")
class CorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.program, cls.auto_init, cls.handlers, cls.base, cls.limit, cls.kinds, cls.regions = \
            memory_map.build_map(IMAGE)

    def test_copy_table_of_3_2_174(self):
        self.assertEqual((self.auto_init, self.handlers, self.base, self.limit),
                         (0xC168673C, 0xC16FFA00, 0xC16FFA08, 0xC16FFA98))
        self.assertEqual(self.kinds, ["rle24", "copy"])

    def test_known_regions(self):
        spans = {(r["start"], r["end"]): r["kind"] for r in self.regions}
        self.assertEqual(spans[(0xC0000000, 0xC1503404)], "zero-filled")
        self.assertEqual(spans[(0xC4000000, 0xC8000000)], "zero-filled")
        self.assertEqual(spans[(0xC16D4D30, 0xC16EFCDA)], "initialised")

    def test_default_heap_configuration(self):
        # Configuration reconstructed from startup data, not live free capacity.
        image = memory_map.Image(self.program.sections)
        heap = image.word(0xC16C6CC4)
        self.assertEqual(heap, 0xC16EE910)
        initialized = memory_map.Image([(r["start"], r["data"])
                                        for r in self.regions if "data" in r])
        words = [initialized.word(heap + offset) for offset in range(0, 24, 4)]
        self.assertEqual(words, [0xC16C90D0, 8, 0xC4000000, 0, 0x04000000, 8])
        self.assertEqual(words[2] + words[4], 0xC8000000)
        self.assertEqual([image.word(words[0] + n) for n in (8, 12, 20)],
                         [0xC168EA40, 0xC16A1520, 0xC1690940])
        self.assertEqual(image.word(0xC16C2E04), 1)
        self.assertEqual(image.word(0xC16D4330), 0xC169C2C0)
        self.assertEqual(image.word(0xC16C2D9C), 0xC16ED4A8)

    def test_allocation_failure_configuration(self):
        # Pin the firmware data underlying the failure-path analysis. These checks
        # do not execute the error hook or prove its output backend returns.
        image = memory_map.Image(self.program.sections)
        self.assertEqual(image.word(0xC16C6904), 0xC1686D40)
        self.assertEqual(image.word(0xC16C6954), 1)
        self.assertEqual(image.word(0xC16C69A4), 0xC16A1220)
        self.assertEqual(image.word(0xC16C0768) >> 16, 16)
        self.assertEqual(image.word(0xC16C1DC4), 0x001D0000)
        self.assertEqual(image.word(0xC16C68B4), 0x00030000)
        initialized = memory_map.Image([(r["start"], r["data"])
                                        for r in self.regions if "data" in r])
        self.assertEqual(initialized.word(0xC150174C), 0)

    def test_error_output_configuration(self):
        image = memory_map.Image(self.program.sections)
        initialized = memory_map.Image([(r["start"], r["data"])
                                        for r in self.regions if "data" in r])
        self.assertEqual(image.word(0xC16C6E54), 128)
        self.assertEqual(image.word(0xC16C6EF4), 0xC16EFCC0)
        self.assertEqual(image.word(0xC16C6C74), 0)
        self.assertEqual(image.word(0xC16C73FC), 0xC167A060)
        # Ring and logger state are reconstructed from the initialization records.
        self.assertEqual([initialized.word(0xC16D4D24 + n) for n in (0, 4, 8)],
                         [0xC1500718, 0, 0])
        self.assertEqual(initialized.word(0xC16EE258 + 32) & 0xFFFF, 0)

    def test_graphics_title_dispatch_configuration(self):
        # Data anchors for the separately inspected call chain, not execution proof.
        image = memory_map.Image(self.program.sections)
        initialized = memory_map.Image([(r["start"], r["data"])
                                        for r in self.regions if "data" in r])
        self.assertEqual(image.word(0xC16BAE74), 0xC154C548)
        self.assertEqual(image.word(0xC16C5338 + 12 * 4), 0xC15D3638)
        self.assertEqual(image.word(0xC16C5338 + 15 * 4), 0xC1666DA0)
        self.assertEqual(initialized.word(0xC16E1A14 + 28), 0x1000)
        self.assertEqual(initialized.word(0xC16E1A14 + 32), 0xC127FD90)

    def test_unclaimed_gap_below_default_heap(self):
        gaps, top = memory_map.unclaimed(self.regions)
        self.assertEqual(top, 0xC8000000)
        self.assertIn((0xC16FFA98, 0xC4000000), gaps)


if __name__ == "__main__":
    unittest.main()
