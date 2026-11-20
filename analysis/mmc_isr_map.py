#!/usr/bin/env python3
"""What `mmcsd0_isr` (0xC166F98C) of SmplTrek 3.2.174 does for each MMCST0 bit, run in c6sim. Read-only and simulated.

MMCST0 (0x01C40008) bits are TI's (SPRUH79C 25.4.3, Table 25-8); reading it clears the status bits, which this tool
models (the ISR reads it again before it returns). The ISR calls a listener whose pointer sits in a table at
0xC16EFBA0 (entry 0), with vtable slots:
  RSPDNE (bit 2)          slot 0 (listener); then, if B14+1124 == 4, 0xC166F900(0): B14+1120 = 0 and
                          Event_post(0xC14FFD54, 4), which wakes `mmcsd_wait`
  DATDNE (bit 0)          slot 1 (listener)
  TOUTRS (bit 4)          slot 2 (listener, -1)
  TOUTRD (bit 3)          slot 2 (listener, -2)
  CRCWR, CRCRD (5, 6)     slot 2 (listener, -7)
  BSYDNE, CRCRS, DXRDY, DRRDY, DATED, TRNDNE, CCS: nothing.
The table's setter (0xC166F978) has no caller and no data reference in the image, and the table entry is 0 after
start-up, so in the stock app only the RSPDNE post runs. B14+1124 is set by `cmdSend` (0xC1645D1C -> 0xC166F8A4):
4 when no data transfer is set up (controller record +76 == 0), else 1. DATDNE with B14+1124 == 1 posts too (data
commands). `0xC166F90C` is the delay-slot code of 0xC166F900, not a helper.

Session.command runs a whole protocol function (CMD13 0xC15D1F54, read 0xC15D2288, ...): cmdSend, the register
writer and cmdStatusGet as in the app, with MMCCMD writes raising status bits and the Event_pend wrapper running the
real ISR, so it shows which bit releases a command and what an unanswered one does (claim HW-44).

Usage (from the repository root; needs firmware/ and the work listing, as hw_compare.py):
  python3 -B analysis/mmc_isr_map.py
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

ISR, POST_STATUS, MMCST0, TABLE, MODE = 0xC166F98C, 0xC166F900, 0x01C40008, 0xC16EFBA0, 1124
MMCCMD, MMCRSP, WDATX = 0x01C40030, 0x01C40038, 1 << 13              # SPRUH79C Table 25-18 (WDATX = data command)
EVENT_PEND, EVENT_POST = 0xC16A5174, 0xC16A516C                          # the app's Event wrappers (claim LIB-3)
FILL, CTRL, CMD13, READ = 0xC164620C, 0xC14B63A8, 0xC15D1F54, 0xC15D2288
DISK_READ, DISK_WRITE = 0xC1682378, 0xC1682320                         # FatFs diskio (pdrv, buff, sector, count)
CACHE = (0xC16AC9E0, 0xC16ACA00, 0xC16ACA20)                             # Cache_inv / Cache_wbInv / Cache_wb
RSPDNE, DATDNE, TOUTRS, TOUTRD = 1 << 2, 1 << 0, 1 << 4, 1 << 3
BITS = {0: "DATDNE", 1: "BSYDNE", 2: "RSPDNE", 3: "TOUTRD", 4: "TOUTRS", 5: "CRCWR", 6: "CRCRD", 7: "CRCRS",
        9: "DXRDY", 10: "DRRDY", 11: "DATED", 12: "TRNDNE", 13: "CCS"}           # SPRUH79C Table 25-8
LISTENER, VTABLE, SLOTS = 0xC0000100, 0xC0000140, 0xC0000180                     # zero-filled DDR


class Session:
    def __init__(self):
        import c6sim
        import hw_compare
        import mmio_trace
        self.c6sim = c6sim
        self.t = mmio_trace.Trace(str(hw_compare.ROOT / hw_compare.PRODUCTS["smpltrek"]["image"]), "smpltrek")
        self.boot = self.t.boot()
        self.b14 = self.boot.cfg["b14"]
        self.pending, self.reads, self.calls = 0, 0, []
        session, base = self, self.t.memory_class

        def memory_class():
            class ClearOnRead(base()):
                def write(self, address, data):
                    if address == MMCCMD and session.answer is not None:
                        command = int.from_bytes(bytes(data), "little")
                        session.commands.append(command)
                        session.raised |= session.answer(command)
                    return super().write(address, data)

                def read(self, address, size):
                    if address == MMCST0:
                        value, session.pending = session.pending, 0
                        session.reads += 1
                        return value.to_bytes(4, "little")[:size]
                    return super().read(address, size)
            return ClearOnRead
        self.t.memory_class = memory_class
        self.hooks = {a: c6sim.returns(0) for a in hw_compare.HOOKS}
        for k in range(4):
            self.hooks[SLOTS + 4 * k] = self.slot(k)
        self.hooks[POST_STATUS] = self.post
        self.answer, self.raised, self.posted, self.waits, self.commands, self.base = None, 0, 0, [], [], None

    def slot(self, k):
        def f(m):
            self.calls.append(("slot", k) + ((self.c6sim.s32(m.R.get("b4", 0)),) if k == 2 else ()))
            return m.R["b3"]
        return f

    def post(self, m):
        self.calls.append(("post", self.c6sim.s32(m.R.get("a4", 0))))
        return m.R["b3"]

    def poke(self, address, value):
        for i in range(4):
            self.t.state[address + i] = (value >> (8 * i)) & 0xFF

    def listener_at_boot(self):
        return sum(self.boot.overlay.get(TABLE + i, 0) << (8 * i) for i in range(4))

    def isr(self, status, mode=0, listener=True):
        """(calls, MMCST0 reads) for one interrupt with `status` in MMCST0 and B14+1124 = `mode`."""
        self.t.state, self.t.regs = dict(self.boot.overlay), {}
        if listener:
            self.poke(TABLE, LISTENER)
            self.poke(LISTENER, VTABLE)
            for k in range(4):
                self.poke(VTABLE + 4 * k, SLOTS + 4 * k)
        self.poke(self.b14 + MODE, mode)
        self.pending, self.reads, self.calls = status, 0, []
        self.t.run(ISR, {}, hooks=self.hooks, max_cycles=200000)
        return list(self.calls), self.reads


    # Whole commands: the protocol layer, cmdSend, the register writer and cmdStatusGet run as in the app; writing
    # MMCCMD raises the status bits `answer(command word)` returns, and the Event_pend wrapper delivers them by
    # running the real mmcsd0_isr (nested), then returns the bits the ISR posted (0 = timed out).
    def event_pend(self, m):
        if self.raised:
            self.t.state, self.pending, self.raised = m.mem.overlay, self.raised, 0
            sp = (m.R.get("b15", 0) - 0x400) & ~7                               # below the interrupted stack
            self.t.run(ISR, {"b15": sp}, hooks=self.isr_hooks, max_cycles=200000)
            m.mem.overlay, self.t.machine = self.t.state, m
        got = self.posted & m.R.get("a6", 0)
        self.waits.append((self.c6sim.s32(m.R.get("b6", 0)), got))
        self.posted &= ~got
        m.R["a4"] = got
        return m.R["b3"]

    def event_post(self, m):
        self.posted |= m.R.get("b4", 0)
        return m.R["b3"]

    def command(self, fn, answer, regs=None):
        """Run protocol function `fn` (A4 = the controller record unless `regs` gives one; e.g. DISK_READ with A4 = 0). Returns (result or the error text, [(Event_pend
        timeout, bits returned)], [command indexes sent], mode word B14+1124 afterwards)."""
        import hw_compare
        if self.base is None:
            self.t.state, self.t.regs = dict(self.boot.overlay), {}
            self.t.run(FILL, {}, hooks=self.hooks)
            card = sum(self.t.state.get(CTRL + 80 + i, 0) << (8 * i) for i in range(4))
            self.poke(card + 8, 0x1234)                                           # RCA
            self.t.state[card + 59] = 1                                           # CCS: block addressing
            self.base = dict(self.t.state)
        self.isr_hooks = {a: self.c6sim.returns(0) for a in hw_compare.HOOKS}
        self.isr_hooks[EVENT_POST] = self.event_post
        hooks = {a: self.c6sim.returns(0) for a in hw_compare.HOOKS}
        hooks.update({a: self.c6sim.returns(0) for a in CACHE})
        hooks.update({EVENT_PEND: self.event_pend, EVENT_POST: self.event_post})
        self.t.state, self.t.regs = dict(self.base), {MMCRSP + 4 * k: 0x900 for k in range(4)}  # card state tran
        self.answer, self.raised, self.posted, self.waits, self.commands = answer, 0, 0, [], []
        try:
            result = self.c6sim.s32(self.t.run(fn, dict({"a4": CTRL}, **(regs or {})), hooks=hooks, max_cycles=3000000)[0])
        except Exception as e:                                                    # noqa: BLE001
            result = f"{type(e).__name__}: {e}"[:80]
        self.answer = None
        mode = sum(self.t.state.get(self.b14 + MODE + i, 0) << (8 * i) for i in range(4))
        return result, list(self.waits), [c & 0x3F for c in self.commands], mode


def main():
    s = Session()
    print(f"listener table entry 0 after start-up: {s.listener_at_boot():#x}")
    for bit, name in BITS.items():
        print(f"{name:7} (bit {bit:2}): mode 4 {s.isr(1 << bit, 4)[0]}; no listener, mode 4 "
              f"{s.isr(1 << bit, 4, listener=False)[0]}")


if __name__ == "__main__":
    main()
