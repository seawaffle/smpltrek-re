"""USB0 checks derived from SPRUH79C register behavior: the control plane with no cable, then the MUSB core in
peripheral mode and the TI wrapper's interrupts against the scripted host, at full and high speed (the test plays the firmware)."""
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
            # INTRTXE, INTRRXE, INTRUSBE at SPRUH79C's reset values (33.4.25, 33.4.26, 33.4.28)
            self.assertEqual((self.get(cpu, BASE + 0x406, 2), self.get(cpu, BASE + 0x408, 2), self.get(cpu, BASE + 0x40b, 1)),
                             (0x1f, 0x1e, 0x06))
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
            self.assertEqual(self.get(cpu, BASE + 0x401, 1), 0x20)       # HSENAB, as the core comes out of reset
            self.assertEqual((self.get(cpu, BASE + 0x406, 2), self.get(cpu, BASE + 0x408, 2), self.get(cpu, BASE + 0x40b, 1)),
                             (0x1f, 0x1e, 0x06))                          # and the enables, after the soft reset too
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
            self.assertEqual(self.get(cpu, BASE + 0x410), 0)       # indexed endpoint 0: nothing received
            self.assertEqual(cpu.usb_state()["port"], "detached")
            for offset in (0x46c, 0x480, 0x80c, 0x84c, 0x1000):  # host reads: the two reserved words answer the CPU only
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


FRAME, BIT = 372000, 31
DEBOUNCE, RESET, RECOVERY = 100 * FRAME, 10 * FRAME, 10 * FRAME
EP0, RESUME_IRQ, RESET_IRQ, SOF_IRQ = 1, 1 << 17, 1 << 18, 1 << 19


@unittest.skipUnless(shutil.which("g++"), "host g++ required")
class UsbHost(unittest.TestCase):
    """The test is the firmware: it programs USB0 through the bus and answers the scripted host."""
    setUpClass = classmethod(UsbDisconnected.setUpClass.__func__)
    tearDownClass = classmethod(UsbDisconnected.tearDownClass.__func__)
    machine, enable_clock = UsbDisconnected.machine, UsbDisconnected.enable_clock
    get, put = staticmethod(UsbDisconnected.get), staticmethod(UsbDisconnected.put)

    def device(self, uint=False, connect=True, sof=False):
        cpu = self.machine()
        self.enable_clock(cpu)
        self.put(cpu, PHY, 0x972)
        cpu.run(64)
        self.put(cpu, BASE + 4, 8 if uint else 0)
        self.put(cpu, BASE + 0x30, 0x01ff1e1f)
        self.put(cpu, BASE + 0x406, 0x1f, 2)
        self.put(cpu, BASE + 0x408, 0x1e, 2)
        self.put(cpu, BASE + 0x40b, 0xff, 1)
        if connect:
            self.put(cpu, BASE + 0x401, 0x40, 1)
        cpu.usb_sof(sof)   # most tests keep SOF interrupts out of the way: the idle bus suspends, the first packet resumes
        return cpu

    def plugged(self, **options):
        """A device on an enabled port at the cycle the first transfer may start, interrupts acknowledged."""
        cpu = self.device(**options)
        cpu.usb_attach()
        cpu.run(DEBOUNCE + RESET + RECOVERY)
        self.assertEqual(cpu.usb_state()["port"], "enabled")
        self.acknowledge(cpu)
        return cpu

    def acknowledge(self, cpu):
        status = self.get(cpu, BASE + 0x20)
        self.put(cpu, BASE + 0x28, status)
        self.put(cpu, BASE + 0x3c, 0)
        return status

    def until(self, cpu, bit, milliseconds=20):
        """Run until INTSRCR shows `bit`, then acknowledge everything pending."""
        for _ in range(milliseconds * FRAME // 1000):
            if self.get(cpu, BASE + 0x20) & bit:
                return self.acknowledge(cpu)
            cpu.run(1000)
        self.fail(f"no USB interrupt source {bit:#x} within {milliseconds} ms")

    def finished(self, cpu, transfer, milliseconds=20):
        for _ in range(milliseconds * FRAME // 1000):
            result = cpu.usb_result(transfer)
            if result["status"] != "pending":
                return result
            cpu.run(1000)
        self.fail(f"USB transfer still pending after {milliseconds} ms")

    def unload(self, cpu, endpoint, widths):
        return b"".join(cpu.read(BASE + 0x420 + 4 * endpoint, width) for width in widths)

    def load(self, cpu, endpoint, data, widths):
        at = 0
        for width in widths:
            cpu.write(BASE + 0x420 + 4 * endpoint, data[at:at + width]); at += width
        self.assertEqual(at, len(data))

    def configure(self, cpu, endpoint, rx=None, tx=None):
        """Dynamic FIFO placement and packet size through the index register: (FIFOSZ, address / 8, MAXP)."""
        self.put(cpu, BASE + 0x40e, endpoint, 1)
        if rx:
            self.put(cpu, BASE + 0x463, rx[0], 1)
            self.put(cpu, BASE + 0x466, rx[1], 2)
            self.put(cpu, BASE + 0x414, rx[2], 2)
            self.put(cpu, BASE + 0x416, 0x80, 1)                          # CLRDATATOG
        if tx:
            self.put(cpu, BASE + 0x462, tx[0], 1)
            self.put(cpu, BASE + 0x464, tx[1], 2)
            self.put(cpu, BASE + 0x410, tx[2], 2)
            self.put(cpu, BASE + 0x412, 0x40, 1)                          # CLRDATATOG
        self.put(cpu, BASE + 0x40e, 0, 1)

    def test_hsenab_is_set_at_reset_and_decides_the_speed_at_each_bus_reset(self):
        with self.device(connect=False) as cpu:
            self.assertEqual(self.get(cpu, BASE + 0x401, 1), 0x20)
            cpu.usb_attach()
            self.put(cpu, BASE + 0x401, 0x60, 1)                          # SOFTCONN ORed in: HSENAB stays on
            cpu.run(DEBOUNCE)
            self.assertEqual(self.get(cpu, BASE + 0x401, 1), 0x78)       # the chirp: HSMODE from the reset on
            cpu.run(RESET)
            state = cpu.usb_state()
            self.assertEqual((self.get(cpu, BASE + 0x401, 1), state["speed"], state["high_speed_resets"]), (0x70, "high", 1))
            self.put(cpu, BASE + 0x401, 0x40, 1)                          # HSENAB off: the speed holds until a reset
            self.assertEqual(self.get(cpu, BASE + 0x401, 1), 0x50)
            cpu.usb_reset()
            cpu.run(RESET)
            state = cpu.usb_state()
            self.assertEqual((self.get(cpu, BASE + 0x401, 1), state["speed"], state["high_speed_resets"]), (0x40, "full", 1))
            self.put(cpu, BASE + 0x401, 0x60, 1)
            cpu.usb_reset()
            cpu.run(RESET)
            self.assertEqual((self.get(cpu, BASE + 0x401, 1), cpu.usb_state()["high_speed_resets"]), (0x70, 2))
            cpu.usb_detach()                                              # the port goes down: HSMODE clears
            self.assertEqual((self.get(cpu, BASE + 0x401, 1), cpu.usb_state()["speed"]), (0x60, "full"))

    def test_attach_waits_for_the_pull_up_then_debounces_resets_and_sends_sof(self):
        with self.device(connect=False, sof=True) as cpu:
            self.assertEqual(self.get(cpu, BASE + 0x460, 1), 0x80)
            cpu.usb_attach()
            self.assertEqual(self.get(cpu, BASE + 0x460, 1), 0x99)       # B device, VBUS valid, session
            self.assertEqual(self.get(cpu, PHY), 0x30972)                 # USB0VBUSSENSE
            cpu.run(2 * DEBOUNCE)
            self.assertEqual(cpu.usb_state()["port"], "powered")          # no pull-up: the host sees no device
            transfer = cpu.usb_control((0x80, 6, 0x0100, 0), 8, wait=False, timeout_ms=500)   # waits for the port
            self.put(cpu, BASE + 0x400, 5, 1)
            self.put(cpu, BASE + 0x40e, 3, 1)
            self.put(cpu, BASE + 0x401, 0x40, 1)                          # SOFTCONN
            start = cpu.cycles()
            self.assertEqual(cpu.usb_state()["port"], "debounce")
            cpu.run(DEBOUNCE - 1)
            self.assertEqual((cpu.usb_state()["port"], self.get(cpu, BASE + 0x20)), ("debounce", 0))
            cpu.run(1)
            self.assertEqual((cpu.usb_state()["port"], self.get(cpu, BASE + 0x20)), ("reset", RESET_IRQ))
            self.assertEqual(self.get(cpu, BASE + 0x401, 1), 0x48)       # POWER.RESET while the bus is in reset
            self.assertEqual((self.get(cpu, BASE + 0x400, 1), self.get(cpu, BASE + 0x40e, 1)), (0, 0))
            self.assertEqual(self.get(cpu, 0x01800000) & (1 << 19), 1 << 19)   # event 19
            self.acknowledge(cpu)
            cpu.run(RESET)
            self.assertEqual((cpu.usb_state()["port"], self.get(cpu, BASE + 0x401, 1)), ("enabled", 0x40))
            cpu.run(FRAME - 1)
            self.assertEqual(self.get(cpu, BASE + 0x20), 0)
            cpu.run(1)
            self.assertEqual((self.get(cpu, BASE + 0x20), self.get(cpu, BASE + 0x40c, 2)), (SOF_IRQ, 1))
            cpu.run(5 * FRAME)
            self.assertEqual((self.get(cpu, BASE + 0x40c, 2), cpu.usb_state()["sofs"]), (6, 6))
            # The queued transfer starts 10 ms after the reset: its SETUP transaction is 161 bit times long.
            cpu.run(RECOVERY - 6 * FRAME + 161 * BIT - 1)
            self.assertFalse(self.acknowledge(cpu) & EP0)
            cpu.run(1)
            self.assertTrue(self.get(cpu, BASE + 0x20) & EP0)
            self.assertEqual(cpu.cycles(), start + DEBOUNCE + RESET + RECOVERY + 161 * BIT)
            self.acknowledge(cpu)
            cpu.usb_detach()
            self.assertEqual(self.get(cpu, BASE + 0x20), 1 << 21)        # DISCON: the session ended
            self.assertEqual((self.get(cpu, BASE + 0x460, 1), self.get(cpu, PHY)), (0x80, 0x20972))
            self.assertEqual(cpu.usb_result(transfer)["status"], "disconnected")
            state = cpu.usb_state()
            self.assertEqual((state["port"], state["cable_connected"], state["bus_resets"]), ("detached", False, 1))

    def test_control_read_in_three_packets_through_every_fifo_width_and_both_register_maps(self):
        descriptor = bytes(range(0x40, 0x52))
        with self.plugged() as cpu:
            transfer = cpu.usb_control((0x80, 6, 0x0100, 0), 18, wait=False, max_packet=8)
            self.until(cpu, EP0)
            self.put(cpu, BASE + 0x40e, 0, 1)
            self.assertEqual((self.get(cpu, BASE + 0x412, 2), self.get(cpu, BASE + 0x418, 2)), (1, 8))   # RXPKTRDY, COUNT0
            self.assertEqual(self.get(cpu, BASE + 0x41f, 1), 0x06)       # CONFIGDATA: dynamic FIFOs, soft connect
            setup = self.unload(cpu, 0, (4, 2, 1, 1))
            self.assertEqual(setup, bytes([0x80, 6, 0, 1, 0, 0, 18, 0]))
            self.assertEqual(self.get(cpu, BASE + 0x508, 2), 0)
            cpu.run(3 * FRAME)                                            # IN tokens are NAKed until the firmware answers
            self.assertAlmostEqual(cpu.usb_result(transfer)["naks"], 3 * FRAME // (62 * BIT), delta=3)
            self.put(cpu, BASE + 0x502, 0x40, 1)                          # SERV_RXPKTRDY
            self.assertEqual(self.get(cpu, BASE + 0x502, 2), 0)
            for at, widths in ((0, (4, 4)), (8, (2, 2, 2, 1, 1))):
                self.load(cpu, 0, descriptor[at:at + 8], widths)
                self.put(cpu, BASE + 0x502, 0x02, 1)                      # TXPKTRDY
                self.assertEqual(self.get(cpu, BASE + 0x502, 1), 0x02)
                self.put(cpu, BASE + 0x502, 0x02, 1)                      # read back and rewritten: still that one packet
                self.until(cpu, EP0)
                self.assertEqual(self.get(cpu, BASE + 0x502, 1), 0)      # sent
            self.load(cpu, 0, descriptor[16:], (1, 1))
            self.put(cpu, BASE + 0x412, 0x0a, 1)                          # TXPKTRDY | DATAEND
            self.until(cpu, EP0)
            self.assertEqual(self.get(cpu, BASE + 0x502, 1), 0x08)       # DATAEND until the status stage
            self.until(cpu, EP0)                                          # the status stage
            self.assertEqual(self.get(cpu, BASE + 0x502, 1), 0)
            result = self.finished(cpu, transfer)
            self.assertEqual((result["status"], result["data"]), ("ok", descriptor))
            state = cpu.usb_state()
            self.assertEqual((state["stalls"], state["errors"], state["fifo_overflows"], state["fifo_underflows"]), (0, 0, 0, 0))
            self.assertEqual(self.unload(cpu, 0, (1,)), b"\0")            # nothing to unload: counted
            self.assertEqual(cpu.usb_state()["fifo_underflows"], 1)

    def test_set_address_takes_effect_after_the_status_stage_whenever_faddr_is_written(self):
        for early in (True, False):
            with self.subTest(early=early), self.plugged() as cpu:
                transfer = cpu.usb_control((0x00, 5, 9, 0), wait=False)
                self.until(cpu, EP0)
                self.assertEqual(self.unload(cpu, 0, (4, 4)), bytes([0, 5, 9, 0, 0, 0, 0, 0]))
                if early:
                    self.put(cpu, BASE + 0x400, 9, 1)                     # written before the status stage
                    self.assertEqual((self.get(cpu, BASE + 0x400, 1), cpu.usb_state()["device_address"]), (9, 0))
                cpu.run(FRAME)
                self.assertEqual(cpu.usb_result(transfer)["status"], "pending")   # status stage NAKed until DATAEND
                self.put(cpu, BASE + 0x502, 0x48, 1)                      # SERV_RXPKTRDY | DATAEND
                self.until(cpu, EP0)                                      # the status stage
                if not early:
                    self.assertEqual(cpu.usb_state()["device_address"], 0)
                    self.put(cpu, BASE + 0x400, 9, 1)                     # as SPRUH79C says: after that interrupt
                self.assertEqual(self.finished(cpu, transfer)["status"], "ok")
                state = cpu.usb_state()
                self.assertEqual((state["address"], state["device_address"]), (9, 9))
                second = cpu.usb_control((0x80, 0, 0, 0), 2, wait=False)   # addressed to 9, after 2 ms of recovery
                self.until(cpu, EP0)
                self.assertGreater(cpu.cycles() - cpu.usb_result(second)["submitted"], FRAME)
                self.put(cpu, BASE + 0x400, 3, 1)                         # a wrong address, written in mid-transfer...
                self.unload(cpu, 0, (4, 4))
                self.put(cpu, BASE + 0x502, 0x40, 1)
                self.load(cpu, 0, b"\1\0", (2,))
                self.put(cpu, BASE + 0x502, 0x0a, 1)
                self.assertEqual(self.finished(cpu, second)["status"], "ok")   # ...is used from the end of this transfer
                self.assertEqual(cpu.usb_state()["device_address"], 3)
                third = cpu.usb_control((0x80, 0, 0, 0), 2, wait=False)
                self.assertEqual(self.finished(cpu, third)["status"], "error")   # nothing answers at address 9
                self.assertEqual(cpu.usb_state()["errors"], 1)

    def test_control_write_stall_and_setup_end(self):
        with self.plugged() as cpu:
            payload = bytes(range(70))
            transfer = cpu.usb_control((0x21, 9, 0x0200, 0), payload, wait=False)
            self.until(cpu, EP0)
            self.unload(cpu, 0, (4, 4))
            self.put(cpu, BASE + 0x502, 0x40, 1)
            self.until(cpu, EP0)
            self.assertEqual((self.get(cpu, BASE + 0x502, 1), self.get(cpu, BASE + 0x508, 1)), (1, 64))
            first = self.unload(cpu, 0, (4,) * 16)
            cpu.run(FRAME)                                                # the second packet is NAKed meanwhile
            self.put(cpu, BASE + 0x502, 0x40, 1)
            self.until(cpu, EP0)
            self.assertEqual(self.get(cpu, BASE + 0x508, 1), 6)
            self.assertEqual(first + self.unload(cpu, 0, (4, 2)), payload)
            self.put(cpu, BASE + 0x502, 0x48, 1)                          # last packet: SERV_RXPKTRDY | DATAEND
            self.until(cpu, EP0)                                          # status stage
            result = self.finished(cpu, transfer)
            self.assertEqual((result["status"], result["sent"]), ("ok", 70))
            self.assertAlmostEqual(result["naks"], FRAME // (149 * BIT), delta=3)   # a 6-byte OUT retry is 149 bit times

            transfer = cpu.usb_control((0x80, 6, 0x0f00, 0), 8, wait=False)   # a request the firmware refuses
            self.until(cpu, EP0)
            self.unload(cpu, 0, (4, 4))
            self.put(cpu, BASE + 0x502, 0x60, 1)                          # SERV_RXPKTRDY | SENDSTALL
            self.until(cpu, EP0)
            self.assertEqual(self.get(cpu, BASE + 0x502, 1), 0x04)       # SENTSTALL
            self.put(cpu, BASE + 0x502, 0, 1)
            self.assertEqual(self.get(cpu, BASE + 0x502, 1), 0)
            self.assertEqual(self.finished(cpu, transfer)["status"], "stall")

            abandoned = cpu.usb_control((0x80, 6, 0x0100, 0), 18, wait=False, timeout_ms=5)   # never answered
            self.until(cpu, EP0)
            self.unload(cpu, 0, (4, 4))
            self.put(cpu, BASE + 0x502, 0x40, 1)
            self.load(cpu, 0, bytes(8), (4, 4))                           # a packet left in the FIFO, never made ready
            result = self.finished(cpu, abandoned)
            self.assertEqual(result["status"], "timeout")
            self.assertAlmostEqual(result["naks"], 5 * FRAME // (62 * BIT), delta=5)   # an IN retry is 62 bit times
            transfer = cpu.usb_control((0x80, 0, 0, 0), 2, wait=False)   # the next SETUP ends the abandoned transfer
            self.until(cpu, EP0)
            self.assertEqual(self.get(cpu, BASE + 0x502, 1), 0x11)       # SETUPEND | RXPKTRDY
            self.put(cpu, BASE + 0x502, 0x80, 1)                          # SERV_SETUPEND
            self.assertEqual(self.get(cpu, BASE + 0x502, 1), 0x01)
            self.assertEqual(self.unload(cpu, 0, (4, 4)), bytes([0x80, 0, 0, 0, 0, 0, 2, 0]))
            self.put(cpu, BASE + 0x502, 0x40, 1)
            self.load(cpu, 0, b"\1\0", (1, 1))
            self.put(cpu, BASE + 0x502, 0x0a, 1)
            result = self.finished(cpu, transfer)
            self.assertEqual((result["status"], result["data"]), ("ok", b"\1\0"))
            self.assertEqual(cpu.usb_state()["stalls"], 1)

    def test_bulk_out_naks_until_unloaded_double_buffers_and_checks_the_data_toggle(self):
        RX1 = 1 << 9
        with self.plugged() as cpu:
            self.configure(cpu, 1, rx=(3, 8, 64))
            state = cpu.usb_state()["endpoints"][0]
            self.assertEqual((state["rx_max_packet"], state["rx_fifo"]), (64, dict(address=64, packet=64, packets=1)))
            data = bytes(range(100))
            transfer = cpu.usb_out(1, data, wait=False)
            self.until(cpu, RX1)
            self.assertEqual((self.get(cpu, BASE + 0x516, 2), self.get(cpu, BASE + 0x518, 2)), (0x03, 64))   # RXPKTRDY, FIFOFULL
            first = self.unload(cpu, 1, (4,) * 15 + (2, 1))
            self.assertEqual(self.get(cpu, BASE + 0x518, 2), 1)
            first += self.unload(cpu, 1, (1,))
            cpu.run(2 * FRAME)
            pending = cpu.usb_result(transfer)
            self.assertEqual((pending["status"], pending["sent"]), ("pending", 64))
            # The second packet (36 bytes: 385 bit times with its token and handshake, then a 4-bit gap) is retried.
            self.assertAlmostEqual(pending["naks"], 2 * FRAME // (389 * BIT), delta=3)
            self.assertFalse(self.get(cpu, BASE + 0x20) & RX1)
            self.put(cpu, BASE + 0x516, 0, 1)                             # RXPKTRDY cleared
            self.until(cpu, RX1)
            self.assertEqual(self.get(cpu, BASE + 0x518, 2), 36)
            self.assertEqual(first + self.unload(cpu, 1, (4,) * 9), data)
            self.put(cpu, BASE + 0x516, 0, 1)
            result = self.finished(cpu, transfer)
            self.assertEqual((result["status"], result["sent"]), ("ok", 100))

            # CLRDATATOG in mid-stream: the device expects DATA0, the host's next packet is DATA1 and is
            # acknowledged but dropped as a repeat.
            self.finished(cpu, cpu.usb_out(1, b"abc", wait=False))
            self.until(cpu, RX1)
            self.put(cpu, BASE + 0x516, 0x80, 1)                          # clears RXPKTRDY too
            self.assertEqual(self.finished(cpu, cpu.usb_out(1, b"lost", wait=False))["status"], "ok")
            cpu.run(FRAME)
            self.assertEqual((self.get(cpu, BASE + 0x516, 1), cpu.usb_state()["toggle_errors"]), (0, 1))

            self.configure(cpu, 1, rx=(0x13, 8, 64))                       # double packet buffering: 2 x 64 bytes
            cpu.usb_reset(); cpu.run(RESET + RECOVERY); self.acknowledge(cpu)   # both ends start from DATA0 again
            data = bytes(range(128, 256))
            result = self.finished(cpu, cpu.usb_out(1, data, wait=False))
            self.assertEqual((result["status"], result["naks"]), ("ok", 0))   # both packets fit
            self.assertTrue(self.acknowledge(cpu) & RX1)
            self.assertEqual(self.get(cpu, BASE + 0x516, 1), 0x03)
            got = self.unload(cpu, 1, (4,) * 16)
            self.put(cpu, BASE + 0x516, 0, 1)
            self.assertTrue(self.get(cpu, BASE + 0x20) & RX1)             # the second packet is ready at once
            self.assertEqual(self.get(cpu, BASE + 0x516, 1), 0x01)
            self.assertEqual(got + self.unload(cpu, 1, (4,) * 16), data)
            self.put(cpu, BASE + 0x516, 0x10, 1)                          # FLUSHFIFO drops it
            self.assertEqual(self.get(cpu, BASE + 0x516, 1), 0)
            self.acknowledge(cpu)

            self.put(cpu, BASE + 0x516, 0x20, 1)                          # SENDSTALL
            self.assertEqual(self.finished(cpu, cpu.usb_out(1, b"x", wait=False))["status"], "stall")
            self.assertEqual(self.get(cpu, BASE + 0x516, 1), 0x60)       # SENTSTALL
            self.assertTrue(self.acknowledge(cpu) & RX1)
            with self.assertRaisesRegex(ValueError, "DMA"):
                self.put(cpu, BASE + 0x517, 0x20, 1)

    def test_bulk_in_naks_until_loaded_then_stall_flush_and_autoset(self):
        TX2 = 1 << 2
        with self.plugged() as cpu:
            self.configure(cpu, 2, tx=(3, 16, 64))
            data = bytes(range(100, 200))
            transfer = cpu.usb_in(0x82, 100, wait=False)
            cpu.run(FRAME)
            pending = cpu.usb_result(transfer)
            self.assertEqual(pending["status"], "pending")
            self.assertAlmostEqual(pending["naks"], FRAME // (62 * BIT), delta=2)
            self.load(cpu, 2, data[:64], (4,) * 16)
            self.assertEqual(self.get(cpu, BASE + 0x522, 1), 0)
            self.put(cpu, BASE + 0x522, 1, 1)                             # TXPKTRDY
            self.assertEqual(self.get(cpu, BASE + 0x522, 1), 0x03)       # with FIFONOTEMPTY
            self.until(cpu, TX2)
            self.assertEqual(self.get(cpu, BASE + 0x522, 1), 0)
            self.load(cpu, 2, data[64:], (4, 4, 4, 4, 4, 4, 4, 4, 2, 1, 1))
            self.put(cpu, BASE + 0x522, 1, 1)
            result = self.finished(cpu, transfer)
            self.assertEqual((result["status"], result["data"]), ("ok", data))
            self.acknowledge(cpu)

            silent = cpu.usb_in(0x82, 64, wait=False, timeout_ms=10)
            result = self.finished(cpu, silent)
            # The first IN is answered 58 bit times in; each retry takes 62.
            self.assertEqual((result["status"], result["naks"]), ("timeout", 1 + (10 * FRAME - 58 * BIT) // (62 * BIT)))
            self.assertEqual(result["completed"] - result["submitted"], 10 * FRAME)

            self.load(cpu, 2, b"gone", (4,))
            self.put(cpu, BASE + 0x522, 1, 1)
            self.put(cpu, BASE + 0x522, 0x08, 1)                          # FLUSHFIFO
            self.assertEqual(self.get(cpu, BASE + 0x522, 1), 0)
            self.put(cpu, BASE + 0x523, 0x80, 1)                          # AUTOSET: a full packet goes by itself
            self.load(cpu, 2, bytes(64), (4,) * 16)
            self.assertEqual(self.get(cpu, BASE + 0x522, 2), 0x8003)
            result = self.finished(cpu, cpu.usb_in(0x82, 64, wait=False))
            self.assertEqual((result["status"], result["data"], result["naks"]), ("ok", bytes(64), 0))
            self.acknowledge(cpu)

            self.put(cpu, BASE + 0x522, 0x10, 1)                          # SENDSTALL
            self.assertEqual(self.finished(cpu, cpu.usb_in(0x82, 64, wait=False))["status"], "stall")
            self.assertEqual(self.get(cpu, BASE + 0x522, 1), 0x30)       # SENDSTALL | SENTSTALL
            self.assertTrue(self.acknowledge(cpu) & TX2)
            state = cpu.usb_state()
            self.assertEqual((state["stalls"], state["errors"], state["toggle_errors"]), (1, 0, 0))
            with self.assertRaisesRegex(ValueError, "endpoints 1 to 4"):
                cpu.usb_in(0x85, 8, wait=False)

    def test_double_buffered_bulk_in_interrupts_only_when_txpktrdy_clears(self):
        # SPRUH79C 33.2.7.1.2.1.2: the interrupt comes when TXPKTRDY goes from 1 to 0. Double-buffered, a
        # load with the other half free clears it at once; a packet that leaves with TXPKTRDY already 0
        # only drops FIFONOTEMPTY (on the unit, a driver waiting for that interrupt stalled; session 6).
        TX2 = 1 << 2
        with self.plugged() as cpu:
            self.configure(cpu, 2, tx=(0x13, 16, 64))                     # double packet buffering: 2 x 64 bytes
            self.load(cpu, 2, bytes(64), (4,) * 16)
            self.put(cpu, BASE + 0x522, 1, 1)
            self.assertEqual(self.get(cpu, BASE + 0x522, 1), 0x02)       # TXPKTRDY cleared at once, FIFONOTEMPTY
            self.assertEqual(self.acknowledge(cpu) & TX2, TX2)
            result = self.finished(cpu, cpu.usb_in(0x82, 64, wait=False))
            self.assertEqual((result["status"], len(result["data"])), ("ok", 64))
            self.assertEqual(self.get(cpu, BASE + 0x522, 1), 0)          # the FIFO is empty: no interrupt
            self.assertEqual(self.get(cpu, BASE + 0x20) & TX2, 0)

            for fill in (1, 2):                                           # both halves: TXPKTRDY stays 1
                self.load(cpu, 2, bytes([fill]) * 64, (4,) * 16)
                self.put(cpu, BASE + 0x522, 1, 1)
            self.assertEqual(self.get(cpu, BASE + 0x522, 1), 0x03)
            self.acknowledge(cpu)
            transfer = cpu.usb_in(0x82, 64, wait=False)
            self.finished(cpu, transfer)
            self.assertEqual(self.get(cpu, BASE + 0x522, 1), 0x02)       # one left: TXPKTRDY cleared, interrupt
            self.assertEqual(self.acknowledge(cpu) & TX2, TX2)
            result = self.finished(cpu, cpu.usb_in(0x82, 64, wait=False))
            self.assertEqual(result["data"], bytes([2]) * 64)
            self.assertEqual(self.get(cpu, BASE + 0x20) & TX2, 0)        # the last one leaves without one

    def test_uint_selects_wrapper_or_core_interrupt_registers(self):
        # UINT = 0: the wrapper takes each event that is enabled in the core.
        with self.plugged() as cpu:
            self.put(cpu, BASE + 0x406, 0, 2)                             # INTRTXE: endpoint 0 off
            cpu.usb_control((0x80, 0, 0, 0), 2, wait=False)
            cpu.run(FRAME)
            self.assertEqual(self.get(cpu, BASE + 0x502, 1), 1)          # the SETUP is there
            self.assertEqual((self.get(cpu, BASE + 0x20), self.get(cpu, BASE + 0x38)), (RESUME_IRQ, RESUME_IRQ))
            self.acknowledge(cpu)
            count = cpu.usb_state()["interrupts"]
            self.put(cpu, BASE + 0x406, 1, 2)                             # enabled: handed over, event 19
            self.assertEqual((self.get(cpu, BASE + 0x20), self.get(cpu, BASE + 0x38)), (EP0, EP0))
            self.assertEqual(cpu.usb_state()["interrupts"], count + 1)
            self.assertEqual(self.get(cpu, BASE + 0x402, 2), 0)          # nothing left in the core register
            self.put(cpu, BASE + 0x34, EP0)                               # masked in the wrapper: a source, no interrupt
            self.assertEqual((self.get(cpu, BASE + 0x20), self.get(cpu, BASE + 0x38)), (EP0, 0))
            self.assertEqual(cpu.usb_state()["interrupt_mode"], "wrapper (UINT = 0)")
        with self.plugged() as cpu:                                       # a core register read loses the event
            self.put(cpu, BASE + 0x406, 0, 2)
            cpu.usb_control((0x80, 0, 0, 0), 2, wait=False)
            cpu.run(FRAME)
            self.assertEqual((self.get(cpu, BASE + 0x402, 2), self.get(cpu, BASE + 0x402, 2)), (1, 0))
            self.put(cpu, BASE + 0x406, 1, 2)
            self.assertEqual(self.get(cpu, BASE + 0x20), RESUME_IRQ)
        # UINT = 1: the core registers hold the events and clear on read; the wrapper's source stays empty.
        with self.device(uint=True) as cpu:
            self.put(cpu, BASE + 0x40b, 0x0c, 1)                          # INTRUSBE: reset and SOF
            self.put(cpu, 0x0180010c, 0x0f0e0d13)                         # CPU interrupt 12 takes event 19
            cpu.usb_attach()
            cpu.run(DEBOUNCE)
            self.assertEqual(cpu.usb_state()["interrupts"], 1)
            self.assertEqual(self.get(cpu, 0x01800000) & (1 << 19), 1 << 19)
            self.put(cpu, 0x01800040, 1 << 19)
            self.assertEqual(self.get(cpu, BASE + 0x20), 0)
            self.assertEqual((self.get(cpu, BASE + 0x40a, 1), self.get(cpu, BASE + 0x40a, 1)), (4, 0))   # reset, read once
            cpu.run(RESET + RECOVERY)
            self.assertEqual(cpu.usb_state()["interrupts"], 1)
            cpu.usb_control((0x80, 0, 0, 0), 2, wait=False)
            cpu.run(FRAME)
            self.assertEqual(cpu.usb_state()["interrupts"], 2)           # the core's output went from idle to driven
            self.assertEqual(self.get(cpu, 0x01800000) & (1 << 19), 1 << 19)
            self.assertEqual((self.get(cpu, BASE + 0x20), self.get(cpu, BASE + 0x38)), (0, 0))
            self.assertEqual((self.get(cpu, BASE + 0x402, 2), self.get(cpu, BASE + 0x402, 2)), (1, 0))
            self.assertEqual(cpu.usb_state()["interrupt_mode"], "core registers (UINT = 1)")
            # An event while another is still unread raises nothing new: the handler must read until all are 0.
            self.unload(cpu, 0, (4, 4))
            self.put(cpu, BASE + 0x502, 0x40, 1)
            self.load(cpu, 0, b"\0\0", (2,))
            cpu.usb_sof(True)
            cpu.run(FRAME)                                                # a SOF, left unread
            self.assertEqual(cpu.usb_state()["interrupts"], 3)
            self.put(cpu, BASE + 0x502, 0x0a, 1)
            cpu.run(FRAME)                                                # the data and status stages: endpoint 0 events
            self.assertEqual(cpu.usb_state()["interrupts"], 3)
            self.assertEqual((self.get(cpu, BASE + 0x402, 2), self.get(cpu, BASE + 0x40a, 1)), (1, 0x0b))   # with the unenabled suspend and resume

    def test_idle_bus_suspends_after_3_ms_and_the_next_packet_resumes(self):
        with self.device(sof=False) as cpu:
            cpu.usb_attach()
            cpu.run(DEBOUNCE + RESET)
            self.acknowledge(cpu)
            cpu.run(3 * FRAME - 1)
            self.assertEqual((self.get(cpu, BASE + 0x20), self.get(cpu, BASE + 0x401, 1)), (0, 0x40))
            cpu.run(1)
            self.assertEqual((self.get(cpu, BASE + 0x20), self.get(cpu, BASE + 0x401, 1)), (1 << 16, 0x42))   # SUSPEND
            self.assertTrue(cpu.usb_state()["suspended"])
            self.acknowledge(cpu)
            cpu.usb_control((0x80, 0, 0, 0), 2, wait=False)
            cpu.run(RECOVERY)
            self.assertEqual(self.get(cpu, BASE + 0x20), 1 << 17 | EP0)   # RESUME, then the SETUP
            self.assertEqual(self.get(cpu, BASE + 0x401, 1), 0x40)

    # Isochronous streams. plugged() returns at the cycle of an SOF, so the next SOFs are whole frames away;
    # after each, endpoint 1's OUT packet comes first, then endpoint 2's IN token.
    OUT_END = (4 + 35 + 4 + 35 + 8 * 192) * BIT                           # token, 192 data bytes
    IN_TOKEN = (4 + 35) * BIT

    def audio(self, cpu, rx=(0x15, 8, 196), tx=(0x05, 72, 196)):
        """Endpoint 1 isochronous OUT (two 256-byte packets at 64) and endpoint 2 isochronous IN (one at 576)."""
        self.configure(cpu, 1, rx=rx)
        self.put(cpu, BASE + 0x517, 0x40, 1)                              # RXCSR.ISO
        self.configure(cpu, 2, tx=tx)
        self.put(cpu, BASE + 0x523, 0x60, 1)                              # TXCSR.ISO, MODE

    def test_isochronous_out_is_one_packet_a_frame_with_no_retry_and_overrun_when_full(self):
        RX1 = 1 << 9
        packets = [bytes([index]) * 192 for index in range(1, 6)]
        with self.plugged(sof=True) as cpu:
            self.audio(cpu)
            state = cpu.usb_state()["endpoints"][0]
            self.assertEqual((state["rx_iso"], state["rx_fifo"]), (True, dict(address=64, packet=256, packets=2)))
            with self.assertRaisesRegex(ValueError, "isochronous"):
                cpu.usb_out(1, b"bulk", wait=False)
            self.assertEqual(cpu.usb_iso_stream_out(1, packets[:4])["queued"], 4)
            cpu.run(FRAME + self.OUT_END - 1)
            self.assertEqual(cpu.usb_state()["endpoints"][0]["rx_packets"], 0)
            cpu.run(1)                                                    # the packet's last bit
            self.assertEqual(cpu.usb_state()["endpoints"][0]["rx_packets"], 1)
            self.assertTrue(self.acknowledge(cpu) & RX1)
            self.assertEqual((self.get(cpu, BASE + 0x516, 1), self.get(cpu, BASE + 0x518, 2)), (0x01, 192))
            self.assertEqual(self.unload(cpu, 1, (4,) * 48), packets[0])
            self.put(cpu, BASE + 0x516, 0, 1)                             # RXPKTRDY cleared
            # Left alone, the next two fill both halves of the FIFO and the fourth is lost for good.
            cpu.run(2 * FRAME)
            self.assertEqual(self.get(cpu, BASE + 0x516, 1), 0x03)        # RXPKTRDY, FIFOFULL
            cpu.run(FRAME)
            self.assertEqual(self.get(cpu, BASE + 0x516, 1), 0x07)        # and OVERRUN
            self.assertEqual(cpu.usb_iso_state(1), dict(queued=0, sent=4, packets=3, bytes=576, missed=1, short=0,
                                                        errors=0, waiting=0, dropped=0))
            state = cpu.usb_state()
            self.assertEqual((state["iso_missed"], state["iso_overruns"], state["iso_errors"], state["naks"]), (1, 1, 0, 0))
            self.assertTrue(state["endpoints"][0]["rx_overrun"])
            self.put(cpu, BASE + 0x516, 0x01, 1)                          # OVERRUN cleared, the packet kept
            self.assertEqual(self.get(cpu, BASE + 0x516, 1), 0x03)
            self.acknowledge(cpu)
            self.assertEqual(self.unload(cpu, 1, (4,) * 48), packets[1])
            self.put(cpu, BASE + 0x516, 0, 1)
            self.assertTrue(self.acknowledge(cpu) & RX1)                  # the interrupt for the one behind it
            self.assertEqual(self.unload(cpu, 1, (1,) * 192), packets[2])
            self.put(cpu, BASE + 0x516, 0, 1)
            cpu.run(3 * FRAME)                                            # nothing queued: no packets, and no fourth
            self.assertEqual((self.get(cpu, BASE + 0x516, 1), cpu.usb_iso_state(1)["sent"]), (0, 4))

            # A zero-length packet is a packet; wait=True runs the guest until the queue is out.
            sofs = cpu.usb_state()["sofs"]
            self.assertEqual(cpu.usb_iso_stream_out(1, [b"", packets[4]], wait=True)["packets"], 5)
            self.assertEqual(cpu.usb_state()["sofs"], sofs + 3)
            self.assertEqual((self.get(cpu, BASE + 0x516, 1), self.get(cpu, BASE + 0x518, 2)), (0x03, 0))
            self.put(cpu, BASE + 0x516, 0, 1)
            self.assertEqual(self.unload(cpu, 1, (2,) * 96), packets[4])
            self.put(cpu, BASE + 0x516, 0, 1)

            # What the device cannot take is an error, not a lost frame: a packet above RXMAXP, and any
            # packet while the endpoint is not isochronous or the device is at another address.
            cpu.usb_iso_stream_out(1, [bytes(197)], wait=True)
            self.put(cpu, BASE + 0x517, 0, 1)
            cpu.usb_iso_stream_out(1, [bytes(8)], wait=True)
            self.put(cpu, BASE + 0x517, 0x40, 1)
            self.put(cpu, BASE + 0x400, 5, 1)
            cpu.usb_iso_stream_out(1, [bytes(8)], wait=True)
            self.put(cpu, BASE + 0x400, 0, 1)
            state = cpu.usb_iso_state(1)
            self.assertEqual((state["sent"], state["packets"], state["missed"], state["errors"]), (9, 5, 1, 3))
            self.assertEqual((cpu.usb_state()["iso_errors"], self.get(cpu, BASE + 0x516, 1)), (3, 0))
            # A bus reset ends the stream.
            cpu.usb_iso_stream_out(1, packets)
            cpu.usb_reset()
            self.assertEqual(cpu.usb_iso_state(1)["queued"], 0)
            with self.assertRaisesRegex(ValueError, "enabled port"):
                cpu.usb_iso_stream_out(1, packets)

    def test_isochronous_in_sends_what_is_loaded_or_a_zero_length_packet_with_underrun(self):
        TX2 = 1 << 2
        data = bytes(range(192))
        with self.plugged(sof=True) as cpu:
            self.audio(cpu)
            start = cpu.cycles()
            self.assertIsNone(cpu.usb_iso_stream_in(0x82, 4, wait=False, max_packet=196, short_below=192))
            # Frame 1: nothing loaded. A zero-length packet, UNDERRUN, no interrupt and no NAK.
            cpu.run(FRAME + self.IN_TOKEN - 1)
            self.assertEqual(self.get(cpu, BASE + 0x522, 1), 0)
            cpu.run(1)
            self.assertEqual(self.get(cpu, BASE + 0x522, 1), 0x04)
            cpu.run(FRAME // 2)
            frame = self.get(cpu, BASE + 0x40c, 2)
            self.assertEqual(cpu.usb_iso_collect(0x82), [dict(frame=frame, status="empty", data=b"",
                                                              cycles=start + FRAME + self.IN_TOKEN + (4 + 35) * BIT)])
            self.assertFalse(self.acknowledge(cpu) & TX2)
            # Frame 2: a packet loaded in time is sent whole; TXPKTRDY drops and the interrupt comes at its end.
            self.load(cpu, 2, data, (4,) * 48)
            self.put(cpu, BASE + 0x522, 0x01, 1)                          # TXPKTRDY; written 0, UNDERRUN clears
            self.assertEqual(self.get(cpu, BASE + 0x522, 1), 0x03)
            sent = start + 2 * FRAME + self.IN_TOKEN + (4 + 35 + 8 * 192) * BIT
            cpu.run(sent - 1 - cpu.cycles())
            self.assertEqual((self.get(cpu, BASE + 0x522, 1), self.acknowledge(cpu) & TX2), (0x03, 0))
            cpu.run(1)
            self.assertEqual((self.get(cpu, BASE + 0x522, 1), self.acknowledge(cpu) & TX2), (0, TX2))
            self.assertEqual(cpu.usb_iso_collect(0x82), [dict(frame=frame + 1, status="data", data=data, cycles=sent)])
            # Frame 3: a zero-length packet the firmware loaded looks the same to the host, but it is no
            # underrun and it is followed by the interrupt. Frame 4: a packet under short_below.
            self.put(cpu, BASE + 0x522, 0x01, 1)
            cpu.run(start + 3 * FRAME + FRAME // 2 - cpu.cycles())
            self.assertEqual((self.get(cpu, BASE + 0x522, 1), self.acknowledge(cpu) & TX2), (0, TX2))
            self.load(cpu, 2, data[:188], (4,) * 47)
            self.put(cpu, BASE + 0x522, 0x01, 1)
            cpu.run(FRAME)
            self.assertEqual([(row["frame"] - frame, row["status"], len(row["data"])) for row in cpu.usb_iso_collect(0x82)],
                             [(2, "empty", 0), (3, "data", 188)])
            self.assertEqual(cpu.usb_iso_state(0x82), dict(queued=0, sent=4, packets=2, bytes=380, missed=2, short=1,
                                                           errors=0, waiting=0, dropped=0))
            state = cpu.usb_state()
            self.assertEqual((state["iso_missed"], state["iso_underruns"], state["iso_errors"], state["naks"]), (2, 1, 0, 0))
            cpu.run(2 * FRAME)                                            # no frames asked for: no tokens, no underrun
            self.assertEqual((self.get(cpu, BASE + 0x522, 1), cpu.usb_iso_state(0x82)["sent"]), (0, 4))

            # wait=True runs the frames and returns them. A packet above max_packet is an error, as is any
            # token while the endpoint is not isochronous.
            self.load(cpu, 2, data[:100], (4,) * 25)
            self.put(cpu, BASE + 0x522, 0x01, 1)
            self.assertEqual([row["status"] for row in cpu.usb_iso_stream_in(0x82, 1, max_packet=64)], ["error"])
            self.put(cpu, BASE + 0x523, 0x20, 1)
            self.assertEqual([row["status"] for row in cpu.usb_iso_stream_in(0x82, 2)], ["error", "error"])
            self.put(cpu, BASE + 0x523, 0x60, 1)
            self.assertEqual((cpu.usb_iso_state(0x82)["errors"], cpu.usb_state()["iso_errors"]), (3, 3))

    def test_isoupdate_holds_a_packet_until_the_next_sof_and_two_loaded_packets_babble(self):
        # Two packets pending at an IN token: on the unit (session 6) the host saw babble and the FIFO emptied
        # twice as fast as one packet a frame, so both leave in one data packet and the stream records an error.
        def first_frames(power):
            with self.plugged(sof=True) as cpu:
                self.audio(cpu, tx=(0x15, 72, 196))                       # two packets
                self.put(cpu, BASE + 0x401, power, 1)
                cpu.usb_iso_stream_in(0x82, 3, wait=False)
                cpu.run(FRAME + 1)                                        # just after the SOF, before the IN token
                for fill in (1, 2):
                    self.load(cpu, 2, bytes([fill]) * 8, (4, 4))
                    self.put(cpu, BASE + 0x522, 0x01, 1)
                self.assertEqual(self.get(cpu, BASE + 0x522, 1), 0x03)    # both halves loaded
                cpu.run(3 * FRAME)
                state = cpu.usb_state()
                rows = [(row["status"], row["data"][:1]) for row in cpu.usb_iso_collect(0x82)]
                return rows, state["iso_underruns"], state["iso_double_sends"]
        self.assertEqual(first_frames(0x40), ([("error", b""), ("empty", b""), ("empty", b"")], 1, 1))
        # ISOUPDATE: neither goes out in the frame it was loaded in, and that zero-length packet is no underrun.
        self.assertEqual(first_frames(0xc0), ([("empty", b""), ("error", b""), ("empty", b"")], 1, 1))

    def test_double_buffered_iso_in_sends_one_packet_a_frame_when_loaded_one_a_frame(self):
        with self.plugged(sof=True) as cpu:
            self.audio(cpu, tx=(0x15, 72, 196))                           # two packets
            cpu.usb_iso_stream_in(0x82, 4, wait=False)
            for fill in range(1, 5):
                cpu.run(FRAME // 2)                                       # after this frame's token
                self.load(cpu, 2, bytes([fill]) * 8, (4, 4))
                self.put(cpu, BASE + 0x522, 0x01, 1)
                cpu.run(FRAME - FRAME // 2)
            rows = [(row["status"], row["data"][:1]) for row in cpu.usb_iso_collect(0x82)]
            self.assertEqual(rows[:3], [("data", b"\x01"), ("data", b"\x02"), ("data", b"\x03")])
            self.assertEqual(cpu.usb_state()["iso_double_sends"], 0)

    def test_isoupdate_loading_at_each_sof_before_the_token_sends_one_packet_a_frame(self):
        # Enaga's feeding since session 6: one packet at each SOF, held by ISOUPDATE. When the load comes before
        # the token, last frame's packet (released at this SOF) goes and the new one stays: no babble.
        with self.plugged(sof=True) as cpu:
            self.audio(cpu, tx=(0x15, 72, 196))                           # two packets
            self.put(cpu, BASE + 0x401, 0xc0, 1)
            cpu.usb_iso_stream_in(0x82, 4, wait=False)
            cpu.run(FRAME + 1)                                            # just after the SOF, before the IN token
            for fill in range(1, 5):
                self.load(cpu, 2, bytes([fill]) * 8, (4, 4))
                self.put(cpu, BASE + 0x522, 0x01, 1)
                cpu.run(FRAME)
            rows = [(row["status"], row["data"][:1]) for row in cpu.usb_iso_collect(0x82)]
            self.assertEqual(rows, [("empty", b""), ("data", b"\x01"), ("data", b"\x02"), ("data", b"\x03")])
            state = cpu.usb_state()
            self.assertEqual((state["iso_double_sends"], state["iso_underruns"]), (0, 0))

    def test_streams_run_beside_a_bulk_transfer_and_fast_forward_changes_nothing(self):
        def script(fast_forward):
            with self.plugged(sof=True) as cpu:
                cpu.fast_forward(fast_forward)
                self.audio(cpu)
                self.configure(cpu, 3, rx=(3, 104, 64))
                rows = []
                cpu.usb_iso_stream_out(1, [bytes([index]) * 192 for index in range(8)])
                cpu.usb_iso_stream_in(0x82, 8, wait=False)
                bulk = cpu.usb_out(3, bytes(range(40)), wait=False)
                cpu.run(FRAME // 2)
                for index in range(8):                                    # the firmware's turn, in the middle of each frame
                    self.load(cpu, 2, bytes([0x80 | index]) * 192, (4,) * 48)
                    self.put(cpu, BASE + 0x522, 0x01, 1)
                    cpu.run(FRAME)
                    rows.append((self.acknowledge(cpu), self.get(cpu, BASE + 0x40c, 2), self.get(cpu, BASE + 0x518, 2)))
                    self.unload(cpu, 1, (4,) * 48)
                    self.put(cpu, BASE + 0x516, 0, 1)
                rows.append(self.finished(cpu, bulk))
                rows.append(cpu.usb_iso_collect(0x82))
                rows.append((cpu.usb_iso_state(1), cpu.usb_iso_state(0x82)))
                rows.append({name: value for name, value in cpu.usb_state().items() if name != "reserved_status"})
                return rows
        fast, slow = script(True), script(False)
        self.assertEqual(fast, slow)
        self.assertEqual([row[2] for row in fast[:8]], [192] * 8)
        self.assertEqual([row[1] - fast[0][1] for row in fast[:8]], list(range(8)))   # FRAME counts the SOFs
        self.assertTrue(all(row[0] & SOF_IRQ for row in fast[:8]))
        self.assertEqual(fast[8]["status"], "ok")
        self.assertEqual([(row["status"], row["data"]) for row in fast[9]],
                         [("data", bytes([0x80 | index]) * 192) for index in range(8)])
        self.assertEqual([row["frame"] for row in fast[9]], [row[1] for row in fast[:8]])
        self.assertEqual((fast[10][0]["packets"], fast[10][0]["missed"], fast[10][1]["packets"], fast[10][1]["missed"]), (8, 0, 8, 0))
        self.assertEqual((fast[11]["iso_errors"], fast[11]["toggle_errors"], fast[11]["errors"]), (0, 0, 0))

    def test_soft_disconnect_and_bus_reset_end_a_transfer_and_fast_forward_changes_nothing(self):
        def script(fast_forward):
            with self.device() as cpu:
                cpu.fast_forward(fast_forward)
                cpu.usb_attach()
                cpu.run(DEBOUNCE + RESET + RECOVERY)
                self.acknowledge(cpu)
                self.configure(cpu, 3, rx=(3, 8, 64), tx=(3, 16, 64))
                rows = []
                first = cpu.usb_in(0x83, 8, wait=False)
                second = cpu.usb_out(3, bytes(5), wait=False)             # queued behind the first
                cpu.run(3 * FRAME)
                self.load(cpu, 3, b"12345678", (4, 4))
                self.put(cpu, BASE + 0x532, 1, 1)
                rows.append(self.finished(cpu, first)); rows.append(self.finished(cpu, second))
                third = cpu.usb_in(0x83, 8, wait=False)
                cpu.run(FRAME)
                self.put(cpu, BASE + 0x401, 0, 1)                         # SOFTCONN off under a transfer
                rows.append(cpu.usb_result(third))
                rows.append(cpu.usb_state()["port"])
                self.put(cpu, BASE + 0x401, 0x40, 1)
                cpu.run(DEBOUNCE + RESET + RECOVERY)
                fourth = cpu.usb_in(0x83, 8, wait=False)
                cpu.run(FRAME)
                cpu.usb_reset()
                rows.append(cpu.usb_result(fourth))
                rows.append({name: value for name, value in cpu.usb_state().items() if name != "reserved_status"})
                return rows
        fast, slow = script(True), script(False)
        self.assertEqual(fast, slow)
        self.assertEqual([row["status"] for row in fast[:3]] + [fast[3], fast[4]["status"]],
                         ["ok", "ok", "disconnected", "powered", "disconnected"])
        self.assertEqual((fast[0]["data"], fast[1]["sent"], fast[5]["bus_resets"], fast[5]["port"]), (b"12345678", 5, 2, "reset"))


MICROFRAME = FRAME // 8


def hs_wire(bits):
    """Cycles for `bits` bit times at 480 Mbit/s (372 MHz: 31/40 cycle a bit, rounded up)."""
    return (bits * 31 + 39) // 40


@unittest.skipUnless(shutil.which("g++"), "host g++ required")
class UsbHighSpeed(unittest.TestCase):
    """A connection whose bus reset settled on high speed (HSENAB set): microframes, 480 Mbit/s timing and
    high-speed packet sizes (USB 2.0 5.5-5.8, 8.4.3.1; SPRUH79C 33.2.7.1.4). Full speed is UsbHost's."""
    setUpClass = classmethod(UsbDisconnected.setUpClass.__func__)
    tearDownClass = classmethod(UsbDisconnected.tearDownClass.__func__)
    machine, enable_clock = UsbDisconnected.machine, UsbDisconnected.enable_clock
    get, put = staticmethod(UsbDisconnected.get), staticmethod(UsbDisconnected.put)
    device, acknowledge, finished = UsbHost.device, UsbHost.acknowledge, UsbHost.finished
    until, unload, load, configure = UsbHost.until, UsbHost.unload, UsbHost.load, UsbHost.configure

    def plugged(self, sof=False, power=0x60):
        """As UsbHost.plugged, with HSENAB left on: the port comes up at high speed."""
        cpu = self.device(connect=False, sof=sof)
        self.put(cpu, BASE + 0x401, power, 1)
        cpu.usb_attach()
        cpu.run(DEBOUNCE + RESET + RECOVERY)
        state = cpu.usb_state()
        self.assertEqual((state["port"], state["speed"], state["profile"]),
                         ("enabled", "high", "USB0 peripheral with a scripted high-speed host"))
        self.acknowledge(cpu)
        return cpu

    def test_sof_every_microframe_and_frame_changes_every_eighth(self):
        def script(fast_forward):
            with self.device(connect=False, sof=True) as cpu:
                cpu.fast_forward(fast_forward)
                self.put(cpu, BASE + 0x401, 0x60, 1)
                cpu.usb_attach()
                cpu.run(DEBOUNCE + RESET)                                 # the port is enabled now
                self.acknowledge(cpu)
                frame = self.get(cpu, BASE + 0x40c, 2)
                cpu.run(MICROFRAME - 1)
                rows = [(self.get(cpu, BASE + 0x20) & SOF_IRQ, cpu.usb_state()["sofs"])]
                for _ in range(16):                                       # the SOF lands on each 46,500th cycle
                    cpu.run(1)
                    rows.append((self.acknowledge(cpu) & SOF_IRQ, (self.get(cpu, BASE + 0x40c, 2) - frame) & 2047))
                    cpu.run(MICROFRAME - 1)
                interrupts = cpu.usb_state()["interrupts"]
                for _ in range(8):                                        # 1 ms, each interrupt acknowledged
                    cpu.run(MICROFRAME)
                    self.acknowledge(cpu)
                rows.append((cpu.usb_state()["sofs"], cpu.usb_state()["interrupts"] - interrupts))
                return rows
        fast, slow = script(True), script(False)
        self.assertEqual(fast, slow)
        self.assertEqual(fast[0], (0, 0))
        self.assertEqual(fast[1:17], [(SOF_IRQ, 1)] * 8 + [(SOF_IRQ, 2)] * 8)   # FRAME: the 1 ms frame number
        self.assertEqual(fast[17], (24, 8))                               # 8 SOF interrupts a millisecond

    def test_bulk_packets_of_512_at_480_mbit(self):
        RX1, TX2 = 1 << 9, 1 << 2
        with self.plugged() as cpu:
            self.configure(cpu, 1, rx=(6, 8, 512))                        # one 512-byte packet at 64
            self.configure(cpu, 2, tx=(6, 72, 512))                       # one 512-byte packet at 576
            data = bytes(range(256)) * 4
            start = cpu.cycles()
            transfer = cpu.usb_out(1, data, wait=False, max_packet=512)
            # token 64, gap 32, data 64 + 8 x 512, gap 32, handshake 48 bit times
            first = start + hs_wire(64 + 32 + 64 + 8 * 512 + 32 + 48)
            cpu.run(first - 1 - cpu.cycles())
            self.assertFalse(self.get(cpu, BASE + 0x20) & RX1)
            cpu.run(1)
            self.assertTrue(self.acknowledge(cpu) & RX1)
            self.assertEqual(self.get(cpu, BASE + 0x518, 2), 512)
            got = self.unload(cpu, 1, (4,) * 128)
            self.put(cpu, BASE + 0x516, 0, 1)
            self.until(cpu, RX1, milliseconds=1)
            got += self.unload(cpu, 1, (4,) * 128)
            self.put(cpu, BASE + 0x516, 0, 1)
            result = self.finished(cpu, transfer, milliseconds=1)
            self.assertEqual((result["status"], result["sent"], got), ("ok", 1024, data))
            self.assertLess(result["completed"] - start, MICROFRAME)       # both packets well inside a microframe

            # IN: a 512-byte packet does not end the transfer, the 88-byte one after it does.
            transfer = cpu.usb_in(0x82, 4096, wait=False, max_packet=512)
            self.load(cpu, 2, data[:512], (4,) * 128)
            self.put(cpu, BASE + 0x522, 1, 1)
            self.until(cpu, TX2, milliseconds=1)
            self.load(cpu, 2, data[512:600], (4,) * 22)
            self.put(cpu, BASE + 0x522, 1, 1)
            result = self.finished(cpu, transfer, milliseconds=1)
            self.assertEqual((result["status"], result["data"]), ("ok", data[:600]))
            # A packet above the host's size is babble, as at full speed.
            self.acknowledge(cpu)
            self.load(cpu, 2, data[:512], (4,) * 128)
            self.put(cpu, BASE + 0x522, 1, 1)
            self.assertEqual(self.finished(cpu, cpu.usb_in(0x82, 4096, wait=False, max_packet=64), milliseconds=1)["status"], "error")
            state = cpu.usb_state()
            self.assertEqual((state["errors"], state["toggle_errors"]), (1, 0))

            with self.assertRaisesRegex(ValueError, "high-speed control packets are 1 to 64 bytes, bulk and interrupt 1 to 1024"):
                cpu.usb_out(1, b"x", wait=False, max_packet=1025)
            with self.assertRaisesRegex(ValueError, "high-speed control packets are 1 to 64"):
                cpu.usb_control((0x80, 6, 0x0100, 0), 18, wait=False, max_packet=128)
        with UsbHost.plugged(self) as cpu:                                # full speed keeps its limit
            with self.assertRaisesRegex(ValueError, "full-speed bulk, interrupt and control packets are 1 to 64 bytes"):
                cpu.usb_out(1, b"x", wait=False, max_packet=512)

    def iso(self, cpu):
        """Endpoint 1 isochronous OUT and endpoint 2 isochronous IN, one 1024-byte packet each."""
        self.configure(cpu, 1, rx=(7, 8, 1024))
        self.put(cpu, BASE + 0x517, 0x40, 1)                              # RXCSR.ISO
        self.configure(cpu, 2, tx=(7, 136, 1024))
        self.put(cpu, BASE + 0x523, 0x60, 1)                              # TXCSR.ISO, MODE

    def test_isochronous_streams_per_microframe_and_interval(self):
        RX1 = 1 << 9
        with self.plugged(sof=True) as cpu:
            self.iso(cpu)
            cpu.run(MICROFRAME // 2)
            rows = cpu.usb_iso_stream_in(0x82, 10)                        # nothing loaded: zero-length packets
            self.assertEqual([row["status"] for row in rows], ["empty"] * 10)
            slots = [(row["frame"] * 8 + row["microframe"]) for row in rows]
            self.assertEqual([b - a for a, b in zip(slots, slots[1:])], [1] * 9)   # one token every microframe
            self.assertEqual([b["cycles"] - a["cycles"] for a, b in zip(rows, rows[1:])], [MICROFRAME] * 9)
            rows = cpu.usb_iso_stream_in(0x82, 4, interval=4)             # bInterval 3: every fourth microframe
            slots = [(row["frame"] * 8 + row["microframe"]) for row in rows]
            self.assertEqual([b - a for a, b in zip(slots, slots[1:])], [4] * 3)

            # 1024 bytes each way in a microframe.
            data = bytes(range(256)) * 4
            self.load(cpu, 2, data, (4,) * 256)
            self.put(cpu, BASE + 0x522, 1, 1)
            self.assertEqual([(row["status"], row["data"]) for row in cpu.usb_iso_stream_in(0x82, 1, interval=1)],
                             [("data", data)])
            self.acknowledge(cpu)
            cpu.usb_iso_stream_out(1, [data], wait=True, interval=1)
            self.assertTrue(self.acknowledge(cpu) & RX1)
            self.assertEqual((self.get(cpu, BASE + 0x518, 2), self.unload(cpu, 1, (4,) * 256)), (1024, data))
            self.put(cpu, BASE + 0x516, 0, 1)
            with self.assertRaisesRegex(ValueError, "high-speed isochronous packet is at most 1024 bytes"):
                cpu.usb_iso_stream_out(1, [bytes(1025)])
            with self.assertRaisesRegex(ValueError, "interval"):
                cpu.usb_iso_stream_in(0x82, 1, interval=3)
            state = cpu.usb_state()
            self.assertEqual((state["iso_errors"], state["iso_underruns"]), (0, 1))

    def test_isoupdate_holds_a_packet_until_the_next_microframe(self):
        def first_microframes(power):
            with self.plugged(sof=True, power=power) as cpu:
                self.iso(cpu)
                cpu.usb_iso_stream_in(0x82, 2, wait=False, interval=1)
                cpu.run(MICROFRAME + 1)                                   # just after the SOF, before the IN token
                self.load(cpu, 2, b"held", (4,))
                self.put(cpu, BASE + 0x522, 1, 1)
                cpu.run(2 * MICROFRAME)
                rows = cpu.usb_iso_collect(0x82)
                return [(row["status"], row["data"]) for row in rows], rows[1]["frame"] * 8 + rows[1]["microframe"] - \
                    (rows[0]["frame"] * 8 + rows[0]["microframe"])
        self.assertEqual(first_microframes(0x60), ([("data", b"held"), ("empty", b"")], 1))
        self.assertEqual(first_microframes(0xe0), ([("empty", b""), ("data", b"held")], 1))   # ISOUPDATE

    def test_enumerate_takes_high_speed_sizes_and_reads_the_qualifier(self):
        """usb_enumerate's host side, over scripted descriptors: the test answers each control transfer."""
        def endpoint(address, attributes, size, interval):
            return struct.pack("<BBBBHB", 7, 5, address, attributes, size, interval)
        body = (struct.pack("<BBBBBBBBB", 9, 4, 0, 0, 4, 0xff, 0, 0, 0) + endpoint(0x01, 2, 512, 0) + endpoint(0x81, 2, 512, 0)
                + endpoint(0x02, 3, 64, 4) + endpoint(0x83, 1, 1024, 3))
        configuration = struct.pack("<BBHBBBBB", 9, 2, 9 + len(body), 1, 1, 0, 0x80, 50) + body
        other = bytes([9, 7]) + configuration[2:]
        device = struct.pack("<BBHBBBBHHHBBBB", 18, 1, 0x0200, 0, 0, 0, 64, 0x1234, 0x5678, 0x0100, 0, 0, 0, 1)
        qualifier = struct.pack("<BBHBBBBBB", 10, 6, 0x0200, 0, 0, 0, 64, 1, 0)

        def run(speed, has_qualifier):
            with self.machine() as cpu:
                asked = []
                cpu.usb_state = lambda: dict(cable_connected=True, port="enabled", speed=speed)
                cpu._usb_iso_set_interval = lambda address, interval: None
                def control(setup, size=None, timeout_ms=1000, **options):
                    kind, request, value = setup[0], setup[1], setup[2]
                    asked.append((request, value >> 8))
                    answers = {1: device, 2: configuration, 6: qualifier if has_qualifier else None, 7: other}
                    if request != 6:
                        return dict(status="ok", data=b"")
                    answer = answers[value >> 8]
                    if answer is None:
                        return dict(status="stall", data=b"")
                    return dict(status="ok", data=answer[:size])
                cpu.usb_control = control
                return cpu.usb_enumerate(), asked, dict(cpu.usb_packets), dict(cpu.usb_iso_packets), dict(cpu.usb_iso_intervals)
        found, asked, packets, iso, intervals = run("high", True)
        self.assertEqual((found["speed"], found["qualifier"], found["other_speed_configuration"]), ("high", qualifier, other))
        self.assertEqual((packets, iso, intervals), ({0x01: 512, 0x81: 512, 0x02: 64}, {0x83: 1024}, {0x83: 4}))
        self.assertEqual([row["interval"] for row in found["endpoints"]], [0, 0, 4, 3])
        self.assertEqual(asked, [(6, 1), (5, 0), (6, 1), (6, 2), (6, 2), (6, 6), (6, 7), (6, 7), (9, 0)])
        found, asked, _, _, _ = run("high", False)                        # a stalled qualifier: one speed only
        self.assertEqual((found["qualifier"], found["other_speed_configuration"]), (None, None))
        self.assertEqual(asked[-2:], [(6, 6), (9, 0)])
        found, asked, packets, iso, intervals = run("full", True)         # full speed: as before
        self.assertEqual((packets, iso, intervals), ({0x01: 64, 0x81: 64, 0x02: 64}, {0x83: 1023}, {}))
        self.assertNotIn("speed", found)
        self.assertNotIn("interval", found["endpoints"][0])
        self.assertNotIn(6, [kind for _, kind in asked])


if __name__ == "__main__":
    unittest.main()
