#!/usr/bin/env python3
"""The SPI NOR command bytes of SmplTrek 3.2.174's `HAL::FlashMemoryDriver`, run in c6sim. Read-only and simulated.

The driver (`this+12` = its SPI driver object) talks to the flash only through the SPI object's vtable: slot 0
(A6 = 1 / 0: hold the chip select across the next transfers / release it), slot 1 (write B4[0..A6)), slot 2
(read A6 bytes into B4). This tool gives it a stand-in SPI object whose slots record those calls, answer reads
with zeros (so the status poll sees "not busy") and return the byte count, and runs `do_erase` (0xC15DF060),
`do_program` (0xC15DF2F4) and `do_read` (0xC15DF488). It groups the writes and reads between a hold and its
release into one transfer.

Argument order, from the code: do_erase(this, addr, len, id), do_program(this, addr, buf, len, id) (B6 is tested
as the length; the symbol file's prototype lists len before buf), do_read(this, addr, buf, len, id).

Limit: do_program and do_read go on after their first data transfer into a path that ends in the run-time
abort loop (0xC16AC864) under this stand-in (an unmodelled completion step); the command and address bytes of
that first transfer are what they send. Single-byte write-enables (06, sent without a hold) are reported apart.

Usage (from the repository root; needs firmware/ and the work listing, as hw_compare.py):
  python3 -B analysis/flash_cmd_map.py
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

DO_ERASE, DO_PROGRAM, DO_READ = 0xC15DF060, 0xC15DF2F4, 0xC15DF488
THIS, SPI_OBJ, VTABLE, SLOTS, BUF = 0xC0000400, 0xC0000500, 0xC0000600, 0xC0000700, 0xC0001000   # zero-filled DDR


class Session:
    def __init__(self):
        import c6sim
        import hw_compare
        import mmio_trace
        self.c6sim = c6sim
        self.t = mmio_trace.Trace(str(hw_compare.ROOT / hw_compare.PRODUCTS["smpltrek"]["image"]), "smpltrek")
        self.t.boot()
        self.calls = []
        self.hooks = {a: c6sim.returns(0) for a in hw_compare.HOOKS}
        for k in range(16):
            self.hooks[SLOTS + 4 * k] = self.slot(k)

    def slot(self, k):
        def f(m):
            b4, a6 = m.R.get("b4", 0), m.R.get("a6", 0)
            data = bytes(m.mem.read(b4, a6)) if k == 1 and 0 < a6 <= 8 else None
            self.calls.append((k, a6, data))
            m.R["a4"] = a6
            return m.R["b3"]
        return f

    def poke(self, address, value):
        for i in range(4):
            self.t.state[address + i] = (value >> (8 * i)) & 0xFF

    def run(self, fn, regs):
        """(returned normally, [transfers]); a transfer is a list of ('W', bytes or length) / ('R', length)."""
        self.t.state, self.t.regs = dict(self.t.boot_state.overlay), {}
        self.calls.clear()
        self.poke(THIS + 12, SPI_OBJ)
        self.poke(SPI_OBJ, VTABLE)
        for k in range(16):
            self.poke(VTABLE + 4 * k, SLOTS + 4 * k)
        try:
            self.t.run(fn, dict(regs, a4=THIS), hooks=self.hooks, max_cycles=300000)
            done = True
        except self.c6sim.SimError:
            done = False
        transfers, cur, held = [], [], False
        for k, n, data in self.calls:
            if k == 0:
                if held and cur:
                    transfers.append(cur)
                held, cur = n == 1, []
            else:
                item = ("W", data if data is not None else n) if k == 1 else ("R", n)
                if held:
                    cur.append(item)
                else:
                    transfers.append([item])
        if cur:
            transfers.append(cur)
        return done, transfers

    def erase(self, addr, length):
        return self.run(DO_ERASE, {"b4": addr, "a6": length, "b6": 0})

    def program(self, addr, length):
        return self.run(DO_PROGRAM, {"b4": addr, "a6": BUF, "b6": length, "a8": 0})

    def read(self, addr, length):
        return self.run(DO_READ, {"b4": addr, "a6": BUF, "b6": length, "a8": 0})


def text(transfers):
    return [" ".join(f"{d}[{v.hex(' ') if isinstance(v, bytes) else v}]" for d, v in tr) for tr in transfers]


def main():
    s = Session()
    for name, (done, tr) in (("erase 0x441000 + 0x11000", s.erase(0x441000, 0x11000)),
                             ("erase 0x450000 + 0x10000", s.erase(0x450000, 0x10000)),
                             ("program 0x441000, 300 bytes", s.program(0x441000, 300)),
                             ("read 0x441000, 300 bytes", s.read(0x441000, 300))):
        print(f"{name} ({'returned' if done else 'stopped in the abort path'}):")
        for line in text(tr):
            print("   ", line)


if __name__ == "__main__":
    main()
