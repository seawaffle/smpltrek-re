#!/usr/bin/env python3
"""Which I2S slot (32-bit word of the McASP DMA buffers) each audio plane of the Sonicware apps uses, run in c6sim.
Read-only and simulated.

Transmit, all three products: `audio_block_process` (SmplTrek `0xC1620FB4`) zeroes the float block, calls the render
callback and converts `sample * 2^31` to int32 into the free TX buffer. Here the callback is a hook that fills the
first plane (block +16) with 0.25 and the second (block +16 + 4 * frames) with -0.5; the report gives the first
words of the TX buffer the function wrote.

Receive, SmplTrek only (the other products' engines are their own code): `audio_fill_input_block` (`0xC159A6EC`)
fills the two planes of `g_audio_in_block` from the RX buffer named by `audio_get_io()`+16. Each plane has a source
selector read from the settings block: plane 0 from g_settings+0x1C, plane 1 from +0x20, and +0x24 non-zero forces
(1, 2). Selector 1 = even words (slot 0), 2 = odd words (slot 1), anything else = silence. The settings are poked,
not hooked, so the field offsets are checked too. The RX buffer holds 0x10000000 in slot 0 and 0x40000000 in slot 1
(0.125 and 0.5 after the 2^-31 scale).

Usage (from the repository root; needs firmware/ and the work listings and match files, as hw_compare.py):
  python3 -B analysis/audio_slot_map.py
"""
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

BLOCK_PROCESS = 0xC1620FB4      # audio_block_process (SmplTrek addresses; the others through hw_compare)
FILL_INPUT = 0xC159A6EC         # audio_fill_input_block, SmplTrek only
GET_IO = 0xC1621688             # audio_get_io, returns the I/O record; +4 frames, +16 current RX buffer
SETTINGS = 0xC14FAC58           # g_settings, SmplTrek
SEL_L, SEL_R, SEL_STEREO = 0x1C, 0x20, 0x24
IN_BLOCK = 0xC16DEF70           # g_audio_in_block: +16 plane 0, +528 plane 1
RX_TEST = 0xC0010000            # RX buffer for the test (DDR, unused at this point)
CALLBACK = 0xC0001000           # address of the hooked render callback
SLOT0, SLOT1 = 0x10000000, 0x40000000


def _f(word):
    return struct.unpack("<f", struct.pack("<I", word))[0]


class Session:
    def __init__(self, key):
        import c6sim
        import hw_compare
        import mmio_trace
        self.c6sim = c6sim
        self.key = key
        self.p = hw_compare.Product(key)
        self.t = mmio_trace.Trace(str(hw_compare.ROOT / self.p.cfg["image"]), key)
        self.t.boot()
        self.hooks = {}
        for a in hw_compare.HOOKS:
            if self.p.function(a) is not None:
                self.hooks[self.p.function(a)] = c6sim.returns(1 if a == 0xC16A1BF0 else 0)

    def word(self, address):
        return sum(self.t.state.get(address + i, 0) << (8 * i) for i in range(4))

    def poke(self, address, value):
        for i in range(4):
            self.t.state[address + i] = (value >> (8 * i)) & 0xFF

    def _callback_slot(self, fn):
        """The render-callback slot: the B14 word audio_block_process calls through (ldw *+b14(n), then b)."""
        import re
        listing = (Path(__file__).resolve().parents[1] / self.p.cfg["listing"]).read_text().splitlines()
        start = next(i for i, l in enumerate(listing) if l.startswith(f"{fn:08x}:"))
        for line in listing[start:start + 60]:
            m = re.search(r"ldw \.D2T2 \*\+b14\((\d+)\),b0", line)
            if m:
                return self.t.boot_state.cfg["b14"] + int(m.group(1))
        raise RuntimeError("callback slot not found")

    def tx(self):
        """(frames, first four TX words) with plane 0 = 0.25 and plane 1 = -0.5."""
        fn = self.p.function(BLOCK_PROCESS)
        self.t.state = dict(self.t.boot_state.overlay)
        self.t.regs = {}
        self.poke(self._callback_slot(fn), CALLBACK)
        seen = {}

        def callback(m):
            block = m.R["a4"]
            n = m.mem.word(block + 4)
            seen["n"] = n
            for i in range(n):
                m.mem.write(block + 16 + 4 * i, struct.pack("<f", 0.25))
                m.mem.write(block + 16 + 4 * n + 4 * i, struct.pack("<f", -0.5))
            return m.R["b3"]

        before = dict(self.t.state)
        self.t.run(fn, {}, hooks={**self.hooks, CALLBACK: callback}, max_cycles=3000000)
        written = sorted(a for a in self.t.state if a < 0xC0000000 and self.t.state[a] != before.get(a, 0))
        buf = written[0] & ~3
        return seen["n"], [self.word(buf + 4 * k) for k in range(4)]

    def rx(self, sel_l, sel_r, stereo):
        """(plane 0, plane 1) first samples for the given selector settings (SmplTrek)."""
        assert self.key == "smpltrek"
        self.t.state = dict(self.t.boot_state.overlay)
        self.t.regs = {}
        io, _ = self.t.run(GET_IO, {}, hooks=self.hooks)
        self.poke(io + 4, 128)
        self.poke(io + 16, RX_TEST)
        for k in range(128):
            self.poke(RX_TEST + 8 * k, SLOT0)
            self.poke(RX_TEST + 8 * k + 4, SLOT1)
        for off, v in ((SEL_L, sel_l), (SEL_R, sel_r), (SEL_STEREO, stereo)):
            self.poke(SETTINGS + off, v)
        self.t.run(FILL_INPUT, {"a4": io}, hooks=self.hooks, max_cycles=3000000)
        return round(_f(self.word(IN_BLOCK + 16)), 6), round(_f(self.word(IN_BLOCK + 528)), 6)

    def rx_table(self):
        return {(l, r, s): self.rx(l, r, s) for s in (0, 1) for l in range(3) for r in range(3)}


def main():
    import hw_compare
    for key in hw_compare.PRODUCTS:
        n, words = Session(key).tx()
        print(f"{key}: TX frames {n}, words 0-3 {[f'{w:#010x}' for w in words]}"
              "  (plane 0 = 0.25 -> 0x20000000, plane 1 = -0.5 -> 0xC0000000)")
    s = Session("smpltrek")
    print("SmplTrek RX (sel+0x1C, sel+0x20, +0x24) -> (plane 0, plane 1); slot 0 = 0.125, slot 1 = 0.5")
    for k, v in s.rx_table().items():
        print(f"  {k} -> {v}")


if __name__ == "__main__":
    main()
