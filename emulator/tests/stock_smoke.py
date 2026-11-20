#!/usr/bin/env python3
"""Optional local-corpus check: real stock runtime, task entry and periodic interrupts, without hooks."""
import json
import argparse
import struct
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build import WORK, digest
from media import build_card
from stock import Stock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--first-frame", action="store_true", help="also run through power-on and the first complete display transfer")
    modes.add_argument("--storage", action="store_true", help="run through settings reads from both SPI NOR chips, stopping before I2C0")
    modes.add_argument("--codec", action="store_true", help="verify all 40 stock codec writes through the real I2C ISR, stopping before McASP0")
    modes.add_argument("--audio", action="store_true", help="verify clocked McASP/EDMA and the real stock audio-render task on digital silence")
    modes.add_argument("--audio-input", action="store_true", help="verify distinct nonzero ADC slots through RX DMA and the stock float input planes")
    modes.add_argument("--sd-card", action="store_true", help="verify stock FAT setup through an inserted private SDSC and EDMA, stopping before the startup wait")
    modes.add_argument("--startup-delay", action="store_true", help="run through stock's three-second startup wait while audio remains active")
    modes.add_argument("--usb-reset", action="store_true", help="explicit low-write policy: verify USB0 reset/PHY, stopping before legacy reserved USB reads")
    args = parser.parse_args()
    input_file = None
    if args.audio_input:
        input_file = WORK / "stock/adc-fixture.pcm32"
        input_file.parent.mkdir(parents=True, exist_ok=True)
        input_file.write_bytes(struct.pack("<2I", 0x10000000, 0xe0000000))  # +0.125 / -0.25
    card = build_card(WORK / "stock/sd-input.img") if args.sd_card else None
    with Stock(audio_input=input_file, loop_audio_input=args.audio_input, card=card,
               reserved_low_writes=args.usb_reset) as stock:
        initial_rx_words = None
        if args.audio_input:
            initial = stock.run(250_000_000, until_checkpoint="audio_start_transfers")
            if initial["error"] or initial["stop_reason"] != "checkpoint":
                raise RuntimeError("stock did not reach audio startup")
            initial_rx_words = struct.unpack("<I", stock.cpu.read(0x01c04008, 4))[0] >> 16
            if initial_rx_words != 255:
                raise RuntimeError("stock initial RX descriptor no longer has the expected short 255-word count")
        full_start = args.first_frame or args.storage or args.codec or args.audio or args.audio_input or args.sd_card or args.startup_delay or args.usb_reset
        budget = 1500000000 if args.startup_delay or args.usb_reset else 250_000_000 if full_start else 20_000_000
        report = stock.run(budget - stock.cpu.state()["cycles"],
                           until_frame=args.first_frame,
                           until_checkpoint="usb_interrupt_status_control" if args.usb_reset else "startup_minimum_delay" if args.sd_card else "startup_delay_done" if args.startup_delay else "mcasp0_first_access" if args.codec else "i2c0_first_access" if args.storage else None)
        if full_start:
            frame, oled = stock.cpu.oled_frame()
            if not oled["complete_frames"] or not any(frame) or not oled["on"]:
                raise RuntimeError("stock did not send a nonempty, complete display frame")
        if args.storage:
            if report["stop_reason"] != "checkpoint":
                raise RuntimeError("stock did not reach I2C0 after storage initialization")
            if [chip["bytes_read"] for chip in report["flash"]["chips"]] != [384, 8192]:
                raise RuntimeError("stock did not read the expected parameter and settings blocks through SPI NOR")
            if stock.cpu.read(0xc14c0400, 4096) != b"\xff" * 4096:
                raise RuntimeError("stock settings buffer does not match erased flash backing")
        if args.codec:
            codec = report["codec"]
            if report["stop_reason"] != "checkpoint" or codec["register_writes"] != 40 or codec["software_resets"] != 1:
                raise RuntimeError("stock did not complete codec initialization before McASP0")
            if (codec["starts"], codec["stops"], codec["bytes_sent"], codec["nacks"]) != (40, 40, 80, 0):
                raise RuntimeError("stock codec writes did not traverse complete, acknowledged I2C transactions")
            # Independent expectations from the AIC3106 register tables and documented stock setup.
            expected = {3: 0xa2, 4: 0x20, 7: 0x0a, 8: 0xd0, 9: 0x37, 12: 0x50,
                        19: 0x84, 22: 0x84, 37: 0xc0, 41: 0x50, 42: 0x9c, 86: 0x0a, 93: 0x0a, 107: 0xc0}
            if any(codec["registers"]["0"][str(reg)] != value for reg, value in expected.items()):
                raise RuntimeError("stock codec configuration did not reach the expected register state")
            if [codec["registers"]["1"][str(reg)] for reg in range(65, 77)] != [0x7f, 0xd5, 0x80, 0x2b, 0x7f, 0xaa] * 2:
                raise RuntimeError("stock ADC high-pass coefficients were not transferred")
        if args.audio or args.audio_input or args.sd_card or args.startup_delay or args.usb_reset:
            raw, audio = stock.cpu.audio_output()
            if audio["transmitted_words"] < 1024 or audio["received_words"] != audio["transmitted_words"]:
                raise RuntimeError("stock audio ring did not exchange at least four 256-word blocks")
            if audio["underruns"] or audio["overruns"] or (not args.audio_input and any(raw)):
                raise RuntimeError("stock McASP profile has audio errors or unexpected nonzero output")
            if audio["last_capture_cycle"] - audio["first_capture_cycle"] != (audio["captured_words"] - 1) * 3875:
                raise RuntimeError("stock sample capture has a clock discontinuity")
        if args.audio_input:
            source = report["audio"]["input"]
            if source["words_from_source"] != audio["received_words"] or source["zero_padding_words"] or source["nonzero_words_received"] != audio["received_words"]:
                raise RuntimeError("stock RX did not consume the complete nonzero digital source")
            # The guest's short first descriptor changes pair phase before the recurring 256-word links.
            expected = struct.pack("<2I", 0xe0000000, 0x10000000) * 128
            if any(stock.cpu.read(base, 1024) != expected for base in (0x11f00800, 0x11f00c00)):
                raise RuntimeError("stock ping/pong RX buffers do not preserve the source stream after initial link phase")
            plane0 = struct.unpack("<128f", stock.cpu.read(0xc16def80, 512))
            plane1 = struct.unpack("<128f", stock.cpu.read(0xc16df180, 512))
            if any(not (-0.26 < left < -0.24 and 0.12 < right < 0.13 and left == -2 * right)
                   for left, right in zip(plane0, plane1)):
                raise RuntimeError("stock input processing lost channel sign, level or ratio")
            report["audio"]["validation"] = dict(initial_rx_descriptor_words=initial_rx_words,
                                                 settled_rx_pair=[0xe0000000, 0x10000000],
                                                 float_plane_first_samples=[plane0[0], plane1[0]],
                                                 physical_channel_routing_verified=False)
        if args.sd_card:
            sd = report["sd"]
            if report["stop_reason"] != "checkpoint" or sd["state"] != 4 or sd["bus_width"] != 4 or sd["bytes_read"] < 512 or sd["bytes_written"] < 512:
                raise RuntimeError("stock did not complete card filesystem setup")
            data = stock.cpu.sd_read()
            # Independent FAT12/16 directory decoding: the stock guest must create these directories.
            sector, reserved, entries, fat_size = (struct.unpack_from("<H", data, off)[0] for off in (11, 14, 17, 22))
            root = (reserved + data[16] * fat_size) * sector
            data_start = root + ((entries * 32 + sector - 1) // sector) * sector
            def directory(begin, size):
                return {data[off:off + 8].decode("ascii").rstrip(): off for off in range(begin, begin + size, 32)
                        if data[off] not in (0, 229) and data[off + 11] & 16 and data[off + 11] != 15}
            roots = directory(root, entries * 32)
            if "SMPLTREK" not in roots:
                raise RuntimeError("stock did not create its SMPLTREK directory")
            cluster = struct.unpack_from("<H", data, roots["SMPLTREK"] + 26)[0]
            children = directory(data_start + (cluster - 2) * data[13] * sector, data[13] * sector)
            if not {"PROJECT", "POOL"} <= children.keys():
                raise RuntimeError("stock did not create its PROJECT/POOL directories")
            if digest(card.read_bytes()) != sd["input"]["sha256"]:
                raise RuntimeError("stock modified its input image instead of private backing")
            artifact = WORK / "stock/sd-private.img"; artifact.write_bytes(data)
            sd["artifact"] = {"path": str(artifact), "sha256": digest(data)}
            sd["validation"] = {"root_directories": sorted(roots), "smpltrek_directories": sorted(children)}
        if args.startup_delay:
            if report["stop_reason"] != "checkpoint" or report["state"]["cycles"] < 3 * 372000000:
                raise RuntimeError("stock did not finish its minimum startup delay")
        if args.usb_reset:
            expected = [(0xc162a4f0, 8, 0xd7), (0xc162a4f4, 9, 0x2f),
                        (0xc162a50c, 10, 4), (0xc162a514, 11, 0),
                        (0xc162a522, 7, 0xc0), (0xc162a52c, 8, 1)]
            rows = report["reserved_low"]["writes"]
            if [(row["pc"], row["address"], row["value"]) for row in rows] != expected or any(row["size"] != 1 for row in rows):
                raise RuntimeError("stock did not execute the expected six original low stores")
            if report["stop_reason"] != "checkpoint" or report["usb"]["soft_resets"] != 1 or not report["usb"]["phy_ready"]:
                raise RuntimeError("stock did not complete USB0 reset and PHY clock-good polling")
            if report["usb"]["soft_connect"] or report["usb"]["interrupts"]:
                raise RuntimeError("disconnected USB profile unexpectedly attached or interrupted")
            report["usb"]["validation"] = dict(original_low_stores=len(rows),
                                                 stop_before_reserved_legacy_status_reads=True,
                                                 full_usb_init_complete=False)
    output = WORK / "stock/smoke.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if report["error"]:
        raise RuntimeError(report["error"])
    reached = {row["name"] for row in report["checkpoints"]}
    required = {"system_entry", "auto_init_return_site", "task_handler_entry"}
    if args.audio or args.audio_input or args.sd_card or args.startup_delay or args.usb_reset:
        required |= {"audio_start_transfers", "audio_render_main"}
    if not required <= reached:
        raise RuntimeError(f"missing stock checkpoints: {sorted(required - reached)}")
    if report["state"]["interrupt_count"] < 2:
        raise RuntimeError("periodic interrupts did not run")
    if not full_start:
        scans = [row for row in report["mmio_trace"] if row["address"] == 0x01e26048 and not row["write"]]
        if not scans:
            raise RuntimeError("stock key scanner did not read GPIO")
    print(f'Stock smoke passed: task entry, {report["state"]["interrupt_count"]} interrupts'
          f'{", guarded low stores and disconnected USB reset/PHY" if args.usb_reset else ", stock SD/FAT directories through EDMA" if args.sd_card else ", startup delay and sustained audio" if args.startup_delay else ", nonzero ADC/RX/float input path" if args.audio_input else ", clocked audio DMA/render task" if args.audio else ", 40 codec writes through I2C ISR" if args.codec else ", NOR parameter/settings reads" if args.storage else ", first frame" if args.first_frame else ", key scans"}; full boot still incomplete')
    print(f"Report: {output}")


if __name__ == "__main__":
    main()
