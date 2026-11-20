"""Tests for check_relocated_lofi.py. Candidates are made in memory only and never written to disk.

Needs the official firmware/lofi12/Lofi-12XT_v1.5.205.zip; skipped without it.
"""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_relocated_lofi as checker

SOURCE = Path(__file__).resolve().parents[2] / "firmware" / "lofi12" / "Lofi-12XT_v1.5.205.zip"


@unittest.skipUnless(SOURCE.exists(), "official Lofi-12 XT 1.5.205 update not present")
class CheckRelocatedLofi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = checker.patch_builder.read_source(SOURCE)

    def candidate(self, words=None, family=5, extra=None, reseal=True):
        data = bytearray(self.source)
        for _, offset, _, new, _, _ in (checker.WORDS if words is None else words):
            struct.pack_into("<I", data, offset, new)
        struct.pack_into("<I", data, checker.FAMILY_OFFSET, family)
        if extra is not None:
            data[extra] ^= 0x01
        return checker.integrity.reseal(bytes(data), "smpltrek", allow_family_mismatch=True) if reseal else bytes(data)

    def test_specified_candidate_passes(self):
        lines = checker.check(self.source, self.candidate())
        # 8 instruction bytes + family byte + two 4-byte CRCs
        self.assertTrue(lines[-1].startswith("17 bytes differ"), lines[-1])

    def test_rejects_missing_word(self):
        with self.assertRaisesRegex(ValueError, "expected 02119788"):
            checker.check(self.source, self.candidate(words=checker.WORDS[1:]))

    def test_rejects_extra_change(self):
        with self.assertRaisesRegex(ValueError, "outside the specification"):
            checker.check(self.source, self.candidate(extra=0x11FAC4))

    def test_rejects_wrong_family(self):
        with self.assertRaisesRegex(ValueError, "CRC invalid|family"):
            checker.check(self.source, self.candidate(family=12))

    def test_rejects_unsealed(self):
        with self.assertRaisesRegex(ValueError, "CRC invalid"):
            checker.check(self.source, self.candidate(reseal=False))

    def test_rejects_unofficial_source(self):
        with self.assertRaisesRegex(ValueError, "official"):
            checker.check(self.candidate(), self.candidate())

    def test_offsets_match_section_table(self):
        image = [i[0] for i in checker.integrity.verify(self.source, "lofi12")][1]
        for address, offset, *_ in checker.WORDS:
            self.assertEqual(checker.file_offset(self.source, image, address), offset)


if __name__ == "__main__":
    unittest.main()
