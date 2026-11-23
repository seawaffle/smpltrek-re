#!/usr/bin/env python3
"""List every on-chip peripheral a Sonicware system image addresses, and from where (static, read-only).

Which C6748 peripherals the stock app touches tells which hardware is in use and which is idle. Method: every 32-bit constant the code builds with an
MVK/MVKL ... MVKH pair (string_refs.constant_pairs, objdump decoding) that falls in the C6748 peripheral space,
plus every aligned word of the initialised data (after the copy table) that equals a peripheral base address (driver tables,
SYS/BIOS module state). Each hit is named from the C6748 memory map (base addresses as in TI StarterWare
1.20.04.01 include/hw/soc_C6748.h) and placed in its enclosing function, taken as the nearest CALLP / branch
target at or below the site, named from symbols when known.

Limits: an address built another way (ADD to a base, B14-relative tables, a loaded pointer) is reached
through a base that is usually found once; treat a missing peripheral as "not found by this method". Data
words are only counted when they equal a base exactly.

Which part (2026-11-18): each peripheral is tagged with the C674x parts that have it (C6742, C6746, C6748, from
the top-level memory maps of TI SPRS587F, SPRS591F and SPRS590G), and the summary names the parts that have
every peripheral the code constants address. A hit rules a part out; an absence rules nothing in. Data words
do not count: SYS/BIOS's timer table lists Timer0-3 on all three parts, used or not.

Inputs: an official update (.zip, .bin, Liven .syx), including the legacy ELZ_1 container (INT-15), whose
mmtd image has the entry point at +24 instead of +28; its copy table is not read, so the data-word scan is skipped.

Usage (from the repository root):
  python3 -B analysis/hw_inventory.py "firmware/smpltrek/SmplTrek v3.2.174.zip" \
      --symbols symbols/smpltrek-3.2.174.json [--json work/hw-inventory.json]
"""
import argparse
import bisect
import collections
import json
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mmtd2elf
import sonicware_integrity as integrity
import string_refs

# C6748 peripheral bases (TI StarterWare soc_C6748.h; sizes are the register windows used for matching).
PERIPHERALS = [
    (0x01800000, 0x10000, "INTC (C674x interrupt controller)"),
    (0x01810000, 0x1000, "PDC (power-down controller)"),
    (0x01811000, 0x2000, "SYS security / revision ID"),
    (0x01820000, 0x20000, "EMC / IDMA"),
    (0x01840000, 0x10000, "cache control (L1P/L1D/L2, MAR)"),
    (0x01C00000, 0x8000, "EDMA3 CC0"),
    (0x01C08000, 0x400, "EDMA3 TC0"),
    (0x01C08400, 0x400, "EDMA3 TC1"),
    (0x01C10000, 0x1000, "PSC0"),
    (0x01C11000, 0x1000, "PLLC0"),
    (0x01C14000, 0x1000, "SYSCFG0"),
    (0x01C20000, 0x1000, "TIMER64P0"),
    (0x01C21000, 0x1000, "TIMER64P1"),
    (0x01C22000, 0x1000, "I2C0"),
    (0x01C23000, 0x1000, "RTC"),
    (0x01C34000, 0x4000, "PRU"),
    (0x01C40000, 0x1000, "MMCSD0"),
    (0x01C41000, 0x1000, "SPI0"),
    (0x01C42000, 0x1000, "UART0"),
    (0x01D00000, 0x1000, "McASP0 control"),
    (0x01D01000, 0x1000, "McASP0 FIFO"),
    (0x01D02000, 0x1000, "McASP0 data"),
    (0x01D0C000, 0x1000, "UART1"),
    (0x01D0D000, 0x1000, "UART2"),
    (0x01D10000, 0x1000, "McBSP0"),
    (0x01D11000, 0x1000, "McBSP1"),
    (0x01E00000, 0x10000, "USB0 (OTG)"),
    (0x01E10000, 0x1000, "HPI"),
    (0x01E13000, 0x1000, "LCDC"),
    (0x01E14000, 0x2000, "MPU1/2"),
    (0x01E16000, 0x1000, "uPP"),
    (0x01E17000, 0x1000, "VPIF"),
    (0x01E18000, 0x1000, "SATA"),
    (0x01E1A000, 0x1000, "PLLC1"),
    (0x01E1B000, 0x1000, "MMCSD1"),
    (0x01E20000, 0x5000, "EMAC / MDIO"),
    (0x01E25000, 0x1000, "USB1 (OHCI)"),
    (0x01E26000, 0x1000, "GPIO"),
    (0x01E27000, 0x1000, "PSC1"),
    (0x01E28000, 0x1000, "I2C1"),
    (0x01E2C000, 0x1000, "SYSCFG1"),
    (0x01E30000, 0x8000, "EDMA3 CC1"),
    (0x01E38000, 0x400, "EDMA3 TC2"),
    (0x01F00000, 0x4000, "eHRPWM0/1"),
    (0x01F06000, 0x3000, "eCAP0-2"),
    (0x01F0C000, 0x1000, "TIMER64P2"),
    (0x01F0D000, 0x1000, "TIMER64P3"),
    (0x01F0E000, 0x1000, "SPI1"),
    (0x01F10000, 0x1000, "McBSP0 data"),
    (0x01F11000, 0x1000, "McBSP1 data"),
    (0x68000000, 0x8000, "EMIFA control"),
    (0xB0000000, 0x8000, "DDR2/mDDR control"),
]
PERIPHERAL_SPACE = (0x01800000, 0x02000000)

PARTS = ("C6742", "C6746", "C6748")
# Peripherals not on every part (Table 3-1 and the top-level memory map of each data sheet: SPRS587F C6742,
# SPRS591F C6746, SPRS590G C6748). Every other entry of PERIPHERALS is on all three.
ONLY_ON = {
    "LCDC": ("C6748",),
    "SATA": ("C6748",),
    "USB1 (OHCI)": ("C6748",),
}
ONLY_ON.update({name: ("C6746", "C6748") for name in (
    "PRU", "MMCSD0", "SPI0", "UART1", "UART2", "McBSP0", "McBSP0 data", "USB0 (OTG)", "uPP", "VPIF", "MMCSD1",
    "EMAC / MDIO", "I2C1", "TIMER64P2", "TIMER64P3")})


def parts_with(name):
    """The parts that have the named peripheral."""
    return ONLY_ON.get(name, PARTS)


def possible_parts(names):
    """The parts that have every named peripheral ("unknown" is ignored)."""
    return [p for p in PARTS if all(p in parts_with(n) for n in names if n != "unknown")]


def peripheral(value):
    for base, size, name in PERIPHERALS:
        if base <= value < base + size:
            return base, name
    return None


def function_starts(instructions):
    """Targets of CALLP and direct branches: an over-approximation of function entries."""
    starts = set()
    for _, mnemonic, operands in instructions:
        if mnemonic in ("callp", "b", "bnop"):
            m = re.search(r"\b([0-9a-f]{8})\b", operands)
            if m:
                starts.add(int(m.group(1), 16))
    return sorted(starts)


def analyse(sections, entry, names):
    instructions = list(string_refs.disassemble(sections, entry))
    starts = function_starts(instructions)
    named = sorted(names)

    def where(site):
        i = bisect.bisect_right(starts, site) - 1
        fn = starts[i] if i >= 0 else None
        j = bisect.bisect_right(named, site) - 1
        label = names.get(fn)
        if label is None and j >= 0 and named[j] == fn:
            label = names[named[j]]
        return fn, label

    hits = collections.defaultdict(list)       # (base, name) -> [(value, site, function, label)]
    for value, mvkh, _ in string_refs.constant_pairs(instructions):
        if PERIPHERAL_SPACE[0] <= value < PERIPHERAL_SPACE[1] or 0x68000000 <= value < 0x68008000 \
                or 0xB0000000 <= value < 0xB0008000:
            p = peripheral(value)
            key = p if p else (value & ~0xFFF, "unknown")
            hits[key].append((value, mvkh) + where(mvkh))
    return hits


def data_words(path):
    """Aligned words equal to a peripheral base in the data as it is after __TI_auto_init.

    Read through the copy table (init_data.InitData): the copy-table source sections are compressed, so a
    scan of the raw loaded sections finds accidental matches and misses the real ones.
    """
    import init_data
    bases = {b for b, _, _ in PERIPHERALS}
    out = []
    for r in init_data.InitData(path).regions:
        data = r["data"]
        for off in range(-r["start"] % 4, len(data) - 3, 4):
            w = int.from_bytes(data[off:off + 4], "little")
            if w in bases:
                out.append((r["start"] + off, w, peripheral(w)[1]))
    return out


is_legacy = mmtd2elf.is_legacy


def legacy_mmtd_sections(data):
    """(entry, [(load_address, bytes)]) of the mmtd image in a legacy ELZ_1 container (mmtd2elf, INT-15)."""
    return mmtd2elf.legacy_mmtd_sections(data)[1:]


def image_sections(data):
    """(entry, sections, legacy) for either container layout."""
    if is_legacy(data):
        return legacy_mmtd_sections(data) + (True,)
    _, entry, sections = mmtd2elf.mmtd_sections(data)
    return entry, sections, False


def summarise(hits):
    """JSON-ready rows keyed by peripheral; unknown pages are keyed "unknown 0x........" so none is lost."""
    out = {}
    for (base, pname), rows in sorted(hits.items()):
        key = f"unknown {base:#010x}" if pname == "unknown" else pname
        out[key] = [{"value": f"{v:#010x}", "site": f"{s:#010x}", "function": f"{f:#010x}" if f else None,
                     "name": l} for v, s, f, l in rows]
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="official update .zip, .bin or .syx")
    parser.add_argument("--symbols", type=Path, help="symbols JSON for the same image (function names)")
    parser.add_argument("--json", type=Path, help="also write the full result as JSON")
    args = parser.parse_args()
    (_, data), = list(integrity.inputs([args.input]))
    entry, sections, legacy = image_sections(data)
    names = {}
    if args.symbols:
        for s in json.loads(args.symbols.read_text())["symbols"]:
            if s.get("kind") == "function":
                names[int(s["address"], 16)] = s["name"]
    hits = analyse(sections, entry, names)
    words = [] if legacy else data_words(args.input)
    for (base, pname), rows in sorted(hits.items()):
        functions = collections.Counter((f, l) for _, _, f, l in rows)
        offsets = sorted({v - base for v, *_ in rows})
        only = "" if parts_with(pname) == PARTS or pname == "unknown" else f"  [{', '.join(parts_with(pname))}]"
        print(f"{pname:34s} {base:#010x}  {len(rows):3d} sites in {len(functions):2d} functions; "
              f"offsets {', '.join(f'{o:#x}' for o in offsets[:12])}{' ...' if len(offsets) > 12 else ''}{only}")
        for (f, label), n in sorted(functions.items(), key=lambda kv: kv[0][0] or 0):
            print(f"    {f:#010x} {label or '':40s} x{n}" if f else f"    ? x{n}")
    if legacy:
        print("legacy ELZ_1 container: initialised data words not scanned")
    elif words:
        print("initialised data words equal to a peripheral base:")
        for address, w, pname in words:
            print(f"    {address:#010x}: {w:#010x} {pname}")
    # Code constants only: the data words include SYS/BIOS's generated device tables, which list every timer of
    # the DA850 class (Timer0-3) for C6742, C6746 and C6748 alike (bios_6_76_03_01 timers/timer64/Timer.xs).
    parts = possible_parts({p for _, p in hits})
    print(f"parts with every peripheral found: {', '.join(parts) or 'none of ' + ', '.join(PARTS)}")
    if args.json:
        args.json.write_text(json.dumps({"constants": summarise(hits), "data_words": [
            {"address": f"{a:#010x}", "value": f"{w:#010x}", "peripheral": p} for a, w, p in words],
            "parts": parts}, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
