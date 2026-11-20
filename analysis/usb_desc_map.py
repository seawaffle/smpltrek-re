#!/usr/bin/env python3
"""The USB audio + MIDI configuration descriptor of SmplTrek 3.2.174, rebuilt in c6sim and decoded. Read-only and
simulated.

usblib assembles a configuration descriptor from a tConfigHeader: a section count and a pointer to an array of
tConfigSection pointers ({uint16 size; const uint8 *data}). SmplTrek's header (0xC16EFB1C) has 27 sections, array at
0xC16EBEB0. The static sections (configuration, interface and endpoint descriptors) are in the initialised data; the
class-specific ones are empty in the boot image and are filled in by the USB start (0xC167C9EC, which runs the
composite set-up 0xC165BF40 -> 0xC165BE20 with the device structure 0xC16AB32C; the audio class part is 0xC162A4A0,
the MIDI part 0xC162D964). This tool runs that start, concatenates the sections and decodes them against USB Audio
1.0 and USB MIDI 1.0 (descriptor layouts from those class specifications).

Usage (from the repository root; needs firmware/ and the work listing, as hw_compare.py):
  python3 -B analysis/usb_desc_map.py
"""
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

USB_START = 0xC167C9EC
SECTIONS, N_SECTIONS = 0xC16EBEB0, 27


def build():
    """The configuration descriptor bytes after the stock USB start."""
    import c6sim
    import hw_compare
    import mmio_trace
    t = mmio_trace.Trace(str(hw_compare.ROOT / hw_compare.PRODUCTS["smpltrek"]["image"]), "smpltrek")
    t.boot()
    hooks = {a: c6sim.returns(1 if a == 0xC16A1BF0 else 0) for a in hw_compare.HOOKS}
    t.state = dict(t.boot_state.overlay)
    t.regs = {}
    t.run(USB_START, {}, hooks=hooks, max_cycles=2000000)
    mem = t.last_machine.mem

    def word(a):
        return struct.unpack("<I", bytes(mem.read(a, 4)))[0]
    out = b""
    for k in range(N_SECTIONS):
        sec = word(SECTIONS + 4 * k)
        size = struct.unpack("<H", bytes(mem.read(sec, 2)))[0]
        out += bytes(mem.read(word(sec + 4), size)) if size else b""
    return out


def decode(b):
    """[(offset, kind, fields dict)] for each descriptor."""
    out, i, iface = [], 0, None
    while i < len(b):
        n, typ = b[i], b[i + 1]
        d = b[i:i + n]
        if n == 0:
            raise ValueError(f"zero-length descriptor at {i}")
        if typ == 2:
            r = ("CONFIG", {"total": d[2] | d[3] << 8, "interfaces": d[4], "attributes": d[7], "max_power_ma": 2 * d[8]})
        elif typ == 4:
            iface = d[2]
            r = ("INTERFACE", {"number": d[2], "alt": d[3], "endpoints": d[4], "class": (d[5], d[6], d[7])})
        elif typ == 5:
            r = ("ENDPOINT", {"address": d[2], "attributes": d[3], "max_packet": d[4] | d[5] << 8, "interval": d[6]})
        elif typ == 0x24 and iface == 0:
            sub = d[2]
            if sub == 1:
                r = ("AC_HEADER", {"bcdADC": d[3] | d[4] << 8, "total": d[5] | d[6] << 8, "streaming": list(d[8:8 + d[7]])})
            elif sub == 2:
                r = ("AC_INPUT_TERMINAL", {"id": d[3], "type": d[4] | d[5] << 8, "channels": d[7],
                                           "channel_config": d[8] | d[9] << 8})
            elif sub == 3:
                r = ("AC_OUTPUT_TERMINAL", {"id": d[3], "type": d[4] | d[5] << 8, "source": d[7]})
            else:
                r = (f"AC_{sub}", {})
        elif typ == 0x24 and iface in (1, 2):
            if d[2] == 1:
                r = ("AS_GENERAL", {"terminal": d[3], "delay": d[4], "format_tag": d[5] | d[6] << 8})
            else:
                r = ("AS_FORMAT_TYPE", {"type": d[3], "channels": d[4], "subframe": d[5], "bits": d[6],
                                        "rates": [d[8 + 3 * k] | d[9 + 3 * k] << 8 | d[10 + 3 * k] << 16
                                                  for k in range(d[7])]})
        elif typ == 0x24 and iface == 3:
            sub = d[2]
            if sub == 1:
                r = ("MS_HEADER", {"bcdMSC": d[3] | d[4] << 8, "total": d[5] | d[6] << 8})
            elif sub == 2:
                r = ("MS_IN_JACK", {"embedded": d[3] == 1, "id": d[4]})
            else:
                r = ("MS_OUT_JACK", {"embedded": d[3] == 1, "id": d[4],
                                     "sources": [(d[6 + 2 * k], d[7 + 2 * k]) for k in range(d[5])]})
        elif typ == 0x25:
            r = (("MS_ENDPOINT", {"jacks": list(d[4:4 + d[3]])}) if iface == 3 else
                 ("AS_ENDPOINT", {"attributes": d[3], "lock_units": d[4], "lock_delay": d[5] | d[6] << 8}))
        else:
            r = (f"TYPE_{typ:#x}", {})
        out.append((i, r[0], r[1]))
        i += n
    return out


def main():
    b = build()
    print(f"{len(b)} bytes")
    for off, kind, f in decode(b):
        print(f"{off:3d} {kind:20s} {f}")


if __name__ == "__main__":
    main()
