#!/usr/bin/env python3
"""Optional local-corpus check: a pad hit plays a drum when the panel MCU's report stream is on.

On a card with the factory kits, a new project gets a DRUM track with the Rock kit. Then pad 1's
level goes to 9000 for 150 guest ms and back to 0, in two machines:
  1. With the panel stream: the MCU model reports all 16 channels continuously (4194 messages a
     second and the channel order measured on the bench; spacing and idle levels assumed) and the pad's
     level is what channel 0 reports. The drum sounds.
  2. Without it: one report with the level and one with 0, as the checks and the panel send by
     default. The firmware plays nothing. That is pinned here as a known difference from the unit,
     where reports never stop.

Checked directly: no fault, sound with the stream, silence without, no underruns. Compared with
tests/fixtures/stock_pad.json: frames, the last 0.68 s of audio, messages sent. `--record` rewrites
the fixture; `--blocks` runs both with compiled blocks against the interpreter's saved result.
Speed with the stream is printed, not compared.

Requires explicit --conditional (the logged reserved low-store assumption).
"""
import argparse
import json
import math
from pathlib import Path
import struct
import sys
import time

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from build import WORK, digest
from media import build_card
from project_card import preset_files
from stock_multitrack import CLR, OK, RIGHT, Session

EXPECTED = Path(__file__).resolve().parent / "fixtures/stock_pad.json"
DRUM = (OK, RIGHT, RIGHT, RIGHT, OK, OK, CLR)          # track 1's type dialog to DRUM, load the kit offered, close the pop-up
LEVEL = 9000


def run(output, card, flash, compiled, stream):
    session = Session(output, "stream" if stream else "single", card, flash, compiled, panel_stream=stream)
    seconds = None
    with session.stock as stock:
        try:
            session.settle(6000); session.step(CLR)
            for action in DRUM:
                session.step(action)
            session.capture("kit"); session.settle(100)
            started = time.perf_counter()
            for level in (LEVEL, 0):
                if stream:
                    stock.panel_level(0, level)
                else:
                    stock.uart_receive(1, bytes([0xb0, level & 0x7f, level >> 7]))
                session.advance(150)
            session.advance(200)
            seconds = time.perf_counter() - started
            session.capture("hit")
        except RuntimeError as error:
            session.row["fault"] = str(error)
        row = session.finish()
        raw, audio = stock.cpu.audio_output()
        words = struct.unpack(f"<{len(raw) // 4}i", raw[:len(raw) // 4 * 4])
        row.update(audio_sha256=digest(raw), underruns=audio["underruns"], messages=stock.cpu.panel_stream_state()["messages"],
                   rms=round(math.sqrt(sum(word * word for word in words) / max(1, len(words))) / 2**31, 6))
    return row, seconds


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--conditional", action="store_true", help="accept the logged reserved low-store assumption")
    parser.add_argument("--record", action="store_true", help="save this run as the expected result")
    parser.add_argument("--blocks", action="store_true", help="run with compiled blocks and compare with the interpreter's saved result")
    parser.add_argument("--output", type=Path, default=WORK / "stock-pad")
    args = parser.parse_args(argv)
    if not args.conditional:
        parser.error("--conditional is required: this run discards reserved low stores")
    if args.blocks and args.record:
        parser.error("the saved result comes from the interpreter: --record cannot be combined with --blocks")
    args.output.mkdir(parents=True, exist_ok=True)
    files, flash = preset_files()
    card = build_card(args.output / "card.img", files, size_mb=256, long_names=True)
    problems = []
    stream, seconds = run(args.output, card, flash, args.blocks, True)
    single, _ = run(args.output, card, flash, args.blocks, False)
    for name, row in (("with the stream", stream), ("with single reports", single)):
        if row["fault"]:
            problems.append(f'fault {name}: {row["fault"]}')
        if row["underruns"]:
            problems.append(f'{row["underruns"]} audio underruns {name}')
    if stream["rms"] < 0.005:
        problems.append(f'the pad hit is silent with the stream (rms {stream["rms"]})')
    if single["rms"] >= 0.005 and not single["fault"]:
        problems.append(f'single reports now play the drum (rms {single["rms"]}): review the note in this check and the README')
    result = dict(stream=stream, single=single)

    (args.output / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    saved = json.loads(EXPECTED.read_text()) if EXPECTED.exists() else None
    if args.record and not problems:
        EXPECTED.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(f"Recorded in {EXPECTED}")
    elif not args.record:
        if saved is None:
            problems.append("no saved result; run with --record and review it")
        else:
            for name in sorted(set(result) | set(saved)):
                if result.get(name) != saved.get(name):
                    ours, theirs = result.get(name) or {}, saved.get(name) or {}
                    problems.append(f"{name} differs from the saved result in: " +
                                    ", ".join(key for key in sorted(set(ours) | set(theirs)) if ours.get(key) != theirs.get(key)))
    for problem in problems:
        print("FAIL:", problem)
    speed = f", {0.5 / seconds:.2f}x real time around the hit" if seconds else ""
    print(f'{"FAIL" if problems else "PASS"}: pad hit rms {stream["rms"]} with the stream ({stream["messages"]} messages{speed}), '
          f'{single["rms"]} with single reports; frames in {args.output}')
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
