import json
import tempfile
import unittest

import region_diff as rd


class TestRegionDiff(unittest.TestCase):
    def test_parse_targets(self):
        text = ("c1000000:\t1ff86993 \tcallp .S2 c1000010 <entry-0x1>,b3\n"
                "c1000004:\t00000000 \tb .S1 c2000000 <entry+0x1>\n"
                "c1000008:\te3c00000 \t<fetch packet header 0xe3c00000>\n"
                "c100000c:\t0275d828 \tmvk .S1 -5200,a4 || nop 5\n")
        self.assertEqual(rd.parse(text, 0xC1000000, 0x20),
                         [(0, "callp .S2 +0x10,b3"), (4, "b .S1 EXT"), (0xC, "mvk .S1 -5200,a4")])

    def test_classification(self):
        base = [(0, "mvk .S1 -19256,a10"), (4, "mvkh .S1 3245211648,a10"), (8, "ldw .D2T2 *+b14(1400),b4"),
                (12, "mvk .L2 3,b4")]
        other = [(0, "mvk .S1 -5584,a10"), (4, "mvkh .S1 3268870144,a10"), (8, "ldw .D2T2 *+b14(1376),b4"),
                 (12, "mvk .L2 2,b4")]
        counts, others = rd.compare(base, other)
        self.assertEqual(counts, {"address": 4, "b14": 2, "other": 2})
        self.assertEqual(others, ["-0x000c mvk .L2 3,b4", "+0x000c mvk .L2 2,b4"])

    def test_locate(self):
        matches = {"matches": [{"a": "0xc1000000", "b": "0xc2000000"}, {"a": "0xc1000100", "b": "0xc2000100"},
                               {"a": "0xc1000200", "b": "0xc2000300"}]}
        with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
            json.dump(matches, f)
            f.flush()
            self.assertEqual(rd.locate(f.name, 0xC1000010, 0xC1000180), 0xC2000010)
            self.assertIsNone(rd.locate(f.name, 0xC1000010, 0xC1000280))

    def test_address_constants(self):
        insns = [(0, "mvk .S2 808,b4"), (4, "mvkh .S2 3245146112,b4"), (8, "mvk .L2 13,b5"),
                 (12, "mvk .S1 -5200,a4"), (16, "mvkh .S1 3245211648,a4"), (20, "mvkh .S1 65536,a6")]
        self.assertEqual(rd.address_constants(insns), [0xC16D0328, 0xC16EEBB0])


if __name__ == "__main__":
    unittest.main()
