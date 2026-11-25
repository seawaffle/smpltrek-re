"""Tests for cydrums_wavetables.py.

Synthetic tests always run. The stock round trip needs firmware/cydrums/CyDrums_folder.zip (not in the repository)
and skips without it.
"""
import math
import os
import struct
import sys
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cydrums_wavetables as cw

ROOT = Path(__file__).resolve().parent.parent
FOLDER_ZIP = ROOT / "firmware/cydrums/CyDrums_folder.zip"


def synthetic_bank():
    # Name lengths as in the stock file: 53 names of 8-10 characters (12-byte field), 11 of 5-7 (8-byte field).
    entries = [dict(name=f"Short{i:02}" if i < 11 else f"Table_{i:02}", ft=(0x10000, 24000, 0, 0x100000),
                    offset=i * cw.TABLE_BYTES, length=cw.TABLE_BYTES) for i in range(cw.SLOTS)]
    index = cw.build_index(entries)
    data = b"".join(bytes([i]) * cw.TABLE_BYTES for i in range(cw.SLOTS))
    return index + b"\xff" * (cw.DATA_BASE - len(index)) + data


def riff(chunks):
    body = b"WAVE"
    for cid, payload in chunks:
        body += cid + struct.pack("<I", len(payload)) + payload + (b"\0" if len(payload) & 1 else b"")
    return b"RIFF" + struct.pack("<I", len(body)) + body


def pcm_wav(path, channels_samples, bits=16, extensible=False, rate=48000):
    """Write integer samples (one list per channel, full scale = 2 ** (bits - 1)) as PCM WAV."""
    channels = len(channels_samples)
    width = bits // 8
    interleaved = [v for frame in zip(*channels_samples) for v in frame]
    if bits == 8:
        data = bytes(v + 128 for v in interleaved)
    elif bits in (16, 32):
        data = struct.pack("<%d%s" % (len(interleaved), "h" if bits == 16 else "i"), *interleaved)
    else:
        data = b"".join(v.to_bytes(width, "little", signed=True) for v in interleaved)
    if extensible:
        fmt = struct.pack("<HHIIHHHHI", 0xFFFE, channels, rate, rate * channels * width, channels * width, bits,
                          22, bits, 0) + struct.pack("<H", 1) + bytes(14)
    else:
        fmt = struct.pack("<HHIIHH", 1, channels, rate, rate * channels * width, channels * width, bits)
    Path(path).write_bytes(riff([(b"fmt ", fmt), (b"data", data)]))


def table_of(blob, entry):
    return struct.unpack_from("<%dh" % (2048 * 256), blob, entry["data"])


class WavetableBank(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.dir.name)
        self.bank = self.tmp / "SystemCore.bin"
        self.bank.write_bytes(synthetic_bank())

    def tearDown(self):
        self.dir.cleanup()

    def test_index_layout_matches_the_stock_chunk_shapes(self):
        blob = self.bank.read_bytes()
        self.assertEqual(blob[:4], b"WTLS")
        self.assertEqual(struct.unpack_from("<4sIIII", blob, 20)[0], b"WTDT")
        entries = cw.parse(blob)
        self.assertEqual(len(entries), 64)
        self.assertEqual(entries[0]["name"], "Short00")
        self.assertEqual(entries[11]["name"], "Table_11")
        self.assertEqual(entries[0]["data"], 0x1E00)
        self.assertEqual(struct.unpack_from("<I", blob, 4)[0], 7400)               # stock index length
        self.assertEqual(struct.unpack_from("<I", blob, 20 + 4)[0], 112)           # 7-character name: 8-byte field
        self.assertEqual(struct.unpack_from("<I", blob, 20 + 11 * 112 + 4)[0], 116)

    def test_short_new_name_keeps_the_old_field_size_so_the_data_base_stays(self):
        source = self.tmp / "one.wav"
        with wave.open(str(source), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(48000)
            w.writeframes(b"\0\1" * 2048)
        out = self.tmp / "out.bin"
        cw.main(["build", str(self.bank), str(out)] + [f"--set={n}={source}:A" for n in range(12, 65)])
        blob = out.read_bytes()
        self.assertEqual(struct.unpack_from("<I", blob, 4)[0], 7400)
        self.assertEqual(cw.parse(blob)[63]["name"], "A")
        self.assertEqual(cw.parse(blob)[63]["data"], 0x1E00 + 63 * cw.TABLE_BYTES)

    def test_build_without_changes_is_byte_identical(self):
        out = self.tmp / "out.bin"
        cw.main(["build", str(self.bank), str(out)])
        self.assertEqual(out.read_bytes(), self.bank.read_bytes())

    def test_replace_slot_with_morphed_float_wavetable_and_clm_chunk(self):
        frames = []
        for k in range(4):
            t = k / 3
            frames += [(1 - t) * (2 * i / 2048 - 1) + t * (1 if i < 1024 else -1) for i in range(2048)]
        data = b"".join(struct.pack("<ff", v * 0.5, v * 0.5) for v in frames)
        source = self.tmp / "morph.wav"
        source.write_bytes(riff([(b"fmt ", struct.pack("<HHIIHH", 3, 2, 44100, 44100 * 8, 8, 32)),
                                 (b"clm ", b"<!>2048 00000000 test"), (b"data", data)]))
        out = self.tmp / "out.bin"
        cw.main(["build", str(self.bank), str(out), "--set", f"2={source}:MyMorph"])
        blob = out.read_bytes()
        self.assertEqual(len(blob), cw.FILE_LENGTH)
        entries = cw.parse(blob)
        self.assertEqual(entries[1]["name"], "MyMorph")
        self.assertEqual(entries[1]["data"], 0x1E00 + cw.TABLE_BYTES)
        table = struct.unpack_from("<%dh" % (2048 * 256), blob, entries[1]["data"])
        first, last = table[:2048], table[-2048:]
        self.assertEqual(first[0], -16384)            # saw at frame 0
        self.assertEqual(last[0], 16384)              # square at frame 255
        self.assertEqual(last[1500], -16384)
        # untouched neighbours
        self.assertEqual(blob[entries[0]["data"]:entries[0]["data"] + 4], b"\0\0\0\0")
        self.assertEqual(blob[entries[2]["data"]:entries[2]["data"] + 4], b"\2\2\2\2")
        self.assertEqual(entries[2]["name"], "Short02")

    def test_single_odd_sized_frame_is_resampled_and_repeated(self):
        source = self.tmp / "sine.wav"
        with wave.open(str(source), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(48000)
            w.writeframes(b"".join(struct.pack("<h", round(16384 * math.sin(2 * math.pi * i / 600)))
                                   for i in range(600)))
        out = self.tmp / "out.bin"
        cw.main(["build", str(self.bank), str(out), "--set", f"64={source}", "--frame", "600"])
        entries = cw.parse(out.read_bytes())
        self.assertEqual(entries[63]["name"], "sine")
        table = struct.unpack_from("<%dh" % (2048 * 256), out.read_bytes(), entries[63]["data"])
        self.assertEqual(table[512], 16384)   # 512 * 600 / 2048 = 150: the peak sample
        self.assertEqual(table[:2048], table[-2048:])

    def test_bad_slot_and_name_are_refused(self):
        out = self.tmp / "out.bin"
        with self.assertRaises(SystemExit):
            cw.main(["build", str(self.bank), str(out), "--set", "65=x.wav"])
        self.assertFalse(out.exists())
        with self.assertRaises(ValueError):
            cw.parse_set(f"1={self.bank}:bad\tname", None)

    def assertSameTable(self, got, want, label):
        # Not assertEqual: on a mismatch its diff of two 524288-sample tables takes minutes.
        got, want = list(got), list(want)
        if got != want:
            first = next((i for i, (a, b) in enumerate(zip(got, want)) if a != b), min(len(got), len(want)))
            self.fail(f"{label}: tables differ from sample {first} (lengths {len(got)}, {len(want)})")

    def build(self, *sets, frame=None, base=None):
        out = self.tmp / "out.bin"
        if out.exists():
            out.unlink()
        args = ["build", str(base or self.bank), str(out)] + [f"--set={x}" for x in sets]
        cw.main(args + (["--frame", str(frame)] if frame else []))
        blob = out.read_bytes()
        return blob, cw.parse(blob)

    def test_export_then_build_back_is_byte_identical(self):
        # A table using the whole 16-bit range, including -32768 and 32767, survives export and re-import exactly.
        values = [((i * 7919) % 65536) - 32768 for i in range(2048 * 256)]
        values[0], values[1] = -32768, 32767
        source = self.tmp / "full.wav"
        pcm_wav(source, [values])
        blob, entries = self.build(f"5={source}:Full")
        self.assertSameTable(table_of(blob, entries[4]), values, "full range")
        exported = self.tmp / "exp"
        cw.main(["export", str(self.tmp / "out.bin"), str(exported), "--slots", "5"])
        again = self.tmp / "again.bin"
        cw.main(["build", str(self.tmp / "out.bin"), str(again), f"--set=5={exported / '05_Full.wav'}:Full"])
        self.assertEqual(again.read_bytes(), blob)

    def test_every_supported_sample_format_gives_the_same_table(self):
        # One frame of a saw at 1/2 scale in 8, 16, 24 and 32-bit PCM, extensible 24-bit and float.
        saw = [((i // 16) - 64) / 128 for i in range(2048)]                 # -0.5 .. 0.492, steps of 1/128: exact in 8 bits
        reference = None
        for label, bits, extensible in [("p8", 8, False), ("p16", 16, False), ("p24", 24, False),
                                        ("p32", 32, False), ("x24", 24, True)]:
            source = self.tmp / f"{label}.wav"
            pcm_wav(source, [[round(v * (1 << (bits - 1))) for v in saw]], bits, extensible)
            blob, entries = self.build(f"7={source}")
            table = table_of(blob, entries[6])
            self.assertEqual(entries[6]["name"], label)
            if reference is None:
                reference = table
            self.assertSameTable(table, reference, label)
        floats = self.tmp / "f32.wav"
        floats.write_bytes(riff([(b"fmt ", struct.pack("<HHIIHH", 3, 1, 48000, 192000, 4, 32)),
                                 (b"data", struct.pack("<2048f", *saw))]))
        blob, entries = self.build(f"7={floats}")
        self.assertSameTable(table_of(blob, entries[6]), reference, "f32")
        self.assertEqual(reference[0], -16384)
        self.assertEqual(reference[2047], 16128)

    def test_stereo_is_mixed_to_mono_and_overs_are_clipped(self):
        left = [16000] * 2048
        right = [-8000] * 2048
        source = self.tmp / "stereo.wav"
        pcm_wav(source, [left, right])
        blob, entries = self.build(f"3={source}")
        self.assertEqual(set(table_of(blob, entries[2])), {4000})
        hot = self.tmp / "hot.wav"
        hot.write_bytes(riff([(b"fmt ", struct.pack("<HHIIHH", 3, 1, 48000, 192000, 4, 32)),
                              (b"data", struct.pack("<2048f", *([1.5] * 1024 + [-1.5] * 1024)))]))
        blob, entries = self.build(f"3={hot}")
        table = table_of(blob, entries[2])
        self.assertEqual((table[0], table[2047]), (32767, -32768))

    def test_more_than_256_frames_keep_first_and_last_and_sample_evenly(self):
        # 511 frames, frame k constant at k * 64: output frame j sits at source position j * 2, so exactly frame 2j.
        source = self.tmp / "many.wav"
        pcm_wav(source, [[k * 64 for k in range(511) for _ in range(2048)]])
        blob, entries = self.build(f"9={source}")
        table = table_of(blob, entries[8])
        self.assertEqual([table[j * 2048] for j in range(256)], [2 * j * 64 for j in range(256)])
        self.assertEqual(len(set(table[255 * 2048:])), 1)

    def test_frame_size_from_clm_chunk_and_frame_option_override_it(self):
        # 2 frames of 1024 (ramp, then constant); clm says 1024, so 2 frames resampled to 2048 each.
        data = [i * 16 for i in range(1024)] + [-4096] * 1024
        fmt = struct.pack("<HHIIHH", 1, 1, 48000, 96000, 2, 16)
        source = self.tmp / "clm.wav"
        source.write_bytes(riff([(b"fmt ", fmt), (b"clm ", b"<!>1024 10000000 wavetable"),
                                 (b"data", struct.pack("<2048h", *data))]))
        blob, entries = self.build(f"10={source}")
        table = table_of(blob, entries[9])
        self.assertEqual(table[2], 16)                                      # ramp stretched x2 in frame 0
        self.assertEqual(set(table[-2048:]), {-4096})                       # last frame = constant frame
        blob, entries = self.build(f"10={source}", frame=2048)
        table = table_of(blob, entries[9])
        self.assertEqual(table[2], 32)                                      # one 2048 frame, not resampled
        self.assertEqual(table[:2048], table[-2048:])

    def test_names_default_truncate_and_must_be_printable_ascii(self):
        source = self.tmp / "a_really_long_wavetable_name.wav"
        pcm_wav(source, [[0] * 2048])
        _, entries = self.build(f"11={source}")
        self.assertEqual(entries[10]["name"], "a_really_l")
        for bad in ["caf\u00e9", "tab\tbed", ""]:
            with self.assertRaises(SystemExit, msg=bad):
                self.build(f"11={source}:{bad}" if bad else f"11={source}:")
        self.assertFalse((self.tmp / "out.bin").exists())

    def test_path_containing_a_colon_is_not_split(self):
        source = self.tmp / "C:odd.wav"
        pcm_wav(source, [[100] * 2048])
        _, entries = self.build(f"12={source}")
        self.assertEqual(entries[11]["name"], "C:odd")
        _, entries = self.build(f"12={source}:Named")
        self.assertEqual(entries[11]["name"], "Named")

    def test_unusable_inputs_are_refused_without_writing(self):
        short = self.tmp / "short.wav"
        pcm_wav(short, [[0] * 2047])
        text = self.tmp / "text.wav"
        text.write_bytes(b"not a wave file at all")
        adpcm = self.tmp / "adpcm.wav"
        adpcm.write_bytes(riff([(b"fmt ", struct.pack("<HHIIHH", 2, 1, 48000, 24000, 256, 4)), (b"data", bytes(4096))]))
        for source in (short, text, adpcm, self.tmp / "missing.wav"):
            with self.assertRaises(SystemExit, msg=source.name):
                self.build(f"1={source}")
            self.assertFalse((self.tmp / "out.bin").exists())

    def test_renaming_short_fields_grows_the_index_but_the_data_stays_put(self):
        source = self.tmp / "z.wav"
        pcm_wav(source, [[5] * 2048])
        blob, entries = self.build(*[f"{n}={source}:TenLetters" for n in range(1, 65)])
        self.assertEqual(struct.unpack_from("<I", blob, 4)[0], 20 + 64 * 116)  # largest index: 7444
        self.assertEqual([e["data"] for e in entries], [0x1E00 + n * cw.TABLE_BYTES for n in range(64)])
        self.assertEqual(blob[7444:0x1E00], b"\xff" * (0x1E00 - 7444))
        self.assertTrue(all(e["name"] == "TenLetters" for e in entries))

    def test_base_file_without_the_stock_layout_is_refused(self):
        truncated = self.tmp / "truncated.bin"
        truncated.write_bytes(self.bank.read_bytes()[:-1])
        with self.assertRaises(SystemExit):
            self.build(base=truncated)
        with self.assertRaises(ValueError):
            cw.parse(b"RIFF" + bytes(100))


@unittest.skipUnless(FOLDER_ZIP.exists(), "needs firmware/cydrums/CyDrums_folder.zip")
class StockBank(unittest.TestCase):
    def test_stock_file_round_trips_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(FOLDER_ZIP) as archive:
            bank = Path(archive.extract("CyDrums/System/SystemCore.bin", tmp))
            out = Path(tmp) / "out.bin"
            cw.main(["build", str(bank), str(out)])
            self.assertEqual(out.read_bytes(), bank.read_bytes())
            entries = cw.parse(bank.read_bytes())
            self.assertEqual(len(entries), 64)
            self.assertEqual([sum(e["ft"][1] == r for e in entries) for r in (24000, 44100, 384000)], [50, 11, 3])


if __name__ == "__main__":
    unittest.main()
