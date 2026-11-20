#!/usr/bin/env python3
"""Optional local-corpus soak: seeded random panel input on the stock firmware.

After start-up with a blank card, each seed presses keys, turns knobs and hits pads at random for
a number of guest seconds. Every seed runs twice, on the interpreter and with compiled blocks, and
the two must end in the same CPU state, display, audio, card and device trace. A guest fault is
reported with the inputs that led to it; the same fault must then appear in both runs.

`--samples` starts from a card holding four short WAV files in the sample pool, so the input can
reach previewing, sample assignment and playback; without it the card is blank. `--project GENRE`
starts instead from a generated project card with the factory kits and the factory-like flash
(project_card.py; needs node and npm), dismisses the card notice with CLR, and so lets the input
reach playback of a real song, saving and loading. `--panel-stream` turns on the panel MCU's
continuous reports (see the README), under which pad hits are heard by the firmware as on the unit:
without it a hit is two single reports, which the firmware largely ignores. `--reserved-low-reads`
adds the opt-in assumption that reserved low memory reads as zero; without it such a read is a
fault, as everywhere else by default, and the seed ends there.

Requires explicit --conditional, as stock_boot.py: reserved low CPU stores are discarded. Faults found here are findings about the emulator or about
those assumptions, not test failures in themselves; a mismatch between the two runs is a failure.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import math
import random
import struct
import sys
import wave

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from build import WORK
from display import png
from media import build_card

SECOND = 372000000
KEYS = [0, 1, 2, 3, 4, 8, 9, *range(16, 48)]
PHASES = {1: (2, 0, 1, 3), -1: (1, 0, 2, 3)}          # one detent, as stock_ui.py sends it
PHASE_CYCLES = 2 * SECOND // 1000
BYTE_CYCLES = 8000


def script(seed, seconds, stream=False):
    """[(cycle offset, kind, a, b)] sorted by time: key a down/up b, encoder a phase b, and for a pad either
    the bytes of its two reports (uart a) or, with the panel stream, its two levels (level a b)."""
    rng, events, now = random.Random(seed), [], 0
    while now < seconds * SECOND:
        now += rng.randrange(SECOND // 25, SECOND // 2)
        kind = rng.choices(("key", "chord", "encoder", "pad"), (10, 2, 4, 3))[0]
        if kind in ("key", "chord"):
            keys = [19, rng.choice(KEYS)] if kind == "chord" else [rng.choice(KEYS)]   # 19 is FUNC
            hold = rng.randrange(SECOND // 30, SECOND // 4)
            for index, key in enumerate(keys):
                events.append((now + index * SECOND // 50, "key", key, 1))
            for key in keys:
                events.append((now + hold + SECOND // 25, "key", key, 0))
        elif kind == "encoder":
            encoder, step = rng.randrange(5), rng.choice((-1, 1))
            for detent in range(rng.randrange(1, 6)):
                for offset, phase in enumerate(PHASES[step]):
                    events.append((now + (detent * 4 + offset) * PHASE_CYCLES, "phase", encoder, phase))
        else:
            pad, value = rng.randrange(15), rng.randrange(900, 16384)
            hold = rng.randrange(SECOND // 30, SECOND // 3)
            for start, level in ((now, value), (now + hold, 0)):
                if stream:
                    events.append((start, "level", pad, level))
                else:
                    for offset, byte in enumerate((0xb0 | pad, level & 0x7f, level >> 7)):
                        events.append((start + offset * BYTE_CYCLES, "uart", byte, 0))
    return sorted(events, key=lambda event: event[0])


def sample_card(output):
    """A 32 MiB card with four deterministic stereo 48 kHz WAV files in the sample pool."""
    rng, files = random.Random(6748), {}
    shapes = {"KICK": lambda t: math.sin(math.tau * (45 * t + 2 * (1 - math.exp(-30 * t)))) * math.exp(-9 * t),
              "SNARE": lambda t: (rng.random() * 2 - 1) * math.exp(-18 * t),
              "TONE": lambda t: 0.6 * math.sin(math.tau * 440 * t),
              "BASS": lambda t: 0.7 * math.sin(math.tau * 55 * t) * (1 - t)}
    for name, shape in shapes.items():
        path = output / f"{name.lower()}.wav"
        with wave.open(str(path), "wb") as wav:
            wav.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
            wav.writeframes(b"".join(struct.pack("<hh", *(2 * [round(30000 * shape(index / 48000))])) for index in range(24000)))
        files[f"/SMPLTREK/POOL/AUDIO/{name}.WAV"] = path
    return build_card(output / "samples.img", files, size_mb=32)


def run(job):
    seed, seconds, compiled, card, flash, output, stream, low_reads = job
    from stock import Stock
    events = script(seed, seconds, stream)
    result = dict(seed=seed, compiled=compiled, fault=None, applied=0)
    with Stock(card=card, flash_image=flash, reserved_low_writes=True, reserved_low_reads=low_reads, panel_stream=stream) as stock:
        cpu = stock.cpu
        if compiled:
            from blocks import compile_blocks
            cpu.blocks(True, heat=True)

        def advance(target):
            while cpu.cycles() < target:
                report = stock.run(min(target - cpu.cycles(), 100000000), 1000000)
                if report["error"]:
                    raise RuntimeError(report["error"])
                if compiled and cpu.cycles() // (3 * SECOND) != (cpu.cycles() - 100000000) // (3 * SECOND):
                    compile_blocks(cpu)

        try:
            advance(6 * SECOND)
            if flash:                                     # the "format recommended" notice on the generated card
                stock.key_input(30, True); advance(cpu.cycles() + SECOND // 12)
                stock.key_input(30, False); advance(cpu.cycles() + SECOND // 2)
            start = cpu.cycles()
            for when, kind, a, b in events:
                advance(start + when)
                if kind == "key": stock.key_input(a, bool(b))
                elif kind == "phase": stock.encoder_phase(a, b)
                elif kind == "level": stock.panel_level(a, b)
                else: stock.uart_receive(1, bytes([a]))
                result["applied"] += 1
            advance(start + (seconds + 1) * SECOND)
        except RuntimeError as error:
            result["fault"] = str(error)
            result["recent"] = [list(event) for event in events[max(0, result["applied"] - 12):result["applied"]]]
        frame, _ = cpu.oled_frame()
        raw, audio = cpu.audio_output()
        state = cpu.state()
        folder = output / f"seed-{seed}"; folder.mkdir(parents=True, exist_ok=True)
        (folder / ("blocks.png" if compiled else "interpreter.png")).write_bytes(png(frame))
        parts = (json.dumps(state, sort_keys=True).encode(), frame, raw, json.dumps(cpu.sd_state(), sort_keys=True).encode(),
                 cpu.sd_read() , json.dumps(cpu.mmio_trace(), sort_keys=True).encode())
        result.update(cycles=state["cycles"], pc=state["pc"], digest=hashlib.sha256(b"\0".join(parts)).hexdigest(),
                      underruns=audio["underruns"], sd_written=cpu.sd_state()["bytes_written"],
                      host=cpu.block_state()["block_cycles"] if compiled else 0)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--conditional", action="store_true", help="accept the logged reserved low-store assumption")
    parser.add_argument("--seeds", type=int, default=4, help="how many seeds, starting at --first")
    parser.add_argument("--first", type=int, default=1)
    parser.add_argument("--seconds", type=int, default=20, help="guest seconds of random input per seed")
    parser.add_argument("--samples", action="store_true", help="start with four WAV files in the card's sample pool")
    parser.add_argument("--project", metavar="GENRE", help="start from a generated project card (e.g. FUNK) and the factory-like flash")
    parser.add_argument("--project-seed", type=int, default=1)
    parser.add_argument("--panel-stream", action="store_true",
                        help="run the panel MCU's continuous reports; a pad hit then sets the level its channel reports")
    parser.add_argument("--reserved-low-reads", action="store_true",
                        help="also read reserved low memory as zero (the opt-in assumption of stock_ui.py), so that input "
                             "goes on past the strict faults on such reads")
    parser.add_argument("--jobs", type=int, help="machines run at once (default: half the CPUs, fewer if memory is short)")
    parser.add_argument("--output", type=Path, default=WORK / "stock-fuzz")
    args = parser.parse_args(argv)
    from blocks import memory_jobs, share_compilers
    if args.jobs is None:
        # A machine holds its whole audio and device trace: after 60 guest seconds 0.9 GB from a blank card
        # and up to 1.9 GB from a project card, measured.
        args.jobs = memory_jobs(max(1, (os.cpu_count() or 2) // 2), 1 + args.seconds / 60)
    share_compilers(args.jobs)
    if not args.conditional:
        parser.error("--conditional is required: this run discards reserved low stores")
    args.output.mkdir(parents=True, exist_ok=True)
    if args.project and args.samples:
        parser.error("--project and --samples are different starting cards: choose one")
    flash = None
    if args.project:
        from project_card import project_card
        card, flash, description = project_card(args.output / "project.img", args.project, args.project_seed)
        print(f'Project: {description["clips"]} clips at {description["bpm"]} BPM on {description["kit"]}')
    else:
        card = sample_card(args.output) if args.samples else build_card(args.output / "blank.img", size_mb=32)
    jobs = [(seed, args.seconds, compiled, card, flash, args.output, args.panel_stream, args.reserved_low_reads) for seed in range(args.first, args.first + args.seeds) for compiled in (False, True)]
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        rows = list(pool.map(run, jobs))
    (args.output / "result.json").write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n")
    failed = faults = 0
    for plain, compiled in zip(rows[0::2], rows[1::2]):
        same = plain["digest"] == compiled["digest"] and plain["fault"] == compiled["fault"]
        failed += not same; faults += bool(plain["fault"])
        print(f'{"ok   " if same else "FAIL "} seed {plain["seed"]}: {plain["applied"]} inputs, {plain["sd_written"]} card bytes written, '
              f'{compiled["host"] * 100 // max(1, compiled["cycles"])}% of cycles in host code'
              + (f'; fault: {plain["fault"]}' if plain["fault"] else "")
              + ("" if same else f'; blocks: cycle {compiled["cycles"]}, fault {compiled["fault"]}'))
        if plain["fault"]:
            print("        last inputs (cycle after start, kind, a, b):", " ".join(f"{when}:{kind}:{a}:{b}" for when, kind, a, b in plain["recent"]))
    for fault in sorted({row["fault"].split(" (PC")[0] + " (PC" + row["fault"].split(" (PC")[1].split(",")[0] + ")"
                         for row in rows if row["fault"] and " (PC" in row["fault"]}):
        print("  fault:", fault)
    print(f'{"FAIL" if failed else "PASS"}: {len(rows) // 2 - failed} of {len(rows) // 2} seeds agree between interpreter and blocks; '
          f'{faults} ended in a guest fault; details in {args.output / "result.json"}')
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
