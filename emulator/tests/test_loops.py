from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from build import ROOT
from core_demo import BIN, symbols, tools_present
from cpu import CPU
sys.path.insert(0, str(ROOT / "analysis"))
sys.path.insert(0, str(ROOT / "tools/toolchain"))
import c6sim
import elfsim


@unittest.skipUnless(shutil.which("g++") and tools_present(), "host g++ and DSP binutils required")
class Loops(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="smpltrek-loops-")
        cls.work = Path(cls.temporary.name)
        cls.elf = cls.work / "loops.elf"
        commands = [
            [BIN / "tic6x-elf-as", "-march=c674x", "-o", cls.work / "loops.o", HERE / "core/fixtures/loops.s"],
            [BIN / "tic6x-elf-ld", "-T", HERE / "core/fixtures/fixture.ld", "-o", cls.elf, cls.work / "loops.o"],
        ]
        for command in commands:
            result = subprocess.run(list(map(str, command)), capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stderr)
        cls.names = symbols(cls.elf)
        cls.reference = elfsim.ElfProgram(cls.elf)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def execute(self, name, registers, sliced=False, profile=False, data=None, size=64):
        data = data or struct.pack("<16I", *range(0x100, 0x110))
        with CPU(self.work) as machine:
            machine.load_elf(self.elf)
            machine.map(0x4000, 8192)
            machine.write(0x4000, data)
            machine.reset(self.names[name])
            for reg, value in registers.items():
                machine.set_register(reg, value)
            if profile:
                machine.profile_guest(1)
            state = machine.run(1 if sliced else 1000)
            while state["status"] == "budget" and state["cycles"] < 1000:
                state = machine.run(1)
            self.assertEqual(state["status"], "returned")
            output = machine.read(0x5000, size)
            if profile:
                machine.profile_guest(0)
                observed = machine.guest_profile()
        reference = c6sim.Machine(self.reference, registers)
        reference.mem.write(0x4000, data)
        reference.run(self.names[name], max_cycles=1000)
        self.assertEqual(output, reference.mem.read(0x5000, size))
        for reg in ("a0", "a4", "b4", "b7", "ilc"):
            self.assertEqual(state["registers"][reg], reference.g(reg), reg)
        self.assertEqual(state["cycles"], reference.cyc)
        return (state, output, observed) if profile else (state, output)

    def test_misaligned_aligned_form_accesses_round_down_as_on_the_unit(self):
        # M1 bench I4: with the buffer 10..1F, LDDW at +4 gave 13121110 17161514 and LDW at +2 gave 13121110;
        # STW at +2 wrote the word at +0. LDH at +1 is not a bench value: it follows the same rule.
        for sliced in (False, True):
            state, output = self.execute("misaligned", {"a4": 0x4000, "b4": 0x5000}, sliced, data=bytes(range(0x10, 0x20)), size=24)
            self.assertEqual(struct.unpack("<6I", output), (0x13121110, 0x17161514, 0x13121110, 0x1110, 0x13121110, 0))
            self.assertEqual(state["registers"]["a4"], 0x5015)   # the pointer itself keeps its low bits

    def test_a_skipped_addkpc_fills_the_delay_slots_of_the_branch_before_it(self):
        # SPRUFE8B 3.8.10: ADDKPC's NOP cycles do not depend on its predicate. Without them the non-negative
        # case runs on into sign_back while the branch to the worker is still in flight.
        for value, expected in ((7, 3), (0, 0), (0x7fffffff, 0x3fffffff), (-7 & 0xffffffff, -3 & 0xffffffff), (-1 & 0xffffffff, 0)):
            for sliced in (False, True):
                with self.subTest(value=hex(value), sliced=sliced):
                    state, _ = self.execute("sign_wrap", {"a4": value}, sliced)
                    self.assertEqual(state["registers"]["a4"], expected)

    def test_guest_profile_tags_original_loop_control_and_overlapping_drain(self):
        for name, registers in (("while_count", {"a4": 8}),
                                ("copy_overlap", {"a4": 0x4000, "b4": 0x5000})):
            with self.subTest(name=name):
                baseline, expected = self.execute(name, registers)
                state, output, p = self.execute(name, registers, profile=True)
                self.assertEqual((state, output), (baseline, expected))
                self.assertEqual((p["cycles"], p["packets"], p["samples"]),
                                 (state["cycles"], state["packets"], state["packets"]))
                self.assertEqual(sum(p[k] for k in ("issue_cycles", "wait_cycles", "software_loop_cycles", "interrupt_entry_cycles")), state["cycles"])
                loops = [row for row in p["pcs"] if row["kind"] == "software_loop"]
                self.assertEqual(sum(row["samples"] for row in loops), p["software_loop_packets"])
                self.assertGreater(p["software_loop_cycles"], 0)
                for row in loops:
                    self.assertTrue(any("sploop" in text for _, text in self.reference.packet(row["pc"])[0]))
                if name == "copy_overlap":
                    self.assertGreater(p["draining_cycles"], 0)

    def test_load_store_software_pipeline_and_delayed_counter(self):
        expected = struct.pack("<8I", *range(0x100, 0x108)) + bytes(32)
        for name in ("copy_loop", "copy_delayed", "copy_overlap"):
            results = []
            for sliced in (False, True):
                with self.subTest(name=name, sliced=sliced):
                    state, output = self.execute(name, {"a4": 0x4000, "b4": 0x5000}, sliced)
                    self.assertEqual(output, expected)
                    results.append(state)
            self.assertEqual(results[0], results[1])

    def test_masked_instruction_runs_once_even_for_zero_iteration_loop(self):
        for count in (0, 1, 4, 8):
            with self.subTest(count=count):
                state, output = self.execute("masked_fill", {"a4": 0x5000, "b4": count, "a6": 0x12345678}, True)
                self.assertEqual(state["registers"]["b7"], 1)
                self.assertEqual(output, struct.pack("<I", 0x12345678) * count + bytes(64 - count * 4))

    def test_predicate_termination_and_minimum_sp_loopw_cycles(self):
        for count in (0, 4, 8, 32):
            with self.subTest(count=count):
                # SPRUFE8B 7.10.2: the exit acts on the condition 4 cycles before the boundary, so a loop
                # of ii 1 whose own body clears the condition starts 4 more iterations.
                state, _ = self.execute("while_count", {"a4": count}, True)
                self.assertEqual(state["registers"]["b4"], count + 4)

    def test_a_compiled_do_while_loop_ends_on_the_condition_four_cycles_before_the_boundary(self):
        # SPRUFE8B 7.10.2, on loops taken from cl6x output. The expected values are the C they were
        # compiled from; an exit on the condition register's current value drops dot_until's last
        # products and string_copy would be unaffected.
        x = [3, -7, 11, 250, -300, 17, 29, -2, 41, 5, -90, 123, 77, -64, 9, 1000]
        y = [2, -3, 5, 7, -11, 13, 1, -1, 19, -23, 4, 6, -8, 31, 15, -2]
        data = struct.pack("<16h", *x) + bytes(32) + struct.pack("<16h", *y)
        for n, m in ((0, 1), (1, 1), (2, 1), (5, 2), (11, 1), (15, 1), (14, 3), (-4, 1)):
            total, left, index = 0, n, 0
            while True:
                total += x[index] * y[index]; left -= m; index += 1
                if left < 0:
                    break
            for sliced in (False, True):
                with self.subTest(n=n, m=m, sliced=sliced):
                    state, _ = self.execute("dot_until", {"a5": 0x4000, "b4": 0x4040, "a4": n & 0xffffffff, "b6": m}, sliced, data=data)
                    self.assertEqual(state["registers"]["a4"], total & 0xffffffff)
        for text in (b"\0tail", b"a\0tail", b"software pipelined loop\0tail"):
            with self.subTest(text=text):
                _, output = self.execute("string_copy", {"a4": 0x5000, "b4": 0x4000}, True, data=text, size=32)
                self.assertEqual(output, text[:text.index(0) + 1] + bytes(31 - text.index(0)))

    def test_nested_loop_reloads_the_buffer_for_each_outer_pass(self):
        # SPRUFE8B 7.9.6. The expected values come from the C the loops stand for, the cycle
        # count and registers from the reference simulator.
        x = [3, -7, 11, 250, -300, 17, 29, -2, 41, 5, -90, 123]
        h = [2, -3, 5, 7, -11, 13, 1, -1]
        fir = struct.pack("<12h", *x) + bytes(232) + struct.pack("<8h", *h)
        correlation = struct.pack("<4h", *(sum(x[i + j] * h[i] for i in range(8)) for j in range(4)))
        words = list(range(0x100, 0x100 + 18 * 3, 3))
        rows = struct.pack("<18I", *(word + index // 6 for index, word in enumerate(words)))
        for name, registers, data, expected, masked in (
                ("nested_fir", {"a4": 0x4000, "b4": 0x4100, "a6": 0x5000}, fir, correlation, 0),
                ("nested_rows", {"a4": 0x4000, "b4": 0x5000}, struct.pack("<18I", *words), rows, 1)):
            results = []
            for sliced in (False, True):
                with self.subTest(name=name, sliced=sliced):
                    state, output = self.execute(name, registers, sliced, data=data, size=len(expected) + 8)
                    self.assertEqual(output, expected + bytes(8))
                    self.assertEqual(state["registers"]["b7"], masked)
                    results.append(state)
            self.assertEqual(results[0], results[1])

    def test_spkernelr_reloads_with_the_post_loop_packet(self):
        # SPRUFE8B 7.5.2.2 and Example 7-15. Expected memory is the C the loop stands for: b8 words from
        # the first source, then a1 times b9 words from the second. b9 = 0: every reload is skipped.
        words = list(range(0x100, 0x110))
        for passes, count, reload_count in ((0, 6, 6), (1, 6, 6), (1, 8, 7), (2, 6, 7), (1, 6, 0), (2, 6, 0)):
            expected = struct.pack(f"<{count + passes * reload_count}I", *(words[:count] + passes * words[8:8 + reload_count]))
            registers = {"a4": 0x4000, "b4": 0x5000, "a6": 0x4020, "a1": passes, "b8": count, "b9": reload_count}
            results = []
            for sliced in (False, True):
                with self.subTest(passes=passes, count=count, reload_count=reload_count, sliced=sliced):
                    state, output = self.execute("kernel_copy", registers, sliced, size=96)
                    self.assertEqual(output, expected + bytes(96 - len(expected)))
                    self.assertEqual(state["registers"]["a1"], 0)
                    results.append(state)
            self.assertEqual(results[0], results[1])

    def test_reload_with_a_zero_count_skips_the_invocation(self):
        # SPRUFE8B 7.9.6.2: with RILC = 0 the reloaded invocations issue nothing, so the outer loop
        # stores a zero sum for each of them; with RILC = 8 this is nested_fir.
        x = [3, -7, 11, 250, -300, 17, 29, -2, 41, 5, -90, 123]
        h = [2, -3, 5, 7, -11, 13, 1, -1]
        data = struct.pack("<12h", *x) + bytes(232) + struct.pack("<8h", *h)
        sums = [sum(x[i + j] * h[i] for i in range(8)) for j in range(4)]
        for reload_count, expected in ((8, sums), (0, [sums[0], 0, 0, 0])):
            results = []
            for sliced in (False, True):
                with self.subTest(reload_count=reload_count, sliced=sliced):
                    state, output = self.execute("nested_skip", {"a4": 0x4000, "b4": 0x4100, "a6": 0x5000, "b6": reload_count},
                                                 sliced, data=data, size=16)
                    self.assertEqual(output, struct.pack("<4h", *expected) + bytes(8))
                    results.append(state)
            self.assertEqual(results[0], results[1])

    def test_an_interrupt_at_any_cycle_leaves_every_loop_result_unchanged(self):
        # SPRUFE8B 7.13: a loop that is interrupted drains, and is piped up again on return. Interrupt 4
        # is requested at every cycle of each function in turn. The result must be the uninterrupted one
        # (masked set-up instructions included: they must not run twice), the routine must have run
        # once, and cycle count, registers and return address must match the reference simulator.
        # Each case: function, registers, data, output size, whether some request must be accepted inside
        # the loop, and the registers that must end as in the uninterrupted run (None: only the
        # reference is compared). copy_delayed's count is below TI's minimum for an interruptible loop,
        # so every request waits for its end. while_count breaks TI's rule for an interruptible SPLOOPW
        # (its condition is set in the last cycles of the body) and over-runs when piped up again.
        text = b"software pipelined loop\0"
        dots = struct.pack("<16h", *range(3, 51, 3)) + bytes(32) + struct.pack("<16h", *range(-40, 40, 5))
        every = ("a0", "a1", "a4", "a7", "b0", "b4", "b7", "ilc")
        x = [3, -7, 11, 250, -300, 17, 29, -2, 41, 5, -90, 123]
        h = [2, -3, 5, 7, -11, 13, 1, -1]
        fir = struct.pack("<12h", *x) + bytes(232) + struct.pack("<8h", *h)
        words = struct.pack("<64I", *range(0x100, 0x140))
        cases = (
            ("crossing_loop", {"a4": 5, "b4": 12}, None, 64, True, every),
            ("masked_fill", {"a4": 0x5000, "b4": 14, "a6": 0x12345678}, None, 64, True, every),
            ("while_count", {"a4": 20}, None, 64, True, None),
            ("string_copy", {"a4": 0x5000, "b4": 0x4000}, text, 32, True, ("a0", "a1", "b4", "b5")),
            ("string_copy", {"a4": 0x5000, "b4": 0x4000}, b"\0" + text, 32, False, ("a0", "a1", "b4", "b5")),
            ("dot_until", {"a5": 0x4000, "b4": 0x4040, "a4": 13, "b6": 1}, dots, 64, True, ("a4", "b5")),
            ("copy_delayed", {"a4": 0x4000, "b4": 0x5000}, None, 64, False, every),
            ("kernel_copy", {"a4": 0x4000, "b4": 0x5000, "a6": 0x4080, "a1": 0, "b8": 24, "b9": 24}, words, 208, True, every),
            ("kernel_copy", {"a4": 0x4000, "b4": 0x5000, "a6": 0x4080, "a1": 1, "b8": 24, "b9": 24}, words, 208, True, every),
            ("nested_fir", {"a4": 0x4000, "b4": 0x4100, "a6": 0x5000}, fir, 16, True, every),
            ("nested_rows", {"a4": 0x4000, "b4": 0x5000}, struct.pack("<18I", *range(0x100, 0x100 + 18 * 3, 3)), 80, True, every),
        )
        compared = ("a0", "a1", "a4", "a7", "b0", "b4", "b5", "b7", "ilc", "irp")
        with CPU(self.work) as machine:
            machine.load_elf(self.elf)
            machine.map(0x4000, 8192)

            def run(name, registers, data, size, at):
                machine.write(0x4000, bytes(8192))
                machine.write(0x4000, data or struct.pack("<16I", *range(0x100, 0x110)))
                machine.reset(self.names[name])
                for reg, value in {**registers, "csr": 0x101, "ier": 0x13, "istp": self.names["loop_isr_table"]}.items():
                    machine.set_register(reg, value)
                state = machine.run(at) if at else None
                if state is None or state["status"] == "budget":
                    if at is not None:
                        machine.set_register("ifr", 0x10)
                    state = machine.run(2000) if at is None or at % 2 else None
                    while state is None or (state["status"] == "budget" and state["cycles"] < 2000):
                        state = machine.run(1)          # odd requests continue whole, even ones cycle by cycle
                self.assertEqual(state["status"], "returned")
                return state, machine.read(0x5000, size), struct.unpack("<I", machine.read(0x5ff8, 4))[0]

            for name, registers, data, size, inside, same in cases:
                plain, expected, calls = run(name, registers, data, size, None)
                self.assertEqual((calls, plain["interrupt_count"]), (0, 0))
                if name == "string_copy":
                    self.assertEqual(expected, data[:data.index(0) + 1] + bytes(size - data.index(0) - 1))
                in_loop = 0
                for at in range(plain["cycles"]):
                    with self.subTest(name=name, a1=registers.get("a1"), at=at):
                        state, output, calls = run(name, registers, data, size, at)
                        reference = c6sim.Machine(self.reference, registers)
                        reference.mem.write(0x4000, data or struct.pack("<16I", *range(0x100, 0x110)))
                        reference.isr, reference.irqs = self.names["loop_isr"], [at]
                        reference.run(self.names[name], max_cycles=2000)
                        taken = len(reference.taken)
                        if same is not None:
                            self.assertEqual(output, expected)
                        else:
                            self.assertEqual(output, reference.mem.read(0x5000, size))
                        self.assertEqual((calls, state["interrupt_count"]), (taken, taken))
                        self.assertEqual(state["loop_interrupt_count"], sum(1 for _, _, splx in reference.taken if splx))
                        self.assertEqual(struct.unpack("<I", reference.mem.read(0x5ff8, 4))[0], taken)
                        self.assertEqual(state["cycles"], reference.cyc)
                        for reg in compared:
                            self.assertEqual(state["registers"][reg], reference.g(reg), reg)
                        if not taken:
                            self.assertEqual(state["cycles"], plain["cycles"])
                        elif reference.taken[0][2]:
                            in_loop += 1
                            self.assertEqual(state["registers"]["itsr"] & 0x4000, 0x4000)
                        for reg in same or ():
                            self.assertEqual(state["registers"][reg], plain["registers"][reg], reg)
                with self.subTest(name=name, a1=registers.get("a1")):
                    self.assertEqual(in_loop > 0, inside, f"{in_loop} requests were accepted inside the loop")

    def test_an_interrupt_inside_a_long_nop_or_idle_matches_the_reference(self):
        # SPRUFE8B 5.5.4: a multicycle NOP, IDLE included, is interrupted like any instruction, and after its
        # first cycle the routine returns to the next packet. wait_nop holds a load, NOP 9 and IDLE; interrupt 4
        # is requested at each cycle in turn, and again at cycle 60 if the function is still waiting in IDLE
        # then. Cycle count, result and return addresses must match the reference simulator, which has its own
        # code for both.
        returns = set()
        with CPU(self.work) as machine:
            machine.load_elf(self.elf)
            machine.map(0x4000, 8192)
            for at in range(40):
                with self.subTest(at=at):
                    machine.write(0x4000, bytes(8192))
                    machine.write(0x4000, struct.pack("<I", 20))
                    machine.reset(self.names["wait_nop"])
                    for reg, value in {"a4": 0x4000, "csr": 0x101, "ier": 0x13, "istp": self.names["loop_isr_table"]}.items():
                        machine.set_register(reg, value)
                    if at:
                        self.assertEqual(machine.run(at)["status"], "budget")
                    machine.set_register("ifr", 0x10)
                    state = machine.run(60 - at)
                    first = state["registers"]["irp"]
                    if state["status"] == "budget":
                        machine.set_register("ifr", 0x10)
                        state = machine.run(200)
                    reference = c6sim.Machine(self.reference, {"a4": 0x4000})
                    reference.mem.write(0x4000, struct.pack("<I", 20))
                    reference.isr, reference.irqs = self.names["loop_isr"], [at, 60]
                    self.assertEqual(reference.run(self.names["wait_nop"], max_cycles=200), 42)
                    taken = len(reference.taken)
                    self.assertEqual((state["status"], state["registers"]["a4"], state["interrupt_count"]), ("returned", 42, taken))
                    self.assertEqual(struct.unpack("<I", machine.read(0x5ff8, 4))[0], taken)
                    self.assertEqual((state["cycles"], state["registers"]["irp"]), (reference.cyc, reference.g("irp")))
                    self.assertEqual(first, reference.taken[0][1])
                    returns.add((first - self.names["wait_nop"], taken))
        # The first request returned to: the load, the NOP (requested before it issued), the ADD after it
        # (requested inside it), IDLE, each followed by a second interrupt to end the IDLE; or, from inside
        # IDLE, to the ADD after it (the latest of those have not returned by cycle 60 and take the second too).
        self.assertEqual(returns, {(0, 2), (4, 2), (8, 2), (12, 2), (16, 1), (16, 2)})

    def test_kernel_on_next_decode_page_preserves_loop_control(self):
        for sliced in (False, True):
            with self.subTest(sliced=sliced):
                state, _ = self.execute("crossing_loop", {"b4": 8}, sliced)
                self.assertEqual(state["registers"]["a4"], 8)


CYDRUMS = ROOT / "firmware/cydrums/CyDrums_v1.1.84.zip"


@unittest.skipUnless(shutil.which("g++") and CYDRUMS.exists() and tools_present(),
                     "host g++, the official CyDrums 1.1.84 update and DSP binutils required")
class CyDrumsNestedReload(unittest.TestCase):
    """A compiler-generated nested loop: [b2] SPLOOPD 7, SPMASKR in the post-loop code, RILC 22, two passes.

    The oracle is the one derived by hand for the reference simulator (analysis/test_c6sim.py): record i
    at SRC + 200 i with count n fills four halfwords at DST + 8 i with its fields at +12 if n > 0, +60 if
    n >= 2, +108 if n > 2 and +156 if n >= 4, else 0; the reloaded pass writes the same to the second row.
    """
    FUNC, SRC, DST = 0xC253FA24, 0xC26851D8, 0xC2427108

    def test_both_invocations_fill_their_rows_in_the_reference_cycle_count(self):
        sys.path.insert(0, str(ROOT / "tools"))
        try:
            import mmtd2elf
            import sonicware_integrity
        finally:
            sys.path.pop(0)
        (_, update), = sonicware_integrity.inputs([CYDRUMS])
        program = c6sim.Program(CYDRUMS)
        reference = c6sim.Machine(program, {"b14": c6sim.PRODUCTS["cydrums"]["b14"]})
        expected = []
        with tempfile.TemporaryDirectory(prefix="smpltrek-cydrums-") as work, CPU(work) as machine:
            machine.map(0xc0000000, 0x08000000, 7)
            for address, content in mmtd2elf.mmtd_sections(update)[2]:
                machine.write(address, content)
            machine.reset(self.FUNC)
            machine.set_register("b14", c6sim.PRODUCTS["cydrums"]["b14"])
            for i in range(22):
                count, fields = i % 6, [0x100 * (i + 1) + k + 1 for k in range(4)]
                record = self.SRC + 200 * i
                for target in (machine, reference.mem):
                    target.write(record, struct.pack("<i", count))
                    for offset, field in zip((12, 60, 108, 156), fields):
                        target.write(record + offset, struct.pack("<H", field))
                expected += [fields[0] if count > 0 else 0, fields[1] if count >= 2 else 0,
                             fields[2] if count > 2 else 0, fields[3] if count >= 4 else 0]
            state = machine.run(5000)
            rows = machine.read(self.DST, 352)
        reference.run(self.FUNC, max_cycles=5000)
        self.assertEqual(state["status"], "returned")
        self.assertEqual(rows, struct.pack("<88H", *expected) * 2)
        self.assertEqual((state["cycles"], state["registers"]["ilc"]), (reference.cyc, 0))


if __name__ == "__main__":
    unittest.main()
