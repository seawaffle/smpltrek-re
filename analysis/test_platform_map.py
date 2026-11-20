import unittest

import platform_map as pm


class TestPlatformMap(unittest.TestCase):
    def test_subsystem_rules(self):
        self.assertEqual(pm.subsystem("McASPTxEnable"), "TI StarterWare McASP / EDMA3 drivers")
        self.assertEqual(pm.subsystem("mcasp_configure"), "Audio: codec and McASP setup")
        self.assertEqual(pm.subsystem("audio_gain_ramp"), "Audio: block processing and mix")
        self.assertEqual(pm.subsystem("SoundEffect::Hall::Hall"), "Audio: block processing and mix")
        self.assertEqual(pm.subsystem("TrackSound::USBTrack::render"), "Tracks")
        self.assertEqual(pm.subsystem("HAL::FlashMemoryDriver::request_read"), "SPI flash")
        self.assertEqual(pm.subsystem("f_open"), "FatFs and SD")
        self.assertEqual(pm.subsystem("midi_send_clock"), "MIDI")
        self.assertEqual(pm.subsystem("pad_velocity"), "Pads and panel controller")
        self.assertEqual(pm.subsystem("unknown_thing"), "Other")

    def test_similarity_and_cell(self):
        carried = {"address": "0xc2c61d84", "kind": "function",
                   "evidence": ["Carried from smpltrek-3.2.174 0xc1621364 by func_match (hash, body similarity 0.87)."]}
        self.assertEqual(pm.similarity(carried), 0.87)
        self.assertEqual(pm.cell(carried), "`0xc2c61d84` (0.87)")
        exact = dict(carried, evidence=["... body similarity 1.0)."])
        self.assertEqual(pm.cell(exact), "`0xc2c61d84`")
        self.assertEqual(pm.cell(None), "—")

    def test_build_and_render(self):
        source = {"f_open": {"address": "0xc150a844", "kind": "function"},
                  "pad_velocity": {"address": "0xc1657690", "kind": "function"}}
        lofi = {"f_open": {"address": "0xc2b86044", "kind": "function", "evidence": []}}
        rows = pm.build(source, [lofi, {}])
        text = pm.render(rows, ["L", "C"])
        self.assertIn("| FatFs and SD | 1 | 1 | 0 | 0 |", text)
        self.assertIn("| `pad_velocity` | function | `0xc1657690` | — | — |", text)

    def test_runs_and_common_blocks(self):
        lofi = [(0x100, 0x1100), (0x140, 0x1140), (0x180, 0x1180), (0x1c0, 0x1300), (0x200, 0x1340), (0x240, 0x1380)]
        cyd = [(0x100, 0x2100), (0x140, 0x2140), (0x180, 0x2180), (0x1c0, 0x21c0), (0x200, 0x2200)]
        self.assertEqual(pm.runs(lofi), [(0x100, 0x180, 0x1000, 3), (0x1c0, 0x240, 0x1140, 3)])
        # Lofi's second run (0x1c0-0x240) overlaps CyDrums' run (0x100-0x200) by 0x1c0-0x200 = 0x40 bytes,
        # the minimum, so it is a block too, with Lofi's delta for that run.
        self.assertEqual(pm.common_blocks([lofi, cyd]),
                         [(0x100, 0x180, [0x1000, 0x2000]), (0x1c0, 0x200, [0x1140, 0x2000])])

    def test_area_stats(self):
        stats = pm.area_stats([0x100, 0x120, 0x180], 0x200, {0x100: "f_open"}, {0x120: "MIDI::Port"},
                              [{0x100, 0x120}, {0x100}])
        self.assertEqual(stats["named: FatFs and SD"], [1, 0x20, 1, 0x20])
        self.assertEqual(stats["MIDI::"], [1, 0x60, 0, 0])
        self.assertEqual(stats["unlabelled"], [1, 0x80, 0, 0])


if __name__ == "__main__":
    unittest.main()
