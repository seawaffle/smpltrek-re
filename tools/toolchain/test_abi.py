"""Tests for the cl6x / GCC interoperability harness. The compiler tests skip when either toolchain is
absent (cl6x under ~/ti or $TI_CGT_C6000, GCC under tools/tic6x). The simulator fixes the harness
needed are covered by analysis/test_c6sim.py for the firmware and here for compiled code.
Run: python3 -B -m unittest discover -s tools/toolchain -v"""
import struct
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import abi_build   # noqa: E402
import abi_check   # noqa: E402
import elfsim      # noqa: E402

tools = unittest.skipUnless(abi_build.tools_present(), "cl6x and tic6x-elf-gcc are both needed")


class Expected(unittest.TestCase):
    def test_expected_values_are_self_consistent(self):
        self.assertEqual(len(abi_check.EXPECTED), 45)
        self.assertEqual(abi_check.EXPECTED[:2], [55, 650])
        # 11.5 as an IEEE double, low word then high word
        self.assertEqual(abi_check.EXPECTED[6:8], [0, 0x40270000])
        # C truncating division: -1000000007 / 13 and the 64-bit remainder keep the dividend's sign
        sdiv = abi_check.EXPECTED[abi_check.LABELS.index("sdiv")]
        self.assertEqual(struct.unpack("<i", struct.pack("<I", sdiv))[0], -76923077)
        self.assertEqual(abi_check.c_rem(-7, 3), -1)
        self.assertEqual(abi_check.c_div(-7, 3), -2)


@tools
class Pairings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        out = Path(cls.tmp.name)
        cls.objs = abi_build.compile_all(out)
        cls.elfs = abi_build.link_all(out, cls.objs)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_pairing_matches_the_expected_words(self):
        for name, elf in self.elfs.items():
            with self.subTest(pairing=name):
                words, cycles, b14 = abi_check.run(elf)
                self.assertEqual(words, abi_check.EXPECTED)
                self.assertEqual(b14, abi_check.DP_SENTINEL)
                self.assertGreater(cycles, 0)

    def test_gcc_never_writes_the_data_page_register(self):
        import re
        import subprocess
        for name in ("abi_driver", "abi_funcs"):
            dis = subprocess.run([str(abi_build.OBJDUMP), "-d", str(self.objs[("gcc", name)])],
                                 capture_output=True, text=True, check=True).stdout
            self.assertEqual(re.findall(r",b14\s*$", dis, re.M), [], name)

    def test_elf_loader_sees_every_code_section(self):
        program, syms = elfsim.load(self.elfs["ti_ti"])
        self.assertIn("abi_driver", syms)
        self.assertIn("__c6xabi_divu", syms)
        self.assertIn(syms["__c6xabi_divu"], program.text)   # TI's helper lives in its own .text:* section


if __name__ == "__main__":
    unittest.main()
