#!/usr/bin/env python3
"""Optional local-corpus integration: conditional stock startup and real GPIO-driven UI.

Requires explicit --conditional: six reserved low CPU stores are discarded and logged, which is not a
verified silicon response. The two reserved USB status reads return 0, as measured on the unit.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build import WORK, digest
from display import png
from stock import Stock
from usb_probe import IMAGE_SHA256

HELD, CONTROLLER, MODAL, METRONOME = 0xc1501df0, 0xc16f367c, 0xc16f3680, 0xc14facb0


def probe(output, slice_cycles=1000000):
    output.mkdir(parents=True, exist_ok=True)
    observations, checks = [], {}
    with Stock(reserved_low_writes=True) as stock:
        if stock.input["sha256"] != IMAGE_SHA256:
            raise ValueError("boot probe addresses require original SmplTrek 3.2.174")
        report = None

        def word(address, size=4):
            return int.from_bytes(stock.cpu.read(address, size), "little")

        def advance(cycles):
            nonlocal report
            report = stock.run(cycles, slice_cycles)
            if report["error"]:
                raise RuntimeError(report["error"])

        def capture(label):
            frame, oled = stock.cpu.oled_frame()
            raw, audio = stock.cpu.audio_output()
            (output / f"{label}.bin").write_bytes(frame)
            (output / f"{label}.png").write_bytes(png(frame))
            row = dict(label=label, cycles=stock.cpu.state()["cycles"],
                       held=word(HELD, 8), controller=word(CONTROLLER), modal=word(MODAL),
                       metronome=word(METRONOME), frame_sha256=digest(frame),
                       complete_frames=oled["complete_frames"], audio=audio)
            observations.append(row)
            if audio["underruns"] or audio["overruns"]:
                raise RuntimeError("stock audio continuity failed during UI execution")
            if audio["last_capture_cycle"] - audio["first_capture_cycle"] != (audio["captured_words"] - 1) * 3875:
                raise RuntimeError("stock audio capture has a clock discontinuity")
            print(f'{label}: cycle {row["cycles"]}, controller {row["controller"]:#010x}', flush=True)
            return row

        def key(index, label):
            stock.key_input(index, True)
            advance(40000000)
            down = capture(label + "-down")
            stock.key_input(index, False)
            advance(40000000)
            up = capture(label + "-up")
            checks[label + "_scanned"] = down["held"] & (1 << index) != 0 and up["held"] & (1 << index) == 0
            return up

        def turn(label):
            for phase in (2, 0, 1, 3):
                stock.encoder_phase(4, phase)
                advance(10000000)
            return capture(label)

        validation_error = None
        try:
            advance(1500000000)
            home = capture("home")
            required = {"auto_init_return_site", "task_handler_entry", "audio_render_main",
                        "usb_start_return", "codec_unmute_return", "startup_return_site"}
            checks["startup_returned"] = required <= {row["name"] for row in report["checkpoints"]}
            checks["home_active"] = home["controller"] == 0xc15037f0 and home["modal"] == 0 and home["held"] == 0
            checks["stock_home_frame"] = home["frame_sha256"] == "4ac7d90cd81d4a25caf37cb16c1300ec62a1fba79222d2489e75338095e0d4bc"
            checks["codec_unmuted"] = all(report["codec"]["registers"]["0"][str(reg)] == 0 for reg in (43, 44))
            checks["usb_disconnected_attached"] = report["usb"]["soft_connect"] == 1 and report["usb"]["interrupts"] == 0
            # PLAY uses GP3[9], which stock leaves at its reset pin mux. Check the real scanner.
            key(22, "play")
            key(29, "stop")
            stock.key_input(19, True)
            advance(20000000)
            menu = key(27, "system")
            stock.key_input(19, False)
            advance(20000000)
            checks["system_menu_opened"] = menu["controller"] != home["controller"] and menu["frame_sha256"] != home["frame_sha256"]
            selected = turn("select-metronome")
            checks["value_encoder_navigated"] = selected["frame_sha256"] != menu["frame_sha256"]
            key(23, "metronome-page")
            key(23, "metronome-edit")
            changed = turn("metronome-on")
            checks["guest_changed_setting"] = home["metronome"] == 0 and changed["metronome"] == 1
            key(23, "metronome-confirm")
            returned = key(27, "home-return")
            checks["home_returned"] = returned["controller"] == home["controller"] and returned["modal"] == 0 and returned["held"] == 0
            checks["frames_continue"] = returned["complete_frames"] > home["complete_frames"]
            # Explicit external input fixtures, not an invented automatic MCU reply/version.
            # One completed 8N1 byte per 8000 DSP cycles matches stock's UART divisor 25.
            def panel_packet(data):
                for byte in data:
                    stock.uart_receive(1, bytes([byte]))
                    advance(8000)
                advance(20000000)
            panel_packet(bytes([0xa1, 1, 2, 3, 4, 5, 6]))
            checks["original_panel_info_parser"] = stock.cpu.read(0xc15019d0 + 70, 6) == bytes([1, 2, 3, 4, 5, 6])
            panel_packet(bytes([0xb3, 0, 8]))
            checks["original_panel_pressure_parser"] = word(0xc15019d0 + 42, 2) == 1024
            panel_packet(bytes([0xb3, 0, 0]))
            checks["original_panel_release_parser"] = word(0xc15019d0 + 42, 2) == 0
            capture("panel-input-fixture")
            checks["original_low_stores_only"] = report["reserved_low"]["count"] == 6
            checks["original_reserved_reads_only"] = [(r["pc"], r["address"], r["assumed_value"]) for r in report["usb"]["reserved_status"]["reads"]] == [
                (0xc15e2034, 0x01e0080c, 0), (0xc15e2060, 0x01e0084c, 0)]
            checks["no_guest_hooks"] = report["guest_function_hooks"] == []
            checks["conditional_execution_reported"] = report["conditional_execution"]
        except (ValueError, RuntimeError) as error:
            validation_error = str(error)
        finally:
            if report is None:
                raise RuntimeError("boot probe failed before a stock execution report was available")
            report["boot_validation"] = dict(kind="conditional stock integration", checks=checks,
                                              passed=validation_error is None and bool(checks) and all(checks.values()),
                                              error=validation_error, observations=observations,
                                              hardware_reserved_bus_verified=False,
                                              live_host_audio_verified=False)
            raw, audio = stock.cpu.audio_output()
            (output / "audio.pcm32").write_bytes(raw)
            report["audio"]["artifact"] = str(output / "audio.pcm32")
            (output / "result.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conditional", action="store_true", required=True,
                        help="explicitly select the recorded reserved low-store assumption; that hardware behavior remains unverified")
    parser.add_argument("--output", type=Path, default=WORK / "stock-boot")
    parser.add_argument("--slice-cycles", type=int, default=1000000)
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(WORK.resolve()):
        parser.error("generated boot artifacts must remain under work/emulator/")
    report = probe(args.output, args.slice_cycles)
    if not report["boot_validation"]["passed"]:
        raise RuntimeError(f'conditional boot check failed: {report["boot_validation"]}')
    print(f"Conditional stock boot/UI check passed; silicon reserved-bus response and live audio remain unverified. Report: {args.output / 'result.json'}")


if __name__ == "__main__":
    main()
