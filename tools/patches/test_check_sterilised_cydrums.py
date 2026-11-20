"""Tests for check_sterilised_cydrums.py. Candidates are made in memory only and never written to disk.

Needs the official firmware/cydrums/CyDrums_v1.1.84.zip; skipped without it.
"""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_sterilised_cydrums as checker

SOURCE = Path(__file__).resolve().parents[2] / "firmware" / "cydrums" / "CyDrums_v1.1.84.zip"
OFF = checker.ENTRY_OFFSET


@unittest.skipUnless(SOURCE.exists(), "official CyDrums 1.1.84 update not present")
class CheckSterilisedCyDrums(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = checker.patch_builder.read_source(SOURCE)

    def candidate(self, entry=checker.NEW_ENTRY, family=5, extra=None, reseal=True):
        data = bytearray(self.source)
        data[OFF:OFF + 4] = entry
        struct.pack_into("<I", data, checker.FAMILY_OFFSET, family)
        if extra is not None:
            data[extra] ^= 0x01
        return checker.integrity.reseal(bytes(data), "smpltrek", allow_family_mismatch=True) if reseal else bytes(data)

    def test_specified_candidate_passes(self):
        lines = checker.check(self.source, self.candidate())
        changed = [int(x, 16) for x in lines[-1].split(": ")[1].split(", ")]
        # all 4 entry bytes and the family byte change; the rest are CRC bytes
        self.assertTrue({OFF, OFF + 1, OFF + 2, OFF + 3, checker.FAMILY_OFFSET} <= set(changed))
        self.assertTrue(all(i in range(OFF, OFF + 4) or i == checker.FAMILY_OFFSET
                            or i in range(8, 12) or i in range(0x38, 0x3C) for i in changed), changed)

    def test_rejects_unpatched_entry(self):
        with self.assertRaisesRegex(ValueError, "entry bytes"):
            checker.check(self.source, self.candidate(entry=checker.OLD_ENTRY))

    def test_rejects_stub_without_delay_nops(self):
        # bnop .S2 b3,0: the original body would run in the branch's five delay slots
        with self.assertRaisesRegex(ValueError, "entry bytes"):
            checker.check(self.source, self.candidate(entry=bytes.fromhex("2606ef01")))

    def test_rejects_header_change(self):
        with self.assertRaisesRegex(ValueError, "header changed"):
            checker.check(self.source, self.candidate(extra=OFF + 4))

    def test_rejects_extra_change(self):
        with self.assertRaisesRegex(ValueError, "outside the specification"):
            checker.check(self.source, self.candidate(extra=OFF - 2))

    def test_rejects_wrong_family(self):
        with self.assertRaisesRegex(ValueError, "CRC invalid|family"):
            checker.check(self.source, self.candidate(family=8))

    def test_rejects_unsealed(self):
        with self.assertRaisesRegex(ValueError, "CRC invalid"):
            checker.check(self.source, self.candidate(reseal=False))

    def test_rejects_unofficial_source(self):
        with self.assertRaisesRegex(ValueError, "official"):
            checker.check(self.candidate(), self.candidate())

    def test_entry_offset_from_section_table(self):
        mmtd, offset = checker.source_layout(self.source)
        self.assertEqual(checker.entry_offset(self.source, mmtd), OFF)
        self.assertEqual(offset, OFF)

    @unittest.skipUnless((checker.BINUTILS / "tic6x-elf-objdump").exists(), "tic6x binutils not built")
    def test_decode(self):
        lines = checker.decode(self.source, self.candidate(), OFF)
        self.assertEqual(lines[:2], ["0xc24c4458: mvk .L1 0,a4", "0xc24c445a: bnop .S2 b3,5"])

    @unittest.skipUnless((checker.BINUTILS / "tic6x-elf-objdump").exists(), "tic6x binutils not built")
    def test_decode_rejects_stub_without_delay_nops(self):
        data = bytearray(self.candidate())
        data[OFF:OFF + 4] = bytes.fromhex("2606ef01")
        with self.assertRaisesRegex(ValueError, "decodes as"):
            checker.decode(self.source, bytes(data), OFF)


if __name__ == "__main__":
    unittest.main()
