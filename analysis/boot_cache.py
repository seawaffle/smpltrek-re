#!/usr/bin/env python3
"""The cache configuration the SmplTrek bootloader (BOOT 1.0.17) leaves at the jump to SYSTEM, simulated.

Runs the bootloader's SYS/BIOS cache start-up (0xC70996A0, the start-up table entry at 0xC70A7C28) in c6sim on
the sections ais_extract.py wrote, and reports every cache controller register it writes. The L2, L1P and L1D
sizes are constants in the code (helpers 0xC709BDA0, 0xC709D420, 0xC709D2E0); the MAR bits come from a table in
the loaded data. Decoded with TI SPRUFK5A (C674x megamodule) Tables 2-2, 3-2 and 4-4.

Needs the extracted bootloader (not committed):
  python3 -B analysis/ais_extract.py work/a4/A4DUMP.BIN --out work/a4/boot-1.0.17
Usage (from the repository root):
  python3 -B analysis/boot_cache.py
"""
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import c6sim
import memory_map
import packets

ROOT = Path(__file__).resolve().parents[1]
EXTRACT = ROOT / "work/a4/boot-1.0.17"
ENTRY = 0xC70A1160
CACHE_STARTUP = 0xC70996A0
L2CFG, L1PCFG, L1DCFG, MAR0 = 0x01840000, 0x01840020, 0x01840040, 0x01848000


class BootProgram(c6sim.Program):
    """c6sim program built from ais_extract.py's section-NN-<address>.bin files."""

    def __init__(self, directory=EXTRACT):
        sections = []
        for f in sorted(Path(directory).glob("section-*.bin")):
            sections.append((int(re.search(r"-([0-9a-f]{8})\.bin$", f.name).group(1), 16), f.read_bytes()))
        if not sections:
            raise FileNotFoundError(f"no bootloader sections in {directory}")
        self.name, self.entry, self.sections = "boot-1.0.17", ENTRY, sections
        self.image = memory_map.Image(sections)
        self.text = packets.listing(sections, ENTRY)
        self.cache = {}


def cache_state(directory=EXTRACT):
    """{"L2CFG": v, "L1PCFG": v, "L1DCFG": v, "MAR": {n: v}} as written by the bootloader's cache start-up."""
    m = c6sim.Machine(BootProgram(directory))
    m.run(CACHE_STARTUP, max_cycles=2_000_000)
    written = {a for a in m.mem.overlay if 0x01840000 <= a < 0x01850000 and a % 4 == 0}
    out = {"MAR": {}}
    for a in sorted(written):
        v = m.mem.word(a)
        if a >= MAR0:
            out["MAR"][(a - MAR0) // 4] = v
        else:
            out[{L2CFG: "L2CFG", L1PCFG: "L1PCFG", L1DCFG: "L1DCFG"}.get(a, f"{a:#010x}")] = v
    return out


def main():
    s = cache_state()
    for k in ("L2CFG", "L1PCFG", "L1DCFG"):
        print(f"{k:7s} {s.get(k, 'not written')}")
    on = [n for n, v in sorted(s["MAR"].items()) if v & 1]
    print(f"MAR written: {len(s['MAR'])}; cacheable (PC=1): {on}")
    for n in on:
        print(f"  MAR{n}: {n << 24:#010x}-{(n << 24) + 0xFFFFFF:#010x}")


if __name__ == "__main__":
    main()
