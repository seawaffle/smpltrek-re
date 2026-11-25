#!/usr/bin/env python3
"""cydrums_wavetables.py -- read and build CyDrums' wavetable bank, /CyDrums/System/SystemCore.bin.

CyDrums' 64 oscillator wavetables are not in the firmware. They live on the card in SystemCore.bin, which ships in
Sonicware's CyDrums_folder.zip. This tool lists that file, exports its tables as WAV files, and builds a new
SystemCore.bin with chosen slots replaced by your own wavetables. Plain Python 3 standard library.

File format (decoded from the 1.1.84 card file and code: index reader 0xC25ABBF0, WTDT loop 0xC25ABB4C, child
loop 0xC25ABA08, table loader 0xC25AB8D0; docs/01-platform-map.md, "CyDrums wavetable bank"):

  Every chunk is   tag[4]  u32 total_length (header included)  u32 a  u32 b  u32 c   then its payload.
  0x0000  WTLS     a = 0, b = 64 (entries), c = payload length (total - 20); payload = 64 WTDT chunks
            WTDT   a = 0, b = 3 (children), c = 0; payload = WTNM, WTFT, WTPL (112 or 116 bytes in all)
              WTNM a = 0, b = 1, c = n;  payload = name, NUL-terminated, 0xFF-padded to n = a multiple of 4
              WTFT a = 0, b = 1, c = 16; payload = u16 0, u16 channels (1), u32 rate, u32 0, u16 0, u16 bits (16)
              WTPL a = 0, b = 1, c = 8;  payload = u32 data offset, u32 data length (0x00100000)
  index end (7400 bytes in the stock file) .. base   0xFF fill; base = index length rounded up to 512 (0x1E00)
  base + offset                      table data: 1 MiB = 256 frames x 2048 samples, signed 16-bit little-endian

What is known and what is not:
  - Slot order is the wavetable number (WAVE 1-64 on the unit). Sound patches store that number (PWT0 chunk,
    first u16, 0-based, 0xFFFF = none) and also the stock source file name (PWP0), taken from a fixed 64-entry
    table in the firmware (0xC26C4950). So a replacement keeps its slot, and patches that used the slot get the
    new waveform. Whether the firmware resolves a patch by PWP0 name or by PWT0 number is not traced.
  - The name on screen comes from WTNM (the firmware has no copy of the short names). Stock names are 8-10
    characters; this tool allows at most 10.
  - The parser's table has 64 entries, so the bank cannot grow.
  - Tables load on demand, when a sound uses them: the loader allocates 1 MiB, seeks to base + WTPL offset, reads
    WTPL length bytes and keeps WTFT's channels, rate and bits; sample count = length / (bits / 8 * channels).
    The index reader sets base = (WTLS length + 511) & ~511 (0xC25ABCC8).
  - WTFT's rate is 24000 for 50 stock tables, 44100 for 11 and 384000 for the 3 sampled ones (stock source names
    say "_24k_"). Where the engine uses it is not traced; this tool writes 24000 unless told otherwise. Channels
    and bits stay 1 and 16, the only layout seen.
  - This tool keeps the data at 0x1E00, so a rebuilt name field is never smaller than the base file's: the index
    stays 7400-7444 bytes, which rounds to 0x1E00.
  - Checked in the emulator (CyDrums 1.1.84, 2026-11-24, emulator/tests/stock_cydrums_wavetables.py): with slot 1
    replaced and every short name lengthened (index 7444 bytes), the firmware loads the same 24 slots as with the
    shipped bank, slot 1 with the new data, all equal to the card. Not run on a unit; sound not checked.

Usage:
  python3 -B tools/cydrums_wavetables.py list SystemCore.bin
  python3 -B tools/cydrums_wavetables.py export SystemCore.bin OUTDIR [--slots 1,5,64]
  python3 -B tools/cydrums_wavetables.py build SystemCore.bin OUT.bin --set 1=mytable.wav[:NAME] [--set ...]
      [--rate 24000]

Input WAVs for --set: mono or stereo (mixed to mono), 8/16/24/32-bit PCM or 32-bit float. The file is cut into
frames of 2048 samples (Serum and Vital export this frame size), or of the size given by a Serum 'clm ' chunk
("<!>N"), or by --frame N. Frames of another size are resampled to 2048 by linear interpolation (periodic). The
frame count is then brought to 256 by sampling the frames at 256 even positions, first to last, blending the two
nearest frames linearly (fewer frames become a morph; a single frame is repeated). Peak level is kept; samples are clipped to 16 bits.

SystemCore.bin and anything exported from it are Sonicware's content: keep them local, never in this repository.
"""
import argparse
import array
import math
import os
import struct
import sys
import wave

SLOTS = 64
FRAME = 2048
FRAMES = 256
TABLE_BYTES = FRAME * FRAMES * 2
DATA_BASE = 0x1E00
FILE_LENGTH = DATA_BASE + SLOTS * TABLE_BYTES
NAME_MAX = 10


def chunk(tag, a, b, c, payload):
    return struct.pack("<4sIIII", tag, 20 + len(payload), a, b, c) + payload


def parse(blob):
    """Return the 64 index entries of a SystemCore.bin as dicts (name, ft, offset, length)."""
    tag, length, _, count, size = struct.unpack_from("<4sIIII", blob, 0)
    if tag != b"WTLS" or size != length - 20:
        raise ValueError("not a CyDrums SystemCore.bin (no WTLS index)")
    entries, p = [], 20
    while p < length:
        t, l, _, children, _ = struct.unpack_from("<4sIIII", blob, p)
        if t != b"WTDT":
            raise ValueError(f"expected WTDT at {p:#x}, found {t!r}")
        entry, q = {}, p + 20
        for _ in range(children):
            tt, ll, _, _, ss = struct.unpack_from("<4sIIII", blob, q)
            body = blob[q + 20:q + 20 + ss]
            if tt == b"WTNM":
                entry["name"] = body.split(b"\0")[0].decode("ascii")
                entry["name_field"] = ss
            elif tt == b"WTFT":
                entry["ft"] = struct.unpack("<4I", body)
            elif tt == b"WTPL":
                entry["offset"], entry["length"] = struct.unpack("<2I", body)
            q += ll
        entries.append(entry)
        p += l
    if len(entries) != count:
        raise ValueError(f"index says {count} entries, found {len(entries)}")
    base = (length + 511) // 512 * 512
    for entry in entries:
        entry["data"] = base + entry["offset"]
    return entries


def build_index(entries):
    records = b""
    for entry in entries:
        name = entry["name"].encode("ascii") + b"\0"
        name = name.ljust(max((len(name) + 3) // 4 * 4, entry.get("name_field", 0)), b"\xff")
        records += chunk(b"WTDT", 0, 3, 0,
                         chunk(b"WTNM", 0, 1, len(name), name)
                         + chunk(b"WTFT", 0, 1, 16, struct.pack("<4I", *entry["ft"]))
                         + chunk(b"WTPL", 0, 1, 8, struct.pack("<2I", entry["offset"], entry["length"])))
    return chunk(b"WTLS", 0, len(entries), len(records), records)


def read_wav(path):
    """Return (mono float samples in -1..1, frame size from a Serum clm chunk or None)."""
    with open(path, "rb") as f:
        riff = f.read()
    if riff[:4] != b"RIFF" or riff[8:12] != b"WAVE":
        raise ValueError(f"{path}: not a RIFF WAVE file")
    fmt = data = None
    clm = None
    p = 12
    while p + 8 <= len(riff):
        cid, size = struct.unpack_from("<4sI", riff, p)
        body = riff[p + 8:p + 8 + size]
        if cid == b"fmt ":
            fmt = struct.unpack_from("<HHIIHH", body)
        elif cid == b"data":
            data = body
        elif cid == b"clm " and body[:3] == b"<!>":
            digits = body[3:].split(b" ")[0]
            if digits.isdigit():
                clm = int(digits)
        p += 8 + size + (size & 1)
    if fmt is None or data is None:
        raise ValueError(f"{path}: missing fmt or data chunk")
    tag, channels, _, _, _, bits = fmt
    if tag == 0xFFFE:
        tag = struct.unpack_from("<H", riff, riff.find(b"fmt ") + 8 + 24)[0]
    if not ((tag == 3 and bits == 32) or (tag == 1 and bits in (8, 16, 24, 32))) or channels < 1:
        raise ValueError(f"{path}: unsupported WAV format {tag} / {bits}-bit / {channels} channels")
    width = bits // 8
    frames = len(data) // (width * channels)
    if tag == 3 and bits == 32:
        values = array.array("f", data[:frames * channels * 4])
        if sys.byteorder != "little":
            values.byteswap()
        scale = 1.0
    elif tag == 1 and bits in (8, 16, 24, 32):
        if bits == 8:
            values = [b - 128 for b in data[:frames * channels]]
        elif bits == 24:
            values = [int.from_bytes(data[i:i + 3], "little", signed=True) for i in range(0, frames * channels * 3, 3)]
        else:
            values = array.array("h" if bits == 16 else "i", data[:frames * channels * width])
            if sys.byteorder != "little":
                values.byteswap()
        scale = float(1 << (bits - 1))
    else:
        raise ValueError(f"{path}: unsupported WAV format {tag} / {bits}-bit")
    mono = [sum(values[i * channels:(i + 1) * channels]) / (channels * scale) for i in range(frames)]
    return mono, clm


def resample_frame(frame, size):
    if len(frame) == size:
        return list(frame)
    n = len(frame)
    out = []
    for i in range(size):
        x = i * n / size
        j = int(x)
        t = x - j
        out.append(frame[j] * (1 - t) + frame[(j + 1) % n] * t)
    return out


def to_table(samples, frame_size):
    """Turn mono samples into 256 frames of 2048 signed 16-bit samples (bytes)."""
    if len(samples) < frame_size:
        raise ValueError(f"shorter than one {frame_size}-sample frame")
    count = len(samples) // frame_size
    frames = [resample_frame(samples[i * frame_size:(i + 1) * frame_size], FRAME) for i in range(count)]
    out = []
    for k in range(FRAMES):
        if count == 1:
            out.append(frames[0])
            continue
        x = k * (count - 1) / (FRAMES - 1)
        j = min(int(x), count - 2)
        t = x - j
        a, b = frames[j], frames[j + 1]
        out.append([a[i] * (1 - t) + b[i] * t for i in range(FRAME)])
    # The same scale as read_wav (full scale = 32768), so a 16-bit table exported and built back is unchanged.
    pcm = array.array("h", (max(-32768, min(32767, round(v * 32768))) for frame in out for v in frame))
    if sys.byteorder != "little":
        pcm.byteswap()
    return pcm.tobytes()


def write_wav(path, data, rate):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data)


def parse_set(text, frame):
    slot_text, _, rest = text.partition("=")
    path, name = rest, None
    if ":" in rest and not os.path.exists(rest):
        path, name = rest.rsplit(":", 1)
    slot = int(slot_text)
    if not 1 <= slot <= SLOTS:
        raise ValueError(f"slot {slot} is not 1-{SLOTS}")
    if name is None:
        name = os.path.splitext(os.path.basename(path))[0]
    name = name[:NAME_MAX]
    if not name or not all(32 <= ord(c) < 127 for c in name):
        raise ValueError(f"name {name!r} must be 1-{NAME_MAX} printable ASCII characters")
    samples, clm = read_wav(path)
    return slot, name, to_table(samples, frame or clm or FRAME)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_list = sub.add_parser("list", help="print the index")
    p_list.add_argument("bank")
    p_export = sub.add_parser("export", help="write slots as 16-bit mono WAV files (2048-sample frames)")
    p_export.add_argument("bank")
    p_export.add_argument("outdir")
    p_export.add_argument("--slots", help="comma-separated slot numbers (1-64); default all")
    p_build = sub.add_parser("build", help="copy a bank with slots replaced")
    p_build.add_argument("bank")
    p_build.add_argument("output")
    p_build.add_argument("--set", action="append", default=[], metavar="SLOT=FILE.wav[:NAME]")
    p_build.add_argument("--rate", type=int, default=24000, help="WTFT rate word for replaced slots")
    p_build.add_argument("--frame", type=int, help="input frame size (default: clm chunk, else 2048)")
    args = parser.parse_args(argv)

    with open(args.bank, "rb") as f:
        blob = f.read()
    entries = parse(blob)

    if args.command == "list":
        for i, e in enumerate(entries, 1):
            print(f"{i:2}  {e['name']:<10}  rate {e['ft'][1]:6}  data {e['data']:#09x} + {e['length']:#x}")
        return 0

    if args.command == "export":
        os.makedirs(args.outdir, exist_ok=True)
        slots = [int(s) for s in args.slots.split(",")] if args.slots else range(1, SLOTS + 1)
        for slot in slots:
            e = entries[slot - 1]
            path = os.path.join(args.outdir, f"{slot:02}_{e['name']}.wav")
            write_wav(path, blob[e["data"]:e["data"] + e["length"]], e["ft"][1])
            print(path)
        return 0

    if len(blob) != FILE_LENGTH or len(entries) != SLOTS or any(
            e["offset"] != i * TABLE_BYTES or e["length"] != TABLE_BYTES for i, e in enumerate(entries)):
        raise SystemExit("base bank does not have the stock layout (64 x 1 MiB from 0x1E00); refusing to build")
    out = bytearray(blob)
    for text in args.set:
        try:
            slot, name, table = parse_set(text, args.frame)
        except (ValueError, OSError) as error:
            raise SystemExit(f"--set {text}: {error}; nothing written")
        e = entries[slot - 1]
        e["name"] = name
        e["ft"] = (e["ft"][0], args.rate, e["ft"][2], e["ft"][3])
        out[e["data"]:e["data"] + TABLE_BYTES] = table
        print(f"slot {slot:2}: {name}")
    index = build_index(entries)
    if not 7168 < len(index) <= DATA_BASE:
        raise SystemExit(f"index of {len(index)} bytes would move the data base; refusing to build")
    out[:DATA_BASE] = index + b"\xff" * (DATA_BASE - len(index))
    with open(args.output, "wb") as f:
        f.write(out)
    print(f"wrote {args.output} ({len(out)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
