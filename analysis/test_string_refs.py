"""string_refs checks. Run: python3 -B -m unittest discover -s analysis -v

The pairing tests are self-contained. The corpus test needs firmware/ and the tic6x objdump build, and
skips without them.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mmtd2elf
import sonicware_integrity as integrity
import string_refs


class PairingTests(unittest.TestCase):
    def test_line_parser_handles_parallel_conditional_and_compact(self):
        lines = [
            "c1666da8:\t0245b22a \tmvk .S2 -29852,b4",
            "c1505418:\t2aef      \t[a0] mvk .S2 1,b5",
            "c1505490:\t220081aa \t|| [b0] mvk .S2 259,b4",
            "c1505494:\t3084a35a \t[!b0] mvk .L2 1,b1",
            "c16ac74a:\t01ef      \tbnop .S2 b3,0",
        ]
        parsed = [string_refs.LINE.match(l).groups() for l in lines]
        self.assertEqual([(p[1], p[2]) for p in parsed],
                         [("mvk", ".S2 -29852,b4"), ("mvk", ".S2 1,b5"), ("mvk", ".S2 259,b4"),
                          ("mvk", ".L2 1,b1"), ("bnop", ".S2 b3,0")])

    def test_pairs_track_registers_and_invalidate_on_write(self):
        instructions = [
            (0x100, "mvk", ".S2 -29852,b4"),      # low 0x8b64 -> b4
            (0x104, "mvk", ".S1 4660,a3"),        # low 0x1234 -> a3
            (0x108, "add", ".L1 a3,a4,a3"),       # a3 overwritten: its pending low is dropped
            (0x10c, "mvkh", ".S2 3245080576,b4"), # 0xc16c0000 | 0x8b64
            (0x110, "mvkh", ".S1 3245080576,a3"), # no pair
            (0x114, "stw", ".D2T2 b4,*+b15(8)"),  # store: no register written
        ]
        self.assertEqual(list(string_refs.constant_pairs(instructions)), [(0xC16C8B64, 0x10C, 0x100)])

    def test_window_drops_stale_low_half(self):
        far = string_refs.WINDOW + 4
        instructions = [(0, "mvk", ".S2 1,b4"), (far, "mvkh", ".S2 3245080576,b4")]
        self.assertEqual(list(string_refs.constant_pairs(instructions)), [])


ZIP = ROOT / "firmware/smpltrek/SmplTrek v3.2.174.zip"


@unittest.skipUnless(ZIP.exists() and string_refs.OBJDUMP.exists(), "needs firmware/ and tools/tic6x objdump")
class CorpusTests(unittest.TestCase):
    def test_known_3_2_174_references(self):
        (_, data), = list(integrity.inputs([ZIP]))
        _, entry, sections = mmtd2elf.mmtd_sections(data)
        result = string_refs.analyse(sections, entry)
        by_text = {}
        for s in result["strings"]:
            by_text.setdefault(s["text"], s)
        # The label patched to CUSTOM INFO on hardware, and its neighbours on the System Info page.
        self.assertEqual(by_text["SYSTEM INFO"]["address"], 0xC16C8B64)
        self.assertEqual(by_text["SYSTEM INFO"]["code_refs"], [0xC1666DAC])
        # Labels stored right after it (the same text can occur elsewhere, so select by address).
        neighbours = {s["text"]: s for s in result["strings"] if 0xC16C8B64 < s["address"] < 0xC16C8B90}
        for label in ("VERSION", "BOOT", "PRESET"):
            self.assertTrue(0xC1666D00 <= neighbours[label]["code_refs"][0] < 0xC1667000, label)
        self.assertNotIn("Checking...", by_text)  # bootloader text, not in the app
        self.assertGreater(result["constant_pairs"], 13000)


if __name__ == "__main__":
    unittest.main()
