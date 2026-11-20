#!/usr/bin/env python3
"""Collect and validate GCC PGO data from original guest execution, then optionally activate it."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True

from build import HERE, WORK, digest
from core_build import activate_profile, collection_core, finalize_profile, instrument_core, selected_core
from performance import pinned_cpu


def collect(bundle, workload, cpu):
    library, manifest = collection_core(bundle)
    with selected_core(library, manifest):
        if workload == "stock-audio":
            spec = importlib.util.spec_from_file_location("stock_audio_training", HERE / "tests/stock_audio.py")
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            report = module.probe(bundle / "training", cpu=cpu)
            result = dict(kind="conditional stock WAV preview", passed=report["passed"],
                          checks=report["checks"], reserved_bus_hypotheses=True)
            report_path = bundle / "training/result.json"
        else:
            from core_demo import demo
            with pinned_cpu(cpu):
                report, report_path = demo(bundle / "training")
            result = dict(kind="source-built RAM copy, replacement and integer loop", passed=True,
                          reserved_bus_hypotheses=False)
    result.update(report=str(report_path), report_sha256=digest(report_path.read_bytes()))
    (bundle / "training.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="new bundle under work/emulator; existing paths are rejected")
    parser.add_argument("--workload", choices=("synthetic", "stock-audio"), default="synthetic")
    parser.add_argument("--conditional", action="store_true", help="select the existing reserved-bus hypotheses for stock audio")
    parser.add_argument("--cpu", type=int, help="pin the collecting emulation thread to an allowed CPU")
    parser.add_argument("--activate", action="store_true", help="use this profile automatically while its source/compiler hashes match")
    parser.add_argument("--collect", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.workload == "stock-audio" and not args.conditional:
        parser.error("stock audio collection requires explicit --conditional")
    output = (args.collect or args.output or WORK / "pgo" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")).resolve()
    if not output.is_relative_to(WORK.resolve()):
        parser.error("generated PGO artifacts must remain under work/emulator/")
    try:
        if args.collect:
            collect(output, args.workload, args.cpu)
            return 0
        output.mkdir(parents=True, exist_ok=False)
        instrument_core(output)
        command = [sys.executable, "-B", str(HERE / "tune_core.py"), "--collect", str(output),
                   "--workload", args.workload]
        if args.conditional: command.append("--conditional")
        if args.cpu is not None: command += ["--cpu", str(args.cpu)]
        environment = os.environ.copy()
        for name in ("GCOV_PREFIX", "GCOV_PREFIX_STRIP", "GCOV_ERROR_FILE"):
            environment.pop(name, None)
        # The child must exit normally before GCC flushes its .gcda files.
        subprocess.run(command, check=True, env=environment)
        training = json.loads((output / "training.json").read_text())
        library, manifest = finalize_profile(output, training)
        # Re-execute real source-built bytes through the optimized core as a first check.
        from core_demo import demo
        with selected_core(library, manifest):
            demo(output / "verification", slice_cycles=1)
        if args.activate: activate_profile(output)
        print(f"PGO core ready: {library}")
        print(f"Profile: {output / 'profile.json'}; automatic selection: {args.activate}")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"core tuning: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
