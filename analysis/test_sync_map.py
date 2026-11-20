"""Pins "SYNC IN / SYNC OUT" in docs/04-hardware-access.md against the simulated code of SmplTrek 3.2.174. Run:
python3 -B -m unittest discover -s analysis -p "test_sync_map.py" -v

Needs firmware/ and work/smpltrek-3.2.174.dis; skipped without them.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hw_compare   # noqa: E402
import sync_map     # noqa: E402

NEEDED = [ROOT / hw_compare.PRODUCTS["smpltrek"][k] for k in ("image", "listing")]
IN, OUT = 1 << 24, 1 << 25      # GP7[8], GP7[9] in the bank 6/7 registers


@unittest.skipUnless(all(p.exists() for p in NEEDED), "official update or work listing not present")
class Simulated(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = sync_map.Session()

    def test_setup_and_polarity_in(self):
        handles, writes, pol0, pol1 = self.s.setup()
        self.assertEqual(handles, (121, 122))
        self.assertEqual(writes, [("PINMUX17", 0x88), ("DIR67", 0xFFFFFFFF & ~OUT), ("CLR_DATA67", OUT),
                                  ("SET_RIS_TRIG67", IN), ("CLR_FAL_TRIG67", IN)])
        self.assertEqual(pol0, [("SET_FAL_TRIG67", IN), ("CLR_RIS_TRIG67", IN)])
        self.assertEqual(pol1, [("SET_RIS_TRIG67", IN), ("CLR_FAL_TRIG67", IN)])

    def test_pulse(self):
        for pol, (start, end) in ((0, ("SET_DATA67", "CLR_DATA67")), (1, ("CLR_DATA67", "SET_DATA67"))):
            seq, again = self.s.pulse(pol)
            self.assertEqual(seq, [(0, [(start, OUT)]), (15, [(end, OUT)])], pol)
            self.assertEqual(again, [(start, OUT)], pol)
        self.assertEqual(self.s.early_retrigger(), [])

    def test_sync_in_edge(self):
        isr, flag, calls, after = self.s.sync_in_edge()
        self.assertEqual((isr, flag, after), ([("INTSTAT67", IN)], 1, 0))
        self.assertEqual(calls, [(sync_map.FAKE_DELEGATE, sync_map.OBJ)])

    def test_positions(self):
        self.assertEqual(self.s.positions(0), {0: ["pulse"], 36: ["pulse"]})
        on = self.s.positions(1)
        self.assertEqual(sorted(on), list(range(0, 80, 3)))
        self.assertEqual([p for p, e in on.items() if "pulse" in e], [0, 36])

    def test_internal_clock(self):
        inc, sps, ev = self.s.clock(1200, 375)          # 120.0 BPM for one second of 128-frame blocks
        self.assertEqual((inc, sps), (86400, 333))     # 72 x 1200; 28,800,000 / 86,400
        steps = [p for _, slot, p in ev if slot == 1]
        self.assertEqual(steps, list(range(72)) * 2)   # 144 steps = 2 quarter notes, wrapping at 72
        self.assertEqual([slot for _, slot, _ in ev], [0, 1] * 144)

    def test_sync_in_tempo(self):
        # 2 PPQN: a beat every second edge; the first beat is measured from time 0
        self.assertEqual(self.s.sync_in_tempo([300] * 8), [2000, 2000, 1000, 1000, 1000, 1000, 1000, 1000])
        # a jump above 5 BPM refills the four-beat ring: 100 -> 120 BPM within two beats
        self.assertEqual(self.s.sync_in_tempo([300] * 6 + [250] * 6)[-4:], [1200] * 4)
        # beats 2 s or more apart are ignored (the tempo stays at the 120.0 the object starts with)
        self.assertEqual(self.s.sync_in_tempo([2500] * 4), [1200] * 4)

    def test_sync_in_steps(self):
        steps = self.s.sync_in_steps([250] * 6 + [200], 720)
        pos = [p for _, p in steps]
        self.assertEqual(steps[0], (501, 0))                     # nothing before the first beat (second edge)
        self.assertEqual(pos[:144], list(range(72)) * 2)         # 72 steps per beat, none lost
        early = [p for ms, p in steps if ms == 1701]             # edge at 1700 ms came before 36 steps: catch-up
        self.assertEqual(early, list(range(29, 37)))
        late = self.s.sync_in_steps([250] * 4 + [300], 520)      # edge late: waits after 36 steps
        self.assertEqual([p for ms, p in late if 1240 <= ms < 1300], [35])
        self.assertEqual(next(x for x in late if x[0] > 1240), (1301, 36))


if __name__ == "__main__":
    unittest.main()
