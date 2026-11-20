#!/usr/bin/env python3
"""Conditional stock create/save/cold-load regression through original UI and FAT drivers."""
import argparse
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build import WORK, digest
from fat_image import FatImage
from media import build_card
from stock import Stock
from stock_session import StockSession, CONTROLLER, MODAL, TEMPO, HOME
from usb_probe import IMAGE_SHA256

CONFIG = "/SmplTrek/Project/Project002/Config"


def boot(card, output, slice_cycles):
    stock = Stock(card=card, reserved_low_writes=True)
    if stock.input["sha256"] != IMAGE_SHA256:
        stock.close()
        raise ValueError("project probe addresses require original SmplTrek 3.2.174")
    session = StockSession(stock, output, slice_cycles)
    try:
        session.advance(1500000000)
        if session.word(MODAL):
            session.key(30, "dismiss-card-warning")
        session.wait(lambda: session.word(MODAL) == 0)
        session.capture("home")
    except Exception:
        stock.close()
        raise
    return stock, session


def probe(output, slice_cycles=1000000):
    output.mkdir(parents=True, exist_ok=True)
    initial = build_card(output / "input.img")
    initial_hash = digest(initial.read_bytes())
    checks, reports = {}, []
    stock, ui = boot(initial, output / "create", slice_cycles)
    with stock:
        ui.key(20, "project-menu")
        ui.key(23, "project-select")
        ui.turn(1, label="select-slot-two")
        ui.key(23, "new-project-confirm")
        ui.key(24, "save-no")
        ui.key(23, "create-project")
        ui.wait(lambda: ui.word(CONTROLLER) == HOME and ui.word(MODAL) == 0)
        ui.capture("created")
        # Right selection opens TEMPO; encoder A adjusts the project tempo (manual p.21).
        before = ui.word(TEMPO)
        ui.key(9, "tempo-menu")
        ui.turn(1, encoder=0, label="tempo-changed")
        tempo = ui.word(TEMPO)
        checks["tempo_changed_by_guest"] = tempo != before and 300 <= tempo <= 3000
        ui.key(27, "home-changed")
        ui.key(20, "project-save-menu")
        ui.turn(1, label="select-save")
        ui.key(23, "save-project-confirm")
        ui.key(24, "save-yes")
        ui.key(23, "save-project")
        ui.wait(lambda: ui.word(MODAL) == 0)
        ui.capture("saved")
        private = stock.cpu.sd_read()
        fat = FatImage(private)
        config = fat.read(CONFIG)
        listing = fat.read("/SmplTrek/Project/Project.lst")
        checks["project_config_written"] = len(config) == 5924 and config[:4] == b"STPJ"
        checks["guest_saved_changed_tempo"] = struct.unpack_from("<I", config, 36)[0] == tempo
        checks["project_two_selected_in_list"] = b">Project002\n" in listing
        checks["input_image_unchanged"] = digest(initial.read_bytes()) == initial_hash
        checks["media_writes_occurred"] = ui.report["sd"]["bytes_written"] > 30208
        exported = output / "private.img"; exported.write_bytes(private)
        reports.append(ui.report)
    saved_hash = digest(exported.read_bytes())
    stock, ui = boot(exported, output / "reload", slice_cycles)
    with stock:
        checks["cold_boot_loaded_changed_tempo"] = ui.word(TEMPO) == tempo
        checks["cold_boot_kept_config_bytes"] = FatImage(stock.cpu.sd_read()).read(CONFIG) == config
        checks["exported_image_unchanged"] = digest(exported.read_bytes()) == saved_hash
        checks["cold_boot_read_media"] = ui.report["sd"]["bytes_read"] >= len(config)
        ui.capture("reloaded")
        reports.append(ui.report)
    checks["no_guest_hooks"] = all(r["guest_function_hooks"] == [] for r in reports)
    checks["no_audio_errors"] = all(not r["audio"]["overruns"] and not r["audio"]["underruns"] for r in reports)
    checks["only_known_reserved_accesses"] = all(r["reserved_low"]["count"] == 6 and r["usb"]["reserved_status"]["count"] == 2 for r in reports)
    report = dict(kind="conditional stock project persistence", checks=checks, passed=all(checks.values()),
                  tempo_x10=tempo, config_size=len(config), config_sha256=digest(config),
                  input_sha256=initial_hash, exported_sha256=saved_hash,
                  files=[vars(entry) for entry in fat.entries.values()], boots=reports,
                  limitations=["reserved-bus hypotheses remain explicit and unverified",
                               "synthetic FAT12 SDSC; physical media timing is unverified",
                               "digital audio continuity only; live audio remains incomplete"])
    (output / "result.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conditional", action="store_true", required=True)
    parser.add_argument("--output", type=Path, default=WORK / "stock-project")
    parser.add_argument("--slice-cycles", type=int, default=1000000)
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(WORK.resolve()):
        parser.error("generated artifacts must remain under work/emulator/")
    report = probe(args.output, args.slice_cycles)
    if not report["passed"]:
        raise RuntimeError(f'project persistence failed: {report["checks"]}')
    print(f"Stock project create/save/cold-load passed. Report: {args.output / 'result.json'}")


if __name__ == "__main__":
    main()
