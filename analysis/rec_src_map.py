#!/usr/bin/env python3
"""What each REC SRC value does in SmplTrek 3.2.174, run in c6sim: codec ADC routing, board pins, the input gain
settings and which I2S slot each input plane takes. Read-only and simulated.

`rec_src_select` (`0xC158B990`, source in A4) stores the source in g_settings+0x10 and, per source, sets the INPUT L
mode (+0x14, through `input_l_gain_apply`), the INPUT R level (+0x18, through `input_r_gain_apply`) and the two
input-plane selectors (+0x1C plane 0, +0x20 plane 1; 1 = slot 0 / even words, 2 = slot 1 / odd words, read by
`audio_fill_input_block`, see audio_slot_map.py). The recorded-file prefix comes from `0xC156C804` (strings
`0xC16BD534`..), which gives the names: 0 BltInMic, 1-3 Gtr, 4-6 DyMic, 7-8 LineSt, 9-10 LineMn, 11 USB, 12-25 ReSmp.

Codec writes are recorded at codec_write (codec_map.Session, after the stock audio start), and the end state of the
ADC input registers is decoded against SLAS509G (Tables 10-23..10-32: 15/16 PGA gain, 17/18 MIC3 to left/right ADC,
19/22 LINE1L/LINE1R to their own ADC with the ADC power bit D2, 21/24 the cross connections). GPIO pins are the
SET_DATA / CLR_DATA writes, in order.

The input monitor mix (`audio_mix_input_monitor` 0xC159AA54) is the one place a source changes what is heard:
with the built-in mic (source 0) it mixes the input only while GP3[8] reads high (0xC16493F8, pin != 0); other sources
do not read GP3[8]. monitor_gate() runs it with monitoring on and the pin and the three later conditions
(0xC15C5B00, 0xC15C5228, 0xC15C5910, each must return 0) hooked.

Usage (from the repository root; needs firmware/ and the work listings, as codec_map.py):
  python3 -B analysis/rec_src_map.py
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

SELECT = 0xC158B990
PREFIX = 0xC156C804
GET_SRC = 0xC158BC30
MONITOR, MONITOR_ON, GP3_8, MIX_LEVEL = 0xC159AA54, 0xC158B954, 0xC16493F8, 0xC158B7D8
MONITOR_CONDITIONS = (0xC15C5B00, 0xC15C5228, 0xC15C5910)
SETTINGS = 0xC14FAC58
FIELDS = {"src": 0x10, "l_mode": 0x14, "r_level": 0x18, "plane0": 0x1C, "plane1": 0x20}
START = {15: 0x00, 16: 0x00, 17: 0xFF, 18: 0xFF, 19: 0x84, 21: 0xF8, 22: 0x84, 24: 0xF8}   # stock start-up values


def adc_inputs(regs):
    """{'left': [...], 'right': [...]} sources and power of each ADC from the end-state registers (SLAS509G)."""
    def level(v):
        return None if v == 0xF else f"{-1.5 * v:g} dB".replace("-0 dB", "0 dB")
    out = {}
    for side, own, cross, mic, power_reg, pga in (("left", 19, 21, 17, 19, 15), ("right", 22, 24, 18, 22, 16)):
        src = []
        own_name, cross_name = ("LINE1L", "LINE1R") if side == "left" else ("LINE1R", "LINE1L")
        for name, v in ((own_name, regs[own] >> 3 & 0xF), (cross_name, regs[cross] >> 3 & 0xF),
                        ("MIC3L", regs[mic] >> 4), ("MIC3R", regs[mic] & 0xF)):
            if level(v):
                src.append(f"{name} {level(v)}")
        out[side] = {"powered": bool(regs[power_reg] & 4), "inputs": src, "pga_db": (regs[pga] & 0x7F) / 2}
    return out


class Session:
    def __init__(self):
        import codec_map
        self.s = codec_map.Session("smpltrek")
        self.t = self.s.t

    def word(self, address):
        return sum(self.t.state.get(address + i, 0) << (8 * i) for i in range(4))

    def prefix(self, src):
        """The recorded-file prefix 0xC156C804 returns for this source (C string)."""
        import c6sim
        r, _ = self.t.run(PREFIX, {}, hooks={**self.s.hooks, GET_SRC: c6sim.returns(src)})
        mem, out = self.t.last_machine.mem, b""
        while not out.endswith(b"\0"):
            out += bytes(mem.read(r + len(out), 1))
        return out[:-1].decode()

    def select(self, src):
        codec, pins = self.s.call(SELECT, {"a4": src}, base=False)
        regs = dict(START)
        for r, v in codec:
            regs[r] = v
        return {"name": self.prefix(src), "fields": {k: self.word(SETTINGS + o) for k, o in FIELDS.items()},
                "codec": codec, "adc": adc_inputs(regs), "pins": pins}

    def monitor_gate(self, src, gp3_8):
        """True if the monitor mix goes on to the mix (its level getter) for this source and GP3[8] level."""
        import c6sim
        seen = []

        def mix(m):
            seen.append(1)
            m.R["a4"] = 0
            return m.R["b3"]
        hooks = {**self.s.hooks, GET_SRC: c6sim.returns(src), MONITOR_ON: c6sim.returns(1),
                 GP3_8: c6sim.returns(gp3_8), MIX_LEVEL: mix,
                 **{a: c6sim.returns(0) for a in MONITOR_CONDITIONS}}
        self.t.state = dict(self.t.boot_state.overlay)
        try:
            self.t.run(MONITOR, {"a4": 0xC0040000}, hooks=hooks, max_cycles=300000)
        except c6sim.SimError:      # past the level getter the mix reads a block the test does not set up
            pass
        return bool(seen)

    def all(self):
        return {src: self.select(src) for src in range(26)}


def main():
    s = Session()
    for src, r in s.all().items():
        f = r["fields"]
        adc = "; ".join(f"{side} ADC {'on' if a['powered'] else 'off'} {'+'.join(a['inputs']) or '-'} PGA {a['pga_db']:g} dB"
                        for side, a in r["adc"].items())
        print(f"{src:2d} {r['name']:8s} L mode {f['l_mode']:2d}, R level {f['r_level']:2d}, planes ({f['plane0']}, "
              f"{f['plane1']}) | {adc} | pins {' '.join(r['pins'])}")
    for src in (0, 7):
        print(f"monitor mix, source {src}: GP3[8] low {s.monitor_gate(src, 0)}, high {s.monitor_gate(src, 1)}")


if __name__ == "__main__":
    main()
