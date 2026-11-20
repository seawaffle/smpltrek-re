#!/usr/bin/env python3
"""Run the emulator's checks side by side and report each one.

Every check is its own process with its own output folder, so they do not disturb each other; the
only shared things are caches that are built once, before the others start (the C++ core, the
preset cards and the project tools). What is run:

  unit       each tests/test_*.py file
  stock      every stock_*.py check, on the interpreter and with compiled blocks (`--conditional`)
  compiled   compiled_c.py, one process per compiler and optimisation level, and its interrupt sweep at three cl6x and four GCC levels
             (and once for GCC with a stack gap in place of -fno-schedule-insns2)
  reference  analysis: c6sim_diff.py per level and each test_*.py file

`--tier fast` runs the unit files, stock_boot and one compiled level per compiler, for use while
working on a change. The default, `full`, is what to run before a commit. `--only` and `--skip` take
substrings of step names (see `--list`).

Speeds that some checks print are lower here than when a check runs alone: they are printed, not
compared, so results are unaffected, but measure speed with the check on its own.

A step passes when its process exits 0. The local-corpus checks skip themselves when their inputs
(the stock updates under firmware/, a DSP compiler) are absent, exactly as when run by hand.

Usage (from the repository root):
  python3 -B emulator/tests/verify.py                 # everything, about as long as the longest step
  python3 -B emulator/tests/verify.py --tier fast
  python3 -B emulator/tests/verify.py --only stock_song compiled --jobs 4
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from build import ROOT, WORK

TESTS = HERE / "tests"
ANALYSIS = ROOT / "analysis"
PYTHON = [sys.executable, "-B"]
STOCK = ("stock_boot", "stock_forward", "stock_project", "stock_audio", "stock_song", "stock_song --blocks",
         "stock_multitrack", "stock_multitrack --blocks", "stock_inst", "stock_inst --blocks", "stock_pad",
         "stock_pad --blocks", "stock_survey", "stock_survey --blocks", "stock_fuzz", "stock_fuzz --samples")
TI_LEVELS = ("O0", "O2", "O3", "O3s", "O3sp", "O2s2")
GCC_LEVELS = ("O0", "O1", "O2", "O3", "Os")
FAST = ("stock:stock_boot", "compiled:ti-O2", "compiled:gcc-O2")   # besides every unit file


def steps(output, inner_jobs):
    """[(name, command, working directory)] of every check."""
    rows = []
    for path in sorted(TESTS.glob("test_*.py")):
        rows.append((f"unit:{path.stem}", [*PYTHON, "-m", "unittest", path.stem], TESTS))
    for check in STOCK:
        script, *options = check.split()
        name = check.replace(" --", "-")
        command = [*PYTHON, str(TESTS / f"{script}.py"), "--conditional", *options, "--output", str(output / "out" / name)]
        if script in ("stock_survey", "stock_fuzz"):
            command += ["--jobs", str(inner_jobs)]          # these run several machines of their own
        rows.append((f"stock:{name}", command, ROOT))
    for level in TI_LEVELS:
        rows.append((f"compiled:ti-{level}", [*PYTHON, str(TESTS / "compiled_c.py"), "--levels", level, "--gcc-levels"], ROOT))
    for level in GCC_LEVELS:
        rows.append((f"compiled:gcc-{level}", [*PYTHON, str(TESTS / "compiled_c.py"), "--gcc-levels", level, "--levels"], ROOT))
    for level in ("O2", "O3", "O3s"):                        # one interrupt at each cycle of each call
        rows.append((f"compiled:interrupts-ti-{level}", [*PYTHON, str(TESTS / "compiled_c.py"), "--interrupts", "--levels", level, "--gcc-levels"], ROOT))
    for level in ("O1", "O2", "O3", "Os"):
        rows.append((f"compiled:interrupts-gcc-{level}", [*PYTHON, str(TESTS / "compiled_c.py"), "--interrupts", "--gcc-levels", level, "--levels"], ROOT))
    # GCC's default scheduling, with a handler that leaves 16 KiB below the interrupted stack pointer alone.
    rows.append(("compiled:interrupts-gcc-O2-gap", [*PYTHON, str(TESTS / "compiled_c.py"), "--interrupts", "--stack-gap", "16384", "--gcc-levels", "O2", "--levels"], ROOT))
    for level in TI_LEVELS:
        rows.append((f"reference:c6sim_diff-{level}", [*PYTHON, str(ANALYSIS / "c6sim_diff.py"), "--levels", level], ROOT))
    for path in sorted(ANALYSIS.glob("test_*.py")):
        rows.append((f"reference:{path.stem}", [*PYTHON, "-m", "unittest", "discover", "-s", str(ANALYSIS), "-p", path.name], ROOT))
    return rows


def prepare():
    """Build what the checks share, once, so that none of them starts on a half-made cache."""
    from cpu import CPU
    with CPU(WORK):
        pass
    try:
        from project_card import preset_files, tools
        preset_files(); preset_files(instruments=True); tools()
    except (ValueError, OSError, RuntimeError) as error:   # no stock update, node or npm: the checks that need them say so
        print(f"prepare: {str(error).splitlines()[0]}")


def run(step, logs):
    name, command, directory = step
    log = logs / (name.replace(":", "-") + ".log")
    started = time.monotonic()
    with log.open("w") as file:
        code = subprocess.run(command, cwd=directory, stdout=file, stderr=subprocess.STDOUT).returncode
    lines = log.read_text(errors="replace").strip().splitlines()
    return name, code, time.monotonic() - started, lines[-1][:150] if lines else "", log


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--tier", choices=("fast", "full"), default="full")
    parser.add_argument("--only", nargs="+", default=[], help="run steps whose name contains one of these")
    parser.add_argument("--skip", nargs="+", default=[], help="leave out steps whose name contains one of these")
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2), help="checks run at once")
    parser.add_argument("--list", action="store_true", help="print the step names and stop")
    parser.add_argument("--output", type=Path, default=WORK / "verify")
    args = parser.parse_args(argv)
    chosen = steps(args.output, max(1, args.jobs // 4))
    if args.tier == "fast":
        chosen = [step for step in chosen if step[0].startswith("unit:") or step[0] in FAST]
    if args.only:
        chosen = [step for step in chosen if any(part in step[0] for part in args.only)]
    chosen = [step for step in chosen if not any(part in step[0] for part in args.skip)]
    if args.list:
        print("\n".join(step[0] for step in chosen))
        return 0
    if not chosen:
        parser.error("no step matches")
    logs = args.output / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    # With an empty block cache about ten steps compile at once: a quarter of the CPUs each, not all of them.
    from blocks import share_compilers
    share_compilers(4)
    started = time.monotonic()
    prepare()
    # Longest first, so the short ones fill in around them.
    order = {"stock:stock_survey": 0, "stock:stock_fuzz": 1, "compiled:": 2, "stock:": 3, "reference:": 4, "unit:": 5}
    chosen.sort(key=lambda step: next(rank for prefix, rank in order.items() if step[0].startswith(prefix)))
    failed = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for name, code, seconds, last, log in pool.map(lambda step: run(step, logs), chosen):
            print(f'{"ok  " if code == 0 else "FAIL"} {name:34} {seconds:6.0f} s  {last}', flush=True)
            if code:
                failed.append((name, log))
    elapsed = time.monotonic() - started
    for name, log in failed:
        print(f"FAILED {name}: see {log}")
    print(f'{"FAIL" if failed else "PASS"}: {len(chosen) - len(failed)} of {len(chosen)} steps passed in {elapsed / 60:.1f} minutes; logs in {logs}')
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
