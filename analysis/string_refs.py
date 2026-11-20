#!/usr/bin/env python3
"""Find code references to strings and other data in a Sonicware system image.

C6000 code materialises 32-bit addresses with a constant pair:
    MVK/MVKL  low16 -> reg     (sign-extends, clears the high half)
    MVKH      high16 -> reg    (keeps the low half)
The two can be several execute packets apart, in parallel with other instructions, conditional, and
the MVK may be a 16-bit compact instruction. Rather than decode instructions here, this script runs
GNU objdump (tools/tic6x, which decodes compact fetch packets) and tracks a pending low half per
register, invalidated when another instruction writes that register or after a window of code.

Outputs, keyed to the source SHA-256:
  strings     each referenced NUL-terminated string, its code references (address of the MVKH, which
              completes the address) and data references (aligned words in data sections pointing at
              the string's first byte, e.g. menu label tables)
  vtable_refs with --rtti: code that loads a class's vtable address point. That is almost always the
              class's constructor or destructor (they store the vptr), which names non-virtual code.
  data_refs   count of other constants pointing into image sections (globals, tables)

Limits: near data reached through the data page pointer (B14 + offset) is not found, and a constant
built any other way (ADDK, loads from a literal table) is missed. Treat absence as "not found by this
method", not "unreferenced".

Usage (from the repository root):
  python3 -B analysis/string_refs.py "firmware/smpltrek/SmplTrek v3.2.174.zip" \
      work/smpltrek-3.2.174.strings.json --rtti work/smpltrek-3.2.174.rtti.json
"""
import argparse
import bisect
import collections
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mmtd2elf
import sonicware_integrity as integrity

OBJDUMP = ROOT / "tools/tic6x/bin/tic6x-elf-objdump"
# "c1505434:\t0200422a \t|| [b0] mvk .S2 132,b4"
LINE = re.compile(r"^\s*([0-9a-f]+):\t[0-9a-f]+\s*\t(?:\|\|\s*)?(?:\[!?[ab]\d+\]\s*)?(\S+)(?:\s+(.*))?$")
PREDICATE = re.compile(r"\t(?:\|\|\s*)?(\[!?[ab]\d+\])")
PARALLEL = re.compile(r"\t\|\|")
REGISTER = re.compile(r"^[ab]\d{1,2}$")
WINDOW = 0x200  # bytes of code between MVK and MVKH before the pending low half is dropped
MIN_STRING = 2


def disassemble(sections, entry, details=False):
    """Yield (address, mnemonic, operands) for the code section via objdump.

    With details=True, yield (address, mnemonic, operands, predicate, parallel): predicate is e.g. "[!b0]"
    or "", parallel is True for an instruction in the same execute packet as the previous one ("||").
    """
    code = {i for i, (a, d) in enumerate(sections) if a <= entry < a + len(d)}
    elf = mmtd2elf.build_elf(entry, sections, code)
    with tempfile.NamedTemporaryFile(suffix=".elf") as tmp:
        tmp.write(elf)
        tmp.flush()
        out = subprocess.run([str(OBJDUMP), "-d", "-j", ".text", tmp.name], capture_output=True,
                             text=True, check=True).stdout
    for line in out.splitlines():
        m = LINE.match(line)
        if m:
            insn = int(m.group(1), 16), m.group(2).lower(), (m.group(3) or "")
            if details:
                p = PREDICATE.search(line)
                insn += (p.group(1) if p else "", PARALLEL.search(line) is not None)
            yield insn


def written_registers(operands):
    """Registers written by an instruction: its last operand when that is a register or pair."""
    if not operands:
        return []
    last = operands.rsplit(",", 1)[-1].strip()
    if last.startswith("*"):
        return []
    return [r for r in last.split(":") if REGISTER.match(r)]


def constant_pairs(instructions):
    """Yield (value, mvkh_address, mvk_address) for each MVK/MVKL ... MVKH pair on one register."""
    pending = {}  # register -> (address, low16)
    for address, mnemonic, operands in instructions:
        if mnemonic in ("mvk", "mvkl", "mvkh"):
            parts = operands.split()
            imm_reg = parts[-1] if parts else ""
            if "," not in imm_reg:
                continue
            imm_text, register = imm_reg.rsplit(",", 1)
            try:
                imm = int(imm_text, 0)
            except ValueError:
                continue
            if mnemonic == "mvkh":
                low = pending.pop(register, None)
                if low and address - low[0] <= WINDOW:
                    yield ((imm & 0xFFFF0000) | low[1]) & 0xFFFFFFFF, address, low[0]
            else:
                pending[register] = (address, imm & 0xFFFF)
            continue
        for register in written_registers(operands):
            pending.pop(register, None)


class Image:
    def __init__(self, sections, entry):
        self.sections = sorted(sections)
        self.starts = [a for a, _ in self.sections]
        self.code = next((a, a + len(d)) for a, d in self.sections if a <= entry < a + len(d))

    def locate(self, address):
        i = bisect.bisect_right(self.starts, address) - 1
        if i >= 0:
            a, d = self.sections[i]
            if a <= address < a + len(d):
                return a, d
        return None

    def string_at(self, address):
        """Printable NUL-terminated text at address (ASCII plus bytes >= 0x80 for Shift-JIS), or None."""
        found = self.locate(address)
        if not found or self.code[0] <= address < self.code[1]:
            return None
        a, d = found
        start = address - a
        end = d.find(b"\0", start, start + 1024)
        if end < 0 or end - start < MIN_STRING:
            return None
        raw = d[start:end]
        if not all(b >= 0x20 and b != 0x7F or b in (9, 10, 13) for b in raw):
            return None
        if sum(0x20 <= b < 0x7F for b in raw) < len(raw) / 2:
            return None
        return raw.decode("cp932", errors="replace"), start == 0 or d[start - 1] == 0

    def data_words(self):
        for a, d in self.sections:
            if (a, a + len(d)) == self.code:
                continue
            for offset in range((-a) % 4, len(d) - 3, 4):
                yield a + offset, struct.unpack_from("<I", d, offset)[0]


def analyse(sections, entry, rtti=None):
    image = Image(sections, entry)
    by_value = collections.defaultdict(list)
    pairs = 0
    for value, mvkh, mvk in constant_pairs(disassemble(sections, entry)):
        pairs += 1
        by_value[value].append(mvkh)

    strings = {}
    other = 0
    for value, refs in by_value.items():
        text = image.string_at(value)
        if text:
            strings[value] = {"address": value, "text": text[0], "starts_after_nul": text[1],
                              "code_refs": sorted(refs), "data_refs": []}
        elif image.locate(value):
            other += 1

    # Data references to string starts (pointer tables). Only exact starts, to keep false positives low.
    for address, value in image.data_words():
        if value in strings and strings[value]["starts_after_nul"]:
            strings[value]["data_refs"].append(address)
        elif value not in strings and value not in by_value:
            text = image.string_at(value)
            if text and text[1] and len(text[0]) >= 3:
                strings[value] = {"address": value, "text": text[0], "starts_after_nul": True,
                                  "code_refs": [], "data_refs": [address]}

    vtable_refs = []
    if rtti:
        for cls in rtti["classes"]:
            for table in cls["vtables"]:
                point = int(table["address_point"], 16)
                refs = by_value.get(point, [])
                if refs:
                    vtable_refs.append({"class": cls["name"], "offset_to_top": table["offset_to_top"],
                                        "address_point": point, "code_refs": sorted(refs)})

    return {
        "constant_pairs": pairs,
        "distinct_constants": len(by_value),
        "data_refs_non_string": other,
        "strings": sorted(strings.values(), key=lambda s: s["address"]),
        "vtable_refs": sorted(vtable_refs, key=lambda v: (v["class"], v["offset_to_top"])),
    }


def hexify(obj, key=None):
    if isinstance(obj, dict):
        return {k: hexify(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [hexify(v, key) for v in obj]
    if isinstance(obj, int) and not isinstance(obj, bool) and key in ("address", "address_point", "code_refs", "data_refs"):
        return f"{obj:#010x}"
    return obj


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="official update .zip or .bin")
    parser.add_argument("output", type=Path, help="JSON output (keep under work/ unless publishing)")
    parser.add_argument("--rtti", type=Path, help="rtti_recover.py JSON for the same image (adds vtable_refs)")
    args = parser.parse_args()
    try:
        (name, data), = list(integrity.inputs([args.input]))
        digest = hashlib.sha256(data).hexdigest()
        version, entry, sections = mmtd2elf.mmtd_sections(data)
        rtti = None
        if args.rtti:
            rtti = json.loads(args.rtti.read_text())
            integrity.require(rtti["source"]["sha256"] == digest, "RTTI JSON is for a different image")
        result = analyse(sections, entry, rtti)
    except (ValueError, OSError, struct.error, subprocess.CalledProcessError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    document = {"source": {"file": name, "sha256": digest, "mmtd_version": ".".join(map(str, version)),
                           "entry": f"{entry:#010x}"}, **hexify(result)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n")
    s = result["strings"]
    print(name)
    print(f"  constant pairs {result['constant_pairs']} ({result['distinct_constants']} distinct)")
    print(f"  strings {len(s)}: {sum(1 for x in s if x['code_refs'])} with code refs, "
          f"{sum(1 for x in s if x['data_refs'])} with data refs")
    print(f"  other constants into image sections {result['data_refs_non_string']}")
    if rtti:
        classes = {v["class"] for v in result["vtable_refs"]}
        sites = sum(len(v["code_refs"]) for v in result["vtable_refs"])
        print(f"  vtable loads: {sites} sites for {len(classes)} classes (constructor/destructor candidates)")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
