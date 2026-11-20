"""Compiled blocks (experimental) must leave exactly the state the interpreter leaves."""
import shutil
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from blocks import compile_blocks
from core_demo import BIN, symbols, tools_present
from cpu import CPU, CoreFault
from ir import Instruction, instruction

# A counted loop with loads, a store, a multiply, a post-incremented pointer and a predicated
# branch whose delay slots hold further work; then floating point and a spin. Each delayed
# result has one reader in its last delay slot (old value) and one just after (new value),
# so a result that lands a cycle early or late changes the registers.
BODY = ["mvk .S1 100,a1", "mvk .S1 3,a2",
        "ldw .D2T1 *+b5(0),a6", "mpy .M1 a2,a1,a7", "add .L1 a7,a1,a18", "add .L1 a7,a1,a19",
        "add .L1 a6,a1,a8", "add .L1 a6,a1,a20", "stw .D2T1 a20,*+b5(0)", "stw .D2T1 a8,*+b5(4)",
        "ldbu .D1T1 *a5++(1),a9", "sub .L1 a1,1,a1", "[a1] b .S1 00001008", "add .L1 a7,a8,a10", "shl .S1 a10,2,a11",
        "ldb .D1T1 *-a5(1),a12", "nop 2", "cmpgt .L1 a12,a1,a13",
        "addsp .L1 a3,a4,a14", "nop 2", "add .L1 a14,a1,a21", "add .L1 a14,a1,a22"]
PROGRAM = BODY + [f"b .S1 {0x1000 + 4 * len(BODY):08x}", "nop 5"]


@unittest.skipUnless(shutil.which("g++"), "host g++ required")
class Blocks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="smpltrek-blocks-")
        cls.work = Path(cls.temporary.name)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def start(self, cpu, **changed):
        cpu.reset(0x1000, return_address=None)
        cpu.write(0x4000, bytes(range(1, 255)) + bytes(400))
        for name, value in (dict(a5=0x4000, b5=0x4100, a3=0x3fc00000, a4=0x40200000) | changed).items():
            cpu.set_register(name, value)

    def observe(self, compiled, boundaries, **changed):
        with CPU(self.work, decode=False) as cpu:
            cpu.map(0x1000, 4096, 7); cpu.map(0x4000, 8192, 3)
            for index, text in enumerate(PROGRAM):
                address = 0x1000 + index * 4
                cpu.install(address, address + 4, False, address & ~31, 32, (Instruction * 1)(instruction(address, text)))
            cpu.fast_forward(False)
            if compiled:
                self.start(cpu)
                cpu.blocks(True, heat=True); cpu.run(2500)  # past the loop, so its tail is known code
                self.assertGreater(compile_blocks(cpu, minimum_heat=1), 0)
                cpu.blocks(True)
            self.start(cpu, **changed)
            rows = []
            for boundary in boundaries:
                try:
                    rows.append((cpu.run(boundary - cpu.cycles()), cpu.read(0x4000, 400)))
                except CoreFault as error:
                    rows.append((str(error), cpu.state(), cpu.read(0x4000, 400)))
                    break
            return rows, cpu.block_state()

    def test_every_boundary_state_matches_the_interpreter(self):
        # Single-cycle boundaries leave no room for a block; the later ones enter them from
        # every phase of the loop and stop inside delay slots and waits.
        boundaries = [*range(1, 60), 100, 333, 700, 701, 1500, 1640, 1641, 2500]  # the loop ends near 1600
        reference, _ = self.observe(False, boundaries)
        compiled, state = self.observe(True, boundaries)
        self.assertEqual(compiled, reference)
        self.assertGreater(state["block_cycles"], 500)

    def test_one_long_run_matches_and_runs_mostly_in_blocks(self):
        reference, _ = self.observe(False, [2500])
        compiled, state = self.observe(True, [2500])
        self.assertEqual(reference[0][0]["registers"]["a22"], 0x40800000)  # the tail ran
        self.assertEqual(compiled, reference)
        self.assertGreater(state["block_cycles"], 1000)

    def test_a_block_compiled_before_is_found_again_in_another_batch(self):
        # blocks.build records, for each block's own source, the library that holds it. A later build that
        # wants the block in a different set (a later run finds its hot code in another order) takes it from
        # there without compiling; a record that names no library is ignored.
        import blocks
        from unittest import mock
        with CPU(self.work, decode=False) as cpu:
            cpu.map(0x1000, 4096, 7); cpu.map(0x4000, 8192, 3)
            for index, text in enumerate(PROGRAM):
                address = 0x1000 + index * 4
                cpu.install(address, address + 4, False, address & ~31, 32, (Instruction * 1)(instruction(address, text)))
            cpu.fast_forward(False)
            self.start(cpu); cpu.blocks(True, heat=True); cpu.run(2500)
            sources = blocks.collect(cpu, minimum_heat=1)
            self.assertGreater(len(sources), 2)
            work = self.work / "reuse"
            first = blocks.build(work, sources)
            pcs = sorted(sources)
            part = {pc: sources[pc] for pc in pcs[1:]}                       # another set: another batch text
            with mock.patch.object(blocks, "build_one", side_effect=AssertionError("compiled again")):
                again = blocks.build(work, part)
            self.assertEqual(again, [(first[0][0], pcs[1:])])
            self.assertEqual(blocks.install(cpu, again, part), len(part))
            header = (HERE / "core/block.h").read_bytes()
            blocks._marker(work, header, sources[pcs[0]]).write_text("no-such-library")
            rebuilt = blocks.build(work, {pcs[0]: sources[pcs[0]]})          # compiled, since the record is useless
            self.assertEqual([batch for _, batch in rebuilt], [[pcs[0]]])
            self.assertTrue(rebuilt[0][0].exists())
            self.assertEqual(blocks.install(cpu, rebuilt, {pcs[0]: sources[pcs[0]]}), 1)

    def test_wide_multiply_and_leftmost_bit_match_the_interpreter(self):
        program = ["mpyli .M1 a3,a4,a7:a6", "lmbd .L1 a1,a2,a8", "lmbd .L1 a3,a4,a10", "nop 3",
                   "add .L1 a6,a7,a9", "add .L1 a9,a8,a9", "b .S1 00001000", "nop 5"]
        vectors = [(0, 0, 0, 0), (1, 0x00010000, 0xffff8000, 0x00010003), (0, 0xfff00000, 0x7fff, 0x80000000),
                   (1, 0, 0x12348765, 0xfedcba98), (0, 0xffffffff, 0xffffffff, 0xffffffff)]
        rows = []
        for compiled in (False, True):
            with CPU(self.work, decode=False) as cpu:
                cpu.map(0x1000, 4096, 7)
                for index, text in enumerate(program):
                    address = 0x1000 + index * 4
                    cpu.install(address, address + 4, False, address & ~31, 32, (Instruction * 1)(instruction(address, text)))
                cpu.fast_forward(False)
                if compiled:
                    cpu.reset(0x1000, return_address=None)
                    cpu.blocks(True, heat=True); cpu.run(200)
                    self.assertGreater(compile_blocks(cpu, minimum_heat=1), 0)
                    cpu.blocks(True)
                rows.append([])
                for vector in vectors:
                    cpu.reset(0x1000, return_address=None)
                    for name, value in zip(("a1", "a2", "a3", "a4"), vector):
                        cpu.set_register(name, value)
                    rows[-1].append([cpu.run(cycles) for cycles in (7, 30, 31)])
                if compiled:
                    self.assertGreater(cpu.block_state()["block_cycles"], 100)
        self.assertEqual(rows[1], rows[0])
        second = rows[0][1][0]["registers"]  # 16 x 32 signed product; bits before the first 1 / 0
        self.assertEqual((second["a7"], second["a6"], second["a8"], second["a10"]), (0xffffffff, 0x7ffe8000, 15, 0))

    def test_a_guest_fault_reached_inside_a_block_leaves_the_interpreter_state(self):
        # The byte pointer walks off mapped memory in the 41st iteration with a multiply and
        # loads in flight. A misaligned word pointer is no fault (the access rounds down) but
        # every packet that uses it is left to the interpreter.
        for changed, faults in ((dict(a5=0x6000 - 40), True), (dict(b5=0x4102), False)):
            with self.subTest(changed):
                reference, _ = self.observe(False, [2500], **changed)
                compiled, state = self.observe(True, [2500], **changed)
                self.assertEqual(isinstance(reference[0][0], str), faults)
                self.assertEqual(compiled, reference)
                self.assertGreater(state["entries"], 0)

    def test_a_store_into_decoded_code_ends_the_block_like_the_interpreter(self):
        # Packet 4 overwrites a word of packet 20. The interpreter stops for decoding when it
        # reaches that packet's 32-byte group (packet 16), after 15 subtractions; host code
        # made from the old bytes must not run past that point.
        program = ["sub .L1 a1,1,a1"] * 4 + ["stw .D2T1 a20,*+b5(0)"] + ["sub .L1 a1,1,a1"] * 20 + ["b .S1 00001000", "nop 5"]
        rows = []
        for compiled in (False, True):
            with CPU(self.work, decode=False) as cpu:
                cpu.map(0x1000, 4096, 7); cpu.map(0x4000, 8192, 3)
                for index, text in enumerate(program):
                    address = 0x1000 + index * 4
                    cpu.install(address, address + 4, False, address & ~31, 32, (Instruction * 1)(instruction(address, text)))
                cpu.fast_forward(False)
                if compiled:
                    cpu.blocks(True, heat=True)
                # A first pass stores elsewhere in the code's own page, so the page is already
                # known as plain writable RAM when the second pass stores into the code.
                cpu.reset(0x1000, return_address=None); cpu.set_register("b5", 0x1800)
                cpu.run(300)
                if compiled:
                    self.assertGreater(compile_blocks(cpu, minimum_heat=1), 0)
                    cpu.blocks(True)
                cpu.reset(0x1000, return_address=None)
                for name, value in dict(a1=1000, a20=0x12345678, b5=0x1050).items():
                    cpu.set_register(name, value)
                rows.append((cpu.run(300), cpu.read(0x1000, 128)))
                if compiled:
                    self.assertGreater(cpu.block_state()["block_cycles"], 0)
        self.assertEqual(rows[0][0]["status"], "decode")
        self.assertEqual(rows[0][0]["registers"]["a1"], 1000 - 15)
        self.assertEqual(rows[1], rows[0])


@unittest.skipUnless(shutil.which("g++") and tools_present(), "host g++ and DSP binutils required")
class LoopBlocks(unittest.TestCase):
    """Compiled SPLOOP iterations against the interpreter, on assembled loop bodies."""
    REGISTERS = dict(a4=0x4000, b4=0x5000, b5=90, a6=0x40400000, a7=0, b8=0)

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="smpltrek-loop-blocks-")
        cls.work = Path(cls.temporary.name)
        cls.elf = cls.work / "loops.elf"
        for command in ([BIN / "tic6x-elf-as", "-march=c674x", "-o", cls.work / "loops.o", HERE / "core/fixtures/loop_blocks.s"],
                        [BIN / "tic6x-elf-ld", "-T", HERE / "core/fixtures/fixture.ld", "-o", cls.elf, cls.work / "loops.o"]):
            result = subprocess.run(list(map(str, command)), capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stderr)
        cls.names = symbols(cls.elf)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def start(self, cpu, name, **changed):
        cpu.reset(self.names[name])
        cpu.write(0x4000, struct.pack("<512f", *(index * 0.375 - 40 for index in range(512))) + bytes(6144))
        for register, value in (self.REGISTERS | changed).items():
            cpu.set_register(register, value)

    def observe(self, name, compiled, boundaries, **changed):
        with CPU(self.work) as cpu:
            cpu.load_elf(self.elf)
            cpu.map(0x4000, 8192)
            cpu.fast_forward(False)
            if compiled:
                cpu.blocks(True, heat=True)
                self.start(cpu, name)
                self.assertEqual(cpu.run(5000)["status"], "returned")
                self.assertGreater(compile_blocks(cpu, minimum_heat=1), 0)
                cpu.blocks(True)
            self.start(cpu, name, **changed)
            rows = []
            for boundary in boundaries:
                try:
                    rows.append((cpu.run(boundary - cpu.cycles()), cpu.read(0x4000, 8192)))
                except CoreFault as error:
                    rows.append((str(error), cpu.state(), cpu.read(0x4000, 8192)))
                    break
                if rows[-1][0]["status"] == "returned":
                    break
            return rows, cpu.block_state()

    def test_every_boundary_state_matches_the_interpreter(self):
        # Dense boundaries stop inside iterations; sparse ones leave room for many at once.
        boundaries = [*range(1, 80), 97, 150, 151, 152, 200, 231, 260, 1000]
        for name in ("scale_loop", "float_loop", "masked_loop", "while_loop"):
            with self.subTest(name):
                reference, _ = self.observe(name, False, boundaries)
                compiled, state = self.observe(name, True, boundaries)
                self.assertEqual(reference[-1][0]["status"], "returned")
                self.assertEqual(compiled, reference)
                self.assertGreater(state["loop_cycles"], 10)

    def test_one_run_spends_most_of_a_loop_in_host_code(self):
        for name, cycles in (("scale_loop", 150), ("float_loop", 70), ("masked_loop", 230), ("while_loop", 150)):
            with self.subTest(name):
                reference, _ = self.observe(name, False, [1000])
                compiled, state = self.observe(name, True, [1000])
                self.assertEqual(compiled, reference)
                self.assertGreater(state["loop_cycles"], cycles)

    def test_a_fault_inside_compiled_iterations_leaves_the_interpreter_state(self):
        # The source pointer leaves mapped memory after 40 iterations.
        for name, start in (("scale_loop", 0x6000 - 80), ("float_loop", 0x6000 - 160), ("while_loop", 0x6000 - 40)):
            with self.subTest(name):
                reference, _ = self.observe(name, False, [1000], a4=start)
                compiled, state = self.observe(name, True, [1000], a4=start)
                self.assertIsInstance(reference[0][0], str)
                self.assertEqual(compiled, reference)
                self.assertGreater(state["loop_cycles"], 20)


if __name__ == "__main__":
    unittest.main()
