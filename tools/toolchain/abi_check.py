#!/usr/bin/env python3
"""Run abi_driver from one or more linked ELFs in the C674x simulator and compare the results.

    python3 -B tools/toolchain/abi_check.py build/ti_ti.elf build/gcc_gcc.elf build/ti_gcc.elf ...

Each ELF is a pairing of abi_driver.c and abi_funcs.c built by cl6x or GCC (see abi_build.py). The
driver writes 45 words; EXPECTED holds the values the C computes, worked out here independently.
Every ELF must match EXPECTED word for word, and B14 (the data page, preserved under the EABI) must
come back unchanged. Exit status 1 on any mismatch or simulator error.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import elfsim  # noqa: E402

BUFFER = 0x40000000
DP_SENTINEL = 0x5EED0000


def words64(v):
    v &= (1 << 64) - 1
    return [v & 0xFFFFFFFF, v >> 32]


def dbits(x):
    return words64(struct.unpack("<Q", struct.pack("<d", x))[0])


def fbits(x):
    return [struct.unpack("<I", struct.pack("<f", x))[0]]


def c_div(a, b):
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def c_rem(a, b):
    return a - b * c_div(a, b)


EXPECTED = (
    [55]                                                  # add5
    + [sum(i * i for i in range(1, 13))]                  # add12
    + words64(0x0000000180000000 + 0x0000000280000001)    # add64
    + words64(0x100000000 + 0x200000000 + 5 * 3 - 2 * 7)  # mix64
    + dbits(2.5 * 4.0 + 1.5)                              # dmul
    + fbits(1.5 * 2.0 + 0.25)                             # fmadd
    + dbits(0.5 + 1.25 + 3 + 0.75)                        # mixfd
    + [(-7) & 0xFFFFFFFF]                                 # f2i(-7.9)
    + fbits(2.5)                                          # i2f(10)
    + [3000000000]                                        # d2u
    + words64(-5000000000)                                # d2ll
    + [7, 21, 128]                                        # s8_make, s8_sum
    + [10, 11, 12, 13, 14, 15, 75 + 1000]                 # s24_make, s24_sum
    + [0, 60, 78]                                         # vsum
    + words64(0x100000001 + 0x200000002 + 0x300000003)    # vsum64
    + [43]                                                # call_through(sub2, 50, 8)
    + [1000000007 // 13, c_div(-1000000007, 13) & 0xFFFFFFFF, 1000000007 % 13]
    + words64(0x123456789ABCDEF0 // 0x1000000FF)
    + words64(c_rem(-0x123456789ABCDEF, 1000003))
    + [0]                                                 # dot
    + [0xF3F2F1F0, 0xF7F6F5F4, 0xFBFAF9F8, 0xFFFEFDFC]    # fill
    + [0]                                                 # pressure (the sums cancel)
)

LABELS = (["add5", "add12", "add64.lo", "add64.hi", "mix64.lo", "mix64.hi", "dmul.lo", "dmul.hi", "fmadd",
           "mixfd.lo", "mixfd.hi", "f2i", "i2f", "d2u", "d2ll.lo", "d2ll.hi", "s8.a", "s8.b", "s8_sum"]
          + [f"s24.v{i}" for i in range(6)] + ["s24_sum", "vsum0", "vsum3", "vsum12", "vsum64.lo", "vsum64.hi",
          "call_through", "udiv", "sdiv", "umod", "udiv64.lo", "udiv64.hi", "smod64.lo", "smod64.hi", "dot",
          "fill0", "fill1", "fill2", "fill3", "pressure"])
assert len(LABELS) == len(EXPECTED)


def run(path):
    """(words, cycles, b14) from running abi_driver in `path`. Raises on simulator errors."""
    program, syms = elfsim.load(path)
    m = elfsim.call(program, syms["abi_driver"], a4=BUFFER, b14=DP_SENTINEL)
    n = m.g("a4")
    return list(struct.unpack(f"<{n}I", m.mem.read(BUFFER, 4 * n))), m.cyc, m.g("b14")


def main(paths):
    ok = True
    for path in paths:
        name = Path(path).name
        try:
            words, cycles, b14 = run(path)
        except Exception as e:  # SimError or a decoding problem: report and continue
            print(f"{name}: SIMULATOR ERROR {type(e).__name__}: {e}")
            ok = False
            continue
        bad = [(LABELS[i], EXPECTED[i], words[i]) for i in range(min(len(words), len(EXPECTED)))
               if words[i] != EXPECTED[i]]
        if len(words) != len(EXPECTED):
            bad.append(("word count", len(EXPECTED), len(words)))
        if b14 != DP_SENTINEL:
            bad.append(("B14 after the run", DP_SENTINEL, b14))
        status = "OK" if not bad else "MISMATCH"
        print(f"{name}: {status}, {len(words)} words, {cycles} cycles")
        for label, want, got in bad:
            print(f"    {label}: expected {want:#x}, got {got:#x}")
        ok &= not bad
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
