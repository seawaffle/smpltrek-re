"""Pins "Messages from the MCU" in docs/04-hardware-access.md against the simulated parser of SmplTrek 3.2.174. Run:
python3 -B -m unittest discover -s analysis -p "test_panel_rx_map.py" -v

Needs firmware/ and the work listing; skipped without them.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hw_compare     # noqa: E402
import panel_rx_map   # noqa: E402

P = hw_compare.PRODUCTS["smpltrek"]


@unittest.skipUnless((ROOT / P["image"]).exists() and (ROOT / P["listing"]).exists(), "official update not present")
class Simulated(unittest.TestCase):
    def setUp(self):
        self.s = panel_rx_map.Session()

    def test_analogue(self):
        self.assertEqual(self.s.feed([0xB3, 0x05, 0x7F]), [(0, 0xB3), (1, 3, 0x05 | 0x7F << 7)])   # lo then hi
        self.assertEqual(self.s.feed([0xBF, 0x00, 0x01]), [(0, 0xBF), (1, 15, 128)])
        self.assertEqual((self.s.channel(3), self.s.channel(15)), (16261, 128))

    def test_split_and_interrupted(self):
        self.assertEqual(self.s.feed([0xB2, 0x05]), [(0, 0xB2)])
        self.assertEqual(self.s.feed([0x7F]), [(1, 2, 16261)])                        # state kept between drains
        self.assertEqual(self.s.feed([0xB4, 0x05, 0xB5, 0x01, 0x02]), [(0, 0xB4), (1, 5, 257)])   # restart

    def test_info_and_unknown(self):
        self.assertEqual(self.s.feed([0xA1, 1, 2, 3, 4, 5, 6]), [(0, 0xA1)])
        self.assertEqual(self.s.info(), [1, 2, 3, 4, 5, 6])
        self.assertEqual(self.s.feed([0x90, 0xC1, 0x12]), [(0, 0x90), (0, 0xC1), (0, 0x12)])   # ignored types


if __name__ == "__main__":
    unittest.main()
