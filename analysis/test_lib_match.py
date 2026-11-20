"""lib_match checks. Run: python3 -B -m unittest discover -s analysis -v

Unit tests are self-contained. The corpus test needs firmware/ and TI CGT 8.5.0.LTS at ~/ti, and skips
without them.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_match
import mmtd2elf
import sonicware_integrity as integrity


class UnitTests(unittest.TestCase):
    def test_anchor_is_longest_unmasked_run(self):
        self.assertEqual(lib_match.anchor(bytes(20), b"\xff" * 4 + b"\0" * 4 + b"\xff" * 12), (8, 12))
        self.assertIsNone(lib_match.anchor(bytes(8), b"\xff" * 4 + b"\0" + b"\xff" * 3))

    def test_find_matches_respects_mask_and_alignment(self):
        code = bytes(range(1, 33))
        mask = bytearray(b"\xff" * 32)
        mask[4:8] = b"\0\0\0\0"  # a relocated word
        patched = bytearray(code)
        patched[4:8] = b"\xaa\xbb\xcc\xdd"
        text = bytes(32) + bytes(patched) + bytes(3) + bytes(code)  # aligned copy at 32, misaligned at 67
        hits = lib_match.find_matches(text, 0x1000, code, bytes(mask), 32, 0)
        self.assertEqual(hits, [0x1020])


LIB = Path.home() / "ti/ti-cgt-c6000_8.5.0.LTS/lib/rts6740_elf.lib"
ZIP = ROOT / "firmware/smpltrek/SmplTrek v3.2.174.zip"


@unittest.skipUnless(LIB.exists() and ZIP.exists(), "needs firmware/ and TI CGT 8.5.0.LTS")
class CorpusTests(unittest.TestCase):
    def test_known_rts_functions_in_3_2_174(self):
        (_, data), = list(integrity.inputs([ZIP]))
        _, entry, sections = mmtd2elf.mmtd_sections(data)
        found = {}
        for r in lib_match.match(sections, entry, [LIB], 32):
            if len(r["matches"]) == 1:
                found[r["name"]] = r["matches"][0]
        # Hand-written assembly is stable across compiler versions and matches exactly.
        self.assertEqual(found["memcpy"], 0xC1694800)
        self.assertEqual(found["__c6xabi_pop_rts"], 0xC16AC740)
        self.assertEqual(found["__c6xabi_push_rts"], 0xC16AC760)
        self.assertIn("__c6xabi_divu", found)


if __name__ == "__main__":
    unittest.main()
