#!/usr/bin/env python3
"""Sonicware firmware triage: parse cmtd containers (24-byte header + 24-byte image descriptors) and pmtd/mmtd images, extract sections,
test for TI C674x compact code, list C++ RTTI class names.

Usage: python3 -I tools/sonicware_triage.py FILE.bin [FILE2.bin ...] [--extract OUTDIR] [--classes]
Depends only on the standard library.
"""
import sys, os, struct, math, re, collections

MODEL_IDS = {5: "SmplTrek", 12: "Lofi-12 XT", 8: "CyDrums / ELZ_1 play", 16: "deconstruct MINIMAL"}  # family word, not a unique product ID

def entropy(b):
    if not b: return 0.0
    c = collections.Counter(b); n = len(b)
    return -sum(v/n*math.log2(v/n) for v in c.values())

def c674x_signature(code):
    """C64x+ compact fetch packets: word 7 of each aligned 32-byte packet has top nibble 0xE."""
    w = struct.unpack(f"<{len(code)//4}I", code[:len(code)//4*4])
    npk = len(w)//8
    if npk == 0: return 0.0, 0.0
    slot7 = sum(1 for i in range(7, npk*8, 8) if (w[i] >> 28) == 0xE) / npk
    other = sum(1 for i in range(0, npk*8) if i % 8 != 7 and (w[i] >> 28) == 0xE) / (npk*7)
    return slot7*100, other*100

def rtti_classes(data):
    names = set()
    for m in re.finditer(rb"(?:N(?:\d+[A-Za-z_]\w*?)+)?(\d+)([A-Z][A-Za-z0-9_]{3,})E?", data):
        if int(m.group(1)) == len(m.group(2)):
            names.add(m.group(2).decode())
    return names

def parse(path, extract=None):
    d = open(path, "rb").read()
    print("=" * 70); print(path, f"{len(d):#x} bytes")
    if d[:4] != b"cmtd":
        print("  not a cmtd container"); return
    size, chk, _z, fam, nimg = struct.unpack_from("<5I", d, 4)
    print(f"  cmtd: size={size:#x} crc={chk:#010x} family_word={fam} ({MODEL_IDS.get(fam,'unknown')}) images={nimg}")
    if size != len(d): print(f"  WARNING: header size {size:#x} != file size {len(d):#x} (legacy ELZ_1 layout?)"); return d
    for n in range(nimg):
        typ, vM, vm, vb, pos, ln = struct.unpack_from("<6I", d, 0x18 + 24*n)
        tag = d[pos:pos+4]
        print(f"  descriptor {n}: type={typ} version={vM}.{vm}.{vb} offset={pos:#x} length={ln:#x} -> {tag.decode(errors='replace')}")
        if tag == b"pmtd":
            h = struct.unpack_from("<4s7I", d, pos)
            print(f"  pmtd@{pos:#x}: size={h[1]:#x} crc={h[2]:#010x} version={h[4]}.{h[5]}.{h[6]} partitions={h[7]}")
            for k in range(h[7]):
                t, a, s_ = struct.unpack_from("<4sII", d, pos+0x20+12*k)
                print(f"    {t.decode():4s} flash@{a:#010x} size={s_:#x}")
        elif tag == b"mmtd":
            h = struct.unpack_from("<4s8I", d, pos)
            print(f"  mmtd@{pos:#x}: size={h[1]:#x} crc={h[2]:#010x} version={h[4]}.{h[5]}.{h[6]} "
                  f"entry={h[7]:#010x} sections={h[8]}")
            i = pos + 0x24
            for k in range(h[8]):
                name, addr, sz = struct.unpack_from("<4sII", d, i)
                pay = d[i+12:i+12+sz]
                note = ""
                if h[7] >= addr and h[7] < addr+sz:
                    s7, so = c674x_signature(pay)
                    note = f"  <- contains entry; C674x fetch-pkt hdr slot7={s7:.1f}% other={so:.1f}%"
                print(f"    sect {k}: @{addr:#010x} size={sz:#09x} ent={entropy(pay[:65536]):.2f}{note}")
                if extract:
                    os.makedirs(extract, exist_ok=True)
                    out = os.path.join(extract, f"{os.path.basename(path)}.sect{k}_{addr:08x}.bin")
                    open(out, "wb").write(pay)
                i += 12 + sz
            print(f"    sections end @ {i:#x} (image end {pos+ln:#x})")
        else:
            print(f"  unknown image tag {tag!r} at {pos:#x}")
    return d

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    extract = None
    if "--extract" in sys.argv:
        extract = sys.argv[sys.argv.index("--extract")+1]; args = [a for a in args if a != extract]
    want_classes = "--classes" in sys.argv
    sets = {}
    for p in args:
        d = parse(p, extract)
        if d is not None and want_classes:
            sets[p] = rtti_classes(d); print(f"  RTTI classes: {len(sets[p])}")
    if want_classes and len(sets) > 1:
        common = set.intersection(*sets.values())
        print(f"\nclasses common to all {len(sets)} files: {len(common)}")
        print(", ".join(sorted(common)))
