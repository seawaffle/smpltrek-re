#!/usr/bin/env python3
"""Optional local-corpus check: the stock firmware loads a preset instrument on an INST track and plays it.

On a card that holds the factory kits and instrument sounds (project_card.py), in a new project:
  1. Known stop. Choosing INST in the track-type dialog makes the firmware read the label of the
     instrument's WAV through a null pointer (PC 0xc163ac44, address 0x8), which the strict
     low-memory policy refuses. The check pins that stop.
  2. The same presses with the low-read option (a low read returns the held data of earlier loads on its
     data path, as measured in bench M2 and M3): the track gets A.Guitar.wav, two step-recorded notes are entered and the clip
     plays (a two-second loop) for 2.7 guest seconds.

Checked directly in step 2: no fault, the output is audible without underruns, and every low read is
one of the four the label copy makes. Compared with tests/fixtures/stock_inst.json: frames, the low
reads with their values, the last 0.68 s of audio and card traffic. `--record` rewrites the fixture; `--blocks` runs
both steps with compiled blocks against the interpreter's saved result.

The values the low reads return come from the low-read model, whose rule was measured on the unit with
test sequences (bench M2, M3); this code path itself was not run on the unit with its values recorded.

Requires explicit --conditional (the logged reserved low-store assumption).
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
from media import build_card
from project_card import preset_files
from stock_multitrack import CLR, NOTES, OK, RIGHT, Session

EXPECTED = Path(__file__).resolve().parent / "fixtures/stock_inst.json"
CLIP_PLAY = 8
CHOOSE = (OK, RIGHT, RIGHT, OK, 2000)                  # track 1's type dialog: LOOP, SHOT, INST
LABEL_READS = {(0xc163ac44, 8, 4), (0xc163ac48, 12, 1), (0xc163ac4c, 13, 1), (0xc163ac50, 0, 8)}


def run(output, card, flash, compiled, low_reads):
    session = Session(output, "inst" if low_reads else "strict", card, flash, compiled, low_reads)
    with session.stock as stock:
        try:
            session.settle(6000); session.step(CLR)
            for action in CHOOSE:
                session.step(action)
            session.capture("chosen"); session.settle(100)
            for action in NOTES:
                session.step(action)
            session.capture("notes")
            session.step(CLIP_PLAY)
            for second in range(1, 3):
                session.advance(1000); session.capture(f"playing-{second}s")
            session.advance(150)                       # the capture keeps the last 0.68 s: end it inside the second pass's notes
        except RuntimeError as error:
            session.row["fault"] = str(error)
        row = session.finish()
        if low_reads:
            reads = stock.cpu.reserved_low_read_state()
            raw, audio = stock.cpu.audio_output()
            words = struct.unpack(f"<{len(raw) // 4}i", raw[:len(raw) // 4 * 4])
            row.update(low_read_count=reads["count"],
                       low_reads=[[item["pc"], item["address"], item["size"], item["value"]] for item in reads["reads"]],
                       audio_sha256=digest(raw), underruns=audio["underruns"],
                       rms=round(math.sqrt(sum(word * word for word in words) / max(1, len(words))) / 2**31, 6))
        return row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--conditional", action="store_true", help="accept the logged reserved low-store assumption")
    parser.add_argument("--record", action="store_true", help="save this run as the expected result")
    parser.add_argument("--blocks", action="store_true", help="run with compiled blocks and compare with the interpreter's saved result")
    parser.add_argument("--output", type=Path, default=WORK / "stock-inst")
    args = parser.parse_args(argv)
    if not args.conditional:
        parser.error("--conditional is required: this run discards reserved low stores")
    if args.blocks and args.record:
        parser.error("the saved result comes from the interpreter: --record cannot be combined with --blocks")
    args.output.mkdir(parents=True, exist_ok=True)
    files, flash = preset_files(instruments=True)
    card = build_card(args.output / "card.img", files, size_mb=256, long_names=True)
    problems = []

    strict = run(args.output, card, flash, args.blocks, False)
    if not strict["fault"] or "0x00000008" not in strict["fault"] or "0xc163ac44" not in strict["fault"]:
        problems.append(f'choosing INST no longer ends in the known null label read (now: {strict["fault"]}); '
                        "review the low-memory policy notes and this check")
    played = run(args.output, card, flash, args.blocks, True)
    if played["fault"]:
        problems.append(f'fault with the low-read option: {played["fault"]}')
    else:
        other = [read for read in played["low_reads"] if tuple(read[:3]) not in LABEL_READS]
        if other or not played["low_reads"] or played["low_read_count"] != len(played["low_reads"]):
            problems.append(f'low reads other than the label copy: {other[:8]} ({played["low_read_count"]} in all)')
        if played["rms"] < 0.005:
            problems.append(f'output is silent (rms {played["rms"]})')
        if played["underruns"]:
            problems.append(f'{played["underruns"]} audio underruns')
        if len({frame["sha256"] for frame in played["frames"]}) < 4:
            problems.append("the display did not change while playing")
    result = dict(strict=strict, inst=played)

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
    print(f'{"FAIL" if problems else "PASS"}: INST track, {played.get("low_read_count")} low reads, rms {played.get("rms")}; frames in {args.output}')
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
