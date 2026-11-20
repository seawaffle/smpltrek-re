"""USB0 disconnected control-plane checks derived from SPRUH79C register behavior."""
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from build import WORK
from cpu import CPU, CoreFault
from ir import Instruction, instruction

BASE, PHY = 0x01e00000, 0x01c14184


@unittest.skipUnless(shutil.which("g++"), "host g++ required")
class UsbDisconnected(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        WORK.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(dir=WORK, prefix="test-usb-")
        cls.work = Path(cls.temporary.name)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def machine(self, texts=None):
        cpu = CPU(self.work, decode=False)
        cpu.enable_board()
        cpu.map(0xc2100000, 4096, 7)
        for i, text in enumerate(texts or ("b .S1 c2100000", "nop 5")):
            pc = 0xc2100000 + i * 4
            cpu.install(pc, pc + 4, False, pc & ~31, 32, (Instruction * 1)(instruction(pc, text)))
        cpu.reset(0xc2100000, return_address=None)
        return cpu

    @staticmethod
    def get(cpu, address, size=4):
        return int.from_bytes(cpu.read(address, size), "little")

    @staticmethod
    def put(cpu, address, value, size=4):
        cpu.write(address, value.to_bytes(size, "little"))

    def enable_clock(self, cpu):
        self.put(cpu, 0x01e27a04, 3)
        self.put(cpu, 0x01e27120, 1)
        cpu.run(16)

    def reserved_machine(self, address=BASE + 0x80c, opcode="ldw", clocked=True):
        texts = ["nop 8"] * 16 + [f"{opcode} .D1T1 *a4,a5", "ldw .D1T1 *a6,a7",
                                          "nop 4", "b .S1 c210004c", "nop 5"]
        cpu = self.machine(texts)
        cpu.set_register("a4", address)
        cpu.set_register("a6", BASE + 0x84c)
        if clocked:
            self.enable_clock(cpu)
            self.put(cpu, PHY, 0x972)
        cpu.run(64)
        return cpu

    def test_reserved_status_words_read_zero_as_on_the_unit_and_are_logged(self):
        # M1 bench I5: with USB0 clocked and the PHY ready, LDW at 0x01e0080c and 0x01e0084c returned 0 with
        # no exception and no event flag, so the interrupt controller needs no guard afterwards.
        traces = []
        for sliced in (False, True):
            with self.reserved_machine() as cpu:
                for _ in range(220 if sliced else 1):
                    cpu.run(1 if sliced else 220)
                state = cpu.usb_reserved_status_state()
                self.assertTrue(state["hardware_response_verified"])
                self.assertEqual(state["count"], 2)
                self.assertEqual(state["reads"], [dict(cycles=128 + i, pc=0xc2100040 + i * 4,
                                                      address=BASE + off, size=4, assumed_value=0)
                                                for i, off in enumerate((0x80c, 0x84c))])
                traces.append(state)
                self.assertEqual(cpu.state()["registers"]["a5"], 0)
                self.assertEqual(cpu.state()["registers"]["a7"], 0)
                with self.assertRaisesRegex(ValueError, "CPU reads only"):
                    self.get(cpu, BASE + 0x80c)
                with self.assertRaisesRegex(ValueError, "unimplemented USB0"):
                    self.put(cpu, BASE + 0x80c, 0)
                self.get(cpu, 0x0180000c)
        self.assertEqual(traces[0], traces[1])

    def test_reserved_status_words_cover_nothing_that_was_not_measured(self):
        for address, opcode, clocked, error in ((BASE + 0x810, "ldw", True, "unimplemented USB0"),
                                                (BASE + 0x80c, "ldbu", True, "CPU reads only"),
                                                (BASE + 0x80c, "ldw", False, "clocked")):
            with self.subTest(address=address, opcode=opcode, clocked=clocked), self.reserved_machine(address, opcode, clocked) as cpu:
                with self.assertRaisesRegex(CoreFault, error):
                    cpu.run(100)
                self.assertEqual(cpu.usb_reserved_status_state()["count"], 0)

    def test_reserved_disable_words_ignore_stores_of_zero_only(self):
        # M1 bench I5 on the unit: STW 0 to 0x01e00808 and 0x01e00848 changed nothing and both read back 0.
        # A read of those two words and a non-zero store were not measured and stay refused.
        def machine(value, address=BASE + 0x808):
            cpu = self.machine(["nop 8"] * 16 + ["stw .D1T1 a5,*a4", "stw .D1T1 a5,*a6", "nop 4", "b .S1 c210004c", "nop 5"])
            for name, number in (("a4", address), ("a6", BASE + 0x848), ("a5", value)):
                cpu.set_register(name, number)
            self.enable_clock(cpu)
            self.put(cpu, PHY, 0x972)
            cpu.run(64)
            return cpu
        with machine(0) as cpu:
            cpu.run(220)
            self.assertEqual([(row["pc"], row["address"], row["assumed_value"]) for row in cpu.usb_reserved_status_state()["reads"]],
                             [(0xc2100040, BASE + 0x808, 0), (0xc2100044, BASE + 0x848, 0)])
            with self.assertRaisesRegex(ValueError, "unimplemented USB0"):
                self.get(cpu, BASE + 0x808)
        for value, address, error in ((1, BASE + 0x808, "stores of 0 only"), (0, BASE + 0x80c, "unimplemented USB0")):
            with self.subTest(value=value, address=hex(address)), machine(value, address) as cpu:
                with self.assertRaisesRegex(CoreFault, error):
                    cpu.run(220)
                self.assertEqual(cpu.usb_reserved_status_state()["count"], 0)
                # A refused store to a disable word is not left in the device trace as if it had happened.
                self.assertFalse([row for row in cpu.mmio_trace() if row["address"] == BASE + 0x808 and row["write"]])

    def test_reserved_status_words_reject_dma_and_keep_counting_past_the_trace(self):
        with self.reserved_machine() as cpu:
            self.put(cpu, 0x01c10a00, 3)
            self.put(cpu, 0x01c10120, 1)
            cpu.run(16)
            for i, value in enumerate((0, BASE + 0x80c, 0x00010004, 0xc2100800, 0, 0xffff, 0, 1)):
                self.put(cpu, 0x01c04040 + i * 4, value)
            self.put(cpu, 0x01c01010, 1 << 2)
            with self.assertRaisesRegex(CoreFault, "CPU reads only"):
                cpu.run(1)
            self.assertEqual(cpu.usb_reserved_status_state()["count"], 0)
        texts = ["nop 8"] * 16 + ["ldw .D1T1 *a4,a5", "b .S1 c2100040", "nop 5"]
        with self.machine(texts) as cpu:
            cpu.set_register("a4", BASE + 0x80c)
            self.enable_clock(cpu)
            self.put(cpu, PHY, 0x972)
            cpu.run(40000)
            state = cpu.usb_reserved_status_state()
            self.assertGreater(state["count"], 4096)
            self.assertEqual(len(state["reads"]), 4096)

    def test_revision_clocked_reset_and_reset_register_values(self):
        with self.machine() as cpu:
            self.assertEqual(self.get(cpu, BASE), 0x4ea10800)
            self.assertEqual(self.get(cpu, BASE + 4), 0)
            self.assertEqual(self.get(cpu, BASE + 0x406, 2), 1)
            with self.assertRaisesRegex(ValueError, "PSC clock"):
                self.put(cpu, BASE + 4, 1)
            self.assertEqual(self.get(cpu, BASE + 4), 0)
            self.enable_clock(cpu)
            self.put(cpu, BASE + 0x401, 0x40, 1)
            self.put(cpu, BASE + 0x30, 0xffffffff)
            self.put(cpu, BASE + 4, 1)
            cpu.run(15)
            self.assertEqual(self.get(cpu, BASE + 4), 1)
            cpu.run(1)
            self.assertEqual(self.get(cpu, BASE + 4), 0)
            self.assertEqual(self.get(cpu, BASE + 0x401, 1), 0)
            self.assertEqual(self.get(cpu, BASE + 0x2c), 0)
            self.assertEqual(cpu.usb_state()["soft_resets"], 1)

    def test_phy_status_is_read_only_and_powerdown_cancels_settling(self):
        with self.machine() as cpu:
            self.put(cpu, PHY, 0x00030972)  # Cannot force CLKGood or VBUSSense by a write.
            self.assertEqual(self.get(cpu, PHY), 0x972)
            cpu.run(63)
            self.assertEqual(self.get(cpu, PHY), 0x972)
            cpu.run(1)
            self.assertEqual(self.get(cpu, PHY), 0x20972)
            self.put(cpu, PHY, 0xd72)  # PHYPWDN
            self.assertEqual(self.get(cpu, PHY), 0xd72)
            self.put(cpu, PHY, 0x972)
            cpu.run(32)
            self.put(cpu, PHY, 0x8d72)  # Reset and powerdown cancel a pending lock.
            cpu.run(100)
            self.assertFalse(self.get(cpu, PHY) & (1 << 17))
            with self.assertRaisesRegex(ValueError, "24 MHz"):
                self.put(cpu, PHY, 0x971)

    def test_wrapper_interrupt_set_clear_masks_and_eoi_rearm(self):
        with self.machine() as cpu:
            self.enable_clock(cpu)
            self.put(cpu, 0x0180010c, 0x0f0e0d13)  # CPU int12 receives USB0 event19.
            bit = 1 << 18
            self.put(cpu, BASE + 0x24, bit)
            self.assertEqual(cpu.usb_state()["interrupts"], 0)
            self.assertEqual(self.get(cpu, BASE + 0x28), bit)  # Clear alias reads raw source, no read clear.
            self.put(cpu, BASE + 0x30, bit)
            self.assertEqual(self.get(cpu, BASE + 0x38), bit)
            self.assertEqual(self.get(cpu, 0x01800000) & (1 << 19), 1 << 19)
            self.assertEqual(cpu.usb_state()["interrupts"], 1)
            self.put(cpu, 0x01800040, 1 << 19)
            self.put(cpu, BASE + 0x3c, 0)
            self.assertEqual(cpu.usb_state()["interrupts"], 2)
            self.assertEqual(self.get(cpu, 0x01800000) & (1 << 19), 1 << 19)
            self.put(cpu, BASE + 0x28, bit)
            self.put(cpu, BASE + 0x3c, 0)
            self.assertEqual(self.get(cpu, BASE + 0x20), 0)
            self.assertEqual(cpu.usb_state()["interrupts"], 2)
            self.put(cpu, BASE + 0x34, bit)
            self.assertEqual(self.get(cpu, BASE + 0x30), 0)

    def test_soft_attach_without_host_has_no_sof_session_or_data_and_unknown_modes_fault(self):
        with self.machine() as cpu:
            self.enable_clock(cpu)
            self.put(cpu, PHY, 0x972)
            self.put(cpu, BASE + 0x406, 0xffff, 2)
            self.put(cpu, BASE + 0x408, 0xffff, 2)
            self.put(cpu, BASE + 0x40b, 0x2f, 1)
            self.put(cpu, BASE + 0x401, 0x40, 1)
            cpu.run(100000)
            self.assertEqual(self.get(cpu, BASE + 0x406, 2), 0x1f)
            self.assertEqual(self.get(cpu, BASE + 0x408, 2), 0x1e)
            self.assertEqual(self.get(cpu, BASE + 0x40a, 1), 0)
            self.assertEqual(self.get(cpu, BASE + 0x40c, 2), 0)
            self.assertEqual(self.get(cpu, BASE + 0x460, 1), 0x80)
            self.assertEqual(cpu.usb_state()["interrupts"], 0)
            self.assertEqual(cpu.usb_state()["soft_connect"], 1)
            for offset in (0x410, 0x420, 0x80c, 0x84c, 0x1000):  # host reads: the two reserved words answer the CPU only
                with self.assertRaisesRegex(ValueError, "unimplemented USB0|CPU reads only"):
                    self.get(cpu, BASE + offset)
            for offset, value, size in ((4, 0x10, 4), (0x460, 1, 1), (0x40f, 1, 1), (0x401, 4, 1)):
                with self.assertRaises(ValueError):
                    self.put(cpu, BASE + offset, value, size)

    def test_dma_setup_registers_hold_documented_fields_and_everything_else_still_faults(self):
        # The values are the ones the stock card-reader set-up writes (seen on a study run).
        held = ((0x10, 0xffffffff, 0x33333333), (0x10, 0x3, 0x3), (0x50, 0x1000, 0x1000), (0x5c, 0xffffffff, 0x1ffff),
                (0x2000, 0x80000007, 0x80000007), (0x2000, 0xffffffff, 0x800000ff),
                (0x4080, 0xc14d3340, 0xc14d3340), (0x4084, 0x1000, 0x1000), (0x4084, 0xffffffff, 0x3fff), (0x4088, 0, 0),
                (0x5000, 0xc1319ec0, 0xc1319ec0), (0x5004, 0x103, 0x103), (0x50f4, 0xffffffff, 0x3fff0f07))
        written = ((0x1800, 0x80000018), (0x1828, 0x8100401b), (0x182c, 0x00010001), (0x1830, 0x00010001),
                   (0x1868, 0x80000000), (0x2800, 0x03020100), (0x2804, 0x83828180), (0x28fc, 0))
        with self.machine() as cpu:
            self.enable_clock(cpu)
            for offset, value, expected in held:
                with self.subTest(offset=hex(offset), value=hex(value)):
                    self.put(cpu, BASE + offset, value)
                    self.assertEqual(self.get(cpu, BASE + offset), expected)
            for offset, value in written:                 # write-only fields: accepted, no read value documented
                with self.subTest(offset=hex(offset)):
                    self.put(cpu, BASE + offset, value)
                    with self.assertRaisesRegex(ValueError, "unimplemented USB0"):
                        self.get(cpu, BASE + offset)
            self.assertEqual(self.get(cpu, BASE + 0x50), 0x1000)   # neighbours did not disturb it
            for offset in (0x1800, 0x1828):
                with self.assertRaisesRegex(ValueError, "teardown"):
                    self.put(cpu, BASE + offset, 0xc0000000)
            # Still outside the model: AUTOREQ, TEARDOWN, the DMA and queue-manager revision/teardown/pending
            # registers, the gaps inside a channel block, every queue register, and partial-width accesses.
            for offset in (0x14, 0x1c, 0x60, 0x1000, 0x1004, 0x1804, 0x1814, 0x1880, 0x2004, 0x2900, 0x4000, 0x4090,
                           0x5008, 0x5100, 0x600c, 0x6800):
                with self.subTest(offset=hex(offset)):
                    with self.assertRaisesRegex(ValueError, "unimplemented USB0"):
                        self.get(cpu, BASE + offset)
                    with self.assertRaisesRegex(ValueError, "unimplemented USB0"):
                        self.put(cpu, BASE + offset, 0)
            for offset in (0x10, 0x2000, 0x4080):
                with self.assertRaisesRegex(ValueError, "unimplemented USB0"):
                    self.get(cpu, BASE + offset, 2)
                with self.assertRaisesRegex(ValueError, "unimplemented USB0"):
                    self.put(cpu, BASE + offset, 1, 1)
            self.assertEqual(cpu.usb_state()["interrupts"], 0)
            self.put(cpu, BASE + 4, 1)                    # a controller reset returns them to zero
            cpu.run(32)
            for offset in (0x10, 0x50, 0x2000, 0x4080, 0x4084, 0x5000, 0x5004):
                self.assertEqual(self.get(cpu, BASE + offset), 0, hex(offset))


if __name__ == "__main__":
    unittest.main()
