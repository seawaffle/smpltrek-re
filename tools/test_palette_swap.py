"""Tests for palette_swap.py. Corpus tests skip with a notice when firmware/ is absent.
Run: python3 -B -m unittest discover -s tools -p "test_palette*.py" -v"""
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import palette_swap as ps
import sonicware_integrity as integrity

LOFI_ZIP = ROOT / "firmware/lofi12/Lofi-12XT_v1.5.205.zip"
ST_ZIP = ROOT / "firmware/smpltrek/SmplTrek v3.2.174.zip"
ST_CONTENT_ZIP = ROOT / "firmware/smpltrek/SmplTrek v2.0.129.zip"
CY2_ZIP = ROOT / "firmware/cydrums/CyDrums_v2.0.97beta.zip"
W1_SHA256 = "ed72341d53dc68e97acd747c3dcfae18cf5159ebd91d324ac5ff88cb827488d7"

corpus = unittest.skipUnless(LOFI_ZIP.exists() and ST_ZIP.exists(),
                             "official firmware corpus (firmware/) not present")


def w1_bytes():
    """The W1 probe image (Lofi-12 XT 1.5.205 rewrapped for the SmplTrek), rebuilt and checked by hash."""
    import hashlib
    data = next(integrity.inputs([LOFI_ZIP]))[1]
    new, _ = ps.convert(data, ps.parse_system_update(data), "smpltrek")
    assert hashlib.sha256(new).hexdigest() == W1_SHA256, "W1 reproduction changed"
    return new


class Parsing(unittest.TestCase):
    def test_refuses_non_cmtd(self):
        with self.assertRaises(ps.Refused):
            ps.parse_system_update(b"NOPE" + b"\x00" * 64)

    @corpus
    def test_refuses_bad_section_length_even_with_valid_crcs(self):
        """A section length that runs past the image is refused although both CRCs are resealed."""
        import struct
        data = bytearray(next(integrity.inputs([LOFI_ZIP]))[1])
        info = ps.parse_system_update(bytes(data))
        struct.pack_into("<I", data, info["mmtd_offset"] + 36 + 8, 0xFFFFFFFF)   # first section's length
        seeds = ps.DEVICES["lofi12"]["seeds"]
        off, size = info["mmtd_offset"], info["mmtd_size"]
        struct.pack_into("<I", data, off + 8, ps.image_crc(data, off, size, seeds["mmtd"]))
        struct.pack_into("<I", data, 8, ps.image_crc(data, 0, len(data), seeds["cmtd"]))
        self.assertTrue(ps.matches_profile(bytes(data), off, size, seeds))
        with self.assertRaises(ps.Refused):
            ps.parse_system_update(bytes(data))

    @corpus
    def test_refuses_content_bundled(self):
        data = next(integrity.inputs([ST_CONTENT_ZIP]))[1]
        with self.assertRaises(ps.Refused):
            ps.parse_system_update(data)

    def test_refuses_truncated_mmtd_header(self):
        """A container whose one system image declares only 8 bytes is refused, not a struct.error (no firmware)."""
        import struct
        mmtd = b"mmtd" + struct.pack("<I", 8)
        data = struct.pack("<4s5I", b"cmtd", 48 + len(mmtd), 0, 0, 5, 1) + struct.pack("<6I", 3, 3, 2, 174, 48, 8) + mmtd
        with self.assertRaises(ps.Refused):
            ps.parse_system_update(data)


class Conversion(unittest.TestCase):
    @corpus
    def test_golden_w1_reproduction(self):
        """Lofi -> smpltrek must reproduce the device-probed W1 bytes exactly."""
        data = next(integrity.inputs([LOFI_ZIP]))[1]
        info = ps.parse_system_update(data)
        self.assertEqual(ps.identify(data, info), "lofi12")
        new, changed = ps.convert(data, info, "smpltrek")
        import hashlib
        self.assertEqual(hashlib.sha256(new).hexdigest(), W1_SHA256)
        self.assertEqual(changed, sorted(list(range(8, 12)) + [16] + list(range(info["mmtd_offset"] + 8,
                                                                               info["mmtd_offset"] + 12))))

    @unittest.skipUnless(CY2_ZIP.exists(), "CyDrums 2.0.97 beta not present")
    def test_cydrums_2_0_beta_converts_both_ways(self):
        """2.0.97 beta verifies with the seeds fitted to 1.1.84 and converts to SmplTrek and Lofi-12 XT."""
        data = next(integrity.inputs([CY2_ZIP]))[1]
        info = ps.parse_system_update(data)
        self.assertEqual(info["version"], (2, 0, 97))
        self.assertEqual(ps.identify(data, info), "cydrums")
        self.assertTrue(all(a == b for _, a, b in integrity.verify(data, "cydrums")))
        for target in ("smpltrek", "lofi12"):
            new, changed = ps.convert(data, info, target)
            self.assertEqual(len(changed), 9)
            self.assertTrue(all(a == b for _, a, b in integrity.verify(new, target)))

    @corpus
    def test_smpltrek_to_lofi_verifies_with_official_tool(self):
        data = next(integrity.inputs([ST_ZIP]))[1]
        info = ps.parse_system_update(data)
        self.assertEqual(ps.identify(data, info), "smpltrek")
        new, _ = ps.convert(data, info, "lofi12")
        checks = integrity.verify(new, "lofi12")
        self.assertTrue(all(a == b for _, a, b in checks))

    @corpus
    def test_smpltrek_to_cydrums_self_consistent(self):
        data = next(integrity.inputs([ST_ZIP]))[1]
        info = ps.parse_system_update(data)
        new, changed = ps.convert(data, info, "cydrums")
        self.assertEqual(len(changed), 9)
        self.assertTrue(ps.matches_profile(new, info["mmtd_offset"], info["mmtd_size"],
                                           ps.DEVICES["cydrums"]["seeds"]))

    @corpus
    def test_refuses_already_converted(self):
        data = w1_bytes()
        info = ps.parse_system_update(data)
        self.assertEqual(ps.identify(data, info), "smpltrek")  # sealed with smpltrek seeds
        self.assertEqual(ps.sniff_payload(info), "lofi12")     # but payload is Lofi code

    @corpus
    def test_cli_refuses_already_converted(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            w1 = Path(tmp) / "w1.bin"
            w1.write_bytes(w1_bytes())
            result = subprocess.run(
                [sys.executable, "-B", str(ROOT / "tools/palette_swap.py"),
                 str(w1), "--to", "lofi12", "--yes"],
                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("ALREADY a converted file", result.stderr)

    @corpus
    def test_cli_golden_and_exit_codes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "SmplTrek.bin"
            result = subprocess.run(
                [sys.executable, "-B", str(ROOT / "tools/palette_swap.py"),
                 str(LOFI_ZIP), "--to", "smpltrek", "--yes", "-o", str(out)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(out.read_bytes(), w1_bytes())
            # a second run must refuse to overwrite
            again = subprocess.run(
                [sys.executable, "-B", str(ROOT / "tools/palette_swap.py"),
                 str(LOFI_ZIP), "--to", "smpltrek", "--yes", "-o", str(out)],
                capture_output=True, text=True)
            self.assertEqual(again.returncode, 1)
            self.assertIn("already exists", again.stderr)


if __name__ == "__main__":
    unittest.main()
