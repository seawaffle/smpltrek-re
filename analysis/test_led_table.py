"""Pins the complete panel LED table (analysis/led_table.py, 04-hardware-access.md "Panel LEDs"): all 144 addresses,
every device observation consistent with the simulated SmplTrek 3.2.174 tables, and the grade counts. Run:
python3 -B -m unittest discover -s analysis -p "test_led_table.py" -v

Needs firmware/ and the work listings and match files (as test_panel_map.py); skipped without them.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import led_table    # noqa: E402
import panel_map    # noqa: E402
from test_panel_map import NEEDED   # noqa: E402


@unittest.skipUnless(all(p.exists() for p in NEEDED), "official updates or work listings not present")
class Table(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.driven = led_table.build(panel_map.Session("smpltrek"))

    def test_every_address_once_and_no_conflict(self):
        self.assertEqual(len(self.rows), 144)
        self.assertEqual([abc for abc, row in self.rows.items() if row[1] == "CONFLICT"], [])

    def test_grades(self):
        counts = {}
        for _, grade, _ in self.rows.values():
            counts[grade] = counts.get(grade, 0) + 1
        self.assertEqual(counts, {"device": 38, "device-group": 24, "static": 53, "unused": 29})

    def test_unused_addresses_are_exactly_those_the_stock_never_drives(self):
        unused = {abc for abc, row in self.rows.items() if row[1] == "unused"}
        named_row0_planes = {(a, 0, c) for a in range(3) for c in range(6)}
        self.assertEqual(unused & (self.driven | named_row0_planes), set())
        self.assertEqual(len(self.driven | named_row0_planes) + len(unused), 144)

    def test_known_identities(self):
        self.assertEqual(self.rows[(0, 1, 1)][:2], ("TRK 2 green", "device"))
        self.assertEqual(self.rows[(2, 5, 4)][0], "STEP 9 green")
        self.assertEqual(self.rows[(1, 4, 7)][0], "OK red")
        self.assertEqual(self.rows[(2, 0, 3)][0], "VALUE encoder blue")


if __name__ == "__main__":
    unittest.main()
