#!/usr/bin/env python3
"""Stock WAV preview twice, with and without fast-forward: every stage must be identical.

The reference run executes every guest cycle. Both runs boot the original image, navigate the
original UI to the sample-pool preview and play it. CPU state, digital audio, display, SD
activity and the recent MMIO trace are compared at each stage and after each playback window.
"""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build import WORK, digest
from media import build_card
from performance import pinned_cpu
from stock import Stock
from stock_session import StockSession, MODAL
import stock_audio
from usb_probe import IMAGE_SHA256


def execute(output, forward, windows):
    output.mkdir(parents=True, exist_ok=True)
    tone = output / "tone.wav"; stock_audio.fixture(tone)
    card = build_card(output / "input.img", {stock_audio.WAV_PATH: tone})
    rows = []
    with Stock(card=card, reserved_low_writes=True) as stock:
        if stock.input["sha256"] != IMAGE_SHA256:
            raise ValueError("this comparison requires original SmplTrek 3.2.174")
        cpu = stock.cpu
        cpu.fast_forward(forward)
        ui = StockSession(stock, output / "stages")

        def mark(label):
            state = cpu.state(); raw, audio = cpu.audio_output(); frame, oled = cpu.oled_frame()
            rows.append(dict(label=label, cycles=state["cycles"], packets=state["packets"], pc=state["pc"],
                             interrupts=state["interrupt_count"], state=digest(json.dumps(state, sort_keys=True).encode()),
                             audio=digest(raw), transmitted_words=audio["transmitted_words"],
                             underruns=audio["underruns"], overruns=audio["overruns"], oled=digest(frame),
                             oled_bytes=oled["bytes_received"], sd=digest(json.dumps(cpu.sd_state(), sort_keys=True).encode()),
                             mmio=digest(json.dumps(cpu.mmio_trace(), sort_keys=True).encode())))

        started = time.perf_counter()
        ui.advance(1500000000); mark("sequencer")
        if ui.word(MODAL):
            ui.key(30)
        ui.wait(lambda: ui.word(MODAL) == 0); mark("home")
        stock.key_input(19, True); ui.advance(20000000)
        ui.key(20); stock.key_input(19, False); ui.advance(20000000)
        ui.key(23); ui.turn(1); ui.key(23); ui.turn(1); ui.key(24); mark("preview-column")
        ui.key(23); mark("preview-started")
        startup_seconds = time.perf_counter() - started
        before, skipped = cpu.state(), cpu.fast_forward_state()
        started = time.perf_counter()
        for index in range(windows):
            for _ in range(50):
                stock.step(1000000)
            mark(f"playing-{index}")
        seconds = time.perf_counter() - started
        after, statistics = cpu.state(), cpu.fast_forward_state()
        cycles = after["cycles"] - before["cycles"]
        raw, audio = cpu.audio_output()
        tones = stock_audio.tones(raw, audio)
        return rows, dict(fast_forward=forward, startup_host_seconds=startup_seconds, playback_cycles=cycles,
                          playback_host_seconds=seconds, playback_realtime_ratio=cycles / 372000000 / seconds,
                          executed_cycle_fraction=1 - (statistics["skipped_cycles"] - skipped["skipped_cycles"]) / cycles,
                          exact_fixture_samples=all(row["max_error"] == 0 and row["peak"] > 0 for row in tones),
                          statistics=statistics, core=cpu.manifest)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--conditional", action="store_true", help="explicitly select the two reserved-bus hypotheses")
    parser.add_argument("--output", type=Path, default=WORK / "stock-forward")
    parser.add_argument("--windows", type=int, default=4, help="50-million-cycle playback windows to compare")
    parser.add_argument("--cpu", type=int, help="pin the emulation thread to an allowed CPU")
    args = parser.parse_args(argv)
    if not args.conditional:
        parser.error("this stock UI comparison requires explicit --conditional")
    try:
        with pinned_cpu(args.cpu) as affinity:
            forward, fast = execute(args.output / "forward", True, args.windows)
            reference, every = execute(args.output / "reference", False, args.windows)
        differences = [dict(label=a["label"], fields=[name for name in a if a[name] != b[name]])
                       for a, b in zip(forward, reference) if a != b]
        passed = len(forward) == len(reference) and not differences and fast["exact_fixture_samples"]
        report = dict(passed=passed, differences=differences, stages=forward, fast_forward=fast, every_cycle=every,
                      host_affinity=affinity, guest_function_hooks=[], reserved_bus_hypotheses=True)
        (args.output / "result.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        for name, row in (("fast-forward", fast), ("every cycle", every)):
            print(f'{name}: playback {row["playback_realtime_ratio"]:.3f}x real time, '
                  f'{100 * row["executed_cycle_fraction"]:.1f}% of cycles executed, start-up {row["startup_host_seconds"]:.1f} s')
        print(("PASS" if passed else "FAIL") + f': {len(forward)} stages compared; report: {args.output / "result.json"}')
        return 0 if passed else 1
    except (ValueError, RuntimeError, OSError) as error:
        print(f"stock fast-forward comparison: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
