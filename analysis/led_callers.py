#!/usr/bin/env python3
"""Which code drives each panel LED in SmplTrek 3.2.174: which function lights which LED. Read-only;
the wrapper addresses are simulated, the callers are static.

Each one-line wrapper in 0xC15F2A98-0xC15F37B4 is run in c6sim with `led_set` (0xC15F2A40) and
`panel_led_command` (0xC161E814) hooked, which gives the (a, b, c) it sets (the row-0 helpers send all three
a-planes directly, uncached). Then every call or branch to a wrapper from outside that block is listed with the
function it sits in, named from symbols/smpltrek-3.2.174.json and the RTTI virtual-function names
(fn_XXXXXXXX otherwise). A page that lights an LED is a hint for which button the LED is under, not proof.

Usage (from the repository root; needs firmware/, the work listing and work/smpltrek-3.2.174.rtti.json):
  python3 -B analysis/led_callers.py
"""
import bisect
import collections
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

LED_SET, PANEL_LED_COMMAND = 0xC15F2A40, 0xC161E814
BLOCK = (0xC15F2A98, 0xC15F37B4)
ROOT = HERE.parent


def function_names():
    names = {}
    for s in json.loads((ROOT / "symbols/smpltrek-3.2.174.json").read_text())["symbols"]:
        if s.get("kind") == "function":
            names[int(s["address"], 16)] = s["name"]
    for s in json.loads((ROOT / "work/smpltrek-3.2.174.rtti.json").read_text())["symbols"]:
        if s.get("kind") == "virtual_function":
            names.setdefault(int(s["address"], 16), s["name"])
    return names


def wrappers(prog, starts):
    """{wrapper address: (a, b, c)} for single-LED wrappers, or ('row0', ((a, b, c), ...)) for direct helpers."""
    import c6sim
    import hw_compare
    import mmio_trace
    t = mmio_trace.Trace(str(hw_compare.ROOT / hw_compare.PRODUCTS["smpltrek"]["image"]), "smpltrek")
    t.boot()
    got = []

    def led(m):
        got.append((m.R.get("a4", 0), m.R.get("b4", 0), m.R.get("a6", 0)))
        return m.R["b3"]

    def direct(m):
        got.append(("direct", m.R.get("b4", 0), m.R.get("a6", 0), m.R.get("b6", 0)))
        return m.R["b3"]
    hooks = {a: c6sim.returns(0) for a in hw_compare.HOOKS}
    hooks.update({LED_SET: led, PANEL_LED_COMMAND: direct})
    out = {}
    for a in (s for s in starts if BLOCK[0] <= s < BLOCK[1]):
        t.state = dict(t.boot_state.overlay)
        got.clear()
        try:
            t.run(a, {"a4": 0x77}, hooks=hooks, max_cycles=20000)
        except Exception:                                   # noqa: BLE001 - not a wrapper
            continue
        if len(got) == 1 and got[0][0] != "direct":
            out[a] = got[0]
        elif got and all(g[0] == "direct" for g in got):
            out[a] = ("row0", tuple(sorted({g[1:] for g in got})))
    return out


def callers():
    """[(LED address(es), wrapper, Counter of caller function names)]."""
    import c6sim
    import hw_compare
    prog = c6sim.Program(str(hw_compare.ROOT / hw_compare.PRODUCTS["smpltrek"]["image"]))
    names = function_names()
    calls = re.compile(r"callp \.S\d ([0-9a-f]{8})|\bb \.S\d ([0-9a-f]{8})")
    starts = sorted(set(names) | {int(m, 16) for t in prog.text.values()
                                  for m in re.findall(r"callp \.S\d ([0-9a-f]{8})", t)})
    found = wrappers(prog, starts)
    sites = collections.defaultdict(list)
    for a, text in prog.text.items():
        m = calls.search(text)
        if m:
            target = int(m.group(1) or m.group(2), 16)
            if target in found and not BLOCK[0] <= a < BLOCK[1]:
                sites[target].append(a)

    def owner(a):
        f = starts[bisect.bisect_right(starts, a) - 1]
        return names.get(f, f"fn_{f:08x}")
    return sorted(((abc, w, collections.Counter(owner(s) for s in sites[w])) for w, abc in found.items()),
                  key=lambda r: str(r[0]))


def main():
    for abc, w, who in callers():
        print(abc, hex(w), dict(who.most_common(8)))


if __name__ == "__main__":
    main()
