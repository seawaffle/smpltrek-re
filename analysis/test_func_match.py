"""func_match checks. Run: python3 -B -m unittest discover -s analysis -v

The corpus test needs the official updates in firmware/ (not tracked) and skips when they are absent.
"""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import func_match

NEW = ROOT / "firmware/smpltrek/SmplTrek v3.2.174.zip"
OLD = ROOT / "firmware/smpltrek/SmplTrek v3.0.148.zip"


def bare_program(insns=(), parallel=(), predicate=()):
    """A Program with only the fields the instruction-level helpers use."""
    p = object.__new__(func_match.Program)
    p.strings = {}
    p.insns = list(insns)
    p.parallel = list(parallel) or [False] * len(p.insns)
    p.predicate = list(predicate) or [""] * len(p.insns)
    return p


class NormaliseTests(unittest.TestCase):
    def setUp(self):
        self.p = bare_program()

    def norm(self, mnemonic, operands, address=0):
        return func_match.Program._normalise(self.p, address, mnemonic, operands)

    def test_branch_targets_and_return_encodings(self):
        self.assertEqual(self.norm("callp", ".S2 c166442c <entry-0x30154>,b3"), "callp .S2 ADDR,b3")
        self.assertEqual(self.norm("bnop", ".S2 b3,0"), self.norm("b", ".S2 b3"))
        self.assertNotEqual(self.norm("bnop", ".S2 b3,4"), self.norm("b", ".S2 b3"))

    def test_constants(self):
        self.assertEqual(self.norm("mvkh", ".S1 3245146112,a6"), "mvkh .S1 IMM,a6")
        self.assertEqual(self.norm("mvk", ".S1 13568,a6"), "mvk .S1 IMM,a6")
        self.assertEqual(self.norm("mvk", ".D1 2,a4"), "mvk .D1 2,a4")  # small: a real constant, kept
        self.assertEqual(self.norm("mvk", ".S2 -1,b4"), "mvk .S2 -1,b4")

    def test_data_page_offsets_and_objdump_artefacts(self):
        self.assertEqual(self.norm("ldw", ".D2T1 *+b14(1352),a4"), "ldw .D2T1 *+b14(DP),a4")
        self.assertEqual(self.norm("addab", ".D2 b14,1671,b11"), "addab .D2 b14,DP,b11")
        self.assertEqual(self.norm("ldw", ".D2T2 *+b15(4),b10"), "ldw .D2T2 *+b15(4),b10")  # stack: kept
        self.assertEqual(self.norm("stw", ".D2T2 b3,*b15--(8) || nop 5"), "stw .D2T2 b3,*b15--(8)")

    def test_string_constants_become_text(self):
        self.p.strings = {0x10: "SYSTEM INFO"}
        self.assertEqual(self.norm("mvkh", ".S2 3245080576,b4", address=0x10), "mvkh STR:SYSTEM INFO")


class FunctionEndTests(unittest.TestCase):
    def test_start_after_return_delay_slots(self):
        # 3.2.174 0xC15D330C..0xC15D3314: BNOP B3,0; LDW; NOP 4 (5 delay cycles); new function.
        p = bare_program([(0x0, "bnop", ".S2 b3,0"), (0x2, "ldw", ".D2T1 *++b15(8),a14"),
                          (0x4, "nop", "4"), (0x8, "mv", ".L2 b3,b11")])
        self.assertEqual(p._ends_of_functions(set()), {0x8})

    def test_no_start_where_an_earlier_branch_lands(self):
        p = bare_program([(0x0, "b", ".S1 00000010 <x>"), (0x4, "b", ".S2 b3"), (0x8, "nop", "5"),
                          (0x10, "mv", ".L2 b3,b11")])
        self.assertEqual(p._ends_of_functions(set()), set())

    def test_predicated_return_is_not_an_end(self):
        p = bare_program([(0x0, "b", ".S2 b3"), (0x4, "nop", "5"), (0x8, "mv", ".L2 b3,b11")],
                         predicate=["[a0]", "", ""])
        self.assertEqual(p._ends_of_functions(set()), set())


class NeighbourTests(unittest.TestCase):
    @staticmethod
    def program(starts, bodies):
        p = object.__new__(func_match.Program)
        p.starts, p.body = starts, dict(zip(starts, bodies))
        return p

    def test_gap_filled_only_when_layout_and_bodies_agree(self):
        same, other = ["mvk .S1 IMM,a3", "stw .D1T2 b4,*+a4[a3]", "b .S2 b3"], ["ldw x", "ldw y", "ldw z"]
        # Matches (delta in brackets): 0x100 (0x1000), 0x200 (0x1000), 0x300 (0x1100), 0x400 (0x1100),
        # 0x500 (0x1100). Gaps: 0x120/0x140 same layout, same delta -> filled; 0x220 lies between
        # different deltas -> not filled; 0x320 matches layout but in b the gap holds two starts -> not
        # filled; 0x420 has the layout but a different body -> not filled.
        a = self.program([0x100, 0x120, 0x140, 0x200, 0x220, 0x300, 0x320, 0x400, 0x420, 0x500],
                         [same] * 8 + [other, same])
        b = self.program([0x1100, 0x1120, 0x1140, 0x1200, 0x1260, 0x1400, 0x1420, 0x1440,
                          0x1500, 0x1520, 0x1600], [same] * 11)
        m = func_match.Matching(a, b)
        m.accept([(0x100, 0x1100), (0x200, 0x1200), (0x300, 0x1400), (0x400, 0x1500), (0x500, 0x1600)], "hash")
        m.by_neighbours()
        self.assertEqual(m.ab.get(0x120), 0x1120)
        self.assertEqual(m.ab.get(0x140), 0x1140)
        self.assertEqual(m.method[0x120], "neighbours")
        for x in (0x220, 0x320, 0x420):
            self.assertNotIn(x, m.ab)


# The corpus tests decode code with tools/tic6x objdump (tools/toolchain/build_tic6x_binutils.sh).
OBJDUMP_OK = (Path(__file__).resolve().parents[1] / "tools/tic6x/bin/tic6x-elf-objdump").exists()


@unittest.skipUnless(NEW.exists() and OLD.exists() and OBJDUMP_OK, "official updates not present in firmware/ (or tools/tic6x objdump missing)")
class CorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a, cls.b = func_match.load(NEW), func_match.load(OLD)
        cls.match = func_match.Matching(cls.a, cls.b)
        cls.match.run()

    def test_coverage_and_holdout_precision(self):
        self.assertGreater(len(self.match.ab) / len(self.a.starts), 0.7)
        h = func_match.holdout(self.a, self.b)
        self.assertGreater(h["scored"], 500)
        self.assertGreaterEqual(h["agree"] / h["scored"], 0.99)

    def test_matching_is_one_to_one(self):
        self.assertEqual(len(set(self.match.ab.values())), len(self.match.ab))

    def test_hand_named_symbols_carry_to_3_0_148(self):
        symbols = json.loads((ROOT / "symbols/smpltrek-3.2.174.json").read_text())
        carried = {t["name"]: t["b"] for t in func_match.transfer(symbols, self.match)}
        drawing = {"get_font", "draw_text", "draw_text_with_font", "draw_text_impl", "draw_page_title",
                   "AppSystemInfo::draw_title"}
        self.assertEqual({k: v for k, v in carried.items() if k in drawing}, {
            "get_font": "0xc1743da0",
            "draw_text": "0xc16806d0",
            "draw_text_with_font": "0xc170446c",
            "draw_text_impl": "0xc171f1c0",
            "draw_page_title": "0xc1678060",
            "AppSystemInfo::draw_title": "0xc17073e0",
        })


if __name__ == "__main__":
    unittest.main()
