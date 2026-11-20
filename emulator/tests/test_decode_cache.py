"""The persistent decode cache must install exactly what a fresh decode installs."""
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from core_demo import build_fixture, symbols, tools_present
from cpu import CPU
from decoder import CACHE_ENV

APPLICATION = 0xC2100000


@unittest.skipUnless(shutil.which("g++") and tools_present(), "host g++ and DSP binutils required")
class DecodeCache(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="smpltrek-decode-")
        self.work = Path(self.temporary.name)
        self.elf = build_fixture(self.work)
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(os.environ.pop, CACHE_ENV, None)
        os.environ.pop(CACHE_ENV, None)

    def execute(self, replace=False):
        """Run the fixture's copy-then-execute routine; optionally execute replaced RAM bytes too."""
        names = symbols(self.elf)
        with CPU(self.work) as machine:
            entry = machine.load_elf(self.elf)
            machine.map(APPLICATION, 4096, 7)
            machine.reset(entry)
            state = machine.run(100000)
            self.assertEqual((state["status"], state["registers"]["a4"]), ("returned", 42))
            packets = {pc: machine.packet_info(pc) for pc in (entry, APPLICATION)}
            if replace:
                machine.write(APPLICATION, machine.read(names["replacement"], 32))
                machine.reset(APPLICATION)
                state = machine.run(100000)
                self.assertEqual((state["status"], state["registers"]["a4"]), ("returned", 99))
            return state, packets, dict(machine.decoder.text), machine.decoder.cache_hits, machine.decoder.cache_misses

    def test_second_run_replays_identical_packets_text_and_state(self):
        state, packets, text, hits, misses = self.execute()
        self.assertEqual(hits, 0)
        self.assertGreater(misses, 0)
        self.assertTrue(any((self.work / "decode-cache").rglob("*.json.z")))
        again = self.execute()
        self.assertEqual(again[:3], (state, packets, text))
        self.assertEqual(again[3:], (misses, 0))

    def test_changed_page_bytes_are_decoded_again(self):
        self.execute()
        state, _, _, hits, misses = self.execute(replace=True)
        self.assertEqual(state["registers"]["a4"], 99)
        self.assertGreater(hits, 0)
        self.assertEqual(misses, 1)  # only the page whose bytes were replaced

    def test_damaged_entries_fall_back_to_decoding_and_are_rewritten(self):
        reference = self.execute()
        entries = list((self.work / "decode-cache").rglob("*.json.z"))
        for index, entry in enumerate(entries):
            entry.write_bytes(b"not a cache entry" if index % 2 else entry.read_bytes()[:20])
        damaged = self.execute()
        self.assertEqual(damaged[:3], reference[:3])
        self.assertEqual(damaged[3:], (0, len(entries)))
        self.assertEqual(self.execute()[3:], (len(entries), 0))

    def test_cache_can_be_disabled_or_moved(self):
        os.environ[CACHE_ENV] = "off"
        reference = self.execute()
        self.assertEqual(self.execute()[3], 0)
        self.assertFalse((self.work / "decode-cache").exists())
        os.environ[CACHE_ENV] = str(self.work / "elsewhere")
        self.execute()
        moved = self.execute()
        self.assertEqual(moved[:3], reference[:3])
        self.assertGreater(moved[3], 0)
        self.assertTrue(any((self.work / "elsewhere").rglob("*.json.z")))


if __name__ == "__main__":
    unittest.main()
