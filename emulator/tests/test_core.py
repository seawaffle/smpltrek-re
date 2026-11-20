"""Independent pipeline checks, differential vectors and source-built C674x binaries."""
from pathlib import Path
import random
import zlib
import shutil
import struct
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from build import ROOT  # noqa: E402
from core_demo import BIN, build_fixture, demo, symbols, tools_present  # noqa: E402
from cpu import CPU, CoreFault  # noqa: E402
from ir import Instruction, instruction  # noqa: E402

sys.path.insert(0, str(ROOT / "analysis"))
import c6sim  # noqa: E402


class Image:
    def byte(self, _):
        return None


class Program:
    image = Image()

    def __init__(self, entries):
        self.entries = entries

    def packet(self, pc):
        texts, following, protected = self.entries[pc]
        return [(pc + i * 4, text) for i, text in enumerate(texts)], following, protected


@unittest.skipUnless(shutil.which("g++"), "host g++ is needed for the compiled core")
class Core(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="smpltrek-core-")
        cls.work = Path(cls.temporary.name)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def machine(self, program):
        machine = CPU(self.work, decode=False)
        machine.map(0x1000, 0x2000, 7)
        machine.map(0x4000, 4096, 3)
        for pc, (texts, following, protected) in program.entries.items():
            compiled = (Instruction * len(texts))(*(instruction(pc + i * 4, text) for i, text in enumerate(texts)))
            end = (pc + len(texts) * 4 + 31) & ~31
            machine.install(pc, following, protected, pc & ~31, end - (pc & ~31), compiled)
        machine.reset(0x1000)
        return machine

    @staticmethod
    def serial(texts):
        texts = [*texts, "b .S2 b3", "nop 5"]
        return Program({0x1000 + i * 4: ([text], 0x1004 + i * 4, False) for i, text in enumerate(texts)})

    def test_parallel_operands_are_read_before_register_writes(self):
        program = Program({0x1000: (["mvk .S1 9,a0", "mv .L1 a0,a4"], 0x1008, False),
                           0x1008: (["b .S2 b3"], 0x100c, False),
                           0x100c: (["nop 5"], 0x1010, False)})
        with self.machine(program) as machine:
            machine.set_register("a0", 7)
            state = machine.run(100)
            self.assertEqual(state["registers"]["a4"], 7)
            self.assertEqual(state["registers"]["a0"], 9)

    @unittest.skipUnless(tools_present(), "DSP binutils required")
    def test_elf_loading_into_pre_mapped_ram_checks_permissions(self):
        elf = build_fixture(self.work)
        # The demo text is at 0xc2000000. A board maps larger RAM windows before ELF load.
        with CPU(self.work) as machine:
            machine.map(0xc2000000, 0x100000, 7)
            entry = machine.load_elf(elf, map_allocations=False)
            self.assertTrue(0xc2000000 <= entry < 0xc2100000)
        with CPU(self.work) as machine:
            machine.map(0xc2000000, 0x100000, 3)
            with self.assertRaisesRegex(ValueError, "lacks mapped RAM permissions"):
                machine.load_elf(elf, map_allocations=False)

    def test_load_pipeline_survives_one_cycle_slices(self):
        program = self.serial(["ldw .D1T1 *a0,a1", "mv .L1 a1,a2", "nop 3", "mv .L1 a1,a4"])
        states = []
        for sliced in (False, True):
            with self.machine(program) as machine:
                machine.set_register("a0", 0x4000)
                machine.set_register("a1", 7)
                machine.write(0x4000, struct.pack("<I", 42))
                state = machine.run(1 if sliced else 100)
                if sliced:
                    self.assertEqual(state["pending_writes"], 1)
                    self.assertEqual(state["registers"]["a1"], 7)
                    while state["status"] == "budget":
                        state = machine.run(1)
                states.append(state)
        self.assertEqual(states[0], states[1])
        self.assertEqual(states[0]["registers"]["a2"], 7)
        self.assertEqual(states[0]["registers"]["a4"], 42)

    def test_wait_stops_at_load_multiply_branch_and_host_budget_boundaries(self):
        # TSC starts at cycle 1. The load and multiply mature together at cycle 6,
        # inside NOP 9. The final branch ends another NOP 9 early, at cycle 19.
        program = self.serial(["mvc .S2 b0,tscl", "ldw .D1T1 *a0,a1", "mpy32 .M1 a2,a3,a4",
                               "nop 9", "mvc .S2 tscl,b5"])
        program.entries[0x1018] = (["nop 9"], 0x101c, False)
        observations = []
        for sliced in (False, True):
            with self.machine(program) as machine:
                for reg, value in (("a0", 0x4000), ("a1", 7), ("a2", 7), ("a3", 9), ("a4", 8)):
                    machine.set_register(reg, value)
                machine.write(0x4000, struct.pack("<I", 42))
                rows = []
                for boundary in (4, 5, 6, 11, 12, 13, 18, 19):
                    while machine.state()["cycles"] < boundary:
                        state = machine.run(1 if sliced else boundary - machine.state()["cycles"])
                    rows.append(state)
                self.assertEqual((rows[1]["registers"]["a1"], rows[1]["registers"]["a4"]), (7, 8))
                self.assertEqual((rows[2]["registers"]["a1"], rows[2]["registers"]["a4"]), (42, 63))
                self.assertEqual(rows[-1]["registers"]["b5"], 11)
                self.assertEqual((state["status"], state["cycles"]), ("returned", 19))
                observations.append(rows)
        self.assertEqual(*observations)

    def test_nop_counts_preserve_instruction_cycles_and_invalid_count_faults(self):
        for text, cycles in (("nop", 7), ("nop 1", 7), ("nop 9", 15)):
            with self.subTest(text=text), self.machine(self.serial([text])) as machine:
                state = machine.run(100)
                self.assertEqual((state["status"], state["cycles"], state["packets"]), ("returned", cycles, 3))
        for count in (0, -1, 10):
            with self.subTest(count=count), self.machine(self.serial([f"nop {count}"])) as machine:
                with self.assertRaisesRegex(CoreFault, "NOP count must be 1..9"):
                    machine.run(100)

    def test_protected_load_wait_can_be_paused_mid_wait(self):
        program = Program({0x1000: (["ldw .D1T1 *a0,a1"], 0x1004, True),
                           0x1004: (["mv .L1 a1,a4"], 0x1008, False),
                           0x1008: (["b .S2 b3"], 0x100c, False),
                           0x100c: (["nop 5"], 0x1010, False)})
        with self.machine(program) as machine:
            machine.set_register("a0", 0x4000)
            machine.write(0x4000, struct.pack("<I", 123))
            state = machine.run(1)
            self.assertEqual(state["idle_cycles"], 4)
            state = machine.run(4)
            self.assertEqual(state["registers"]["a1"], 123)
            self.assertEqual(state["registers"]["a4"], 0)
            self.assertEqual(machine.run(100)["registers"]["a4"], 123)

    def test_branch_ends_multicycle_nop_at_cycle_six_per_ti(self):
        for text in ("b .S2 b3", "bnop .S2 b3,7"):
            with self.subTest(text=text), self.machine(self.serial([text, "nop 9"])) as machine:
                state = machine.run(100)
                self.assertEqual(state["status"], "returned")
                self.assertEqual(state["cycles"], 6)

    def test_false_predicated_protected_load_keeps_decode_inserted_nops(self):
        program = Program({0x1000: (["b .S2 00001100"], 0x1004, False),
                           0x1004: (["[a0] ldw .D1T1 *a2,a1"], 0x1008, True),
                           0x1008: (["mvk .S1 99,a6"], 0x100c, False),
                           0x100c: (["nop 9"], 0x1010, False),
                           0x1100: (["mvk .S1 42,a4"], 0x1104, False),
                           0x1104: (["b .S2 b3"], 0x1108, False),
                           0x1108: (["nop 5"], 0x110c, False)})
        for sliced in (False, True):
            with self.subTest(sliced=sliced), self.machine(program) as machine:
                # A2=0 remains unmapped; the false load must consume time without reading it.
                state = machine.run(1 if sliced else 100)
                while state["status"] == "budget":
                    state = machine.run(1)
                self.assertEqual(state["status"], "returned")
                self.assertEqual(state["registers"]["a4"], 42)
                self.assertEqual(state["registers"]["a6"], 0)
                self.assertEqual(state["cycles"], 13)

    def test_false_predicate_keeps_bnop_wait_but_has_no_branch(self):
        program = self.serial(["[a0] bnop .S2 b3,7", "mvk .S1 42,a4"])
        with self.machine(program) as machine:
            self.assertEqual(machine.run(7)["idle_cycles"], 1)
            state = machine.run(100)
            self.assertEqual(state["registers"]["a4"], 42)
            self.assertEqual(state["cycles"], 15)

    def test_false_predicate_keeps_addkpc_wait_but_writes_nothing(self):
        # SPRUFE8B 3.8.10: ADDKPC label, reg, n generates its multicycle NOP "regardless of predication", as
        # BNOP does. GCC's integer division helpers rely on it: a skipped ADDKPC with n = 4 fills the delay
        # slots of the branch before it. Dropping the wait lets the packets after it run as well.
        for parallel in ((), ("mpy2 .M1 a1,a2,a9:a8",)):   # alone (fast form) and beside an op with no fast form
            rows = []
            for enabled in (0, 1):
                program = Program({0x1000: (["b .S1 00001100"], 0x1004, False),
                                   0x1004: (["[b0] addkpc .S2 00001020,b5,4", *parallel], 0x1004 + 4 * (1 + len(parallel)), False),
                                   0x1004 + 4 * (1 + len(parallel)): (["mvk .S1 11,a4"], 0x1010, False),
                                   0x1010: (["nop 5"], 0x1014, False),
                                   0x1100: (["mvk .S1 22,a6"], 0x1104, False),
                                   0x1104: (["b .S2 b3"], 0x1108, False),
                                   0x1108: (["nop 5"], 0x110c, False)})
                with self.subTest(parallel=parallel, enabled=enabled), self.machine(program) as machine:
                    machine.set_register("b0", enabled)
                    state = machine.run(100)
                    self.assertEqual(state["status"], "returned")
                    r = state["registers"]
                    self.assertEqual((r["a4"], r["a6"], r["b5"]), (0, 22, 0x1020 if enabled else 0))
                    rows.append(state["cycles"])
            self.assertEqual(rows[0], rows[1])   # the same wait, executed or not
            self.assertEqual(rows[0], 13)        # branch, ADDKPC + 4, target packet, return + 5

    def test_counted_branches_include_zero_and_preserve_negative_counter(self):
        for op in ("bdec", "bpos"):
            program = Program({0x1000: ([f"[a0] {op} .S1 00001100,a6"], 0x1004, False),
                               0x1004: (["nop 5"], 0x1008, False),
                               0x1008: (["mvk .S1 11,a4"], 0x100c, False),
                               0x100c: (["b .S2 b3"], 0x1010, False),
                               0x1010: (["nop 5"], 0x1014, False),
                               0x1100: (["mvk .S1 22,a4"], 0x1104, False),
                               0x1104: (["b .S2 b3"], 0x1108, False),
                               0x1108: (["nop 5"], 0x110c, False)})
            for enabled, counter in ((0, 7), (1, 0), (1, 7), (1, 0xffffffff), (1, 0x80000000)):
                taken = bool(enabled and counter < 0x80000000)
                with self.subTest(op=op, enabled=enabled, counter=counter), self.machine(program) as machine:
                    machine.set_register("a0", enabled)
                    machine.set_register("a6", counter)
                    state = machine.run(100)
                    self.assertEqual(state["registers"]["a4"], 22 if taken else 11)
                    self.assertEqual(state["registers"]["a6"], (counter - (taken and op == "bdec")) & 0xffffffff)

    def test_double_precision_results_and_staggered_destination_words(self):
        operations = [("adddp .L1 a1:a0,a3:a2,a5:a4", 3.75, 6),
                      ("subdp .L1 a1:a0,a3:a2,a5:a4", -1.25, 6),
                      ("mpydp .M1 a1:a0,a3:a2,a5:a4", 3.125, 9)]
        for text, answer, delay in operations:
            program = self.serial([text, "nop 9", "nop"])
            snapshots = []
            for sliced in (False, True):
                with self.subTest(text=text, sliced=sliced), self.machine(program) as machine:
                    x, y = struct.unpack("<Q", struct.pack("<d", 1.25))[0], struct.unpack("<Q", struct.pack("<d", 2.5))[0]
                    for reg, value in {"a0": x & 0xffffffff, "a1": x >> 32, "a2": y & 0xffffffff,
                                       "a3": y >> 32, "a4": 0x12345678, "a5": 0x87654321}.items():
                        machine.set_register(reg, value)
                    if sliced:
                        state = machine.run(delay - 1)
                        self.assertEqual(state["registers"]["a4"], 0x12345678)
                        state = machine.run(1)
                        self.assertEqual(state["registers"]["a4"], 0)
                        self.assertEqual(state["registers"]["a5"], 0x87654321)
                        state = machine.run(1)
                    state = machine.run(100)
                    bits = state["registers"]["a4"] | state["registers"]["a5"] << 32
                    self.assertEqual(struct.unpack("<d", struct.pack("<Q", bits))[0], answer)
                    snapshots.append(state)
            self.assertEqual(snapshots[0], snapshots[1])

    def test_double_precision_high_sources_are_read_in_later_cycles(self):
        # ADDDP reads low halves in E1 and high halves in E2. The previous packet's
        # SPDP writes A1 at that E2 boundary; reading the complete pair in E1 fails.
        program = self.serial(["spdp .S1 a6,a1:a0", "adddp .L1 a1:a0,a3:a2,a5:a4", "nop 9"])
        with self.machine(program) as machine:
            machine.set_register("a6", struct.unpack("<I", struct.pack("<f", 1.5))[0])
            machine.set_register("a1", 0x40000000)  # old high half encodes 2.0
            machine.set_register("a3", 0x3ff00000)  # other operand 1.0
            state = machine.run(100)
            bits = state["registers"]["a4"] | state["registers"]["a5"] << 32
            self.assertEqual(struct.unpack("<d", struct.pack("<Q", bits))[0], 2.5)

    def test_two_branches_remain_in_flight_across_slices(self):
        program = Program({0x1000: (["b .S2 00001100"], 0x1004, False),
                           0x1004: (["b .S2 00001200"], 0x1008, False),
                           0x1008: (["nop 4"], 0x100c, False),
                           0x1100: (["mvk .S1 11,a6"], 0x1104, False),
                           0x1200: (["b .S2 b3"], 0x1204, False),
                           0x1204: (["nop 5"], 0x1208, False)})
        with self.machine(program) as machine:
            state = machine.run(2)
            self.assertEqual(state["pending_branches"], 2)
            while state["status"] == "budget":
                state = machine.run(1)
            self.assertEqual(state["registers"]["a6"], 11)
            self.assertEqual(state["cycles"], 13)

    def test_callp_links_in_a3_and_preserves_same_packet_arguments(self):
        program = Program({0x1000: (["callp .S1 00001100,a3", "mvk .L2 12,b4"], 0x1008, False),
                           0x1008: (["b .S2 b3"], 0x100c, False),
                           0x100c: (["nop 5"], 0x1010, False),
                           0x1100: (["mv .L1X b4,a4"], 0x1104, False),
                           0x1104: (["b .S1 a3"], 0x1108, False),
                           0x1108: (["nop 5"], 0x110c, False)})
        with self.machine(program) as machine:
            state = machine.run(1)
            self.assertEqual(state["idle_cycles"], 5)
            while state["status"] == "budget":
                state = machine.run(1)
            self.assertEqual(state["registers"]["a4"], 12)
            self.assertEqual(state["registers"]["a3"], 0x1008)

    def test_memory_post_update_signed_load_and_doubleword(self):
        program = self.serial(["ldb .D1T1 *a0++[1],a1", "lddw .D2T1 *b0,a5:a4", "nop 4"])
        with self.machine(program) as machine:
            machine.write(0x4000, bytes.fromhex("ff000000000000008877665544332211"))
            machine.set_register("a0", 0x4000)
            machine.set_register("b0", 0x4008)
            state = machine.run(100)
            self.assertEqual(state["registers"]["a0"], 0x4001)
            self.assertEqual(state["registers"]["a1"], 0xffffffff)
            self.assertEqual(state["registers"]["a4"], 0x55667788)
            self.assertEqual(state["registers"]["a5"], 0x11223344)

    def test_alias_to_another_offset_within_a_page_reads_and_writes_its_target(self):
        # A fetch-aligned alias need not keep the offset within the RAM page; repeated accesses
        # (the second through whatever the first cached) must reach the same bytes.
        program = self.serial(["ldw .D1T1 *a0,a1", "nop 4", "ldw .D1T1 *a0,a2", "stw .D1T1 a3,*+a0(4)",
                               "stw .D1T1 a3,*+a0(8)", "nop 4"])
        with self.machine(program) as machine:
            machine.map(0x6000, 8192, 3)
            machine.alias(0x8000, 0x6020, 4096)
            machine.write(0x6000, struct.pack("<I", 0x11111111))
            machine.write(0x6020, struct.pack("<I", 0x22222222))
            machine.reset(0x1000)
            machine.set_register("a0", 0x8000); machine.set_register("a3", 0x33333333)
            state = machine.run(100)
            self.assertEqual((state["registers"]["a1"], state["registers"]["a2"]), (0x22222222, 0x22222222))
            self.assertEqual(machine.read(0x6000, 12), struct.pack("<III", 0x11111111, 0, 0))
            self.assertEqual(machine.read(0x6024, 8), struct.pack("<II", 0x33333333, 0x33333333))

    def test_doubleword_copy_crosses_ram_pages_and_both_alias_boundaries(self):
        program = self.serial(["ldndw .D1T1 *a0[0],a5:a4", "nop 4",
                               "stndw .D2T1 a5:a4,*b0[0]"])
        with self.machine(program) as machine:
            machine.map(0x5000, 32, 3)
            machine.alias(0x5020, 0x4000, 32)
            machine.map(0x5040, 32, 3)
            machine.map(0x9000, 4096, 3)
            machine.write(0x4000, bytes(range(32)))
            machine.write(0x4ffc, b"abcd")
            machine.write(0x5000, bytes(range(32, 64)))
            machine.write(0x5040, bytes(range(64, 96)))
            vectors = {0x4000: bytes(range(8)), 0x401c: bytes(range(28, 32)) + bytes(4),
                       0x4ffc: b"abcd" + bytes(range(32, 36)),
                       0x501c: bytes(range(60, 64)) + bytes(range(4)),
                       0x503c: bytes(range(28, 32)) + bytes(range(64, 68))}
            for address, expected in vectors.items():
                with self.subTest(load=hex(address)):
                    machine.reset(0x1000)
                    machine.set_register("a0", address)
                    machine.set_register("b0", 0x9000)
                    self.assertEqual(machine.run(100)["status"], "returned")
                    self.assertEqual(machine.read(0x9000, 8), expected)
            for address, halves in ((0x4ffc, (0x4ffc, 0x5000)), (0x501c, (0x501c, 0x4000)),
                                    (0x503c, (0x401c, 0x5040))):
                with self.subTest(store=hex(address)):
                    machine.write(0x9000, b"12345678")
                    machine.reset(0x1000)
                    machine.set_register("a0", 0x9000)
                    machine.set_register("b0", address)
                    self.assertEqual(machine.run(100)["status"], "returned")
                    self.assertEqual(machine.read(halves[0], 4), b"1234")
                    self.assertEqual(machine.read(halves[1], 4), b"5678")

    def test_unmapped_mmio_and_unsupported_instructions_fault(self):
        for text in ("ldw .D1T1 *a0,a4", "spkernelr"):
            with self.subTest(text=text), self.machine(self.serial([text])) as machine:
                machine.set_register("a0", 0x01f0e000)
                with self.assertRaises(CoreFault):
                    machine.run(100)
                self.assertEqual(machine.state()["status"], "fault")
                self.assertEqual(machine.state()["fault_address"], 0x1000)

    def test_region_permissions_bounds_and_zero_initialized_sparse_ram(self):
        with CPU(self.work, decode=False) as machine:
            machine.map(0xc0000000, 128 * 1024 * 1024, 3)
            self.assertEqual(machine.read(0xc7000000, 16), bytes(16))
            with self.assertRaises(ValueError):
                machine.read(0xc8000000, 1)
            with self.assertRaises(ValueError):
                machine.map(0xc7000000, 4096, 3)
            with self.assertRaises(ValueError):
                machine.map(0xfffffff0, 32, 3)
            machine.reset(0xc0000000)
            with self.assertRaises(CoreFault):
                machine.run(1)
        program = self.serial(["stw .D1T1 a4,*a0"])
        with self.machine(program) as machine:
            machine.map(0x8000, 32, 1)
            machine.set_register("a0", 0x8000)
            with self.assertRaises(CoreFault):
                machine.run(1)

    def test_sparse_ram_guest_copy_across_pointer_groups_and_top_of_address_space(self):
        program = self.serial(["ldndw .D1T1 *a0[0],a5:a4", "nop 4",
                               "stndw .D2T1 a5:a4,*b0[0]"])
        with self.machine(program) as machine:
            machine.map(0x003ff000, 8192, 3)
            machine.map(0xfffff000, 4096, 3)
            machine.alias(0x80000000, 0x003fffe0, 64)
            machine.alias(0x90000000, 0xffffffe0, 32)
            self.assertEqual(machine.read(0xfffffff8, 8), bytes(8))
            # The next 4 MiB pointer group is absent, then allocated independently.
            machine.write(0x003ffffc, b"abcd")
            self.assertEqual(machine.read(0x8000001c, 8), b"abcd" + bytes(4))
            machine.write(0x00400000, b"efgh")
            machine.set_register("a0", 0x8000001c)
            machine.set_register("b0", 0x90000018)
            state = machine.run(100)
            self.assertEqual(state["status"], "returned")
            self.assertEqual((state["registers"]["a4"], state["registers"]["a5"]),
                             (0x64636261, 0x68676665))
            self.assertEqual(machine.read(0xfffffff8, 8), b"abcdefgh")
            self.assertEqual(machine.read(0x90000018, 8), b"abcdefgh")
            self.assertEqual(machine.read(0x00401000 - 8, 8), bytes(8))
            with self.assertRaises(ValueError):
                machine.read(0x00401000, 1)
            with self.assertRaises(ValueError):
                machine.read(0xfffffffc, 8)

    def test_swe_enters_the_exception_vector_and_b_nrp_returns(self):
        # SWE with TSR.GEE set: EFR.SXF, NRP = the next packet, NTSR = TSR, TSR.EXC, entry at ISTP + 0x20;
        # ECR clears EFR and B NRP restores TSR (SYS/BIOS c64p Exception.xdc bit values).
        main = ["mvk .S2 0x1400,b0", "mvc .S2 b0,istp", "mvk .S2 4,b1", "mvc .S2 b1,tsr", "swe",
                "mvk .S1 7,a4", "mvc .S2 tsr,b8", "mvc .S2 efr,b9", "b .S2 b3", "nop 5"]
        handler = ["mvc .S2 efr,b4", "mvc .S2 nrp,b5", "mvc .S2 tsr,b6", "mvc .S2 ntsr,b7",
                   "mvk .S2 1,b0", "mvc .S2 b0,ecr", "b .S2 nrp", "nop 5"]
        entries = {0x1000 + i * 4: ([t], 0x1004 + i * 4, False) for i, t in enumerate(main)}
        entries.update({0x1420 + i * 4: ([t], 0x1424 + i * 4, False) for i, t in enumerate(handler)})
        with self.machine(Program(entries)) as machine:
            state = machine.run(200)
            r = state["registers"]
            self.assertEqual(state["status"], "returned")
            self.assertEqual(r["a4"], 7)                        # resumed after SWE
            self.assertEqual((r["b4"], r["b5"]), (1, 0x1014))   # EFR.SXF; NRP = the packet after SWE
            self.assertEqual(r["b6"] & 0x404, 0x404)            # TSR.EXC and GEE in the handler
            self.assertEqual((r["b7"], r["b8"], r["b9"]), (4, 4, 0))   # NTSR; TSR restored; EFR cleared

    def test_idle_waits_for_an_interrupt_and_resumes_after_it(self):
        # SPRUFE8B IDLE: a multicycle NOP that ends when an interrupt is serviced; the handler returns to the
        # instruction after it. Interrupt 4's vector is at ISTP + 0x80.
        main = ["mvk .S2 0x1400,b0", "mvc .S2 b0,istp", "mvk .S1 1,a4", "idle", "mvk .S1 2,a4", "b .S2 b3", "nop 5"]
        handler = ["mvc .S2 irp,b5", "add .L1 a6,1,a6", "b .S2 irp", "nop 5"]
        entries = {0x1000 + i * 4: ([t], 0x1004 + i * 4, False) for i, t in enumerate(main)}
        entries.update({0x1480 + i * 4: ([t], 0x1484 + i * 4, False) for i, t in enumerate(handler)})
        for sliced in (False, True):
            with self.subTest(sliced=sliced), self.machine(Program(entries)) as machine:
                for register, value in (("csr", 0x101), ("ier", 0x13)):
                    machine.set_register(register, value)
                state = machine.run(5000) if not sliced else None
                for _ in range(300 if sliced else 0):
                    state = machine.run(17)
                self.assertEqual((state["status"], state["registers"]["a4"], state["registers"]["a6"]), ("budget", 1, 0))
                waited = state["cycles"]
                machine.set_register("ifr", 0x10)
                state = machine.run(100)
                r = state["registers"]
                self.assertEqual(state["status"], "returned")
                self.assertEqual((r["a4"], r["a6"], r["b5"]), (2, 1, 0x1010))      # resumed at the instruction after IDLE
                self.assertLess(state["cycles"] - waited, 40)
        # A branch already in flight ends it, as it ends any multicycle NOP.
        program = self.serial(["b .S1 00001020", "idle", "mvk .S1 9,a4", "nop 1", "nop 1", "nop 1", "nop 1", "nop 1", "mvk .S1 5,a5"])
        with self.machine(program) as machine:
            state = machine.run(100)
            self.assertEqual((state["status"], state["registers"]["a4"], state["registers"]["a5"], state["cycles"]), ("returned", 0, 5, 13))

    def test_interrupt_inside_a_multicycle_nop_returns_to_the_next_packet(self):
        # SPRUFE8B 5.5.4: a multicycle NOP is interrupted like any instruction, but once its first cycle has run
        # the return address is the next packet's, so the rest of the NOP is not executed after the handler.
        main = ["mvk .S2 0x1400,b0", "mvc .S2 b0,istp", "mvk .S1 1,a4", "nop 9", "mvk .S1 2,a4", "b .S2 b3", "nop 5"]
        handler = ["mvc .S2 irp,b5", "add .L1 a6,1,a6", "b .S2 irp", "nop 5"]
        entries = {0x1000 + i * 4: ([t], 0x1004 + i * 4, False) for i, t in enumerate(main)}
        entries.update({0x1480 + i * 4: ([t], 0x1484 + i * 4, False) for i, t in enumerate(handler)})
        totals = {}
        # Requested after `before` cycles: None never, 3 as the NOP is about to issue, 6 three cycles into it.
        for before, irp in ((None, 0), (3, 0x100c), (6, 0x1010)):
            with self.subTest(before=before), self.machine(Program(entries)) as machine:
                for register, value in (("csr", 0x101), ("ier", 0x13)):
                    machine.set_register(register, value)
                if before is not None:
                    self.assertEqual(machine.run(before)["status"], "budget")
                    machine.set_register("ifr", 0x10)
                state = machine.run(200)
                r = state["registers"]
                self.assertEqual((state["status"], r["a4"], r["a6"], r["b5"]), ("returned", 2, int(before is not None), irp))
                totals[before] = state["cycles"]
        # The handler and its entry take 17 cycles. Before the NOP that is all it adds; inside it, the 6 cycles
        # of the NOP still to run are dropped.
        self.assertEqual((totals[3] - totals[None], totals[6] - totals[None]), (17, 17 - 6))

    def test_swenr_enters_at_rep_and_leaves_nrp_and_ntsr_alone(self):
        # SPRUFE8B SWENR: as SWE, but NRP and NTSR keep their values, TSR.IB is set and entry is at REP.
        main = ["mvk .S2 0x1500,b0", "mvc .S2 b0,rep", "mvk .S2 4,b1", "mvc .S2 b1,tsr", "swenr", "mvk .S1 7,a4", "nop 9"]
        handler = ["mvc .S2 efr,b4", "mvc .S2 nrp,b5", "mvc .S2 tsr,b6", "mvc .S2 ntsr,b7", "b .S2 b3", "nop 5"]
        entries = {0x1000 + i * 4: ([t], 0x1004 + i * 4, False) for i, t in enumerate(main)}
        entries.update({0x1500 + i * 4: ([t], 0x1504 + i * 4, False) for i, t in enumerate(handler)})
        with self.machine(Program(entries)) as machine:
            for register, value in (("nrp", 0x1234), ("ntsr", 0x55)):
                machine.set_register(register, value)
            state = machine.run(200)
            r = state["registers"]
            self.assertEqual(state["status"], "returned")
            self.assertEqual((r["a4"], r["b4"], r["b5"], r["b7"]), (0, 1, 0x1234, 0x55))   # never resumed; EFR.SXF; NRP, NTSR kept
            self.assertEqual(r["b6"] & 0x8404, 0x8404)                                      # TSR.IB, EXC and GEE

    def test_packed_16_bit_multiplies_and_pack_follow_the_manual(self):
        # SPRUFE8B MPYLH, MPYLHU (1 delay slot), DOTP2, MPY2 (3 delay slots) and DPACK2 (none), which
        # cl6x emits for 16-bit loops. Values are worked by hand from the manual's definitions; b5
        # copies the destination in the last delay slot (still the old value) and b6 one cycle later.
        old = 0x5a5a5a5a
        for text, slots, a0, a1, expected in (
                ("mpylh .M1 a0,a1,a2", 1, 0x1234fffe, 0xfffd5678, (6,)),                    # -2 x -3
                ("mpylhu .M1 a0,a1,a2", 1, 0x1234fffe, 0xfffd5678, (0xfffb0006,)),           # 65534 x 65533
                ("dotp2 .M1 a0,a1,a2", 3, 0x7fff8000, 0x7fff8000, (0x7fff0001,)),            # 32767^2 + 32768^2
                ("dotp2 .M1 a0,a1,a2", 3, 0x0003fffe, 0x00050007, (1,)),                     # 3 x 5 + -2 x 7
                ("dotp2 .M1 a0,a1,a3:a2", 3, 0x80008000, 0x80008000, (0x80000000, 0)),       # the manual's overflow note
                ("dotp2 .M1 a0,a1,a3:a2", 3, 0x0001fff0, 0x00010100, (0xfffff001, 0xffffffff)),  # 1 - 4096, sign-extended
                ("mpy2 .M1 a0,a1,a3:a2", 3, 0x0003fffe, 0x00050007, (0xfffffff2, 15)),       # low: -2 x 7, high: 3 x 5
                ("dpack2 .L1 a0,a1,a3:a2", 0, 0x11223344, 0x55667788, (0x33447788, 0x11225566))):
            wait = [f"nop {slots - 1}"] if slots > 1 else []
            late = ["mv .L2X a2,b5"] if slots else []
            program = self.serial([text, *wait, *late, "mv .L2X a2,b6", "nop 1"])
            with self.subTest(text=text, a0=hex(a0)), self.machine(program) as machine:
                machine.reset(0x1000)
                for register, value in (("a0", a0), ("a1", a1), ("a2", old), ("a3", old)):
                    machine.set_register(register, value)
                state = machine.run(100)
                r = state["registers"]
                self.assertEqual(state["status"], "returned")
                self.assertEqual((r["a2"], r["b6"]), (expected[0], expected[0]))
                if slots:
                    self.assertEqual(r["b5"], old)
                self.assertEqual(r["a3"], expected[1] if len(expected) > 1 else old)

    def test_packed_saturating_and_half_word_instructions_give_the_manuals_example_values(self):
        # The worked examples of SPRUFE8B for the instructions GCC emits for 16-bit multiplies, saturating
        # arithmetic, small vectors and byte swaps (the stock firmware uses none of them). a0 and a1 are the
        # sources, a2 or a3:a2 the destination; b5 copies it in the last delay slot and b6 once it has landed.
        old = 0x5a5a5a5a
        for text, slots, a0, a1, expected in (
                ("abs2 .L1 a0,a2", 0, 0xff684e3d, 0, (0x00984e3d,)),
                ("abs2 .L1 a0,a2", 0, 0x3ff6f105, 0, (0x3ff60efb,)),
                ("abs2 .L1 a0,a2", 0, 0x80008000, 0, (0x7fff7fff,)),                      # its rule 3
                ("add2 .L1 a0,a1,a2", 0, 0x002137e1, 0x039ae4b8, (0x03bb1c99,)),
                ("sub2 .L1 a0,a1,a2", 0, 0x11056e30, 0x11056980, (0x000004b0,)),
                ("sub2 .L1 a0,a1,a2", 0, 0xf23a3789, 0x04b86732, (0xed82d057,)),
                ("add4 .L1 a0,a1,a2", 0, 0xff684e3d, 0x3ff6f105, (0x3e5e3f42,)),
                ("add4 .L1 a0,a1,a2", 0, 0x4ae2d31f, 0x321ac128, (0x7cfc9447,)),
                ("sub4 .L1 a0,a1,a2", 0, 0x3789f23a, 0x04b84975, (0x33d1a9c5,)),
                ("sadd2 .S1 a0,a1,a2", 0, 0x5789f23a, 0x74b84975, (0x7fff3baf,)),
                ("sadd2 .S1 a0,a1,a2", 0, 0x0124847c, 0x01a6a051, (0x02ca8000,)),
                ("ssub2 .L1 a0,a1,a2", 0, 0x00070005, 0xffffffff, (0x00080006,)),
                ("ssub2 .L1 a0,a1,a2", 0, 0x00070005, 0x8000ffff, (0x7fff0006,)),
                ("saddu4 .S1 a0,a1,a2", 0, 0x5789f23a, 0x74b84975, (0xcbffffaf,)),
                ("saddu4 .S1 a0,a1,a2", 0, 0x147c0124, 0xa05101a6, (0xb4cd02ca,)),
                ("saddus2 .S1 a0,a1,a2", 0, 0x5789f23a, 0x74b84975, (0xcc41ffff,)),
                ("saddus2 .S1 a0,a1,a2", 0, 0x147c0124, 0xa05101a6, (0x000002ca,)),
                ("max2 .L1 a0,a1,a2", 0, 0x3789f23a, 0x04b84975, (0x37894975,)),
                ("max2 .L1 a0,a1,a2", 0, 0x01242451, 0x01a6a051, (0x01a62451,)),
                ("min2 .L1 a0,a1,a2", 0, 0x3789f23a, 0x04b84975, (0x04b8f23a,)),
                ("min2 .L1 a0,a1,a2", 0, 0x01248003, 0x0a378001, (0x01248001,)),
                ("avg2 .M1 a0,a1,a2", 1, 0x61984357, 0x7582ae15, (0x6b8df8b6,)),
                ("avgu4 .M1 a0,a1,a2", 1, 0x1a2e5f4e, 0x9ef26e3f, (0x5c906747,)),
                ("bitr .M1 a0,a2", 1, 0xa6e2c179, 0, (0x9e834765,)),
                ("swap4 .L1 a0,a2", 0, 0x9e526e30, 0, (0x529e306e,)),
                ("shlmb .L1 a0,a1,a2", 0, 0x3789f23a, 0x04b84975, (0xb8497537,)),
                ("shrmb .L1 a0,a1,a2", 0, 0x3789f23a, 0x04b84975, (0x3a04b849,)),
                ("dpackx2 .L1 a0,a1,a3:a2", 0, 0x87654321, 0x12345678, (0x43211234, 0x56788765)),
                ("dpackx2 .L1 a0,a1,a3:a2", 0, 0x3fff8000, 0x40007777, (0x80004000, 0x77773fff)),
                ("mpyh .M1 a0,a1,a2", 1, 0x00230000, 0xffa71234, (0xfffff3d5,)),
                ("mpyhu .M1 a0,a1,a2", 1, 0x00230000, 0xffa71234, (0x0022f3d5,)),
                ("mpyhsu .M1 a0,a1,a2", 1, 0x00230000, 0xffa7ffff, (0x0022f3d5,)),
                ("mpyhl .M1 a0,a1,a2", 1, 0x008a003e, 0x21ff00a7, (0x00005a06,)),
                # No example in the manual for these six; worked from its definitions with -2 or 65534 and -3 or 65533.
                ("mpyhus .M1 a0,a1,a2", 1, 0xfffe1111, 0xfffd2222, (0xfffd0006,)),          # 65534 x -3
                ("mpyhlu .M1 a0,a1,a2", 1, 0xfffe1111, 0x2222fffd, (0xfffb0006,)),          # 65534 x 65533
                ("mpyhuls .M1 a0,a1,a2", 1, 0xfffe1111, 0x2222fffd, (0xfffd0006,)),         # 65534 x -3
                ("mpyhslu .M1 a0,a1,a2", 1, 0xfffe1111, 0x2222fffd, (0xfffe0006,)),         # -2 x 65533
                ("mpyluhs .M1 a0,a1,a2", 1, 0x1111fffe, 0xfffd2222, (0xfffd0006,)),         # 65534 x -3
                ("mpylshu .M1 a0,a1,a2", 1, 0x1111fffe, 0xfffd2222, (0xfffe0006,)),         # -2 x 65533
                ("mpyu4 .M1 a0,a1,a3:a2", 3, 0x6832c193, 0xb1742cab, (0x212c6231, 0x47e816a8)),
                ("mpyu4 .M1 a0,a1,a3:a2", 3, 0x3de6507f, 0xc3560244, (0x00a021bc, 0x2e774d44)),
                ("mpysu4 .M1 a0,a1,a3:a2", 3, 0x6a321193, 0xb1746ca4, (0x072cba2c, 0x494a16a8)),
                ("mpysu4 .M1 a0,a1,a3:a2", 3, 0x3ff65010, 0xc3560244, (0x00a00440, 0x2ffdfca4)),
                ("smpy2 .M1 a0,a1,a3:a2", 3, 0x6a321193, 0xb1746ca4, (0x0eea8c58, 0xbed56150)),
                ("smpy2 .M1 a0,a1,a3:a2", 3, 0x12343497, 0x21ff50a7, (0x2122fd02, 0x04d5ab98)),
                ("smpy .M1 a0,a1,a2", 1, 0x00000123, 0x01e0fa81, (0xfff38146,)),
                ("smpyhl .M1 a0,a1,a2", 1, 0x008a0000, 0x000000a7, (0x0000b40c,)),
                ("smpyh .M1 a0,a1,a2", 1, 0xfffe0000, 0x00030000, (0xfffffff4,)),           # -2 x 3, doubled (no example)
                ("sadd .L1 a0,a1,a2", 0, 0x5a2e51a3, 0x012a3fa2, (0x5b589145,)),
                ("ssub .L1 a0,a1,a2", 0, 0x436771f2, 0x5a2e51a3, (0xe939204f,)),
                ("shl .S1 a0,a1,a3:a2", 0, 0x87654321, 12, (0x54321000, 0x00000076))):       # 32 bits in, 40 out
            wait = [f"nop {slots - 1}"] if slots > 1 else []
            late = ["mv .L2X a2,b5"] if slots else []
            program = self.serial([text, *wait, *late, "mv .L2X a2,b6", "nop 1", "mvc .S2 csr,b7"])
            with self.subTest(text=text, a0=hex(a0)), self.machine(program) as machine:
                machine.reset(0x1000)
                for register, value in (("a0", a0), ("a1", a1), ("a2", old), ("a3", old)):
                    machine.set_register(register, value)
                state = machine.run(100)
                r = state["registers"]
                self.assertEqual(state["status"], "returned")
                self.assertEqual((hex(r["a2"]), hex(r["b6"])), (hex(expected[0]), hex(expected[0])))
                if slots:
                    self.assertEqual(r["b5"], old)
                self.assertEqual(hex(r["a3"]), hex(expected[1] if len(expected) > 1 else old))
                self.assertEqual(r["b7"] & 0x200, 0)                 # none of these saturates a 32-bit result

    def test_the_rest_of_the_packed_and_fixed_point_set_gives_the_manuals_example_values(self):
        # SPRUFE8B's worked examples for the instructions no compiler here has emitted yet (hand-written
        # assembly or a library could). Sources a0 and a1 (a pair source is a5:a4, a third operand a6), result
        # in a2 or a3:a2; `flag` is CSR.SAT afterwards.
        old = 0x5a5a5a5a
        for text, slots, a0, a1, expected, flag in (
                ("cmpeq2 .S1 a0,a1,a2", 0, 0x11056e30, 0x11056980, (2,), 0),
                ("cmpeq2 .S1 a0,a1,a2", 0, 0xf23a3789, 0x04b83789, (1,), 0),
                ("cmpeq4 .S1 a0,a1,a2", 0, 0x023a4e1c, 0x02b84e76, (0xa,), 0),
                ("cmpeq4 .S1 a0,a1,a2", 0, 0xf23a3789, 0x04b83789, (3,), 0),
                ("cmpgt2 .S1 a0,a1,a2", 0, 0x11056e30, 0x11056980, (1,), 0),
                ("cmpgt2 .S1 a0,a1,a2", 0, 0x01a62451, 0x0124a051, (3,), 0),
                ("cmpgtu4 .S1 a0,a1,a2", 0, 0x253a1ce4, 0x02b84e76, (9,), 0),
                ("cmpgtu4 .S1 a0,a1,a2", 0, 0x89f23a37, 0x048f1789, (0xe,), 0),
                ("xpnd2 .M1 a0,a2", 1, 0xb1746ca1, 0, (0x0000ffff,), 0),
                ("xpnd4 .M1 a0,a2", 1, 0xb1746ca4, 0, (0x00ff0000,), 0),
                ("xpnd4 .M1 a0,a2", 1, 0x0000000a, 0, (0xff00ff00,), 0),
                ("bitc4 .M1 a0,a2", 1, 0x9e526e30, 0, (0x05030502,), 0),
                ("packh2 .L1 a0,a1,a2", 0, 0x3789f23a, 0x04b84975, (0x378904b8,), 0),
                ("packh4 .L1 a0,a1,a2", 0, 0x3789f23a, 0x04b84975, (0x37f20449,), 0),
                ("packh4 .L1 a0,a1,a2", 0, 0x01242451, 0x01a6a051, (0x012401a0,), 0),
                ("unpkhu4 .L1 a0,a2", 0, 0x9e526e30, 0, (0x009e0052,), 0),
                ("unpklu4 .L1 a0,a2", 0, 0x9e526e30, 0, (0x006e0030,), 0),
                ("spack2 .S1 a0,a1,a2", 0, 0x3789f23a, 0x04b84975, (0x7fff7fff,), 0),
                ("spack2 .S1 a0,a1,a2", 0, 0xa1242451, 0x01a6a051, (0x80007fff,), 0),
                ("spacku4 .S1 a0,a1,a2", 0, 0x3789f23a, 0x04b84975, (0xff00ffff,), 0),
                ("spacku4 .S1 a0,a1,a2", 0, 0xa1242451, 0x01a6a051, (0x00ffff00,), 0),
                ("shru2 .S1 a0,a1,a2", 0, 0xa6e2c179, 0x14583b69, (0x00530060,), 0),
                ("shru2 .S1 a0,a1,a2", 0, 0x000a87af, 15, (0x00000001,), 0),
                ("shru2 .S1 a0,a1,a2", 0, 0xffffffff, 16, (0,), 0),                        # its note: 16 to 31 clear dst
                ("subabs4 .L1 a0,a1,a2", 0, 0x3789f23a, 0x04b84975, (0x332fa93b,), 0),
                ("addsub2 .L1 a0,a1,a3:a2", 0, 0x0700c005, 0xffff0001, (0x0701c004, 0x06ffc006), 0),
                ("addsub2 .L1 a0,a1,a3:a2", 0, 0x90008000, 0x80009000, (0x1000f000, 0x10001000), 0),
                ("saddsub .L1 a0,a1,a3:a2", 0, 0x0700c005, 0xffffffff, (0x0700c006, 0x0700c004), 0),
                ("saddsub .L1 a0,a1,a3:a2", 0, 0x7fffffff, 0x00000001, (0x7ffffffe, 0x7fffffff), 0x200),
                ("saddsub .L1 a0,a1,a3:a2", 0, 0x80000000, 0x00000001, (0x80000000, 0x80000001), 0x200),
                ("saddsub2 .L1 a0,a1,a3:a2", 0, 0x0700c005, 0xffff0001, (0x0701c004, 0x06ffc006), 0),
                ("saddsub2 .L1 a0,a1,a3:a2", 0, 0x7fff8000, 0xffffffff, (0x7fff8001, 0x7ffe8000), 0),
                ("dotpn2 .M1 a0,a1,a2", 3, 0x3629274a, 0x325c8036, (0x1e442f20,), 0),
                ("dotpn2 .M1 a0,a1,a2", 3, 0x3ff65010, 0xb1c30244, (0xebbe6a22,), 0),
                ("dotpnrsu2 .M1 a0,a1,a2", 3, 0x3629274a, 0x325c8036, (0xfffff6fa,), 0),
                ("dotpnrsu2 .M1 a0,a1,a2", 3, 0x3ff65010, 0xb1c30244, (0x00002bb4,), 0),
                ("dotprsu2 .M1 a0,a1,a2", 3, 0x3629274a, 0x325c8036, (0x00001e55,), 0),
                ("dotprsu2 .M1 a0,a1,a2", 3, 0xb1c30244, 0x3ff65010, (0xffffed29,), 0),
                ("dotpsu4 .M1 a0,a1,a2", 3, 0x6a321193, 0xb1746ca4, (0x0000214a,), 0),
                ("dotpsu4 .M1 a0,a1,a2", 3, 0x3ff65010, 0xc3560244, (0x00003181,), 0),
                ("dotpu4 .M1 a0,a1,a2", 3, 0x6a321193, 0xb1746ca4, (0x0000c54a,), 0),
                ("mpy2ir .M1 a0,a1,a3:a2", 3, 0x80008001, 0x80000000, (0x7fff0000, 0x7fffffff), 0x200),
                ("mpy2ir .M1 a0,a1,a3:a2", 3, 0x87654321, 0x12345678, (0x098c16c1, 0xeed8e38f), 0),
                ("mpyhir .M1 a0,a1,a2", 3, 0x12343497, 0x21ff50a7, (0x04d5b710,), 0),
                ("mpylir .M1 a0,a1,a2", 3, 0x12343497, 0x21ff50a7, (0x0df7d3f5,), 0),
                ("smpy32 .M1 a0,a1,a2", 3, 0x87654321, 0x12345678, (0xeed8ed1a,), 0),
                ("smpy32 .M1 a0,a1,a2", 3, 0x80000000, 0x80000000, (0x7fffffff,), 0x200),
                # The manual prints FDBA 2468h; its stated operation, msb16(sat(src1 << 1)), gives FDB9h, and the other
                # half and its second example follow the stated operation.
                ("rpack2 .S1 a0,a1,a2", 0, 0xfedcba98, 0x12345678, (0xfdb92468,), 0),
                ("rpack2 .S1 a0,a1,a2", 0, 0x87654321, 0x12345678, (0x80002468,), 0x200),
                ("sshvl .M1 a0,a1,a2", 1, 0xfffff000, 0xffffffe1, (0xffffffff,), 0),
                ("sshvl .M1 a0,a1,a2", 1, 0xf14c2108, 0x0000001f, (0x80000000,), 0x200),
                ("sshvl .M1 a0,a1,a2", 1, 0x187a65fc, 0xffffffff, (0x0c3d32fe,), 0),         # the manual prints 03CD 32FEh here
                ("sshvr .M1 a0,a1,a2", 1, 0xfffff000, 0xffffffe1, (0x80000000,), 0x200),
                ("sshvr .M1 a0,a1,a2", 1, 0xf14c2108, 0x0000001f, (0xffffffff,), 0),
                ("sshvr .M1 a0,a1,a2", 1, 0x187a65fc, 0xffffffff, (0x30f4cbf8,), 0),
                ("cmpy .M1 a0,a1,a3:a2", 3, 0x00080004, 0x00090002, (0x00000034, 0x00000040), 0),
                ("cmpy .M1 a0,a1,a3:a2", 3, 0x7fff7fff, 0x7fff8000, (0xffff8001, 0x7ffe8001), 0),
                ("cmpy .M1 a0,a1,a3:a2", 3, 0x80008000, 0x80008000, (0x7fffffff, 0x00000000), 0x200),
                ("cmpyr .M1 a0,a1,a2", 3, 0x08000400, 0x09000200, (0x00400034,), 0),
                ("cmpyr .M1 a0,a1,a2", 3, 0x7fff7fff, 0x7fff8000, (0x7fff0000,), 0),
                ("cmpyr .M1 a0,a1,a2", 3, 0x80008000, 0x80008000, (0x00007fff,), 0x200),
                ("cmpyr1 .M1 a0,a1,a2", 3, 0x08000400, 0x09000200, (0x00800068,), 0),
                ("cmpyr1 .M1 a0,a1,a2", 3, 0x80008000, 0x80008000, (0x00007fff,), 0x200),
                ("ddotp4 .M1 a0,a1,a3:a2", 3, 0x00050003, 0x01020304, (0x0000001b, 0x0000000b), 0),
                ("ddotp4 .M1 a0,a1,a3:a2", 3, 0x80008000, 0x80807f7f, (0xff810000, 0x00800000), 0),
                ("deal .M1 a0,a2", 1, 0x9e526e30, 0, (0xb1746ca4,), 0),
                ("shfl .M1 a0,a2", 1, 0xb1746ca4, 0, (0x9e526e30,), 0),
                ("shfl3 .L1 a0,a1,a3:a2", 0, 0x87654321, 0x12345678, (0x7e179306, 0x00008c11), 0),
                ("xormpy .M1 a0,a1,a2", 3, 0x12345678, 0x00000126, (0x1e654210,), 0),
                ("gmpy4 .M1 a0,a1,a2", 3, 0x45230001, 0x57340001, (0x72920001,), 0),        # the reset field: 8 bits, polynomial 1Dh
                ("gmpy4 .M1 a0,a1,a2", 3, 0xfffe021f, 0xfffe0201, (0xe2e3041f,), 0),
                ("mpyi .M1 a0,a1,a2", 8, 0x00345678, 0x00112765, (0xcbca6558,), 0),
                ("mpyid .M1 a0,a1,a3:a2", 9, 0x00345678, 0x00112765, (0xcbca6558, 0x00000381), 0)):
            wait = [f"nop {slots}"] if slots else []
            program = self.serial([text, *wait, "mv .L2X a2,b6", "nop 4", "mvc .S2 csr,b7"])
            with self.subTest(text=text, a0=hex(a0)), self.machine(program) as machine:
                for register, value in (("a0", a0), ("a1", a1), ("a2", old), ("a3", old)):
                    machine.set_register(register, value)
                state = machine.run(100)
                r = state["registers"]
                self.assertEqual(state["status"], "returned")
                self.assertEqual((hex(r["a2"]), hex(r["b6"])), (hex(expected[0]), hex(expected[0])))
                self.assertEqual(hex(r["a3"]), hex(expected[1] if len(expected) > 1 else old))
                self.assertEqual(r["b7"] & 0x200, flag)
        # Sources the table above cannot express: a pair, and the control registers GMPY reads.
        for text, a4, a5, a6, expected, flag in (
                ("ddotph2 .M1 a5:a4,a6,a3:a2", 0x00050003, 0x00020004, 0x00070001, (0x21, 0x12), 0),
                ("ddotph2 .M1 a5:a4,a6,a3:a2", 0x80005678, 0x12348000, 0x80008000, (0x7fffffff, 0x36e60000), 0x200),
                ("ddotph2 .M1 a5:a4,a6,a3:a2", 0x46b416ba, 0xbbaed169, 0x340bf73b, (0xf41b4aff, 0xf3b4faad), 0),
                ("ddotpl2 .M1 a5:a4,a6,a3:a2", 0x00050003, 0x00020004, 0x00070001, (0x26, 0x21), 0),
                ("ddotpl2 .M1 a5:a4,a6,a3:a2", 0x46b416ba, 0xbbaed169, 0x340bf73b, (0x0d984c9a, 0xf41b4aff), 0),
                ("ddotpl2 .M1 a5:a4,a6,a3:a2", 0x80005678, 0x12348000, 0x80008000, (0x14c40000, 0x7fffffff), 0x200),
                ("ddotph2r .M1 a5:a4,a6,a2", 0x46b416ba, 0xbbaed169, 0x340bf73b, (0xf3b5f41b,), 0),
                ("ddotph2r .M1 a5:a4,a6,a2", 0x80008000, 0x80008000, 0x80008001, (0x7fff7fff,), 0x200),
                ("ddotpl2r .M1 a5:a4,a6,a2", 0x46b416ba, 0xbbaed169, 0x340bf73b, (0xf41b0d98,), 0),
                ("ddotpl2r .M1 a5:a4,a6,a2", 0x80005678, 0x12348000, 0x80008001, (0x7fff14c4,), 0x200)):
            program = self.serial([text, "nop 5", "mvc .S2 csr,b7"])
            with self.subTest(text=text, a4=hex(a4)), self.machine(program) as machine:
                for register, value in (("a4", a4), ("a5", a5), ("a6", a6), ("a3", old)):
                    machine.set_register(register, value)
                r = machine.run(100)["registers"]
                self.assertEqual(hex(r["a2"]), hex(expected[0]))
                self.assertEqual(hex(r["a3"]), hex(expected[1] if len(expected) > 1 else old))
                self.assertEqual(r["b7"] & 0x200, flag)
        program = self.serial(["mvc .S2 b0,gplya", "gmpy .M1 a0,a1,a2", "nop 4"])
        with self.machine(program) as machine:
            for register, value in (("b0", 0x87654321), ("a0", 0x12345678), ("a1", 0x126)):
                machine.set_register(register, value)
            self.assertEqual(hex(machine.run(100)["registers"]["a2"]), hex(0xc721a0ef))
        program = self.serial(["rsqrdp .S1 a1:a0,a3:a2", "nop 2"])
        with self.machine(program) as machine:
            machine.set_register("a1", 0x40100000)                       # 4.0
            r = machine.run(100)["registers"]
            self.assertEqual((hex(r["a3"]), r["a2"]), (hex(0x3fe00000), 0))  # 0.5

    def test_reciprocal_estimates_are_the_units(self):
        # Bench M2, step R1 (image 0.3.2): CRC-32 of the 256 results for mantissas 1 + k/256 at exponents 0, +1 and -3,
        # and the special inputs. The unit rounds the exact value to nearest at eight mantissa bits. Bench M3 (image
        # 0.3.4, view RCP2): with the input's lower mantissa bits set (H: the next bit; F: all of them) the unit
        # gave the exponent 0 tables again, all eight, so only the top eight mantissa bits of the input count.
        crcs = {"rcpsp": (0x24BA9252, 0xF62922BA, 0x7236A471), "rsqrsp": (0xB37E28CA, 0x62118BB7, 0xD4B23279),
                "rcpdp": (0x9F40B027, 0x1F67AB74, 0x3C697084), "rsqrdp": (0xE9F42249, 0x0F916977, 0x1F9C6A55)}
        # +0, -0, +infinity, -infinity, NaN, denormal, -1, largest
        single = (0, 0x80000000, 0x7f800000, 0xff800000, 0x7fc00000, 1, 0xbf800000, 0x7f7fffff)
        double = tuple(x << 32 for x in (0, 0x80000000, 0x7ff00000, 0xfff00000, 0x7ff80000, 0x00080000, 0xbff00000)) + (0x7fefffffffffffff,)
        special = {"rcpsp": (0x7f800000, 0xff800000, 0, 0x80000000, 0x7fffffff, 0x7f800000, 0xbf800000, 0),
                   "rsqrsp": (0x7f800000, 0xff800000, 0, 0x7fffffff, 0x7fffffff, 0x7f800000, 0x7fffffff, 0x1f800000),
                   "rcpdp": (0x7ff00000 << 32, 0xfff00000 << 32, 0, 0x80000000 << 32, 0x7fffffffffffffff, 0x7ff00000 << 32,
                             0xbff00000 << 32, 0),
                   "rsqrdp": (0x7ff00000 << 32, 0xfff00000 << 32, 0, 0x7fffffffffffffff, 0x7fffffffffffffff,
                              0x7ff00000 << 32, 0x7fffffffffffffff, 0x1ff00000 << 32)}
        for name, expected in crcs.items():
            wide = name.endswith("dp")
            program = self.serial([f"{name} .S1 a1:a0,a5:a4" if wide else f"{name} .S1 a0,a4", "nop 4"])
            with self.machine(program) as machine:
                def estimate(x):
                    machine.reset(0x1000)
                    machine.set_register("a0", x & 0xffffffff); machine.set_register("a1", x >> 32)
                    r = machine.run(100)["registers"]
                    return r["a5"] << 32 | r["a4"] if wide else r["a4"]
                for exponent, crc in zip((0, 1, -3), expected):
                    with self.subTest(name=name, exponent=exponent):
                        values = [estimate((1023 + exponent) << 52 | k << 44 if wide else (127 + exponent) << 23 | k << 15)
                                  for k in range(256)]
                        self.assertEqual(zlib.crc32(struct.pack("<256Q" if wide else "<256I", *values)), crc)
                for variant, low in (("H", 1 << 43 if wide else 0x4000), ("F", (1 << 44) - 1 if wide else 0x7fff)):
                    with self.subTest(name=name, variant=variant):
                        values = [estimate(1023 << 52 | k << 44 | low if wide else 127 << 23 | k << 15 | low) for k in range(256)]
                        self.assertEqual(zlib.crc32(struct.pack("<256Q" if wide else "<256I", *values)), expected[0])
                for x, result in zip(double if wide else single, special[name]):
                    with self.subTest(name=name, x=hex(x)):
                        self.assertEqual(hex(estimate(x)), hex(result))
                # Between two table points, and an input whose result rounds up to the next power of two.
                x = 0x3ff00000000007ff if wide else 0x3f800001
                self.assertEqual(hex(estimate(x)), hex(0x3ff00000 << 32 if wide else 0x3f800000))

    def test_saturation_sets_csr_sat_and_the_units_ssr_bit_one_cycle_after_the_result(self):
        # SPRUFE8B SADD, SSUB, SSHL, SAT and SMPYLH examples that saturate: 7FFF FFFFh, CSR 0001 0300h and the
        # SSR bit of the unit (L1 01h, L2 02h, S1 04h, M1 10h), "set one cycle after dst is written". b5, b6
        # and b7 read CSR in the three cycles after the instruction, or after its delay slot.
        for text, slots, a0, a1, a3, unit in (
                ("sadd .L1 a0,a1,a2", 0, 0x436771f2, 0x5a2e51a3, 0, 0x01),
                ("ssub .L2X a0,a1,b2", 0, 0x5a2e51a3, 0x802a3fa2, 0, 0x02),
                ("sshl .S1 a0,a1,a2", 0, 0x47191925, 6, 0, 0x04),
                ("sat .L1 a1:a0,a2", 0, 0x3413539a, 0x0000001f, 0, 0x01),
                ("smpylh .M1 a0,a1,a2", 1, 0x00008000, 0x80000000, 0, 0x10),
                ("smpy2 .M1 a0,a1,a3:a2", 3, 0x80008000, 0x80008000, 0x7fffffff, 0x10)):
            wait = [f"nop {slots}"] if slots else []
            program = self.serial([text, *wait, "mvc .S2 csr,b5", "mvc .S2 csr,b6", "mvc .S2 csr,b7", "mvc .S2 ssr,b8"])
            with self.subTest(text=text), self.machine(program) as machine:
                for register, value in (("a0", a0), ("a1", a1)):
                    machine.set_register(register, value)
                r = machine.run(100)["registers"]
                self.assertEqual(r["b2" if "b2" in text else "a2"], 0x7fffffff)
                if a3:
                    self.assertEqual(r["a3"], a3)
                # The result is there for the first read, the flag for the second.
                self.assertEqual((r["b5"] & 0x200, r["b6"] & 0x200, r["b7"] & 0x200, r["b8"]), (0, 0x200, 0x200, unit))
        # A result that fits leaves both alone (the manual's first SADD and SSHL examples), and packed saturation never sets them.
        for text, a0, a1 in (("sadd .L1 a0,a1,a2", 0x5a2e51a3, 0x012a3fa2), ("sshl .S1 a0,a1,a2", 0x02e3031c, 2),
                             ("sadd2 .S1 a0,a1,a2", 0x7fff7fff, 0x7fff7fff), ("saddu4 .S1 a0,a1,a2", 0xffffffff, 0xffffffff),
                             ("abs2 .L1 a0,a2", 0x80008000, 0)):
            program = self.serial([text, "nop 4", "mvc .S2 csr,b5", "mvc .S2 ssr,b8"])
            with self.subTest(text=text), self.machine(program) as machine:
                for register, value in (("a0", a0), ("a1", a1)):
                    machine.set_register(register, value)
                r = machine.run(100)["registers"]
                self.assertEqual((r["b5"] & 0x200, r["b8"]), (0, 0))
        # 40-bit forms saturate at 40 bits.
        program = self.serial(["sadd .L1 a0,a5:a4,a3:a2", "sadd .L2 b0,b5:b4,b7:b6", "sadd .L1 a0,a9:a8,a11:a10", "nop 2", "mvc .S2 ssr,b8"])
        with self.machine(program) as machine:
            for register, value in (("a0", 0x7fffffff), ("a4", 0xffffffff), ("a5", 0x7f), ("b0", 0x80000000), ("b4", 0), ("b5", 0x80),
                                    ("a8", 5), ("a9", 1)):
                machine.set_register(register, value)
            r = machine.run(100)["registers"]
            self.assertEqual((r["a3"], r["a2"]), (0x7f, 0xffffffff))        # 2^39 - 1
            self.assertEqual((r["b7"], r["b6"]), (0x80, 0))                 # -2^39
            self.assertEqual((r["a11"], r["a10"]), (1, 0x80000004))         # fits: 1 0000 0005h + 7FFF FFFFh
            self.assertEqual(r["b8"], 0x03)                                 # L1 and L2

    def test_misaligned_word_and_doubleword_accesses_round_the_address_down(self):
        # The unit, M1 bench I4 (2026-11-16, three runs, EFR and IERR 0): a 16-byte buffer 10..1F aligned
        # to 8 in DDR. LDDW at +4 gave 13121110 17161514, LDW at +2 gave 13121110, STW AABBCCDD at +2
        # wrote bytes 0-3 and left 4-15. The non-aligned forms and the pointer update are unaffected.
        program = self.serial(["lddw .D1T1 *+a4(4),a7:a6", "ldw .D1T1 *+a4(2),a8", "ldnw .D1T1 *+a4(2),a9",
                               "ldw .D1T1 *a5++(4),a10", "nop 4", "stw .D1T1 a11,*+a4(2)"])
        with self.machine(program) as machine:
            machine.write(0x4000, bytes(range(0x10, 0x20)))
            for register, value in (("a4", 0x4000), ("a5", 0x400a), ("a11", 0xaabbccdd)):
                machine.set_register(register, value)
            state = machine.run(100)
            r = state["registers"]
            self.assertEqual(state["status"], "returned")
            self.assertEqual((r["a6"], r["a7"], r["a8"]), (0x13121110, 0x17161514, 0x13121110))
            self.assertEqual((r["a9"], r["a10"], r["a5"]), (0x15141312, 0x1b1a1918, 0x400e))
            self.assertEqual(machine.read(0x4000, 16), bytes.fromhex("ddccbbaa") + bytes(range(0x14, 0x20)))

    def test_dmv_moves_two_registers_into_a_pair(self):
        # SPRUFE8B DMV: src1 -> odd register, src2 -> even register, single cycle. The swap form checks that
        # both sources are read before the pair is written. GCC's C674x libgcc uses it for 64-bit moves.
        for text, expected in (("dmv .S1 a0,a1,a5:a4", (0x11223344, 0x55667788)),
                               ("dmv .S1 a4,a5,a5:a4", (0xcafef00d, 0x0badf00d))):
            program = self.serial([text, "nop 4"])
            with self.subTest(text=text), self.machine(program) as machine:
                machine.reset(0x1000)
                machine.set_register("a0", 0x11223344); machine.set_register("a1", 0x55667788)
                machine.set_register("a4", 0xcafef00d); machine.set_register("a5", 0x0badf00d)
                state = machine.run(100)
                self.assertEqual((state["registers"]["a5"], state["registers"]["a4"]), expected)

    def test_maxu4_and_minu4_compare_unsigned_bytes(self):
        # SPRUFE8B MAXU4 / MINU4: each of the four bytes compared as unsigned, single cycle; the cross path
        # (B side source on an .L1 unit) is the form GCC emits for a byte clamp.
        x, y = 0x80FF0105, 0x7F00FF05
        for text, expected in (("maxu4 .L1X a4,b5,a6", 0x80FFFF05), ("minu4 .L1X a4,b5,a6", 0x7F000105)):
            program = self.serial([text, "nop 4"])
            with self.subTest(text=text), self.machine(program) as machine:
                machine.reset(0x1000)
                machine.set_register("a4", x); machine.set_register("b5", y)
                state = machine.run(100)
                self.assertEqual(state["registers"]["a6"], expected)

    def test_integer_vectors_match_reference_interpreter(self):
        examples = [
            "add .L1 a0,a1,a4", "sub .L1 a0,a1,a4", "and .L1 a0,a1,a4", "andn .L1 a0,a1,a4",
            "or .L1 a0,a1,a4", "xor .L1 a0,a1,a4", "shl .S1 a0,a1,a4", "shr .S1 a0,a1,a4",
            "shru .S1 a0,a1,a4", "cmpeq .L1 a0,a1,a4", "cmpgt .L1 a0,a1,a4", "cmplt .L1 a0,a1,a4",
            "cmpgtu .L1 a0,a1,a4", "cmpltu .L1 a0,a1,a4", "mpy .M1 a0,a1,a4", "mpyu .M1 a0,a1,a4",
            "mpysu .M1 a0,a1,a4", "mpyus .M1 a0,a1,a4", "mpy32 .M1 a0,a1,a5:a4",
            "mpy32u .M1 a0,a1,a5:a4", "mpy32su .M1 a0,a1,a5:a4", "mpy32us .M1 a0,a1,a5:a4",
            "rotl .M1 a0,a1,a4", "lmbd .L1 a0,a1,a4", "norm .L1 a0,a4", "abs .L1 a0,a4",
            "subc .L1 a0,a1,a4", "pack2 .L1 a0,a1,a4", "packhl2 .L1 a0,a1,a4",
            "packlh2 .L1 a0,a1,a4", "packl4 .L1 a0,a1,a4", "sshl .S1 a0,a1,a4",
            "set .S1 a0,3,31,a4", "clr .S1 a0,0,31,a4", "ext .S1 a0,3,7,a4", "extu .S1 a0,3,7,a4",
            "ext .S1 a0,a1,a4", "extu .S1 a0,a1,a4", "addaw .D1 a0,a1,a4", "subah .D1 a0,a1,a4",
            "subu .L1 a0,a1,a5:a4", "addu .L1 a0,a3:a2,a5:a4", "add .L1 a1:a0,a2,a5:a4",
            "sub .L1 a1:a0,a2,a5:a4", "shl .S1 a1:a0,a2,a5:a4", "shr .S1 a1:a0,a2,a5:a4",
            "shru .S1 a1:a0,a2,a5:a4", "sat .L1 a1:a0,a4", "cmpgt .L1 a1:a0,a2,a4",
            "cmplt .L1 a1:a0,a2,a4", "cmpeq .L1 a1:a0,a2,a4", "addsub .L1 a0,a1,a5:a4",
            "mpyhi .M1 a0,a1,a5:a4", "mpyli .M1 a0,a1,a5:a4", "shr2 .S1 a0,a1,a4",
            "addsp .L1 a0,a1,a4", "subsp .L1 a0,a1,a4", "mpysp .M1 a0,a1,a4",
            "intsp .L1 a0,a4", "intspu .L1 a0,a4", "sptrunc .L1 a0,a4", "spint .L1 a0,a4",
            "cmpeqsp .S1 a0,a1,a4", "cmpgtsp .S1 a0,a1,a4", "cmpltsp .S1 a0,a1,a4",
            "abssp .S1 a0,a4", "rcpsp .S1 a0,a4",
        ]
        generator = random.Random(6748)
        values = [(0, 0), (0xffffffff, 0x80000000), (0x80000000, 0xffffffff),
                  (0x7fffffff, 32), (0x80000000, 63)] + [(generator.getrandbits(32), generator.getrandbits(32)) for _ in range(25)]
        for text in examples:
            program = self.serial([text, "nop 4"])
            with self.machine(program) as machine:
                for x, y in values:
                    with self.subTest(text=text, x=x, y=y):
                        machine.reset(0x1000)
                        machine.set_register("a0", x); machine.set_register("a1", y)
                        machine.set_register("a2", x ^ 0x13579bdf); machine.set_register("a3", y ^ 0x2468ace0)
                        state = machine.run(100)
                        reference = c6sim.Machine(program, {"a0": x, "a1": y, "a2": x ^ 0x13579bdf, "a3": y ^ 0x2468ace0})
                        reference.run(0x1000, max_cycles=100)
                        if text.startswith("rcpsp") and x & 0x7f800000 == 0x7f800000 and x & 0x7fffff:
                            # SPRUFE8B RCPSP returns NaN_out; the reference also truncates NaN's mantissa.
                            self.assertEqual(state["registers"]["a4"], 0x7fffffff)
                            continue
                        self.assertEqual(state["registers"]["a4"], reference.g("a4"))
                        self.assertEqual(state["registers"]["a5"], reference.g("a5"))
                        self.assertEqual(state["cycles"], reference.cyc)

    @unittest.skipUnless(tools_present(), "DSP binutils are needed for instruction-byte tests")
    def test_real_code_copied_into_ram_and_replaced_without_an_app_elf(self):
        large, _ = demo(self.work, slice_cycles=10000)
        small, _ = demo(self.work, slice_cycles=1)
        self.assertEqual(large["copied_code"], small["copied_code"])
        self.assertEqual(large["replaced_code"], small["replaced_code"])
        self.assertEqual(small["copied_code"]["result"], 42)
        self.assertEqual(small["replaced_code"]["result"], 99)

    @unittest.skipUnless(tools_present(), "DSP binutils are needed for instruction-byte tests")
    def test_cached_nop_classification_tracks_current_ram_and_alias_writes(self):
        elf = build_fixture(self.work)
        names = symbols(elf)
        with CPU(self.work) as machine:
            machine.load_elf(elf)
            base = 0xc2100000
            machine.map(base, 4096, 7)
            machine.alias(0x00800000, base, 4096)
            original = machine.read(names["payload"], 32)
            # GNU pads the first MVK packet with parallel NOPs. An encoded NOP
            # with p=0 splits that packet, adding one cycle before the unchanged
            # return. Replace through the alias to invalidate both cached forms.
            self.assertTrue(any(original[:4]))
            self.assertEqual(original[0] & 1, 1)
            for entry, first, answer, cycles in ((base, bytes(4), 7, 8), (0x00800000, original[:4], 42, 7),
                                                 (base, bytes(4), 7, 8)):
                machine.write(0x00800000, first + original[4:])
                machine.reset(entry)
                machine.set_register("a4", 7)
                state = machine.run(100)
                self.assertEqual(state["status"], "returned")
                self.assertEqual(state["registers"]["a4"], answer)
                self.assertEqual(state["cycles"], cycles)

    @unittest.skipUnless(tools_present(), "DSP binutils are needed for instruction-byte tests")
    def test_cached_packet_depends_on_next_fetch_packet_across_page_boundary(self):
        elf = build_fixture(self.work)
        names = symbols(elf)
        with CPU(self.work) as machine:
            machine.load_elf(elf)
            machine.map(0xc2100000, 8192, 7)
            # A parallel NOP at the last word of a page, followed by a real MVK in the next page.
            pc = 0xc2100ffc
            machine.write(pc, struct.pack("<I", 1) + machine.read(names["payload"], 32))
            machine.reset(pc)
            self.assertEqual(machine.run(100)["registers"]["a4"], 42)
            machine.write(pc + 4, machine.read(names["replacement"], 32))
            machine.reset(pc)
            self.assertEqual(machine.run(100)["registers"]["a4"], 99)

    @unittest.skipUnless(tools_present(), "DSP binutils are needed for instruction-byte tests")
    def test_cross_group_code_replacement_invalidates_alias_packet_dependencies(self):
        elf = build_fixture(self.work)
        names = symbols(elf)
        with CPU(self.work) as machine:
            machine.load_elf(elf)
            machine.map(0xc23ff000, 8192, 7)
            machine.alias(0x00800000, 0xc23ff000, 8192)
            pc, alias_pc = 0xc23ffffc, 0x00800ffc
            machine.write(pc, struct.pack("<I", 1) + machine.read(names["payload"], 32))
            for entry in (pc, alias_pc):
                machine.reset(entry)
                self.assertEqual(machine.run(100)["registers"]["a4"], 42)
            # Change only the next fetch packet through an alias. Both decoded
            # packets depend on it, across the 4 MiB pointer-group boundary.
            machine.write(alias_pc + 4, machine.read(names["replacement"], 32))
            for entry in (pc, alias_pc):
                machine.reset(entry)
                state = machine.run(1)
                while state["status"] == "budget":
                    state = machine.run(1)
                self.assertEqual(state["status"], "returned")
                self.assertEqual(state["registers"]["a4"], 99)

    @unittest.skipUnless(tools_present(), "DSP binutils are needed for instruction-byte tests")
    def test_aliased_decode_invalidation_survives_sparse_ram_growth_and_reset(self):
        elf = build_fixture(self.work)
        names = symbols(elf)
        with CPU(self.work) as machine:
            machine.load_elf(elf)
            machine.map(0xc2100000, 4096, 7)
            machine.alias(0x00800000, 0xc2100000, 4096)
            original = machine.read(names["payload"], 32)
            replacement = machine.read(names["replacement"], 32)
            machine.write(0xc2100000, original)
            machine.reset(0x00800000)
            self.assertEqual(machine.run(100)["registers"]["a4"], 42)
            # Allocate many new RAM pages while retaining decoded version pointers.
            machine.map(0x40000000, 2 * 1024 * 1024, 3)
            machine.write(0x40000000, bytes(2 * 1024 * 1024))
            for destination, code, expected in ((0xc2100000, replacement, 99),
                                                (0x00800000, original, 42)):
                machine.write(destination, code)
                for entry in (0x00800000, 0xc2100000):
                    machine.reset(entry)
                    self.assertEqual(machine.run(100)["registers"]["a4"], expected)

    @unittest.skipUnless(tools_present(), "DSP binutils are needed for instruction-byte tests")
    def test_distant_code_fetches_survive_cache_growth_and_aliased_replacement(self):
        elf = build_fixture(self.work)
        names = symbols(elf)
        with CPU(self.work) as machine:
            machine.load_elf(elf)
            base, distant = 0xc2100000, 0xc2102000
            machine.map(base, 0x6000, 7)
            machine.alias(0x00800000, base, 0x6000)
            machine.write(base, machine.read(names["payload"], 32))
            replacement = machine.read(names["replacement"], 32)
            machine.write(distant, replacement)
            # These addresses collide in the tagged fetch table. Both retain their
            # distinct original instruction bytes and must work across one-cycle calls.
            for entry, expected in ((base, 42), (distant, 99), (base, 42)):
                machine.reset(entry)
                state = machine.run(1)
                while state["status"] == "budget":
                    state = machine.run(1)
                self.assertEqual(state["status"], "returned")
                self.assertEqual(state["registers"]["a4"], expected)
            # Retain a hot entry while the owning packet hash table rehashes.
            for pc in range(base + 0x4000, base + 0x5000, 4):
                compiled = (Instruction * 1)(instruction(pc, "nop"))
                machine.install(pc, pc + 4, False, pc & ~31, 32, compiled)
            machine.write(0x00800000, replacement)
            machine.reset(base)
            state = machine.run(100)
            self.assertEqual(state["status"], "returned")
            self.assertEqual(state["registers"]["a4"], 99)

    @unittest.skipUnless(tools_present(), "DSP binutils are needed for instruction-byte tests")
    def test_changing_only_fetch_header_invalidates_cached_protected_load(self):
        elf = build_fixture(self.work)
        names = symbols(elf)
        with CPU(self.work) as machine:
            machine.load_elf(elf)
            machine.map(0xc2100000, 4096, 7)
            machine.map(0x4000, 4096, 3)
            machine.write(0x4000, struct.pack("<I", 42))
            machine.write(0xc2100000, machine.read(names["protected_payload"], 32))
            results = []
            for header in (0xe0000000, 0xe0100000):
                machine.write(0xc210001c, struct.pack("<I", header))
                machine.reset(0xc2100000)
                machine.set_register("a0", 0x4000)
                machine.set_register("a1", 7)
                results.append(machine.run(100)["registers"]["a4"])
            self.assertEqual(results, [7, 42])

    @unittest.skipUnless(tools_present() and (BIN / "tic6x-elf-gcc").exists(), "DSP GCC is needed for the C fixture")
    def test_gcc_compiled_integer_functions_match_c_and_reference_results(self):
        sys.path.insert(0, str(ROOT / "tools/toolchain"))
        import elfsim
        elf = build_fixture(self.work, integer=True)
        program = elfsim.ElfProgram(elf)
        names = symbols(elf)
        values = [0, 1, 0xffffffff, 0x80000000, 123, 456, 789, 1000]
        with CPU(self.work) as machine:
            machine.load_elf(elf)
            machine.map(0x30ff0000, 65536, 3)
            machine.map(0x40000000, 4096, 3)
            for name, x, y in (("integer_mix", 0x12345678, 0x87654321),
                               ("integer_mix", 0x87654321, 0x12345678),
                               ("integer_sum", 0x40000000, len(values))):
                registers = {"a4": x, "b4": y, "b15": 0x30fffff8}
                machine.reset(names[name])
                for reg, value in registers.items():
                    machine.set_register(reg, value)
                machine.write(0x40000000, struct.pack("<8I", *values))
                state = machine.run(10000)
                reference = c6sim.Machine(program, registers)
                reference.mem.write(0x40000000, struct.pack("<8I", *values))
                reference.run(names[name], max_cycles=10000)
                self.assertEqual(state["registers"]["a4"], reference.g("a4"))
                if name == "integer_sum":
                    expected = sum(value ^ (i * 17) for i, value in enumerate(values)) & 0xffffffff
                else:
                    expected = ((x ^ ((y << 3) & 0xffffffff)) + 0x12345678) & 0xffffffff
                    expected ^= x >> 5 if c6sim.s32(x) < c6sim.s32(y) else ~y & 0xffffffff
                    expected = (expected + x * y) & 0xffffffff
                self.assertEqual(state["registers"]["a4"], expected)


if __name__ == "__main__":
    unittest.main()
