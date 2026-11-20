"""cydrums_card_check: a foreign card (no /CyDrums folder) gets no write-side calls, and the hooks do catch writes.

Run: python3 -B -m unittest discover -s analysis -p "test_cydrums_card_check.py" -v
Needs the official CyDrums 1.1.84 and 2.0.97 beta updates in firmware/ (not tracked); each class skips without its
image. A few minutes each (the start-up state is built once per class).
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cydrums_card_check as cc
import sim_boot

CYDRUMS = ROOT / "firmware/cydrums/CyDrums_v1.1.84.zip"
CYDRUMS_2 = ROOT / "firmware/cydrums/CyDrums_v2.0.97beta.zip"
PATH = 0x30000300


# The corpus tests decode code with tools/tic6x objdump (tools/toolchain/build_tic6x_binutils.sh).
OBJDUMP_OK = (Path(__file__).resolve().parents[1] / "tools/tic6x/bin/tic6x-elf-objdump").exists()


@unittest.skipUnless(CYDRUMS.exists() and OBJDUMP_OK, "official CyDrums 1.1.84 update not present (or tools/tic6x objdump missing)")
class ForeignCard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.boot = sim_boot.Boot("cydrums", CYDRUMS)
        cls.path = {PATH + i: b for i, b in enumerate(b"/CyDrums/System/Temp\0")}

    def test_paths_make_no_write_calls(self):
        seen = {}
        for name, start, regs, memory in cc.PATHS:
            log, _ = cc.run_path(self.boot, start, regs, memory)
            self.assertEqual([entry for entry in log if entry[3]], [], name)
            seen[name] = [(call, path) for call, path, _, _ in log]
        self.assertEqual(seen["start-up card block"], [("f_mount", ""),
                                                       ("f_stat", "/CyDrums/System/SystemCore.bin")])

    def test_hooks_catch_mkdir(self):
        log, _ = cc.run_path(self.boot, 0xC2565AD0, {"a4": PATH}, extra_memory=self.path)     # file_mkdir
        self.assertEqual(log, [("f_mkdir", "/CyDrums/System/Temp", None, True)])

    def test_hooks_catch_open_for_write(self):
        log, _ = cc.run_path(self.boot, 0xC2565B6C, {"a4": PATH, "b4": 0x0A}, extra_memory=self.path)  # file_open
        self.assertEqual(log, [("f_open", "/CyDrums/System/Temp", 0x0A, True)])


@unittest.skipUnless(CYDRUMS_2.exists() and OBJDUMP_OK, "official CyDrums 2.0.97 beta update not present (or tools/tic6x objdump missing)")
class ForeignCard2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.boot = sim_boot.Boot("cydrums-2.0.97", CYDRUMS_2)
        cls.path = {PATH + i: b for i, b in enumerate(b"/CyDrums/System/Temp\0")}

    def test_version_from_image(self):
        self.assertEqual(cc.image_version(CYDRUMS_2), "2.0.97")

    def test_boot_errors(self):
        self.assertEqual(self.boot.errors, [])
        m = self.boot.machine()
        self.assertEqual(m.mem.word(0xC222288C), 0xC27124C0)      # MainDelegate, its vtable (RTTI)
        self.assertEqual(m.mem.word(0xC249B2DC), 0xC2725868)      # AppNoSystemCore

    def test_paths_make_no_write_calls(self):
        seen = {}
        for name, start, regs, memory in cc.paths("2.0.97"):
            log, m = cc.run_path(self.boot, start, regs, memory, version="2.0.97")
            self.assertEqual([entry for entry in log if entry[3]], [], name)
            seen[name] = [(call, path) for call, path, _, _ in log]
            if name == "start-up card block":      # the new sample-slot reset runs before the card check
                self.assertIn(0xC2611284, [target for _, target, _, _ in m.calls])
        self.assertEqual(seen["start-up card block"], [("f_mount", ""),
                                                       ("f_stat", "/CyDrums/System/SystemCore.bin")])
        self.assertEqual(seen["card inserted (lambda, event 1)"], seen["start-up card block"])

    def test_old_cydrums_card_gets_config_writes(self):
        """SystemCore.bin found, nothing else: the start-up block creates the configs and a project folder.
        The run stops later in the project load (a null object; tasks and the rest of start-up are not run)."""
        name, start, regs, memory = cc.paths("2.0.97")[0]
        log, m = cc.run_path(self.boot, start, regs, memory, version="2.0.97", stat_found=(cc.SYSTEM_CORE,),
                             keep_going=True)
        self.assertEqual([(call, path, mode) for call, path, mode, is_write in log if is_write], [
            ("f_open", "/CyDrums/System/.SoundConfig", 6),
            ("f_open", "/CyDrums/System/.EfxConfig", 6),
            ("f_open", "/CyDrums/System/.KitConfig", 6),
            ("f_mkdir", "/CyDrums/System/Project/Project001", None)])
        self.assertNotIn("/CyDrums/Contents/Samples/SlotInfo.lst", [path for _, path, _, _ in log])

    def test_hooks_catch_mkdir(self):
        log, _ = cc.run_path(self.boot, 0xC25E2E50, {"a4": PATH}, extra_memory=self.path, version="2.0.97")
        self.assertEqual(log, [("f_mkdir", "/CyDrums/System/Temp", None, True)])

    def test_hooks_catch_open_for_write(self):
        log, _ = cc.run_path(self.boot, 0xC25E2EEC, {"a4": PATH, "b4": 0x0A}, extra_memory=self.path,
                             version="2.0.97")
        self.assertEqual(log, [("f_open", "/CyDrums/System/Temp", 0x0A, True)])


if __name__ == "__main__":
    unittest.main()
