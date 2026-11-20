#!/usr/bin/env python3
"""What SmplTrek 3.2.174 does with bytes from the panel MCU: `ADControllerUART::parse` (0xC161DF94) run in c6sim on
chosen byte streams. Read-only and simulated.

`parse(this)` drains the UART driver (`0xC161BAD8(this+12, &byte, 1, 0)`, 0 = a byte was read) and runs its state
machine (state at this+32). The tool feeds the drain from a list and puts a stand-in ADControllerDelegate at
this+20 whose slots record their calls: slot 0 (delegate, uart, byte) and slot 1 (delegate, uart, channel, value).
It reads back the stored channel values (this+36+2n) and the A1 bytes (this+70..75).

Usage (from the repository root; needs firmware/ and the work listing, as hw_compare.py):
  python3 -B analysis/panel_rx_map.py
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

UART, PARSE, READ = 0xC15019D0, 0xC161DF94, 0xC161BAD8
DELEGATE, VTABLE, SLOTS = 0xC0000100, 0xC0000140, 0xC0000180          # zero-filled DDR


class Session:
    def __init__(self):
        import c6sim
        import hw_compare
        import mmio_trace
        self.c6sim = c6sim
        self.t = mmio_trace.Trace(str(hw_compare.ROOT / hw_compare.PRODUCTS["smpltrek"]["image"]), "smpltrek")
        self.t.boot()
        self.t.state, self.t.regs = dict(self.t.boot_state.overlay), {}
        self.queue, self.events = [], []
        self.poke(UART + 20, DELEGATE)
        self.poke(DELEGATE, VTABLE)
        for k in range(4):
            self.poke(VTABLE + 4 * k, SLOTS + 4 * k)

        def read(m):
            if self.queue:
                m.mem.write(m.R["b4"], bytes([self.queue.pop(0)]))
                m.R["a4"] = 0
            else:
                m.R["a4"] = 1
            return m.R["b3"]

        def slot(k):
            def f(m):
                args = ("a6",) if k == 0 else ("a6", "b6")
                self.events.append((k,) + tuple(c6sim.s32(m.R.get(r, 0)) for r in args))
                return m.R["b3"]
            return f
        self.hooks = {a: c6sim.returns(0) for a in hw_compare.HOOKS}
        self.hooks[READ] = read
        for k in range(4):
            self.hooks[SLOTS + 4 * k] = slot(k)

    def poke(self, address, value):
        for i in range(4):
            self.t.state[address + i] = (value >> (8 * i)) & 0xFF

    def feed(self, data):
        """Delegate calls for these bytes: (0, byte) for slot 0, (1, channel, value) for slot 1. The parser's state
        carries over between calls, as in the app."""
        self.queue[:] = list(data)
        self.events.clear()
        self.t.run(PARSE, {"a4": UART}, hooks=self.hooks, max_cycles=500000)
        return list(self.events)

    def state(self):
        return self.t.state.get(UART + 32, 0)

    def channel(self, n):
        return self.t.state.get(UART + 36 + 2 * n, 0) | self.t.state.get(UART + 37 + 2 * n, 0) << 8

    def info(self):
        return [self.t.state.get(UART + 70 + i, 0) for i in range(6)]


STREAMS = [("B3 05 7F", [0xB3, 0x05, 0x7F]), ("B0 7F 7F", [0xB0, 0x7F, 0x7F]), ("BF 00 01", [0xBF, 0x00, 0x01]),
           ("A1 01 02 03 04 05 06", [0xA1, 1, 2, 3, 4, 5, 6]), ("B2 05 (incomplete)", [0xB2, 0x05]),
           ("then 7F", [0x7F]), ("B4 05 B5 01 02", [0xB4, 0x05, 0xB5, 0x01, 0x02]),
           ("90 C1 D2 E3 F4 80", [0x90, 0xC1, 0xD2, 0xE3, 0xF4, 0x80]), ("12 34 while idle", [0x12, 0x34])]


def main():
    s = Session()
    for name, data in STREAMS:
        print(f"{name}: delegate calls {s.feed(data)}, state {s.state()}")
    print("stored channels:", [s.channel(n) for n in range(16)])
    print("A1 bytes (+70..75):", s.info())


if __name__ == "__main__":
    main()
