"""Pins "REC SRC" in docs/04-hardware-access.md against the simulated code of SmplTrek 3.2.174. Run:
python3 -B -m unittest discover -s analysis -p "test_rec_src_map.py" -v

Needs firmware/ and the work listings (as test_codec_map.py); skipped without them.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hw_compare   # noqa: E402
import rec_src_map  # noqa: E402

NEEDED = [ROOT / hw_compare.PRODUCTS["smpltrek"][k] for k in ("image", "listing")]
# src -> (name, L mode, R level, planes, left ADC (on, inputs, PGA), right ADC (on, inputs, PGA))
L1L, L1R, M3R = ["LINE1L 0 dB"], ["LINE1R 0 dB"], ["MIC3R 0 dB"]
TABLE = {0: ("BltInMic", 0, 3, (1, 1), (True, M3R, 0), (False, L1R, 0)),
         1: ("Gtr", 1, 3, (1, 1), (True, L1L, 0), (False, L1R, 0)),
         2: ("Gtr", 2, 3, (1, 1), (True, L1L, 0), (False, L1R, 0)),
         3: ("Gtr", 3, 3, (1, 1), (True, L1L, 10), (False, L1R, 0)),
         4: ("DyMic", 6, 0, (2, 2), (False, L1L, 0), (True, L1R, 0)),
         5: ("DyMic", 6, 1, (2, 2), (False, L1L, 0), (True, L1R, 0)),
         6: ("DyMic", 6, 2, (2, 2), (False, L1L, 0), (True, L1R, 21)),
         7: ("LineSt", 6, 3, (1, 2), (True, L1L, 0), (True, L1R, 0)),
         8: ("LineSt", 6, 3, (1, 2), (True, L1L, 0), (True, L1R, 0)),
         9: ("LineMn", 6, 3, (1, 1), (True, L1L, 0), (False, L1R, 0)),
         10: ("LineMn", 6, 3, (1, 1), (True, L1L, 0), (False, L1R, 0)),
         11: ("USB", 7, 4, (1, 2), (False, [], 0), (True, L1R, 0))}
TABLE.update({n: ("ReSmp", 21, 18, (1, 2), (False, [], 0), (True, L1R, 0)) for n in range(12, 26)})
# pin levels each source leaves (last write wins)
PINS = {0: {"GP1[2]": 1, "GP7[14]": 1, "GP7[15]": 0, "GP5[11]": 0}, 2: {"GP1[2]": 0, "GP7[14]": 1, "GP7[15]": 1},
        5: {"GP7[15]": 0, "GP5[11]": 1}, 7: {"GP1[2]": 0, "GP7[14]": 1, "GP7[15]": 0, "GP5[11]": 0}}


@unittest.skipUnless(all(p.exists() for p in NEEDED), "official update or work listing not present")
class Simulated(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = rec_src_map.Session()
        cls.r = cls.s.all()

    def test_table(self):
        for src, (name, lm, rl, planes, left, right) in TABLE.items():
            r = self.r[src]
            f = r["fields"]
            self.assertEqual((r["name"], f["src"], f["l_mode"], f["r_level"], (f["plane0"], f["plane1"])),
                             (name, src, lm, rl, planes), src)
            for side, want in (("left", left), ("right", right)):
                a = r["adc"][side]
                self.assertEqual((a["powered"], a["inputs"], a["pga_db"]), want, (src, side))

    def test_pins(self):
        for src, want in PINS.items():
            last = {}
            for p in self.r[src]["pins"]:
                last[p[1:]] = 1 if p[0] == "+" else 0
            self.assertEqual({k: last[k] for k in want}, want, src)

    def test_one_adc_sources_read_its_slot(self):
        # every source that powers exactly one ADC reads both planes from one slot: left ADC -> 1, right ADC -> 2
        for src in range(11):
            a, f = self.r[src]["adc"], self.r[src]["fields"]
            if a["left"]["powered"] != a["right"]["powered"]:
                slot = 1 if a["left"]["powered"] else 2
                self.assertEqual((f["plane0"], f["plane1"]), (slot, slot), src)

    def test_monitor_gate(self):
        # the built-in mic is monitored only while GP3[8] reads high; a line source ignores the pin
        self.assertEqual([self.s.monitor_gate(0, p) for p in (0, 1)], [False, True])
        self.assertEqual([self.s.monitor_gate(7, p) for p in (0, 1)], [True, True])


if __name__ == "__main__":
    unittest.main()
