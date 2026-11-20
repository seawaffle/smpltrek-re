"""Pins hw_inventory.py: the legacy ELZ_1 container, the per-part peripheral tags and the part verdicts for one
ELZ_1 and one Liven release (INT-16, INT-17). Run:
python3 -B -m unittest discover -s analysis -p "test_hw_inventory.py" -v

The corpus tests need firmware/ and are skipped without it; the synthetic tests always run.
"""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "tools"))
import hw_inventory                       # noqa: E402
import sonicware_integrity as integrity   # noqa: E402

ELZ1 = ROOT / "firmware/other/ELZ_1 v2.0.zip"
LIVEN_LOFI = ROOT / "firmware/other/LIVEN_LOFI_SYSTEM_2_1_65.syx"


def legacy_container(entry, sections):
    """A legacy ELZ_1 container (INT-15 layout) holding one pmtd stub and one mmtd image; CRCs left zero."""
    body = b"".join(b"sect" + struct.pack("<II", a, len(d)) + d for a, d in sections)
    mmtd = b"mmtd" + struct.pack("<8I", 2, 0, 0x5D, 36 + len(body), 0, entry, len(sections), 0xFFFFFFFF) + body
    pmtd = b"pmtd" + bytes(28)
    head = 0x14 + 24 * 2
    descriptors = struct.pack("<6I", 2, 2, 0, 0x1E, head, len(pmtd)) + \
        struct.pack("<6I", 3, 2, 0, 0x5D, head + len(pmtd), len(mmtd))
    return b"cmtd" + struct.pack("<4I", 1, 0, 0, 2) + descriptors + pmtd + mmtd


class Synthetic(unittest.TestCase):
    def test_legacy_sections(self):
        sections = [(0xC0F49320, b"\x01\x02\x03\x04"), (0xC0D02000, bytes(range(16)))]
        data = legacy_container(0xC0DF88E0, sections)
        self.assertTrue(hw_inventory.is_legacy(data))
        entry, got, legacy = hw_inventory.image_sections(data)
        self.assertEqual((entry, got, legacy), (0xC0DF88E0, sections, True))

    def test_legacy_rejects_trailing_bytes(self):
        data = bytearray(legacy_container(0xC0000000, [(0xC0000000, b"abcd")]))
        size_field = 0x14 + 24 + 20   # the mmtd descriptor (the second), word 5
        struct.pack_into("<I", data, size_field, struct.unpack_from("<I", data, size_field)[0] + 4)
        data += b"xxxx"
        with self.assertRaises(ValueError):
            hw_inventory.legacy_mmtd_sections(bytes(data))

    def test_current_layout_is_not_legacy(self):
        data = b"cmtd" + struct.pack("<I", 0x40) + bytes(0x38)
        self.assertFalse(hw_inventory.is_legacy(data))

    def test_part_tags_name_real_peripherals(self):
        names = {name for _, _, name in hw_inventory.PERIPHERALS}
        self.assertLessEqual(set(hw_inventory.ONLY_ON), names)

    def test_possible_parts(self):
        pp = hw_inventory.possible_parts
        self.assertEqual(pp({"SPI1", "UART0", "I2C0", "McASP0 control", "unknown"}), ["C6742", "C6746", "C6748"])
        self.assertEqual(pp({"SPI1", "USB0 (OTG)", "MMCSD0"}), ["C6746", "C6748"])
        self.assertEqual(pp({"USB0 (OTG)", "LCDC"}), ["C6748"])
        self.assertEqual(pp({"McBSP1 data"}), ["C6742", "C6746", "C6748"])
        self.assertEqual(pp({"McBSP0 data"}), ["C6746", "C6748"])

    def test_unknown_pages_kept_apart(self):
        hits = {(0x01B77000, "unknown"): [(0x01B77400, 0xC0000010, None, None)],
                (0x01E84000, "unknown"): [(0x01E84800, 0xC0000020, None, None)],
                (0x01F0E000, "SPI1"): [(0x01F0E000, 0xC0000030, 0xC0000000, "f")]}
        out = hw_inventory.summarise(hits)
        self.assertEqual(sorted(out), ["SPI1", "unknown 0x01b77000", "unknown 0x01e84000"])


# The corpus tests decode code with tools/tic6x objdump (tools/toolchain/build_tic6x_binutils.sh).
OBJDUMP_OK = (Path(__file__).resolve().parents[1] / "tools/tic6x/bin/tic6x-elf-objdump").exists()


@unittest.skipUnless(ELZ1.exists() and LIVEN_LOFI.exists() and OBJDUMP_OK, "official updates not present (or tools/tic6x objdump missing)")
class Corpus(unittest.TestCase):
    def found(self, path):
        (_, data), = list(integrity.inputs([path]))
        entry, sections, legacy = hw_inventory.image_sections(data)
        return {name for _, name in hw_inventory.analyse(sections, entry, {})}, legacy

    def test_elz1_needs_c6748(self):
        names, legacy = self.found(ELZ1)
        self.assertTrue(legacy)
        self.assertIn("LCDC", names)
        self.assertIn("USB0 (OTG)", names)
        self.assertEqual(hw_inventory.possible_parts(names), ["C6748"])

    def test_liven_fits_every_part(self):
        names, legacy = self.found(LIVEN_LOFI)
        self.assertFalse(legacy)
        self.assertLessEqual({"SPI1", "UART0", "I2C0", "McASP0 control"}, names)
        self.assertEqual(hw_inventory.possible_parts(names), ["C6742", "C6746", "C6748"])


if __name__ == "__main__":
    unittest.main()
