"""Guarded low-write continuation is explicit and never supplies invented read data."""
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


@unittest.skipUnless(shutil.which("g++"), "host g++ required")
class ReservedWrites(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        WORK.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(dir=WORK, prefix="test-reserved-")
        cls.work = Path(cls.temporary.name)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def machine(self, texts, enabled=True):
        cpu = CPU(self.work, decode=False)
        cpu.enable_board()
        cpu.reserved_low_writes(enabled)
        cpu.map(0xc2100000, 4096, 7)
        for i, text in enumerate([*texts, "b .S2 b3", "nop 5"]):
            pc = 0xc2100000 + 4 * i
            compiled = (Instruction * 1)(instruction(pc, text))
            cpu.install(pc, pc + 4, False, pc & ~31, 32, compiled)
        cpu.reset(0xc2100000)
        cpu.set_register("a0", 8)
        return cpu

    @staticmethod
    def put(cpu, address, value):
        cpu.write(address, struct.pack("<I", value))

    @staticmethod
    def get(cpu, address):
        return struct.unpack("<I", cpu.read(address, 4))[0]

    def test_exact_store_values_pcs_and_cycles_across_slices(self):
        texts = ["stb .D1T1 a4,*a0", "sth .D1T1 a5,*+a0(2)",
                 "stw .D1T1 a6,*+a0(4)", "stdw .D1T1 a9:a8,*+a0(8)"]
        results = []
        for sliced in (False, True):
            with self.machine(texts) as cpu:
                for name, value in dict(a4=0x123456d7, a5=0xabcdef01, a6=0x98765432,
                                        a8=0x11223344, a9=0x55667788).items():
                    cpu.set_register(name, value)
                state = cpu.run(1 if sliced else 100)
                while state["status"] == "budget":
                    state = cpu.run(1)
                self.assertEqual(state["status"], "returned")
                rows = cpu.reserved_low_state()["writes"]
                expected = [(8, 1, 0xd7), (10, 2, 0xef01), (12, 4, 0x98765432), (16, 8, 0x5566778811223344)]
                self.assertEqual(rows, [dict(cycles=i, pc=0xc2100000 + 4 * i, address=a, size=s, value=v)
                                        for i, (a, s, v) in enumerate(expected)])
                results.append((state, rows))
                with self.assertRaisesRegex(ValueError, "unmapped"):
                    cpu.read(8, 1)
                with self.assertRaisesRegex(ValueError, "CPU stores only"):
                    cpu.write(8, b"\x00")
                with self.assertRaisesRegex(ValueError, "does not map RAM"):
                    cpu.map(0, 4096, 7)
                cpu.reset(8, return_address=None)
                with self.assertRaisesRegex(CoreFault, "unmapped"):
                    cpu.run(1)
        self.assertEqual(results[0], results[1])

    def test_strict_default_and_range_boundary(self):
        with self.machine(["stb .D1T1 a4,*a0"], enabled=False) as cpu:
            with self.assertRaisesRegex(CoreFault, "unmapped"):
                cpu.run(1)
            self.assertEqual(cpu.reserved_low_state()["count"], 0)
        for address in (0x6ffffe, 0x700000):
            with self.machine(["stw .D1T1 a4,*a0"]) as cpu:
                cpu.set_register("a0", address)
                with self.assertRaises(CoreFault):
                    cpu.run(1)
                self.assertEqual(cpu.reserved_low_state()["count"], 0)

    def read_machine(self, texts, enabled=True):
        cpu = self.machine(texts, enabled=False)
        cpu.reserved_low_reads(enabled)
        cpu.write(0xc2100800, bytes([*range(0x21, 0x29), *range(0x31, 0x39)]))
        for name, value in dict(a0=0, a1=0xc2100800, a10=0x01800104, a11=0x4630314c, b0=8, b1=0xc2100800, b2=0x4630314c, b4=0xaabbccdd).items():
            cpu.set_register(name, value)
        return cpu

    def test_low_reads_return_the_held_load_data_by_byte_lane(self):
        # Bench M2 on the unit (image 0.3.2, views LOW2, L8, IDLE): D = 21..28 and E = 31..38 are two doublewords
        # of RAM. LD loads D whole; the probe's own accesses follow. The rows named L are the bench's sequences
        # and values, except that L3's device register here is INTMUX1 (07060504, upper lanes) where the bench
        # read EVTFLAG0, and L5's byte comes from E so that the replaced lane shows. The last three rows are the
        # same rule on sequences the bench did not run. The rows named S are bench M3's (image 0.3.4, view SIDE,
        # S1-S11, the same on both runs of two presses): each data path holds its own data, and a read returns
        # the data of the path of its destination register, whichever side its address register is on. S12, the
        # same with the second load made by an interrupt handler, returned 34333231 and is not run here.
        LD = "lddw .D1T1 *a1,a9:a8"
        LDB = "lddw .D2T2 *+b1(8),b7:b6"
        probes = (
            ("L1a", [LD, "ldw .D1T1 *+a0(8),a4"], dict(a4=0x24232221)),
            ("L1b", [LD, "ldw .D1T1 *+a0(12),a4"], dict(a4=0x28272625)),
            ("L1c", [LD, "ldh .D1T1 *+a0(2),a4"], dict(a4=0x2423)),
            ("L1d", [LD, "ldbu .D1T1 *+a0(5),a4"], dict(a4=0x26)),
            ("L2", [LD, "stw .D1T2 b4,*a1", "ldw .D1T1 *+a0(8),a4", "ldw .D1T1 *a1,a5"], dict(a4=0x24232221, a5=0xaabbccdd)),
            ("L3", [LD, "ldw .D1T1 *a10,a4", "ldw .D1T1 *+a0(12),a5", "ldw .D1T1 *+a0(8),a6"],
             dict(a4=0x07060504, a5=0x07060504, a6=0x24232221)),
            ("L4", [LD, "ldw .D1T1 *+a0(8),a4", "ldw .D1T1 *+a0(12),a5"], dict(a4=0x24232221, a5=0x28272625)),
            ("L5", [LD, "ldbu .D1T1 *+a1(9),a4", "ldw .D1T1 *+a0(8),a5"], dict(a4=0x32, a5=0x24233221)),
            ("L5c", [LD, "ldw .D1T1 *+a1(8),a4", "ldw .D1T1 *+a0(8),a5", "ldw .D1T1 *+a0(12),a6"],
             dict(a4=0x34333231, a5=0x34333231, a6=0x28272625)),
            ("L6", [LD, "lddw .D2T2 *+b1(8),b7:b6", "ldw .D1T1 *+a0(8),a4"], dict(a4=0x24232221, b6=0x34333231, b7=0x38373635)),
            ("L7a", [LD, "ldnw .D1T1 *+a0(1),a4"], dict(a4=0x25242322)),
            ("L7b", [LD, "ldnw .D1T1 *+a0(5),a4"], dict(a4=0x21282726)),
            ("L7c", [LD, "ldndw .D1T1 *+a0(3),a5:a4"], dict(a4=0x27262524, a5=0x23222128)),
            ("L8", [LD, "ldw .D1T1 *a11,a4", "ldw .D1T1 *+a0(8),a5"], dict(a4=0x28272625, a5=0x24232221)),
            ("L9", ["ldw .D1T1 *+a0(8),a4", "ldw .D1T1 *+a0(8),a5"], dict(a4=0, a5=0)),
            ("half", [LD, "ldh .D1T1 *+a1(14),a4", "ldndw .D1T1 *a0,a7:a6"], dict(a4=0x3837, a6=0x24232221, a7=0x38372625)),
            ("signed", [LD, "ldb .D1T1 *+a0(7),a4", "ldh .D1T1 *+a0(16),a5"], dict(a4=0x28, a5=0x2221)),
            ("a20", [LD, "ldw .D1T1 *+a1(8),a20", "ldw .D1T1 *+a0(8),a31"], dict(a20=0x34333231, a31=0x34333231)),
            ("b31", [LD, "ldw .D2T2 *+b1(8),b31", "ldw .D1T1 *+a0(8),a4"], dict(b31=0x34333231, a4=0x24232221)),
            ("S1", [LD, LDB, "ldw .D1T1 *+a0(8),a4"], dict(a4=0x24232221)),
            ("S2", [LD, LDB, "ldw .D2T2 *b0,b4"], dict(b4=0x34333231)),
            ("S3", [LDB, LD, "ldw .D2T2 *b0,b4"], dict(b4=0x34333231)),
            ("S4", [LDB, LD, "ldw .D1T1 *+a0(8),a4"], dict(a4=0x24232221)),
            ("S5", [LD, "lddw .D1T2 *+a1(8),b7:b6", "ldw .D1T1 *+a0(8),a4"], dict(a4=0x24232221)),
            ("S6", [LD, "lddw .D2T1 *+b1(8),a7:a6", "ldw .D1T1 *+a0(8),a4"], dict(a4=0x34333231)),
            ("S7", [LD, LDB, "ldw .D2T1 *b0,a4"], dict(a4=0x24232221)),
            ("S8", [LD, LDB, "ldw .D1T2 *+a0(8),b4"], dict(b4=0x34333231)),
            ("S9", [LDB, "ldbu .D2T2 *+b1(1),b5", "ldw .D2T2 *b0,b4"], dict(b4=0x34332231)),
            ("S10", [LD, LDB, "ldw .D2T2 *b2,b4"], dict(b4=0x38373635)),
            ("S11", [LD, LDB, "ldw .D1T1 *a11,a4"], dict(a4=0x28272625)),
            ("B first", ["ldw .D2T2 *b0,b4"], dict(b4=0)),
            ("upper", ["ldw .D1T1 *+a1(12),a4", "ldw .D1T1 *a0,a5", "ldw .D1T1 *+a0(4),a6"], dict(a4=0x38373635, a5=0, a6=0x38373635)),
        )
        for name, texts, expected in probes:
            results = []
            for sliced in (False, True):
                with self.subTest(probe=name, sliced=sliced), self.read_machine([line for text in texts for line in (text, "nop 4")]) as cpu:
                    state = cpu.run(1 if sliced else 200)
                    while state["status"] == "budget":
                        state = cpu.run(1)
                    self.assertEqual({key: hex(state["registers"][key]) for key in expected}, {key: hex(value) for key, value in expected.items()})
                    reads = cpu.reserved_low_read_state()
                    self.assertEqual(reads["count"], sum(any(part in text for part in ("*+a0(", "*a0,", "*a11,", "*b0,", "*b2,")) for text in texts))
                    results.append((state, reads))
                    with self.assertRaisesRegex(ValueError, "fresh board"):
                        cpu.reserved_low_reads(False)
                    with self.assertRaisesRegex(ValueError, "unmapped"):
                        cpu.read(0, 4)
                    with self.assertRaisesRegex(ValueError, "does not map RAM"):
                        cpu.map(0, 4096, 7)
            self.assertEqual(results[0], results[1])
        with self.read_machine(["ldw .D1T1 *+a1(4),a4", "nop 4", "ldh .D1T1 *+a0(6),a5", "nop 4"]) as cpu:
            cpu.run(100)
            self.assertEqual(cpu.reserved_low_read_state()["reads"], [dict(cycles=5, pc=0xc2100008, address=6, size=2, value=0x2827)])

    def test_emifa_reads_need_the_option_and_alignment(self):
        for texts, enabled, error in ((["ldw .D1T1 *a11,a4"], False, "unmapped"),
                                      (["ldw .D1T1 *+a11(2),a4"], True, "unaligned load outside RAM")):
            with self.subTest(texts=texts, enabled=enabled), self.read_machine(texts, enabled) as cpu:
                with self.assertRaisesRegex(CoreFault, error):
                    cpu.run(10)
                self.assertEqual(cpu.reserved_low_read_state()["count"], 0)

    def test_a_misaligned_emifa_store_is_dropped_with_the_low_read_option_too(self):
        # M1 bench I6: the unit's own store was at 0x4630314e. CyDrums makes it after a low read on a blank card.
        with self.read_machine(["stw .D1T1 a4,*+a11(2)", "nop 4"]) as cpu:
            self.assertEqual(cpu.run(100)["status"], "returned")

    def test_low_reads_stay_faults_by_default_at_the_boundary_and_when_misaligned(self):
        for texts, enabled, registers, error in ((["ldw .D1T1 *a0,a2"], False, {}, "unmapped"),
                                                 (["ldw .D1T1 *a0,a2"], True, dict(a0=0x700000), "unmapped"),
                                                 (["ldw .D1T1 *a0,a2"], True, dict(a0=2), "unaligned load outside RAM"),
                                                 (["stw .D1T1 a2,*a0"], True, {}, "unmapped")):
            with self.subTest(texts=texts, enabled=enabled, registers=registers), self.read_machine(texts, enabled) as cpu:
                for name, value in registers.items():
                    cpu.set_register(name, value)
                with self.assertRaisesRegex(CoreFault, error):
                    cpu.run(10)
                self.assertEqual(cpu.reserved_low_read_state()["count"], 0)

    def test_low_reads_follow_loads_made_by_compiled_blocks(self):
        from blocks import compile_blocks
        texts = ["ldw .D1T1 *a1++[1],a2", "nop 4", "add .L1 a2,a6,a6", "nop 1", "ldw .D1T1 *a0,a3", "nop 4",
                 "add .L1 a3,a5,a5", "sub .L1 a4,1,a4", "[a4] b .S1 c2100000", "nop 5"]
        rows = []
        for compiled in (False, True):
            with self.read_machine(texts) as cpu:
                cpu.write(0xc2100800, struct.pack("<64I", *range(1000, 1064)))
                if compiled:
                    cpu.blocks(True, heat=True)
                    cpu.set_register("a4", 8); cpu.run(400)
                    self.assertGreater(compile_blocks(cpu, minimum_heat=1), 0)
                    cpu.blocks(True)
                cpu.reset(0xc2100000)
                for name, value in dict(a0=4, a1=0xc2100800, a4=40, a5=0, a6=0).items():
                    cpu.set_register(name, value)
                state = cpu.run(5000)
                self.assertEqual(state["status"], "returned")
                # Address 4 selects the upper lanes, which only the odd words replace.
                self.assertEqual(state["registers"]["a5"], sum(1000 + i if i & 1 else 999 + i for i in range(1, 40)))
                self.assertEqual(state["registers"]["a6"], sum(range(1000, 1040)))
                if compiled:
                    self.assertGreater(cpu.block_state()["block_cycles"], 100)
                rows.append((state["registers"], state["cycles"], cpu.reserved_low_read_state()["reads"][-40:]))
        self.assertEqual(rows[0], rows[1])

    def test_a_low_read_beside_a_load_in_one_packet_is_the_same_in_compiled_blocks(self):
        # The low read's neighbour loads into side B, which has its own held data: the read sees the side A
        # load of the pass. A block leaves such a packet to the interpreter; nothing the block did for it may be
        # left behind.
        from blocks import compile_blocks
        texts = ["ldw .D1T1 *a8++[1],a9", "nop 4", "ldw .D1T1 *a0,a3", "ldw .D2T2 *b1++[1],b2", "nop 4", "add .L1 a3,a5,a5", "add .L2 b2,b6,b6",
                 "sub .L1 a4,1,a4", "[a4] b .S1 c2100000", "nop 5"]
        rows = []
        for compiled in (False, True):
            with self.read_machine(texts) as cpu:
                pair = (Instruction * 2)(instruction(0xc2100008, texts[2]), instruction(0xc210000c, texts[3]))
                cpu.install(0xc2100008, 0xc2100010, False, 0xc2100000, 32, pair)  # the two loads as one packet
                cpu.write(0xc2100800, struct.pack("<64I", *range(1000, 1064)))
                cpu.write(0xc2100900, struct.pack("<64I", *range(2000, 2064)))
                if compiled:
                    cpu.blocks(True, heat=True)
                    cpu.set_register("a4", 8); cpu.set_register("b1", 0xc2100900); cpu.set_register("a8", 0xc2100800); cpu.run(400)
                    self.assertGreater(compile_blocks(cpu, minimum_heat=1), 0)
                    cpu.blocks(True)
                cpu.reset(0xc2100000)
                for name, value in dict(a0=0, a8=0xc2100800, b1=0xc2100900, a4=40, a5=0, b6=0).items():
                    cpu.set_register(name, value)
                state = cpu.run(5000)
                self.assertEqual(state["status"], "returned")
                self.assertEqual(state["registers"]["b6"], sum(range(2000, 2040)))
                # Address 0 selects the lower lanes, which only the even words of the side A table replace.
                self.assertEqual(state["registers"]["a5"], sum(1000 + (i & ~1) for i in range(40)))
                if compiled:
                    self.assertGreater(cpu.block_state()["block_cycles"], 30)
                rows.append((state["registers"], state["cycles"], cpu.reserved_low_read_state()["reads"][-40:]))
        self.assertEqual(rows[0], rows[1])

    def test_exception_masks_routing_and_status_are_guarded(self):
        for address, value in ((0x018000cc, 0x7fffffff), (0x01800104, 0x0706057f), (0x01800104, 0x07060503)):
            with self.subTest(address=address, value=value), self.machine(["stb .D1T1 a4,*a0"]) as cpu:
                self.put(cpu, address, value)
                with self.assertRaisesRegex(CoreFault, "reserved-low write policy"):
                    cpu.run(1)
                self.assertEqual(cpu.reserved_low_state()["count"], 0)
        with self.machine(["stb .D1T1 a4,*a0"]) as cpu:
            cpu.run(1)
            for address, value in ((0x018000cc, 0x7fffffff), (0x01800104, 0x0706057f)):
                old = self.get(cpu, address)
                with self.assertRaisesRegex(ValueError, "reserved-low write policy"):
                    self.put(cpu, address, value)
                self.assertEqual(self.get(cpu, address), old)
            for address in (0x0180000c, 0x018000ac, 0x018000ec):   # bench M2, LOWW: the store sets no event flag
                self.assertEqual(self.get(cpu, address), 0)
            with self.assertRaises(ValueError):
                self.get(cpu, 0x01820400)  # BUSERR is not fabricated.
            with self.assertRaisesRegex(ValueError, "fresh board"):
                cpu.reserved_low_writes(False)

    def test_trace_overflow_faults_without_losing_earlier_stores(self):
        with self.machine(["stb .D1T1 a4,*a0", "b .S1 c2100000", "nop 5"]) as cpu:
            with self.assertRaisesRegex(CoreFault, "trace capacity"):
                cpu.run(40000)
            rows = cpu.reserved_low_state()["writes"]
            self.assertEqual(len(rows), 4096)
            self.assertEqual([row["cycles"] for row in rows], list(range(0, 4096 * 7, 7)))

    def test_dma_cannot_use_the_cpu_store_policy(self):
        with self.machine(["b .S1 c2100000", "nop 5"]) as cpu:
            self.put(cpu, 0x01c10a00, 3)  # PSC0 module 0: EDMA CC0.
            self.put(cpu, 0x01c10120, 1)
            cpu.run(16)
            cpu.map(0xc2200000, 4096, 3)
            cpu.write(0xc2200000, b"abcd")
            words = [0, 0xc2200000, 0x00010004, 8, 0, 0xffff, 0, 1]
            for index, value in enumerate(words):
                self.put(cpu, 0x01c04040 + index * 4, value)
            self.put(cpu, 0x01c01010, 1 << 2)
            with self.assertRaisesRegex(CoreFault, "CPU stores only"):
                cpu.run(1)
            self.assertEqual(cpu.reserved_low_state()["count"], 0)


if __name__ == "__main__":
    unittest.main()
