"""Pins "Channel order" in docs/04-hardware-access.md: which McASP DMA word each audio plane uses, simulated in
SmplTrek 3.2.174, Lofi-12 XT 1.5.205 and CyDrums 1.1.84 (transmit) and SmplTrek (receive). Run:
python3 -B -m unittest discover -s analysis -p "test_audio_slot_map.py" -v

Needs firmware/ and the work listings and match files (as test_hw_compare.py); skipped without them.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hw_compare       # noqa: E402
import audio_slot_map   # noqa: E402

NEEDED = [ROOT / p[k] for p in hw_compare.PRODUCTS.values() for k in ("image", "listing")] + \
         [ROOT / p["match"] for p in hw_compare.PRODUCTS.values() if p["match"]]
S0, S1 = 0.125, 0.5     # what slot 0 and slot 1 of the test RX buffer read as


@unittest.skipUnless(all(p.exists() for p in NEEDED), "official updates or work listings not present")
class Simulated(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = audio_slot_map.Session("smpltrek")

    def test_tx_plane0_even_words(self):
        frames = {"smpltrek": 128, "lofi12": 96, "cydrums": 96}
        for key in hw_compare.PRODUCTS:
            s = self.s if key == "smpltrek" else audio_slot_map.Session(key)
            self.assertEqual(s.tx(), (frames[key], [0x20000000, 0xC0000000] * 2), key)

    def test_rx_selectors(self):
        pick = {0: 0.0, 1: S0, 2: S1}
        for (l, r, stereo), planes in self.s.rx_table().items():
            self.assertEqual(planes, (S0, S1) if stereo else (pick[l], pick[r]), (l, r, stereo))

    def test_rx_defaults(self):
        self.assertEqual(self.s.rx(1, 2, 0), (S0, S1))   # PREF defaults +0x1C = 1, +0x20 = 2 (+0x24 = 1 gives the same)


if __name__ == "__main__":
    unittest.main()
