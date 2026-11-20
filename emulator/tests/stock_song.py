#!/usr/bin/env python3
"""Optional local-corpus check: the stock firmware loads a generated drum project and plays it.

project_card.py builds the card (factory kits written by the firmware itself, plus a project from the
pinned npm generator). The stock image then starts with that card and a factory-like flash, PLAY is
pressed and the song runs for ten guest seconds. Checked directly: no fault, the display moves while
playing, the output is audible and continuous. Compared with tests/fixtures/stock_song.json: the
project file, the final display, the last 0.7 s of audio and the card traffic. `--record` rewrites
the fixture; `--blocks` plays with compiled blocks against the interpreter's saved result.

Requires explicit --conditional (the logged reserved low-store assumption), node and npm.
"""
import argparse
import json
import math
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from build import WORK, digest
from display import png
from project_card import MS, project_card
from stock import Stock

EXPECTED = Path(__file__).resolve().parent / "fixtures/stock_song.json"
PLAY, CLR = 22, 30


def play(output, genre, seed, compiled):
    card, flash, description = project_card(output / "card.img", genre, seed)
    row = dict(project=description, frames=[], fault=None)
    with Stock(card=card, flash_image=flash, reserved_low_writes=True) as stock:
        if compiled:
            from blocks import compile_blocks
            stock.cpu.blocks(True, heat=True)

        def advance(milliseconds):
            for _ in range(milliseconds // 500):
                report = stock.run(500 * MS, 1000000)
                if report["error"]:
                    raise RuntimeError(report["error"])
            if compiled:
                compile_blocks(stock.cpu)

        def press(key):
            stock.key_input(key, True); advance(500)
            stock.key_input(key, False); advance(500)

        def capture(label):
            frame, _ = stock.cpu.oled_frame()
            (output / f"{label}.png").write_bytes(png(frame))
            row["frames"].append(dict(label=label, sha256=digest(frame)))

        try:
            advance(6000); press(CLR); capture("loaded")
            press(PLAY)
            for second in (2, 4, 6, 8, 10):
                advance(2000); capture(f"playing-{second}s")
        except RuntimeError as error:
            row["fault"] = str(error)
        raw, audio = stock.cpu.audio_output()
        words = struct.unpack(f"<{len(raw) // 4}i", raw[:len(raw) // 4 * 4])
        sd = stock.cpu.sd_state()
        row.update(cycles=stock.cpu.cycles(), audio_sha256=digest(raw), underruns=audio["underruns"],
                   rms=round(math.sqrt(sum(word * word for word in words) / max(1, len(words))) / 2**31, 6),
                   sd=dict(bytes_read=sd["bytes_read"], bytes_written=sd["bytes_written"]))
        host = stock.cpu.block_state() if compiled else None
    return row, host


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--conditional", action="store_true", help="accept the logged reserved low-store assumption")
    parser.add_argument("--record", action="store_true", help="save this run as the expected result")
    parser.add_argument("--blocks", action="store_true", help="play with compiled blocks and compare with the interpreter's saved result")
    parser.add_argument("--genre", default="FUNK")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--output", type=Path, default=WORK / "stock-song")
    args = parser.parse_args(argv)
    if not args.conditional:
        parser.error("--conditional is required: this run discards reserved low stores")
    if args.blocks and args.record:
        parser.error("the saved result comes from the interpreter: --record cannot be combined with --blocks")
    args.output.mkdir(parents=True, exist_ok=True)
    row, host = play(args.output, args.genre, args.seed, args.blocks)
    (args.output / "result.json").write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
    problems = []
    if row["fault"]:
        problems.append(f'fault: {row["fault"]}')
    if len({frame["sha256"] for frame in row["frames"]}) < 4:
        problems.append("the display did not change while playing")
    if row["rms"] < 0.005:
        problems.append(f'output is silent (rms {row["rms"]})')
    if row["underruns"]:
        problems.append(f'{row["underruns"]} audio underruns')
    key = f"{args.genre} {args.seed}"
    saved = json.loads(EXPECTED.read_text()) if EXPECTED.exists() else {}
    if args.record and not problems:
        saved[key] = row
        EXPECTED.write_text(json.dumps(saved, indent=2, sort_keys=True) + "\n")
        print(f"Recorded {key} in {EXPECTED}")
    elif not args.record:
        if key not in saved:
            problems.append(f"no saved result for {key}; run with --record and review it")
        elif row != saved[key]:
            problems.append("differs from the saved result in: " + ", ".join(name for name in row if row[name] != saved[key].get(name)))
    summary = f'{row["project"]["clips"]} clips at {row["project"]["bpm"]} BPM on {row["project"]["kit"]}, rms {row["rms"]}, {row["sd"]["bytes_read"]} card bytes read'
    if host:
        summary += f', {host["block_cycles"] * 100 // max(1, row["cycles"])}% of cycles in host code'
    for problem in problems:
        print("FAIL:", problem)
    print(f'{"FAIL" if problems else "PASS"}: {key}: {summary}; frames in {args.output}')
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
