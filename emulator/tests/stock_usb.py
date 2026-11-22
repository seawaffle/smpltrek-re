#!/usr/bin/env python3
"""Optional local-corpus check: the USB0 device model and scripted host against the stock 3.2.174 firmware.

The stock image starts with the generated drum project of stock_song.py; a full-speed host is plugged in
once it has started, and the firmware is driven through its own menus (guest memory is read, never
written). Checked, against what static analysis found in the firmware (docs/04-hardware-access.md, "USB
device"; claims HW-12, HW-18):

  enumeration   the host's reset, the 8-byte and full device descriptor, SET_ADDRESS, the configuration
                descriptor and SET_CONFIGURATION all succeed: vendor 0x2fd7, product 0x0004, bcdUSB 1.10,
                and the 234-byte composite configuration byte for byte as analysis/usb_desc_map.py
                rebuilds it (audio control, two audio streaming interfaces on isochronous 0x01 and 0x82,
                MIDI streaming on bulk 0x03 and 0x83 at 64 bytes). The firmware then programs endpoint 3
                for 64-byte packets with FIFOs clear of endpoint 0's.
  control       an unsupported request is answered with STALL and the next request works; a second bus
                reset is followed by a second enumeration.
  bulk OUT      a USB MIDI note-on event (4 bytes) for track 1's channel on endpoint 0x03 plays the track;
                the same note on an unused channel is silent.
  bulk IN       with CLOCK OUT and COMMAND on, PLAY puts a 0x0F 0xFA 0x00 0x00 event on endpoint 0x83, then
                0x0F 0xF8 0x00 0x00 events 24 times per quarter note, and STOP 0xFC. (Stopped, the stock
                sends no clock over USB, where its DIN jack keeps sending it; recorded, not judged.)

Requires explicit --conditional (the logged reserved low-store assumption), node and npm.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from build import WORK
from cpu import CYCLES_PER_SECOND, UsbError
from project_card import MS, project_card
from stock import Stock

SELECT_RIGHT, FUNC, PLAY, OK, DOWN, HOME, STOP, CLR = 9, 19, 22, 23, 25, 27, 29, 30
TEMPO, SETTINGS = 0xc1500cf4, 0xc14fac58
TRACK_CHANNELS, MIDI_SETTINGS = SETTINGS + 0x8c, SETTINGS + 0xd8
BLOCK = 128 * CYCLES_PER_SECOND // 48000   # one audio block: 2.67 ms
CONFIGURATION_SHA256 = "fa71cef9d8f089a6b9613d590805fb966d76ea383d694afcc7c0c3372dc3b1e2"   # analysis/usb_desc_map.py build()
ENDPOINTS = [dict(address=0x01, interface=1, alternate=1, max_packet=196, type="isochronous"),
             dict(address=0x82, interface=2, alternate=1, max_packet=196, type="isochronous"),
             dict(address=0x03, interface=3, alternate=0, max_packet=64, type="bulk"),
             dict(address=0x83, interface=3, alternate=0, max_packet=64, type="bulk")]


def measure(output, genre, seed):
    card, flash, description = project_card(output / "card.img", genre, seed)
    row = dict(project=description, fault=None)
    with Stock(card=card, flash_image=flash, reserved_low_writes=True) as stock:
        cpu = stock.cpu

        def advance(milliseconds):
            for part in [100] * (milliseconds // 100) + [milliseconds % 100] * bool(milliseconds % 100):
                report = stock.run(part * MS, 1000000)
                if report["error"]:
                    raise RuntimeError(report["error"])

        def press(*keys):
            for key in keys:
                stock.key_input(key, True); advance(70)
            for key in reversed(keys):
                stock.key_input(key, False); advance(70)
            advance(450)

        def turn(encoder, detents):
            for _ in range(abs(detents)):
                for phase in ((2, 0, 1, 3) if detents > 0 else (1, 0, 2, 3)):
                    stock.encoder_phase(encoder, phase); advance(10)
            advance(300)

        def words(address, count=1):
            return list(struct.unpack(f"<{count}I", cpu.read(address, 4 * count)))

        def rms(milliseconds):
            seen = cpu.audio_tail(0)[2]
            advance(milliseconds)
            raw = cpu.audio_tail(seen)[0]
            samples = struct.unpack(f"<{len(raw) // 4}i", raw)
            return round(math.sqrt(sum(sample * sample for sample in samples) / max(1, len(samples))) / 2**31, 6)

        def enumerate_device():
            found = cpu.usb_enumerate()
            return dict(device=found["device"].hex(), configuration=found["configuration"].hex(), vendor=found["vendor"],
                        product=found["product"], max_packet0=found["max_packet0"], endpoints=found["endpoints"],
                        steps=[dict(step=step["step"], status=step["status"], naks=step["naks"],
                                    cycles=step["completed"] - step["submitted"]) for step in found["steps"]])

        def note(channel, key=36):
            sent = cpu.usb_out(0x03, bytes([0x09, 0x90 | channel, key, 110]))
            level = rms(300)
            cpu.usb_out(0x03, bytes([0x08, 0x80 | channel, key, 0]))
            advance(1500)   # let it ring out
            return dict(status=sent["status"], naks=sent["naks"], rms=level)

        def events(milliseconds):
            """USB MIDI events read from endpoint 0x83 over a stretch of guest time: [bytes, cycle]."""
            found, end = [], cpu.cycles() + milliseconds * MS
            while cpu.cycles() < end:
                packet = cpu.usb_in(0x83, 64, timeout_ms=max(1, (end - cpu.cycles()) // MS))
                if packet["status"] not in ("ok", "timeout"):
                    raise RuntimeError(f'endpoint 0x83 answered {packet["status"]}')
                found += [[packet["data"][at:at + 4].hex(), packet["completed"]] for at in range(0, len(packet["data"]), 4)]
            return found

        try:
            advance(6000); press(CLR)
            row["tempo_x10"] = words(TEMPO)[0]
            row["before_attach"] = {name: cpu.usb_state()[name] for name in ("port", "soft_connect", "phy_ready", "interrupt_mask")}
            cpu.usb_attach()
            row["enumeration"] = enumerate_device()
            advance(10)
            state = cpu.usb_state()
            row["after_enumeration"] = {name: state[name] for name in (
                "port", "address", "device_address", "configuration", "bus_resets", "stalls", "errors", "toggle_errors",
                "fifo_overflows", "fifo_underflows", "interrupt_mode", "sof")}
            row["endpoint_3"] = state["endpoints"][2]
            row["sof_interrupts"] = dict(sofs=state["sofs"], frame=state["frame"])

            bad = cpu.usb_control((0x80, 6, 0x0f00, 0), 8)   # a descriptor type the device does not have
            status = cpu.usb_control((0x80, 0, 0, 0), 2)     # GET_STATUS still works after the STALL
            row["control"] = dict(unsupported=bad["status"], get_status=[status["status"], status["data"].hex()])

            channels = words(TRACK_CHANNELS, 8)
            unused = next(channel for channel in range(15) if channel not in channels)   # 15 is the AUTO channel
            row["bulk_out"] = dict(track_channels=channels, unused_channel=unused, silence=rms(300),
                                   track_1=note(channels[0]), unused=note(unused))
            row["in_with_factory_settings"] = len(events(300))

            # SYSTEM MENU > MIDI > CONFIG, second page: A CLOCK OUT, C COMMAND (OFF, RX, TX, RX/TX).
            press(FUNC, HOME)
            for _ in range(4): press(DOWN)
            press(OK); press(DOWN); press(DOWN); press(OK)
            press(SELECT_RIGHT)
            turn(0, 1); turn(2, 3)
            press(HOME)
            row["midi_settings"] = words(MIDI_SETTINGS, 9)
            # Stopped, the stock sends no clock over USB (it does on the DIN jack: stock_midi.py). Recorded, not judged.
            stopped = len(events(150))
            row["stopped"] = dict(events=stopped, fifo_3_loads=sum(
                1 for access in cpu.mmio_trace() if access["address"] == 0x01e0042c and access["write"]))
            stock.key_input(PLAY, True)
            start = cpu.cycles()
            row["play"] = [[data, cycle - start] for data, cycle in events(1500)]
            stock.key_input(PLAY, False)
            stock.key_input(STOP, True)
            row["stop"] = sorted({data for data, _ in events(400)})
            stock.key_input(STOP, False)
            advance(200)

            cpu.usb_reset()
            again = enumerate_device()
            row["second_enumeration"] = dict(same=again["device"] == row["enumeration"]["device"] and
                                             again["configuration"] == row["enumeration"]["configuration"],
                                             steps=[step["status"] for step in again["steps"]])
            advance(10)
            row["after_reset"] = dict(note=note(channels[0]))
            stock.key_input(PLAY, True)
            row["after_reset"]["play"] = sorted({data for data, _ in events(300)})
            stock.key_input(PLAY, False)
            press(STOP)
            cpu.usb_detach()
            advance(20)
            state = cpu.usb_state()
            row["final"] = {name: state[name] for name in ("port", "bus_resets", "naks", "stalls", "errors", "toggle_errors",
                                                           "fifo_overflows", "fifo_underflows", "transfers")}
        except (RuntimeError, UsbError) as error:
            row["fault"] = str(error)
        row["cycles"] = cpu.cycles()
    return row


def judge(row):
    problems = []
    if row["fault"]:
        return [f'fault: {row["fault"]}']
    quarter = CYCLES_PER_SECOND * 600 / row["tempo_x10"]
    before = row["before_attach"]
    if before["port"] != "detached" or not before["soft_connect"] or before["interrupt_mask"] != 0x01ff1e1f:
        problems.append(f"before the cable: {before}")
    found = row["enumeration"]
    device = bytes.fromhex(found["device"])
    if [step["status"] for step in found["steps"]] != ["ok"] * 6:
        problems.append(f'enumeration steps: {found["steps"]}')
    if (found["vendor"], found["product"]) != (0x2fd7, 0x0004) or len(device) != 18 or device[2:4] != b"\x10\x01" or found["max_packet0"] != 64:
        problems.append(f'device descriptor {found["device"]}: expected vendor 0x2fd7, product 0x0004, bcdUSB 1.10, 64-byte endpoint 0')
    configuration = bytes.fromhex(found["configuration"])
    if len(configuration) != 234 or hashlib.sha256(configuration).hexdigest() != CONFIGURATION_SHA256:
        problems.append(f"the configuration descriptor ({len(configuration)} bytes) is not the one rebuilt statically")
    if found["endpoints"] != ENDPOINTS:
        problems.append(f'endpoints {found["endpoints"]}')
    after = row["after_enumeration"]
    if (after["port"], after["address"], after["device_address"], after["configuration"], after["bus_resets"]) != ("enabled", 1, 1, 1, 1):
        problems.append(f"after enumeration: {after}")
    if after["stalls"] or after["errors"] or after["toggle_errors"] or after["fifo_overflows"] or after["fifo_underflows"]:
        problems.append(f"enumeration left errors: {after}")
    if "UINT = 0" not in after["interrupt_mode"] or not row["sof_interrupts"]["sofs"]:
        problems.append(f'interrupt mode {after["interrupt_mode"]}, {row["sof_interrupts"]}')
    three = row["endpoint_3"]
    fifos = [three["tx_fifo"], three["rx_fifo"]]
    if (three["tx_max_packet"], three["rx_max_packet"]) != (64, 64) or any(fifo["packet"] < 64 or fifo["address"] < 64 for fifo in fifos) \
            or abs(fifos[0]["address"] - fifos[1]["address"]) < 64:
        problems.append(f"endpoint 3 after SET_CONFIGURATION: {three}")
    if row["control"] != dict(unsupported="stall", get_status=["ok", row["control"]["get_status"][1]]) or len(row["control"]["get_status"][1]) != 4:
        problems.append(f'control state machine: {row["control"]}')

    out = row["bulk_out"]
    if out["silence"] or out["unused"]["rms"] > 0.0005:
        problems.append(f'output without a matching note: idle rms {out["silence"]}, channel {out["unused_channel"] + 1} rms {out["unused"]["rms"]}')
    if out["track_1"]["status"] != "ok" or out["track_1"]["rms"] < 0.005:
        problems.append(f'a USB MIDI note on track 1\'s channel: {out["track_1"]}')
    if row["in_with_factory_settings"]:
        problems.append(f'{row["in_with_factory_settings"]} events on endpoint 0x83 with the factory settings')
    if row["midi_settings"][5:8] != [1, 0, 3]:
        problems.append(f'the menu did not set CLOCK OUT on, OUT/THRU = OUT, COMMAND = RX/TX: {row["midi_settings"]}')
    clocks = [cycle for data, cycle in row["play"] if data == "0ff80000"]
    others = [[data, cycle] for data, cycle in row["play"] if data != "0ff80000"]
    if [data for data, _ in others] != ["0ffa0000"] or others[0][1] > CYCLES_PER_SECOND // 10:
        problems.append(f"PLAY did not put one 0xFA event on endpoint 0x83 within 100 ms: {others}")
    if len(clocks) < 40:
        problems.append(f"endpoint 0x83 with CLOCK OUT on: {len(clocks)} clock events in 1.5 s of playing")
    else:
        gaps = [after - before for before, after in zip(clocks, clocks[1:])]
        mean = (clocks[-1] - clocks[0]) / len(gaps)
        if abs(mean / (quarter / 24) - 1) > 0.005:
            problems.append(f"USB MIDI clock is not 24 per quarter note: {quarter / mean:.3f}")
        if max(abs(gap - quarter / 24) for gap in gaps) > 2 * BLOCK:
            problems.append(f"a USB MIDI clock is more than two audio blocks from its nominal spacing ({min(gaps)} to {max(gaps)} cycles)")
    if row["stop"] != ["0ff80000", "0ffc0000"]:
        problems.append(f'STOP did not put 0xFC on endpoint 0x83: {row["stop"]}')
    second, after = row["second_enumeration"], row["after_reset"]
    if not second["same"] or second["steps"] != ["ok"] * 6:
        problems.append(f"after a second bus reset: {second}")
    if after["note"]["status"] != "ok" or after["note"]["rms"] < 0.005 or after["play"] != ["0ff80000", "0ffa0000"]:
        problems.append(f"endpoint 3 after the second enumeration: {after}")
    final = row["final"]
    if final["port"] != "detached" or final["bus_resets"] != 2 or final["stalls"] != 1 or final["errors"] or final["toggle_errors"] \
            or final["fifo_overflows"] or final["fifo_underflows"]:
        problems.append(f"at the end: {final}")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--conditional", action="store_true", help="accept the logged reserved low-store assumption")
    parser.add_argument("--genre", default="FUNK")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--output", type=Path, default=WORK / "stock-usb")
    args = parser.parse_args(argv)
    if not args.conditional:
        parser.error("this check runs the stock image past its reserved low stores: pass --conditional")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    row = measure(output, args.genre, args.seed)
    problems = judge(row)
    (output / "result.json").write_text(json.dumps(dict(row, problems=problems), indent=2) + "\n")
    if problems:
        print("FAIL:\n  " + "\n  ".join(problems))
        return 1
    clocks = [cycle for data, cycle in row["play"] if data == "0ff80000"]
    print(f'PASS: vendor {row["enumeration"]["vendor"]:#06x} product {row["enumeration"]["product"]:#06x}, 234-byte configuration, '
          f'note rms {row["bulk_out"]["track_1"]["rms"]} over USB MIDI, {len(clocks)} clock events on 0x83 in 1.5 s of playing at '
          f'{row["tempo_x10"] / 10:g} BPM, {row["final"]["naks"]} NAKs')
    return 0


if __name__ == "__main__":
    sys.exit(main())
