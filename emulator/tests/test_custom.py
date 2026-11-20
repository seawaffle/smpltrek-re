"""custom.py runs a user-supplied DSP ELF on the board model. The guest is a tiny assembly fixture."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from build import WORK
from core_demo import BIN
from custom import Custom, elf_symbols, main
from media import build_card

SOURCE = HERE / "tests/fixtures/custom_guest.s"


def link(work, text):
    obj, script, elf = work / "guest.o", work / f"guest-{text:08x}.ld", work / f"guest-{text:08x}.elf"
    script.write_text(f"ENTRY(_start)\nSECTIONS {{\n  . = {text:#x};\n  .text : {{ *(.text) }}\n"
                      f"  . = {text + 0x1000:#x};\n  .data : {{ *(.data) }}\n  /DISCARD/ : {{ *(.c6xabi.attributes) }}\n}}\n")
    subprocess.run([str(BIN / "tic6x-elf-as"), "-mlittle-endian", "-march=c674x", "-o", str(obj), str(SOURCE)],
                   check=True, capture_output=True)
    subprocess.run([str(BIN / "tic6x-elf-ld"), "-EL", "-T", str(script), "-o", str(elf), str(obj)],
                   check=True, capture_output=True)
    return elf


@unittest.skipUnless(shutil.which("g++") and (BIN / "tic6x-elf-as").exists(), "host g++ and DSP binutils required")
class CustomProgram(unittest.TestCase):
    def setUp(self):
        WORK.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="test-custom-", dir=WORK)
        self.work = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_symbols_are_read_without_external_tools(self):
        elf = link(self.work, 0xc2000000)
        names = elf_symbols(elf)
        self.assertEqual(names["_start"], 0xc2000000)
        self.assertEqual(names["result"], 0xc2001000)
        self.assertGreater(names["done"], names["main"])

    def test_program_runs_from_ddr_l2_and_shared_ram_and_reports_breakpoints_and_watched_words(self):
        for text in (0xc2000000, 0x11800000, 0x80000000):
            with self.subTest(text=hex(text)), Custom(link(self.work, text), WORK, breakpoints=("main", "done"),
                                                      watch=("result",)) as custom:
                report = custom.run(100000)
                self.assertIsNone(report["error"])
                self.assertEqual([row["name"] for row in report["checkpoints"]], ["main", "done"])
                self.assertEqual(report["watch"], {"result": 0x600df00d})
                self.assertEqual(report["state"]["cycles"], 100000)
                self.assertEqual(report["program"]["entry"], text)
                self.assertFalse(report["sd"]["present"])

    def test_card_is_a_private_copy(self):
        card = build_card(self.work / "card.img", {})
        original = card.read_bytes()
        with Custom(link(self.work, 0xc2000000), WORK, card=card) as custom:
            report = custom.run(10000)
            self.assertIsNone(report["error"])
            self.assertTrue(report["sd"]["present"])
            self.assertEqual(custom.cpu.sd_read(), original)
        self.assertEqual(card.read_bytes(), original)

    def test_rejects_programs_that_do_not_fit_the_device(self):
        with self.assertRaisesRegex(ValueError, "lacks mapped RAM"):
            Custom(link(self.work, 0x60000000), WORK)
        text = self.work / "not.elf"; text.write_bytes(b"not an ELF file" * 8)
        with self.assertRaisesRegex(ValueError, "ELF32"):
            Custom(text, WORK)
        with self.assertRaisesRegex(ValueError, "watched symbols"):
            Custom(link(self.work, 0xc2000000), WORK, watch=("missing",))

    def test_command_line_writes_a_report(self):
        output = self.work / "out"
        code = main(["--elf", str(link(self.work, 0xc2000000)), "--cycles", "20000", "--watch", "result",
                     "--output", str(output)])
        self.assertEqual(code, 0)
        self.assertIn('"result": 1611526157', (output / "result.json").read_text())


if __name__ == "__main__":
    unittest.main()
