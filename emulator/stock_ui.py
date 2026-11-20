#!/usr/bin/env python3
"""Interactive panel for the unmodified stock firmware: live display, controls and audio.

Runs the stock SYSTEM image on the compiled C674x core at real-time pace and serves a local
web page (Linux, Windows and macOS browsers). Inputs are external ones only: key switches,
encoder quadrature phases and panel-MCU bytes on UART1. No guest function is hooked.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import heapq
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import queue
import signal
import struct
import sys
import threading
import time
from urllib.parse import urlsplit

import blocks
from build import WORK
from display import png

UI = Path(__file__).resolve().parent / "ui"
CYCLES_PER_SECOND = 372000000
FRAME, AUDIO, STATUS = 1, 2, 3
KEYS, ENCODERS, PADS = 48, 5, 15
# One completed 8N1 byte per 8000 DSP cycles matches stock's UART1 divisor.
UART_BYTE_CYCLES = 8000
# Stock polls the encoders from its 1 ms tick; two polls per phase keep every edge visible.
ENCODER_PHASE_CYCLES = 2 * CYCLES_PER_SECOND // 1000
ENCODER_PHASES = {1: (2, 0, 1, 3), -1: (1, 0, 2, 3)}
ASSETS = {"/": ("stock.html", "text/html; charset=utf-8"), "/stock.js": ("stock.js", "text/javascript; charset=utf-8"),
          "/stock.css": ("stock.css", "text/css; charset=utf-8")}


def integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer from {low} to {high}")
    return value


def message(kind, payload):
    return struct.pack("<BI", kind, len(payload)) + payload


class Panel:
    """Owns the machine on one thread; HTTP threads only queue inputs and read published data."""

    def __init__(self, stock, slice_ms=2, speed=1.0, state=None, compiled=False, labels="generic"):
        self.stock, self.cpu = stock, stock.cpu
        self.slice_cycles = integer(slice_ms, 1, 50, "slice_ms") * CYCLES_PER_SECOND // 1000
        if not 0.05 <= speed <= 8:
            raise ValueError("speed must be between 0.05 and 8")
        self.speed, self.state_directory = speed, state
        self.labels = labels
        self.inputs = queue.Queue()
        self.scheduled, self.sequence = [], 0
        self.encoder_free, self.uart_free = [0] * ENCODERS, 0
        self.clients, self.lock = [], threading.Lock()
        self.paused, self.fault, self.notice, self.stopping = False, None, None, False
        self.cycles = self.cpu.cycles()
        self.audio_seen = self.cpu.audio_tail(0)[2]
        self.audio_lost = 0
        self.frame, self.frame_info = self.cpu.oled_frame()
        self.keys, self.pads, self.power, self.power_manual = 0, [0] * PADS, False, False
        self.uart_seen, self.led_packet, self.leds = 0, [], [0] * 144
        self.rate = 0.0
        # Compiled blocks: hot code is compiled off this thread and installed here.
        self.block_pool = ThreadPoolExecutor(max_workers=1) if compiled else None
        self.block_job, self.block_sources, self.block_known, self.block_next = None, {}, set(), time.monotonic() + 1
        self.block_built = time.monotonic()
        if compiled:
            self.cpu.blocks(True, heat=True)
        self.status = self.describe()

    # ---- inputs (any thread) -------------------------------------------------------------
    def post(self, event):
        """Validate now, apply on the machine thread."""
        if not isinstance(event, dict):
            raise ValueError("input must be an object")
        kind = event.get("type")
        if kind == "key" and set(event) == {"type", "index", "down"} and type(event["down"]) is bool:
            integer(event["index"], 0, KEYS - 1, "key index")
        elif kind == "encoder" and set(event) == {"type", "index", "delta"}:
            integer(event["index"], 0, ENCODERS - 1, "encoder index")
            if integer(event["delta"], -8, 8, "encoder delta") == 0:
                raise ValueError("encoder delta must not be zero")
        elif kind == "pad" and set(event) == {"type", "index", "value"}:
            integer(event["index"], 0, PADS - 1, "pad index"); integer(event["value"], 0, 16383, "pad value")
        elif kind == "battery" and set(event) == {"type", "value"}:
            integer(event["value"], 0, 16383, "battery value")
        elif kind == "power" and set(event) == {"type", "down"} and type(event["down"]) is bool:
            pass
        elif kind == "control" and set(event) == {"type", "action"} and event["action"] in ("pause", "resume", "save"):
            pass
        else:
            raise ValueError("unknown input or invalid fields")
        self.inputs.put(dict(event))

    # ---- machine thread ------------------------------------------------------------------
    def at(self, cycle, action):
        self.sequence += 1
        heapq.heappush(self.scheduled, (cycle, self.sequence, action))

    def analogue(self, channel, value):
        # Panel MCU analogue report: status Bn, then the 14-bit value, low seven bits first.
        if self.stock.cpu.panel_stream_state()["enabled"]:   # the stream reports the level from its next round on
            self.stock.panel_level(channel, value)
            return
        start = max(self.cycles, self.uart_free)
        for offset, byte in enumerate((0xb0 | channel, value & 0x7f, value >> 7)):
            self.at(start + offset * UART_BYTE_CYCLES, lambda byte=byte: self.stock.uart_receive(1, bytes([byte])))
        self.uart_free = start + 3 * UART_BYTE_CYCLES

    def apply(self, event):
        kind = event["type"]
        if kind == "key":
            self.stock.key_input(event["index"], event["down"])
            self.keys = self.keys | 1 << event["index"] if event["down"] else self.keys & ~(1 << event["index"])
        elif kind == "encoder":
            index, step = event["index"], 1 if event["delta"] > 0 else -1
            start = max(self.cycles, self.encoder_free[index])
            for detent in range(abs(event["delta"])):
                for offset, phase in enumerate(ENCODER_PHASES[step]):
                    self.at(start + (detent * 4 + offset) * ENCODER_PHASE_CYCLES,
                            lambda phase=phase: self.stock.encoder_phase(index, phase))
            self.encoder_free[index] = start + abs(event["delta"]) * 4 * ENCODER_PHASE_CYCLES
        elif kind == "pad":
            self.pads[event["index"]] = event["value"]
            self.analogue(event["index"], event["value"])
        elif kind == "battery":
            self.analogue(15, event["value"])
        elif kind == "power":
            # GP3[0] is low while the power key is held. A manual press overrides the scripted hold.
            self.stock.power_release = None
            self.cpu.gpio_input(3, 0, not event["down"])
            self.stock.inputs.append(dict(cycles=self.cycles, type="power_key", down=event["down"]))
            self.power, self.power_manual = event["down"], True
        elif event["action"] == "save":
            self.save()
        else:
            self.paused = event["action"] == "pause"

    def save(self):
        if self.state_directory is None:
            raise ValueError("start with --state DIRECTORY to keep the card and flash")
        self.state_directory.mkdir(parents=True, exist_ok=True)
        for name, data in (("flash.img", self.cpu.nor_read(0) + self.cpu.nor_read(1)),
                           ("card.img", self.cpu.sd_read() if self.cpu.sd_state()["present"] else None),
                           ("frame.png", png(self.frame))):
            if data is not None:
                pending = self.state_directory / (name + ".pending")
                pending.write_bytes(data); pending.replace(self.state_directory / name)

    def leds_from(self, data):
        # C1 a b c value sets LED 48a + 8b + c (the stock panel_led_command packet).
        for byte in data:
            if byte == 0xc1:
                self.led_packet = [byte]
            elif self.led_packet:
                if byte & 0x80:
                    self.led_packet = []
                    continue
                self.led_packet.append(byte)
                if len(self.led_packet) == 5:
                    _, a, b, c, value = self.led_packet
                    if a < 3 and b < 6 and c < 8:
                        self.leds[48 * a + 8 * b + c] = value
                    self.led_packet = []

    def describe(self):
        forward = self.cpu.fast_forward_state()
        return dict(cycles=self.cycles, guest_seconds=self.cycles / CYCLES_PER_SECOND, rate=self.rate, speed=self.speed,
                    paused=self.paused, fault=self.fault, notice=self.notice, keys=f"{self.keys:012x}", pads=self.pads,
                    power_key=self.power if self.power_manual else self.stock.power_release is not None,
                    leds=bytes(self.leds).hex(), display_on=self.frame_info["on"], frames=self.frame_info["complete_frames"],
                    audio_lost_words=self.audio_lost, skipped_cycles=forward["skipped_cycles"],
                    compiled_blocks=self.cpu.block_state()["installed"] if self.block_pool else None,
                    checkpoints=[row["name"] for row in self.stock.checkpoints][-3:],
                    conditional=self.cpu.reserved_low_state()["enabled"] or self.cpu.reserved_low_read_state()["enabled"],
                    persistent=self.state_directory is not None, labels=self.labels,
                    panel_stream=self.cpu.panel_stream_state()["enabled"])

    def publish(self, data, droppable=False, frame=False):
        """Queue for every client. A droppable message skips a congested client; a skipped
        display frame is remembered and sent by observe() once that client has caught up."""
        with self.lock:
            for client in self.clients[:]:
                try:
                    if droppable and client.qsize() > 64:
                        client.frame_owed |= frame
                    else:
                        client.put_nowait(data)
                        client.frame_owed &= not frame
                except queue.Full:
                    self.clients.remove(client); client.dead = True

    def subscribe(self):
        client = queue.Queue(maxsize=512); client.dead = False; client.frame_owed = False
        with self.lock:
            client.put(message(STATUS, json.dumps(self.status).encode()))
            client.put(message(FRAME, self.frame))
            self.clients.append(client)
        return client

    def unsubscribe(self, client):
        with self.lock:
            if client in self.clients:
                self.clients.remove(client)

    def step(self):
        """Apply due inputs, run one slice and publish what it produced."""
        while True:
            try:
                event = self.inputs.get_nowait()
            except queue.Empty:
                break
            try:
                self.apply(event)
                self.notice = "Card and flash saved" if event.get("action") == "save" else None
            except (ValueError, RuntimeError, OSError) as error:
                self.notice = f"Input not applied: {error}"
        while self.scheduled and self.scheduled[0][0] <= self.cycles:
            heapq.heappop(self.scheduled)[2]()
        if self.paused or self.fault:
            return False
        budget = self.slice_cycles
        if self.scheduled:
            budget = max(1, min(budget, self.scheduled[0][0] - self.cycles))
        try:
            state = self.stock.step(budget)
        except RuntimeError as error:  # CoreFault: the guest state is kept for inspection.
            self.fault = str(error); self.cycles = self.cpu.cycles()
            return False
        self.cycles = state["cycles"]
        if state["status"] not in ("budget", "breakpoint"):
            self.fault = f'emulation stopped: {state["status"]} at PC {state["pc"]:#010x}'
        data, slot, self.audio_seen, lost = self.cpu.audio_tail(self.audio_seen)
        self.audio_lost += lost
        if data:
            self.publish(message(AUDIO, bytes([slot]) + data), droppable=True)
        return True

    def observe(self):
        frame, self.frame_info = self.cpu.oled_frame()
        if frame != self.frame:
            self.frame = frame
            self.publish(message(FRAME, frame), droppable=True, frame=True)
        else:
            with self.lock:
                for client in self.clients:
                    if client.frame_owed and client.qsize() <= 64:
                        client.put_nowait(message(FRAME, frame)); client.frame_owed = False
        sent, self.uart_seen = self.cpu.uart_sent(1, self.uart_seen)
        self.leds_from(sent)

    def compile_round(self, now):
        """Start a background build of newly hot code, or install the one that finished."""
        if self.block_job is not None:
            if not self.block_job.done():
                return
            job, self.block_job = self.block_job, None
            try:
                blocks.install(self.cpu, job.result(), self.block_sources)
            except (ValueError, OSError, StopIteration) as error:
                self.notice, self.block_pool = f"Compiled blocks stopped: {str(error)[:200]}", None
                return
            self.block_known.update(self.block_sources)
            self.block_next, self.block_built = now + 1, now
        elif now >= self.block_next:
            # Blocks compiled in an earlier run come back without a compiler (blocks.build), so rounds are
            # frequent; a round for only a few new entries waits until five seconds have passed without one.
            self.block_sources = blocks.collect(self.cpu, known=self.block_known)
            if len(self.block_sources) < (8 if now - self.block_built < 5 else 1):
                self.block_next = now + 1
            else:
                self.block_job = self.block_pool.submit(blocks.build, self.cpu.work, self.block_sources, max(1, (os.cpu_count() or 2) // 2))

    def run(self):
        wall, guest = time.monotonic(), self.cycles
        observed = reported = wall
        rate_wall, rate_guest = wall, self.cycles
        while not self.stopping:
            ran = self.step()
            now = time.monotonic()
            if now - observed >= 1 / 30:
                self.observe(); observed = now
            if now - reported >= 0.25:
                if now > rate_wall:
                    self.rate = (self.cycles - rate_guest) / CYCLES_PER_SECOND / (now - rate_wall)
                rate_wall, rate_guest, reported = now, self.cycles, now
                if self.block_pool:
                    self.compile_round(now)
                self.status = self.describe()
                self.publish(message(STATUS, json.dumps(self.status).encode()))
            if not ran:
                time.sleep(0.02)
                wall, guest = time.monotonic(), self.cycles
                continue
            ahead = (self.cycles - guest) / CYCLES_PER_SECOND / self.speed - (now - wall)
            if ahead > 0.001:
                time.sleep(ahead)
            elif ahead < -0.25:
                # The host cannot keep up: restart pacing here instead of chasing lost time.
                wall, guest = now, self.cycles


def make_server(panel, port=8766):
    class Handler(BaseHTTPRequestHandler):
        disable_nagle_algorithm = True

        def log_message(self, *_):
            pass

        def send(self, data, mime="application/json", code=200):
            if mime == "application/json":
                data = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.common_headers()
            self.wfile.write(data)

        def common_headers(self):
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()

        def local(self):
            hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            origin = self.headers.get("Origin")
            if self.headers.get("Host") not in hosts or (origin and urlsplit(origin).netloc not in hosts):
                self.send({"error": "use the local emulator address"}, code=403)
                return False
            return True

        def do_GET(self):
            if not self.local():
                return
            path = urlsplit(self.path).path
            if path in ASSETS:
                name, mime = ASSETS[path]
                self.send((UI / name).read_bytes(), mime)
            elif path == "/api/state":
                self.send(panel.status)
            elif path == "/api/frame.png":
                self.send(png(panel.frame), "image/png")
            elif path == "/stream":
                self.stream()
            else:
                self.send({"error": "not found"}, code=404)

        def stream(self):
            # One long response, delimited by the connection closing: display frames, audio
            # words and status as they are produced.
            client = panel.subscribe()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.common_headers()
                while not client.dead and not panel.stopping:
                    try:
                        self.wfile.write(client.get(timeout=1))
                    except queue.Empty:
                        self.wfile.write(message(STATUS, json.dumps(panel.status).encode()))
            except OSError:
                pass
            finally:
                panel.unsubscribe(client)

        def do_POST(self):
            if not self.local():
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if self.headers.get_content_type() != "application/json" or not 1 <= length <= 4096:
                    raise ValueError("expected a JSON request of at most 4 KiB")
                body = json.loads(self.rfile.read(length))
                if urlsplit(self.path).path != "/api/input":
                    self.send({"error": "not found"}, code=404)
                    return
                panel.post(body)
                self.send({"ok": True})
            except (ValueError, KeyError, TypeError, UnicodeDecodeError) as error:
                self.send({"error": str(error)}, code=400)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def main(argv=None):
    from stock import DEFAULT_FIRMWARE, Stock
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--firmware", type=Path, default=DEFAULT_FIRMWARE)
    parser.add_argument("--profile", choices=("smpltrek", "lofi12", "cydrums"), default="smpltrek",
                        help="update checksum profile; lofi12 and cydrums run a Lofi-12 XT or CyDrums image on the same board model")
    parser.add_argument("--labels", choices=("generic", "sampler", "lofi", "drum"), default="generic",
                        help="panel printing a fresh browser starts with: generic (F1-F8 and pad numbers), or the sampler, "
                             "lo-fi sampler or drum synth printing; the page can switch it")
    parser.add_argument("--card", type=Path, help="SD card image (power of two, 2 MiB to 1 GiB); a private copy is used")
    parser.add_argument("--flash", type=Path, help="32 MiB SPI NOR image (CS0 then CS1); a private copy is used")
    parser.add_argument("--state", type=Path, help="directory whose card.img/flash.img are loaded when present and "
                        "written by Save and on exit, so settings and projects persist between runs")
    parser.add_argument("--port", type=int, default=8766, help="loopback port; 0 chooses a free one")
    parser.add_argument("--speed", type=float, default=1.0, help="pace relative to real time (audio expects 1.0)")
    parser.add_argument("--slice-ms", type=int, default=2, help="guest milliseconds per emulation slice")
    parser.add_argument("--power-held-ms", type=int, default=600, help="initial power-key hold in guest milliseconds")
    parser.add_argument("--strict", action="store_true",
                        help="keep stores to and reads of reserved low memory as faults; stock then stops in USB start-up")
    parser.add_argument("--panel-stream", action=argparse.BooleanOptionalAction, default=True,
                        help="the panel MCU reports every pad and the battery continuously, as on the unit (about 4194 "
                             "messages a second), which pads need to play; on by default. --no-panel-stream sends a report "
                             "only when a level changes and runs about a third faster")
    parser.add_argument("--no-fast-forward", action="store_true", help="execute every repeated idle period")
    parser.add_argument("--blocks", action=argparse.BooleanOptionalAction, default=True,
                        help="compile hot guest code with the host C++ compiler while running (default; --no-blocks interprets everything)")
    parser.add_argument("--work", type=Path, default=WORK)
    args = parser.parse_args(argv)
    def interrupt(*_):
        raise KeyboardInterrupt

    try:
        if not 0 <= args.port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        signal.signal(signal.SIGTERM, interrupt)  # A plain kill also saves --state.
        card, flash = args.card, args.flash
        if args.state:
            card = card or (args.state / "card.img" if (args.state / "card.img").exists() else None)
            flash = flash or (args.state / "flash.img" if (args.state / "flash.img").exists() else None)
        with Stock(args.firmware, args.work, args.power_held_ms, flash, card=card,
                   reserved_low_writes=not args.strict, reserved_low_reads=not args.strict, profile=args.profile,
                   panel_stream=args.panel_stream) as stock:
            stock.cpu.fast_forward(not args.no_fast_forward)
            panel = Panel(stock, args.slice_ms, args.speed, args.state, args.blocks, args.labels)
            with make_server(panel, args.port) as server:
                threading.Thread(target=server.serve_forever, daemon=True).start()
                print(f"SmplTrek stock panel: http://127.0.0.1:{server.server_port}", flush=True)
                print("Ctrl-C stops the emulator." + (f" Card and flash are kept in {args.state}." if args.state else ""), flush=True)
                try:
                    panel.run()
                finally:
                    panel.stopping = True
                    if args.state:
                        panel.save()
                    server.shutdown()
        return 0
    except KeyboardInterrupt:
        return 0
    except (ValueError, RuntimeError, OSError) as error:
        print(f"stock panel: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
