"""External-input scripting and observations of the unmodified 3.2.174 stock guest.

This harness uses GPIO/UART inputs, guest cycle budgets and read-only watches. It never calls
guest functions directly or changes guest RAM/registers to navigate the UI.
"""
import json
from pathlib import Path
import struct

from build import digest
from display import png

HELD, CONTROLLER, MODAL, TEMPO = 0xc1501df0, 0xc16f367c, 0xc16f3680, 0xc1500cf4
HOME = 0xc15037f0


class StockSession:
    def __init__(self, stock, output, slice_cycles=1000000):
        self.stock, self.output, self.slice_cycles = stock, Path(output), slice_cycles
        self.output.mkdir(parents=True, exist_ok=True)
        self.observations = []
        self.report = None

    def word(self, address, size=4):
        return int.from_bytes(self.stock.cpu.read(address, size), "little")

    def advance(self, cycles):
        self.report = self.stock.run(cycles, self.slice_cycles)
        if self.report["error"]:
            self.save("fault")
            raise RuntimeError(self.report["error"])
        return self.report

    def wait(self, predicate, budget=1000000000, step=20000000):
        end = self.stock.cpu.state()["cycles"] + budget
        while not predicate():
            remaining = end - self.stock.cpu.state()["cycles"]
            if remaining <= 0:
                self.capture("wait-budget")
                raise RuntimeError("stock UI predicate did not become true within the guest cycle budget")
            self.advance(min(step, remaining))

    def key(self, key, label=None):
        self.stock.key_input(key, True)
        self.advance(40000000)
        down = self.word(HELD, 8)
        self.stock.key_input(key, False)
        self.advance(40000000)
        up = self.word(HELD, 8)
        if not down & (1 << key) or up & (1 << key):
            self.save("key-not-scanned")
            raise RuntimeError(f"stock scanner did not observe press/release of key {key}")
        if label:
            return self.capture(label)

    def turn(self, delta=1, encoder=4, label=None):
        for _ in range(abs(delta)):
            for phase in ((2, 0, 1, 3) if delta > 0 else (1, 0, 2, 3)):
                self.stock.encoder_phase(encoder, phase)
                self.advance(10000000)
        if label:
            return self.capture(label)

    def capture(self, label):
        raw, audio = self.stock.cpu.audio_output()
        frame, oled = self.stock.cpu.oled_frame()
        words = struct.unpack("<" + "i" * (len(raw) // 4), raw)
        row = dict(label=label, cycles=self.stock.cpu.state()["cycles"], held=self.word(HELD, 8),
                   controller=self.word(CONTROLLER), modal=self.word(MODAL), tempo_x10=self.word(TEMPO),
                   frame_sha256=digest(frame), complete_frames=oled["complete_frames"],
                   audio={**audio, "nonzero_words": sum(bool(v) for v in words), "sha256": digest(raw)})
        self.observations.append(row)
        (self.output / f"{label}.bin").write_bytes(frame)
        (self.output / f"{label}.png").write_bytes(png(frame))
        (self.output / f"{label}.pcm32").write_bytes(raw)
        self.save("result")
        print(f'{label}: cycle {row["cycles"]}, tempo {row["tempo_x10"] / 10:g}', flush=True)
        return row

    def save(self, label="result"):
        if self.report is not None:
            report = {**self.report, "observations": self.observations, "inputs": self.stock.inputs.copy()}
            (self.output / f"{label}.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
