#!/usr/bin/env python3
"""Optional local-corpus check: isochronous streams on USB0 against the stock 3.2.174 firmware's USB audio.

The stock image starts with the generated drum project of stock_song.py; a full-speed host is plugged in,
enumerates and selects alternate setting 1 of the two audio streaming interfaces. Checked, against what
static analysis and simulation found in the firmware (docs/01-platform-map.md, "USB audio sample path";
docs/04-hardware-access.md, "The codec PLL trim"; claims HW-18, HW-40):

  interfaces    GET_INTERFACE answers 0, SET_INTERFACE 1 succeeds on interfaces 1 and 2 and GET_INTERFACE
                then answers 1. The firmware makes endpoint 1 an isochronous OUT and endpoint 2 an
                isochronous IN endpoint of 196 bytes, with FIFO access (no DMA).
  OUT           one 192-byte packet per frame (48 kHz, 16-bit, stereo: a 1 kHz tone) is stored every frame,
                none lost. It is silent until the USB AUDIO track is switched on with its pad (panel channel
                12), then reaches the line output at unity. With the track on and no more packets, the
                output keeps repeating the last 128-frame block.
  IN            the firmware answers every frame with a 192-byte packet (after a few zero-length ones it
                loads itself at the start), never with an underrun; the packets carry the mix.
  trim          while a streaming interface is active TIMER64P1 runs as a 64-bit counter at 24 MHz and
                stops when both are back at alternate setting 0. With the emulator's exact clocks the
                firmware finds nothing to correct: the codec PLL registers are not rewritten in 12 s.

Requires explicit --conditional (the logged reserved low-store assumption), node and npm.
"""
import argparse
import collections
import json
import math
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from build import WORK
from cpu import UsbError
from project_card import MS, project_card
from stock import Stock

CLR, USB_AUDIO_PAD, PAD_LEVEL = 30, 12, 9000
TIMER1 = 0x01c21000
AMPLITUDE = 12000
TONE = b"".join(struct.pack("<hh", sample, sample) for sample in
                (int(AMPLITUDE * math.sin(2 * math.pi * index / 48)) for index in range(48)))   # 1 ms of 1 kHz


def level(samples, hertz=1000):
    """(amplitude of the `hertz` component, rms) of samples scaled to 1.0."""
    k = 2 * math.cos(2 * math.pi * hertz / 48000)
    a = b = 0.0
    for sample in samples:
        a, b = sample + k * a - b, a
    count = max(1, len(samples))
    return (round(math.sqrt(max(0.0, a * a + b * b - k * a * b)) * 2 / count, 5),
            round(math.sqrt(sum(sample * sample for sample in samples) / count), 5))


def measure(output, genre, seed):
    card, flash, description = project_card(output / "card.img", genre, seed)
    row = dict(project=description, fault=None)
    with Stock(card=card, flash_image=flash, reserved_low_writes=True, panel_stream=True) as stock:
        cpu = stock.cpu

        def advance(milliseconds):
            for part in [100] * (milliseconds // 100) + [milliseconds % 100] * bool(milliseconds % 100):
                report = stock.run(part * MS, 1000000)
                if report["error"]:
                    raise RuntimeError(report["error"])

        def line_out(milliseconds):
            """The left channel the codec was sent over a stretch of guest time, as level()."""
            seen = cpu.audio_tail(0)[2]
            advance(milliseconds)
            raw, slot = cpu.audio_tail(seen)[:2]
            words = struct.unpack(f"<{len(raw) // 4}i", raw)
            return level([word / 2**31 for word in words[slot & 1::2]])

        def stream(milliseconds, out=True):
            """Run both streams for a stretch: the line output's level, and what came in."""
            if out:
                cpu.usb_iso_stream_out(1, [TONE] * milliseconds)
            cpu.usb_iso_stream_in(0x82, milliseconds, wait=False, short_below=192)
            heard = line_out(milliseconds)
            packets = cpu.usb_iso_collect(0x82)
            data = b"".join(packet["data"] for packet in packets)
            left = [sample / 32768 for sample in struct.unpack(f"<{len(data) // 2}h", data)[::2]]
            kinds = collections.Counter(f'{packet["status"]} {len(packet["data"])}' for packet in packets)
            return dict(line_out=heard, packets=dict(kinds), into_host=level(left),
                        first_data=next((index for index, packet in enumerate(packets) if packet["status"] == "data"), None))

        def tap():
            stock.panel_level(USB_AUDIO_PAD, PAD_LEVEL); advance(150)
            stock.panel_level(USB_AUDIO_PAD, 0); advance(250)

        def timer():
            return dict(zip(("tim12", "tim34", "prd12", "prd34", "tcr", "tgcr"),
                            (struct.unpack("<I", cpu.read(TIMER1 + offset, 4))[0] for offset in (0x10, 0x14, 0x18, 0x1c, 0x20, 0x24))))

        def endpoints():
            return cpu.usb_state()["endpoints"][:2]

        def pll():
            return [cpu.codec_register(0, register) for register in (3, 4, 5, 6)]

        try:
            advance(6000)
            stock.key_input(CLR, True); advance(70); stock.key_input(CLR, False); advance(500)
            cpu.usb_attach()
            found = cpu.usb_enumerate()
            advance(10)
            row["endpoints"] = [endpoint for endpoint in found["endpoints"] if endpoint["type"] == "isochronous"]
            get = lambda interface: cpu.usb_control((0x81, 10, 0, interface), 1)
            row["alternate_0"] = dict(get_interface=[get(1)["data"].hex(), get(2)["data"].hex()], endpoints=endpoints(), timer=timer())
            row["set_interface"] = [cpu.usb_set_interface(1, 1)["status"], cpu.usb_set_interface(2, 1)["status"]]
            advance(20)
            row["alternate_1"] = dict(get_interface=[get(1)["data"].hex(), get(2)["data"].hex()], endpoints=endpoints(), timer=timer())
            row["pll_before"], writes = pll(), cpu.codec_state()["register_writes"]

            row["track_off"] = stream(300)
            tap()
            row["track_on"] = stream(1000)
            seconds = []
            for _ in range(12):
                before, start = timer()["tim12"], cpu.cycles()
                seconds.append(dict(stream(1000), ticks=None))
                seconds[-1].update(ticks=(timer()["tim12"] - before) & 0xffffffff, cycles=cpu.cycles() - start)
            row["seconds"] = seconds
            row["starved"] = stream(300, out=False)
            tap()
            row["track_off_again"] = stream(300)
            row["pll_after"], row["codec_writes_while_streaming"] = pll(), cpu.codec_state()["register_writes"] - writes
            row["streams"] = dict(out=cpu.usb_iso_state(1), into_host=cpu.usb_iso_state(0x82))
            state = cpu.usb_state()
            row["while_streaming"] = {name: state[name] for name in ("stalls", "errors", "toggle_errors", "iso_errors", "iso_missed",
                                                                     "iso_underruns", "iso_overruns", "fifo_overflows", "fifo_underflows")}

            row["clear_interface"] = [cpu.usb_set_interface(1, 0)["status"], cpu.usb_set_interface(2, 0)["status"]]
            advance(50)
            stopped = timer()
            advance(10)
            row["alternate_0_again"] = dict(get_interface=[get(1)["data"].hex(), get(2)["data"].hex()], timer=stopped,
                                            ticks_in_10_ms=(timer()["tim12"] - stopped["tim12"]) & 0xffffffff)
            # After the stream is closed (recorded, not judged): what five more IN tokens get.
            row["tokens_at_alternate_0"] = [packet["status"] for packet in cpu.usb_iso_stream_in(0x82, 5)]
        except (RuntimeError, UsbError) as error:
            row["fault"] = str(error)
        row["cycles"] = cpu.cycles()
    return row


def judge(row):
    problems = []
    if row["fault"]:
        return [f'fault: {row["fault"]}']
    if [(endpoint["address"], endpoint["interface"], endpoint["alternate"], endpoint["max_packet"]) for endpoint in row["endpoints"]] != \
            [(0x01, 1, 1, 196), (0x82, 2, 1, 196)]:
        problems.append(f'isochronous endpoints in the descriptor: {row["endpoints"]}')
    before, after = row["alternate_0"], row["alternate_1"]
    if before["get_interface"] != ["00", "00"] or row["set_interface"] != ["ok", "ok"] or after["get_interface"] != ["01", "01"]:
        problems.append(f'alternate settings: {before["get_interface"]}, SET_INTERFACE {row["set_interface"]}, then {after["get_interface"]}')
    one, two = after["endpoints"]
    if not one["rx_iso"] or one["rx_max_packet"] != 196 or one["rx_fifo"]["packet"] < 196:
        problems.append(f"endpoint 1 at alternate setting 1: {one}")
    if not two["tx_iso"] or two["tx_max_packet"] != 196 or two["tx_fifo"]["packet"] < 196:
        problems.append(f"endpoint 2 at alternate setting 1: {two}")
    timer = after["timer"]
    if timer["tgcr"] & 0xf != 3 or timer["tcr"] >> 6 & 3 != 2 or (timer["prd12"], timer["prd34"]) != (0xffffffff, 0xffffffff):
        problems.append(f"TIMER64P1 is not a free-running 64-bit counter while streaming: {timer}")
    if before["timer"]["tcr"] >> 6 & 3:
        problems.append(f'TIMER64P1 already runs before a streaming interface is active: {before["timer"]}')

    unity = 12000 / 32768
    off, on = row["track_off"], row["track_on"]
    if any(off["line_out"]):
        problems.append(f'the stream is heard with the USB AUDIO track off: {off["line_out"]}')
    if off["first_data"] is None or off["first_data"] > 8 or set(off["packets"]) - {"data 192", "empty 0"}:
        problems.append(f'the first IN frames: {off["packets"]}, data from frame {off["first_data"]}')
    if off["into_host"][1]:
        problems.append(f'the IN stream is not silent with nothing playing: {off["into_host"]}')
    for name, part in [("the first second", on)] + [(f"second {index + 2}", part) for index, part in enumerate(row["seconds"])]:
        if abs(part["line_out"][0] - unity) > 0.01:
            problems.append(f'{name} with the track on: the tone is at {part["line_out"][0]} on the line output, not {unity:.4f}')
        if part["packets"] != {"data 192": 1000}:
            problems.append(f'{name}: IN packets {part["packets"]}')
    if on["into_host"][0] < 0.05:
        problems.append(f'the IN stream does not carry the mix: tone at {on["into_host"][0]}')
    if any(second["ticks"] != 24000000 * second["cycles"] // 372000000 for second in row["seconds"]):
        problems.append(f'TIMER64P1 does not count at 24 MHz: {[second["ticks"] for second in row["seconds"]]}')
    starved = row["starved"]
    if starved["line_out"][1] < 0.1 or starved["line_out"][0] > 0.1:
        problems.append(f'with no packets and the track on, the output is not the last block repeated: {starved["line_out"]}')
    if any(row["track_off_again"]["line_out"]):
        problems.append(f'the second pad press did not switch the track off: {row["track_off_again"]["line_out"]}')
    if row["pll_before"] != row["pll_after"]:
        problems.append(f'the codec PLL changed while streaming: {row["pll_before"]} to {row["pll_after"]}')

    out, into_host = row["streams"]["out"], row["streams"]["into_host"]
    if out["packets"] != out["sent"] or out["missed"] or out["errors"]:
        problems.append(f"OUT stream: {out}")
    if into_host["errors"] or into_host["short"] or into_host["missed"] > 8:
        problems.append(f"IN stream: {into_host}")
    again = row["alternate_0_again"]
    if row["clear_interface"] != ["ok", "ok"] or again["get_interface"] != ["00", "00"] or again["timer"]["tcr"] >> 6 & 3 or again["ticks_in_10_ms"]:
        problems.append(f'back at alternate setting 0: {row["clear_interface"]}, {again}')
    final = row["while_streaming"]
    if final["stalls"] or final["errors"] or final["toggle_errors"] or final["iso_errors"] or final["iso_underruns"] \
            or final["iso_overruns"] or final["fifo_overflows"] or final["fifo_underflows"]:
        problems.append(f"errors while streaming: {final}")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--conditional", action="store_true", help="accept the logged reserved low-store assumption")
    parser.add_argument("--genre", default="FUNK")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--output", type=Path, default=WORK / "stock-usb-audio")
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
    out, into_host = row["streams"]["out"], row["streams"]["into_host"]
    print(f'PASS: {out["packets"]} of {out["sent"]} OUT packets stored, tone at {row["track_on"]["line_out"][0]} on the line output '
          f'with the USB AUDIO track on, {into_host["packets"]} IN packets of 192 bytes and {into_host["missed"]} zero-length, '
          f'TIMER64P1 at {row["seconds"][0]["ticks"]} counts a second, {row["codec_writes_while_streaming"]} codec writes while streaming')
    return 0


if __name__ == "__main__":
    sys.exit(main())
