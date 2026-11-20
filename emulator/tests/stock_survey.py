#!/usr/bin/env python3
"""Optional local-corpus regression: every stock image starts and answers the same key presses.

Each SmplTrek and Lofi-12 XT update under firmware/ is booted on the board model with an erased flash,
once with no card and once with a blank 32 MiB FAT card, then MIXER and HOME are pressed. A run that
stops at a read of reserved low memory is repeated with the low-read option (a low read returns the
held data of earlier loads on its data path, measured in bench M2 and M3 with test sequences, not on these code paths), as a
separate result. The display after each stage, the audio output and
any fault are compared with the results saved in tests/fixtures/stock_survey.json (keyed by the
update's SHA-256 and the card state). `--record` rewrites that file from the current run; review the diff.

Requires explicit --conditional: reserved low CPU stores are discarded, as in stock_boot.py. An
image that faults is expected to keep faulting at the
same instruction and cycle until the cause is settled; that is recorded, not hidden.

`--blocks` repeats the runs with compiled blocks (experimental host code for hot guest code),
compiling as each run goes. The saved results come from the interpreter, so this is a check that
host code leaves exactly the interpreter's display, audio, card traffic and faults.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from build import ROOT, WORK, digest
from display import png
from media import build_card

EXPECTED = Path(__file__).resolve().parent / "fixtures/stock_survey.json"
# (checksum profile, folder, updates in it). The CyDrums folder also holds an archive of card contents.
PRODUCTS = (("smpltrek", "firmware/smpltrek", "*.zip"), ("lofi12", "firmware/lofi12", "*.zip"), ("cydrums", "firmware/cydrums", "CyDrums_v*.zip"))
MIXER, HOME = 21, 27
BOOT, HOLD, SETTLE = 2200000000, 40000000, 250000000
COMPILE_EVERY = 200000000


def survey(job):
    path, profile, card, output, compiled, low_reads = job
    from stock import Stock
    row = dict(file=path.name, profile=profile, card=("blank card" if card else "no card") + (", low reads" if low_reads else ""),
               stages=[], fault=None)
    with Stock(path, card=card, reserved_low_writes=True, profile=profile, reserved_low_reads=low_reads) as stock:
        row["sha256"], row["version"] = stock.input["sha256"], stock.input["version"]
        folder = output / f'{profile}-{row["version"]}-{row["card"].replace(",", "").replace(" ", "-")}'
        folder.mkdir(parents=True, exist_ok=True)

        if compiled:
            from blocks import compile_blocks
            stock.cpu.blocks(True, heat=True)

        def advance(cycles):
            while cycles:
                part = min(cycles, COMPILE_EVERY) if compiled else cycles
                report = stock.run(part, 1000000)
                if report["error"]:
                    raise RuntimeError(report["error"])
                cycles -= part
                if compiled:
                    compile_blocks(stock.cpu)

        def capture(label):
            frame, oled = stock.cpu.oled_frame()
            (folder / f"{label}.png").write_bytes(png(frame))
            row["stages"].append(dict(label=label, cycles=stock.cpu.state()["cycles"], frame_sha256=digest(frame),
                                      drew=oled["complete_frames"] > 0))

        try:
            advance(BOOT); capture("boot")
            for key, label in ((MIXER, "mixer"), (HOME, "home")):
                stock.key_input(key, True); advance(HOLD)
                stock.key_input(key, False); advance(SETTLE)
                capture(label)
        except RuntimeError as error:
            row["fault"] = str(error)
            capture("fault")
        raw, audio = stock.cpu.audio_output()
        row["audio"] = dict(sha256=digest(raw), transmitted_words=audio["transmitted_words"],
                            underruns=audio["underruns"], overruns=audio["overruns"])
        sd = stock.cpu.sd_state()
        row["sd"] = dict(bytes_read=sd["bytes_read"], bytes_written=sd["bytes_written"])
        row["host"] = stock.cpu.block_state() if compiled else None
        if low_reads:
            row["low_reads"] = stock.cpu.reserved_low_read_state()["count"]
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--conditional", action="store_true", help="accept the logged reserved low-store assumption")
    parser.add_argument("--record", action="store_true", help="save this run as the expected results")
    parser.add_argument("--blocks", action="store_true", help="run with compiled blocks and compare with the interpreter's saved results")
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    parser.add_argument("--output", type=Path, default=WORK / "stock-survey")
    args = parser.parse_args(argv)
    if args.blocks and args.record:
        parser.error("saved results come from the interpreter: --record cannot be combined with --blocks")
    if not args.conditional:
        parser.error("--conditional is required: this run discards reserved low stores")
    images = [(path, profile) for profile, folder, pattern in PRODUCTS for path in sorted((ROOT / folder).glob(pattern))]
    if not images:
        print("SKIP: no stock updates under firmware/")
        return 0
    blank = build_card(args.output / "blank.img", size_mb=32)
    jobs = [(path, profile, card, args.output) for path, profile in images for card in (None, blank)]
    jobs = [(*job, args.blocks, False) for job in jobs]
    if args.blocks:
        from blocks import share_compilers
        share_compilers(args.jobs)
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        rows = list(pool.map(survey, jobs))
        # Every strict stop so far is a read of reserved low memory: run those again with the low-read option.
        again = [(*job[:5], True) for job, row in zip(jobs, rows) if row["fault"] and "memory access at 0x00" in row["fault"]]
        rows += list(pool.map(survey, again))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "result.json").write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n")
    host = {f'{row["sha256"]} {row["card"]}': f', {row["host"]["installed"]} blocks, {row["host"]["block_cycles"]} cycles in host code'
            for row in rows if row["host"]}
    current = {f'{row["sha256"]} {row["card"]}': {key: row[key] for key in ("file", "profile", "version", "card", "stages", "fault", "audio", "sd", "low_reads") if key in row}
               for row in rows}
    if args.record:
        EXPECTED.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
        print(f"Recorded {len(current)} runs in {EXPECTED}")
        return 0
    expected = json.loads(EXPECTED.read_text())
    failed = 0
    for sha, row in current.items():
        name = f'{row["profile"]} {row["version"]}, {row["card"]}'
        if sha not in expected:
            print(f"NEW   {name}: no saved result ({row['file']})"); failed += 1
        elif row != expected[sha]:
            differing = [key for key in row if row[key] != expected[sha].get(key)]
            print(f"FAIL  {name}: {', '.join(differing)} differ; fault: {row['fault']}"); failed += 1
        else:
            print(f'ok    {name}: {"fault as recorded" if row["fault"] else row["stages"][-1]["label"] + " reached"}' + host.get(sha, ""))
    print(f'{"FAIL" if failed else "PASS"}: {len(current) - failed} of {len(current)} runs match; frames in {args.output}')
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
