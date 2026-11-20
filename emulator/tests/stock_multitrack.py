#!/usr/bin/env python3
"""Optional local-corpus check: the stock firmware builds, saves, reloads and plays a six-track project.

Everything is done through the emulated panel, on a card that holds only the factory drum kits
(project_card.py) and with the factory-like flash:
  1. Build. In a new project the track-type dialog makes tracks 1-6: DRUM (House kit, kit pattern),
     DRUM (Trap kit, kit pattern), INST (two step-recorded notes, no instrument), MIDI (two notes),
     LOOP and SHOT (both empty). PROJECT MENU > SAVE then writes it to the card.
  2. Play. A second machine starts from the saved card, loads the project and plays six guest seconds
     (the single scene stops by itself after four bars, eight seconds at 120 BPM).
  3. Known stop. On the same card plus one WAV in the pool, OK on that file name in SAMPLE POOL ends
     in the firmware's null-object read (PC 0xc16166a0, address 0xc), which the strict low-memory
     policy refuses. The check pins that stop; it is why LOOP and SHOT stay empty here.
  4. The same presses with the low-read option (a low read returns the held data of earlier loads on its
     data path, as measured in bench M2 and M3): the one low read returns 0 and the AUDIO LOADER opens on the file.

Checked directly: no fault in steps 1 and 2, the six track types are on the saved card's project,
the display moves while playing, the output is audible and continuous. Compared with
tests/fixtures/stock_multitrack.json: frames, the saved project file, the last 0.7 s of audio, card
traffic, the known stop and step 4's low read and frame. `--record` rewrites the fixture; `--blocks` runs all four steps with
compiled blocks against the interpreter's saved result. Playback speed is printed, not compared.

Requires explicit --conditional (the logged reserved low-store assumption).
"""
import argparse
import json
import math
from pathlib import Path
import struct
import sys
import time
import wave

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from build import WORK, digest
from display import png
from fat_image import FatImage
from media import build_card
from project_card import MS, preset_files
from stock import Stock

EXPECTED = Path(__file__).resolve().parent / "fixtures/stock_multitrack.json"
UP, RIGHT, FUNC, PROJECT, PLAY, OK, LEFT, DOWN, REC, CLR = 17, 18, 19, 20, 22, 23, 24, 25, 26, 30
STEP5, STEP9 = 36, 40
KIT, PATTERN = 2, 3                                    # encoders C and D in the KIT pop-up
TURN = (2, 0, 1, 3)                                    # quadrature phases of one detent clockwise
NOTES = (REC, OK, STEP5, UP, OK, REC)                  # record standby, a note on step 1, one a step higher on step 5
BUILD = (
    ("drum-1", (OK, RIGHT, RIGHT, RIGHT, OK, (PATTERN, 1), OK, CLR, CLR)),
    ("drum-2", (DOWN, OK, OK, (KIT, 3), (PATTERN, 2), OK, CLR, CLR)),
    ("inst", (DOWN, OK, LEFT, OK, OK, *NOTES, CLR)),
    ("midi", (DOWN, OK, RIGHT, RIGHT, OK, CLR, *NOTES, CLR)),
    ("loop", (DOWN, OK, RIGHT, OK, CLR)),
    ("shot", (DOWN, OK, RIGHT, OK, CLR)),
    ("saved", (PROJECT, DOWN, OK, LEFT, OK, 3000, CLR)),
)
POOL_OK = (OK, OK, 2, DOWN, OK, DOWN, OK)              # LOOP track, its editor, SAMPLE POOL, Pool, first file, OK
TYPES = ("DRUM", "DRUM", "INST", "MIDI", "LOOP", "SHOT")
PLAY_SECONDS = 6


class Session:
    """One machine driven by panel steps: a key number, (encoder, detents) or a wait in ms (>= 100)."""

    def __init__(self, output, name, card, flash, compiled, low_reads=False, panel_stream=False):
        self.output, self.name, self.compiled = output, name, compiled
        self.stock = Stock(card=card, flash_image=flash, reserved_low_writes=True, reserved_low_reads=low_reads,
                           panel_stream=panel_stream)
        self.row = dict(frames=[], fault=None)
        if compiled:
            self.stock.cpu.blocks(True, heat=True)

    def advance(self, milliseconds):
        report = self.stock.run(milliseconds * MS, 1000000)
        if report["error"]:
            raise RuntimeError(report["error"])

    def settle(self, milliseconds):
        self.advance(milliseconds)
        if self.compiled:
            from blocks import compile_blocks
            compile_blocks(self.stock.cpu)

    def step(self, action):
        if isinstance(action, tuple):
            for _ in range(action[1]):
                for phase in TURN:
                    self.stock.encoder_phase(action[0], phase); self.advance(2)
            self.advance(400)
        elif action >= 100:
            self.advance(action)
        else:
            self.stock.key_input(action, True); self.advance(80)
            self.stock.key_input(action, False); self.advance(500)

    def capture(self, label):
        frame, _ = self.stock.cpu.oled_frame()
        (self.output / f"{self.name}-{label}.png").write_bytes(png(frame))
        self.row["frames"].append(dict(label=label, sha256=digest(frame)))

    def finish(self):
        cpu = self.stock.cpu
        sd = cpu.sd_state()
        self.row.update(cycles=cpu.cycles(), sd=dict(bytes_read=sd["bytes_read"], bytes_written=sd["bytes_written"]))
        return self.row


def build(output, card, flash, compiled):
    session = Session(output, "build", card, flash, compiled)
    with session.stock as stock:
        try:
            session.settle(6000); session.step(CLR)    # the "format recommended" notice on a foreign card
            for label, actions in BUILD:
                for action in actions:
                    session.step(action)
                session.capture(label); session.settle(100)
        except RuntimeError as error:
            session.row["fault"] = str(error)
        row = session.finish()
        saved = stock.cpu.sd_read()
    return row, saved


def play(output, card, flash, compiled):
    session = Session(output, "play", card, flash, compiled)
    with session.stock as stock:
        seconds = None
        try:
            session.settle(6000); session.step(CLR); session.capture("loaded")
            session.step(PLAY); session.settle(100)
            started = time.perf_counter()
            for second in range(1, PLAY_SECONDS + 1):
                session.advance(1000); session.capture(f"playing-{second}s")
            seconds = time.perf_counter() - started
        except RuntimeError as error:
            session.row["fault"] = str(error)
        raw, audio = stock.cpu.audio_output()
        words = struct.unpack(f"<{len(raw) // 4}i", raw[:len(raw) // 4 * 4])
        row = session.finish()
        row.update(audio_sha256=digest(raw), underruns=audio["underruns"],
                   rms=round(math.sqrt(sum(word * word for word in words) / max(1, len(words))) / 2**31, 6))
        host = stock.cpu.block_state() if compiled else None
    return row, seconds, host


def known_stop(output, card, flash, compiled, low_reads=False):
    session = Session(output, "loader" if low_reads else "pool", card, flash, compiled, low_reads)
    with session.stock as stock:
        try:
            session.settle(6000); session.step(CLR)
            for action in POOL_OK:
                session.step(action)
            session.capture("after-ok")
        except RuntimeError as error:
            session.row["fault"] = str(error)
        if low_reads:
            session.row["low_reads"] = [[row["pc"], row["address"], row["size"], row["value"]] for row in stock.cpu.reserved_low_read_state()["reads"]]
        return session.finish()


def tone(path):
    with wave.open(str(path), "wb") as file:
        file.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
        file.writeframes(b"".join(struct.pack("<hh", value, value) for value in
                                  (round(12000 * math.sin(math.tau * 220 * index / 48000)) for index in range(24000))))
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--conditional", action="store_true", help="accept the logged reserved low-store assumption")
    parser.add_argument("--record", action="store_true", help="save this run as the expected result")
    parser.add_argument("--blocks", action="store_true", help="run with compiled blocks and compare with the interpreter's saved result")
    parser.add_argument("--output", type=Path, default=WORK / "stock-multitrack")
    args = parser.parse_args(argv)
    if not args.conditional:
        parser.error("--conditional is required: this run discards reserved low stores")
    if args.blocks and args.record:
        parser.error("the saved result comes from the interpreter: --record cannot be combined with --blocks")
    args.output.mkdir(parents=True, exist_ok=True)
    files, flash = preset_files()
    problems = []

    blank = build_card(args.output / "kits.img", files, size_mb=256, long_names=True)
    built, saved = build(args.output, blank, flash, args.blocks)
    saved_card = args.output / "saved.img"
    saved_card.write_bytes(saved)
    result = dict(build=built)
    if built["fault"]:
        problems.append(f'fault while building: {built["fault"]}')
    else:
        card = FatImage(saved)
        config = "/SmplTrek/Project/Project001/Config"
        if config.lower() not in card.entries:
            problems.append("the saved card has no project file")
        else:
            data = card.read(config)
            (args.output / "Config").write_bytes(data)
            built["config"] = dict(bytes=len(data), sha256=digest(data))
        played, seconds, host = play(args.output, saved_card, flash, args.blocks)
        result["play"] = played
        if played["fault"]:
            problems.append(f'fault while playing: {played["fault"]}')
        else:
            if len({frame["sha256"] for frame in played["frames"]}) < 4:
                problems.append("the display did not change while playing")
            if played["rms"] < 0.005:
                problems.append(f'output is silent (rms {played["rms"]})')
            if played["underruns"]:
                problems.append(f'{played["underruns"]} audio underruns')

    pool = dict(files)
    pool["/SmplTrek/Pool/Audio/TONE.WAV"] = tone(args.output / "tone.wav")
    pool_card = build_card(args.output / "pool.img", pool, size_mb=256, long_names=True)
    stop = known_stop(args.output, pool_card, flash, args.blocks)
    result["pool_ok"] = stop
    loader = known_stop(args.output, pool_card, flash, args.blocks, low_reads=True)
    result["pool_loader"] = loader
    if loader["fault"] or loader["low_reads"] != [[0xc16166a0, 0xc, 4, 0]]:
        problems.append(f'with the low-read option, OK on a pool file name gave fault {loader["fault"]} and low reads {loader.get("low_reads")}')
    if not stop["fault"] or "0x0000000c" not in stop["fault"] or "0xc16166a0" not in stop["fault"]:
        problems.append(f'OK on a pool file name no longer ends in the known null-object read (now: {stop["fault"]}); '
                        "review the low-memory policy notes and this check")

    (args.output / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    saved_result = json.loads(EXPECTED.read_text()) if EXPECTED.exists() else None
    if args.record and not problems:
        EXPECTED.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(f"Recorded in {EXPECTED}")
    elif not args.record:
        if saved_result is None:
            problems.append("no saved result; run with --record and review it")
        else:
            for name in sorted(set(result) | set(saved_result)):
                if result.get(name) != saved_result.get(name):
                    ours, theirs = result.get(name) or {}, saved_result.get(name) or {}
                    problems.append(f"{name} differs from the saved result in: " +
                                    ", ".join(key for key in sorted(set(ours) | set(theirs)) if ours.get(key) != theirs.get(key)))
    summary = "tracks " + "/".join(TYPES)
    if "play" in result and not result["play"]["fault"]:
        summary += f', rms {result["play"]["rms"]}, {result["play"]["sd"]["bytes_read"]} card bytes read, playback {PLAY_SECONDS / seconds:.2f}x real time'
        if host:
            summary += f', {host["block_cycles"] * 100 // max(1, result["play"]["cycles"])}% of cycles in host code'
    for problem in problems:
        print("FAIL:", problem)
    print(f'{"FAIL" if problems else "PASS"}: {summary}; frames in {args.output}')
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
