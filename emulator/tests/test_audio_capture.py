"""WAV framing must preserve digital words and rolling-capture channel phase."""
import io
from pathlib import Path
import struct
import sys
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audio_capture import stereo_wav


class AudioCapture(unittest.TestCase):
    def decode(self, raw, first_slot):
        data, info = stereo_wav(raw, first_slot)
        with wave.open(io.BytesIO(data), "rb") as wav:
            self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (2, 4, 48000))
            self.assertEqual(wav.getnframes(), info["frames"])
            return wav.readframes(wav.getnframes()), info

    def test_slot_one_start_discards_both_incomplete_frames(self):
        # First and last words belong to different incomplete stereo frames.
        raw = struct.pack("<4i", -99, -2147483648, 2147483647, 88)
        pcm, info = self.decode(raw, 1)
        self.assertEqual(pcm, struct.pack("<2i", -2147483648, 2147483647))
        self.assertEqual((info["frames"], info["trimmed_leading_words"], info["trimmed_trailing_words"]), (1, 1, 1))

    def test_slot_zero_start_keeps_exact_words_and_drops_only_the_final_half_frame(self):
        raw = struct.pack("<5i", 0x1020304, -0x1020304, 0, -1, 42)
        pcm, info = self.decode(raw, 0)
        self.assertEqual(pcm, raw[:16])
        self.assertEqual((info["frames"], info["trimmed_leading_words"], info["trimmed_trailing_words"]), (2, 0, 1))

    def test_short_capture_has_no_invented_channel_samples(self):
        for raw in (b"", struct.pack("<i", 123)):
            for first_slot in (0, 1):
                with self.subTest(raw=raw, first_slot=first_slot):
                    pcm, info = self.decode(raw, first_slot)
                    self.assertEqual(pcm, b"")
                    self.assertEqual(info["frames"], 0)

    def test_invalid_slot_or_partial_word_fails(self):
        for slot in (-1, 2, True, 0.0):
            with self.subTest(slot=slot), self.assertRaises(ValueError):
                stereo_wav(bytes(8), slot)
        with self.assertRaises(ValueError):
            stereo_wav(bytes(7), 0)


if __name__ == "__main__":
    unittest.main()
