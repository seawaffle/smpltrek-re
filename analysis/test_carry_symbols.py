"""carry_symbols checks. Run: python3 -B -m unittest discover -s analysis -v

The carried files themselves are checked against their images by test_symbols.py.
"""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import carry_symbols


class CarryTests(unittest.TestCase):
    def test_file_stems(self):
        self.assertEqual(carry_symbols.file_stem("firmware/smpltrek/SmplTrek v3.0.148.zip:x/SmplTrek.bin", "3.0.148"),
                         "smpltrek-3.0.148")
        self.assertEqual(carry_symbols.file_stem("firmware/lofi12/Lofi-12XT_v1.5.205.zip:y.bin", "1.5.205"),
                         "lofi-12xt-1.5.205")
        self.assertEqual(carry_symbols.file_stem("firmware/cydrums/CyDrums_v1.1.84.zip:z.bin", "1.1.84"),
                         "cydrums-1.1.84")

    def test_hand_file_merge(self):
        import tempfile
        carried = [{"name": "f", "address": "0xc2000010", "evidence": ["carried"]},
                   {"name": "g", "address": "0xc2000020", "evidence": ["carried"]}]
        hand = {"source": {"sha256": "ab"}, "symbols": [
            {"name": "g2", "address": "0xc2000020", "evidence": ["read"]},   # replaces g (same address)
            {"name": "h", "address": "0xc2000000", "evidence": ["read"]}]}   # added
        with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
            json.dump(hand, f)
            f.flush()
            merged = carry_symbols.merge_hand(carried, Path(f.name), "ab")
            self.assertEqual([e["name"] for e in merged], ["h", "f", "g2"])
            self.assertIn("Hand-written", merged[0]["evidence"][-1])
            self.assertEqual(carry_symbols.merge_hand(carried, Path(f.name + ".missing"), "ab"), carried)
            hand["rejected"] = [{"name": "f", "reason": "checked, wrong"}]   # dropped
            f.seek(0)
            f.truncate()
            json.dump(hand, f)
            f.flush()
            merged = carry_symbols.merge_hand(carried, Path(f.name), "ab")
            self.assertEqual([e["name"] for e in merged], ["h", "g2"])

    def test_confidence_never_rises(self):
        self.assertEqual(carry_symbols.cap("confirmed", "probable"), "probable")
        self.assertEqual(carry_symbols.cap("probable", "confirmed"), "probable")
        self.assertEqual(carry_symbols.cap("speculative", "confirmed"), "speculative")

    def test_generated_files_never_exceed_source_confidence(self):
        source = json.loads((ROOT / "symbols/smpltrek-3.2.174.json").read_text())
        rank = carry_symbols.RANK
        by_name = {s["name"]: rank[s["confidence"]] for s in source["symbols"]}
        for path in (ROOT / "symbols").glob("*.json"):
            document = json.loads(path.read_text())
            if "carry_symbols.py" not in document["notes"][0]:
                continue
            for entry in document["symbols"]:
                with self.subTest(file=path.name, name=entry["name"]):
                    if entry["name"] not in by_name:
                        # Product-only names exist only through the hand-written file; nothing to cap them.
                        self.assertTrue(any(e.startswith("Hand-written in") for e in entry["evidence"]))
                        continue
                    self.assertLessEqual(rank[entry["confidence"]], by_name[entry["name"]])


if __name__ == "__main__":
    unittest.main()
