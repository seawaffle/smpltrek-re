"""Measure stock boot and warmed audio slices against the real-time target, without guest hooks."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from contextlib import contextmanager

from build import WORK, digest
from stock import Stock


@contextmanager
def pinned_cpu(cpu=None):
    """Bind only the calling thread, restoring its original affinity on exit."""
    available = sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None
    if cpu is not None:
        if type(cpu) is not int or cpu < 0 or available is None or cpu not in available:
            raise ValueError(f"CPU must be in the calling thread's allowed affinity: {available}")
        os.sched_setaffinity(0, {cpu})
    try:
        yield dict(requested_cpu=cpu, effective_cpus=[cpu] if cpu is not None else available,
                   original_cpus=available, scope="calling emulation thread; not host CPU isolation")
    finally:
        if cpu is not None:
            os.sched_setaffinity(0, available)


def measure(work=WORK, boot_cycles=250000000, sample_cycles=50000000, samples=3, eager_board=False,
            audio_input=None, loop_audio_input=False, cpu=None, guest_sample_period=0, fast_forward=True):
    if type(samples) is not int or not 1 <= samples <= 100:
        raise ValueError("samples must be 1..100")
    if type(guest_sample_period) is not int or not 0 <= guest_sample_period <= 1000000:
        raise ValueError("guest sample period must be 0..1000000")
    setup_start = time.perf_counter()
    with pinned_cpu(cpu) as affinity, Stock(work=work, audio_input=audio_input, loop_audio_input=loop_audio_input) as stock:
        stock.cpu.board_eager_polling(eager_board)
        stock.cpu.fast_forward(fast_forward)
        setup_seconds = time.perf_counter() - setup_start
        boot = stock.run(boot_cycles)
        if boot["error"]:
            raise RuntimeError(boot["error"])
        if stock.cpu.audio_output()[1]["transmitted_words"] < 1024:
            raise RuntimeError("stock has not exchanged enough audio to measure warmed execution")
        if guest_sample_period:
            stock.cpu.profile_guest(guest_sample_period)
        rows = []
        for index in range(samples):
            before = stock.cpu.state()
            skipped = stock.cpu.fast_forward_state()["skipped_cycles"]
            old_audio = stock.cpu.audio_output()[1]
            old_input = stock.cpu.audio_input_state()
            report = stock.run(sample_cycles)
            if report["error"]:
                raise RuntimeError(report["error"])
            elapsed = report["elapsed_seconds"]
            cycles = report["state"]["cycles"] - before["cycles"]
            audio = report["audio"]
            packets = report["state"]["packets"] - before["packets"]
            row = dict(sample=index, cycles=cycles, host_seconds=elapsed, guest_seconds=cycles / 372000000,
                       realtime_ratio=cycles / 372000000 / elapsed,
                       cycles_per_host_second=cycles / elapsed,
                       packets=packets, packets_per_cycle=packets / cycles,
                       skipped_cycles=stock.cpu.fast_forward_state()["skipped_cycles"] - skipped,
                       ns_per_packet=elapsed * 1e9 / packets if packets else None,
                       realtime_target_ns_per_packet=cycles / 372000000 * 1e9 / packets if packets else None,
                       interrupts_per_guest_second=(report["state"]["interrupt_count"] - before["interrupt_count"]) / (cycles / 372000000),
                       transmitted_words=audio["transmitted_words"] - old_audio["transmitted_words"],
                       received_words=audio["received_words"] - old_audio["received_words"],
                       nonzero_input_words=audio["input"]["nonzero_words_received"] - old_input["nonzero_words_received"],
                       zero_padding_input_words=audio["input"]["zero_padding_words"] - old_input["zero_padding_words"],
                       underruns=audio["underruns"] - old_audio["underruns"], overruns=audio["overruns"] - old_audio["overruns"])
            rows.append(row)
            cost = f'{row["ns_per_packet"]:.2f} ns/packet' if packets else "no issued packets"
            print(f'Sample {index}: {row["realtime_ratio"]:.4f}x real time, {cost}, {row["cycles_per_host_second"]:,.0f} cycles/s', flush=True)
        raw, audio = stock.cpu.audio_output()
        frame, oled = stock.cpu.oled_frame()
        seconds = sum(row["host_seconds"] for row in rows)
        guest = sum(row["guest_seconds"] for row in rows)
        packets = sum(row["packets"] for row in rows)
        guest_profile = None
        if guest_sample_period:
            stock.cpu.profile_guest(0)
            guest_profile = stock.cpu.guest_profile()
        return dict(target="stock real-time audio", setup_host_seconds=setup_seconds, eager_board=eager_board,
                    core=stock.cpu.manifest, firmware=stock.input, boot_host_seconds=boot["elapsed_seconds"],
                    boot_cycles=boot["state"]["cycles"], samples=rows,
                    realtime_ratio=guest / seconds, real_time_target_met=guest >= seconds, host_affinity=affinity,
                    ns_per_packet=seconds * 1e9 / packets if packets else None,
                    realtime_target_ns_per_packet=guest * 1e9 / packets if packets else None,
                    guest_profile=guest_profile, fast_forward=stock.cpu.fast_forward_state(),
                    state=stock.cpu.state(), audio={**audio, "sha256": digest(raw),
                                                   "input": {**stock.audio_input_profile, **stock.cpu.audio_input_state()}},
                    oled={**oled, "sha256": digest(frame)}, guest_function_hooks=[],
                    limitations=["startup and UI remain incomplete", "digital ADC boundary; no analog codec processing",
                                 "throughput is host/load dependent; no live playback or deadline guarantee"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--boot-cycles", type=int, default=250000000)
    parser.add_argument("--sample-cycles", type=int, default=50000000)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--eager-board", action="store_true", help="diagnostic reference: poll every controller each cycle")
    parser.add_argument("--audio-input", type=Path, help="raw 48 kHz little-endian 32-bit ADC slot pairs")
    parser.add_argument("--loop-audio-input", action="store_true")
    parser.add_argument("--cpu", type=int, help="pin the emulation thread to an allowed CPU, restoring affinity afterward")
    parser.add_argument("--no-fast-forward", action="store_true",
                        help="reference: execute every repeated idle period instead of skipping it")
    parser.add_argument("--guest-sample-period", type=int, default=0,
                        help="optional jittered guest packet sampling; 0 disables, 1009 is a useful starting point")
    args = parser.parse_args(argv)
    try:
        report = measure(args.work, args.boot_cycles, args.sample_cycles, args.samples, args.eager_board,
                         args.audio_input, args.loop_audio_input, args.cpu, args.guest_sample_period,
                         not args.no_fast_forward)
        path = args.output or args.work / "performance/result.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(f'Aggregate: {report["realtime_ratio"]:.4f}x real time; report: {path}')
        return 0
    except (ValueError, RuntimeError, OSError) as error:
        print(f"stock performance: {error}", file=sys.stderr); return 1


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
