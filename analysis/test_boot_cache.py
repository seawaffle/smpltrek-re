import unittest

import boot_cache


@unittest.skipUnless(boot_cache.EXTRACT.joinpath("section-00-c7074628.bin").exists(),
                     "needs the extracted bootloader (see boot_cache.py)")
class BootCacheTest(unittest.TestCase):
    def test_cache_state_at_jump(self):
        s = boot_cache.cache_state()
        self.assertEqual((s["L2CFG"], s["L1PCFG"], s["L1DCFG"]), (0, 4, 3))
        self.assertEqual([n for n, v in sorted(s["MAR"].items()) if v & 1], [17, 128, 192, 193, 194, 195, 199])


if __name__ == "__main__":
    unittest.main()
