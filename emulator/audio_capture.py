"""Package captured digital McASP slots as PCM WAV, preserving their signed 32-bit words.

The two WAV channels are slot 0 and slot 1. Physical left/right routing, codec gain and
analog conversion are outside this export. A rolling capture may start at slot 1 or
end at slot 0; discard those incomplete frames instead of swapping channel phase.
"""
import io
import wave

from build import digest


def stereo_wav(raw, first_slot):
    if type(first_slot) is not int or first_slot not in (0, 1):
        raise ValueError("first_slot must be 0 or 1")
    if len(raw) % 4:
        raise ValueError("McASP capture must contain complete 32-bit words")
    words = len(raw) // 4
    leading = min(first_slot, words)
    trailing = (words - leading) % 2
    frames = (words - leading - trailing) // 2
    pcm = raw[leading * 4:(leading + frames * 2) * 4]
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(4)
        wav.setframerate(48000)
        wav.writeframes(pcm)
    data = output.getvalue()
    return data, dict(rate_hz=48000, sample_bits=32, channels=["McASP slot 0", "McASP slot 1"],
                      frames=frames, trimmed_leading_words=leading, trimmed_trailing_words=trailing,
                      sha256=digest(data))
