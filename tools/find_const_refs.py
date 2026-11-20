#!/usr/bin/env python3
"""Find 32-bit constants materialised by MVKL/MVKH pairs in a raw TI C64x+ code section.

Usage: python3 -I find_const_refs.py CODE_SECTION.bin LOAD_ADDR [CONST ...]
With no CONST, prints every constant with its reference count (top 200).
Example: find who references the string "pmtd" at 0xc26a5710 in the CyDrums image.
"""
import struct, sys
def mvk_pairs(code, base):
    n = len(code)//4; w = struct.unpack(f"<{n}I", code[:n*4]); pairs = {}
    def kind(x):
        op = (x >> 2) & 0x1f
        return 'L' if op == 0x0a else 'H' if op == 0x1a else None
    for i, x in enumerate(w):
        if kind(x) != 'L': continue
        dst = (x >> 23) & 0x1f; s = (x >> 1) & 1
        for j in range(i+1, min(i+9, n)):
            y = w[j]
            if kind(y) == 'H' and ((y >> 23) & 0x1f) == dst and ((y >> 1) & 1) == s:
                val = (((y >> 7) & 0xffff) << 16) | ((x >> 7) & 0xffff)
                pairs.setdefault(val, []).append(base + i*4); break
    return pairs
if __name__ == "__main__":
    code = open(sys.argv[1], "rb").read(); base = int(sys.argv[2], 0)
    pairs = mvk_pairs(code, base)
    want = [int(a, 0) for a in sys.argv[3:]]
    if want:
        for v in want: print(f"{v:#010x}: {[hex(a) for a in pairs.get(v, [])]}")
    else:
        for v, a in sorted(pairs.items(), key=lambda kv: -len(kv[1]))[:200]: print(f"{v:#010x} refs={len(a)}")
