"""Pins the SPI flash commands in docs/04-hardware-access.md ("SPI flash on SPI0") against the simulated driver of
SmplTrek 3.2.174. Run:
python3 -B -m unittest discover -s analysis -p "test_flash_cmd_map.py" -v

Needs firmware/ and the work listing; skipped without them.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import flash_cmd_map  # noqa: E402
import hw_compare     # noqa: E402

P = hw_compare.PRODUCTS["smpltrek"]
WREN, POLL = [("W", b"\x06")], [("W", b"\x05"), ("R", 1)]


@unittest.skipUnless((ROOT / P["image"]).exists() and (ROOT / P["listing"]).exists(), "official update not present")
class Simulated(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = flash_cmd_map.Session()

    def test_erase_sizes(self):
        done, tr = self.s.erase(0x441000, 0x11000)
        self.assertTrue(done)
        cmds = [t[0][1] for t in tr if len(t[0][1]) == 4]
        self.assertEqual([c.hex() for c in cmds],
                         ["20441000", "20442000", "20443000", "20444000", "20445000", "20446000", "20447000",
                          "52448000", "20450000", "20451000"])
        self.assertEqual(tr[:3], [POLL, WREN, [("W", bytes.fromhex("20441000"))]])   # poll, write enable, erase
        done, tr = self.s.erase(0x450000, 0x10000)
        self.assertEqual(tr, [POLL, WREN, [("W", bytes.fromhex("d8450000"))]])

    def test_program_and_read(self):
        _, tr = self.s.program(0x441000, 300)
        self.assertEqual(tr[:3], [POLL, WREN, [("W", bytes.fromhex("02441000")), ("W", 256)]])   # one 256-byte page
        _, tr = self.s.read(0x441000, 300)
        self.assertEqual(tr[:2], [POLL, [("W", bytes.fromhex("03441000")), ("R", 300)]])


if __name__ == "__main__":
    unittest.main()
