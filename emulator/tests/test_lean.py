"""Control-register moves, DINT/RINT, ROTL and the time stamp counter on the lean path and in compiled blocks.

These instructions used to take the general path only. The general path, the lean path and compiled blocks
must leave the same state at every boundary, with interrupts requested at awkward moments: an interrupt that
is pending while GIE is clear has to be taken at the same cycle whichever of them runs the RINT or the write
to CSR or IER that lets it in.
"""
import random
import shutil
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from blocks import compile_blocks
from cpu import CPU
from ir import Instruction, instruction

LOOP = 0x1000 + 4 * 7
MAIN = [
    "mvk .S2 0x1400,b0", "mvc .S2 b0,istp",             # general path: ISTP masks what is written
    "mvk .S2 0,b0", "mvc .S2 b0,tscl",                  # general path: starts the counter
    "mvk .S1 40,a1", "mvk .S2 0x13,b1", "mvc .S2 b1,ier",
    # LOOP
    "mvc .S2 csr,b4", "dint", "mvc .S2 tsr,b6", "mvc .S2 csr,b15",
    "mvc .S2 tscl,b7", "mvc .S2 tsch,b8", "rotl .M2 b7,5,b9", "add .L2 b9,b10,b10", "add .L2 b9,b10,b10",
    "mvc .S2 b10,nrp", "mvc .S2 nrp,b11", "mvc .S2 b10,ilc", "mvc .S2 ilc,b12", "mvc .S2 b9,rilc",
    "mvc .S2 b7,ntsr", "mvc .S2 b9,rep", "mvc .S2 ntsr,b2", "mvc .S2 rep,b3",
    "rint", "mvc .S2 ifr,b13", "mvc .S2 ier,b14",
    "mvk .S2 0x3,b1", "mvc .S2 b1,ier", "mvk .S2 0x13,b1", "mvc .S2 b1,ier",    # interrupt 4 masked, then let in
    "dint", "or .L2 1,b4,b5", "mvc .S2 b5,csr",                               # GIE set by a write to CSR
    "sub .L1 a1,1,a1", f"[a1] b .S1 {LOOP:08x}", "add .L1 a7,a1,a7", "nop 4",
    "mvk .S2 0x1300,b3", "b .S2 b3", "nop 5",
]
HANDLER = ["add .L1 a6,1,a6", "mvc .S2 irp,b14", "mvc .S2 itsr,b0", "xor .L1 a8,a6,a8", "b .S2 irp", "nop 5"]
SPIN = [f"b .S1 {0x1300:08x}", "nop 5"]


@unittest.skipUnless(shutil.which("g++"), "host g++ required")
class Lean(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="smpltrek-lean-")
        cls.work = Path(cls.temporary.name)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def start(self, cpu):
        cpu.reset(0x1000, return_address=None)
        for name, value in dict(csr=0x100, b10=0x12345678).items():
            cpu.set_register(name, value)

    def observe(self, mode, steps, requests):
        """[state] after each step; `requests` are step indexes at which interrupt 4 is requested first."""
        with CPU(self.work, decode=False) as cpu:
            cpu.map(0x1000, 4096, 7)
            if mode == "general":
                cpu.micro(False)
            for base, texts in ((0x1000, MAIN), (0x1300, SPIN), (0x1480, HANDLER)):
                for index, text in enumerate(texts):
                    address = base + index * 4
                    cpu.install(address, address + 4, False, address & ~31, 32, (Instruction * 1)(instruction(address, text)))
            cpu.fast_forward(False)
            if mode == "blocks":
                self.start(cpu)
                cpu.blocks(True, heat=True)
                for at in range(0, 3000, 100):          # a first pass with interrupts, so the handler is known code too
                    cpu.set_register("ifr", 0x10); cpu.run(100)
                self.assertGreater(compile_blocks(cpu, minimum_heat=1), 0)
                cpu.blocks(True)
            self.start(cpu)
            rows = []
            for index, step in enumerate(steps):
                if index in requests:
                    cpu.set_register("ifr", 0x10)
                rows.append(cpu.run(step))
            sources = "".join(source[0] for source in (cpu.block_source(0x1000 + 4 * i) for i in range(len(MAIN))) if source) if mode == "blocks" else ""
            return rows, cpu.block_state(), sources

    def test_the_general_path_the_lean_path_and_blocks_agree_at_every_boundary(self):
        rng = random.Random(674)
        steps = [rng.choice((1, 1, 2, 3, 7, 19, 64, 150)) for _ in range(400)]
        requests = {index for index in range(len(steps)) if rng.random() < 0.3}
        general, _, _ = self.observe("general", steps, requests)
        lean, _, _ = self.observe("lean", steps, requests)
        blocks, stats, sources = self.observe("blocks", steps, requests)
        last = general[-1]
        self.assertEqual(last["status"], "budget")
        self.assertGreater(last["interrupt_count"], 40)                 # interrupts were taken all through the loop
        self.assertEqual(last["registers"]["a1"], 0)                    # and the loop ran to its end
        for index, (a, b, c) in enumerate(zip(general, lean, blocks)):
            self.assertEqual(a, b, f"general and lean differ after step {index}")
            self.assertEqual(a, c, f"interpreter and blocks differ after step {index}")
        # The blocks really held the new forms, and most of the run was host code.
        for needle in ("c6b_tsc(", "std::rotl(", "R[64] & ~1u", "R[65] & 2u", "R[81] & ~1u"):
            self.assertIn(needle, sources)
        self.assertGreater(stats["block_cycles"], last["cycles"] // 3)

    def test_a_pending_interrupt_enters_at_the_same_cycle_after_each_unmasking_instruction(self):
        # Every packet here is one instruction and one cycle, so on the first pass an instruction's index is its
        # cycle. With GIE set from the start, interrupt 4 is requested once: just after the first DINT (the RINT
        # lets it in), just after the write to IER that masks it (the next write to IER lets it in), or just
        # after the second DINT (the write to CSR lets it in). General path, lean path and blocks must end in
        # the same state, and IRP must be the packet after the instruction that let it in.
        handler = ["mvc .S2 tscl,b0", "add .L1 a6,1,a6", "b .S2 irp", "nop 5"]
        ier = [index for index, text in enumerate(MAIN) if text == "mvc .S2 b1,ier"]      # set-up, mask, unmask
        dint = [index for index, text in enumerate(MAIN) if text == "dint"]
        cases = ((dint[0] + 1, MAIN.index("rint")), (ier[1] + 1, ier[2]), (dint[1] + 1, MAIN.index("mvc .S2 b5,csr")))
        for request, opener in cases:
            states = {}
            for mode in ("general", "lean", "blocks"):
                with self.subTest(request=request, mode=mode), CPU(self.work, decode=False) as cpu:
                    cpu.map(0x1000, 4096, 7)
                    if mode == "general":
                        cpu.micro(False)
                    for base, body in ((0x1000, MAIN), (0x1300, SPIN), (0x1480, handler)):
                        for index, text in enumerate(body):
                            address = base + index * 4
                            cpu.install(address, address + 4, False, address & ~31, 32, (Instruction * 1)(instruction(address, text)))
                    cpu.fast_forward(False)
                    if mode == "blocks":
                        self.start(cpu); cpu.blocks(True, heat=True)
                        for _ in range(20):
                            cpu.set_register("ifr", 0x10); cpu.run(150)
                        self.assertGreater(compile_blocks(cpu, minimum_heat=1), 0)
                        cpu.blocks(True)
                    self.start(cpu)
                    cpu.set_register("csr", 0x101)
                    cpu.run(request)
                    cpu.set_register("ifr", 0x10)
                    states[mode] = cpu.run(300)
                    if mode == "blocks":
                        self.assertGreater(cpu.block_state()["block_cycles"], 100)
            self.assertEqual(states["general"]["interrupt_count"], 1, request)
            self.assertEqual(states["general"]["registers"]["irp"], 0x1000 + 4 * (opener + 1), request)
            self.assertEqual(states["general"], states["lean"], request)
            self.assertEqual(states["general"], states["blocks"], request)
