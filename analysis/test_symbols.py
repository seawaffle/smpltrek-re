"""Checks symbols/*.json against the official images. Run: python3 -B -m unittest discover -s analysis -v

Every function entry records a hash of the first 16 bytes at its address ("prefix_sha256", see symfile.py); this test
confirms them, so a
symbol file cannot silently drift from the image it describes. Needs the official updates in firmware/
(not tracked); skips when they are absent.
"""
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mmtd2elf
import symfile
import sonicware_integrity as integrity

SYMBOLS = sorted((ROOT / "symbols").glob("*.json")) + sorted((ROOT / "symbols/hand").glob("*.json"))
CONFIDENCE = {"confirmed", "probable", "speculative"}
KINDS = {"function", "data"}


def image_for(sha256):
    for path in sorted((ROOT / "firmware").rglob("*.zip")):
        try:
            for _, data in integrity.inputs([path]):
                if hashlib.sha256(data).hexdigest() == sha256:
                    return data
        except Exception:
            continue
    return None


class SymbolFileTests(unittest.TestCase):
    def test_entries_are_well_formed(self):
        for path in SYMBOLS:
            document = json.loads(path.read_text())
            names = set()
            for entry in document["symbols"]:
                with self.subTest(file=path.name, name=entry.get("name")):
                    self.assertRegex(entry["address"], r"^0x[0-9a-f]{8}$")
                    self.assertIn(entry["kind"], KINDS)
                    self.assertIn(entry["confidence"], CONFIDENCE)
                    self.assertTrue(entry["evidence"])
                    self.assertNotIn(entry["name"], names)
                    names.add(entry["name"])
                    if entry["kind"] == "function":
                        self.assertRegex(entry["prefix_sha256"], r"^[0-9a-f]{32}$")
                        self.assertNotIn("prefix", entry)   # code bytes are never stored, only their hash

    def test_function_prefixes_match_the_image(self):
        """Each symbol file is checked against its own image; a missing image skips that file only."""
        checked = 0
        for path in SYMBOLS:
            document = json.loads(path.read_text())
            with self.subTest(file=path.name):
                data = image_for(document["source"]["sha256"])
                if data is None:
                    self.skipTest(f"image for {path.name} not present in firmware/")
                version, _, sections = mmtd2elf.mmtd_sections(data)
                self.assertEqual(".".join(map(str, version)), document["source"]["mmtd_version"])
                for entry in document["symbols"]:
                    if entry["kind"] != "function":
                        continue
                    address = int(entry["address"], 16)
                    with self.subTest(name=entry["name"]):
                        found = [symfile.prefix_hash(d[address - a:address - a + symfile.PREFIX_LEN])
                                 for a, d in sections if a <= address < a + len(d)]
                        self.assertEqual(found, [entry["prefix_sha256"]])
                checked += 1
        if not checked:
            self.skipTest("no symbol file's image is present in firmware/")

if __name__ == "__main__":
    unittest.main()
