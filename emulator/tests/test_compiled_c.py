from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compiled_c


@unittest.skipUnless(compiled_c.available(), "TI C6000 compiler, gcc or g++ not present")
class CompiledC(unittest.TestCase):
    def test_ti_compiled_functions_match_the_host_in_the_interpreter_and_in_compiled_blocks(self):
        # A short pass; `compiled_c.py` alone runs six levels with more inputs.
        for (level, mode), (bad, runs, host) in compiled_c.run(["O2", "O3s"], 6, True).items():
            with self.subTest(level=level, mode=mode):
                self.assertEqual(bad[:3], [])
                self.assertGreater(runs, 300)
                if mode == "blocks":
                    self.assertGreater(host, 0)


@unittest.skipUnless(compiled_c.gcc_available(), "tools/tic6x GCC, gcc or g++ not present")
class GccCompiledC(unittest.TestCase):
    def test_gcc_compiled_functions_match_the_host_or_differ_only_by_approximate_division(self):
        # A short pass; `compiled_c.py` alone runs five levels with more inputs.
        results = compiled_c.run_gcc(["O2"], 6, True)
        self.assertEqual(sorted(results), [("gcc-O2", "blocks"), ("gcc-O2", "interpreter"), ("gcc-O2-exact", "blocks"), ("gcc-O2-exact", "interpreter")])
        for (label, mode), (bad, runs, host, approximate) in results.items():
            with self.subTest(label=label, mode=mode):
                self.assertEqual(bad[:3], [])
                self.assertGreater(runs, 300)
                if label.endswith("exact"):
                    self.assertEqual(approximate, 0)
                if mode == "blocks":
                    self.assertGreater(host, 0)


if __name__ == "__main__":
    unittest.main()
