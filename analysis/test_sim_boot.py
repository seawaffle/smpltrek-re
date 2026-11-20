"""sim_boot checks. Needs the official updates in firmware/ (not tracked); skips without them. About 30 s each.

Run: python3 -B -m unittest discover -s analysis -p "test_sim_boot.py" -v
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sim_boot

LOFI = ROOT / "firmware/lofi12/Lofi-12XT_v1.5.205.zip"


# The corpus tests decode code with tools/tic6x objdump (tools/toolchain/build_tic6x_binutils.sh).
OBJDUMP_OK = (Path(__file__).resolve().parents[1] / "tools/tic6x/bin/tic6x-elf-objdump").exists()


@unittest.skipUnless(LOFI.exists() and OBJDUMP_OK, "official Lofi-12 XT 1.5.205 update not present (or tools/tic6x objdump missing)")
class LofiBoot(unittest.TestCase):
    def test_static_objects_are_built(self):
        boot = sim_boot.Boot("lofi12", LOFI)
        self.assertEqual(boot.errors, [])
        m = boot.machine()
        # primary vtable address points from the RTTI
        expected = {0xC2B7CCD4: 0xC2D898A0,     # MainDelegate
                    0xC2B7F088: 0xC2D93480,     # AppSystemMenu
                    0xC2B7E440: 0xC2D93D70}     # AppMixer
        self.assertEqual({a: m.mem.word(a) for a in expected}, expected)

    def test_main_delegate_start_up_sets_its_message_handler(self):
        boot = sim_boot.Boot("lofi12", LOFI)
        m = boot.machine({"a4": 0xC2B7CCD4})
        m.run(0xC2BAC964, max_cycles=3000000)
        self.assertEqual(m.mem.word(0xC2B7CCD4 + 104), 0xC2B7CCD4 + 12)


if __name__ == "__main__":
    unittest.main()
