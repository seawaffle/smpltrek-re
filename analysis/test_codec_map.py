"""Pins the codec decode in docs/04-hardware-access.md ("Audio") against the TLV320AIC3106 data sheet (SLAS509G) and,
when the official updates are present, the simulated codec writes of SmplTrek 3.2.174, Lofi-12 XT 1.5.205 and
CyDrums 1.1.84. Run:
python3 -B -m unittest discover -s analysis -p "test_codec_map.py" -v

The decoder tests always run; the simulation tests need firmware/ and the work listings and match files (as
test_hw_compare.py) and are skipped without them.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import codec_map


class Decoder(unittest.TestCase):
    def meaning(self, reg, value, page=0):
        writes = ([(0, 1)] if page else []) + [(reg, value)]
        return codec_map.decode(writes)[-1][4]

    def test_pll_48k_needs_24_576_mhz_mclk(self):
        # P = 2, J = 8, D = 0, R = 1 (register 11 not written): fs(ref) = MCLK * 8 / 4096
        self.assertEqual(codec_map.pll_rate(24.576e6, 2, 8, 0), 48000)
        self.assertAlmostEqual(codec_map.pll_rate(24.576e6, 2, 7, 3500), 44100)
        self.assertNotEqual(codec_map.pll_rate(24e6, 2, 8, 0), 48000)      # the DSP's 24 MHz would give 46.875 kHz
        self.assertEqual(self.meaning(3, 0xA2), "PLL on, Q = 4, P = 2")
        self.assertEqual(self.meaning(4, 0x20), "J = 8")

    def test_register_7_is_the_datapath_not_pll(self):
        self.assertEqual(self.meaning(7, 0x0A), "fs(ref) 48 kHz, dual-rate ADC 0 DAC 0, left DAC plays left, "
                                                "right DAC plays right")
        self.assertTrue(self.meaning(7, 0x8A).startswith("fs(ref) 44.1 kHz"))

    def test_interface(self):
        self.assertTrue(self.meaning(8, 0xD0).startswith("BCLK out, WCLK out, DOUT 3-state 0, "
                                                         "clocks run when powered down 1"))
        self.assertTrue(self.meaning(9, 0x37).startswith("I2S, 32-bit, continuous BCLK"))

    def test_output_path_is_direct_to_line_drivers(self):
        self.assertTrue(self.meaning(41, 0x50).startswith("left DAC -> DAC_x3 (direct to line driver), "
                                                          "right DAC -> DAC_x3"))
        self.assertEqual(self.meaning(42, 0x9C), "driver power-on delay 800 ms, ramp step 4 ms, weak VCM from AVDD divider")
        self.assertIn("level 0 dB, unmuted", self.meaning(86, 0x0B))
        self.assertIn("read-only status", self.meaning(86, 0x0B))

    def test_line_inputs(self):
        self.assertEqual(self.meaning(19, 0x84), "LINE1L -> left ADC: differential, 0 dB, left ADC channel powered, "
                                                 "soft-step 0")
        self.assertEqual(self.meaning(21, 0xF8), "LINE1R -> left ADC: differential, not connected")
        self.assertEqual(self.meaning(17, 0xF0), "MIC3L -> left ADC not connected; MIC3R -> left ADC 0 dB")

    def test_page1_high_pass_pairs(self):
        d = codec_map.decode([(0, 1), (65, 0x7F), (66, 0xD5), (67, 0x80), (68, 0x2B), (69, 0x7F), (70, 0xAA), (0, 0)])
        self.assertEqual([x[4] for x in d if x[1] in (66, 68, 70)],
                         ["left N0 = 32725", "left N1 = -32725", "left D1 = 32682"])
        self.assertEqual(d[-1][0], 1)     # the page-select write itself is shown in the page it was written from

    def test_gpio_pin_names(self):
        self.assertEqual(codec_map.gpio_pins(0x01E26018 + 0x28, 1 << 9), ["+GP2[9]"])
        self.assertEqual(codec_map.gpio_pins(0x01E2601C + 0x28 * 3, 1 << 30), ["-GP7[14]"])
        self.assertIsNone(codec_map.gpio_pins(0x01E26010, 1))


import hw_compare   # noqa: E402  (after codec_map's path set-up)
NEEDED = [ROOT / p[k] for p in hw_compare.PRODUCTS.values() for k in ("image", "listing")] + \
         [ROOT / p["match"] for p in hw_compare.PRODUCTS.values() if p["match"]]


@unittest.skipUnless(all(p.exists() for p in NEEDED), "official updates or work listings not present")
class Simulated(unittest.TestCase):
    CALLS = [(0xC161D990, {}, True), (0xC161D758, {"b4": 20}, True), (0xC161D798, {"b4": 20}, True),
             (0xC161D7D4, {"b4": 20}, True), (0xC161D7E8, {"b4": 1}, True), (0xC161D894, {"b4": 1}, True),
             (0xC161D964, {"b4": 1}, True), (0xC161DB74, {"b4": 1}, True), (0xC161DB74, {"b4": 0}, True),
             (0xC15F1064, {"a4": 1}, False), (0xC15F1064, {"a4": 2}, False), (0xC15F112C, {"a4": 3}, False),
             (0xC15F112C, {"a4": 6}, False)]

    @classmethod
    def setUpClass(cls):
        cls.results = {}
        for key in hw_compare.PRODUCTS:
            s = codec_map.Session(key)
            cls.results[key] = [s.call(a, dict(r), base=b) for a, r, b in cls.CALLS]

    def get(self, i, key="smpltrek"):
        codec, pins = self.results[key][i]
        self.assertIsNotNone(codec, pins)
        return codec, pins

    def test_same_in_three_products(self):
        for key in ("lofi12", "cydrums"):
            self.assertEqual(self.results[key], self.results["smpltrek"], key)

    def test_output_init(self):
        self.assertEqual(self.get(0)[0], [(37, 0xC0), (41, 0x50), (42, 0x9C), (86, 0x0B), (93, 0x0B)])

    def test_dormant_output_functions(self):
        self.assertEqual(self.get(1)[0], [(82, 0x94), (92, 0x94)])
        self.assertEqual(self.get(2)[0], [(71, 0x94)])
        self.assertEqual(self.get(3)[0], [(54, 0x94)])
        self.assertEqual(self.get(4)[0], [(58, 0x69)])
        self.assertEqual(self.get(5)[0], [(82, 0x00), (85, 0x80)])
        self.assertEqual(self.get(6)[0], [(47, 0x80)])

    def test_routing_keeps_differential_and_power(self):
        self.assertEqual(self.get(7)[0], [(22, 0x84)])
        self.assertEqual(self.get(8)[0], [(22, 0xFC)])

    def test_input_gain_presets(self):
        # INPUT R: index 1 = mic stage on + PGA 0 dB, index 2 = on + 21 dB (manual: NORMAL +28.8, HI +50)
        self.assertEqual(self.get(9), ([(24, 0xFC), (22, 0x84), (16, 0x00)], ["+GP7[14]", "+GP5[11]"]))
        self.assertEqual(self.get(10), ([(24, 0xFC), (22, 0x84), (16, 0x2A)], ["+GP7[14]", "+GP5[11]"]))
        # INPUT L mode 3: Hi-Z stage on + left PGA +10 dB, GP7[14] low; mode 6: GP7[14] high, stage off
        self.assertEqual(self.get(11)[1], ["-GP1[2]", "-GP7[14]", "+GP7[15]"])
        self.assertIn((15, 0x14), self.get(11)[0])
        self.assertEqual(self.get(12)[1], ["-GP1[2]", "+GP7[14]", "-GP7[15]"])


if __name__ == "__main__":
    unittest.main()
