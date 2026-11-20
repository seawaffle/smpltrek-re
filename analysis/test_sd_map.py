"""Pins the SD controller layer in docs/04-hardware-access.md ("SD card", "Controller layer") against the simulated
code of SmplTrek 3.2.174, Lofi-12 XT 1.5.205 and CyDrums 1.1.84. Run:
python3 -B -m unittest discover -s analysis -p "test_sd_map.py" -v

Needs firmware/ and the work listings and match files (as test_hw_compare.py); skipped without them.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hw_compare   # noqa: E402
import sd_map       # noqa: E402

NEEDED = [ROOT / p[k] for p in hw_compare.PRODUCTS.values() for k in ("image", "listing")] + \
         [ROOT / p["match"] for p in hw_compare.PRODUCTS.values() if p["match"]]
RCA = 0x12340000    # the test's RCA << 16

# name -> [(MMCARGHL, MMCCMD)], as in 04-hardware-access.md
COMMANDS = {
    "CMD0": [(0, 0x4800)], "CMD55 probe": [(RCA, 0xA37), (0, 0xA37)], "CMD8": [(0x1AA, 0xA08)],
    "ACMD41": [(RCA, 0xA37), (0x40FF8000, 0xE29)], "CMD2": [(0, 0xC02)], "CMD3": [(0, 0xA03)],
    "CMD9": [(RCA, 0xC09)], "CMD7": [(RCA, 0xB07)], "CMD16": [(512, 0xA10)],
    "ACMD51": [(RCA, 0xA37), (RCA, 0x1A233)], "CMD13": [(RCA, 0xA0D)], "CMD12": [(0, 0x8B0C)]}
# (op, blocks) -> [(MMCARGHL, MMCCMD)] on a block-addressed card, block 0x100
TRANSFERS = {("read", 1): [(0x100, 0x1A211)], ("read", 4): [(0x100, 0x1A212), (0, 0x8B0C)],
             ("write", 1): [(0x100, 0x1AA18), (RCA, 0xA0D)],
             ("write", 4): [(0x100, 0x1AA19), (0, 0x8B0C), (RCA, 0xA0D)]}


@unittest.skipUnless(all(p.exists() for p in NEEDED), "official updates or work listings not present")
class Simulated(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = {key: sd_map.Session(key).all() for key in hw_compare.PRODUCTS}

    def test_same_in_three_products(self):
        for key in ("lofi12", "cydrums"):
            self.assertEqual(self.r[key], self.r["smpltrek"], key)

    def test_record(self):
        self.assertEqual(self.r["smpltrek"]["record"], {"memBase": 0x01C40000, "ipClk": 186000000, "opClk": 400000,
                                                        "intrMask": 0x7D, "busWidth": 5, "highspeed": 1})

    def test_commands(self):
        self.assertEqual(self.r["smpltrek"]["commands"], COMMANDS)
        for pairs in COMMANDS.values():     # no command sets PPLEN (SPRUH79C Table 25-18 bit 7: open drain)
            self.assertFalse(any(c & 0x80 for _, c in pairs))

    def test_transfers(self):
        t = self.r["smpltrek"]["transfers"]
        for key, pairs in TRANSFERS.items():
            self.assertEqual(sd_map.Session.commands_of(t[key]), pairs, key)
            first = [n for n, _ in t[key]].index("MMCCMD")
            w = dict(t[key][:first])       # each register / field as set before the data command
            self.assertEqual((w["MMCBLEN"], w["MMCNBLK"]), (512, key[1]))
            read = key[0] == "read"
            fifo = [v for n, v in t[key] if n == "MMCFIFOCTL"]
            self.assertEqual((fifo[0], fifo[-1]), (1, 4 if read else 6))   # reset; 64-byte level, direction
            ch = 16 if read else 17
            self.assertEqual(w[f"PaRAM({ch}).OPT"], 0x00010004 | (0 if read else 0x1000))   # TCC = ch, AB-sync
            self.assertEqual(w[f"PaRAM({ch}).A_B_CNT"], 0x00100004)                          # 4 x 16 = 64 bytes
            self.assertEqual(w[f"PaRAM({ch}).CCNT"], 8 * key[1])

    def test_bus_width(self):
        bw = self.r["smpltrek"]["bus_width"]
        self.assertEqual([v for n, v in bw[0x5] if n in ("MMCARGHL", "MMCCTL")][-3:], [2, 0, 4])
        self.assertEqual([v for n, v in bw[0x1] if n in ("MMCARGHL", "MMCCTL")][-3:], [0, 0, 0])

    def test_high_speed(self):
        self.assertEqual(self.r["smpltrek"]["high_speed"], {(0x32, 0): (0x103, 25000000, 0x32),
                                                            (0x32, 1): (0x103, 25000000, 0x5A),
                                                            (0x5A, 0): (0x101, 50000000, 0x5A),
                                                            (0x5A, 1): (0x101, 50000000, 0x5A)})

    def test_acmd41_card(self):
        self.assertEqual(self.r["smpltrek"]["acmd41_card"], ([0x00, 0x80, 0xFF, 0xC0], 1))

    def test_ctrl_init(self):
        self.assertEqual(self.r["smpltrek"]["ctrl_init"],
                         [("MMCCTL", 3), ("MMCCLK", 0), ("MMCCTL", 3), ("MMCCTL", 3), ("MMCCLK", 0xE8),
                          ("MMCTOR", 0x3FFFF), ("MMCTOD", 0xFFFF), ("MMCCTL", 0), ("MMCCLK", 0x1E8)])


if __name__ == "__main__":
    unittest.main()
