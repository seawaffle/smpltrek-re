#!/usr/bin/env python3
"""Every codec function of the Sonicware apps, run in c6sim in SmplTrek 3.2.174, Lofi-12 XT 1.5.205 and CyDrums 1.1.84,
with each (register, value) it writes decoded against the TI TLV320AIC3106 data sheet (SLAS509G, section 10.6 register
map, tables cited per register below). Read-only and simulated.

How it runs: each product is started (sim_boot), then the stock SYSCFG unlock, board set-up and audio start
(`0xC1621574`) run once, so the codec functions' shadow bytes for page-0 registers 19 and 22 (SmplTrek `0xC1502D6D`,
`0xC1502D6F`; the routing functions read-modify-write them) hold the start-up values. Before each call the audio start
is run again, so every call sees the start-up state. Codec writes are recorded at `codec_write` (hw_compare.CODEC_WRITE)
as (register, value); the I2C bytes themselves are interrupt-driven and are not simulated. GPIO pins are recorded from
SET_DATA / CLR_DATA writes (bank pair n at 0x01E26018 + 0x28n / +0x1C), as +GPb[p] (driven high) or -GPb[p] (low).

Usage (from the repository root, needs firmware/ and the work listings and match files, as hw_compare.py):
  python3 -B analysis/codec_map.py              # SmplTrek: every function, decoded
  python3 -B analysis/codec_map.py --compare    # also Lofi-12 XT and CyDrums, report differences
  python3 -B analysis/codec_map.py --decode 41=0x50 86=0x0B
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

# --- decoder (data sheet SLAS509G, Rev. G) -------------------------------------------------------------------------

LEVEL = ["0 dB", "-1.5 dB", "-3 dB", "-4.5 dB", "-6 dB", "-7.5 dB", "-9 dB", "-10.5 dB", "-12 dB"]


def _level(n):
    """ADC-mixer input level field (Tables 10-25..10-32): 0-8 = 0..-12 dB, 15 = not connected, else reserved."""
    return "not connected" if n == 15 else (LEVEL[n] if n < len(LEVEL) else f"reserved {n}")


def _route(name):
    """Output-mixer routing registers (Tables 10-54..10-101): D7 routed, D6-D0 volume step (Table 10-53, -0.5 dB/step
    at the top of the range)."""
    def d(v):
        return f"{name}: {'routed' if v & 0x80 else 'not routed'}, volume step {v & 0x7F}" + \
            (" (0 dB)" if v & 0x7F == 0 else "")
    return d


def _outlevel(name, power_rw=True):
    """Output level registers 51/58/65/72 (HP drivers, D0 power R/W) and 86/93 (line drivers, D1/D0 read-only status,
    Table 10-95/10-102)."""
    def d(v):
        lv = v >> 4
        s = f"{name}: level {lv} dB" if lv <= 9 else f"{name}: level reserved {lv}"
        s += ", unmuted" if v & 8 else ", muted"
        if power_rw:
            s += ", powered" if v & 1 else ", not powered"
            s += ", high-Z when down" if v & 4 else ", weak VCM when down"
        elif v & 3:
            s += f" (bits 1:0 = {v & 3} written to read-only status bits)"
        return s
    return d


def _adc_line(src, adc, power_bit):
    def d(v):
        s = f"{src} -> {adc} ADC: {'differential' if v & 0x80 else 'single-ended'}, {_level((v >> 3) & 15)}"
        if power_bit:
            s += f", {adc} ADC channel {'powered' if v & 4 else 'powered down'}, soft-step {v & 3}"
        elif v & 7:
            s += f" (reserved bits 2:0 = {v & 7})"
        return s
    return d


def _mic3(adc):
    return lambda v: f"MIC3L -> {adc} ADC {_level(v >> 4)}; MIC3R -> {adc} ADC {_level(v & 15)}"


def _pll_a(v):
    q = (v >> 3) & 15
    return f"PLL {'on' if v & 0x80 else 'off'}, Q = {16 + q if q < 2 else q}, P = {(v & 7) or 8}"


def _hpf(v):
    names = ["off", "0.0045 fs", "0.0125 fs", "0.025 fs"]
    return f"ADC high-pass left {names[v >> 6]}, right {names[(v >> 4) & 3]}; DAC effects/de-emphasis bits {v & 15:04b}"


def _dac_path(v):
    paths = {0: "DAC_x1 (mixer)", 1: "DAC_x3 (direct to line driver)", 2: "DAC_x2 (direct to HP driver)", 3: "reserved"}
    return f"left DAC -> {paths[v >> 6]}, right DAC -> {paths[(v >> 4) & 3]}, volume mode {v & 3}"


def _pop(v):
    on = ["0 us", "10 us", "100 us", "1 ms", "10 ms", "50 ms", "100 ms", "200 ms", "400 ms", "800 ms", "2 s", "4 s"]
    ramp = ["0 ms", "1 ms", "2 ms", "4 ms"]
    return f"driver power-on delay {on[v >> 4] if v >> 4 < 12 else 'reserved'}, ramp step {ramp[(v >> 2) & 3]}, " \
           f"weak VCM from {'bandgap' if v & 2 else 'AVDD divider'}"


PAGE0 = {   # register: (name, decoder); table numbers from SLAS509G section 10.6
    0: ("page select (T10-8)", lambda v: f"page {v & 1}"),
    1: ("software reset (T10-9)", lambda v: "reset" if v & 0x80 else "no-op"),
    2: ("sample rate select (T10-10)", lambda v: f"ADC fs(ref)/{1 + (v >> 4) / 2:g}, DAC fs(ref)/{1 + (v & 15) / 2:g}"),
    3: ("PLL A (T10-11)", _pll_a),
    4: ("PLL B (T10-12)", lambda v: f"J = {v >> 2}"),
    5: ("PLL C, D bits 13:6 (T10-13)", lambda v: f"D high byte {v}"),
    6: ("PLL D, D bits 5:0 (T10-14)", lambda v: f"D low bits {v >> 2}"),
    7: ("datapath (T10-15)", lambda v: f"fs(ref) {'44.1' if v & 0x80 else '48'} kHz, dual-rate ADC {v >> 6 & 1} DAC "
                                       f"{v >> 5 & 1}, left DAC plays {['off', 'left', 'right', 'mono'][v >> 3 & 3]}, "
                                       f"right DAC plays {['off', 'right', 'left', 'mono'][v >> 1 & 3]}"),
    8: ("serial interface A (T10-16)", lambda v: f"BCLK {'out' if v & 0x80 else 'in'}, WCLK {'out' if v & 0x40 else 'in'}"
                                                 f", DOUT 3-state {v >> 5 & 1}, clocks run when powered down {v >> 4 & 1}"
                                                 f", 3-D {v >> 2 & 1}, digital mic {v & 3}"),
    9: ("serial interface B (T10-17)", lambda v: f"{['I2S', 'DSP', 'right-justified', 'left-justified'][v >> 6]}, "
                                                 f"{[16, 20, 24, 32][v >> 4 & 3]}-bit, "
                                                 f"{'256-clock' if v & 8 else 'continuous'} BCLK, DAC re-sync {v >> 2 & 1}"
                                                 f", ADC re-sync {v >> 1 & 1}, re-sync soft-mute {v & 1}"),
    10: ("data offset (T10-18)", lambda v: f"{v} bit clocks"),
    11: ("overflow flags / PLL R (T10-19)", lambda v: f"R = {v & 15 or 16}"),
    12: ("digital filter (T10-20)", _hpf),
    15: ("left ADC PGA (T10-23)", lambda v: f"{'muted' if v & 0x80 else 'unmuted'}, {min(v & 0x7F, 119) / 2:g} dB"),
    16: ("right ADC PGA (T10-24)", lambda v: f"{'muted' if v & 0x80 else 'unmuted'}, {min(v & 0x7F, 119) / 2:g} dB"),
    17: ("MIC3L/R to left ADC (T10-25)", _mic3("left")),
    18: ("MIC3L/R to right ADC (T10-26)", _mic3("right")),
    19: ("LINE1L to left ADC (T10-27)", _adc_line("LINE1L", "left", True)),
    21: ("LINE1R to left ADC (T10-29)", _adc_line("LINE1R", "left", False)),
    22: ("LINE1R to right ADC (T10-30)", _adc_line("LINE1R", "right", True)),
    24: ("LINE1L to right ADC (T10-32)", _adc_line("LINE1L", "right", False)),
    37: ("AC power / HPLCOM config (T10-45)", lambda v: f"left DAC {'on' if v & 0x80 else 'off'}, right DAC "
                                                      f"{'on' if v & 0x40 else 'off'}, HPLCOM "
                                                      f"{['differential of HPLOUT', 'VCM', 'single-ended', 'reserved'][v >> 4 & 3]}"),
    41: ("DAC output switching (T10-49)", _dac_path),
    42: ("output pop reduction (T10-50)", _pop),
    43: ("left DAC volume (T10-51)", lambda v: f"{'muted' if v & 0x80 else 'unmuted'}, -{(v & 0x7F) / 2:g} dB"),
    44: ("right DAC volume (T10-52)", lambda v: f"{'muted' if v & 0x80 else 'unmuted'}, -{(v & 0x7F) / 2:g} dB"),
    47: ("DAC_L1 to HPLOUT (T10-56)", _route("DAC_L1 -> HPLOUT")),
    51: ("HPLOUT level (T10-60)", _outlevel("HPLOUT")),
    54: ("DAC_L1 to HPLCOM (T10-63)", _route("DAC_L1 -> HPLCOM")),
    58: ("HPLCOM level (T10-67)", _outlevel("HPLCOM")),
    64: ("DAC_R1 to HPROUT (T10-73)", _route("DAC_R1 -> HPROUT")),
    65: ("HPROUT level (T10-74)", _outlevel("HPROUT")),
    71: ("DAC_R1 to HPRCOM (T10-80)", _route("DAC_R1 -> HPRCOM")),
    72: ("HPRCOM level (T10-81)", _outlevel("HPRCOM")),
    82: ("DAC_L1 to LEFT_LOP/M (T10-91)", _route("DAC_L1 -> LEFT_LOP/M")),
    85: ("DAC_R1 to LEFT_LOP/M (T10-94)", _route("DAC_R1 -> LEFT_LOP/M")),
    86: ("LEFT_LOP/M level (T10-95)", _outlevel("LEFT_LOP/M", power_rw=False)),
    92: ("DAC_R1 to RIGHT_LOP/M (T10-101)", _route("DAC_R1 -> RIGHT_LOP/M")),
    93: ("RIGHT_LOP/M level (T10-102)", _outlevel("RIGHT_LOP/M", power_rw=False)),
    107: ("ADC digital path / I2C (T10-116)", lambda v: f"programmable HPF coefficients left {v >> 7}, right {v >> 6 & 1}"
                                                      f", decimation config {v >> 4 & 3}, filter path {v >> 3 & 1}"
                                                      f", I2C error detect {'off' if v & 4 else 'on'}"),
}
PAGE1_HPF = {65: "left N0", 67: "left N1", 69: "left D1", 71: "right N0", 73: "right N1", 75: "right D1"}  # T10-176..187


def decode(writes):
    """[(reg, value)] in write order -> [(page, reg, value, name, meaning)]; tracks the page register and joins the
    page-1 high-pass coefficient pairs (MSB, LSB) into one signed 16-bit value."""
    page, out, msb = 0, [], {}
    for reg, value in writes:
        if reg == 0:
            out.append((page, 0, value, PAGE0[0][0], PAGE0[0][1](value)))
            page = value & 1
            continue
        if page == 1 and reg in range(65, 77):
            base = reg if reg in PAGE1_HPF else reg - 1
            if reg == base:
                msb[base] = value
                meaning = "MSB"
            else:
                x = (msb.get(base, 0) << 8) | value
                meaning = f"{PAGE1_HPF[base]} = {x - 65536 if x & 0x8000 else x}"
            out.append((1, reg, value, f"ADC high-pass coefficient (page 1, T10-176..187)", meaning))
            continue
        name, fn = PAGE0.get(reg, (f"register {reg}", lambda v: "not decoded"))
        out.append((page, reg, value, name, fn(value) if page == 0 else "page 1, not decoded"))
    return out


def pll_rate(mclk, p, j, d, r=1):
    """fs(ref) = PLLCLK_IN x K x R / (2048 x P), K = J.D (SLAS509G section 10.3.3.1, equation 2)."""
    return mclk * (j + d / 10000) * r / (2048 * p)


# --- simulation ----------------------------------------------------------------------------------------------------

AUDIO_START = 0xC1621574
I2C0 = 0x01C22000
GPIO = 0x01E26000
# (SmplTrek address, name, argument sets as dicts of registers; a4 = I2C0 base unless the function takes no base)
CODEC_FUNCTIONS = [
    (0xC161D64C, "codec_reset", [{}]),
    (0xC161D814, "codec_set_audio_interface", [{"b4": 0, "a6": 32, "b6": 0}]),
    (0xC161D560, "codec_set_sample_rate", [{"a6": 48000}, {"a6": 44100}]),
    (0xC161D6E0, "codec_set_pll_fraction", [{"b4": t} for t in (0, 1, 300, -1, -300)]),
    (0xC161D900, "codec_set_dac_mute", [{"b4": 0}, {"b4": 1}]),
    (0xC161D990, "codec_output_init", [{}]),
    (0xC161D758, "line_out_dac1_volume (dormant)", [{"b4": 0}, {"b4": 20}]),
    (0xC161D798, "hprcom_dac_r1_volume (dormant)", [{"b4": 0}, {"b4": 20}]),
    (0xC161D7D4, "hplcom_dac_l1_volume (dormant)", [{"b4": 0}, {"b4": 20}]),
    (0xC161D7E8, "hplcom_level (dormant)", [{"b4": 0}, {"b4": 1}]),
    (0xC161D894, "left_lop_from_dac_r1 (dormant)", [{"b4": 0}, {"b4": 1}]),
    (0xC161D964, "hplout_from_dac_l1 (dormant)", [{"b4": 0}, {"b4": 1}]),
    (0xC161D9E4, "codec_route_mic3r_to_right_adc", [{"b4": 0}, {"b4": 1}]),
    (0xC161DA10, "codec_route_mic3r_to_left_adc", [{"b4": 0}, {"b4": 1}]),
    (0xC161DCA0, "mic3r_to_both_adcs (dormant)", [{"b4": 0}, {"b4": 1}]),
    (0xC161DA40, "line1l_right_and_line1r_right", [{"b4": 0, "a6": 0}, {"b4": 1, "a6": 0}, {"b4": 0, "a6": 1}]),
    (0xC161DAF0, "line1l_left_and_line1r_left", [{"b4": 0, "a6": 0}, {"b4": 1, "a6": 0}, {"b4": 0, "a6": 1}]),
    (0xC161DB74, "route_line1r_to_right_adc", [{"b4": 0}, {"b4": 1}]),
    (0xC161DBB0, "route_line1r_to_left_adc", [{"b4": 0}, {"b4": 1}]),
    (0xC161DBE0, "route_line1l_to_right_adc", [{"b4": 0}, {"b4": 1}]),
    (0xC161DC0C, "route_line1l_to_left_adc", [{"b4": 0}, {"b4": 1}]),
    (0xC161DD08, "line1l_left_level (dormant)", [{"b4": 0}, {"b4": 4}, {"b4": 15}]),
    (0xC161DC48, "codec_set_pga_right", [{"b4": 0}, {"b4": 42}]),
    (0xC161DC58, "codec_set_pga_left", [{"b4": 0}, {"b4": 20}]),
    (0xC161DC6C, "pga_both (dormant)", [{"b4": 20}]),
    (0xC161DD74, "codec_adc_hpf_init", [{}]),
    (0xC161DDF4, "codec_input_init", [{}]),
    (0xC161DE80, "codec_set_adc_hpf", [{"b4": 1, "a6": 1}, {"b4": 0, "a6": 0}]),
    (0xC161DE94, "right_adc_power", [{"b4": 0}, {"b4": 1}]),
    (0xC161DEE4, "left_adc_power", [{"b4": 0}, {"b4": 1}]),
]
# input actions (no base argument): routing halves and gain presets used through 0xC15F102C
INPUT_ACTIONS = [
    (0xC15F0FC0, "route R -> right ADC"), (0xC15F0FD2, "route R -> left ADC"),
    (0xC15F0FEA, "route L -> right ADC"), (0xC15F1004, "route L -> left ADC"),
    (0xC15F0E80, "reset input stages"),
    (0xC15F0EA0, "mic stage on, right PGA +21"), (0xC15F0EB2, "mic stage on, right PGA 0"),
    (0xC15F0ECA, "mic stage on, left PGA +21"), (0xC15F0EE2, "mic stage on, left PGA 0"),
    (0xC15F0F00, "Hi-Z stage on, right PGA +10"), (0xC15F0F12, "Hi-Z stage on, right PGA 0"),
    (0xC15F0F2A, "Hi-Z stage on, left PGA +10"), (0xC15F0F42, "Hi-Z stage on, left PGA 0"),
    (0xC15F0F60, "mic stage off, right PGA 0"), (0xC15F0F72, "mic stage off, left PGA 0"),
    (0xC15F0F8A, "Hi-Z stage off, right PGA 0"), (0xC15F0FA4, "Hi-Z stage off, left PGA 0"),
]
INPUT_APPLIERS = [(0xC15F1064, "input_r_gain_apply", [{"a4": n} for n in range(4)]),
                  (0xC15F112C, "input_l_gain_apply", [{"a4": n} for n in range(1, 7)]),
                  (0xC15F102C, "input_action_pair (GP7[14])", [{"a4": 0xC15F0E80, "b4": 0xC15F0E80, "a6": n}
                                                               for n in (0, 1)])]


def gpio_pins(address, value):
    """+GPb[p] / -GPb[p] for a GPIO SET_DATA / CLR_DATA write, else None (SPRUH79 GPIO register map)."""
    off = address - GPIO
    for n in range(5):
        kind = {0x18 + 0x28 * n: "+", 0x1C + 0x28 * n: "-"}.get(off)
        if kind:
            return [f"{kind}GP{2 * n + b // 16}[{b % 16}]" for b in range(32) if value >> b & 1]
    return None


class Session:
    """One product, booted, with the board set-up and audio start run once."""

    def __init__(self, key):
        import c6sim
        import hw_compare
        import mmio_trace
        self.p = hw_compare.Product(key)
        self.t = mmio_trace.Trace(str(hw_compare.ROOT / self.p.cfg["image"]), key)
        stubs = mmio_trace.sim_boot.PRODUCTS[key]["stubs"]
        saved = dict(stubs)
        for a, why in saved.items():
            if why.startswith("PSC") or "USB" in why:
                del stubs[a]
        try:
            self.t.boot()
        finally:
            stubs.clear()
            stubs.update(saved)
        self.codec = []

        def codec_write(m):
            self.codec.append((m.g("b4"), m.g("a6") & 0xFF))
            m.R["a4"] = 1
            return m.R["b3"]
        self.hooks = {self.p.function(hw_compare.CODEC_WRITE): codec_write}
        for a in hw_compare.HOOKS:
            f = self.p.function(a)
            if f is not None:
                self.hooks[f] = c6sim.returns(1 if a == 0xC16A1BF0 else 0)
        for f, regs in ((0xC16907D4, {}), (0xC169CD20, {}), (AUDIO_START, {"a4": I2C0})):
            self.t.run(self.p.function(f), regs, hooks=self.hooks, max_cycles=1500000)

    def call(self, smpl_address, regs, base=True):
        """(codec writes, GPIO pin events) of one call after a fresh audio start, or (None, error text)."""
        import c6sim
        f = self.p.function(smpl_address)
        if f is None:
            return None, "no counterpart"
        # arguments that are SmplTrek code addresses (the action pointers) become this product's counterparts
        regs = {r: (self.p.function(v) if 0xC1500000 <= v < 0xC1700000 else v) for r, v in regs.items()}
        if None in regs.values():
            return None, "argument has no counterpart"
        self.t.run(self.p.function(AUDIO_START), {"a4": I2C0}, hooks=self.hooks, max_cycles=1500000)
        self.codec.clear()
        try:
            _, log = self.t.run(f, dict({"a4": I2C0} if base else {}, **regs), hooks=self.hooks, max_cycles=1500000)
        except c6sim.SimError as e:
            return None, str(e)
        pins = [x for a in log if a.kind == "W" for x in (gpio_pins(a.address, a.value) or [])]
        return list(self.codec), pins


def sweep(key):
    """{(address, args tuple): (codec writes, pins)} for every function and input action in one product."""
    s = Session(key)
    out = {}
    for address, _, argsets in CODEC_FUNCTIONS:
        for regs in argsets:
            out[(address, tuple(sorted(regs.items())))] = s.call(address, regs)
    for address, _ in INPUT_ACTIONS:
        out[(address, ())] = s.call(address, {}, base=False)
    for address, _, argsets in INPUT_APPLIERS:
        for regs in argsets:
            out[(address, tuple(sorted(regs.items())))] = s.call(address, regs, base=False)
    return out


def names():
    n = {a: name for a, name, _ in CODEC_FUNCTIONS}
    n.update({a: name for a, name in INPUT_ACTIONS})
    n.update({a: name for a, name, _ in INPUT_APPLIERS})
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--compare", action="store_true", help="also run Lofi-12 XT and CyDrums and list differences")
    ap.add_argument("--decode", nargs="*", metavar="REG=VALUE", help="decode register writes and exit")
    args = ap.parse_args()
    if args.decode is not None:
        w = [(int(x.split("=")[0], 0), int(x.split("=")[1], 0)) for x in args.decode]
        for page, reg, value, name, meaning in decode(w):
            print(f"p{page} r{reg:3d} = {value:#04x}  {name}: {meaning}")
        return
    base = sweep("smpltrek")
    label = names()
    for (address, a), (codec, pins) in base.items():
        argtext = ", ".join(f"{k}={v}" for k, v in a)
        print(f"{address:#010x} {label[address]}({argtext})")
        if codec is None:
            print(f"    error: {pins}")
            continue
        if pins:
            print(f"    pins: {' '.join(pins)}")
        for page, reg, value, name, meaning in decode(codec):
            print(f"    p{page} r{reg:3d} = {value:#04x}  {name}: {meaning}")
    if args.compare:
        for key in ("lofi12", "cydrums"):
            other = sweep(key)
            diff = [k for k in base if other.get(k) != base[k]]
            print(f"{key}: {len(base) - len(diff)} of {len(base)} calls identical" +
                  "".join(f"\n    differs: {label[k[0]]} {k[1]}: {other.get(k)}" for k in diff))


if __name__ == "__main__":
    main()
