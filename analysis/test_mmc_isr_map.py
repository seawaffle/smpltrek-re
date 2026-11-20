"""Pins the MMC interrupt dispatch in docs/04-hardware-access.md ("Controller layer") against the simulated
`mmcsd0_isr` of SmplTrek 3.2.174. Run:
python3 -B -m unittest discover -s analysis -p "test_mmc_isr_map.py" -v

Needs firmware/ and the work listing; skipped without them.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hw_compare    # noqa: E402
import mmc_isr_map   # noqa: E402

P = hw_compare.PRODUCTS["smpltrek"]


@unittest.skipUnless((ROOT / P["image"]).exists() and (ROOT / P["listing"]).exists(), "official update not present")
class Simulated(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = mmc_isr_map.Session()

    def test_dispatch(self):
        isr = lambda st, mode=0: self.s.isr(st, mode)[0]     # noqa: E731
        self.assertEqual(isr(1 << 2), [("slot", 0)])                          # RSPDNE
        self.assertEqual(isr(1 << 2, 4), [("slot", 0), ("post", 0)])          # command waiting: post
        self.assertEqual(isr(1 << 0, 4), [("slot", 1)])                       # DATDNE
        self.assertEqual(isr(1 << 4, 4), [("slot", 2, -1)])                   # TOUTRS
        self.assertEqual(isr(1 << 3, 4), [("slot", 2, -2)])                   # TOUTRD
        self.assertEqual(isr(0x60, 4), [("slot", 2, -7)])                     # CRCWR | CRCRD
        for bit in (1, 7, 9, 10, 11, 12, 13):
            self.assertEqual(isr(1 << bit, 4), [], mmc_isr_map.BITS[bit])
        self.assertEqual(self.s.isr(0x5, 4), ([("slot", 0), ("post", 0), ("slot", 1)], 2))   # reads until clear

    def test_stock_has_no_listener(self):
        self.assertEqual(self.s.listener_at_boot(), 0)
        self.assertEqual(self.s.isr(1 << 2, 4, listener=False)[0], [("post", 0)])
        self.assertEqual(self.s.isr(1 << 4, 4, listener=False)[0], [])        # a time-out posts nothing
        self.assertEqual(self.s.isr(1 << 2, 1, listener=False)[0], [])        # data command: no post

    def test_data_done_posts_in_data_mode(self):
        self.assertEqual(self.s.isr(1 << 0, 1, listener=False)[0], [("post", 0)])    # DATDNE, mode 1

    def test_commands_wait_with_a_time_out(self):
        s, M = self.s, mmc_isr_map
        ok = lambda c: M.RSPDNE | (M.DATDNE if c & M.WDATX else 0)                      # noqa: E731
        read = {"b4": 0xC0010000, "a6": 0x100}
        self.assertEqual(s.command(M.CMD13, ok), (1, [(1000, 4)], [13], 0))             # released by RSPDNE
        self.assertEqual(s.command(M.READ, ok, dict(read, b6=1)), (1, [(1000, 1)], [17], 0))      # by DATDNE
        self.assertEqual(s.command(M.READ, ok, dict(read, b6=4)), (1, [(1000, 1), (1000, 4)], [18, 12], 0))
        for answer in (lambda c: M.TOUTRS, lambda c: 0):                                 # unanswered command
            self.assertEqual(s.command(M.CMD13, answer), (0, [(1000, 0)], [13], 0))     # fails, mode cleared
        self.assertEqual(s.command(M.READ, lambda c: M.RSPDNE, dict(read, b6=1)), (0, [(1000, 0)], [17], 0))

    def test_disk_layer_has_no_retry(self):
        s, M = self.s, mmc_isr_map
        ok = lambda c: M.RSPDNE | (M.DATDNE if c & M.WDATX else 0)                      # noqa: E731
        args = lambda n: {"a4": 0, "b4": 0xC0010000, "a6": 0x100, "b6": n}             # noqa: E731
        self.assertEqual(s.command(M.DISK_READ, ok, args(4)), (0, [(1000, 1), (1000, 4)], [18, 12], 0))
        self.assertEqual(s.command(M.DISK_READ, lambda c: 0, args(1)), (4, [(1000, 0)], [17], 0))  # one try
        no12 = lambda c: (M.RSPDNE | M.DATDNE) if c & M.WDATX else (0 if c & 0x3F == 12 else M.RSPDNE)  # noqa
        self.assertEqual(s.command(M.DISK_READ, no12, args(4))[0], 4)
        self.assertEqual(s.command(M.DISK_WRITE, ok, args(1)), (0, [(1000, 1), (1000, 4)], [24, 13], 0))
        self.assertEqual(s.command(M.DISK_WRITE, lambda c: 0, args(1)), (4, [(1000, 0)], [24], 0))
        no13 = lambda c: M.DATDNE if c & M.WDATX else (0 if c & 0x3F == 13 else M.RSPDNE)          # noqa
        self.assertEqual(s.command(M.DISK_WRITE, no13, args(1))[0], 0)                  # status poll ignored
        self.assertEqual(s.command(M.DISK_READ, ok, dict(args(1), a4=1)), (4, [], [], 0))           # drive 1


if __name__ == "__main__":
    unittest.main()
