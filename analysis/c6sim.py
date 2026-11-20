#!/usr/bin/env python3
"""Small concrete C674x simulator for running one function of a Sonicware system image.

It executes objdump's instruction text (via packets.py) one execute packet per cycle:
  - every instruction in a packet reads its operands before any of them writes;
  - loads land after 4 delay slots; a load in a PROT fetch packet adds 4 NOP cycles after its execute packet
    (an execute packet that crosses into a PROT fetch packet without a load there gets none);
  - branches take effect 5 cycles after issue, several can be in flight, and a BNOP's or ADDKPC's NOP
    count is spent whether or not the branch is taken;
  - CALLP calls (B3 = the next packet), and a branch to the RET sentinel ends the run;
  - SPLOOP, SPLOOPD and SPLOOPW follow TI SPRUFE8B chapter 7: overlapping iterations every ii cycles,
    ILC counting with SPLOOPD's minimum iterations, SPLOOPW's predicate test at stage boundaries (on the
    value the register had 4 cycles earlier, 7.10.2) without an epilog, the SPKERNEL fetch delay (decoded
    from the opcode, see Machine.spkernel_delay), the epilog
    issuing alongside the post-loop code, and SPMASK on the loading pass and in post-loop packets.
    Nested reload (SPRUFE8B 7.9.6) through a conditional SPLOOP(D) and an SPMASKR in the post-loop code:
    the reload condition is the SPLOOP predicate 4 cycles before the last kernel stage boundary, ILC is
    RILC - 1, the reloaded prolog issues alongside the program from the cycle after the SPMASKR, and program
    fetch stops after the last delay slot of the outer branch (or when the reload reaches dynlen) until the
    reloaded loop's post-SPLOOP point. With SPKERNELR instead (7.5.2.2) the post-loop code and the reload
    both start in the first epilog cycle. RILC = 0 at the reload point skips the invocation (7.9.6.2): the
    buffer issues nothing until its last stage boundary, where the reload condition is judged again (read
    here as the predicate 4 cycles before that boundary; TI's text does not say which cycle).
  - One maskable interrupt, for checking loops only (Machine.isr and Machine.irqs, off by default): it is
    taken at a packet boundary with no branch in flight (every branch blocks it for its 5 delay slots, taken
    or not) and no loop buffer activity, costs 9 cycles before the first packet of the routine, and B IRP
    returns. Inside an SPLOOP(D/W) it follows 7.13: the loop drains from a stage boundary once its body is
    loaded, the termination condition is false, the first 3 cycles of an SPLOOPD/SPLOOPW have passed and ILC
    is at least the number of loading stages; IRP is the SPLOOP packet; on return that packet executes
    nothing, SPMASKed instructions do not run again and an SPLOOPD counts like an SPLOOP. An SPLOOPW whose
    condition ends it while draining is interrupted at the packet after its body (7.10.3). An invocation
    started by a reload is not interrupted (the interrupt waits). GIE, IER and the 2 cycles of blocking
    before an SPLOOP are not modelled. A multicycle NOP is interrupted like any instruction; after its first
    cycle IRP is the next packet and the rest of it is dropped (5.5.4). IDLE is such a NOP with no end: it
    is an error if no interrupt is left to end it.
Double-precision sources are read over two cycles (low word in the issue cycle, high word in the next,
SPRUFE8B), so a compiler may write the high word in the same packet; 2026-11-12, found with cl6x output.
RCPSP, RSQRSP, RCPDP and RSQRDP round the exact value to nearest at 8 mantissa bits, as a unit did for the 256
mantissas 1 + k/256 at three exponents (bench M2, claim HW-66); inputs with lower mantissa bits set were not measured. Only the instructions needed so far are implemented; any other one stops the run with an error, so an
unknown instruction cannot be skipped silently. Caches and peripherals are not modelled, and interrupts only
as far as the loop check above; DINT and RINT do nothing.

Memory is the image's loaded sections plus a writable overlay; everything else reads as 0. The boot copy
table's initialised data is applied only on request (Machine.apply_init_data). Peripherals are not modelled:
code that polls hardware has to be replaced with a hook (returns()).

Checked against hand-read results: Lofi-12 XT 1.5.205's settings_validate (every clamp, the forced words,
the shadow copy) and settings_set_defaults; see test_c6sim.py and docs/01-platform-map.md, "CyDrums reading
SmplTrek's settings".

Usage (from the repository root):
  # run a product's settings_validate on a 4 KiB settings block (e.g. from a flash dump) and print g_settings
  python3 -B analysis/c6sim.py settings lofi12 firmware/lofi12/Lofi-12XT_v1.5.205.zip --block BLOCK.bin
  # the same product's factory defaults (settings_set_defaults)
  python3 -B analysis/c6sim.py settings cydrums firmware/cydrums/CyDrums_v1.1.84.zip --defaults
"""
import argparse
from pathlib import Path
import re
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import packets

M = 0xFFFFFFFF
RET = 0xDEAD0000          # return-address sentinel: branching here ends the run
STACK = 0x31000000        # scratch stack top (outside every image)
NUM = re.compile(r"-?\d+")


def s32(v):
    v &= M
    return v - (1 << 32) if v & 0x80000000 else v


def f32(v):
    """IEEE single from a register; denormals read as zero (C67x floating-point units flush them)."""
    v &= M
    if (v >> 23) & 0xFF == 0:
        return -0.0 if v >> 31 else 0.0
    return struct.unpack("<f", struct.pack("<I", v))[0]


def bits32(x):
    """Round a Python float to single precision, flushing denormal results to zero."""
    import math
    if math.isnan(x):
        return 0x7FFFFFFF
    try:
        v = struct.unpack("<I", struct.pack("<f", x))[0]
    except OverflowError:
        v = 0x7F800000 | (0x80000000 if x < 0 else 0)
    if (v >> 23) & 0xFF == 0:
        v &= 0x80000000
    return v


def f64(hi, lo):
    """IEEE double from a register pair; denormals read as zero."""
    v = ((hi & M) << 32) | (lo & M)
    if (v >> 52) & 0x7FF == 0:
        return -0.0 if v >> 63 else 0.0
    return struct.unpack("<d", struct.pack("<Q", v))[0]


def bits64(x):
    import math
    if math.isnan(x):
        return 0x7FFFFFFFFFFFFFFF
    v = struct.unpack("<Q", struct.pack("<d", x))[0]
    if (v >> 52) & 0x7FF == 0:
        v &= 1 << 63
    return v


REST = {"cmpeq2", "cmpeq4", "cmpgt2", "cmpgtu4", "xpnd2", "xpnd4", "bitc4", "packh2", "packh4", "unpkhu4", "unpklu4", "spack2",
        "spacku4", "shru2", "subabs4", "addsub2", "saddsub", "saddsub2", "dotpn2", "dotpnrsu2", "dotprsu2", "dotpsu4", "dotpu4",
        "mpy2ir", "mpyhir", "mpylir", "smpy32", "rpack2", "sshvl", "sshvr", "cmpy", "cmpyr", "cmpyr1", "ddotp4", "ddotph2",
        "ddotph2r", "ddotpl2", "ddotpl2r", "deal", "shfl", "shfl3", "gmpy", "gmpy4", "xormpy", "mpyi", "mpyid"}
# 16 x 16 multiplies named by the halves they take: (src1 high, src1 signed, src2 high, src2 signed).
HALF_MULTIPLIES = {"mpyh": (True, True, True, True), "mpyhu": (True, False, True, False), "mpyhus": (True, False, True, True),
                   "mpyhsu": (True, True, True, False), "mpyhl": (True, True, False, True), "mpyhlu": (True, False, False, False),
                   "mpyhuls": (True, False, False, True), "mpyhslu": (True, True, False, False),
                   "mpyluhs": (False, False, True, True), "mpylshu": (False, True, True, False)}


def half(word, high, signed):
    """One 16-bit half of a 32-bit word."""
    part = word >> 16 if high else word & 0xFFFF
    return part - 0x10000 if signed and part & 0x8000 else part


def sat32(x):
    return max(-0x80000000, min(0x7FFFFFFF, x)) & M


# Double-precision instructions: delay slots (to the last result word) and the ones that read a DP source in
# a single cycle (SPRUFE8B pipeline tables).
DP_DELAY = {"mpysp2dp": 4, "mpyspdp": 6, "mpydp": 9, "adddp": 6, "subdp": 6, "intdp": 4, "intdpu": 4,
            "dptrunc": 3, "dpint": 3, "dpsp": 3, "cmpeqdp": 1, "cmpgtdp": 1, "cmpltdp": 1, "absdp": 1, "rcpdp": 1, "rsqrdp": 1}
DP_READ_ONCE = {"dptrunc", "dpint", "dpsp", "absdp", "rcpdp", "rsqrdp"}



def estimate(bits, width, root):
    """RCPSP/RCPDP (or RSQRSP/RSQRDP with `root`) of a normal number given as its bits. Only the top eight
    mantissa bits of the input are used (bench M3, RCP2); the result is the exact value for that input rounded to
    nearest at eight mantissa bits, lower bits zero (bench M2, step R1, claim HW-66; no result is a tie). A result too small for a normal number is a signed zero."""
    from math import isqrt
    fraction = 23 if width == 32 else 52
    field = width - 1 - fraction
    bias = (1 << (field - 1)) - 1
    sign = bits >> (width - 1) << (width - 1)
    one = 1 << fraction
    mantissa = ((bits & (one - 1)) | one) >> (fraction - 8) << (fraction - 8)
    exponent = (bits >> fraction & ((1 << field) - 1)) - bias
    if not root:
        top, out = (256, -exponent) if mantissa == one else (((1 << (fraction + 10)) + mantissa) // (2 * mantissa), -exponent - 1)
    else:
        odd = exponent & 1
        scaled = mantissa << odd
        out = -((exponent - odd) // 2)
        if scaled == one:
            top = 256
        else:                                   # the largest t with (2t - 1)^2 * scaled <= 2^(fraction + 20)
            top = (isqrt((1 << (fraction + 20)) // scaled) + 1) // 2
            while (2 * top + 1) ** 2 * scaled <= 1 << (fraction + 20):
                top += 1
            while (2 * top - 1) ** 2 * scaled > 1 << (fraction + 20):
                top -= 1
            out -= 1
    if top == 512:
        top, out = 256, out + 1
    if out + bias <= 0:
        return sign
    return sign | (out + bias) << fraction | (top - 256) << (fraction - 8)

class SimError(Exception):
    pass


class Returned(Exception):
    pass


class Memory:
    """Loaded sections with a byte overlay. Unmapped bytes read as 0."""

    def __init__(self, image):
        self.image = image
        self.overlay = {}

    def byte(self, address):
        if address in self.overlay:
            return self.overlay[address]
        b = self.image.byte(address)
        return 0 if b is None else b

    def read(self, address, size):
        return bytes(self.byte(address + i) for i in range(size))

    def write(self, address, data):
        for i, b in enumerate(data):
            self.overlay[address + i] = b

    def word(self, address, signed=False):
        v = struct.unpack("<I", self.read(address, 4))[0]
        return s32(v) if signed else v


class Program:
    """Decoded execute packets of one image: {first address: ([(address, text)], next address, protected)}."""

    def __init__(self, path):
        self.name, self.entry, self.sections, self.image = packets.load(path)
        self.text = packets.listing(self.sections, self.entry)
        self.cache = {}

    def raw(self, address):
        """(opcode, size in bytes) of the instruction at address."""
        unit = next(u for u in packets.fetch_packet(self.image, address) if u[0] == address)
        d, o = self.image.at(address, unit[1])
        return int.from_bytes(d[o:o + unit[1]], "little"), unit[1]

    def packet(self, address):
        if address in self.cache:
            return self.cache[address]
        out, a, prot = [], address, False
        while True:
            units = packets.fetch_packet(self.image, a)
            fp_prot = packets.protected(packets.header_of(self.image, a))   # PROT is per fetch packet
            unit = next((u for u in units if u[0] == a), None)
            if unit is None:
                raise SimError(f"{a:#010x} is not an instruction start")
            rest = units[units.index(unit):]
            for n, (addr, size, p) in enumerate(rest):
                t = self.text.get(addr)
                if t is None and size == 4 and self.image.word(addr) == 0:
                    t = "nop"           # objdump folds runs of zero words (NOP) into "..."
                if t is None:
                    raise SimError(f"no instruction text at {addr:#010x}")
                out.append((addr, t))
                prot |= fp_prot and bool(re.search(r"\bld\w+\b", t))   # a load in a PROT fetch packet
                if not p:
                    nxt = rest[n + 1][0] if n + 1 < len(rest) else (a & ~31) + 32
                    result = (out, nxt, prot)
                    self.cache[address] = result
                    return result
            a = (a & ~31) + 32


class Machine:
    def __init__(self, program, regs=None, hooks=None, trace=False):
        self.p = program
        self.mem = Memory(program.image)
        self.R = {"b3": RET, "b15": STACK, "gfpgfr": 0x0700001D}   # GMPY4's field after reset: 8 bits, polynomial 1Dh
        self.R.update(regs or {})
        self.hooks = hooks or {}
        self.trace = trace
        self.cyc = 0
        self.pending = []     # (cycle visible, register, value)
        self.late = []        # double-precision sources awaiting their second-cycle (high word) read
        self.branches = []    # (cycle taken, target)
        self.calls = []       # (site, target, a4, b4)
        self.residual = {}    # cycle -> SPLOOP epilog instructions still to issue from the loop buffer
        self.loopbuf = None   # the last SPLOOP's buffer: body, ii, dynlen, delay, predicate, reload condition
        self.hold = None      # (fetch stops from this cycle, resumes at this cycle) while a reload runs
        self.sample = None    # absolute cycle at which the reload condition is sampled
        self.sat_due = None   # cycle from which CSR.SAT reads as set (one cycle after a clipped result is written)
        self.sat_units = 0    # the SSR bits to set with it
        self.busy = 0         # the loop buffer still holds a draining or reloading invocation before this cycle
        self.isr = None       # address of the interrupt service routine; None: no interrupts
        self.irqs = []        # cycles at which an interrupt is requested, ascending; one is pending at a time
        self.taken = []       # (cycle, return address, SPLX) of each interrupt taken
        self.in_isr = False   # between taking an interrupt and its B IRP landing
        self.irq_block = 0    # no interrupt before this cycle (branch delay slots)
        self.iret = None      # the (cycle, target) of a B IRP in flight
        self.itsr_splx = False  # ITSR.SPLX: the interrupt drained a loop
        self.splx = False     # TSR.SPLX after a return: the next packet, if an SPLOOP, pipes the loop back up
        self.tsc_scale = 1    # TSCL reads cyc x this: tests of time-outs raise it so seconds take fewer cycles

    def apply_init_data(self, path):
        """Write the copy table's initialised data (what __TI_auto_init does before main) into memory."""
        import init_data
        for r in init_data.InitData(path).regions:
            if r["kind"] == "initialised":
                self.mem.write(r["start"], r["data"])

    # --- registers and operands -------------------------------------------------------------------
    def g(self, r):
        if r in ("ilc", "rilc", "csr", "ier", "irp", "nrp", "tsr"):
            return self.R.get("_" + r, 0) & M
        if r == "tscl":                      # the time-stamp counter: free-running at the CPU clock
            return (self.cyc * self.tsc_scale) & M
        if ":" in r:
            raise SimError(f"register pair {r} read as one register (use l40 or the pair halves)")
        return self.R.get(r, 0) & M

    def l40(self, x):
        """A source as a signed 40-bit value: a pair is bits 39-32 in the odd register's low 8 bits and bits
        31-0 in the even one (SPRUFE8B 2.2, Figure 2-2); a single register or constant is sign-extended."""
        if ":" in x:
            hi_, lo_ = x.split(":")
            v = self.g(lo_) | (self.g(hi_) & 0xFF) << 32
            return v - (1 << 40) if v >> 39 else v
        return s32(self.val(x))

    def w40(self, dst, v):
        """[(register, value)] writes of a 40-bit result to a pair; the odd register's upper 24 bits are zero."""
        hi_, lo_ = dst.split(":")
        v &= (1 << 40) - 1
        return [(lo_, v & M), (hi_, v >> 32)]

    def val(self, x):
        x = x.strip()
        return int(x) & M if NUM.fullmatch(x) else self.g(x)

    def ea(self, s, size):
        """Effective address and optional base update. (n) is a byte offset, [n] is scaled by size."""
        m = re.match(r"\*(\+\+|--|\+|-)?(\w+)(\+\+|--)?(?:\((-?\w+)\)|\[(-?\w+)\])?$", s)
        if not m:
            raise SimError("address mode " + s)
        pre, base, post, boff, ioff = m.groups()
        if boff is not None:
            off = int(boff) if NUM.fullmatch(boff) else s32(self.g(boff))
        elif ioff is not None:
            off = (int(ioff) if NUM.fullmatch(ioff) else s32(self.g(ioff))) * size
        else:
            off = size if (pre in ("++", "--") or post) else 0
        b = self.g(base)
        if pre in ("+", None) and not post:
            return (b + off) & M, None
        if pre == "-":
            return (b - off) & M, None
        if pre == "++":
            return (b + off) & M, (base, b + off)
        if pre == "--":
            return (b - off) & M, (base, b - off)
        return b, (base, (b + off) if post == "++" else (b - off))

    def dp_finish(self, e):
        """Pending writes (cycle visible, register, value) of a double-precision instruction whose source
        words have all been read: a pair result's low word one cycle before its high word."""
        ds, i = DP_DELAY[e["op"]], e["issue"]
        out = self.dp_result(e["op"], e["args"], e["lows"], e["highs"], e["singles"])
        if len(out) == 1:
            return [(i + ds + 1, out[0][0], out[0][1] & M)]
        (lo_, lv), (hi_, hv) = out
        return [(i + ds, lo_, lv & M), (i + ds + 1, hi_, hv & M)]

    def dp_result(self, op, args, lows, highs, singles):
        """(register, value) pairs of a double-precision instruction from its source words."""
        import math

        def dp(arg):
            return f64(highs[arg], lows[arg])
        dst = args[-1]
        if op in ("cmpeqdp", "cmpgtdp", "cmpltdp"):
            x, y = dp(args[0]), dp(args[1])
            return [(dst, int({"cmpeqdp": x == y, "cmpgtdp": x > y, "cmpltdp": x < y}[op]))]
        if op in ("dptrunc", "dpint", "dpsp"):
            x = dp(args[0])
            if op == "dpsp":
                r = bits32(x)
            elif math.isnan(x) or x >= 2147483648.0:
                r = 0x7FFFFFFF
            elif x < -2147483648.0:
                r = 0x80000000
            else:
                r = int(x) if op == "dptrunc" else int(round(x))
            return [(dst, r & M)]
        if op == "mpysp2dp":
            r = f32(singles[args[0]]) * f32(singles[args[1]])
        elif op == "mpyspdp":
            r = f32(singles[args[0]]) * dp(args[1])
        elif op in ("mpydp", "adddp", "subdp"):
            x, y = dp(args[0]), dp(args[1])
            r = x * y if op == "mpydp" else x + y if op == "adddp" else x - y
        elif op == "absdp":
            r = abs(dp(args[0]))
        elif op == "rsqrdp":                 # as RCPDP
            x = dp(args[0])
            if math.isnan(x) or x < 0:
                r = math.nan
            elif x == 0.0:
                r = math.copysign(math.inf, x)
            elif math.isinf(x):
                r = 0.0
            else:
                v = estimate(bits64(x), 64, True)
                h, l = dst.split(":")
                return [(l, v & M), (h, v >> 32)]
        elif op == "rcpdp":
            # Exponent exact, mantissa to 8 bits (SPRUFE8B RCPDP): the true reciprocal rounded to nearest at 8
            # mantissa bits, as the unit does (estimate()). Denormal or 0 -> signed
            # infinity, infinity -> signed 0, NaN -> NaN_out.
            x = dp(args[0])
            if math.isnan(x):
                r = math.nan
            elif x == 0.0:
                r = math.copysign(math.inf, x)
            elif math.isinf(x):
                r = math.copysign(0.0, x)
            else:
                v = estimate(bits64(x), 64, False)
                h, l = dst.split(":")
                return [(l, v & M), (h, v >> 32)]
        else:
            x = singles[args[0]]
            r = float(s32(x) if op == "intdp" else x)
        v = bits64(r)
        h, l = dst.split(":")
        return [(l, v & M), (h, v >> 32)]

    # --- one execute packet -----------------------------------------------------------------------
    def execute(self, ins, nxt, prot, skip_units=()):
        """Run one execute packet. Returns the call target if the packet holds a CALLP, else None."""
        writes, loads, call, extra, forever = [], [], None, 0, False
        delayed = []          # (register, value, delay slots)
        for a, t in ins:
            t = t.replace("||", "").strip()
            pred = None
            m = re.match(r"\[(!?)(\w+)\]\s*(.*)$", t)
            if m:
                pred, t = (m.group(1) == "!", m.group(2)), m.group(3)
            m = re.match(r"(\w+)(?:\s+\.(\w+))?\s*(.*)$", t)
            op, unit, rest = m.group(1), m.group(2) or "", m.group(3)
            if skip_units and unit[:2].upper() in skip_units:
                continue
            args = [x.strip() for x in re.split(r",(?![^(]*\))", rest)] if rest else []
            if op in ("b", "bnop", "bdec", "bpos", "callp"):
                self.irq_block = self.cyc + 6
            if pred is not None:
                taken = (self.g(pred[1]) != 0) != pred[0]
                if not taken:
                    if op == "bnop":
                        extra += int(args[1])
                    elif op == "addkpc" and len(args) > 2:   # its NOP cycles do not depend on the predicate
                        extra += int(args[2])
                    continue
            if self.trace:
                print(f"  {self.cyc:6d} {a:08x} {t}")
            if op == "nop":
                extra += (int(args[0]) if args else 1) - 1
            elif op == "idle":
                forever = True
            elif op in ("spmask", "spmaskr", "spkernel", "spkernelr", "dint", "rint"):
                pass
            elif op == "mvk":
                writes.append((args[1], int(args[0]) & M))
            elif op == "mvkh":
                writes.append((args[1], (self.g(args[1]) & 0xFFFF) | (int(args[0]) & 0xFFFF0000)))
            elif op in ("set", "clr"):
                if len(args) == 3:                  # register form: src1 bits 9-5 = csta, bits 4-0 = cstb
                    c = self.val(args[1])
                    args = [args[0], str((c >> 5) & 31), str(c & 31), args[2]]
                lo, hi = int(args[1]), int(args[2])
                if lo > hi:
                    raise SimError(f"bitfield bounds at {a:#010x}: {t}")
                mask = ((1 << (hi - lo + 1)) - 1) << lo
                v = self.val(args[0])
                writes.append((args[3], v | mask if op == "set" else v & ~mask))
            elif op in ("cmpeq", "cmpgt", "cmplt") and any(":" in x for x in args[:2]):
                x, y = self.l40(args[0]), self.l40(args[1])            # slong form: 40-bit signed compare
                writes.append((args[2], int({"cmpeq": x == y, "cmpgt": x > y, "cmplt": x < y}[op])))
            elif op in ("cmpgtu", "cmpltu") and any(":" in x for x in args[:2]):
                raise SimError(f"unsigned 40-bit compare not modelled at {a:#010x}: {t}")
            elif op in ("cmpeq", "cmpgt", "cmplt", "cmpgtu", "cmpltu"):
                x, y = self.val(args[0]), self.val(args[1])
                f = {"cmpeq": x == y, "cmpgt": s32(x) > s32(y), "cmplt": s32(x) < s32(y),
                     "cmpgtu": x > y, "cmpltu": x < y}[op]
                writes.append((args[2], int(f)))
            elif op == "addk":
                writes.append((args[1], self.g(args[1]) + int(args[0])))
            elif op in ("add", "sub") and ":" in args[2]:              # .L long forms: signed 40-bit result
                x, y = self.l40(args[0]), self.l40(args[1])
                writes += self.w40(args[2], x + y if op == "add" else x - y)
            elif op == "shl" and ":" in args[2] and ":" not in args[0]:  # 32-bit source, 40-bit result (xuint to ulong)
                writes += self.w40(args[2], self.val(args[0]) << min(self.val(args[1]) & 63, 40))
            elif op in ("shl", "shru", "shr") and ":" in args[0]:       # 40-bit src2 (SPRUFE8B SHL/SHR/SHRU)
                if ":" not in args[2]:
                    raise SimError(f"40-bit shift to one register at {a:#010x}: {t}")
                hi_, lo_ = args[0].split(":")
                x = self.g(lo_) | (self.g(hi_) & 0xFF) << 32
                n = min(self.val(args[1]) & 63, 40)                      # 39 < n < 64 shifts by 40
                if op == "shr" and x >> 39:
                    x -= 1 << 40
                writes += self.w40(args[2], x << n if op == "shl" else x >> n)
            elif op in ("and", "or", "xor", "add", "sub", "shl", "shru", "shr"):
                if ":" in args[2] or ":" in args[0] or ":" in args[1]:
                    raise SimError(f"register pair operand at {a:#010x}: {t}")
                x, y = self.val(args[0]), self.val(args[1])
                r = {"and": x & y, "or": x | y, "xor": x ^ y, "add": x + y, "sub": x - y,
                     "shl": x << (y & 63), "shru": x >> (y & 63), "shr": s32(x) >> (y & 63)}[op]
                writes.append((args[2], r & M))
            elif op == "subu":
                x, y = self.val(args[0]), self.val(args[1])
                r = (x - y) & ((1 << 40) - 1)
                hi_, lo_ = args[2].split(":")
                writes += [(lo_, r & M), (hi_, r >> 32)]
            elif op in ("ext", "extu"):
                if len(args) == 3:                  # register form: src1 bits 9-5 = csta, bits 4-0 = cstb
                    c = self.val(args[1])
                    args = [args[0], str((c >> 5) & 31), str(c & 31), args[2]]
                x, csta, cstb = self.val(args[0]), int(args[1]), int(args[2])
                v = (x << csta) & M
                writes.append((args[3], (s32(v) >> cstb if op == "ext" else v >> cstb) & M))
            elif op == "dmv":                                           # dst_o:dst_e = src1:src2
                h, l = args[2].split(":")
                writes += [(h, self.val(args[0])), (l, self.val(args[1]))]
            elif op == "mv":
                writes.append((args[1], self.val(args[0])))
            elif op == "mvc":
                v = self.g(args[0])
                if args[1] == "amr" and v:
                    raise SimError(f"AMR = {v:#x} (circular addressing) is not modelled at {a:#010x}")
                if args[1] in ("fadcr", "fmcr") and (v >> 9 & 3 or v >> 25 & 3):
                    raise SimError(f"{args[1].upper()} rounding mode {v:#x} is not modelled at {a:#010x}")
                writes.append(("_" + args[1] if args[1] in ("ilc", "rilc", "csr", "ier", "tsr") else args[1],
                               self.g(args[0])))
            elif op in ("ldw", "ldb", "ldbu", "ldh", "ldhu", "lddw", "ldndw", "ldnw"):
                size = {"ldw": 4, "ldb": 1, "ldbu": 1, "ldh": 2, "ldhu": 2, "lddw": 8, "ldndw": 8, "ldnw": 4}[op]
                addr, upd = self.ea(args[0], size)
                if upd:
                    writes.append(upd)
                if op not in ("ldnw", "ldndw"):
                    addr &= ~(size - 1)   # aligned forms ignore the low address bits (measured: M1 bench I4)
                raw = int.from_bytes(self.mem.read(addr, size), "little")
                if op in ("ldb", "ldh") and raw >> (8 * size - 1):
                    raw -= 1 << (8 * size)
                if size == 8:
                    hi_, lo_ = args[1].split(":")
                    loads += [(lo_, raw & M), (hi_, raw >> 32)]
                else:
                    loads.append((args[1], raw & M))
            elif op in ("stw", "stb", "sth", "stdw", "stndw", "stnw"):
                size = {"stw": 4, "stb": 1, "sth": 2, "stdw": 8, "stndw": 8, "stnw": 4}[op]
                addr, upd = self.ea(args[1], size)
                if upd:
                    writes.append(upd)
                if op not in ("stnw", "stndw"):
                    addr &= ~(size - 1)
                if size == 8:
                    hi_, lo_ = args[0].split(":")
                    v = self.g(lo_) | (self.g(hi_) << 32)
                else:
                    v = self.g(args[0])
                self.mem.write(addr, (v & ((1 << (8 * size)) - 1)).to_bytes(size, "little"))
            elif op == "addkpc":
                writes.append((args[1], int(args[0].split()[0], 16)))
                if len(args) > 2:
                    extra += int(args[2])
            elif op in ("b", "bnop"):
                tgt = args[0].split()[0]
                target = int(tgt, 16) if re.fullmatch(r"[0-9a-f]{8}", tgt) else self.g(tgt)
                self.branches.append((self.cyc + 6, target))
                if tgt == "irp":
                    self.iret = (self.cyc + 6, target)
                if op == "bnop":
                    extra += int(args[1])
            elif op == "callp":
                call = int(args[0].split()[0], 16)
                self.link = args[1] if len(args) > 1 else "b3"         # CALLP .S1 links in A3, .S2 in B3
                self.calls.append((a, call, self.g("a4"), self.g("b4")))
            elif op in ("addab", "addah", "addaw", "addad", "subab", "subah", "subaw"):
                sc = {"addab": 1, "addah": 2, "addaw": 4, "addad": 8, "subab": -1, "subah": -2, "subaw": -4}[op]
                writes.append((args[2], self.val(args[0]) + s32(self.val(args[1])) * sc))
            elif op in ("mpy", "mpyu", "mpysu", "mpyus"):            # 16 x 16, 1 delay slot
                x, y = self.val(args[0]) & 0xFFFF, self.val(args[1]) & 0xFFFF
                if op in ("mpy", "mpysu") and x & 0x8000:
                    x -= 0x10000
                if op in ("mpy", "mpyus") and y & 0x8000:
                    y -= 0x10000
                delayed.append((args[2], x * y, 1))
            elif op in ("mpy32", "mpy32u", "mpy32su", "mpy32us", "mpyli"):  # 3 delay slots
                x, y = self.val(args[0]), self.val(args[1])
                if op == "mpyli":
                    x = x & 0xFFFF
                    x, y = (x - 0x10000 if x & 0x8000 else x), s32(y)
                else:
                    if op in ("mpy32", "mpy32su"):
                        x = s32(x)
                    if op in ("mpy32", "mpy32us"):
                        y = s32(y)
                r = x * y
                if ":" in args[2]:
                    hi_, lo_ = args[2].split(":")
                    delayed += [(lo_, r & M, 3), (hi_, (r >> 32) & M, 3)]
                else:
                    delayed.append((args[2], r & M, 3))
            elif op == "mvd":
                delayed.append((args[1], self.val(args[0]), 3))
            elif op == "andn":
                writes.append((args[2], self.val(args[0]) & ~self.val(args[1])))
            elif op == "addu":
                if ":" not in args[2]:
                    raise SimError(f"addu form at {a:#010x}: {t}")
                if ":" in args[1]:
                    h, l = args[1].split(":")
                    y = self.g(l) | ((self.g(h) & 0xFF) << 32)
                else:
                    y = self.val(args[1])
                r = (self.val(args[0]) + y) & ((1 << 40) - 1)
                hi_, lo_ = args[2].split(":")
                writes += [(lo_, r & M), (hi_, r >> 32)]
            elif op == "rotl":                                          # rotl src2, src1, dst
                x, n = self.val(args[0]), self.val(args[1]) & 31
                delayed.append((args[2], ((x << n) | (x >> (32 - n))) & M if n else x, 1))
            elif op == "lmbd":
                bit, x = self.val(args[0]) & 1, self.val(args[1])
                n = 0
                while n < 32 and ((x >> (31 - n)) & 1) != bit:
                    n += 1
                writes.append((args[2], n))
            elif op == "norm":
                x = self.val(args[0])
                sign, n = x >> 31, 0
                while n < 31 and ((x >> (30 - n)) & 1) == sign:
                    n += 1
                writes.append((args[1], n))
            elif op == "abs":
                writes.append((args[1], sat32(abs(s32(self.val(args[0]))))))
            elif op == "subc":
                x, y = self.val(args[0]), self.val(args[1])
                writes.append((args[2], (((x - y) << 1) + 1) if x >= y else (x << 1)))
            elif op in ("pack2", "packhl2", "packlh2", "packl4"):
                x, y = self.val(args[0]), self.val(args[1])
                r = {"pack2": ((x & 0xFFFF) << 16) | (y & 0xFFFF),
                     "packhl2": (x & 0xFFFF0000) | (y & 0xFFFF),
                     "packlh2": ((x & 0xFFFF) << 16) | (y >> 16),
                     "packl4": ((x >> 16 & 0xFF) << 24) | ((x & 0xFF) << 16) | ((y >> 16 & 0xFF) << 8) | (y & 0xFF)}[op]
                writes.append((args[2], r))
            elif op == "sshl":
                x, n = s32(self.val(args[0])), self.val(args[1]) & 63
                writes.append((args[2], sat32(x << n) if n < 40 else (0 if x == 0 else sat32(x << 40))))
                if x << n != s32(sat32(x << n)):
                    self.clipped(unit)
            elif op in ("sadd", "ssub"):                                # to 32 bits, or to 40 when the result is a pair
                x, y = self.l40(args[0]), self.l40(args[1])
                r, wide = (x + y if op == "sadd" else x - y), ":" in args[2]
                low = -(1 << 39) if wide else -(1 << 31)
                kept = max(low, min(-low - 1, r))
                writes += self.w40(args[2], kept) if wide else [(args[2], kept & M)]
                if kept != r:
                    self.clipped(unit)
            elif op in HALF_MULTIPLIES:                                 # one half of each source, 1 delay slot
                h1, s1, h2, s2 = HALF_MULTIPLIES[op]
                delayed.append((args[2], (half(self.val(args[0]), h1, s1) * half(self.val(args[1]), h2, s2)) & M, 1))
            elif op in ("smpy", "smpyh", "smpyhl", "smpylh", "smpy2"):  # signed halves, doubled; 80000000h saturates
                x, y = self.val(args[0]), self.val(args[1])
                def doubled(h1, h2, slots):
                    p = half(x, h1, True) * half(y, h2, True) * 2
                    if p != 0x80000000:
                        return p & M
                    self.clipped(unit, slots)
                    return 0x7FFFFFFF
                if op == "smpy2":                                       # low halves to dst_e, high halves to dst_o, 3 delay slots
                    hi_, lo_ = args[2].split(":")
                    delayed += [(lo_, doubled(False, False, 3), 3), (hi_, doubled(True, True, 3), 3)]
                else:
                    delayed.append((args[2], doubled(op in ("smpyh", "smpyhl"), op in ("smpyh", "smpylh"), 1), 1))
            elif op in ("add2", "sub2", "sadd2", "ssub2", "saddus2", "saddsu2", "max2", "min2", "avg2"):   # per 16-bit half
                x, y, r = self.val(args[0]), self.val(args[1]), 0
                for high in (False, True):
                    p, q = half(x, high, True), half(y, high, True)
                    part = {"add2": p + q, "sub2": p - q, "sadd2": max(-32768, min(32767, p + q)), "ssub2": max(-32768, min(32767, p - q)),
                            "saddus2": max(0, min(65535, half(x, high, False) + q)), "saddsu2": max(0, min(65535, p + half(y, high, False))),
                            "max2": max(p, q), "min2": min(p, q), "avg2": (p + q + 1) >> 1}[op]
                    r |= (part & 0xFFFF) << (16 if high else 0)
                if op == "avg2":
                    delayed.append((args[2], r, 1))
                else:
                    writes.append((args[2], r))
            elif op in ("add4", "sub4", "saddu4", "avgu4", "maxu4", "minu4"):   # per unsigned byte
                x, y, r = self.val(args[0]), self.val(args[1]), 0
                for shift in (0, 8, 16, 24):
                    p, q = x >> shift & 0xFF, y >> shift & 0xFF
                    part = {"add4": p + q, "sub4": p - q, "saddu4": min(p + q, 255), "avgu4": (p + q + 1) >> 1,
                            "maxu4": max(p, q), "minu4": min(p, q)}[op]
                    r |= (part & 0xFF) << shift
                if op == "avgu4":
                    delayed.append((args[2], r, 1))
                else:
                    writes.append((args[2], r))
            elif op == "not":
                writes.append((args[1], ~self.val(args[0]) & M))
            elif op in REST:
                self.rest(op, args, unit, writes, delayed)
            elif op == "abs2":                                          # 8000h gives 7FFFh; SAT untouched
                x = self.val(args[0])
                writes.append((args[1], min(abs(half(x, True, True)), 32767) << 16 | min(abs(half(x, False, True)), 32767)))
            elif op == "bitr":                                          # 1 delay slot
                delayed.append((args[1], int(f"{self.val(args[0]):032b}"[::-1], 2), 1))
            elif op == "swap4":
                x = self.val(args[0])
                writes.append((args[1], (x & 0xFF00FF00) >> 8 | (x & 0x00FF00FF) << 8))
            elif op in ("shlmb", "shrmb"):                              # src2 moved a byte, the freed byte from src1
                x, y = self.val(args[0]), self.val(args[1])
                writes.append((args[2], ((y << 8) & M) | x >> 24 if op == "shlmb" else y >> 8 | ((x << 24) & M)))
            elif op in ("mpyu4", "mpysu4", "mpyus4"):                   # four byte products, 3 delay slots
                x, y = (self.val(args[1]), self.val(args[0])) if op == "mpyus4" else (self.val(args[0]), self.val(args[1]))
                parts = []
                for index in range(4):
                    p = x >> (index * 8) & 0xFF
                    if op != "mpyu4" and p & 0x80:
                        p -= 0x100                                      # MPYSU4: src1's bytes are signed
                    parts.append((p * (y >> (index * 8) & 0xFF)) & 0xFFFF)
                hi_, lo_ = args[2].split(":")
                delayed += [(lo_, parts[1] << 16 | parts[0], 3), (hi_, parts[3] << 16 | parts[2], 3)]
            elif op == "dpackx2":                                       # dst_e = lsb16(src1):msb16(src2), dst_o = lsb16(src2):msb16(src1)
                hi_, lo_ = args[2].split(":")
                x, y = self.val(args[0]), self.val(args[1])
                writes += [(hi_, ((y << 16) & M) | x >> 16), (lo_, ((x << 16) & M) | y >> 16)]
            elif op in ("addsp", "subsp", "mpysp"):                     # 3 delay slots
                x, y = f32(self.val(args[0])), f32(self.val(args[1]))
                delayed.append((args[2], bits32(x + y if op == "addsp" else x - y if op == "subsp" else x * y), 3))
            elif op in ("intsp", "intspu"):
                x = self.val(args[0])
                delayed.append((args[1], bits32(float(s32(x) if op == "intsp" else x)), 3))
            elif op in ("sptrunc", "spint"):
                import math
                x = f32(self.val(args[0]))
                if math.isnan(x) or x >= 2147483648.0:
                    r = 0x7FFFFFFF
                elif x < -2147483648.0:
                    r = 0x80000000
                else:
                    r = int(x) if op == "sptrunc" else int(round(x))  # round(): nearest, ties to even
                delayed.append((args[1], r & M, 3))
            elif op in ("cmpgtsp", "cmpltsp", "cmpeqsp"):
                x, y = f32(self.val(args[0])), f32(self.val(args[1]))
                writes.append((args[2], int({"cmpgtsp": x > y, "cmpltsp": x < y, "cmpeqsp": x == y}[op])))
            elif op == "abssp":
                v = self.val(args[0])
                writes.append((args[1], 0 if (v >> 23) & 0xFF == 0 else v & 0x7FFFFFFF))
            elif op in ("rcpsp", "rsqrsp"):
                # TI specifies only the exponent and 8 mantissa bits (a Newton-Raphson seed, SPRUFE8B RCPSP /
                # RSQRSP): the true value rounded to nearest at 8 bits, as the unit does (estimate()).
                import math
                x = f32(self.val(args[0]))
                if math.isnan(x):
                    r = 0x7FFFFFFF                                      # NaN_out
                elif x == 0.0:
                    r = 0x7F800000 | (0x80000000 if math.copysign(1, x) < 0 else 0)
                elif math.isinf(x):
                    r = 0x80000000 if x < 0 else 0
                elif op == "rsqrsp" and x < 0:
                    r = 0x7FFFFFFF
                else:
                    r = estimate(bits32(x), 32, op == "rsqrsp")
                writes.append((args[1], r))
            elif op == "spdp":                                          # 1 delay slot
                x = f32(self.val(args[0]))
                v = 0x7FFFFFFFFFFFFFFF if x != x else struct.unpack("<Q", struct.pack("<d", x))[0]   # a NaN gives NaN_out
                hi_, lo_ = args[1].split(":")
                delayed += [(lo_, v & M, 0), (hi_, v >> 32, 1)]               # dst_l in E1, dst_h in E2
            elif op in DP_DELAY:
                # Double-precision operands and results move one word per cycle (SPRUFE8B pipeline tables):
                # most readers take a source's low word in E1 and its high word in E2 (MPYDP: src1's high word
                # in E3), DPSP, DPTRUNC, DPINT, ABSDP and RCPDP take both in E1; a pair result has its low
                # word written one cycle before its high word. High words due later are read in tick(), after
                # that cycle's earlier writes have landed (self.late).
                lows, highs, due = {}, {}, {}
                for k, arg in enumerate(args[:-1]):
                    if ":" in arg:
                        hi_, lo_ = arg.split(":")
                        lows[arg] = self.g(lo_)
                        if op in DP_READ_ONCE:
                            highs[arg] = self.g(hi_)
                        else:
                            due[arg] = self.cyc + (2 if op == "mpydp" and k == 0 else 1)
                singles = {arg: self.val(arg) for arg in args[:-1] if ":" not in arg}
                entry = {"issue": self.cyc, "op": op, "args": list(args), "lows": lows, "highs": highs,
                         "due": due, "singles": singles}
                if due:
                    self.late.append(entry)
                else:
                    self.pending += self.dp_finish(entry)
            elif op == "sat":                                           # 40-bit to 32-bit, saturating
                writes.append((args[1], sat32(self.l40(args[0]))))
                if self.l40(args[0]) != s32(sat32(self.l40(args[0]))):
                    self.clipped(unit)
            elif op == "dpack2":                                        # dst_e = low halves, dst_o = high halves
                hi_, lo_ = args[2].split(":")
                x, y = self.val(args[0]), self.val(args[1])
                writes += [(hi_, (x & 0xFFFF0000) | (y >> 16)), (lo_, ((x << 16) & M) | (y & 0xFFFF))]
            elif op == "addsub":                                        # dst_o = src1 + src2, dst_e = src1 - src2
                hi_, lo_ = args[2].split(":")
                x, y = self.val(args[0]), self.val(args[1])
                writes += [(hi_, (x + y) & M), (lo_, (x - y) & M)]
            elif op in ("mpylh", "mpylhu"):                             # lsb16(src1) x msb16(src2), 1 delay slot
                x, y = self.val(args[0]) & 0xFFFF, self.val(args[1]) >> 16
                if op == "mpylh":
                    x, y = (x - 0x10000 if x & 0x8000 else x), (y - 0x10000 if y & 0x8000 else y)
                delayed.append((args[2], (x * y) & M, 1))
            elif op in ("dotp2", "mpy2"):                               # signed packed halves, 3 delay slots
                h = [(v - 0x10000 if v & 0x8000 else v) for w in (self.val(args[0]), self.val(args[1])) for v in (w >> 16, w & 0xFFFF)]
                hi_p, lo_p = h[0] * h[2], h[1] * h[3]                   # a_hi x b_hi, a_lo x b_lo
                if op == "mpy2":                                        # dst_e = low product, dst_o = high product
                    hi_, lo_ = args[2].split(":")
                    delayed += [(lo_, lo_p & M, 3), (hi_, hi_p & M, 3)]
                elif ":" in args[2]:                                    # 64-bit sum, sign-extended
                    hi_, lo_ = args[2].split(":")
                    delayed += [(lo_, (hi_p + lo_p) & M, 3), (hi_, ((hi_p + lo_p) >> 32) & M, 3)]
                else:
                    delayed.append((args[2], (hi_p + lo_p) & M, 3))
            elif op == "mpyhi":                                         # msb16(src1) x src2, 64-bit, 3 delay slots
                x, y = self.val(args[0]) >> 16, s32(self.val(args[1]))
                r = ((x - 0x10000) if x & 0x8000 else x) * y
                hi_, lo_ = args[2].split(":")
                delayed += [(lo_, r & M, 3), (hi_, (r >> 32) & M, 3)]
            elif op == "shr2":                                          # packed signed 16-bit shifts right
                x, n = self.val(args[0]), self.val(args[1]) & 31
                h = [((x >> k) & 0xFFFF) for k in (16, 0)]
                h = [((v - 0x10000) if v & 0x8000 else v) >> n for v in h]
                writes.append((args[2], ((h[0] & 0xFFFF) << 16) | (h[1] & 0xFFFF)))
            elif op == "bdec":                                          # if dst >= 0: branch, dst -= 1
                if s32(self.g(args[1])) >= 0:
                    self.branches.append((self.cyc + 6, int(args[0].split()[0], 16)))
                    writes.append((args[1], self.g(args[1]) - 1))
            else:
                raise SimError(f"unhandled instruction at {a:#010x}: {t}")
        for r, v in writes:
            self.R[r] = v & M
        self.pending += [(self.cyc + 5, r, v) for r, v in loads]
        self.pending += [(self.cyc + ds + 1, r, v & M) for r, v, ds in delayed]
        if prot and any(re.search(r"\bld\w+\b", t) for _, t in ins):
            extra = max(extra, 4)       # PROT: four NOP cycles after each load (SPRUFE8B 3.10, header bit 20)
        # SPRUFE8B 5.5.4: a multicycle NOP is interrupted like any instruction; once its first cycle has run
        # the return address is the next packet's and the rest of it is dropped. IDLE is one with no end.
        while extra or forever:
            if self.irq_ready(self.cyc + 1):
                break
            if not extra and not (self.isr is not None and self.irqs and not self.in_isr):
                raise SimError(f"IDLE at cycle {self.cyc} with no interrupt to end it")
            self.idle(1)
            extra -= bool(extra)
        return call

    def rest(self, op, args, unit, writes, delayed):
        """The packed and fixed-point instructions no compiler has emitted here (SPRUFE8B); see the core for each."""
        def sat(v):
            kept = max(-(1 << 31), min((1 << 31) - 1, v))
            if kept != v:
                clip.append(1)
            return kept
        clip, slots, dst = [], 0, args[-1]
        if ":" in args[0]:                                  # DDOTPH2 / DDOTPL2: a pair source
            odd, even = (self.g(r) for r in args[0].split(":"))
            y = self.val(args[1])
            h2, l2 = half(y, True, True), half(y, False, True)
            top = half(odd, True, True) * h2 + half(odd, False, True) * l2
            middle = half(odd, False, True) * h2 + half(even, True, True) * l2
            bottom = half(even, True, True) * h2 + half(even, False, True) * l2
            first, second = (top, middle) if op in ("ddotph2", "ddotph2r") else (middle, bottom)
            slots = 3
            if op in ("ddotph2", "ddotpl2"):
                out = [sat(second) & M, sat(first) & M]
            else:
                out = ((sat(first + 0x8000) & 0xFFFF0000) | (sat(second + 0x8000) & M) >> 16) & M
        else:
            x = self.val(args[0])
            y = self.val(args[1]) if len(args) > 2 else 0
            sx, sy = s32(x), s32(y)
            xh, xl, yh, yl = half(x, True, True), half(x, False, True), half(y, True, True), half(y, False, True)
            xb, yb = [x >> s & 0xFF for s in (0, 8, 16, 24)], [y >> s & 0xFF for s in (0, 8, 16, 24)]
            s8 = lambda v: v - 256 if v & 0x80 else v
            if op in ("cmpeq2", "cmpgt2"):
                out = sum((half(x, h, False) == half(y, h, False) if op == "cmpeq2" else half(x, h, True) > half(y, h, True)) << h for h in (0, 1))
            elif op in ("cmpeq4", "cmpgtu4"):
                out = sum((p == q if op == "cmpeq4" else p > q) << i for i, (p, q) in enumerate(zip(xb, yb)))
            elif op == "subabs4":
                out = sum(abs(p - q) << (8 * i) for i, (p, q) in enumerate(zip(xb, yb)))
            elif op == "xpnd2":
                out, slots = (0xFFFF0000 if x & 2 else 0) | (0xFFFF if x & 1 else 0), 1
            elif op == "xpnd4":
                out, slots = sum(0xFF << (8 * i) for i in range(4) if x >> i & 1), 1
            elif op == "bitc4":
                out, slots = sum(bin(p).count("1") << (8 * i) for i, p in enumerate(xb)), 1
            elif op == "packh2":
                out = (x & 0xFFFF0000) | y >> 16
            elif op == "packh4":
                out = xb[3] << 24 | xb[1] << 16 | yb[3] << 8 | yb[1]
            elif op == "unpkhu4":
                out = xb[3] << 16 | xb[2]
            elif op == "unpklu4":
                out = xb[1] << 16 | xb[0]
            elif op == "spack2":
                out = (max(-32768, min(32767, sx)) & 0xFFFF) << 16 | (max(-32768, min(32767, sy)) & 0xFFFF)
            elif op == "spacku4":
                out = sum(max(0, min(255, v)) << s for v, s in ((xh, 24), (xl, 16), (yh, 8), (yl, 0)))
            elif op == "shru2":
                n = y & 31
                out = 0 if n >= 16 else (x >> 16 >> n) << 16 | (x & 0xFFFF) >> n
            elif op == "saddsub":
                out = [sat(sx - sy) & M, sat(sx + sy) & M]
            elif op in ("addsub2", "saddsub2"):
                lim = (lambda v: max(-32768, min(32767, v))) if op == "saddsub2" else (lambda v: v)
                out = [(lim(xh - yh) & 0xFFFF) << 16 | (lim(xl - yl) & 0xFFFF), (lim(xh + yh) & 0xFFFF) << 16 | (lim(xl + yl) & 0xFFFF)]
            elif op == "dotpn2":
                out, slots = (xh * yh - xl * yl) & M, 3
            elif op in ("dotprsu2", "dotpnrsu2"):
                high, low = xh * half(y, True, False), xl * half(y, False, False)
                out, slots = (((high + low if op == "dotprsu2" else high - low) + 0x8000) >> 16) & M, 3
            elif op in ("dotpu4", "dotpsu4"):
                out, slots = sum((p if op == "dotpu4" else s8(p)) * q for p, q in zip(xb, yb)) & M, 3
            elif op in ("mpyhir", "mpylir"):
                out, slots = (((xh if op == "mpyhir" else xl) * sy + 0x4000) >> 15) & M, 3
            elif op == "mpy2ir":
                parts = []
                for factor in (xl, xh):
                    if factor == -32768 and y == 0x80000000:
                        parts.append(0x7FFFFFFF); clip.append(1)
                    else:
                        parts.append(((factor * sy + 0x4000) >> 15) & M)
                out, slots = parts, 3
            elif op == "smpy32":
                slots = 3
                if x == y == 0x80000000:
                    out = 0x7FFFFFFF; clip.append(1)
                else:
                    out = ((sx * sy * 2) >> 32) & M
            elif op == "rpack2":
                out = (sat(sx * 2) & 0xFFFF0000) | (sat(sy * 2) & M) >> 16
            elif op in ("sshvl", "sshvr"):
                count = max(-31, min(31, sy))
                count, slots = (-count if op == "sshvr" else count), 1
                out = (sat(sx << count) if count >= 0 else sx >> -count) & M
            elif op in ("cmpy", "cmpyr", "cmpyr1"):
                imaginary, real, slots = sat(xl * yh + xh * yl), sat(xh * yh - xl * yl), 3
                if op == "cmpy":
                    out = [imaginary & M, real & M]
                else:
                    rounded = (lambda v: (sat(v + 0x8000) & M) >> 16) if op == "cmpyr" else (lambda v: (sat((v + 0x4000) * 2) & M) >> 16)
                    low = rounded(imaginary)
                    out = rounded(real) << 16 | low
            elif op == "ddotp4":
                out, slots = [(xh * s8(yb[1]) + xl * s8(yb[0])) & M, (xh * s8(yb[3]) + xl * s8(yb[2])) & M], 3
            elif op == "deal":
                out, slots = sum((x >> (2 * i) & 1) << i | (x >> (2 * i + 1) & 1) << (16 + i) for i in range(16)), 1
            elif op == "shfl":
                out, slots = sum((x >> i & 1) << (2 * i) | (x >> (16 + i) & 1) << (2 * i + 1) for i in range(16)), 1
            elif op == "shfl3":
                wide = sum((y >> i & 1) << (3 * i) | (x >> i & 1) << (3 * i + 1) | (x >> (16 + i) & 1) << (3 * i + 2) for i in range(16))
                out = [wide & M, wide >> 32]
            elif op in ("gmpy", "xormpy"):
                polynomial = 0 if op == "xormpy" else self.g("gplyb" if unit[:2].upper() == "M2" else "gplya")
                pp, mask = 0, 0x100
                while mask > 1:
                    if y & mask:
                        pp ^= x
                    pp = (polynomial ^ (pp << 1)) & M if pp & 0x80000000 else (pp << 1) & M
                    mask >>= 1
                out, slots = (pp ^ x if y & 1 else pp), 3
            elif op == "gmpy4":
                control = self.g("gfpgfr")
                size = (control >> 24 & 7) + 1
                polynomial, out, slots = (control & 0xFF) | 1 << size, 0, 3
                for i, (p, q) in enumerate(zip(xb, yb)):
                    product = 0
                    for bit in range(8):
                        if q >> bit & 1:
                            product ^= p << bit
                    for bit in range(14, size - 1, -1):
                        if product >> bit & 1:
                            product ^= polynomial << (bit - size)
                    out |= (product & 0xFF) << (8 * i)
            elif op == "mpyi":
                out, slots = (x * y) & M, 8
            elif op == "mpyid":
                wide = (sx * sy) & ((1 << 64) - 1)
                hi_, lo_ = dst.split(":")
                delayed += [(lo_, wide & M, 8), (hi_, wide >> 32, 9)]
                return
            else:
                raise SimError(f"unhandled instruction {op}")
        if isinstance(out, list):                           # [even, odd]
            hi_, lo_ = dst.split(":")
            rows = [(lo_, out[0] & M), (hi_, out[1] & M)]
        else:
            rows = [(dst, out & M)]
        if slots:
            delayed += [(reg, value, slots) for reg, value in rows]
        else:
            writes += rows
        if clip:
            self.clipped(unit, slots)

    def clipped(self, unit, slots=0):
        """A saturating instruction on `unit` with `slots` delay slots clipped its result: CSR.SAT and the unit's
        SSR bit follow the result by one cycle."""
        due = self.cyc + slots + 2
        self.sat_due = due if self.sat_due is None else min(self.sat_due, due)
        self.sat_units |= {"L1": 1, "L2": 2, "S1": 4, "S2": 8, "M1": 16, "M2": 32}.get(unit[:2].upper(), 0)

    def tick(self):
        self.cyc += 1
        if self.sat_due is not None and self.cyc >= self.sat_due:
            self.R["_csr"] = self.g("csr") | 0x200
            self.R["ssr"] = self.g("ssr") | self.sat_units
            self.sat_due, self.sat_units = None, 0
        for item in [p for p in self.pending if p[0] <= self.cyc]:
            self.R[item[1]] = item[2]
            self.pending.remove(item)
        waiting = []
        for e in self.late:
            for arg, cycle in list(e["due"].items()):
                if cycle <= self.cyc:
                    e["highs"][arg] = self.g(arg.split(":")[0])
                    del e["due"][arg]
            if e["due"]:
                waiting.append(e)
            else:
                self.pending += self.dp_finish(e)
        self.late = waiting
        if self.sample == self.cyc:
            self.loopbuf["reload"] = self.predicate()
            self.sample = None

    def predicate(self):
        lb = self.loopbuf
        return (self.g(lb["preg"]) != 0) != lb["neg"]

    def idle(self, n):
        """n cycles with no program packet (multi-cycle NOP, CALLP wait); epilog instructions still issue."""
        for _ in range(n):
            self.tick()
            extra = self.residual.pop(self.cyc, None)
            if extra:
                self.execute(extra, None, False)

    # --- software-pipelined loops (TI SPRUFE8B chapter 7) ------------------------------------------
    def spkernel_delay(self, address, ii):
        """Post-epilog fetch delay in cycles, fstg * ii + fcyc, decoded from the opcode (Table 3-29).

        Decoded from the raw bits rather than objdump's text: binutils 2.42 assembles the compact (Uspk)
        field in a different bit order from Figure H-7, so e.g. 0x1C67 (fstg 1 at ii 1) prints as
        'spkernel 32,0'. Its 32-bit decoding agrees with the table.
        """
        op, size = self.p.raw(address)
        if size == 4:
            field = (op >> 22) & 0x3F
        else:
            field = ((op >> 7) & 7) | (((op >> 14) & 3) << 3) | ((op & 1) << 5)
        cbits = 0 if ii <= 1 else 1 if ii <= 2 else 2 if ii <= 4 else 3 if ii <= 8 else 4
        fcyc = field & ((1 << cbits) - 1)
        fstg = sum(((field >> (5 - j)) & 1) << j for j in range(6 - cbits))
        return fstg * ii + fcyc

    def sploop(self, ins, nxt, prot, resumed=False):
        """Run a SPLOOP(D/W) from its execute packet; return the address of the code that runs next.

        Iterations start every ii cycles (body cycle 0 is the cycle after the SPLOOP packet). SPLOOP: the
        initial test and every stage boundary end the loop when ILC is 0, else decrement it. SPLOOPD: no
        test at the start or at boundaries in the first 3 cycles, so ILC + 1 + 3 // ii iterations
        (Table 7-4). SPLOOPW: ends at a stage boundary when its predicate was false 4 cycles earlier, and the
        epilog is skipped. Post-SPLOOP code starts at min(buffer idle, termination boundary + SPKERNEL delay) and the
        rest of the epilog issues alongside it. SPMASK'd instructions run on the first (loading) pass only.
        SPKERNELR: delay 0, and the reload starts with the post-SPLOOP code.

        An interrupt accepted on a stage boundary (7.13.1) starts no further iteration and does not count
        that boundary in ILC; when the started iterations have finished it is taken with IRP = this packet,
        and the routine's address is returned. `resumed`: the return from that interrupt (7.13.2).
        """
        packet_address = ins[0][0]
        kind_text = next(t for _, t in ins if re.search(r"\bsploop\w*\b", t))
        m = re.match(r"(?:\[(!?)(\w+)\]\s*)?(sploop\w*)\s+(\d+)", kind_text.replace("||", "").strip())
        neg, preg, kind, ii = m.group(1) == "!", m.group(2), m.group(3), int(m.group(4))
        if kind == "sploopw" and not preg:
            raise SimError("SPLOOPW must be predicated")
        nested = preg is not None and kind != "sploopw"
        if resumed:
            if kind == "sploopd":
                kind = "sploop"                     # 7.13.2: tests and counts like an SPLOOP
        else:                                       # on a return the packet itself executes nothing
            self.execute([(a, t) for a, t in ins if "sploop" not in t], nxt, prot)
        body, a, off, delay, kr = [], nxt, 0, 0, False
        while True:
            pins, pnxt, pprot = self.p.packet(a)
            masks, instrs, length, ker = set(), [], 1, None
            for addr, t in pins:
                tt = t.replace("||", "").strip()
                mm = re.match(r"spmask(r?)\s*(.*)$", tt)
                if mm:
                    if mm.group(1):
                        raise SimError("SPMASKR inside a loop body")
                    masks |= {u.strip().upper() for u in mm.group(2).split(",") if u.strip()}
                elif re.match(r"spkernel(r?)\b", tt):
                    ker, kr = addr, tt.startswith("spkernelr")
                    if kr and not nested:
                        raise SimError(f"SPKERNELR at {addr:#010x} without a conditional SPLOOP(D)")
                elif re.match(r"nop\b", tt):
                    nm = re.match(r"nop\s+(\d+)", tt)
                    length = max(length, int(nm.group(1)) if nm else 1)
                else:
                    instrs.append((addr, t))
                    if pprot and re.match(r"(\[!?\w+\]\s*)?ld\w+\b", tt):
                        length = max(length, 5)     # protected load: 4 NOP cycles in the body too
            body.append((off, instrs, pprot, masks))
            off += length
            a = pnxt
            if ker is not None:
                delay = 0 if kr else self.spkernel_delay(ker, ii)
                break
        L, after = off, a
        llb = -(-L // ii) * ii                      # last loading stage boundary
        ilc = self.g("ilc")
        loading_only = False
        if kind == "sploop":
            if ilc == 0:
                loading_only = True                 # zero iterations: only SPMASK'd instructions run
            else:
                ilc -= 1
        started, term, t0, wstop = 1, None, self.cyc + 1, False
        self.loopbuf = dict(body=body, ii=ii, L=L, llb=llb, delay=delay, after=after, preg=preg, neg=neg,
                            nested=nested, reload=False, kr=kr)
        history = []                                # SPLOOP predicate at the start of each loop cycle

        def issued(tt):
            """The buffer's instructions for body cycle tt. SPMASK'd ones were set-up code: they run in the
            loading pass only, and not at all when the loop is piped up again after an interrupt."""
            out = []
            for o, instrs, _, masks in body:
                k, r = divmod(tt - o, ii)
                if tt >= o and r == 0 and k < started:
                    for x in instrs:
                        masked = self.unit_of(x[1]) in masks
                        if (masked and not resumed) if loading_only else not (masked and (k or resumed)):
                            out.append(x)
            return out

        self.tick()
        t = 0
        drain = None                                # (boundary that accepted the interrupt, buffer empty)
        while True:
            if self.cyc > getattr(self, "limit", float("inf")):
                raise SimError(f"cycle limit reached inside the SPLOOP at {nxt:#010x}")
            if preg is not None:
                history.append(self.predicate())
            boundary = t > 0 and t % ii == 0
            if (drain is None and term is None and boundary and t >= llb and (kind == "sploop" or t > 3)
                    and not loading_only and not wstop and self.irq_ready()
                    and (history[t - 4] if kind == "sploopw" else ilc >= llb // ii)):
                drain = (t, max((started - 1) * ii + L, t))
            if drain is not None:
                if kind == "sploopw" and boundary and t > drain[0] and not history[t - 4]:
                    if self.irq_ready():            # 7.10.3: ended while draining, interrupted after the body
                        self.interrupt(after, False)
                        return self.isr
                    return after
                if t >= drain[1]:
                    if kind != "sploopw":
                        self.R["_ilc"] = ilc
                    if not self.irq_ready():
                        raise SimError("the interrupt was withdrawn while the loop buffer drained for it")
                    self.interrupt(packet_address, True)
                    return self.isr
            elif boundary and term is None:
                if kind == "sploopw":
                    # 7.10.2: the condition is the one read 3 cycles before the boundary, i.e. the register
                    # as it stood at the start of body cycle t - 4, so there is no test in the first 3
                    # cycles. cl6x relies on this: it sets the condition register exactly 5 cycles before
                    # the boundary that must act on it, and later stages of the last iterations still run
                    # (found 2026-11-16 with a compiled do-while dot product, ii 3). A condition that ends
                    # the loop while its body is still loading takes effect at the last loading stage
                    # boundary: iterations keep starting until then and there is no epilog (7.10, Figure 7-9).
                    if t > 3 and (wstop or not history[t - 4]):
                        if t >= llb:
                            term = t
                        else:
                            wstop = True
                elif loading_only:
                    term = 0
                elif kind == "sploopd" and t <= 3:
                    pass
                elif ilc == 0:
                    term = t
                else:
                    ilc -= 1
                if term is None:
                    started += 1
            if loading_only and term is None:
                term = 0
            if term is not None:
                if kind == "sploopw":
                    post, idle = term, term
                else:
                    idle = max((started - 1) * ii + L, llb)
                    post = min(idle, max(term, llb) + delay)
                if t >= post:
                    break
            issue = issued(t)
            if issue:
                self.execute(issue, None, False)
            self.tick()
            t += 1
        if kind != "sploopw" and not loading_only:
            for tt in range(post, idle):            # the epilog left over runs alongside the post code
                self.residual.setdefault(t0 + tt, []).extend(issued(tt))
            if post < idle:
                self.busy = max(self.busy, t0 + idle)
        if kind != "sploopw":
            self.R["_ilc"] = ilc
        if nested:
            if loading_only or term < 4:
                raise SimError("reload condition of a zero-iteration or very short nested SPLOOP is not modelled")
            self.loopbuf["reload"] = history[term - 4]
            if kr:
                self.reload(after, start=self.cyc)
        return after

    @staticmethod
    def buffer_schedule(lb, ilc):
        """A reloaded invocation, from its first cycle: ({cycle: instructions}, term, post, idle).

        One iteration is started at once and ILC (= RILC - 1) is tested and decremented at each stage
        boundary, as in SPLOOP (7.9.6.2). SPMASK'd instructions were never loaded, so they never issue.
        """
        body, ii, L, llb, delay = lb["body"], lb["ii"], lb["L"], lb["llb"], lb["delay"]
        started, t = 1, 0
        while True:
            t += 1
            if t % ii == 0:
                if ilc == 0:
                    break
                ilc -= 1
                started += 1
        term = t
        idle = max((started - 1) * ii + L, llb)
        post = min(idle, max(term, llb) + delay)
        issues = {}
        for tt in range(idle):
            for o, instrs, _, masks in body:
                k, r = divmod(tt - o, ii)
                if tt >= o and r == 0 and k < started:
                    issues.setdefault(tt, []).extend(x for x in instrs if self_unit(x[1]) not in masks)
        return issues, term, post, idle

    def reload(self, packet_address, start=None):
        """The reload point of a nested loop: an SPMASKR in the post-loop code (the new invocation starts on the
        next cycle) or, for a loop ended by SPKERNELR, the first epilog cycle (`start` = this cycle). Nothing
        happens unless the reload condition holds. RILC is read now; 0 skips the invocation."""
        lb = self.loopbuf
        if lb is None or not lb["nested"]:
            raise SimError(f"SPMASKR at {packet_address:#010x} without a conditional SPLOOP(D)")
        if start is None and lb["kr"]:
            raise SimError(f"SPMASKR at {packet_address:#010x} after a loop that reloads by SPKERNELR")
        if not lb["reload"]:
            return
        if start is None:
            start = self.cyc + 1
        rilc = self.g("rilc")
        if rilc == 0:                               # skipped: NOPs until the last reloading stage boundary
            issues, term, post, idle = {}, lb["llb"], lb["llb"], lb["llb"]
        else:
            issues, term, post, idle = self.buffer_schedule(lb, rilc - 1)
        if term < 4:
            raise SimError("reload condition of a very short reloaded SPLOOP is not modelled")
        for tt, instrs in issues.items():
            self.residual.setdefault(start + tt, []).extend(instrs)
        self.hold = (start + lb["L"], start + post)
        self.busy = max(self.busy, start + idle)
        lb["reload"] = False                       # sampled again for this invocation
        self.sample = start + term - 4
        if self.sample == self.cyc:                # this cycle's tick has already happened
            lb["reload"], self.sample = self.predicate(), None
        self.R["_ilc"] = 0

    # --- one maskable interrupt, for checking loops (TI SPRUFE8B 7.13) ---------------------------------
    def irq_ready(self, cyc=None):
        """A requested interrupt can be taken now (or at `cyc`): not in the routine, no branch in flight or in
        its delay slots, no loop buffer still draining, reloading or waiting for its SPMASKR."""
        cyc = self.cyc if cyc is None else cyc
        return (self.isr is not None and not self.in_isr and bool(self.irqs) and self.irqs[0] <= cyc
                and not self.branches and cyc >= self.irq_block and cyc >= self.busy
                and not self.hold and not (self.loopbuf and self.loopbuf["reload"]))

    def interrupt(self, pc, splx):
        """Take the pending interrupt: IRP = pc, ITSR.SPLX = splx, 9 cycles before the routine's first packet."""
        self.taken.append((self.cyc, pc, splx))
        self.irqs.pop(0)
        self.R["_irp"], self.itsr_splx, self.in_isr = pc, splx, True
        self.idle(9)

    @staticmethod
    def unit_of(text):
        return self_unit(text)

    # --- driver -------------------------------------------------------------------------------------
    def run(self, start, max_cycles=200000):
        self.limit = max_cycles
        pc = start
        while self.cyc < max_cycles:
            if self.hold and self.cyc >= self.hold[0]:
                while self.cyc < self.hold[1]:      # fetch disabled: the buffer runs alone
                    extra = self.residual.pop(self.cyc, None)
                    if extra:
                        self.execute(extra, None, False)
                    self.tick()
                self.hold = None
                if self.loopbuf["kr"] and self.loopbuf["reload"]:
                    self.reload(pc, start=self.cyc)     # SPKERNELR: the next reload starts with the post code
            if self.irq_ready():
                self.interrupt(pc, self.splx)
                self.splx = False
                pc = self.isr
                continue
            if pc in self.hooks and not self.branches and not self.pending:
                pc = self.hooks[pc](self)
                if pc == RET:
                    return self.R.get("a4", 0) & M
                continue
            ins, nxt, prot = self.p.packet(pc)
            resumed, self.splx = self.splx, False
            buffered = self.residual.pop(self.cyc, None)
            spmaskr = False
            masked = set()
            for _, t in ins:
                mm = re.match(r"(?:\|\|)?\s*spmask(r?)\b\s*(.*)$", t.strip())
                if mm:
                    spmaskr |= bool(mm.group(1))
                    masked |= {u.strip().upper() for u in mm.group(2).split(",") if u.strip()}
            if buffered:
                ins = ins + [x for x in buffered if self.unit_of(x[1]) not in masked]
            if any(re.search(r"\bsploop\w*\b", t) for _, t in ins):
                pc = self.sploop(ins, nxt, prot, resumed)
                continue
            if spmaskr:
                self.reload(pc)                     # RILC is read in the SPMASKR cycle
            call = self.execute(ins, nxt, prot)
            if call is not None:
                self.R[self.link] = nxt
                self.idle(5)
                self.tick()
                pc = call
                continue
            self.tick()
            due = [b for b in self.branches if b[0] <= self.cyc]
            if due:
                b = min(due)
                self.branches.remove(b)
                if b == self.iret:                  # B IRP lands: TSR = ITSR
                    self.iret, self.in_isr, self.splx = None, False, self.itsr_splx
                if b[1] == RET:
                    result = self.R.get("a4", 0) & M
                    while self.residual:            # let a loop epilog still in the buffer finish
                        if min(self.residual) <= self.cyc:
                            raise SimError(f"loop buffer cycle {min(self.residual)} was never issued")
                        self.idle(1)
                    return result
                pc = b[1]
                if self.hold:                       # last delay slot of the outer branch: fetch stops
                    self.hold = (self.cyc, self.hold[1])
            else:
                pc = nxt
        raise SimError(f"no return within {max_cycles} cycles (pc {pc:#010x})")


def self_unit(text):
    """Functional unit of an instruction text, e.g. 'S2'."""
    m = re.search(r"\s\.(\w\d)", text)
    return m.group(1).upper() if m else ""


def returns(value):
    """Hook: return `value` in A4 at once (stands in for a function)."""
    def hook(m):
        m.R["a4"] = value & M
        return m.R["b3"]
    return hook


# --- settings_validate / settings_set_defaults per product -------------------------------------------
PRODUCTS = {
    # g_settings, bytes copied from a 'PREF' block, settings_validate, settings_set_defaults, B14
    "smpltrek": dict(settings=0xC14FAC58, size=284, validate=0xC159596C, defaults=0xC1594CAC, b14=0xC16F3320),
    "lofi12": dict(settings=0xC2B74984, size=404, validate=0xC2BD31AC, defaults=0xC2BD20D8, b14=0xC2DA6758),
    "cydrums": dict(settings=0xC2426E18, size=376, validate=0xC24F6088, defaults=0xC24F5088, b14=0xC26B0EC0),
}
BLOCK = 0x30000000


def run_settings(program, product, block=None, trace=False):
    """(return value, g_settings bytes). With block: settings_validate(block, len(block)); else the defaults."""
    p = PRODUCTS[product]
    m = Machine(program, {"b14": p["b14"]}, trace=trace)
    if block is None:
        result = m.run(p["defaults"])
    else:
        m.mem.write(BLOCK, block)
        m.R.update({"a4": BLOCK, "b4": len(block)})
        result = m.run(p["validate"])
    return s32(result), m.mem.read(p["settings"], p["size"])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("settings", help="run settings_validate or settings_set_defaults")
    s.add_argument("product", choices=sorted(PRODUCTS))
    s.add_argument("image", help="the product's official update (.zip/.bin)")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--block", help="file holding the settings block (first 4 KiB used)")
    g.add_argument("--defaults", action="store_true")
    s.add_argument("--trace", action="store_true")
    args = ap.parse_args()
    program = Program(args.image)
    block = Path(args.block).read_bytes()[:4096] if args.block else None
    result, data = run_settings(program, args.product, block, args.trace)
    print(f"return {result}")
    for i in range(len(data) // 4):
        print(f"+0x{4 * i:03X} {struct.unpack_from('<i', data, 4 * i)[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
