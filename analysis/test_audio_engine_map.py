"""Pins the audio engine of SmplTrek 3.2.174 (racks, file player, clicks, curves, mixers, track EQ, sidechain key, send
and master effect roles, render order, PROJECT LEVEL) against the simulated code. Run:
python3 -B -m unittest discover -s analysis -p "test_audio_engine_map.py" -v

Needs firmware/, work/smpltrek-3.2.174.dis and work/smpltrek-3.2.174.rtti.json; skipped without them.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hw_compare           # noqa: E402
import audio_engine_map     # noqa: E402

NEEDED = [ROOT / hw_compare.PRODUCTS["smpltrek"][k] for k in ("image", "listing")] + [audio_engine_map.RTTI]


@unittest.skipUnless(all(p.exists() for p in NEEDED), "official update or work listing / RTTI not present")
class Simulated(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = audio_engine_map.Session()

    def close(self, got, want, places=4):
        self.assertEqual(len(got), len(want))
        for g, w in zip(got, want):
            self.assertAlmostEqual(g, w, places=places)

    def test_dry_block_getter(self):
        self.assertEqual(audio_engine_map.dry_block_getter(self.s), (0xC16DF790, []))

    def test_racks(self):
        r = audio_engine_map.racks(self.s)
        self.assertEqual(r["send"]["members"], [
            "StereoDigialDelay", "PingPongDelay", "ReverseDelay", "TapeEcho", "Room", "Plate", "Hall", "Arena",
            "Tunnel", "Infinity", "SideChainCompressor"])
        self.assertEqual(r["master"]["members"], [
            "AnalogRecord", "CassetteTape", "MultiBandCompressor", "EQandLimiter", "Maximizer"])
        self.assertEqual(r["insert"]["members"], [
            "Chorus", "Flanger", "Phaser", "InsertDelay", "AnalogDelay", "Vibrate", "AutoWah", "Tremolo",
            "RingModulator", "SamplerateCrusher", "AutoPan", "Isolator", "TiltFilter", "Compressor", "RackComp",
            "CleanAmp", "CrunchAmp", "RockAmp", "MetalAmp", "BassAmp"])
        self.assertEqual(r["send"]["header"], [0, 1])          # index 0, on
        self.assertEqual(r["master"]["header"], [0, 0, 1])
        self.assertEqual(r["insert"]["header"], [0, 0])

    def test_file_player_adds(self):
        f = audio_engine_map.file_mix
        self.assertEqual(f(self.s), (0.5, -0.75, 128, 128))                     # 0.25 + 0.25, -0.25 - 0.5
        self.assertEqual(f(self.s, gains=(0.5, 2.0))[:2], (0.375, -1.25))
        # 128 frames asked whatever the rate; the stream advances by what the resampler says it used
        self.assertEqual(f(self.s, rate=44100)[2:], (128, 117))
        self.assertEqual(f(self.s, consumed=99)[2:], (128, 99))

    def test_player_states(self):
        self.assertEqual(audio_engine_map.player_states(self.s),
                         {"0xC1625BF8": [1, 4], "0xC1625F50": [5], "0xC162600C": [2], "0xC16263D0": [3]})

    def test_clicks(self):
        c = audio_engine_map.clicks
        for src, hz, cycles, n in (("metronome 1", 750, 31, 1984), ("metronome 2", 375, 15, 1920),
                                   ("precount", 375, 15, 1920)):
            r = c(self.s, 10, src)
            self.assertEqual((r["hz"], r["cycles"], r["samples"]), (hz, cycles, n), src)
            self.assertAlmostEqual(r["peak"], 0.4516, places=4)
        for level, peak in ((3, 0.01219), (16, 1.8496)):
            self.assertAlmostEqual(c(self.s, level, "metronome 1")["peak"], peak, places=4)
        self.assertEqual(c(self.s, 0, "metronome 1")["samples"], 0)
        self.assertEqual(c(self.s, 0, "precount")["samples"], 0)

    def test_curves(self):
        c = audio_engine_map.curves(self.s)
        self.close([c["level"][v] for v in (100, 127, 63, 0)], [1.0, 2.0, 0.251189, 0.0], 5)
        self.close([c["send"][v] for v in (63, 127, 0, 1, 32, 64, 100)],
                   [1.0, 2.0, 0.0, (1 / 63) ** 2, (32 / 63) ** 2, 1 + 1 / 64, 1 + 37 / 64], 5)

    def test_mix_tracks(self):
        r = audio_engine_map.mix_tracks(self.s, 0.5, (0.25, 0.5, 0.0))
        self.assertEqual(r["rendered"], [10, 11, 12])
        self.assertEqual(r["b1008"], 0.5)                                      # copied from B14+528
        self.close(r["out"], [111 * 0.5, 222 * 0.5])                           # dry x P
        self.close(r["send"], [(4 * 0.25 + 40 * 0.5) * 0.5, (8 * 0.25 + 80 * 0.5) * 0.5])   # send x level x P

    def test_mix_usb_ext(self):
        usb = audio_engine_map.mix_usb(self.s, 0.5, 0.5, 0.25)
        self.close(usb["post"] + usb["send"], [1.0, 2.0, 2.0, 4.0])            # no balance factor
        ext = audio_engine_map.mix_ext(self.s, 0.5, 0.5, 0.25)
        self.assertEqual(ext["b1012"], 0.25)                                   # copied from B14+532
        self.close(ext["post"] + ext["send"], [0.25, 0.5, 0.5, 1.0])

    def test_track_eq_planes(self):
        self.assertEqual(audio_engine_map.track_eq(self.s, 0), {"dry": (0.5, 2.0), "send": (3.0, 4.0)})
        self.assertEqual(audio_engine_map.track_eq(self.s, 1), {"dry": (1.0, 1.0), "send": (3.0, 4.0)})

    def test_sidechain_key(self):
        for key in (10, 11, 12):
            r = audio_engine_map.sidechain(self.s, key)
            want = (0.1 + 0.05) * (key - 9) / 2                                # (L + R) / 2 of the key track
            self.close(r["key"], [want, want], 5)
        other = audio_engine_map.sidechain(self.s, 11, send_type=6)            # not the SideChainCompressor
        self.assertEqual(other["key"], (9.0, 9.0))

    def test_send_delay(self):
        r = audio_engine_map.send_delay(self.s)
        self.assertEqual(r["class"], "SoundEffect::StereoDigialDelay")
        self.assertEqual(r["dry_after_block0"], 0.0)                           # dry copy overwritten: 100 % wet
        self.assertTrue(r["send_kept"])
        self.assertTrue(r["key_kept"])
        self.assertEqual(r["first"][:2], (184, 72))
        self.assertEqual(r["first_abs"], 23624)
        self.assertAlmostEqual(r["first"][3] / r["first"][2], 0.5, places=4)   # echo keeps the L / R ratio

    def test_master_maximizer(self):
        r = audio_engine_map.master_maximizer(self.s)
        self.assertEqual(r["class"], "SoundEffect::Maximizer")
        self.assertTrue(r["same"])
        self.assertTrue(r["send_kept"])
        self.close(r["out"][0], [0.794779, -0.794779, 0.506996], 5)           # in place on out

    def test_render_order(self):
        r = audio_engine_map.render_order
        self.assertEqual(r(self.s)["out"], (0.125, -0.25))                     # MASTER LEVEL 0.5
        self.assertEqual(r(self.s, post=0.125)["out"], (0.1875, -0.1875))      # post bus at unity, before the level
        self.assertEqual(r(self.s, gain=0.0)["out"], (0.0, 0.0))
        click = -0.451556                                                      # level 10, first sample
        self.close(r(self.s, metronome=True)["out"], [0.125 + click, -0.25 + click], 5)
        self.close(r(self.s, metronome=True, gain=0.0)["out"], [click, click], 5)      # after MASTER LEVEL
        rec = r(self.s, rec_src=25, post=0.125)
        self.assertEqual(rec["in_block"], (0.25, -0.5))                        # out before the post bus and level
        self.assertEqual(rec["out"], (0.1875, -0.1875))

    def test_project_level(self):
        p = audio_engine_map.project_level(self.s)
        self.assertEqual(p["boot"], (100, 1.0))
        self.assertEqual({v: p[v][0] for v in (0, 63, 100, 127)}, {0: 0, 63: 63, 100: 100, 127: 127})
        self.close([p[v][1] for v in (0, 63, 100, 127)], [0.0, 0.251189, 1.0, 2.0], 5)


if __name__ == "__main__":
    unittest.main()
