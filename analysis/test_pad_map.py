"""Pins the line PAD in docs/04-hardware-access.md ("Inputs", REC SRC) against the simulated code of SmplTrek
3.2.174. Run:
python3 -B -m unittest discover -s analysis -p "test_pad_map.py" -v

Needs firmware/ and the work listings (as test_rec_src_map.py); skipped without them.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hw_compare   # noqa: E402
import pad_map      # noqa: E402

P = hw_compare.PRODUCTS["smpltrek"]
NEEDED = [ROOT / P["image"], ROOT / P["listing"]]
GP13 = 1 << 19      # GP1[n] is bit 16 + n of the bank 0/1 registers (SPRUH79C Table 19-2)


@unittest.skipUnless(all(p.exists() for p in NEEDED), "official update or work listing not present")
class Simulated(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = pad_map.Session()

    def test_value_change(self):
        for src, d, new, pad, pin in ((7, 1, 8, 1, ["low"]), (8, -1, 7, 0, ["high"]),
                                      (9, 1, 10, 1, ["low"]), (10, -1, 9, 0, ["high"])):
            self.assertEqual(self.s.change(pad_map.VALUE_CHANGE, src, d), (new, pad, pin), (src, d))

    def test_group_change_leaves_pad(self):
        self.assertEqual(self.s.change(pad_map.GROUP_CHANGE, 8, 1), (9, 0, ["high"]))
        self.assertEqual(self.s.change(pad_map.GROUP_CHANGE, 7, 1), (9, 0, []))

    def test_apply(self):
        self.assertEqual(self.s.apply(0), ([], [("SET_DATA01", GP13)]))
        codec, pins = self.s.apply(1)
        self.assertEqual(dict(codec), {19: 0x84, 22: 0x84, 21: 0xFC, 24: 0xFC, 15: 0, 16: 0})
        self.assertIn(("CLR_DATA01", GP13), pins)

    def test_routes(self):
        r = self.s.routes()
        low = {k for k, (_, pins) in r.items() if ("CLR_DATA01", GP13) in pins}
        self.assertEqual(low, {(0, 8), (1, 8), (0, 13), (1, 13)})        # only the two PAD routes
        self.assertEqual(r[(0, 8)][0], [(17, 0xFF), (21, 0xFC), (19, 0x84)])   # left ADC: LINE1L, no PGA write
        self.assertEqual(r[(0, 13)][0], [(17, 0xFF), (19, 0xFC), (21, 0x84)])  # left ADC: LINE1R (cross path)
        self.assertIn(("SET_DATA01", 1 << 18), r[(0, 1)][1])                   # built-in mic: GP1[2] high

    def test_pin(self):
        self.assertEqual(self.s.pin(0), [("SET_DATA01", GP13)])
        self.assertEqual(self.s.pin(1), [("CLR_DATA01", GP13)])


if __name__ == "__main__":
    unittest.main()
