#!/usr/bin/env python3
"""The line input PAD of SmplTrek 3.2.174, run in c6sim: which code turns it on and off, the pin and the settings
field it uses, and what it does to codec routing and the input planes. Read-only and simulated.

REC SRC 7/8 (LineSt) and 9/10 (LineMn) are the line sources without and with PAD. `rec_src_select` treats the two
members of each pair the same (rec_src_map.py). The PAD lives in the REC SRC page's handlers instead:

  0xC153EF40  value change within a source group (a4 = +1 / -1). For the line pairs it also sets the PAD:
              to 8 or 10 -> `pad_set(1)` (0xC158C088) and `pad_apply(1)` (0xC15F1290); to 7 or 9 -> both with 0
  0xC153EEA4  source-group change (a4 = +1 / -1): selects the group's first value; leaving 8 or 10 calls
              `pad_apply(0)`
  0xC158C088  pad_set(v): g_settings+0x24 = (v == 1), through the setter 0xC15953C8
  0xC158C644  pad_on(): g_settings+0x24 != 0 (getter 0xC1595418)
  0xC15F1290  pad_apply(v): v == 1 -> LINE1L / LINE1R each into its own ADC at 0 dB, both ADCs on, PGA 0, GP7[15]
              and GP5[11] low, GP7[14] high, GP1[3] low; otherwise only GP1[3] high
  0xC1649680  GP1[3] pin: 0 -> SET_DATA01 bit 19 (high), 1 -> CLR_DATA01 bit 19 (low). SPRUH79C Table 19-2: banks
              0 and 1 share SET_DATA01 0x01E26018 / CLR_DATA01 0x01E2601C, GP1[n] is bit 16 + n
  0xC158B780  part of the settings apply at start-up: pad_apply(pad_on())

The factory AUDIO TEST page (0xC16140EC, title string 0xC16BE7F9) names 16 input routes (pointer table copied to
0xC16ED2A8 at start-up) and shows the two current ones from 0xC16EFC18 / +4 as "L-" and "R-". The same numbers are
the routes of the input dispatcher 0xC15F1A84(adc, route) (a4 = 0 left ADC, 1 right; b4 = route), which that page and
0xC158D184 call. Route 8 "L LineIn PAD" and 13 "R LineIn PAD" are the only ones that drive GP1[3] low; see routes().

Readers of pad_on(): `audio_fill_input_block` (0xC159A6EC: PAD on forces the input planes to (1, 2), so even LineMn
with PAD records both slots), 0xC159A44C (returns 1 with PAD on, 3 with it off), 0xC158D184 (keeps GP1[3] high when
the PAD is off) and the REC SRC page drawing.

Usage (from the repository root; needs firmware/ and the work listings, as codec_map.py):
  python3 -B analysis/pad_map.py
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

SETTINGS = 0xC14FAC58
SRC, PAD = 0x10, 0x24
VALUE_CHANGE, GROUP_CHANGE = 0xC153EF40, 0xC153EEA4
PAD_APPLY, PAD_PIN, MODE = 0xC15F1290, 0xC1649680, 0xC159A44C
ROUTE = 0xC15F1A84
ROUTES = ["OFF", "Built-In MIC", "L HiZ Low", "L HiZ", "L HiZ High", "L D-Mic U-Low", "L D-Mic Low", "L LineIn",
          "L LineIn PAD", "R D-Mic U-Low", "R D-Mic", "R D-Mic High", "R LineIn", "R LineIn PAD", "L USB", "R USB"]
GPIO = {0x18: "SET_DATA01", 0x1C: "CLR_DATA01", 0x68: "SET_DATA45", 0x6C: "CLR_DATA45",
        0x90: "SET_DATA67", 0x94: "CLR_DATA67"}


def pins(log):
    """[(register, value)] GPIO data writes in order (SPRUH79C Table 19-2 names)."""
    return [(GPIO.get(a.address - 0x01E26000, hex(a.address)), a.value) for a in log
            if a.kind == "W" and 0x01E26000 <= a.address < 0x01E27000]


class Session:
    def __init__(self):
        import codec_map
        self.codec_map = codec_map
        self.s = codec_map.Session("smpltrek")
        self.t = self.s.t

    def word(self, address):
        return sum(self.t.state.get(address + i, 0) << (8 * i) for i in range(4))

    def poke(self, address, value):
        for i in range(4):
            self.t.state[address + i] = (value >> (8 * i)) & 0xFF

    def run(self, fn, a4, src=None, pad=None, b4=None):
        """(return value, codec writes, GPIO writes) of fn(a4[, b4]) after the stock audio start."""
        cm = self.codec_map
        self.t.run(cm.AUDIO_START, {"a4": cm.I2C0}, hooks=self.s.hooks, max_cycles=1500000)
        if src is not None:
            self.poke(SETTINGS + SRC, src)
        if pad is not None:
            self.poke(SETTINGS + PAD, pad)
        self.s.codec.clear()
        regs = {"a4": a4 & 0xFFFFFFFF} if b4 is None else {"a4": a4, "b4": b4}
        r, log = self.t.run(fn, regs, hooks=self.s.hooks, max_cycles=1500000)
        return r, list(self.s.codec), pins(log)

    def change(self, fn, src, delta):
        """(new source, g_settings+0x24, GP1[3] writes) for a REC SRC page step from `src`."""
        _, _, g = self.run(fn, delta, src=src, pad=1 if src in (8, 10) else 0)
        gp13 = [("high" if n == "SET_DATA01" else "low") for n, v in g if n in ("SET_DATA01", "CLR_DATA01")
                and v & (1 << 19)]
        return self.word(SETTINGS + SRC), self.word(SETTINGS + PAD), gp13

    def apply(self, v):
        _, codec, g = self.run(PAD_APPLY, v)
        return codec, g

    def pin(self, v):
        return self.run(PAD_PIN, v)[2]

    def routes(self):
        """{(adc, route): (codec writes, GPIO writes)} of the input dispatcher for both ADCs and all 16 routes."""
        return {(adc, r): self.run(ROUTE, adc, b4=r)[1:] for adc in (0, 1) for r in range(16)}

    def mode(self, src):
        return self.run(MODE, 0, src=src, pad=1 if src in (8, 10) else 0)[0]


def main():
    s = Session()
    for fn, name in ((VALUE_CHANGE, "value change"), (GROUP_CHANGE, "group change")):
        for src in range(7, 11):
            for d in (1, -1):
                new, pad, gp = s.change(fn, src, d)
                print(f"{name}: {src} {d:+d} -> source {new}, +0x24 {pad}, GP1[3] {gp or '-'}")
    for v in (0, 1):
        codec, g = s.apply(v)
        print(f"pad_apply({v}): codec {codec}; pins {[(n, hex(x)) for n, x in g]}")
        print(f"GP1[3] pin function({v}): {[(n, hex(x)) for n, x in s.pin(v)]}")
    print(f"0xC159A44C: {[(src, s.mode(src)) for src in (7, 8, 9, 10)]}")
    for (adc, r), (codec, g) in s.routes().items():
        print(f"route {r:2d} {ROUTES[r]:13s} {'left' if adc == 0 else 'right'} ADC: codec {codec}; "
              f"pins {[(n, hex(x)) for n, x in g]}")


if __name__ == "__main__":
    main()
