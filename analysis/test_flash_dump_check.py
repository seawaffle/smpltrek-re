import io
from pathlib import Path
import struct
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flash_dump_check as check


def payload():
    return bytes((i * i + 3 * i) >> 2 & 0xFF for i in range(0x400))


def synthetic():
    data = bytearray(b"\xff" * 0x50000)
    data[0:0x2000] = bytes(i & 0xFF for i in range(0x2000))          # "bootloader"
    data[0x2000:0x4000] = b"\x00" * 0x2000
    data[0x3FFE4:0x3FFE4 + 28] = b"bmtd" + struct.pack("<II", 0x80, 0) + b"\xfe\xff\xff\xff" + struct.pack("<3I", 1, 0, 17)
    data[0x40000:0x40000 + 28] = b"mmtd" + struct.pack("<II", 0x80, 0) + b"\xfe\xff\xff\xff" + struct.pack("<3I", 3, 2, 174)
    data[0x40080:0x40080 + 0x400] = payload()  # "section 0"
    data[0x4F000:0x4F004] = b"PREF"
    return bytes(data)


class RunsAndHeaders(unittest.TestCase):
    def test_runs_group_erased_and_zero_sectors(self):
        runs = check.runs(synthetic())
        self.assertEqual(runs[0], ("zero", 0x2000, 0x4000))
        self.assertEqual(runs[1], ("erased", 0x4000, 0x3F000))
        self.assertEqual(runs[-1], ("erased", 0x41000, 0x4F000))

    def test_headers_and_tags(self):
        report = check.summarise(synthetic())
        self.assertFalse(report["complete"])
        self.assertTrue(report["headers"]["bmtd_ok"])
        self.assertTrue(report["headers"]["mmtd_ok"])
        self.assertFalse(report["headers"]["pmtd_ok"])
        self.assertIsNone(report["headers"]["pmtd"])
        self.assertEqual(report["headers"]["mmtd"]["version"], [3, 2, 174])
        self.assertEqual(report["headers"]["mmtd"]["size"], 0x80)
        self.assertEqual(report["tags"]["PREF"], ["0x4f000"])
        self.assertEqual(report["tags"]["PREX"], [])

    def test_locate_reports_exact_and_partial_hits(self):
        data = synthetic()
        exact = check.locate(data, "s0", payload())
        self.assertEqual(exact["hits"], [{"offset": "0x40080", "matching_bytes": 0x400,
                                         "length": 0x400, "exact": True}])
        partial = check.locate(data, "s0", payload()[:0x200] + b"\x00" * 0x200)
        self.assertTrue(0x200 <= partial["hits"][0]["matching_bytes"] < 0x400)
        self.assertFalse(partial["hits"][0]["exact"])
        self.assertEqual(check.locate(data, "none", b"\x01\x02\x03" * 40)["hits"], [])

    def test_cli_text_output(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "A4FLASH.BIN"
            path.write_bytes(synthetic())
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                self.assertEqual(check.main([str(path)]), 0)
            text = out.getvalue()
            self.assertIn("not a complete 32 MiB image", text)
            self.assertIn("mmtd @0x40000: OK", text)
            self.assertIn("pmtd @0x440000: beyond the dump", text)
            err = io.StringIO()
            with mock.patch("sys.stderr", err):
                self.assertEqual(check.main([str(path / "missing")]), 2)
            self.assertIn("error:", err.getvalue())


class InstalledComparison(unittest.TestCase):
    def fixture(self):
        section = b"sample code bytes"
        mmtd = (b"mmtd" + struct.pack("<8I", 48 + len(section), 0, 0xFFFFFFFF,
                                     3, 2, 174, 0xC0000000, 1)
                + b"sect" + struct.pack("<II", 0xC0000000, len(section)) + section)
        reference = (b"cmtd" + struct.pack("<5I", 48 + len(mmtd), 0, 0, 5, 1)
                     + struct.pack("<6I", 3, 3, 2, 174, 48, len(mmtd)) + mmtd)
        reference = check.integrity.reseal(reference, "smpltrek")
        flash = bytearray(b"\xff" * 0x40000 + reference[48:])
        flash[0x4000C] = 0xFE
        return flash, reference

    def test_only_install_marker_differs_without_mutating_input(self):
        flash, reference = self.fixture()
        before = bytes(flash)
        r = check.compare_installed_system(flash, reference)
        self.assertTrue(r["marker_only_difference"])
        self.assertFalse(r["raw_exact"])
        self.assertTrue(r["reference_crc_valid"])
        self.assertEqual(r["stored_crc"], r["marker_normalized_crc"])
        self.assertNotEqual(r["stored_crc"], r["raw_crc"])
        self.assertTrue(r["size_matches"])
        self.assertEqual(flash, before)

    def test_size_mismatch_is_reported(self):
        flash, reference = self.fixture()
        struct.pack_into("<I", flash, 0x40004, struct.unpack_from("<I", flash, 0x40004)[0] + 4)
        r = check.compare_installed_system(flash, reference)
        self.assertFalse(r["size_matches"])
        self.assertFalse(r["marker_only_difference"])

    def test_payload_change_is_not_hidden_by_marker_normalization(self):
        flash, reference = self.fixture()
        flash[-1] ^= 1
        r = check.compare_installed_system(flash, reference)
        self.assertFalse(r["marker_only_difference"])
        self.assertEqual(r["other_differing_bytes"], 1)

    def test_truncation_and_unknown_marker_are_not_accepted(self):
        flash, reference = self.fixture()
        self.assertIn("error", check.compare_installed_system(flash[:-1], reference))
        flash[0x4000C] = 0xFC
        r = check.compare_installed_system(flash, reference)
        self.assertFalse(r["marker_only_difference"])
        self.assertEqual(r["other_differing_bytes"], 1)


if __name__ == "__main__":
    unittest.main()
