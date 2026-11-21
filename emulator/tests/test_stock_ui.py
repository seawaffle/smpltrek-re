"""Panel server logic against a recording stand-in machine; no firmware image is needed."""
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import stock_ui
from stock_ui import AUDIO, CYCLES_PER_SECOND, FRAME, MIDI, STATUS, Panel, make_server


class Processor:
    def __init__(self):
        self.now, self.words, self.sent, self.pins, self.stream = 0, [], b"", [], False
        self.midi_sent, self.midi_received = b"", b""
        self.frame = bytes(8192)

    def cycles(self):
        return self.now

    def audio_tail(self, since):
        fresh = self.words[since:]
        return struct.pack(f"<{len(fresh)}I", *fresh), since & 1, len(self.words), 0

    def oled_frame(self):
        return self.frame, {"on": True, "complete_frames": 1}

    def uart_sent(self, index, since):
        sent = self.sent if index == 1 else self.midi_sent
        return sent[since:], len(sent)

    def midi_state(self):
        return {"queued": 0, "delivered": len(self.midi_received), "ignored": 0, "overruns": 0, "loopback": False}

    def fast_forward_state(self):
        return {"skipped_cycles": 0}

    def reserved_low_state(self):
        return {"enabled": True}

    def reserved_low_read_state(self):
        return {"enabled": True}

    def panel_stream_state(self):
        return {"enabled": self.stream}

    def gpio_input(self, bank, pin, high):
        self.pins.append((self.now, bank, pin, high))

    def nor_read(self, chip):
        return bytes([chip]) * 16

    def sd_state(self):
        return {"present": True}

    def sd_read(self):
        return b"card"


class Machine:
    """Records every external input with the guest cycle at which it was applied."""

    def __init__(self):
        self.cpu, self.log, self.inputs, self.checkpoints, self.power_release = Processor(), [], [], [], 1

    def step(self, cycles):
        self.cpu.now += cycles
        self.cpu.words += [len(self.cpu.words) + 1, len(self.cpu.words) + 2]
        return {"cycles": self.cpu.now, "status": "budget", "pc": 0}

    def key_input(self, key, down):
        self.log.append((self.cpu.now, "key", key, down))

    def panel_level(self, channel, value):
        self.log.append((self.cpu.now, "level", channel, value))

    def encoder_phase(self, encoder, phase):
        self.log.append((self.cpu.now, "phase", encoder, phase))

    def uart_receive(self, index, data):
        self.log.append((self.cpu.now, "uart", index, bytes(data)))

    def midi_in(self, data):
        self.cpu.midi_received += bytes(data)
        self.log.append((self.cpu.now, "midi", bytes(data)))


class StockPanel(unittest.TestCase):
    def settle(self, panel, steps=400):
        for _ in range(steps):
            panel.step()

    def test_inputs_are_validated_before_they_reach_the_machine(self):
        panel = Panel(Machine())
        for event in ({"type": "key", "index": 48, "down": True}, {"type": "key", "index": 1, "down": 1},
                      {"type": "encoder", "index": 5, "delta": 1}, {"type": "encoder", "index": 0, "delta": 0},
                      {"type": "pad", "index": 15, "value": 1}, {"type": "pad", "index": 0, "value": 16384},
                      {"type": "battery", "value": -1}, {"type": "power", "down": "yes"},
                      {"type": "midi", "bytes": []}, {"type": "midi", "bytes": [256]}, {"type": "midi", "bytes": "\x90"},
                      {"type": "midi", "bytes": [0] * 1025}, {"type": "midi", "bytes": [0x90, 60.0, 1]},
                      {"type": "control", "action": "reset"}, {"type": "key", "index": 1, "down": True, "extra": 1}, []):
            with self.subTest(event=event), self.assertRaises(ValueError):
                panel.post(event)
        self.assertTrue(panel.inputs.empty())

    def test_keys_reach_the_switch_matrix_and_the_status(self):
        machine = Machine(); panel = Panel(machine)
        panel.post({"type": "key", "index": 19, "down": True}); panel.post({"type": "key", "index": 27, "down": True})
        panel.step()
        self.assertEqual([row[1:] for row in machine.log], [("key", 19, True), ("key", 27, True)])
        self.assertEqual(panel.describe()["keys"], f"{1 << 19 | 1 << 27:012x}")
        panel.post({"type": "key", "index": 19, "down": False}); panel.step()
        self.assertEqual(panel.describe()["keys"], f"{1 << 27:012x}")

    def test_encoder_detents_are_complete_quadrature_sequences_two_polls_apart(self):
        machine = Machine(); panel = Panel(machine)
        panel.post({"type": "encoder", "index": 4, "delta": 2}); panel.post({"type": "encoder", "index": 4, "delta": -1})
        panel.post({"type": "encoder", "index": 0, "delta": 1})
        self.settle(panel)
        value = [(cycle, phase) for cycle, kind, encoder, phase in machine.log if kind == "phase" and encoder == 4]
        self.assertEqual([phase for _, phase in value], [2, 0, 1, 3, 2, 0, 1, 3, 1, 0, 2, 3])
        gaps = {later - earlier for (earlier, _), (later, _) in zip(value, value[1:])}
        self.assertEqual(gaps, {2 * CYCLES_PER_SECOND // 1000})
        other = [phase for _, kind, encoder, phase in machine.log if kind == "phase" and encoder == 0]
        self.assertEqual(other, [2, 0, 1, 3])

    def test_pads_and_battery_are_panel_analogue_packets_one_byte_at_a_time(self):
        machine = Machine(); panel = Panel(machine)
        panel.post({"type": "pad", "index": 3, "value": 1024}); panel.post({"type": "battery", "value": 16383})
        self.settle(panel, 60)
        sent = [(cycle, data) for cycle, kind, index, data in machine.log if kind == "uart" and index == 1]
        self.assertEqual(b"".join(data for _, data in sent), bytes([0xb3, 0, 8, 0xbf, 0x7f, 0x7f]))
        self.assertTrue(all(len(data) == 1 for _, data in sent))
        self.assertTrue(all(later - earlier >= 8000 for (earlier, _), (later, _) in zip(sent, sent[1:])))
        self.assertEqual(panel.describe()["pads"][3], 1024)

    def test_with_the_panel_stream_a_pad_or_battery_change_sets_the_level_it_reports(self):
        machine = Machine(); machine.cpu.stream = True; panel = Panel(machine)
        panel.post({"type": "pad", "index": 3, "value": 1024}); panel.post({"type": "battery", "value": 16383})
        self.settle(panel, 60)
        self.assertEqual([entry[1:] for entry in machine.log if entry[1] != "key"], [("level", 3, 1024), ("level", 15, 16383)])
        self.assertEqual(panel.describe()["pads"][3], 1024)

    def test_midi_input_reaches_the_midi_in_peer_and_midi_out_is_published_in_order(self):
        machine = Machine()
        machine.cpu.midi_sent = b"\xf8"                      # sent before the panel started: not replayed
        panel = Panel(machine)
        client = panel.subscribe()
        panel.post({"type": "midi", "bytes": [0x90, 60, 100]}); panel.post({"type": "midi", "bytes": [0x80, 60, 0]})
        panel.step()
        self.assertEqual([row[1:] for row in machine.log], [("midi", b"\x90\x3c\x64"), ("midi", b"\x80\x3c\x00")])
        machine.cpu.midi_sent += b"\xfa\xf8"; panel.step()
        machine.cpu.midi_sent += b"\xf8"; panel.step(); panel.step()
        payloads = []
        while not client.empty():
            data = client.get()
            if data[0] == MIDI:
                payloads.append(data[5:])
        self.assertEqual(payloads, [b"\xfa\xf8", b"\xf8"])
        self.assertEqual(panel.describe()["midi"], {"queued": 0, "delivered": 6, "overruns": 0, "sent": 4})

    def test_power_key_cancels_the_scripted_hold_and_drives_gp3_0_low(self):
        machine = Machine(); panel = Panel(machine)
        self.assertTrue(panel.describe()["power_key"])
        panel.post({"type": "power", "down": False}); panel.step()
        self.assertIsNone(machine.power_release)
        self.assertEqual(machine.cpu.pins[-1][1:], (3, 0, True))
        panel.post({"type": "power", "down": True}); panel.step()
        self.assertEqual(machine.cpu.pins[-1][1:], (3, 0, False))

    def test_led_packets_are_parsed_across_reads_and_abandoned_by_a_status_byte(self):
        panel = Panel(Machine())
        panel.leds_from(bytes([0xc1, 1, 5]))
        panel.leds_from(bytes([6, 9, 0xc1, 0, 0, 0xb3, 1, 2, 0xc1, 2, 5, 7, 15, 0xc1, 3, 0, 0, 1]))
        self.assertEqual(panel.leds[94], 9)
        self.assertEqual(panel.leds[143], 15)
        self.assertEqual(sum(1 for value in panel.leds if value), 2)

    def test_a_frame_dropped_for_a_busy_client_is_sent_once_its_queue_drains(self):
        machine = Machine(); panel = Panel(machine)
        client = panel.subscribe()
        while client.qsize() <= 64:                       # a client that has stopped reading
            panel.publish(stock_ui.message(AUDIO, b"\0"))
        machine.cpu.frame = b"\x55" * len(panel.frame)
        panel.observe()                                   # the changed frame finds the queue congested
        frames = []
        def drain():
            while not client.empty():
                data = client.get()
                if data[0] == FRAME:
                    frames.append(data[5:])
        drain()
        self.assertNotIn(machine.cpu.frame, frames)       # it was dropped, as audio would be
        panel.observe()                                   # nothing changed on the display since
        drain()
        self.assertEqual(frames[-1], machine.cpu.frame)
        panel.observe(); drain()
        self.assertEqual(frames.count(machine.cpu.frame), 1)

    def test_pause_stops_guest_time_and_save_needs_a_state_directory(self):
        machine = Machine(); panel = Panel(machine)
        panel.post({"type": "control", "action": "pause"})
        self.assertFalse(panel.step())
        before = machine.cpu.now
        self.assertFalse(panel.step())
        self.assertEqual(machine.cpu.now, before)
        panel.post({"type": "control", "action": "save"}); panel.step()
        self.assertIn("--state", panel.describe()["notice"])
        panel.post({"type": "control", "action": "resume"})
        self.assertTrue(panel.step())
        with tempfile.TemporaryDirectory(prefix="smpltrek-panel-") as directory:
            kept = Panel(Machine(), state=Path(directory) / "kept")
            kept.post({"type": "control", "action": "save"}); kept.step()
            self.assertEqual((Path(directory) / "kept/flash.img").read_bytes(), b"\0" * 16 + b"\1" * 16)
            self.assertEqual((Path(directory) / "kept/card.img").read_bytes(), b"card")
            self.assertTrue((Path(directory) / "kept/frame.png").read_bytes().startswith(b"\x89PNG"))

    def test_stream_carries_status_frame_and_ordered_audio_and_rejects_foreign_origins(self):
        machine = Machine(); panel = Panel(machine)
        with make_server(panel, 0) as server:
            base = f"http://127.0.0.1:{server.server_port}"
            threading.Thread(target=server.serve_forever, daemon=True).start()
            runner = threading.Thread(target=panel.run, daemon=True); runner.start()
            try:
                self.assertIn(b'id="screen"', urlopen(base + "/", timeout=5).read())
                self.assertIn(b"function draw", urlopen(base + "/stock.js", timeout=5).read())
                stream, buffered, kinds, words = urlopen(base + "/stream", timeout=5), b"", [], []
                deadline = time.monotonic() + 5
                while len(words) < 64 and time.monotonic() < deadline:
                    buffered += stream.read1(65536)
                    while len(buffered) >= 5:
                        kind, length = struct.unpack_from("<BI", buffered)
                        if len(buffered) < 5 + length:
                            break
                        payload, buffered = buffered[5:5 + length], buffered[5 + length:]
                        kinds.append(kind)
                        if kind == AUDIO:
                            self.assertEqual(payload[0], len(words) & 1)  # slot of the first word
                            words += struct.unpack(f"<{(length - 1) // 4}I", payload[1:])
                        elif kind == FRAME:
                            self.assertEqual(length, 8192)
                        else:
                            self.assertIn("guest_seconds", json.loads(payload))
                self.assertEqual(kinds[:2], [STATUS, FRAME])
                self.assertEqual(words[:64], list(range(words[0], words[0] + 64)))  # nothing lost or reordered

                def post(event, origin=None):
                    headers = {"Content-Type": "application/json", **({"Origin": origin} if origin else {})}
                    return json.loads(urlopen(Request(base + "/api/input", json.dumps(event).encode(), headers=headers), timeout=5).read())

                self.assertEqual(post({"type": "key", "index": 23, "down": True}), {"ok": True})
                for event, origin, code in (({"type": "pad", "index": 99, "value": 1}, None, 400),
                                            ({"type": "key", "index": 1, "down": True}, "https://example.invalid", 403)):
                    with self.assertRaises(HTTPError) as rejected:
                        post(event, origin)
                    self.assertEqual(rejected.exception.code, code)
                deadline = time.monotonic() + 5
                while not machine.log and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual([row[1:] for row in machine.log], [("key", 23, True)])
                self.assertTrue(urlopen(base + "/api/frame.png", timeout=5).read().startswith(b"\x89PNG"))
                stream.close()
            finally:
                panel.stopping = True
                runner.join(5)
                server.shutdown()

    def test_run_paces_guest_time_to_the_wall_clock(self):
        machine = Machine(); panel = Panel(machine, slice_ms=2, speed=1.0)
        runner = threading.Thread(target=panel.run, daemon=True); runner.start()
        time.sleep(0.5)
        panel.stopping = True; runner.join(5)
        self.assertGreater(machine.cpu.now, 0.3 * CYCLES_PER_SECOND)
        self.assertLess(machine.cpu.now, 0.7 * CYCLES_PER_SECOND)

    @unittest.skipUnless(shutil.which("node"), "Node is only needed to check browser JavaScript")
    def test_browser_script_draws_plays_and_releases_inputs(self):
        result = subprocess.run(["node", str(HERE / "tests/stock_ui_smoke.js")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
