"""Pins the USB configuration descriptor in docs/04-hardware-access.md ("USB device") against the simulated USB
start of SmplTrek 3.2.174. Run:
python3 -B -m unittest discover -s analysis -p "test_usb_desc_map.py" -v

Needs firmware/ and the work listing; skipped without them.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hw_compare     # noqa: E402
import usb_desc_map   # noqa: E402

P = hw_compare.PRODUCTS["smpltrek"]


@unittest.skipUnless((ROOT / P["image"]).exists() and (ROOT / P["listing"]).exists(), "official update not present")
class Simulated(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = usb_desc_map.build()
        cls.d = usb_desc_map.decode(cls.b)

    def kinds(self, kind):
        return [f for _, k, f in self.d if k == kind]

    def test_length(self):
        self.assertEqual(len(self.b), 234)
        self.assertEqual(self.kinds("CONFIG")[0]["total"], 234)

    def test_audio_format(self):
        for f in self.kinds("AS_FORMAT_TYPE"):         # both directions
            self.assertEqual((f["type"], f["channels"], f["subframe"], f["bits"], f["rates"]), (1, 2, 2, 16, [48000]))

    def test_terminals(self):
        self.assertEqual([(t["id"], t["type"]) for t in self.kinds("AC_INPUT_TERMINAL")], [(3, 0x0101), (5, 0x0201)])
        self.assertEqual([(t["id"], t["type"], t["source"]) for t in self.kinds("AC_OUTPUT_TERMINAL")],
                         [(4, 0x0302, 3), (6, 0x0101, 5)])
        self.assertFalse([k for _, k, _ in self.d if k.startswith("AC_") and k[3:].isdigit()])   # no feature unit

    def test_endpoints(self):
        self.assertEqual([(e["address"], e["attributes"], e["max_packet"]) for e in self.kinds("ENDPOINT")],
                         [(0x01, 0x09, 196), (0x82, 0x05, 196), (0x03, 0x02, 64), (0x83, 0x02, 64)])

    def test_midi(self):
        self.assertEqual(self.kinds("MS_IN_JACK"), [{"embedded": True, "id": 1}])
        self.assertEqual(self.kinds("MS_OUT_JACK"), [{"embedded": True, "id": 2, "sources": [(1, 1)]}])


if __name__ == "__main__":
    unittest.main()
