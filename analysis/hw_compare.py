#!/usr/bin/env python3
"""Run the same hardware bring-up steps in SmplTrek 3.2.174, Lofi-12 XT 1.5.205 and CyDrums 1.1.84 and compare the
register writes (simulated, read-only).

The three apps drive the same board (platform map). A register value that all three
write is board fact, not one build's choice; a difference shows a product-specific use of the same part. Each
step names a SmplTrek function; its counterpart in the other products is the function of the same name in that
product's symbol files, else the func_match counterpart (region_diff.locate). Object arguments are the same-named
global, or the A4 constant loaded before the counterpart of a SmplTrek call site.

Writes are compared in order as (register, value). Values that are memory addresses (DDR 0xC0000000-0xC7FFFFFF,
L1D/L2 0x11800000-0x11FFFFFF) are shown as <ptr>, because buffers move between builds. Codec register writes are
recorded at codec_write (I2C transfers themselves are interrupt-driven and are not simulated).

Usage (from the repository root, needs firmware/):
  python3 -B analysis/hw_compare.py                 # every step, summary
  python3 -B analysis/hw_compare.py --step audio -v # one step, every write
"""
import argparse
import difflib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import c6sim
import mmio_trace
import region_diff

PRODUCTS = {
    "smpltrek": dict(image="firmware/smpltrek/SmplTrek v3.2.174.zip", listing="work/smpltrek-3.2.174.dis",
                     symbols=["symbols/smpltrek-3.2.174.json"], match=None),
    "lofi12": dict(image="firmware/lofi12/Lofi-12XT_v1.5.205.zip", listing="work/lofi-1.5.205.dis",
                   symbols=["symbols/lofi-12xt-1.5.205.json", "symbols/hand/lofi-12xt-1.5.205.json"],
                   match="work/match-3.2.174-Lofi-12XT_v1.5.205.json"),
    "cydrums": dict(image="firmware/cydrums/CyDrums_v1.1.84.zip", listing="work/cydrums-1.1.84.dis",
                    symbols=["symbols/cydrums-1.1.84.json", "symbols/hand/cydrums-1.1.84.json"],
                    match="work/match-3.2.174-CyDrums_v1.1.84.json"),
}

# (step, SmplTrek function, arguments). An argument is an int, ("sym", global name) or ("site", SmplTrek call
# site whose A4 constant is the argument[, global name to use when the counterpart site does not show it]).
STEPS = [
    ("syscfg_unlock", 0xC16907D4, {}),
    ("early_psc", 0xC169CD20, {}),
    ("usb_phy_cfg", 0xC16907C0, {}),
    ("spi", 0xC167C7B4, {}),
    ("oled", 0xC1672298, {"a4": 0x30000000}),
    ("oled_data", 0xC16723A8, {"a4": ("sym", "g_oled_framebuffer"), "b4": 32}),
    ("panel_uart", 0xC161E338, {"a4": ("sym", "g_ad_controller_uart"), "b4": 460800}),
    ("panel_uart_rx", 0xC161E790, {"a4": ("sym", "g_ad_controller_uart"), "b4": 1}),
    ("panel_uart_tx", 0xC161E6E0, {"a4": ("sym", "g_ad_controller_uart"), "b4": 1}),
    ("encoders", 0xC166DB50, {"a4": ("site", 0xC154A5A4, "g_encoders")}),
    ("keys", 0xC168F140, {"a4": ("sym", "g_control_scan")}),
    ("sync", 0xC16720D8, {"a4": ("site", 0xC154A5B0)}),
    ("power_pinmux", 0xC16470B0, {}),
    ("power", 0xC1646FCC, {"a4": ("sym", "g_power_manager")}),
    ("audio_power", 0xC1649448, {"a4": 1}),
    ("gp4_10", 0xC1649654, {"a4": 0}),
    ("audio_hw", 0xC1621854, {}),
    ("i2c_setup", 0xC1671E90, {}),
    ("audio", 0xC1621574, {"a4": 0x01C22000}),
    ("midi_uart", 0xC1620EF4, {"a4": ("sym", "g_midi_stream_uart")}),
    ("midi_in", 0xC16194AC, {"a4": 1}),
    ("usb", 0xC168EFE4, {}),
    ("usb_dcd", 0xC158EE00, {"a4": 0, "b4": ("sym", "g_usb_midi_device_info"), "a6": 0x30001000}),
    ("sd", 0xC167270C, {}),
]
# SmplTrek functions replaced in every product: (address, behaviour)
HOOKS = {0xC16A1BF0: "returns 1 (wait for the SPI DMA completion)", 0xC1667D20: "returns 0 (task_sleep)"}
CODEC_WRITE = 0xC1671CC4


def load_symbols(files):
    out = {}
    for f in files:
        p = ROOT / f
        if p.exists():
            for s in json.loads(p.read_text())["symbols"]:
                out.setdefault(s["name"], int(s["address"], 16))
    return out


SMPL = load_symbols(PRODUCTS["smpltrek"]["symbols"])
SMPL_NAME = {a: n for n, a in SMPL.items()}


class Product:
    def __init__(self, key):
        self.key, self.cfg = key, PRODUCTS[key]
        self.symbols = load_symbols(self.cfg["symbols"])
        self._listing = None

    def function(self, smpl_address):
        """This product's counterpart of a SmplTrek function, or None."""
        if self.key == "smpltrek":
            return smpl_address
        name = SMPL_NAME.get(smpl_address)
        if name and name in self.symbols:
            return self.symbols[name]
        return region_diff.locate(ROOT / self.cfg["match"], smpl_address, smpl_address + 1)

    def listing(self):
        if self._listing is None:
            self._listing = {}
            for line in (ROOT / self.cfg["listing"]).read_text().splitlines():
                m = re.match(r"([0-9a-f]{8}):\t\S+\s*\t(.*)$", line)
                if m:
                    self._listing[int(m.group(1), 16)] = m.group(2)
        return self._listing

    def a4_before(self, site):
        """The constant built into A4 by MVK/MVKH in the 16 instructions up to site (None if not found)."""
        text = self.listing()
        addresses = sorted(a for a in text if site - 64 <= a <= site)
        after = sorted(a for a in text if site < a <= site + 16)
        for a in after:                     # the rest of the call's execute packet
            if not text[a].lstrip().startswith("||"):
                break
            addresses.append(a)
        lo = hi = None
        for a in addresses:
            t = text[a].replace("||", "").strip()
            m = re.match(r"(?:\[!?\w+\]\s*)?(mvkl?|mvkh) \.\w+ (-?\d+),a4$", t)
            if m:
                v = int(m.group(2))
                if m.group(1) == "mvkh":
                    hi = v & 0xFFFF0000
                else:
                    lo, hi = v & 0xFFFF, None
            m = re.match(r"or \.\w+ 0,(b\d+),a4$", t)
            if m:               # value built in a B register and copied
                reg = m.group(1)
                for b in addresses:
                    if b >= a:
                        break
                    u = text[b].replace("||", "").strip()
                    mm = re.match(rf"(mvkl?|mvkh) \.\w+ (-?\d+),{reg}$", u)
                    if mm:
                        if mm.group(1) == "mvkh":
                            hi = int(mm.group(2)) & 0xFFFF0000
                        else:
                            lo, hi = int(mm.group(2)) & 0xFFFF, None
        return None if lo is None or hi is None else hi | lo

    def argument(self, value):
        if isinstance(value, int):
            return value
        kind, x, *fallback = value
        if kind == "sym":
            return self.symbols.get(x) if self.key != "smpltrek" else SMPL[x]
        site = x if self.key == "smpltrek" else self.function(x)
        found = None if site is None else self.a4_before(site)
        if found is None and fallback:          # the named global the SmplTrek site loads
            return self.argument(("sym", fallback[0]))
        return found


def run(key, steps=STEPS):
    """{step: (function address, [(register, value)], [(codec reg, value)] or error text)} for one product."""
    p = Product(key)
    # the tracer answers the PSC and USB status polls itself, so sim_boot's stubs for them would hide writes
    stubs = mmio_trace.sim_boot.PRODUCTS[key]["stubs"]
    saved = dict(stubs)
    for a, why in saved.items():
        if why.startswith("PSC") or "USB" in why:
            del stubs[a]
    t = mmio_trace.Trace(str(ROOT / p.cfg["image"]), key)
    try:
        t.boot()
    finally:
        stubs.clear()
        stubs.update(saved)
    hooks = {}
    for a, _ in HOOKS.items():
        f = p.function(a)
        if f is not None:
            hooks[f] = c6sim.returns(1 if a == 0xC16A1BF0 else 0)
    codec = []

    def codec_write(m):
        codec.append((m.g("b4"), m.g("a6")))
        m.R["a4"] = 1
        return m.R["b3"]
    cw = p.function(CODEC_WRITE)
    if cw is not None:
        hooks[cw] = codec_write
    out = {}
    for name, address, args in steps:
        f = p.function(address)
        regs = {r: p.argument(v) for r, v in args.items()}
        if f is None or None in regs.values():
            out[name] = (f, None, f"not resolved (function {f}, arguments {regs})")
            continue
        codec.clear()
        try:
            _, log = t.run(f, regs, hooks=hooks, max_cycles=1500000)
        except c6sim.SimError as e:
            out[name] = (f, None, f"SimError: {e}")
            continue
        out[name] = (f, [(a.address, a.value) for a in log if a.kind == "W"], list(codec))
    return out


def shown(value):
    if 0xC0000000 <= value < 0xC8000000 or 0x11800000 <= value < 0x12000000:
        return "<ptr>"
    return f"{value:#x}"


def lines(writes):
    return [f"{mmio_trace.name(a)} = {shown(v)}" for a, v in writes]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--step", action="append", help="only these steps (repeatable)")
    parser.add_argument("-v", action="store_true", help="print every write")
    args = parser.parse_args()
    steps = [s for s in STEPS if not args.step or s[0] in args.step]
    results = {k: run(k, steps) for k in PRODUCTS}
    for name, *_ in steps:
        base = results["smpltrek"][name]
        print(f"== {name}")
        for k in PRODUCTS:
            f, writes, extra = results[k][name]
            if writes is None:
                print(f"   {k:9s} {extra}")
                continue
            codec = f", {len(extra)} codec writes" if extra else ""
            if k == "smpltrek":
                print(f"   {k:9s} {f:#010x}: {len(writes)} register writes{codec}")
                if args.v:
                    for line in lines(writes):
                        print("      " + line)
                    for r, v in extra:
                        print(f"      codec reg {r} = {v:#04x}")
                continue
            if base[1] is None:
                print(f"   {k:9s} {f:#010x}: {len(writes)} writes (no SmplTrek baseline)")
                continue
            diff = [d for d in difflib.unified_diff(lines(base[1]), lines(writes), lineterm="", n=0)
                    if not d.startswith(("---", "+++", "@@"))]
            cdiff = [d for d in difflib.unified_diff([f"{r}={v:#x}" for r, v in base[2]],
                                                     [f"{r}={v:#x}" for r, v in extra], lineterm="", n=0)
                     if not d.startswith(("---", "+++", "@@"))]
            same = "same" if not diff else f"{len(diff)} differing lines"
            csame = "" if not base[2] and not extra else ("; codec same" if not cdiff else f"; codec {len(cdiff)} differing")
            print(f"   {k:9s} {f:#010x}: {same}{csame}")
            for d in (diff + ["codec " + c for c in cdiff])[: (200 if args.v else 12)]:
                print("      " + d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
