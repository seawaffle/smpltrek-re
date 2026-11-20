#!/usr/bin/env python3
"""Recover C++ classes, inheritance and vtables from a Sonicware system image (Itanium C++ ABI).

The stock firmware is built with TI's C6000 compiler, EABI, libc++, with RTTI enabled. Itanium ABI
structures on this 32-bit little-endian target:

  type_info objects (all start with a vptr into one of three __cxxabiv1 vtables, then a name pointer)
    __class_type_info      { vptr, name }                          no base
    __si_class_type_info   { vptr, name, base_type }               single public non-virtual base at 0
    __vmi_class_type_info  { vptr, name, flags, count, {base_type, offset_flags} * count }
      offset_flags: bit 0 virtual, bit 1 public, bits 8.. signed offset
  vtables: { offset_to_top, type_info*, vfunc0, vfunc1, ... }, objects point at vfunc0 ("address point")

Method:
  1. Find NUL-terminated strings shaped like mangled type names; a word pointing at one, preceded by a
     word, is a candidate type_info.
  2. Identify the three ABI vptrs from the type_infos named N10__cxxabiv1..._type_infoE, falling back to
     the three most frequent vptr values if those names are absent.
  3. Parse class type_infos and their bases.
  4. A vtable is a word pointing at a class type_info, preceded by a small non-positive offset_to_top,
     outside any type_info object, followed by pointers into the code section.
  5. Name each function by the class that introduces or overrides it: a slot whose function differs from
     the same slot in the primary base's primary vtable.

Output: JSON (classes, bases, vtables, symbols), keyed to the source SHA-256. The JSON holds only
addresses, names and structure, no code bytes. Default output path is under the gitignored work/.

Usage (from the repository root):
  python3 -B analysis/rtti_recover.py "firmware/smpltrek/SmplTrek v3.2.174.zip" work/smpltrek-3.2.174.rtti.json
"""
import argparse
import bisect
import collections
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mmtd2elf
import sonicware_integrity as integrity

CXXFILT = ROOT / "tools/tic6x/bin/tic6x-elf-c++filt"
ABI_NAMES = {
    "class": "N10__cxxabiv117__class_type_infoE",
    "si": "N10__cxxabiv120__si_class_type_infoE",
    "vmi": "N10__cxxabiv121__vmi_class_type_infoE",
}
# Mangled type-name strings: nested (N...E), std (St...), or length-prefixed source names.
NAME_RE = re.compile(rb"(?<=\0)((?:N|St|[1-9])[0-9A-Za-z_]{1,511})\0")


class Memory:
    def __init__(self, sections, entry):
        self.sections = sorted(sections)
        self.starts = [a for a, _ in self.sections]
        code = [(a, d) for a, d in self.sections if a <= entry < a + len(d)]
        integrity.require(len(code) == 1, "entry point not in exactly one section")
        self.code = (code[0][0], code[0][0] + len(code[0][1]))

    def word(self, address):
        i = bisect.bisect_right(self.starts, address) - 1
        if i < 0:
            return None
        a, d = self.sections[i]
        if address - a + 4 > len(d):
            return None
        return struct.unpack_from("<I", d, address - a)[0]

    def cstring(self, address, limit=512):
        i = bisect.bisect_right(self.starts, address) - 1
        if i < 0:
            return None
        a, d = self.sections[i]
        start = address - a
        if not 0 <= start < len(d):
            return None
        end = d.find(b"\0", start, start + limit)
        return d[start:end] if end >= 0 else None

    def is_code(self, value):
        return self.code[0] <= value < self.code[1]

    def words(self):
        for a, d in self.sections:
            for offset in range(0, len(d) - 3, 4):
                yield a + offset, struct.unpack_from("<I", d, offset)[0]


def signed(value):
    return value - (1 << 32) if value & 0x80000000 else value


def demangle_all(mangled):
    """Demangle type names via c++filt as 'typeinfo name for X'; fall back to the mangled form."""
    if not mangled:
        return {}
    tool = str(CXXFILT) if CXXFILT.exists() else shutil.which("c++filt")
    if not tool:
        return {m: m for m in mangled}
    out = subprocess.run([tool], input="\n".join("_ZTS" + m for m in mangled), capture_output=True,
                         text=True, check=True).stdout.splitlines()
    prefix = "typeinfo name for "
    return {m: (o[len(prefix):] if o.startswith(prefix) else m) for m, o in zip(mangled, out)}


def recover(sections, entry):
    mem = Memory(sections, entry)
    pointers = collections.defaultdict(list)  # value -> addresses holding that word
    for address, value in mem.words():
        pointers[value].append(address)

    names = {}
    for a, d in mem.sections:
        for m in NAME_RE.finditer(d):
            names[a + m.start(1)] = m.group(1).decode()

    # Candidate type_infos: (address, vptr, name_address)
    candidates = []
    for name_address in names:
        for ref in pointers.get(name_address, ()):
            vptr = mem.word(ref - 4)
            if vptr is not None:
                candidates.append((ref - 4, vptr, name_address))

    # ABI vptrs: vtable of each __cxxabiv1 type_info class, address point = vtable + 8.
    by_name = {names[n]: ti for ti, _, n in candidates}
    abi = {}
    for kind, abi_name in ABI_NAMES.items():
        ti = by_name.get(abi_name)
        if ti is None:
            continue
        for ref in pointers.get(ti, ()):
            if mem.word(ref - 4) == 0:
                abi[ref + 4] = kind
    abi_source = "named __cxxabiv1 type_infos"
    if len(set(abi.values())) != 3:
        abi_source = "frequency fallback (unverified kinds)"
        counts = collections.Counter(v for _, v, _ in candidates).most_common(3)
        abi = {}
        for vptr, _ in counts:
            # Classify by shape of the first object using this vptr.
            ti = next(t for t, v, _ in candidates if v == vptr)
            base = mem.word(ti + 8)
            abi[vptr] = "si" if base in {t for t, _, _ in candidates} else (
                "vmi" if (mem.word(ti + 12) or 0) < 64 else "class")

    # Second pass, now that the ABI vptrs are known: every word equal to an ABI vptr whose next word
    # points at a mangled type name is a type_info. This also finds names not preceded by a NUL
    # (the first pass's string search misses those).
    full_name = re.compile(rb"(?:N|St|[1-9])[0-9A-Za-z_]+\Z")
    seen = {ti for ti, _, _ in candidates}
    for vptr in abi:
        for ti in pointers.get(vptr, ()):
            name_address = mem.word(ti + 4)
            if ti in seen or name_address is None:
                continue
            text = mem.cstring(name_address)
            if text and full_name.match(text):
                names[name_address] = text.decode()
                candidates.append((ti, vptr, name_address))
                seen.add(ti)

    classes = {}
    extents = []  # (start, end) of each class type_info object, to exclude from vtable search
    for ti, vptr, name_address in candidates:
        kind = abi.get(vptr)
        if kind is None:
            continue
        info = {"typeinfo": ti, "name_address": name_address, "mangled": names[name_address],
                "kind": kind, "bases": []}
        end = ti + 8
        if kind == "si":
            info["bases"].append({"typeinfo": mem.word(ti + 8), "offset": 0, "virtual": False, "public": True})
            end = ti + 12
        elif kind == "vmi":
            info["vmi_flags"] = mem.word(ti + 8)
            count = mem.word(ti + 12)
            if count is None or count > 64:
                continue
            for k in range(count):
                base, flags = mem.word(ti + 16 + 8 * k), mem.word(ti + 20 + 8 * k)
                info["bases"].append({"typeinfo": base, "offset": signed(flags) >> 8,
                                      "virtual": bool(flags & 1), "public": bool(flags & 2)})
            end = ti + 16 + 8 * count
        classes[ti] = info
        extents.append((ti, end))
    extents.sort()
    extent_starts = [s for s, _ in extents]

    def inside_typeinfo(address):
        i = bisect.bisect_right(extent_starts, address) - 1
        return i >= 0 and extents[i][0] <= address < extents[i][1]

    # Vtable starts first, so a scan can stop at the next one.
    starts = {}
    for info in classes.values():
        for ref in pointers.get(info["typeinfo"], ()):
            top = mem.word(ref - 4)
            if not inside_typeinfo(ref) and top is not None and -0x10000 < signed(top) <= 0:
                starts[ref - 4] = (info, signed(top))
    for info in classes.values():
        info["vtables"] = []
    for start, (info, top) in sorted(starts.items()):
        # Entries are code pointers or 0. Null slots occur when the TI linker drops an unused virtual
        # function; trailing nulls are trimmed below using the primary base's length.
        entries, address = [], start + 8
        while address not in starts and not inside_typeinfo(address):
            value = mem.word(address)
            if value is None or not (value == 0 or mem.is_code(value)):
                break
            entries.append(value)
            address += 4
        info["vtables"].append({"address": start, "address_point": start + 8,
                                "offset_to_top": top, "entries": entries})
    for info in classes.values():
        info["vtables"].sort(key=lambda v: (-v["offset_to_top"], v["address"]))

    # Unresolved base pointers: bases not among class type_infos (e.g. from fundamental/other kinds).
    for info in classes.values():
        for base in info["bases"]:
            base["resolved"] = base["typeinfo"] in classes

    pretty = demangle_all(sorted({c["mangled"] for c in classes.values()}))
    for info in classes.values():
        info["name"] = pretty[info["mangled"]]
    for info in classes.values():
        for base in info["bases"]:
            base["name"] = classes[base["typeinfo"]]["name"] if base["resolved"] else None

    def primary(info):
        """The vtable with offset_to_top 0, if any."""
        return next((v for v in info["vtables"] if v["offset_to_top"] == 0), None)

    def primary_base(info):
        for base in info["bases"]:
            if base["offset"] == 0 and not base["virtual"] and base["resolved"]:
                return classes[base["typeinfo"]]
        return None

    # Vtable lengths. A scan can overrun into adjacent function-pointer data, and can include null slots
    # (unused virtual functions removed by the TI linker). Two ABI constraints fix the length:
    #   upper: a class's primary vtable is no longer than any primary-derived class's primary vtable;
    #   lower: a vtable is at least as long as the primary vtable of the base whose subobject it serves.
    # True length = min(upper, max(last code pointer within upper, base's true length)).
    children = collections.defaultdict(list)  # base type_info -> classes deriving from it at offset 0
    for info in classes.values():
        base = primary_base(info)
        if base:
            children[base["typeinfo"]].append(info)

    upper = {}

    def upper_bound(info):
        table = primary(info)
        if table is None:
            return None
        key = table["address"]
        if key not in upper:
            upper[key] = len(table["entries"])  # cycle guard
            bounds = [upper_bound(c) for c in children[info["typeinfo"]]]
            upper[key] = min([len(table["entries"])] + [b for b in bounds if b is not None])
        return upper[key]

    true_length = {}

    def length(info, table):
        key = table["address"]
        if key in true_length:
            return true_length[key]
        true_length[key] = len(table["entries"])  # cycle guard
        bound = upper_bound(info) if table["offset_to_top"] == 0 else len(table["entries"])
        last = max((i + 1 for i, f in enumerate(table["entries"][:bound]) if f), default=0)
        minimum = 0
        base = next((b for b in info["bases"] if b["offset"] == -table["offset_to_top"]
                     and not b["virtual"] and b["resolved"]), None)
        if base:
            parent = classes[base["typeinfo"]]
            if primary(parent):
                minimum = length(parent, primary(parent))
        true_length[key] = min(bound, max(last, minimum))
        return true_length[key]

    for info in classes.values():
        for table in info["vtables"]:
            length(info, table)
    for info in classes.values():
        has_children = bool(children[info["typeinfo"]])
        for table in info["vtables"]:
            scanned = len(table["entries"])
            table["entries"] = table["entries"][:true_length[table["address"]]]
            table["null_slots"] = [i for i, f in enumerate(table["entries"]) if not f]
            table["trimmed_from"] = scanned if scanned != len(table["entries"]) else None
            # Without derived classes, an overrun into adjacent code pointers cannot be ruled out.
            table["length_bounded_by_children"] = table["offset_to_top"] == 0 and has_children

    # Function ownership: introduced or overridden in this class's primary vtable.
    owners = collections.defaultdict(list)
    for info in classes.values():
        table = primary(info)
        if not table:
            continue
        parent = primary_base(info)
        parent_entries = primary(parent)["entries"] if parent and primary(parent) else []
        for slot, function in enumerate(table["entries"]):
            if not function or (slot < len(parent_entries) and parent_entries[slot] == function):
                continue
            owners[function].append((info["name"], slot))

    occurrences = collections.Counter(f for c in classes.values() for v in c["vtables"]
                                      for f in set(v["entries"]) if f)
    # A function that is a fresh (not inherited) entry in many classes is __cxa_pure_virtual or a shared
    # stub, not a method of any one class. In 3.2.174 the top one (0xC16AC720) branches with A4 = 6
    # (SIGABRT), consistent with __cxa_pure_virtual. Threshold: owned by at least 20 classes.
    shared_owned = {f: len(o) for f, o in owners.items() if len(o) >= 20}

    symbols = []
    for info in classes.values():
        symbols.append({"address": info["typeinfo"], "name": f"typeinfo for {info['name']}", "kind": "typeinfo"})
        symbols.append({"address": info["name_address"], "name": f"typeinfo name for {info['name']}",
                        "kind": "typeinfo_name"})
        for table in info["vtables"]:
            suffix = "" if table["offset_to_top"] == 0 else f" (offset {table['offset_to_top']})"
            symbols.append({"address": table["address"], "name": f"vtable for {info['name']}{suffix}",
                            "kind": "vtable"})
    for function, owned in owners.items():
        if function in shared_owned:
            rank = sorted(shared_owned, key=lambda f: (-shared_owned[f], f)).index(function)
            symbols.append({"address": function,
                            "name": "__cxa_pure_virtual_candidate" if rank == 0 else f"shared_vfunc_stub_{rank}",
                            "kind": "shared_virtual_function", "owned_by_classes": len(owned),
                            "vtable_occurrences": occurrences[function]})
            continue
        cls, slot = sorted(owned)[0]
        symbols.append({"address": function, "name": f"{cls}::vfunc_{slot}", "kind": "virtual_function",
                        "aliases": [f"{c}::vfunc_{s}" for c, s in sorted(owned)[1:]],
                        "vtable_occurrences": occurrences[function]})

    shared = [{"address": f, "owned_by_classes": n}
              for f, n in sorted(shared_owned.items(), key=lambda kv: (-kv[1], kv[0]))]
    return {
        "abi": {"source": abi_source, "vptrs": {kind: vptr for vptr, kind in sorted(abi.items())}},
        "code_section": list(mem.code),
        "classes": sorted(classes.values(), key=lambda c: c["typeinfo"]),
        "shared_vtable_entries": shared,
        "symbols": sorted(symbols, key=lambda s: (s["address"], s["name"])),
    }


def to_hex(obj):
    """Render addresses as hex strings for readability; keep small ints (offsets, counts, slots) decimal."""
    if isinstance(obj, dict):
        return {k: (f"{v:#010x}" if isinstance(v, int) and not isinstance(v, bool) and k in HEX_KEYS
                    else to_hex(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [f"{v:#010x}" if isinstance(v, int) and not isinstance(v, bool) and v >= 0x10000 else to_hex(v)
                for v in obj]
    return obj


HEX_KEYS = {"typeinfo", "name_address", "address", "address_point", "vmi_flags"}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="official update .zip or .bin")
    parser.add_argument("output", type=Path, help="JSON output (keep under work/ unless publishing)")
    args = parser.parse_args()
    try:
        (name, data), = list(integrity.inputs([args.input]))
        version, entry, sections = mmtd2elf.mmtd_sections(data)
        result = recover(sections, entry)
    except (ValueError, OSError, struct.error, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    abi_vptrs = {k: f"{v:#010x}" for k, v in result["abi"]["vptrs"].items()}
    result["abi"]["vptrs"] = abi_vptrs
    document = {"source": {"file": name, "sha256": hashlib.sha256(data).hexdigest(),
                           "mmtd_version": ".".join(map(str, version)), "entry": f"{entry:#010x}"},
                **to_hex(result)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=1) + "\n")

    classes = result["classes"]
    kinds = collections.Counter(c["kind"] for c in classes)
    with_vtables = sum(1 for c in classes if c["vtables"])
    functions = sum(1 for s in result["symbols"] if s["kind"] == "virtual_function")
    unresolved = sum(1 for c in classes for b in c["bases"] if not b["resolved"])
    print(name)
    print(f"  ABI vptrs ({result['abi']['source']}): {abi_vptrs}")
    print(f"  classes {len(classes)} (no base {kinds['class']}, single {kinds['si']}, multiple {kinds['vmi']}),"
          f" {with_vtables} with vtables, {unresolved} unresolved base pointers")
    print(f"  named virtual functions {functions}")
    for entry_ in result["shared_vtable_entries"]:
        print(f"  shared vtable entry {entry_['address']:#010x}, fresh entry in {entry_['owned_by_classes']}"
              " classes (pure-virtual or shared-stub candidate)")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
