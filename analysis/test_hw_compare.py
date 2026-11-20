"""Pins docs/04-hardware-access.md: the bring-up register writes are the same in SmplTrek 3.2.174, Lofi-12 XT 1.5.205
and CyDrums 1.1.84, and have the documented values. Run:
python3 -B -m unittest discover -s analysis -p "test_hw_compare.py" -v

Needs the three official updates in firmware/ and the listings in work/ (not tracked); skipped without them.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hw_compare

NEEDED = [ROOT / p[k] for p in hw_compare.PRODUCTS.values() for k in ("image", "listing")] + \
         [ROOT / p["match"] for p in hw_compare.PRODUCTS.values() if p["match"]]
BOARD_STEPS = ["syscfg_unlock", "early_psc", "usb_phy_cfg", "spi", "oled", "panel_uart", "encoders", "keys", "sync",
               "power_pinmux", "power", "audio_power", "i2c_setup", "audio", "midi_uart", "usb_dcd", "sd"]


@unittest.skipUnless(all(p.exists() for p in NEEDED), "official updates or work listings not present")
class SameBoard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        steps = [s for s in hw_compare.STEPS if s[0] in BOARD_STEPS + ["audio_hw"]]
        cls.results = {k: hw_compare.run(k, steps) for k in hw_compare.PRODUCTS}

    def normal(self, key, step):
        f, writes, codec = self.results[key][step]
        self.assertIsNotNone(writes, f"{key} {step}: {codec}")
        return [(a, hw_compare.shown(v)) for a, v in writes], codec

    def test_board_steps_identical(self):
        for step in BOARD_STEPS:
            base = self.normal("smpltrek", step)
            for key in ("lofi12", "cydrums"):
                with self.subTest(step=step, product=key):
                    self.assertEqual(self.normal(key, step), base)

    def test_audio_ring_differs_only_in_length(self):
        base, _ = self.normal("smpltrek", "audio_hw")
        for key in ("lofi12", "cydrums"):
            other, _ = self.normal(key, "audio_hw")
            diff = [(a, b) for a, b in zip(base, other) if a != b]
            self.assertEqual(len(base), len(other))
            # A_B_CNT and LINK_BCNTRLD carry BCNT: 256/255 words in SmplTrek, 192/191 in the others
            self.assertTrue(all((a[0] - 0x01C04000) % 32 in (8, 20) for a, _ in diff), diff)

    def writes(self, step):
        return self.results["smpltrek"][step][1]

    def test_documented_values(self):
        w = lambda step: dict(self.writes(step))
        self.assertEqual(w("syscfg_unlock"), {0x01C14038: 0x83E70B13, 0x01C1403C: 0x95A4F1E0})
        self.assertEqual(w("usb_phy_cfg")[0x01C14184], 0x0972)
        midi = w("midi_uart")
        self.assertEqual(midi[0x01C42024] << 8 | midi[0x01C42020], 372)   # UART0 DLH:DLL: 31,250 baud at 186 MHz
        i2c = w("i2c_setup")
        self.assertEqual((i2c[0x01C22030], i2c[0x01C2200C], i2c[0x01C22010]), (2, 35, 35))
        audio = w("audio")
        self.assertEqual((audio[0x01D00068], audio[0x01D000AC]), (0x180F0, 0x110))    # RFMT, AFSXCTL
        self.assertEqual(audio[0x01D00044], 0x1E1E)                       # GBLCTL, last
        self.assertEqual(w("audio_hw")[0x01C04000], 0x00100201)           # PaRAM 0 OPT
        usb = w("usb_dcd")
        self.assertEqual((usb[0x01E00030], usb[0x01E00401]), (0x01FF1E1F, 0x40))
        sd = w("sd")
        self.assertEqual((sd[0x01C40004], sd[0x01C40010]), (0x1E8, 0x7D))   # MMCCLK, MMCIM
        codec = self.results["smpltrek"]["audio"][2]
        self.assertEqual(len(codec), 40)
        self.assertIn((9, 0x37), codec)
        self.assertIn((7, 0x0A), codec)


if __name__ == "__main__":
    unittest.main()
