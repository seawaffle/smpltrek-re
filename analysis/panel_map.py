#!/usr/bin/env python3
"""Panel LED addressing, panel-MCU command bytes and the SPI flash write-enable of the Sonicware apps, run in c6sim in
SmplTrek 3.2.174, Lofi-12 XT 1.5.205 and CyDrums 1.1.84. Read-only and simulated.

LEDs. Every LED goes through `led_set(a, b, c, value)` (SmplTrek `0xC15F2A40`), which keeps a byte per LED in
`g_led_state[a][b][c]` (3 x 6 x 8, `0xC1500578`), returns at once if the value is unchanged, and otherwise tail-calls
`panel_led_command` (`0xC161E814`), which sends the five bytes `C1 a b c value` to the panel MCU. A few helpers call
`panel_led_command` directly (no cache). This tool hooks `panel_led_command` and records (a, b, c, value) for:
- `pad_rgb_set(i, v1, v2, v3)` (`0xC15F3068`), which indexes three 15-entry tables of single-LED setters (filled at
  start-up, `0xC16ED668` / `0xC16ED628` / `0xC16ED5E8`): pads 0-14;
- the three "set a group" functions the app uses to clear the panel (`0xC15FB0E0`, `0xC15FB180`, `0xC15FB2EC`), each
  of which calls one setter per LED with the same value.

Panel MCU commands. The one-byte commands are constants at B14+1622..1628, each sent by its own `ADControllerUART`
method through the UART send (`0xC161E3C0`, buffer in B4, length in A6). The tool runs each method and records the
bytes.

Flash. `HAL::FlashMemoryDriver`'s write-enable (`0xC15DF028`) sends one byte from B14+1630 through the SPI object's
vtable slot 1. The tool gives it a fake SPI object whose slot 1 is hooked, and records the byte.

Usage (from the repository root; needs firmware/ and the work listings and match files, as hw_compare.py):
  python3 -B analysis/panel_map.py              # SmplTrek
  python3 -B analysis/panel_map.py --compare    # also Lofi-12 XT and CyDrums, report differences
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

LED_SET = 0xC15F2A40
PANEL_LED_COMMAND = 0xC161E814
PANEL_SEND = 0xC161E3C0
PAD_RGB_SET = 0xC15F3068
STEP_LED_SET_RG = 0xC15F31B4   # (step 0-15 in A4, red B4, green A6) through g_step_led_setters 0xC16EB448
GROUPS = [(0xC15FB0E0, "group A (row-0 LED c3 direct, then the pad setters)"),
          (0xC15FB180, "group B (row-0 LEDs direct, single LEDs, then 16 two-channel LEDs, first channel)"),
          (0xC15FB2EC, "group C (row-0 LEDs direct, single LEDs, then 16 two-channel LEDs, second channel)")]
# ADControllerUART one-byte senders (SmplTrek addresses) and the B14 offset each loads
SENDERS = [(0xC161E680, 1622), (0xC161E620, 1623), (0xC161E500, 1624), (0xC161E4A0, 1625), (0xC161E560, 1626),
           (0xC161E5C0, 1627), (0xC161E72C, 1628)]
LOCK = 0xC1682F0C           # called first by each sender with *(this+28) (inference: a lock); stubbed
UART_READY = 0xC1662BC0     # the senders send only when this returns non-zero; stubbed to 1
FLASH_WREN = 0xC15DF028
SCRATCH = 0xC0010000        # zero-filled DDR below every product's image: fake objects live here
FAKE_HOOK = 0xC0011000      # a code address used only as a hook
# region_diff maps pad_rgb_set 4 bytes past the function start in the other two products (onto a fetch-packet header,
# where the compiled packets differ); the starts below were read from work/lofi-1.5.205.dis and cydrums-1.1.84.dis
# (same body: three calls to the table-indexed setters with A4 kept and B4 = v1, A6 = v2, B6 = v3).
OVERRIDES = {"lofi12": {PAD_RGB_SET: 0xC2C33938}, "cydrums": {PAD_RGB_SET: 0xC254EAB8}}


class Session:
    """One product, booted (sim_boot), with panel_led_command and the UART send hooked."""

    def __init__(self, key):
        import c6sim
        import hw_compare
        import mmio_trace
        self.c6sim = c6sim
        self.p = hw_compare.Product(key)
        self.t = mmio_trace.Trace(str(hw_compare.ROOT / self.p.cfg["image"]), key)
        self.t.boot()
        self.t.state = dict(self.t.boot_state.overlay)
        self.leds, self.sent = [], []

        def led(m):
            self.leds.append((m.g("b4") & 0xFF, m.g("a6") & 0xFF, m.g("b6") & 0xFF, m.g("a8") & 0xFF))
            return m.R["b3"]

        def send(m):
            self.sent.append(bytes(m.mem.read(m.g("b4"), m.g("a6"))))
            m.R["a4"] = 0
            return m.R["b3"]
        self.hooks = {self.p.function(PANEL_LED_COMMAND): led, self.p.function(PANEL_SEND): send,
                      self.p.function(LOCK): c6sim.returns(0), self.p.function(UART_READY): c6sim.returns(1),
                      FAKE_HOOK: send}
        for a in hw_compare.HOOKS:
            f = self.p.function(a)
            if f is not None:
                self.hooks.setdefault(f, c6sim.returns(1 if a == 0xC16A1BF0 else 0))

    def poke(self, address, value):
        for i in range(4):
            self.t.state[address + i] = (value >> (8 * i)) & 0xFF

    def run(self, smpl_address, regs):
        f = OVERRIDES.get(self.p.key, {}).get(smpl_address) or self.p.function(smpl_address)
        if f is None:
            raise LookupError(f"{self.p.key}: no counterpart of {smpl_address:#x}")
        self.leds.clear()
        self.sent.clear()
        self.t.run(f, regs, hooks=self.hooks, max_cycles=500000)
        return list(self.leds), list(self.sent)

    def pads(self):
        """[(pad, [(a, b, c) for v1, v2, v3])] for pads 0-14."""
        out = []
        for i in range(15):
            leds, _ = self.run(PAD_RGB_SET, {"a4": i, "b4": 0x11 + i, "a6": 0x41 + i, "b6": 0x71 + i})
            by_value = {v: (a, b, c) for a, b, c, v in leds}
            out.append((i, [by_value.get(0x11 + i), by_value.get(0x41 + i), by_value.get(0x71 + i)]))
        return out

    def steps(self):
        """[(step 1-16, green (a, b, c), red (a, b, c))] from step_led_set_rg."""
        out = []
        for n in range(16):
            leds, _ = self.run(STEP_LED_SET_RG, {"a4": n, "b4": 0x21, "a6": 0x31})
            by_value = {v: (a, b, c) for a, b, c, v in leds}
            out.append((n + 1, by_value.get(0x31), by_value.get(0x21)))
        return out

    def groups(self):
        """{group function: [(a, b, c), ...] in call order}; each call uses a value no LED holds yet."""
        out = {}
        for n, (address, _) in enumerate(GROUPS):
            leds, _ = self.run(address, {"a4": 0xA0 + n})
            out[address] = [(a, b, c) for a, b, c, v in leds]
        return out

    def commands(self):
        """[(sender, bytes sent)] for the one-byte ADControllerUART commands."""
        out = []
        for address, _ in SENDERS:
            _, sent = self.run(address, {"a4": SCRATCH})
            out.append((address, b"".join(sent)))
        return out

    def flash_write_enable(self):
        """Bytes the flash write-enable sends: this+12 -> SPI object -> vtable -> slot 1 (hooked)."""
        obj, vtable = SCRATCH + 0x100, SCRATCH + 0x200
        self.poke(SCRATCH + 12, obj)
        self.poke(obj, vtable)
        self.poke(vtable + 4, FAKE_HOOK)
        _, sent = self.run(FLASH_WREN, {"a4": SCRATCH})
        return b"".join(sent)

    def all(self):
        return {"pads": self.pads(), "groups": self.groups(), "commands": self.commands(),
                "flash_write_enable": self.flash_write_enable()}


def report(r):
    print("Pads (pad_rgb_set argument order v1, v2, v3 -> LED (a, b, c)):")
    for i, abc in r["pads"]:
        print(f"  pad {i:2d}: " + "  ".join(str(x) for x in abc))
    for address, what in GROUPS:
        g = r["groups"][address]
        print(f"{what}, {address:#x}: {len(g)} LEDs")
        print("  " + " ".join(f"{a}{b}{c}" for a, b, c in g))
    print("One-byte panel commands:")
    for address, b in r["commands"]:
        print(f"  {address:#x}: {b.hex(' ').upper()}")
    print(f"Flash write-enable byte: {r['flash_write_enable'].hex().upper()}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--compare", action="store_true", help="also run Lofi-12 XT and CyDrums and list differences")
    args = ap.parse_args()
    base = Session("smpltrek").all()
    report(base)
    if args.compare:
        for key in ("lofi12", "cydrums"):
            r = Session(key).all()
            diffs = [k for k in base if r[k] != base[k]]
            print(f"{key}: " + ("same as SmplTrek" if not diffs else "differs in " + ", ".join(diffs)))
            for k in diffs:
                print(f"  {k}: {r[k]}")


if __name__ == "__main__":
    main()
