#!/usr/bin/env python3
"""Optional local-corpus check: the MIDI and SYNC models against the stock 3.2.174 firmware.

The stock image starts with the generated drum project of stock_song.py and is driven through its own
menus (SYSTEM MENU > MIDI > CONFIG and SYSTEM MENU > CLOCK); guest memory is read, never written.
Checked, against what static analysis found in the firmware (docs/04-hardware-access.md, "MIDI DIN on
UART0" and "SYNC IN / SYNC OUT"; claims HW-11, HW-27, HW-31, HW-41):

  MIDI IN    a note on track 1's channel, sent through the paced MIDI IN peer, plays the track; the
             same note on an unused channel is silent; a 300-byte SysEx dump followed by a note
             arrives without a FIFO overrun, where the same bytes pushed at once overrun.
  SYNC OUT   GP7[9] is driven low at set-up and pulses high twice per quarter note for 14 to 15 ms
             (the firmware ends a pulse on its 1 ms tick), each pulse on an audio block boundary.
  MIDI OUT   nothing is sent with the factory settings. With CLOCK OUT on, UART0 sends 0xF8 24 times
             per quarter note, 12 to a SYNC OUT pulse, the clock of positions 0 and 36 in the same
             audio block as the pulse; with COMMAND on, PLAY sends 0xFA and STOP 0xFC; with OUT/THRU
             set to THRU, a message sent to MIDI IN comes back out whole.
  SYNC IN    with SOURCE = SYNC, pulses scheduled on GP7[8] raise the bank 7 interrupt, the stock
             handler acknowledges each one, and the tempo follows: steady, changed, then stopped.

Requires explicit --conditional (the logged reserved low-store assumption), node and npm.
"""
import argparse
import json
import math
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from build import WORK
from cpu import CYCLES_PER_SECOND
from project_card import MS, project_card
from stock import Stock

SELECT_RIGHT, UP, FUNC, PLAY, OK, DOWN, HOME, STOP, CLR = 9, 17, 19, 22, 23, 25, 27, 29, 30
TEMPO, SETTINGS, EXTERNAL_TEMPO = 0xc1500cf4, 0xc14fac58, 0xc1501fe8 + 40
SOURCE, TRACK_CHANNELS, MIDI_SETTINGS = SETTINGS + 4, SETTINGS + 0x8c, SETTINGS + 0xd8
BINTEN, INTSTAT67, SYNC_IN_BIT = 0x01e26008, 0x01e260ac, 1 << 24
BLOCK = 128 * CYCLES_PER_SECOND // 48000   # one audio block: 2.67 ms
CHARACTER = 119040
SYNC_TEMPOS = (140, 90)


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

        def note(channel, key=36):
            cpu.midi_in(bytes([0x90 | channel, key, 110]))
            level = rms(300)
            cpu.midi_in(bytes([0x80 | channel, key, 0]))
            advance(1500)   # let it ring out
            return level

        def sent(since):
            data, total, cycles = cpu.uart_sent(0, since, cycles=True)
            return data, cycles, total

        try:
            advance(6000); press(CLR)
            row["tempo_x10"] = words(TEMPO)[0]
            channels = words(TRACK_CHANNELS, 8)
            unused = next(channel for channel in range(15) if channel not in channels)   # 15 is the AUTO channel
            row["midi_in"] = dict(track_channels=channels, silence=rms(300), track_1=note(channels[0]), unused=note(unused),
                                  unused_channel=unused)
            dump = bytes([0xf0, 0x7d, *(index & 0x7f for index in range(297)), 0xf7])
            cpu.midi_in(dump + bytes([0x90 | channels[0], 36, 110]))
            advance(len(dump) * CHARACTER // MS + 1)
            row["midi_in"].update(after_dump=note(channels[0]), **{name: cpu.midi_state()[name] for name in ("delivered", "ignored", "overruns")})
            row["sent_with_factory_settings"] = cpu.uart_sent(0)[1]

            # SYSTEM MENU > MIDI > CONFIG, second page: A CLOCK OUT, B OUT/THRU, C COMMAND (OFF, RX, TX, RX/TX).
            press(FUNC, HOME)
            for _ in range(4): press(DOWN)
            press(OK); press(DOWN); press(DOWN); press(OK)
            press(SELECT_RIGHT)
            # THRU: the jack repeats MIDI IN in place of the unit's own output. A message for no track of this
            # project comes back out.
            turn(1, 1)
            thru_setting = words(MIDI_SETTINGS + 0x18)[0]
            message = bytes([0x90 | unused, 60, 100, 0x80 | unused, 60, 0])
            begin = cpu.cycles()
            cpu.midi_in(message)
            advance(200)
            data, cycles, _ = sent(0)
            row["thru"] = dict(setting=thru_setting, sent=message.hex(), echoed=data.hex(),
                               delay_cycles=[cycle - (begin + (index + 1) * CHARACTER) for index, cycle in enumerate(cycles)])
            turn(1, -1); turn(0, 1); turn(2, 3)
            press(HOME)
            row["midi_settings"] = words(MIDI_SETTINGS, 9)

            mark, trace_from = cpu.uart_sent(0)[1], cpu.gpio_trace()[1]
            stock.key_input(PLAY, True)
            start = cpu.cycles()
            advance(500); stock.key_input(PLAY, False)
            advance(5500)
            data, cycles, mark = sent(mark)
            rows, total = cpu.gpio_trace()
            row["midi_out"] = dict(bytes=len(data), other_bytes=[[byte, cycle - start] for byte, cycle in zip(data, cycles) if byte != 0xf8],
                                   clock_cycles=[cycle - start for byte, cycle in zip(data, cycles) if byte == 0xf8])
            row["sync_out"] = dict(first=rows[0] if total <= 4096 else None,
                                   changes=[[change["high"], change["cycles"] - start] for change in rows[trace_from - total:]],
                                   pins=sorted({change["bank"] * 16 + change["pin"] for change in rows}))
            press(STOP)
            data, cycles, mark = sent(mark)
            row["midi_out"]["after_stop"] = sorted(set(data) - {0xf8})

            # SYSTEM MENU (its cursor still on MIDI) > CLOCK: A SOURCE, INTERNAL > MIDI > SYNC. POLARITY IN stays
            # at its default.
            press(FUNC, HOME); press(UP); press(UP); press(OK)
            turn(0, 2)
            press(HOME)
            row["sync_in"] = dict(source=words(SOURCE)[0], bank_7_interrupt=bool(words(BINTEN)[0] & 1 << 7), trains=[])
            ends, at = [], cpu.cycles() + MS
            for bpm in SYNC_TEMPOS:   # one train straight after the other: a tempo change with no gap
                at = cpu.sync_in(bpm, 16, at)
                ends.append(at)
            for bpm, end in zip(SYNC_TEMPOS, ends):
                pending, readings = 0, []
                while cpu.cycles() + 100 * MS <= end:
                    advance(100)
                    pending += bool(words(INTSTAT67)[0] & SYNC_IN_BIT)
                    readings.append(words(EXTERNAL_TEMPO)[0])
                row["sync_in"]["trains"].append(dict(bpm=bpm, pulses=16, pending_samples=pending, tempo_x10=readings,
                                                     shown_tempo_x10=words(TEMPO)[0]))
            advance(3000)   # the clock has stopped
            row["sync_in"].update(edges_left=cpu.gpio_scheduled(), tempo_x10_after_stop=words(EXTERNAL_TEMPO)[0],
                                  pending_after_stop=bool(words(INTSTAT67)[0] & SYNC_IN_BIT))

            before = cpu.midi_state()["overruns"]
            cpu.uart_receive(0, dump)
            row["instant_path_overruns"] = cpu.midi_state()["overruns"] - before
        except RuntimeError as error:
            row["fault"] = str(error)
        row["cycles"] = cpu.cycles()
    return row


def judge(row):
    problems = []
    if row["fault"]:
        return [f'fault: {row["fault"]}']
    quarter = CYCLES_PER_SECOND * 600 / row["tempo_x10"]
    midi_in = row["midi_in"]
    if midi_in["silence"] or midi_in["unused"] > 0.0005:
        problems.append(f'output without a matching note: idle rms {midi_in["silence"]}, channel {midi_in["unused_channel"] + 1} rms {midi_in["unused"]}')
    if midi_in["track_1"] < 0.005 or midi_in["after_dump"] < 0.005:
        problems.append(f'a note on track 1\'s channel is silent (rms {midi_in["track_1"]}, after the dump {midi_in["after_dump"]})')
    if midi_in["overruns"] or midi_in["ignored"] or midi_in["delivered"] != 321:
        problems.append(f'the paced MIDI IN lost bytes: {midi_in["delivered"]} of 321 delivered, {midi_in["ignored"]} ignored, {midi_in["overruns"]} overruns')
    if not row["instant_path_overruns"]:
        problems.append("300 bytes pushed at once no longer overrun the FIFO: review the note on uart_receive")
    if row["sent_with_factory_settings"]:
        problems.append(f'{row["sent_with_factory_settings"]} bytes sent on MIDI OUT with the factory settings')
    thru = row["thru"]
    if thru["setting"] != 1 or thru["echoed"] != thru["sent"] or not all(0 <= delay < BLOCK for delay in thru["delay_cycles"]):
        problems.append(f'THRU (setting {thru["setting"]}) sent {thru["echoed"] or "nothing"} for {thru["sent"]}, delays {thru["delay_cycles"]}')
    if row["midi_settings"][5:8] != [1, 0, 3]:
        problems.append(f'the menu did not set CLOCK OUT on, OUT/THRU = OUT, COMMAND = RX/TX: {row["midi_settings"]}')

    midi_out, clocks = row["midi_out"], row["midi_out"]["clock_cycles"]
    if [byte for byte, _ in midi_out["other_bytes"]] != [0xfa] or midi_out["other_bytes"][0][1] > CYCLES_PER_SECOND // 10:
        problems.append(f'PLAY did not send one 0xFA within 100 ms and then clocks only: {midi_out["other_bytes"]}')
    if midi_out["after_stop"] != [0xfc]:
        problems.append(f'STOP did not send 0xFC: {midi_out["after_stop"]}')
    gaps = [after - before for before, after in zip(clocks, clocks[1:])]
    if len(clocks) < 100:
        problems.append(f"only {len(clocks)} MIDI clocks in six seconds")
    else:
        mean = (clocks[-1] - clocks[0]) / len(gaps)
        if abs(mean / (quarter / 24) - 1) > 0.002:
            problems.append(f"MIDI clock is not 24 per quarter note: {quarter / mean:.3f}")
        if max(abs(gap - quarter / 24) for gap in gaps) > BLOCK + 64:
            problems.append("a MIDI clock is more than one audio block from its nominal spacing")

    sync = row["sync_out"]
    if sync["pins"] != [7 * 16 + 9] or sync["first"] is None or sync["first"]["high"]:
        problems.append(f'SYNC OUT is not driven low at set-up: first change {sync["first"]}, pins {sync["pins"]}')
    changes = sync["changes"]
    if changes and not changes[0][0]:
        changes = changes[1:]   # the end of a pulse begun before PLAY
    rises = [cycle for high, cycle in changes if high]
    widths = [fall[1] - rise[1] for rise, fall in zip(changes[::2], changes[1::2])]
    if len(rises) < 10 or [high for high, _ in changes] != [index % 2 == 0 for index in range(len(changes))]:
        problems.append(f"SYNC OUT does not alternate, or pulsed only {len(rises)} times")
    else:
        mean = (rises[-1] - rises[0]) / (len(rises) - 1)
        if abs(mean / (quarter / 2) - 1) > 0.002:
            problems.append(f"SYNC OUT is not 2 pulses per quarter note: {quarter / mean:.3f}")
        if any((after - before) % BLOCK > 64 and (before - after) % BLOCK > 64 for before, after in zip(rises, rises[1:])):
            problems.append("SYNC OUT pulses are not a whole number of audio blocks apart")
        if not all(14 * MS <= width <= 15 * MS + 64 for width in widths):
            problems.append(f"SYNC OUT pulses are not 14 to 15 ms wide: {min(widths) / MS:.2f} to {max(widths) / MS:.2f} ms")
        per_pulse = {sum(before <= clock - CHARACTER < after for clock in clocks) for before, after in zip(rises, rises[1:])}
        if per_pulse != {12}:
            problems.append(f"MIDI clocks per SYNC OUT pulse: {sorted(per_pulse)}, expected 12")
        # The clock byte of the pulse's position starts within the block the pulse starts in.
        if not all(any(abs(clock - CHARACTER - rise) < BLOCK for clock in clocks) for rise in rises if rise + BLOCK + CHARACTER < clocks[-1]):
            problems.append("a SYNC OUT pulse has no MIDI clock in its audio block")
    sync_in = row["sync_in"]
    if sync_in["source"] != 2 or not sync_in["bank_7_interrupt"]:
        problems.append(f'the menu did not set SOURCE = SYNC (setting {sync_in["source"]}) or the bank 7 interrupt is off')
    else:
        for train in sync_in["trains"]:
            if train["pending_samples"]:
                problems.append(f'SYNC IN at {train["bpm"]} BPM: the edge interrupt was left pending in {train["pending_samples"]} samples')
            if abs(train["tempo_x10"][-1] - train["bpm"] * 10) > 2:
                problems.append(f'SYNC IN at {train["bpm"]} BPM: the firmware measured {train["tempo_x10"][-1] / 10}')
        if sync_in["edges_left"] or sync_in["pending_after_stop"] or sync_in["tempo_x10_after_stop"] != sync_in["trains"][-1]["tempo_x10"][-1]:
            problems.append(f'SYNC IN stopped: {sync_in["edges_left"]} edges left, tempo {sync_in["tempo_x10_after_stop"] / 10}')
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--conditional", action="store_true", help="accept the logged reserved low-store assumption")
    parser.add_argument("--genre", default="FUNK")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--output", type=Path, default=WORK / "stock-midi")
    args = parser.parse_args(argv)
    if not args.conditional:
        parser.error("--conditional is required: this run discards reserved low stores")
    args.output.mkdir(parents=True, exist_ok=True)
    row = measure(args.output, args.genre, args.seed)
    (args.output / "result.json").write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
    problems = judge(row)
    for problem in problems:
        print("FAIL:", problem)
    summary = ""
    if not row["fault"]:
        widths = [fall[1] - rise[1] for rise, fall in zip(row["sync_out"]["changes"][-20::2], row["sync_out"]["changes"][-19::2])]
        summary = (f': {row["tempo_x10"] / 10:g} BPM, {len(row["midi_out"]["clock_cycles"])} MIDI clocks, '
                   f'{sum(high for high, _ in row["sync_out"]["changes"])} SYNC OUT pulses of {min(widths) / MS:.2f} to {max(widths) / MS:.2f} ms, '
                   f'note rms {row["midi_in"]["track_1"]} on channel {row["midi_in"]["track_channels"][0] + 1}, SYNC IN read as '
                   + " then ".join(f'{train["tempo_x10"][-1] / 10:g}' for train in row["sync_in"]["trains"]) + " BPM")
    print(f'{"FAIL" if problems else "PASS"}{summary}; result in {args.output}')
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
