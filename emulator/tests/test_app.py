"""A GCC-built program with a C interrupt handler, run on the board model and compared with the host.

tests/fixtures/app/app.c is a small synthesiser: Timer 0's interrupt renders one block of samples at a time
(through the register-saving stub of crt0.s, since GCC for this CPU has no interrupt attribute) while the
main program does unrelated work and then sleeps in IDLE. The host build renders the same blocks in a
loop. The timer period is swept, so the interrupts fall on different instructions of the main program each
time; the result must not depend on it.

Built with -fno-schedule-insns2, which the emulator README recommends for any code that runs with interrupts
on (GCC's early stack release). This program also passed with GCC's defaults when tried by hand, so the flag
is the recommended setting here, not something this test depends on.
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from build import ROOT
from cpu import CPU
sys.path.insert(0, str(ROOT / "analysis"))
import c6sim_diff

GCC = ROOT / "tools/tic6x/bin/tic6x-elf-gcc"
APP = Path(__file__).resolve().parent / "fixtures/app"
SUPPORT = Path(__file__).resolve().parent / "fixtures/gcc_support.c"
STACK = 0x31000000
BLOCKS = 24


def build(work, level, extra=()):
    image = work / f'app-{level}{"".join(extra)}.out'
    subprocess.run([str(GCC), "-march=c674x", "-mlittle-endian", "-std=gnu99", f"-{level}", "-ffreestanding", "-msdata=none", "-nostdlib",
                    "-fno-reciprocal-math", *extra, str(APP / "app.c"), str(APP / "crt0.s"), str(SUPPORT), "-lgcc",
                    "-Wl,-Ttext=0xC0000000,-e,app_main", "-o", str(image)], check=True, capture_output=True)
    return image


def host(work, cases):
    subprocess.run(["gcc", "-std=gnu99", "-O1", "-fsanitize=undefined", "-fno-sanitize-recover=all", str(APP / "app.c"), "-o", str(work / "app-host")], check=True)
    out = subprocess.run([str(work / "app-host")], input="".join(f"{seed} {rounds}\n" for seed, rounds in cases), capture_output=True, text=True, check=True).stdout
    return dict(zip(cases, map(int, out.split())))


def run(work, image, period, seed, rounds, compiled=False):
    """(result, interrupts taken, cycles) of one run on the board model."""
    _, symbols = c6sim_diff.elf(image)
    with CPU(work) as machine:
        machine.enable_board()
        machine.load_elf(image)
        machine.map(STACK - 0x100000, 0x100000)
        if compiled:
            from blocks import compile_blocks
            machine.blocks(True, heat=True)
        machine.reset(symbols["app_main"])
        for register, value in dict(a4=period, b4=seed, a6=rounds, b15=STACK - 64, csr=0x101, ier=0x13, istp=symbols["vectors"]).items():
            machine.set_register(register, value)
        state = machine.run(300000)
        if compiled:
            compile_blocks(machine, minimum_heat=4)
        while state["status"] == "budget" and state["cycles"] < 60_000_000:
            state = machine.run(2_000_000)
        return (state["registers"]["a4"] if state["status"] == "returned" else state["status"]), state["interrupt_count"], state["cycles"]


@unittest.skipUnless(GCC.exists() and shutil.which("gcc") and shutil.which("g++"), "tools/tic6x GCC, gcc or g++ not present")
class App(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="smpltrek-app-")
        cls.work = Path(cls.temporary.name)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_the_result_does_not_depend_on_where_the_interrupts_fall(self):
        cases = [(0x12345678, 60), (0xdeadbeef, 25)]
        wanted = host(self.work, cases)
        for level in ("O2", "Os"):
            image = build(self.work, level, ("-fno-schedule-insns2",))
            for (seed, rounds) in cases:
                cycles = set()
                for period in range(700, 1100, 29):
                    with self.subTest(level=level, seed=hex(seed), period=period):
                        result, interrupts, spent = run(self.work / "core", image, period, seed, rounds)
                        self.assertEqual(result, wanted[seed, rounds])
                        self.assertGreaterEqual(interrupts, BLOCKS)
                        cycles.add(spent)
                self.assertGreater(len(cycles), 8)          # the periods really moved the interrupts
        # Compiled blocks give the interpreter's answer.
        image = build(self.work, "O2", ("-fno-schedule-insns2",))
        result, interrupts, _ = run(self.work / "blocks", image, 800, *cases[0], compiled=True)
        self.assertEqual((result, interrupts >= BLOCKS), (wanted[cases[0]], True))


if __name__ == "__main__":
    unittest.main()
