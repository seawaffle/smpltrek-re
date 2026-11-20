"""AIS parser bounds and corpus identity checks; no target execution."""
import hashlib
from pathlib import Path
import struct
import unittest

import ais_extract as ais


def words(*values):
    return struct.pack("<" + "I" * len(values), *values)


def fixture():
    return (words(ais.MAGIC, ais.SEQUENTIAL, ais.FUNCTION, 0x20003, 1, 2,
                  ais.LOAD, 0xC7000000, 3) + b"abc\0" + words(ais.CLOSE, 0xC7000000))


class AisTests(unittest.TestCase):
    def test_load_padding_rom_arguments_and_trailing_flash(self):
        data = fixture() + b"unrelated trailing flash"
        report, sections = ais.parse(data)
        self.assertEqual(sections, [(0xC7000000, b"abc")])
        self.assertEqual(report["ais_length"], len(fixture()))
        self.assertEqual(report["commands"][1]["arguments"], [1, 2])
        self.assertEqual(report["commands"][1]["function"], 3)
        self.assertEqual(report["ais_sha256"], hashlib.sha256(fixture()).hexdigest())

    def test_every_truncation_rejected(self):
        data = fixture()
        for n in range(len(data)):
            with self.subTest(length=n), self.assertRaises(ValueError):
                ais.parse(data[:n])

    def test_unknown_command_and_entry_outside_load(self):
        for data in (words(ais.MAGIC, 0x58535999),
                     words(ais.MAGIC, ais.CLOSE, 0xC7000000),
                     fixture()[:-4] + words(0xC7000003)):
            with self.assertRaises(ValueError):
                ais.parse(data)

    def test_overlap_address_wrap_and_limit(self):
        prefix = words(ais.MAGIC, ais.LOAD, 0xC7000000, 4) + b"1234"
        for data in (prefix + words(ais.LOAD, 0xC7000002, 4) + b"5678",
                     words(ais.MAGIC, ais.LOAD, 0xFFFFFFFE, 4) + b"1234"):
            with self.assertRaises(ValueError):
                ais.parse(data)
        with self.assertRaises(ValueError):
            ais.parse(fixture(), len(fixture()) - 1)


DUMP = Path(__file__).resolve().parents[1] / "work/a4/A4DUMP.BIN"


@unittest.skipUnless(DUMP.exists(), "device flash dump not present")
class CorpusTests(unittest.TestCase):
    def test_captured_bootloader(self):
        report, sections = ais.parse(DUMP.read_bytes(), 0x40000)
        self.assertEqual(report["input_sha256"],
                         "3767d6ad9ee07a43593e9042c12514e634083fced5de555ff4de2fd2e7e4c8d5")
        self.assertEqual(report["ais_length"], 0x36B3C)
        self.assertEqual(report["entry"], 0xC70A1160)
        self.assertEqual(len(sections), 11)
        self.assertEqual(sections[1][0], 0xC7074800)
        self.assertEqual(len(sections[1][1]), 0x323C0)


if __name__ == "__main__":
    unittest.main()
