"""Fast-forward of repeating guest state must be indistinguishable from executing every cycle."""
import shutil
import struct
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from cpu import CPU
from ir import Instruction, instruction


@unittest.skipUnless(shutil.which("g++"), "host g++ required")
class FastForward(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="smpltrek-forward-")
        cls.work = Path(cls.temporary.name)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    @staticmethod
    def install(cpu, start, texts):
        for index, text in enumerate(texts):
            address = start + index * 4
            cpu.install(address, address + 4, False, address & ~31, 32, (Instruction * 1)(instruction(address, text)))

    def machine(self, body=()):
        """A loop at 0x1000: the branch, `body` in its delay slots, then NOPs up to the landing."""
        cpu = CPU(self.work, decode=False)
        cpu.enable_board()
        cpu.map(0x1000, 4096, 7)
        cpu.map(0x2000, 4096, 7)
        cpu.map(0x4000, 8192, 3)
        self.install(cpu, 0x1000, ["b .S1 00001000", *body, f"nop {5 - len(body)}"])
        cpu.reset(0x1000, return_address=None)
        return cpu

    @staticmethod
    def put(cpu, address, value):
        cpu.write(address, struct.pack("<I", value))

    def timer(self, cpu, period):
        """Timer0 in continuous mode (an event every period * 15.5 cycles) into interrupt 4."""
        self.install(cpu, 0x2080, ["add .L1 1,a8,a8", "mvc .S2 itsr,b9", "b .S2 irp", "nop 5"])
        cpu.set_register("istp", 0x2000)
        cpu.set_register("ier", 0x12)
        cpu.set_register("csr", 0x101)
        self.put(cpu, 0x01c20018, period)
        self.put(cpu, 0x01c20024, 5)
        self.put(cpu, 0x01c20020, 0x80)

    def spi_loopback(self, cpu, receive):
        """SPI1 in loopback sends the four bytes at 0x4100 by DMA; `receive` is the PaRAM set
        of the receive channel, triggered once per byte."""
        for base, module in ((0x01e27000, 10), (0x01c10000, 0)):
            self.put(cpu, base + 0xa00 + module * 4, 3); self.put(cpu, base + 0x120, 1)
            cpu.run(16)
        spi = 0x01f0e000
        for offset, value in ((0, 0), (0, 1), (4, 3), (0x14, 0xe01), (0x50, 0x00011308), (4, 0x01010003)):
            self.put(cpu, spi + offset, value)
        self.put(cpu, 0x01c14134, 0x00100110)
        self.put(cpu, 0x01c00348, 3 << 18)
        for channel, words in ((19, [0x00013000, 0x4100, 0x00040001, spi + 0x3c, 1, 0xffff, 0, 1]), (18, receive)):
            for index, value in enumerate(words):
                self.put(cpu, 0x01c04000 + channel * 32 + index * 4, value)
        self.put(cpu, 0x01c01030, 3 << 18)
        self.put(cpu, spi + 8, 0x10000)

    def observe(self, prepare, boundaries, forward, sliced=False):
        with prepare() as cpu:
            cpu.fast_forward(forward)
            before = cpu.fast_forward_state()  # prepare may already have run a few cycles
            rows, state = [], cpu.state()
            for boundary in boundaries:
                while cpu.cycles() < boundary:
                    state = cpu.run(1 if sliced else boundary - cpu.cycles())
                rows.append((state, cpu.read(0x4000, 64)))
            after = cpu.fast_forward_state()
            return rows, {name: value - before[name] for name, value in after.items() if name != "enabled"}

    def compare(self, prepare, boundaries):
        """Every boundary state with fast-forward equals the one without; returns its statistics."""
        reference, off = self.observe(prepare, boundaries, False)
        self.assertEqual(off["skipped_cycles"], 0)
        forward, stats = self.observe(prepare, boundaries, True)
        self.assertEqual(forward, reference)
        self.assertEqual(self.observe(prepare, boundaries[:40], True, sliced=True)[0], reference[:40])
        return stats

    def test_spin_loop_is_skipped_and_every_boundary_state_matches(self):
        stats = self.compare(self.machine, [1, 5, 6, 7, 100, 101, 1000, 1003, 60000, 60001, 60005])
        self.assertGreater(stats["skipped_cycles"], 55000)
        self.assertEqual(stats["skipped_cycles"] % 6, 0)  # whole six-cycle periods only
        self.assertEqual(stats["skipped_packets"] * 3, stats["skipped_cycles"])  # two packets per period

    def test_store_of_the_same_value_keeps_the_loop_repeating(self):
        def prepare():
            # The load's result lands with the branch, so the pipeline is empty at the anchor.
            cpu = self.machine(["ldw .D1T1 *+a5(4),a6", "stw .D1T1 a4,*+a5(0)"])
            cpu.set_register("a4", 0x12345678); cpu.set_register("a5", 0x4000)
            self.put(cpu, 0x4004, 0xcafe)
            return cpu
        stats = self.compare(prepare, [3, 12, 13, 500, 20000, 20001])
        self.assertGreater(stats["skipped_cycles"], 15000)

    def test_loop_that_alternates_ram_repeats_over_several_iterations(self):
        def prepare():
            # Loads a word, inverts the previous load and stores that: state returns after a
            # few iterations, with RAM different in between.
            cpu = self.machine(["ldw .D1T1 *+a5(0),a6", "not .L1 a6,a7", "stw .D1T1 a7,*+a5(0)"])
            cpu.set_register("a5", 0x4000)
            self.put(cpu, 0x4000, 0x0f0f0f0f)
            return cpu
        stats = self.compare(prepare, [1, 20, 21, 22, 23, 24, 25, 26, 27, 300, 301, 302, 30000, 30001, 30007])
        self.assertGreater(stats["proofs"], 0)

    def test_progressing_and_time_reading_loops_execute_every_cycle(self):
        for body, name in ((["add .L1 1,a4,a4"], "counter"), (["mvc .S2 tscl,b4"], "timestamp")):
            with self.subTest(name):
                stats = self.compare(lambda: self.machine(body), [1, 50, 51, 2000, 2001])
                self.assertEqual(stats["skipped_cycles"], 0)

    def test_timer_interrupts_enter_and_return_at_the_same_cycles(self):
        def prepare():
            cpu = self.machine()
            self.timer(cpu, 40)  # an event every 620 cycles; the loop repeats every 6
            return cpu
        # Dense boundaries around two timer events, the interrupt entries and the returns.
        boundaries = [*range(600, 660), *range(1225, 1275), 5000, 5001, 40000, 40003]
        stats = self.compare(prepare, boundaries)
        self.assertGreater(stats["skipped_cycles"], 30000)
        self.assertGreater(stats["events_run_ahead"], 20)
        self.assertGreater(stats["events_held_back"], 20)  # each raised interrupt 4

    def test_masked_timer_flag_is_already_set_and_events_keep_running_ahead(self):
        def prepare():
            cpu = self.machine()
            self.timer(cpu, 40)
            cpu.set_register("ier", 0x02)  # the flag is raised but never taken
            return cpu
        stats = self.compare(prepare, [*range(615, 630), 20000, 20001, 20006])
        self.assertGreater(stats["events_run_ahead"], stats["events_held_back"] + 10)

    def test_eager_board_polling_and_guest_profiling_disable_skipping(self):
        for eager, profile in ((True, False), (False, True)):
            with self.subTest(eager=eager, profile=profile), self.machine() as cpu:
                cpu.board_eager_polling(eager)
                if profile:
                    cpu.profile_guest(1)
                cpu.run(5000)
                self.assertEqual(cpu.fast_forward_state()["skipped_cycles"], 0)

    def test_host_writes_between_runs_are_seen_by_the_loop(self):
        with self.machine(["ldw .D1T1 *+a5(0),a6"]) as cpu:
            cpu.set_register("a5", 0x4000)
            self.put(cpu, 0x4000, 1)
            cpu.run(6000)
            self.assertGreater(cpu.fast_forward_state()["skipped_cycles"], 0)
            self.assertEqual(cpu.state()["registers"]["a6"], 1)
            self.put(cpu, 0x4000, 2)
            cpu.run(6000)
            self.assertEqual(cpu.state()["registers"]["a6"], 2)

    def test_flag_the_loop_clears_and_sets_again_still_sees_every_timer_event(self):
        def prepare():
            # Each period clears masked flag 4, reads IFR, then sets the flag again, so the
            # anchor always finds it set. A timer event between the clear and the read counts.
            cpu = self.machine()
            self.install(cpu, 0x1000, ["b .S1 00001000", "mvc .S2 b4,icr", "nop", "mvc .S2 ifr,b0",
                                       "mvc .S2 b4,isr", "[b0] add .L1 1,a8,a8"])
            self.timer(cpu, 6)  # an event every 93 cycles drifts through the six-cycle period
            cpu.set_register("ier", 2); cpu.set_register("ifr", 16); cpu.set_register("b4", 16)
            return cpu
        reference, _ = self.observe(prepare, [6000, 6001, 6007], False)
        self.assertGreater(reference[0][0]["registers"]["a8"], 5)
        forward, stats = self.observe(prepare, [6000, 6001, 6007], True)
        self.assertEqual(forward, reference)
        self.assertGreater(stats["skipped_cycles"], 3000)

    def test_every_word_of_a_device_transfer_arrives_at_its_own_cycle(self):
        def prepare():
            # As below, but the receive event copies two words to 0x4000 and the loop watches
            # the second: a write behind the first one the loop touches must be held back too.
            cpu = self.machine(["ldw .D1T1 *+a5(4),b0", "[b0] add .L1 1,a8,a8"])
            cpu.set_register("a5", 0x4000)
            cpu.write(0x4100, b"DMA!")
            cpu.write(0x4108, struct.pack("<II", 0x11111111, 0x22222222))
            self.spi_loopback(cpu, [0x00012000, 0x4108, 0x00010008, 0x4000, 0, 0xffff, 0, 1])
            return cpu
        reference, _ = self.observe(prepare, [4000, 4001, 4013], False)
        self.assertEqual(reference[0][1][:8], struct.pack("<II", 0x11111111, 0x22222222))
        self.assertGreater(reference[0][0]["registers"]["a8"], 100)
        forward, stats = self.observe(prepare, [4000, 4001, 4013], True)
        self.assertEqual(forward, reference)
        self.assertGreater(stats["skipped_cycles"], 100)
        self.assertGreater(stats["events_held_back"], 0)

    def test_device_write_of_the_value_already_there_does_not_hold_events_back(self):
        def prepare():
            # The receive DMA stores the same byte each time, as a display's unused receive
            # side does, into the word the loop reads.
            cpu = self.machine(["ldw .D1T1 *+a5(0),b0"])
            cpu.set_register("a5", 0x4000)
            cpu.write(0x4100, b"AAAA"); cpu.write(0x4000, b"A")
            self.spi_loopback(cpu, [0x00012000, 0x01f0e040, 0x00040001, 0x4000, 0, 0xffff, 0, 1])
            return cpu
        reference, _ = self.observe(prepare, [4000, 4001, 4013], False)
        forward, stats = self.observe(prepare, [4000, 4001, 4013], True)
        self.assertEqual(forward, reference)
        self.assertEqual((stats["events_run_ahead"], stats["events_held_back"]), (4, 0))

    def test_device_write_into_loop_memory_arrives_at_its_own_cycle(self):
        def prepare():
            # SPI1 in loopback shifts four bytes out by DMA; receive DMA stores each byte at
            # 0x4000. The loop loads that word every iteration and counts the iterations in
            # which it is nonzero, so its final count records when the first byte arrived.
            cpu = self.machine(["ldw .D1T1 *+a5(0),b0", "[b0] add .L1 1,a8,a8"])
            cpu.set_register("a5", 0x4000)
            cpu.write(0x4100, b"DMA!")
            self.spi_loopback(cpu, [0x00012000, 0x01f0e040, 0x00040001, 0x4000, 0, 0xffff, 0, 1])
            return cpu
        # One long run lets events run ahead; the reference executes the same cycles in order.
        reference, _ = self.observe(prepare, [4000, 4001, 4013], False)
        self.assertEqual(reference[0][1][:4], b"!\0\0\0")
        self.assertGreater(reference[0][0]["registers"]["a8"], 100)
        forward, stats = self.observe(prepare, [4000, 4001, 4013], True)
        self.assertEqual(forward, reference)
        self.assertGreater(stats["skipped_cycles"], 100)
        self.assertGreater(stats["events_held_back"], 0)


if __name__ == "__main__":
    unittest.main()
