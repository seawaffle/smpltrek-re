"""Electrical key-matrix observations, independent of either firmware's scanner."""
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build import WORK
from cpu import CPU

GPIO, MUX = 0x01e26000, 0x01c14120


@unittest.skipUnless(shutil.which("g++"), "host g++ required")
class KeyMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        WORK.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(dir=WORK, prefix="test-keys-")
        cls.work = Path(cls.temporary.name)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    @staticmethod
    def put(cpu, address, value):
        cpu.write(address, value.to_bytes(4, "little"))

    @staticmethod
    def get(cpu, address):
        return int.from_bytes(cpu.read(address, 4), "little")

    def machine(self):
        cpu = CPU(self.work, decode=False)
        cpu.enable_board(profile=1)
        # GPIO pin functions from SPRUH79C tables 10-28..10-33.
        for index, value in ((6, 0x88888800), (7, 0x08080000), (8, 0x08888880), (11, 0x00800000)):
            self.put(cpu, MUX + index * 4, value)
        self.put(cpu, GPIO + 0x38, 0xffffffc0)  # Rows GP2[0..5] outputs, columns inputs.
        return cpu

    def columns(self, cpu):
        return self.get(cpu, GPIO + 0x48) >> 16 & 0xa7e

    def test_selected_row_columns_pinmux_direction_and_multiple_switches(self):
        with self.machine() as cpu:
            cpu.key_input(32, True)  # STEP 1: row4/col0 -> GP3[1].
            cpu.key_input(15, True)  # row1/col7 -> GP3[11].
            cpu.key_input(46, True)  # row5/col6 -> GP3[9].
            self.assertEqual(self.columns(cpu), 0)
            for row, expected in ((0, 0), (4, 2), (1, 0x800), (5, 0x200)):
                self.put(cpu, GPIO + 0x3c, 1 << row)
                self.assertEqual(self.columns(cpu), expected)
            self.put(cpu, GPIO + 0x3c, 0x32)
            self.assertEqual(self.columns(cpu), 0xa02)
            self.put(cpu, GPIO + 0x38, 0xfffffff0)  # Row4/5 tri-stated as inputs.
            self.assertEqual(self.columns(cpu), 0x800)
            self.put(cpu, MUX + 7 * 4, 0)  # Column inputs remain connected with no GPIO output mux.
            self.assertEqual(self.columns(cpu), 0x800)
            self.put(cpu, GPIO + 0x38, 0xffffffc0)
            self.put(cpu, MUX + 6 * 4, 0)  # Rows no longer GPIOs.
            self.assertEqual(self.columns(cpu), 0)
            for invalid in (-1, 48, True):
                with self.assertRaises(ValueError):
                    cpu.key_input(invalid, True)

    def test_key_four_is_active_low_and_does_not_connect_matrix_column_four(self):
        with self.machine() as cpu:
            self.put(cpu, GPIO + 0x3c, 1)
            self.assertTrue(self.get(cpu, GPIO + 0x70) & (1 << 26))
            cpu.key_input(4, True)
            self.assertFalse(self.get(cpu, GPIO + 0x70) & (1 << 26))
            self.put(cpu, MUX + 11 * 4, 0)
            self.assertFalse(self.get(cpu, GPIO + 0x70) & (1 << 26))
            self.assertEqual(self.columns(cpu), 0)
            self.put(cpu, GPIO + 0x3c, 0)
            self.assertFalse(self.get(cpu, GPIO + 0x70) & (1 << 26))
            cpu.key_input(4, False)
            self.assertTrue(self.get(cpu, GPIO + 0x70) & (1 << 26))

    def test_column_edges_follow_row_drives_and_key_release(self):
        with self.machine() as cpu:
            self.put(cpu, GPIO + 8, 1 << 3)
            self.put(cpu, GPIO + 0x4c, 1 << 17)  # SET_RIS_TRIG, GP3[1].
            self.put(cpu, GPIO + 0x54, 1 << 17)  # SET_FAL_TRIG.
            cpu.key_input(32, True)  # Unselected row has no edge.
            self.assertEqual(self.get(cpu, GPIO + 0x5c), 0)
            self.put(cpu, GPIO + 0x40, 16)  # SET_DATA, select row4.
            self.assertEqual(self.get(cpu, GPIO + 0x5c), 1 << 17)
            self.assertTrue(self.get(cpu, 0x01800004) & (1 << 20))  # DSP event52.
            self.put(cpu, GPIO + 0x5c, 1 << 17)
            self.put(cpu, 0x01800044, 1 << 20)
            cpu.key_input(32, False)
            self.assertEqual(self.get(cpu, GPIO + 0x5c), 1 << 17)
            self.assertTrue(self.get(cpu, 0x01800004) & (1 << 20))
            self.assertEqual(self.columns(cpu), 0)

    def test_stock_play_column_senses_input_with_the_reset_pinmux(self):
        with self.machine() as cpu:
            self.put(cpu, MUX + 7 * 4, 0)  # GP3[9] is tri-stated, as in stock initialization.
            self.put(cpu, MUX + 8 * 4, 0)
            cpu.key_input(22, True)
            self.put(cpu, GPIO + 0x3c, 4)  # Row2, column6 -> PLAY.
            self.assertEqual(self.columns(cpu), 0x200)
            self.put(cpu, GPIO + 0x44, 4)
            self.assertEqual(self.columns(cpu), 0)
            self.put(cpu, GPIO + 0x40, 4)
            cpu.key_input(22, False)
            self.assertEqual(self.columns(cpu), 0)


if __name__ == "__main__":
    unittest.main()
