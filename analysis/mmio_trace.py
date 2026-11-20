#!/usr/bin/env python3
"""Record the peripheral register accesses of Sonicware app code run in c6sim (read-only, simulated).

The exact register sequence the stock app uses to bring up a peripheral (pin mux, PSC,
SPI, UART, GPIO, timer) shows how the board is driven. c6sim runs the code; this module
puts a logging layer under it for the C6748 peripheral space (0x01800000-0x01FFFFFF):
  - a write is recorded and its value kept;
  - a read returns the last value written there, or 0, except for status registers that code polls, which
    answer "ready" (see READY); every such answer is marked "assumed" in the log, because it is not a
    hardware value;
  - every access is tagged with the address of the execute packet that made it.
Register names come from TI StarterWare 1.20.04.01's include/hw headers when the install is present
(default ~/ti/C6748_StarterWare_1_20_04_01, or $STARTERWARE); without it, offsets are printed.

Usage (from the repository root):
  # every access during start-up (SYS/BIOS module start-up and .init_array)
  python3 -B analysis/mmio_trace.py "firmware/smpltrek/SmplTrek v3.2.174.zip" --boot
  # then one function on the start-up state, with argument registers
  python3 -B analysis/mmio_trace.py "firmware/smpltrek/SmplTrek v3.2.174.zip" --run 0xC1672298 a4=0xC15043C0

As a module: Trace(image).boot(); Trace.run(address, regs) -> list of Access.
"""
import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import c6sim
import hw_inventory
import sim_boot

SPACE = (0x01800000, 0x02000000)
STARTERWARE = Path(os.environ.get("STARTERWARE", Path.home() / "ti/C6748_StarterWare_1_20_04_01"))
HEADERS = {   # peripheral name prefix -> (header, macro prefix)
    "PSC": ("hw_psc_C6748.h", "PSC_"), "PLLC": ("hw_pllc_C6748.h", "PLLC_"),
    "SYSCFG0": ("hw_syscfg0_C6748.h", "SYSCFG0_"), "SYSCFG1": ("hw_syscfg1_C6748.h", "SYSCFG1_"),
    "SPI": ("hw_spi.h", "SPI_"), "UART": ("hw_uart.h", "UART_"), "TIMER64": ("hw_tmr.h", "TMR_"),
    "GPIO": ("hw_gpio.h", "GPIO_"), "I2C": ("hw_i2c.h", "I2C_"), "MMCSD": ("hw_mmcsd.h", "MMCSD_"),
    "McASP0 control": ("hw_mcasp.h", "MCASP_"), "EDMA3 CC": ("hw_edma3cc.h", "EDMA3CC_"),
    "INTC": ("hw_dspintc.h", "DSPINTC_"), "cache": ("hw_dspcache.h", "DSPCACHE_"),
}


def register_names():
    """{peripheral prefix: {offset: name}} from StarterWare headers (empty when not installed)."""
    out = {}
    for key, (header, prefix) in HEADERS.items():
        path = STARTERWARE / "include/hw" / header
        if not path.exists():
            continue
        names, rank = {}, {}
        for line in path.read_text(errors="replace").splitlines():
            m = re.match(rf"#define\s+({prefix}\w+?)(\(n\))?\s+(\(.*\))\s*$", line)
            if not m or "SHIFT" in m.group(1) or re.search(r"\d+u\b|[0-9a-fA-F]u\)", m.group(3)):
                continue
            if key == "McASP0 control" and m.group(1).startswith(prefix + "FIFO_"):
                continue        # the AFIFO block is a separate window (0x01D01000); its offsets collide
            expr = m.group(3)
            if not re.fullmatch(r"[\s()0-9a-fA-FxX+*n]+", expr):
                continue
            for n in (range(64) if m.group(2) else [None]):
                try:
                    off = eval(expr, {"__builtins__": {}}, {"n": n})
                except Exception:
                    break
                # a fixed name beats an indexed one, a smaller index beats a larger (EVTSET(57) vs INTMUX(1))
                r = -1 if n is None else n
                if 0 <= off < 0x20000 and r < rank.get(off, 1 << 30):
                    names[off], rank[off] = m.group(1)[len(prefix):] + (f"({n})" if n is not None else ""), r
        out[key] = names
    return out


NAMES = register_names()


def pinmux_functions():
    """{(pinmux register n, nibble k): {value: pin function}} from StarterWare's hw_syscfg0_C6748.h."""
    path = STARTERWARE / "include/hw/hw_syscfg0_C6748.h"
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(errors="replace").splitlines():
        m = re.match(r"#define\s+SYSCFG_PINMUX(\d+)_PINMUX\1_(\d+)_(\d+)_(\w+)\s+\((0x[0-9A-Fa-f]+)u\)", line)
        if m and m.group(4) not in ("SHIFT", "DEFAULT") and not m.group(4).startswith("RESERVED"):
            out.setdefault((int(m.group(1)), int(m.group(3)) // 4), {})[int(m.group(5), 16)] = m.group(4)
    return out


PINMUX = pinmux_functions()


def decode_pinmux(n, value):
    """Pin functions selected by PINMUXn = value, one per non-zero nibble ('?' when not in the header)."""
    out = []
    for k in range(8):
        v = (value >> (4 * k)) & 0xF
        if v:
            out.append(PINMUX.get((n, k), {}).get(v, f"nibble{k}={v}?"))
    return out


def name(address):
    p = hw_inventory.peripheral(address)
    if not p:
        return f"{address:#010x}"
    base, pname = p
    off = address - base
    if pname.startswith("EDMA3 CC") and off >= 0x4000:            # PaRAM: 32-byte sets
        field = ["OPT", "SRC", "A_B_CNT", "DST", "SRC_DST_BIDX", "LINK_BCNTRLD", "SRC_DST_CIDX", "CCNT"]
        return f"{pname} PaRAM({(off - 0x4000) // 32}).{field[(off % 32) // 4]}"
    if pname == "SYSCFG0" and 0x120 <= off < 0x170:
        return f"SYSCFG0 PINMUX{(off - 0x120) // 4}"
    for key, names in NAMES.items():
        if pname.startswith(key) or (key == "TIMER64" and pname.startswith("TIMER64")):
            if off in names:
                return f"{pname} {names[off]}"
    return f"{pname} +{off:#x}"


def reset_value(address):
    """Register value after reset where it is not 0 (C6748 GPIO DIR: every pin an input)."""
    p = hw_inventory.peripheral(address)
    if p and p[1] == "GPIO" and (address - p[0] - 0x10) % 0x28 == 0 and 0x10 <= address - p[0] < 0xB8:
        return 0xFFFFFFFF
    return 0


def ready(address, value):
    """Answer for a polled status register, or None to return the stored value."""
    p = hw_inventory.peripheral(address)
    if not p:
        return None
    base, pname = p
    off = address - base
    if pname.startswith("PSC") and 0x800 <= off < 0xA00:          # MDSTAT(n): state = MDCTL(n).NEXT
        return None                                                 # filled in by Trace (needs MDCTL)
    if pname.startswith("SPI") and off == 0x10:                    # SPIFLG: TXINTFLAG | RXINTFLAG
        return 0x300
    if pname.startswith("SPI") and off == 0x40:                    # SPIBUF: not RXEMPTY, not TXFULL
        return value & 0xFFFF
    if pname.startswith("UART") and off == 0x14:                   # LSR: THRE | TEMT
        return 0x60
    if pname.startswith("I2C") and off == 0x08:                    # ICSTR: ARDY | ICRRDY | ICXRDY, bus free
        return 0x1C
    if pname == "SYSCFG0" and off == 0x184:                         # CFGCHIP2: USB0 PHY clock good
        return value | 0x20000
    if pname.startswith("USB0") and off == 0x04:                   # CTRLR: RESET clears itself
        return value & ~1
    return None


@dataclass
class Access:
    cycle: int
    packet: int
    kind: str          # "W", "R" or "R*" (assumed answer)
    address: int
    size: int
    value: int

    def __str__(self):
        text = f"{self.cycle:8d} {self.packet:08x} {self.kind:2s} {name(self.address):34s} " \
               f"{self.address:#010x} = {self.value:#010x}" + ("  (assumed)" if self.kind == "R*" else "")
        if self.kind == "W" and 0x01C14120 <= self.address < 0x01C14170:
            text += "  " + " ".join(decode_pinmux((self.address - 0x01C14120) // 4, self.value))
        return text


class Trace:
    def __init__(self, image, product="smpltrek"):
        self.image = image
        self.product = product
        self.log = []
        self.regs = {}            # peripheral address -> last value written
        self.machine = None

    def memory_class(trace):
        class TraceMemory(c6sim.Memory):
            def read(self, address, size):
                if SPACE[0] <= address < SPACE[1]:
                    stored = trace.regs.get(address & ~3, reset_value(address & ~3))
                    answer = ready(address, stored)
                    p = hw_inventory.peripheral(address)
                    if answer is None and p and p[1].startswith("PSC") and 0x800 <= address - p[0] < 0xA00:
                        answer = (trace.regs.get(address + 0x200, 0) & 0x1F)      # MDSTAT = MDCTL.NEXT
                    value = stored if answer is None else answer
                    trace.record("R" if answer is None else "R*", address, size, value)
                    return (value >> (8 * (address & 3))).to_bytes(4, "little")[:size] if size < 4 \
                        else value.to_bytes(4, "little") + bytes(size - 4)
                return super().read(address, size)

            def write(self, address, data):
                if SPACE[0] <= address < SPACE[1]:
                    value = int.from_bytes(bytes(data), "little")
                    trace.record("W", address, len(data), value)
                    trace.store(address, value)
                    return
                super().write(address, data)
        return TraceMemory

    def store(self, address, value):
        """Keep a written value, with the McASP side effects TI StarterWare's McASP driver waits on:
        RGBLCTL / XGBLCTL write the receive / transmit halves of GBLCTL, and all three read back GBLCTL;
        RSTAT / XSTAT are write-1-to-clear."""
        p = hw_inventory.peripheral(address)
        word = address & ~3
        if p and p[1] == "McASP0 control":
            base, off = p[0], address - p[0]
            g = self.regs.get(base + 0x44, 0)
            if off in (0x44, 0x60, 0xA0):
                if off == 0x44:
                    g = value
                elif off == 0x60:
                    g = (g & ~0x1F) | (value & 0x1F)
                else:
                    g = (g & ~0x1F00) | (value & 0x1F00)
                for o in (0x44, 0x60, 0xA0):
                    self.regs[base + o] = g
                return
            if off in (0x80, 0xC0):
                self.regs[word] = self.regs.get(word, 0) & ~value
                return
        self.regs[word] = value

    def record(self, kind, address, size, value):
        m = self.machine
        self.log.append(Access(m.cyc if m else 0, getattr(m, "packet_address", 0) if m else 0,
                               kind, address, size, value))

    def _patch(self):
        """Make every Machine built from now on log peripheral accesses and remember its packet address."""
        trace = self
        memory = self.memory_class()

        class TracingMachine(c6sim.Machine):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                old = self.mem
                self.mem = memory(old.image)
                self.mem.overlay = old.overlay
                trace.machine = self

            def execute(self, ins, nxt, prot, skip_units=()):
                if ins:
                    self.packet_address = ins[0][0]
                return super().execute(ins, nxt, prot, skip_units)
        return TracingMachine

    def boot(self):
        """Build the product's start-up state while logging; returns the sim_boot.Boot."""
        cls = self._patch()
        saved = c6sim.Machine
        c6sim.Machine = cls
        try:
            self.boot_state = sim_boot.Boot(self.product, self.image)
        finally:
            c6sim.Machine = saved
        return self.boot_state

    def run(self, address, regs=None, hooks=None, max_cycles=2000000):
        """Run one function on the current state and return (A4, the accesses it made).

        The first run starts from the start-up state (boot() first); each later run continues from the
        memory the previous one left, so a sequence of calls builds on itself as in the app.
        """
        cls = self._patch()
        b = self.boot_state
        all_hooks = b.hooks()
        all_hooks.update(hooks or {})
        m = cls(b.program, dict({"b14": b.cfg["b14"]}, **(regs or {})), hooks=all_hooks)
        m.mem.overlay = dict(getattr(self, "state", b.overlay))
        start = len(self.log)
        result = m.run(address, max_cycles=max_cycles)
        self.state = m.mem.overlay
        self.last_machine = m
        return result, self.log[start:]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image")
    parser.add_argument("--product", default="smpltrek", choices=sorted(sim_boot.PRODUCTS))
    parser.add_argument("--boot", action="store_true", help="print the accesses made during start-up")
    parser.add_argument("--run", nargs="+", metavar=("ADDRESS", "REG=VALUE"),
                        help="run a function on the start-up state, e.g. --run 0xC1672298 a4=0xC15043C0")
    parser.add_argument("--writes", action="store_true", help="print writes only")
    args = parser.parse_args()
    t = Trace(args.image, args.product)
    n0 = len(t.log)
    b = t.boot()
    for e, s in b.errors:
        print(f"start-up entry {e:#010x}: {s}", file=sys.stderr)
    if args.boot:
        for a in t.log[n0:]:
            if not args.writes or a.kind == "W":
                print(a)
    if args.run:
        regs = {k: int(v, 0) for k, v in (x.split("=") for x in args.run[1:])}
        result, log = t.run(int(args.run[0], 0), regs)
        print(f"returned {result:#x}")
        for a in log:
            if not args.writes or a.kind == "W":
                print(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
