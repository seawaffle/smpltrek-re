"""Pins the register sequences in docs/04-hardware-access.md. Run:
python3 -B -m unittest discover -s analysis -p "test_mmio_trace.py" -v

Needs the official SmplTrek 3.2.174 update in firmware/ (not tracked); skipped without it. Pin-function names need
a local TI StarterWare install and are checked only when it is present.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import c6sim
import hw_inventory
import mmio_trace

SMPLTREK = ROOT / "firmware/smpltrek/SmplTrek v3.2.174.zip"
HOOKS = {0xC16A1BF0: c6sim.returns(1),       # wait for the SPI DMA completion
         0xC1667D20: c6sim.returns(0)}       # task_sleep


class Peripherals(unittest.TestCase):
    def test_peripheral_lookup(self):
        self.assertEqual(hw_inventory.peripheral(0x01F0E050), (0x01F0E000, "SPI1"))
        self.assertEqual(hw_inventory.peripheral(0x01D0C020), (0x01D0C000, "UART1"))
        self.assertIsNone(hw_inventory.peripheral(0x01B77400))

    def test_gpio_dir_resets_to_inputs(self):
        self.assertEqual(mmio_trace.reset_value(0x01E26038), 0xFFFFFFFF)      # DIR of bank pair 1
        self.assertEqual(mmio_trace.reset_value(0x01E26040), 0)               # SET_DATA


# The corpus tests decode code with tools/tic6x objdump (tools/toolchain/build_tic6x_binutils.sh).
OBJDUMP_OK = (Path(__file__).resolve().parents[1] / "tools/tic6x/bin/tic6x-elf-objdump").exists()


@unittest.skipUnless(SMPLTREK.exists() and OBJDUMP_OK, "official SmplTrek 3.2.174 update not present (or tools/tic6x objdump missing)")
class Sequences(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = mmio_trace.Trace(str(SMPLTREK))
        n = len(cls.t.log)
        cls.boot = cls.t.boot()
        cls.boot_log = cls.t.log[n:]
        cls.logs = {}
        for name, address, regs in (
                ("spi", 0xC167C7B4, {}),
                ("oled", 0xC1672298, {"a4": 0x30000000}),
                ("oled_data", 0xC16723A8, {"a4": 0xC14B8400, "b4": 32}),
                ("uart", 0xC161E338, {"a4": 0xC15019D0, "b4": 460800}),
                ("uart_rx", 0xC161E790, {"a4": 0xC15019D0, "b4": 1}),
                ("uart_tx", 0xC161E6E0, {"a4": 0xC15019D0, "b4": 1}),
                ("encoders", 0xC166DB50, {"a4": 0xC10E1288}),
                ("keys", 0xC168F140, {"a4": 0xC1503ED8}),
                ("sync", 0xC16720D8, {"a4": 0xC1504350}),
                ("power", 0xC1646FCC, {"a4": 0xC15036E8})):
            cls.logs[name] = cls.t.run(address, regs, hooks=HOOKS, max_cycles=400000)[1]

    def writes(self, name, address):
        return [a.value for a in self.logs[name] if a.kind == "W" and a.address == address]

    def test_boot_builds_cleanly(self):
        self.assertEqual(self.boot.errors, [])

    def test_tick_timer(self):
        w = {(a.address, a.value) for a in self.boot_log if a.kind == "W"}
        self.assertIn((0x01C20018, 24000), w)          # TIMER64P0 PRD12: 1 ms at 24 MHz
        self.assertIn((0x01C20024, 5), w)              # TGCR: dual 32-bit unchained, 1:2 running
        self.assertIn((0x01800104, 0x483D0824), w)     # INTMUX1

    def test_spi_formats(self):
        self.assertEqual(self.writes("spi", 0x01C41050)[-1], 0x00010408)   # SPI0: prescale 4
        self.assertEqual(self.writes("spi", 0x01F0E050)[-1], 0x00011308)   # SPI1: prescale 19
        self.assertEqual(self.writes("spi", 0x01F0E004)[-1], 0x01000003)
        self.assertEqual(self.writes("spi", 0x01E27A28), [3])               # PSC1 module 10 (SPI1)

    def test_oled_commands_and_pin(self):
        self.assertEqual(self.writes("oled", 0x01C14134)[-1], 0x00180110)   # PINMUX5: SPI1 + GP2[11]
        self.assertEqual(self.writes("oled", 0x01E26038)[-1] & (1 << 11), 0)  # GP2[11] an output
        self.assertEqual(self.writes("oled", 0x01F0E03C), [0xB3, 0xF0, 0x81, 0xFF, 0xA0, 0x07, 0xAF])
        self.assertEqual(self.writes("oled", 0x01E26044), [0x800] * 4)      # D/C low for each command

    def test_oled_frame_dma(self):
        self.assertEqual(self.writes("oled_data", 0x01E26040), [0x800])     # D/C high
        self.assertEqual(self.writes("oled_data", 0x01C0426C), [0x01F0E03C])  # PaRAM 19 DST = SPIDAT1
        self.assertEqual(self.writes("oled_data", 0x01C04260), [0x00113000])
        self.assertEqual(self.writes("oled_data", 0x01F0E008), [0x00010000])

    def test_panel_uart(self):
        self.assertEqual(self.writes("uart", 0x01C14130)[-1] & 0xFF000000, 0x22000000)
        self.assertEqual(self.writes("uart", 0x01D0C020), [25])             # DLL
        self.assertEqual(self.writes("uart", 0x01D0C00C), [3])              # LCR 8N1
        self.assertEqual(self.writes("uart_tx", 0x01D0C030), [0x6001])
        self.assertEqual(self.writes("uart", 0x01E27A30), [3])              # PSC1 module 12 (UART1)

    def test_input_pins(self):
        self.assertEqual(self.writes("keys", 0x01C14138), [0x88888800])     # PINMUX6: GP2[0..5]
        self.assertEqual(self.writes("keys", 0x01C14140), [0x08888880])     # PINMUX8: GP3[1..6]
        self.assertEqual(self.writes("keys", 0x01E26038)[-1] & 0x3F, 0)     # rows are outputs
        p7 = self.writes("keys", 0x01C1413C)[-1]
        self.assertEqual((p7 >> 16) & 0xF, 8)                               # GP3[11]
        self.assertEqual((p7 >> 24) & 0xF, 0)                               # GP3[9] not set (Open 1)
        self.assertEqual(self.writes("encoders", 0x01C14150), [0x80808808])

    def test_power_and_sync(self):
        self.assertEqual(self.writes("power", 0x01E26068), [0x800])         # GP4[11] high
        self.assertEqual([a for a in self.logs["power"] if a.kind == "W" and a.address == 0x01E26060], [])
        self.assertEqual(self.writes("sync", 0x01E2609C), [1 << 24])        # GP7[8] rising edge

    @unittest.skipUnless(mmio_trace.PINMUX, "TI StarterWare headers not installed")
    def test_pin_function_names(self):
        self.assertEqual(mmio_trace.decode_pinmux(4, 0x22000000), ["UART1_RXD", "UART1_TXD"])
        self.assertEqual(mmio_trace.decode_pinmux(5, 0x00080000), ["GPIO2_11"])


if __name__ == "__main__":
    unittest.main()
