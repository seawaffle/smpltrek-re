"""Pins the panel LED addressing, the panel-MCU command bytes and the flash write-enable byte in
docs/04-hardware-access.md ("Panel MCU on UART1", "SPI flash on SPI0") against the simulated code of SmplTrek
3.2.174, Lofi-12 XT 1.5.205 and CyDrums 1.1.84. Run:
python3 -B -m unittest discover -s analysis -p "test_panel_map.py" -v

Needs firmware/ and the work listings and match files (as test_hw_compare.py); skipped without them.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hw_compare   # noqa: E402
import panel_map    # noqa: E402

NEEDED = [ROOT / p[k] for p in hw_compare.PRODUCTS.values() for k in ("image", "listing")] + \
         [ROOT / p["match"] for p in hw_compare.PRODUCTS.values() if p["match"]]

# pad -> (v1, v2, v3) LED addresses (a, b, c), as in 04-hardware-access.md
PADS = [((2, 1, 5), (2, 1, 4), (2, 1, 6)), ((2, 1, 2), (2, 1, 1), (2, 1, 3)), ((0, 1, 5), (0, 1, 4), (0, 1, 6)),
        ((0, 1, 2), (0, 1, 1), (0, 1, 3)), ((1, 1, 5), (1, 1, 4), (1, 1, 6)), ((1, 1, 2), (1, 1, 1), (1, 1, 3)),
        ((2, 2, 4), (2, 2, 3), (2, 2, 5)), ((0, 2, 7), (0, 2, 6), (0, 1, 0)), ((1, 2, 4), (1, 2, 3), (1, 2, 5)),
        ((1, 2, 7), (1, 2, 6), (1, 1, 0)), ((0, 2, 4), (0, 2, 3), (0, 2, 5)), ((2, 2, 7), (2, 2, 6), (2, 1, 0)),
        ((0, 2, 1), (0, 2, 0), (0, 2, 2)), ((2, 2, 1), (2, 2, 0), (2, 2, 2)), ((1, 2, 1), (1, 2, 0), (1, 2, 2))]


@unittest.skipUnless(all(p.exists() for p in NEEDED), "official updates or work listings not present")
class Simulated(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = {key: panel_map.Session(key).all() for key in hw_compare.PRODUCTS}

    def test_same_in_three_products(self):
        for key in ("lofi12", "cydrums"):
            self.assertEqual(self.r[key], self.r["smpltrek"], key)

    def test_pads(self):
        self.assertEqual([tuple(abc) for _, abc in self.r["smpltrek"]["pads"]], PADS)

    def test_every_led_once(self):
        g = self.r["smpltrek"]["groups"]
        leds = [x for address, _ in panel_map.GROUPS for x in g[address]]
        self.assertEqual(len(leds), len(set(leds)))
        pad_leds = {x for abc in PADS for x in abc}
        self.assertTrue(pad_leds <= set(leds))
        two_channel = [x for x in leds if x[1] >= 3 and x[2] % 2 == 0]
        self.assertEqual(len(two_channel), 26)
        for a, b, c in two_channel:     # every even channel of rows 3-5 has its odd partner in the other group
            self.assertIn((a, b, c + 1), leds)
        row0 = sorted(x for x in leds if x[1] == 0)
        self.assertEqual(row0, [(a, 0, c) for a in range(3) for c in range(6)])

    def test_step_leds(self):
        steps = panel_map.Session("smpltrek").steps()
        green = [g for _, g, _ in steps]
        self.assertEqual(green, [(1, 3, 0), (1, 3, 2), (0, 3, 2), (0, 3, 4), (0, 3, 6), (0, 4, 0), (1, 4, 2), (1, 4, 4),
                                 (2, 5, 4), (0, 3, 0), (2, 5, 6), (1, 3, 4), (1, 3, 6), (1, 4, 0), (0, 4, 2), (0, 4, 4)])
        for n, abc in ((3, (0, 3, 2)), (4, (0, 3, 4)), (5, (0, 3, 6)), (6, (0, 4, 0)), (10, (0, 3, 0)), (15, (0, 4, 2))):
            self.assertEqual(green[n - 1], abc)          # swept on the device (claim HW-48)
        self.assertTrue(all(r == (a, b, c + 1) for _, (a, b, c), r in steps))

    def test_commands(self):
        self.assertEqual([b for _, b in self.r["smpltrek"]["commands"]],
                         [b"\x90", b"\x91", b"\xB0", b"\xB1", b"\xB2", b"\xA0", b"\xC2"])

    def test_flash_write_enable(self):
        self.assertEqual(self.r["smpltrek"]["flash_write_enable"], b"\x06")


if __name__ == "__main__":
    unittest.main()
