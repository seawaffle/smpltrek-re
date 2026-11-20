"""Guest profiling observes actual packets/cycles without changing execution."""
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build import WORK
from cpu import CPU
from ir import Instruction, instruction


@unittest.skipUnless(shutil.which("g++"), "host g++ required")
class GuestProfile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        WORK.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(prefix="test-guest-profile-", dir=WORK)
        cls.work = Path(cls.temporary.name)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def machine(self, looping=False):
        cpu = CPU(self.work, decode=False)
        cpu.map(0x1000, 4096, 7)
        texts = ["b .S2 00001000", "nop 5"] if looping else ["mvk .S1 3,a4", "nop 9", "b .S2 b3", "nop 5"]
        for i, text in enumerate(texts):
            pc = 0x1000 + i * 4
            cpu.install(pc, pc + 4, False, pc & ~31, 32, (Instruction * 1)(instruction(pc, text)))
        cpu.reset(0x1000, return_address=None if looping else 0xdead0000)
        return cpu

    def test_exact_packets_wait_counters_and_profiled_execution_match_reference(self):
        states = []
        for enabled, sliced in ((False, False), (True, False), (True, True)):
            with self.subTest(enabled=enabled, sliced=sliced), self.machine() as cpu:
                if enabled:
                    cpu.profile_guest(1)
                state = cpu.run(1 if sliced else 100)
                while state["status"] == "budget":
                    state = cpu.run(1)
                self.assertEqual((state["cycles"], state["packets"], state["registers"]["a4"]), (16, 4, 3))
                states.append(state)
                if enabled:
                    cpu.profile_guest(0)
                    p = cpu.guest_profile()
                    self.assertEqual((p["cycles"], p["packets"], p["issue_cycles"], p["wait_cycles"]), (16, 4, 4, 12))
                    self.assertEqual((p["software_loop_cycles"], p["interrupt_entry_cycles"], p["interrupts"]), (0, 0, 0))
                    self.assertEqual((p["samples"], p["dropped_samples"]), (4, 0))
                    self.assertEqual(p["wait_advances"], 0 if sliced else 2)
                    self.assertEqual(p["wait_ticks_coalesced"], 0 if sliced else 10)
                    self.assertEqual([(r["pc"], r["kind"], r["samples"]) for r in p["pcs"]],
                                     [(pc, "ordinary_or_drain", 1) for pc in (0x1000, 0x1004, 0x1008, 0x100c)])
        self.assertEqual(states[0], states[1])
        self.assertEqual(states[0], states[2])

    def test_jittered_sampling_is_slice_independent_and_stop_freezes_the_window(self):
        profiles, states = [], []
        for sliced in (False, True):
            with self.machine(looping=True) as cpu:
                cpu.profile_guest(7)
                for _ in range(10000 if sliced else 1):
                    cpu.run(1 if sliced else 10000)
                cpu.profile_guest(0)
                p = cpu.guest_profile()
                self.assertEqual(p["samples"], sum(row["samples"] for row in p["pcs"]))
                self.assertEqual({row["pc"] for row in p["pcs"]}, {0x1000, 0x1004})
                self.assertEqual(p["issue_cycles"] + p["wait_cycles"], 10000)
                cpu.run(1000)
                self.assertEqual(cpu.guest_profile(), p)
                states.append(cpu.state())
                profiles.append(p)
        self.assertEqual(states[0], states[1])
        for name in ("cycles", "packets", "samples", "pcs", "issue_cycles", "wait_cycles"):
            self.assertEqual(profiles[0][name], profiles[1][name], name)

    def test_invalid_periods_restart_and_cpu_reset_are_explicit(self):
        with self.machine(looping=True) as cpu:
            for period in (True, -1, 1000001, 1.5):
                with self.subTest(period=period), self.assertRaises(ValueError):
                    cpu.profile_guest(period)
            self.assertLess(cpu.lib.c6_guest_profile(cpu.handle, 1000001), 0)
            cpu.profile_guest(1); cpu.run(12)
            self.assertEqual(cpu.guest_profile()["cycles"], 12)
            cpu.profile_guest(3)
            self.assertEqual(cpu.guest_profile()["cycles"], 0)
            cpu.run(6)
            self.assertEqual(cpu.guest_profile()["cycles"], 6)
            cpu.reset(0x1000, return_address=None)
            p = cpu.guest_profile()
            self.assertFalse(p["enabled"])
            self.assertEqual((p["cycles"], p["packets"], p["pcs"]), (0, 0, []))


if __name__ == "__main__":
    unittest.main()
