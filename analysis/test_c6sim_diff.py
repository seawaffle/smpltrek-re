"""c6sim against TI-compiled C (analysis/c6sim_diff.py). Run:
python3 -B -m unittest discover -s analysis -p "test_c6sim_diff.py" -v

Needs the TI C6000 code generation tools and gcc; skipped without them. Three levels cover plain code (O0),
software-pipelined loops (O2) and size-optimised code with compact PROT packets and the push/pop helpers that
CALLP .S1 links through A3 (O3s); the command-line tool runs all six at 80 inputs.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import c6sim_diff   # noqa: E402


@unittest.skipUnless(c6sim_diff.available(), "TI C6000 compiler, gcc or tools/tic6x objdump not present")
class Compiled(unittest.TestCase):
    def test_matches_host(self):
        for level, bad in c6sim_diff.run(["O0", "O2", "O3s"], 12).items():
            self.assertEqual(bad, [], level)


if __name__ == "__main__":
    unittest.main()
