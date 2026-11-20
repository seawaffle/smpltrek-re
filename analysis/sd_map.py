#!/usr/bin/env python3
"""SD card controller layer of the Sonicware apps, run in c6sim in SmplTrek 3.2.174, Lofi-12 XT 1.5.205 and
CyDrums 1.1.84: the MMCCMD word and argument of every command the protocol layer sends, the transfer set-up
(FIFO, block length and count, EDMA PaRAM), how multi-block transfers stop, the bus width and the clock after
initialisation. Read-only and simulated. Register and field names are TI's (StarterWare hw_mmcsd.h; SPRUH79C
chapter 25, Table 25-18 MMCCMD, Table 25-29 MMCFIFOCTL).

The controller record. `0xC164620C` fills a StarterWare-style `mmcsdCtrlInfo` (compare StarterWare
bootloader/src/bl_hsmmcsd.c, lines 402-419) at `0xC14B63A8`: memBase `0x01C40000`, ipClk 186 MHz, opClk 400 kHz,
then function pointers (ctrlInit +12, cmdSend +16, busWidthConfig +20, busFreqConfig +24, cmdStatusGet +28,
xferStatusGet +32, xferSetup +40), intrMask +52, busWidth +56, highspeed +60, and the card record pointer +80.
The protocol functions take this record in A4. The app's status functions wait on semaphores filled by the MMC
interrupt; here cmdStatusGet and xferStatusGet (found through the record, so the same in every product) return 1,
the semaphore calls and the cache write-back are stubbed, and the response registers read `0x900` (card state
"tran", ready for data), so every command succeeds once.

Usage (from the repository root; needs firmware/ and the work listings and match files, as hw_compare.py):
  python3 -B analysis/sd_map.py              # SmplTrek
  python3 -B analysis/sd_map.py --compare    # also Lofi-12 XT and CyDrums, report differences
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

MMC = 0x01C40000
REG = {0x00: "MMCCTL", 0x04: "MMCCLK", 0x10: "MMCIM", 0x14: "MMCTOR", 0x18: "MMCTOD", 0x1C: "MMCBLEN", 0x20: "MMCNBLK", 0x30: "MMCCMD", 0x34: "MMCARGHL",
       0x74: "MMCFIFOCTL"}
FILL = 0xC164620C           # fills the controller record (SmplTrek addresses throughout)
PEND = 0xC166F8A4           # semaphore/lock taken before every command (inference); stubbed, returns 1
PEND2 = 0xC166F934          # semaphore wait inside the status functions; stubbed (they are hooked anyway)
CACHE_WB = 0xC16ACA20       # cache write-back of the write buffer (polls L2 registers c6sim does not model)
CARD_RCA = 8                # card record offsets
CARD_OCR = 52
CARD_SCR_WIDTHS = 57
CARD_TRAN_SPEED = 58        # CSD byte (inference: TRAN_SPEED; 0x32 = 25 MHz, 0x5A = 50 MHz in the SD spec)
CARD_CCS = 59
CARD_BLKLEN = 60
CMD6_STATUS = 0xC1502080    # the 64-byte buffer CMD6 and ACMD51 read into (SmplTrek)
OCR_READY = 0xC0FF8000     # ACMD41 response: powered up (bit 31), CCS (bit 30), 2.7-3.6 V
COMMANDS = [("CMD0", 0xC15D2488), ("CMD55 probe", 0xC15D2460), ("CMD8", 0xC15D24C0), ("ACMD41", 0xC15D24EC),
            ("CMD2", 0xC15D2658), ("CMD3", 0xC15D26E4), ("CMD9", 0xC15D2A4C), ("CMD7", 0xC15D2C24),
            ("CMD16", 0xC15D2C68), ("ACMD51", 0xC15D2D18), ("CMD13", 0xC15D1F54), ("CMD12", 0xC15D1F2C)]
READ, WRITE = 0xC15D2288, 0xC15D1FF4      # (ctrl, buffer, block, count)
BUS_WIDTH, HIGH_SPEED, CTRL_INIT = 0xC15D3010, 0xC15D2160, 0xC167B4CC
BUFFER, BLOCK = 0xC0010000, 0x100


class Session:
    """One product, booted, with the controller record filled."""

    def __init__(self, key):
        import c6sim
        import hw_compare
        import mmio_trace
        self.p = hw_compare.Product(key)
        self.t = mmio_trace.Trace(str(hw_compare.ROOT / self.p.cfg["image"]), key)
        self.t.boot()
        self.t.state = dict(self.t.boot_state.overlay)
        before = dict(self.t.state)
        self.t.run(self.p.function(FILL), {})
        changed = sorted(a for a in self.t.state if before.get(a) != self.t.state[a])
        self.ctrl = next(a for a in changed if a % 4 == 0 and self.word(a) == MMC)
        self.card = self.word(self.ctrl + 80)
        f = self.p.function
        self.hooks = {f(PEND): c6sim.returns(1), f(PEND2): c6sim.returns(0), f(CACHE_WB): c6sim.returns(0),
                      self.word(self.ctrl + 28): c6sim.returns(1), self.word(self.ctrl + 32): c6sim.returns(1)}
        for a in hw_compare.HOOKS:
            if f(a) is not None:
                self.hooks.setdefault(f(a), c6sim.returns(1 if a == 0xC16A1BF0 else 0))
        self.poke(self.card + CARD_RCA, 0x1234)
        self.base = dict(self.t.state)

    def word(self, address):
        return sum(self.t.state.get(address + i, 0) << (8 * i) for i in range(4))

    def poke(self, address, value, size=4):
        for i in range(size):
            self.t.state[address + i] = (value >> (8 * i)) & 0xFF

    def record(self):
        w = self.word
        c = self.ctrl
        return {"memBase": w(c), "ipClk": w(c + 4), "opClk": w(c + 8), "intrMask": w(c + 52),
                "busWidth": w(c + 56), "highspeed": w(c + 60)}

    def run(self, smpl_address, regs, card=None, status16=None, response=0x900):
        """Run from the filled state; returns [(register name or PaRAM field, value)] written, in order.
        The CCNT word keeps only its 16-bit CCNT field: the code stores a whole word whose upper (reserved) half
        is whatever was on the stack, which differs between products."""
        status = self.cmd6_status() if status16 is not None else None
        self.t.state = dict(self.base)
        self.t.regs = {MMC + r: response for r in range(0x38, 0x48, 4)}
        self.t.state.update({self.card + k: v for k, v in (card or {}).items()})
        if status16 is not None:
            self.t.state[status + 16] = status16
        n = len(self.t.log)
        r, _ = self.t.run(self.p.function(smpl_address), dict(regs, a4=self.ctrl), hooks=self.hooks,
                          max_cycles=3000000)
        out = []
        for a in self.t.log[n:]:
            if a.kind != "W":
                continue
            if MMC <= a.address < MMC + 0x100 and a.address - MMC in REG:
                out.append((REG[a.address - MMC], a.value))
            elif 0x01C04000 <= a.address < 0x01C08000:
                field = ("OPT", "SRC", "A_B_CNT", "DST", "BIDX", "LINK", "CIDX", "CCNT")[(a.address % 32) // 4]
                out.append((f"PaRAM({(a.address - 0x01C04000) // 32}).{field}",
                            a.value & 0xFFFF if field == "CCNT" else a.value))
        return r, out

    def cmd6_status(self):
        # the buffer address is a constant in the product's high-speed step: the DST of PaRAM 16 in its run
        if not hasattr(self, "_cmd6"):
            self.t.state = dict(self.base)
            n = len(self.t.log)
            self.t.run(self.p.function(HIGH_SPEED), {"a4": self.ctrl}, hooks=self.hooks, max_cycles=3000000)
            self._cmd6 = next(a.value for a in self.t.log[n:] if a.kind == "W" and a.address == 0x01C0420C)
        return self._cmd6

    @staticmethod
    def commands_of(writes):
        """[(MMCARGHL, MMCCMD)] pairs from a write list."""
        out, arg = [], None
        for name, v in writes:
            if name == "MMCARGHL":
                arg = v
            elif name == "MMCCMD":
                out.append((arg, v))
        return out

    def commands(self):
        """{name: [(argument, MMCCMD)]} for each protocol-layer command function."""
        return {name: self.commands_of(self.run(a, {}, response=OCR_READY if name == "ACMD41" else 0x900)[1])
                for name, a in COMMANDS}

    def acmd41_card(self):
        """Card record bytes OCR (+52..+55) and CCS (+59) after ACMD41 answers OCR_READY."""
        self.run(0xC15D24EC, {}, response=OCR_READY)
        return [self.t.state.get(self.card + i, 0) for i in range(CARD_OCR, CARD_OCR + 4)], \
            self.t.state.get(self.card + CARD_CCS, 0)

    def transfers(self):
        """{(op, count): writes} for 1- and 4-block reads and writes on a block-addressed card."""
        card = {CARD_CCS: 1, CARD_BLKLEN: 0, CARD_BLKLEN + 1: 2}
        out = {}
        for op, a in (("read", READ), ("write", WRITE)):
            for n in (1, 4):
                out[(op, n)] = self.run(a, {"b4": BUFFER, "a6": BLOCK, "b6": n}, card=card)[1]
        return out

    def bus_width(self):
        """{SCR bus widths byte: writes} (ctrl busWidth is 5: 1- and 4-bit)."""
        return {scr: self.run(BUS_WIDTH, {}, card={CARD_SCR_WIDTHS: scr})[1] for scr in (0x1, 0x5)}

    def high_speed(self):
        """{(TRAN_SPEED byte before, CMD6 group-1 result): (last MMCCLK, opClk after, TRAN_SPEED after)}."""
        out = {}
        for tran in (0x32, 0x5A):
            for grp in (0, 1):
                _, w = self.run(HIGH_SPEED, {}, card={CARD_TRAN_SPEED: tran}, status16=grp)
                clk = [v for name, v in w if name == "MMCCLK"]
                out[(tran, grp)] = (clk[-1], self.word(self.ctrl + 8), self.t.state.get(self.card + CARD_TRAN_SPEED))
        return out

    def ctrl_init(self):
        return [(n, v) for n, v in self.run(CTRL_INIT, {})[1]]

    def all(self):
        return {"record": self.record(), "commands": self.commands(), "transfers": self.transfers(),
                "bus_width": self.bus_width(), "high_speed": self.high_speed(), "ctrl_init": self.ctrl_init(),
                "acmd41_card": self.acmd41_card()}


def decode(cmd):
    """MMCCMD fields (SPRUH79C Table 25-18)."""
    f = [f"CMD{cmd & 0x3F}", ("no rsp", "R1", "R2", "R3")[(cmd >> 9) & 3]]
    for bit, name in ((16, "DMATRIG"), (15, "DCLR"), (14, "INITCK"), (13, "WDATX"), (12, "STRMTP"), (11, "DTRW"),
                      (8, "BSYEXP"), (7, "PPLEN")):
        if cmd >> bit & 1:
            f.append(name)
    return " ".join(f)


def report(r, ctrl=None):
    rec = r["record"]
    print("Controller record: " + ", ".join(f"{k} {v:#x}" for k, v in rec.items()))
    print("Commands (argument, MMCCMD):")
    for name, pairs in r["commands"].items():
        print(f"  {name:12s} " + "; ".join(f"{a:#010x} {c:#07x} ({decode(c)})" for a, c in pairs))
    print("Transfers:")
    for (op, n), w in r["transfers"].items():
        print(f"  {op} {n}: " + ", ".join(f"{k}={v:#x}" for k, v in w if not k.endswith(("SRC", "DST", "LINK"))))
    print("Bus width (SCR widths byte -> writes after ACMD6):")
    for scr, w in r["bus_width"].items():
        print(f"  {scr:#x}: " + ", ".join(f"{k}={v:#x}" for k, v in w))
    print("High-speed step (TRAN_SPEED before, CMD6 group 1) -> (MMCCLK, opClk, TRAN_SPEED after):")
    for k, v in r["high_speed"].items():
        print(f"  ({k[0]:#x}, {k[1]}) -> (MMCCLK {v[0]:#x}, {v[1]}, {v[2]:#x})")
    ocr, ccs = r["acmd41_card"]
    print(f"After ACMD41: card+52..55 = {bytes(ocr).hex(' ')}, CCS (card+59) = {ccs}")
    print("ctrlInit: " + ", ".join(f"{k}={v:#x}" for k, v in r["ctrl_init"]))


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
