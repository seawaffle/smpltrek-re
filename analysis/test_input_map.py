"""Pins "Key matrix" and "Encoders" in docs/04-hardware-access.md against the simulated stock code of SmplTrek
3.2.174. Run:
python3 -B -m unittest discover -s analysis -p "test_input_map.py" -v

Needs firmware/ and the work listing; skipped without them.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hw_compare   # noqa: E402
import input_map    # noqa: E402

P = hw_compare.PRODUCTS["smpltrek"]


@unittest.skipUnless((ROOT / P["image"]).exists() and (ROOT / P["listing"]).exists(), "official update not present")
class Simulated(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = input_map.Session()

    def test_key_matrix(self):
        bits = self.s.key_bits()
        for r in range(6):
            for c, pin in enumerate(input_map.COLUMNS):
                self.assertEqual(bits[(r, pin)], [8 * r + c], (r, pin))
        self.assertEqual(bits[("GP5", 10)], [4])            # replaces row 0 column 4, active low

    def test_key_debounce(self):
        # In scans of the key's own row (every 6 polls): presses register on the first closed scan, even a single
        # one; bits 0-31 release only after two consecutive open scans (a one-scan opening is filtered), bits
        # 32-47 (STEP) on the first open scan (a one-scan opening is reported). One key per row; all 48 were run
        # by hand on 2026-11-15 with the same split. key_timing leaves the scanner idle (all open).
        s = input_map.Session()
        s.install_switch_delegate()
        filtered = {"press": [1], "release": [2], "press_glitch": [True], "release_glitch": [False]}
        unfiltered = {"press": [1], "release": [1], "press_glitch": [True], "release_glitch": [True]}
        for row, pin in ((0, 1), (1, 6), (2, 4), (3, 11), (4, 1), (5, 11)):
            self.assertEqual(s.key_timing((row, pin)), filtered if row < 4 else unfiltered, (row, pin))

    def test_encoder_detents(self):
        for i in range(5):
            self.assertEqual(self.s.turn(i, [1, 0, 2, 3]), [(i, -1)], i)    # one step per detent
            self.assertEqual(self.s.turn(i, [2, 0, 1, 3]), [(i, 1)], i)
        self.assertEqual(sum(n for _, n in self.s.turn(0, [1, 0, 2, 3] * 3)), -3)

    def test_encoder_bounce(self):
        # Every arrival at phase 0 with a direction set counts once; bounces are not undone. Reported totals
        # (the accumulator itself is cleared by each 16-poll report, so it is not compared mid-sequence).
        def total(seq):
            return sum(n for _, n in self.s.turn(2, seq))
        self.assertEqual(total([3, 1, 3]), 0)
        self.assertEqual(total([1, 0, 1, 3]), -1)
        self.assertEqual(total([1, 0, 1, 0, 2, 3]), -2)
        self.assertEqual(total([2, 0, 2, 0, 1, 3]), 2)
        self.assertEqual(total([0, 3]), 0)                  # no direction yet: not counted

    def test_power_on_check(self):
        self.assertEqual(self.s.power_on_check([1])[:2], (0, []))         # key not held at entry: 0 at once
        r, sleeps, writes = self.s.power_on_check([0])                    # held 10 x 50 ms: power hold, 1
        self.assertEqual((r, sleeps), (1, [50] * 10))
        self.assertIn((input_map.SET45, 1 << 11), writes)                 # GP4[11] high (SET_DATA45 bit 11)
        self.assertEqual(self.s.power_on_check([1], started=True)[0], 2)
        self.assertIsNone(self.s.power_on_check([0, 0, 0, 1], max_cycles=100000)[0])   # released: never returns

    def test_sd_card_detect(self):
        self.assertEqual((self.s.sd_card_present(0), self.s.sd_card_present(1)), (1, 0))


if __name__ == "__main__":
    unittest.main()
