#!/usr/bin/env python3
"""Optional local-corpus integration: CyDrums 1.1.84 loads a wavetable bank built by tools/cydrums_wavetables.py.

Needs firmware/cydrums/CyDrums_v1.1.84.zip and CyDrums_folder.zip (not in the repository). Builds a 128 MiB card
from the folder with SystemCore.bin rebuilt so that
  - slot 1 (loaded at start-up by the shipped project) is a 4-frame saw-to-square morph,
  - every slot with a short stock name gets a 10-character name, so the index grows from 7400 to its largest
    size (7444 bytes) and every later WTDT record moves,
boots for --seconds, then finds every table the firmware has loaded into RAM and compares each one in full with
the bank on the card. Passes when slot 1 is loaded with the new data and every loaded table equals the card's
data for its slot. With --stock the card keeps the shipped bank (control run).

Usage (from the repository root): python3 -B emulator/tests/stock_cydrums_wavetables.py [--stock] [--seconds 6]
Run time: about 3 minutes each. Work files go to WORK/cydrums-wavetables/ (emulator/build.py). Run --stock first:
the rebuilt run then also checks that it loaded the same slots as the control.
Result (2026-11-24): both pass; 24 slots loaded at start-up (1, 3-21, 43, 45, 62, 63) in both runs, slot 1 with
the new data and no stock slot 1 left in RAM, with the index at 7444 bytes.
"""
import argparse
import json
from pathlib import Path
import shutil
import struct
import sys
import zipfile

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))
from build import WORK
from media import build_card
from project_card import MS
from stock import Stock
import cydrums_wavetables as cw

FIRMWARE = ROOT / "firmware/cydrums/CyDrums_v1.1.84.zip"
FOLDER = ROOT / "firmware/cydrums/CyDrums_folder.zip"
DDR, DDR_SIZE, CHUNK = 0xC0000000, 0x8000000, 0x2000000


def morph_wav(path):
    frames = []
    for k in range(4):
        t = k / 3
        frames += [(1 - t) * (2 * i / 2048 - 1) + t * (1 if i < 1024 else -1) for i in range(2048)]
    data = struct.pack("<%df" % len(frames), *(v * 0.5 for v in frames))
    fmt = struct.pack("<HHIIHH", 3, 1, 48000, 192000, 4, 32)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(data)) + data
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)


def loaded_tables(ram, bank, entries):
    """Slots whose table is somewhere in RAM in full, matched by a frame-1 signature, with their addresses."""
    found = {}
    for slot, entry in enumerate(entries, 1):
        table = bank[entry["data"]:entry["data"] + entry["length"]]
        signature = table[4096:4096 + 256]
        if len(set(signature)) < 8:          # constant or near-constant frame: would match anywhere
            continue
        at = ram.find(signature)
        while at >= 0:
            start = at - 4096
            if start >= 0 and ram[start:start + len(table)] == table:
                found[slot] = DDR + start
                break
            at = ram.find(signature, at + 1)
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--stock", action="store_true", help="control run with the shipped bank")
    parser.add_argument("--seconds", type=float, default=6)
    args = parser.parse_args()
    for path in (FIRMWARE, FOLDER):
        if not path.exists():
            print(f"SKIP: needs {path.relative_to(ROOT)}")
            return 0
    work = WORK / "cydrums-wavetables"
    folder = work / "card"
    if folder.exists():
        shutil.rmtree(folder)
    with zipfile.ZipFile(FOLDER) as archive:
        archive.extractall(folder)
    target = folder / "CyDrums/System/SystemCore.bin"
    stock_bank = target.read_bytes()
    stock_entries = cw.parse(stock_bank)
    if not args.stock:
        source = work / "morph.wav"
        morph_wav(source)
        renames = [n for n, e in enumerate(stock_entries, 1) if e["name_field"] < 12]
        sets = [f"1={source}:MorphTest1"] + [f"{n}={source}:Renamed{n:03}" for n in renames if n != 1]
        # Renaming would replace those slots' data too, so put their stock data back afterwards.
        built = work / "SystemCore.bin"
        cw.main(["build", str(target), str(built)] + [f"--set={s}" for s in sets])
        blob = bytearray(built.read_bytes())
        for n in renames:
            e = stock_entries[n - 1]
            blob[e["data"]:e["data"] + e["length"]] = stock_bank[e["data"]:e["data"] + e["length"]]
        target.write_bytes(blob)
    bank = target.read_bytes()
    entries = cw.parse(bank)
    index_length = struct.unpack_from("<I", bank, 4)[0]
    files = {"/" + str(p.relative_to(folder)): p for p in sorted(folder.rglob("*")) if p.is_file()}
    card = build_card(work / "card.img", files, size_mb=128, long_names=True)

    with Stock(FIRMWARE, card=card, flash_image=None, reserved_low_writes=True, profile="cydrums",
               reserved_low_reads=True) as stock:
        for _ in range(int(args.seconds * 10)):
            report = stock.run(100 * MS, 1000000)
            if report["error"]:
                raise RuntimeError(report["error"])
        ram = b"".join(bytes(stock.cpu.read(DDR + k * CHUNK, CHUNK)) for k in range(DDR_SIZE // CHUNK))

    found = loaded_tables(ram, bank, entries)
    result = dict(bank="stock" if args.stock else "rebuilt", index_length=index_length,
                  names=[e["name"] for e in entries], loaded={str(k): hex(v) for k, v in found.items()})
    (work / f"result-{'stock' if args.stock else 'rebuilt'}.json").write_text(json.dumps(result, indent=1) + "\n")
    print(f"index {index_length} bytes; loaded slots: " + ", ".join(f"{k} at {v:#x}" for k, v in found.items()))
    problems = []
    if 1 not in found:
        problems.append("slot 1 is not in RAM with the card's data")
    if not args.stock:
        if index_length != 20 + 64 * 116:
            problems.append(f"index is {index_length} bytes, expected 7444")
        e = stock_entries[0]
        if ram.find(stock_bank[e["data"] + 4096:e["data"] + 4096 + 256]) >= 0:
            problems.append("the stock slot 1 table is in RAM: the firmware read the old data")
        control = work / "result-stock.json"
        if control.exists():
            expected = set(json.loads(control.read_text())["loaded"])
            if set(result["loaded"]) != expected:
                problems.append(f"loaded slots {sorted(result['loaded'], key=int)} differ from the stock run's "
                                f"{sorted(expected, key=int)}")
        else:
            print("note: no control run yet (--stock), so the loaded slots were not compared")
    print("PASS" if not problems else "FAIL: " + "; ".join(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
