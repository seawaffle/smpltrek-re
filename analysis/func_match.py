#!/usr/bin/env python3
"""Match functions between two Sonicware system images (versions of one product, or different products).

Byte comparison finds little: even consecutive SmplTrek releases share only ~40% of virtual function
prefixes byte-for-byte, because PC-relative branch/call displacements, MVK/MVKH address halves and
data-page (B14) offsets change whenever code or data moves. This tool matches in passes, each
proposing pairs that must be one-to-one and consistent with pairs already accepted:

  hash        functions of at least HASH_MIN_INSNS instructions whose normalised body (masked addresses,
              MVK/MVKH immediates, B14 offsets, string constants replaced by their text) is unique in
              both images.
  strings     functions whose ordered list of referenced strings is non-empty and unique in both.
  vtable      same class name, same vtable (by offset_to_top), same slot, and body similarity of at
              least VTABLE_MIN_SIMILARITY. Slots alone are not enough: they shift when a base class gains
              virtual methods, which happens between products and distant versions.
  calls       for a matched pair with equally long ordered callee lists, callees at the same
              position are paired (repeated to a fixpoint).

Function starts are call targets (CALLP, or B with ADDKPC to B3 nearby), RTTI virtual functions
and the entry point; a function runs to the next start. objdump (tools/tic6x) does the decoding.

--holdout-vtable runs every pass except vtable and scores the result against the (similarity-gated)
vtable pairs, which estimates the precision of the other passes. Every match records the similarity
(0..1) of the two normalised bodies, so consumers can filter.

Usage (from the repository root):
  python3 -B analysis/func_match.py "firmware/smpltrek/SmplTrek v3.2.174.zip" \\
      "firmware/smpltrek/SmplTrek v3.0.148.zip" -o work/match-3.2.174-3.0.148.json \\
      --symbols symbols/smpltrek-3.2.174.json
"""
import argparse
import bisect
import collections
import difflib
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import symfile  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mmtd2elf
import rtti_recover
import sonicware_integrity as integrity
import string_refs

TARGET = re.compile(r"\b[0-9a-f]{8} <[^>]*>")
B14_OFFSET = re.compile(r"(\*[+-]?b14[\[(])-?\d+([\])])")
B14_ADDA = re.compile(r"^(b14,)-?\d+")
NOP_SUFFIX = re.compile(r"\s*\|\| nop \d+$")  # objdump appends this to some compact-packet lines, inconsistently
HASH_MIN_INSNS = 6  # shorter bodies (getters, thunks) coincide too often between products
VTABLE_MIN_SIMILARITY = 0.6
SMALL_MVK = 256  # MVK immediates with |value| below this are kept (likely real constants, not address halves)


class Program:
    """One system image: instructions, function starts and per-function features."""

    def __init__(self, data, label):
        self.label = label
        self.sha256 = hashlib.sha256(data).hexdigest()
        self.version, self.entry, self.sections = mmtd2elf.mmtd_sections(data)
        self.rtti = json.loads(json.dumps(rtti_recover.to_hex(rtti_recover.recover(self.sections, self.entry))))
        self.image = string_refs.Image(self.sections, self.entry)
        detailed = [i for i in string_refs.disassemble(self.sections, self.entry, details=True)
                    if not i[1].startswith("<")]
        self.insns = [i[:3] for i in detailed]
        self.predicate = [i[3] for i in detailed]
        self.parallel = [i[4] for i in detailed]
        self.addresses = [a for a, _, _ in self.insns]
        self.strings = {}  # mvkh address -> string text
        for value, mvkh, _ in string_refs.constant_pairs(self.insns):
            text = self.image.string_at(value)
            if text:
                self.strings[mvkh] = text[0]
        self._find_functions()

    def _call_target(self, i):
        """Target of the instruction at index i if it is a call, else None."""
        address, mnemonic, operands = self.insns[i]
        m = TARGET.search(operands)
        if not m:
            return None
        target = int(m.group()[:8], 16)
        if mnemonic == "callp":
            return target
        if mnemonic == "b":
            for j in range(max(0, i - 6), min(len(self.insns), i + 7)):
                if self.insns[j][1] == "addkpc" and self.insns[j][2].endswith("b3"):
                    return target
        return None

    def _ends_of_functions(self, known):
        """Starts found after unconditional returns, beyond which no earlier branch of the function jumps.

        A return (B or BNOP to B3, unpredicated) has 5 delay slots: BNOP's own nop count covers some, each
        later execute packet one, and "NOP n" n. The first packet after the delay slots begins a new
        function unless a non-call branch since the current function's start targets it or beyond.
        Branches into the delay slots themselves are normal (TI overlaps a conditional branch with a
        return). When objdump misdecodes a fetch packet inside the delay slots (its "|| nop N" artefact),
        the cycle count is unreliable, so then any branch target after the return instruction keeps the
        function going (SmplTrek 3.2.174 f_read 0xC1509F78 was wrongly split at 0xC150A074 otherwise).
        """
        found = set()
        reach = 0        # furthest non-call branch target since the current function start
        countdown = None  # delay-slot cycles left after a return
        returned_at = 0   # address of the return being counted down
        garbled = False   # an objdump misdecode inside the delay slots
        for i, (address, mnemonic, operands) in enumerate(self.insns):
            new_packet = not self.parallel[i]
            if countdown is not None and NOP_SUFFIX.search(operands):
                garbled = True
            if new_packet and countdown is not None:
                if countdown <= 0:
                    if reach <= (returned_at if garbled else address - 1):
                        found.add(address)
                        reach = 0
                    countdown = None
            if address in known:
                reach, countdown = 0, None
            if new_packet and countdown is not None:
                m = re.match(r"^nop\s*$", mnemonic) and re.match(r"^(\d+)$", operands.strip())
                countdown -= int(m.group(1)) if m else 1
            if mnemonic in ("b", "bnop"):
                if operands.startswith((".S2 b3", ".S2X b3")) and not self.predicate[i]:
                    n = re.search(r"b3,(\d+)", operands)
                    countdown = 5 - (int(n.group(1)) if n else 0)
                    returned_at, garbled = address, False
                    continue
                t = TARGET.search(operands)
                if t and self._call_target(i) is None:
                    target = int(t.group()[:8], 16)
                    if target > address:
                        reach = max(reach, target)
        return found

    def _tail_call_targets(self, known):
        """Targets of non-call branches that leave the function they are in: tail calls.

        Functions reached only by tail branches (e.g. FatFs entry points behind thin wrappers) are
        otherwise merged into the preceding function. Repeated until stable, since each new start
        shrinks a function and can expose further exits.
        """
        lo, hi = self.image.code
        jumps = []
        for i, (address, mnemonic, operands) in enumerate(self.insns):
            if mnemonic in ("b", "bnop"):
                t = TARGET.search(operands)
                if t and self._call_target(i) is None:
                    jumps.append((address, int(t.group()[:8], 16)))
        found = set()
        for _ in range(5):
            starts = sorted(known | found)
            added = set()
            for source, target in jumps:
                if not lo <= target < hi or target in known or target in found:
                    continue
                k = bisect.bisect_right(starts, source) - 1
                begin = starts[k] if k >= 0 else lo
                end = starts[k + 1] if k + 1 < len(starts) else hi
                if not begin <= target < end:
                    added.add(target)
            if not added:
                break
            found |= added
        return found

    def _find_functions(self):
        lo, hi = self.image.code
        starts = {self.entry}
        self.virtuals = set()
        for c in self.rtti["classes"]:
            for vt in c["vtables"]:
                for e in vt["entries"]:
                    if e and lo <= int(e, 16) < hi:
                        self.virtuals.add(int(e, 16))
        starts |= self.virtuals
        calls = []
        for i in range(len(self.insns)):
            t = self._call_target(i)
            if t is not None and lo <= t < hi:
                starts.add(t)
                calls.append((self.insns[i][0], t))
        starts |= self._ends_of_functions(starts)
        starts |= self._tail_call_targets(starts)
        self.starts = sorted(starts)
        self.callees = collections.defaultdict(list)
        for site, target in calls:
            f = self.function_of(site)
            if f is not None:
                self.callees[f].append(target)
        self.body = {}
        self.string_list = {}
        for k, start in enumerate(self.starts):
            end = self.starts[k + 1] if k + 1 < len(self.starts) else hi
            i, j = bisect.bisect_left(self.addresses, start), bisect.bisect_left(self.addresses, end)
            self.body[start] = [self._normalise(a, m, o) for a, m, o in self.insns[i:j]]
            self.string_list[start] = tuple(self.strings[a] for a, _, _ in self.insns[i:j] if a in self.strings)

    def function_of(self, address):
        k = bisect.bisect_right(self.starts, address) - 1
        return self.starts[k] if k >= 0 else None

    def _normalise(self, address, mnemonic, operands):
        if address in self.strings:
            return f"{mnemonic} STR:{self.strings[address]}"
        operands = NOP_SUFFIX.sub("", TARGET.sub("ADDR", operands))
        if mnemonic == "bnop" and operands.endswith(",0"):  # same operation as B; encodings vary per build
            mnemonic, operands = "b", operands[:-2]
        if mnemonic in ("mvkh", "mvkl", "mvklh"):
            operands = re.sub(r"^\S+ -?\d+,", lambda m: m.group().split()[0] + " IMM,", operands)
        elif mnemonic == "mvk":
            def mask(m):
                return m.group() if abs(int(m.group(2))) < SMALL_MVK else m.group(1) + "IMM,"
            operands = re.sub(r"^(\S+ )(-?\d+),", mask, operands)
        elif mnemonic == "addkpc":
            operands = re.sub(r"^\S+ \S+ ", "ADDR ", operands)
        operands = B14_OFFSET.sub(r"\1DP\2", operands)
        parts = operands.split(" ", 1)
        if mnemonic.startswith("adda") and len(parts) == 2:
            operands = parts[0] + " " + B14_ADDA.sub(r"\1DP", parts[1])
        return f"{mnemonic} {operands}"

    def body_hash(self, f):
        return hashlib.sha1("\n".join(self.body[f]).encode()).hexdigest()

    def vtable_slots(self):
        """(class, offset_to_top, slot) -> function address, for slots in the code section."""
        slots = {}
        lo, hi = self.image.code
        for c in self.rtti["classes"]:
            for vt in c["vtables"]:
                for n, e in enumerate(vt["entries"]):
                    if e and lo <= int(e, 16) < hi:
                        slots[(c["name"], vt["offset_to_top"], n)] = int(e, 16)
        return slots


class Matching:
    def __init__(self, a, b):
        self.a, self.b = a, b
        self.ab, self.ba, self.method = {}, {}, {}

    def accept(self, proposals, method):
        """Accept proposed (x, y) pairs that are one-to-one among themselves and with accepted pairs."""
        fwd, back = collections.defaultdict(set), collections.defaultdict(set)
        for x, y in proposals:
            fwd[x].add(y)
            back[y].add(x)
        added = 0
        for x, ys in fwd.items():
            if len(ys) != 1:
                continue
            y = next(iter(ys))
            if len(back[y]) != 1 or x in self.ab or y in self.ba:
                continue
            self.ab[x], self.ba[y], self.method[x] = y, x, method
            added += 1
        return added

    def by_vtable(self, min_similarity=VTABLE_MIN_SIMILARITY):
        """Same class, vtable and slot. Slots shift when a base class gains virtual methods (common between
        products and distant versions), so a slot pair is only proposed when the bodies are also similar."""
        sa, sb = self.a.vtable_slots(), self.b.vtable_slots()
        proposals = []
        for k in sa.keys() & sb.keys():
            x, y = sa[k], sb[k]
            if self.a.body[x] == self.b.body[y] or body_similarity(self.a.body[x], self.b.body[y]) >= min_similarity:
                proposals.append((x, y))
        return self.accept(proposals, "vtable")

    def by_unique_key(self, key, method):
        ka, kb = collections.defaultdict(list), collections.defaultdict(list)
        for f in self.a.starts:
            k = key(self.a, f)
            if k is not None:
                ka[k].append(f)
        for f in self.b.starts:
            k = key(self.b, f)
            if k is not None:
                kb[k].append(f)
        return self.accept([(ka[k][0], kb[k][0]) for k in ka.keys() & kb.keys()
                            if len(ka[k]) == 1 and len(kb[k]) == 1], method)

    def by_calls(self):
        """Pair callees at the same position in matched pairs' equally long callee lists.

        A function called from many places collects one vote per call site; a pair is accepted when it is
        the clear winner for both functions (at least twice the votes of any rival), so one caller with
        misaligned callee lists does not block it.
        """
        total = 0
        while True:
            votes = collections.Counter()
            for x, y in list(self.ab.items()):
                ca, cb = self.a.callees.get(x, []), self.b.callees.get(y, [])
                if ca and len(ca) == len(cb):
                    votes.update((p, q) for p, q in zip(ca, cb) if p not in self.ab and q not in self.ba)
            best_a, best_b = collections.defaultdict(list), collections.defaultdict(list)
            for (p, q), n in votes.items():
                best_a[p].append((n, q))
                best_b[q].append((n, p))

            def winner(options):
                options.sort(reverse=True)
                if len(options) == 1 or options[0][0] >= 2 * options[1][0]:
                    return options[0][1]
                return None
            proposals = [(p, q) for (p, q) in votes
                         if winner(best_a[p]) == q and winner(best_b[q]) == p]
            added = self.accept(proposals, "calls")
            total += added
            if not added:
                return total

    def by_neighbours(self, min_similarity=VTABLE_MIN_SIMILARITY):
        """Fill gaps in identically laid-out code: between two matched functions p < n whose address
        delta d is the same in both images, if the function starts strictly between them in a, shifted
        by d, are exactly the starts between them in b, pair them, each gated by body similarity.

        Short functions (driver register helpers, thunks) are below the hash pass's size limit and have
        no strings or vtable slot, but in shared driver code the surrounding functions match and keep the
        same layout (SmplTrek 3.2.174 McASPRxIntEnable 0xC16155A4 between McASPRxReset and
        McASPRxHFClkPolaritySet, same delta in Lofi-12 XT and CyDrums)."""
        matched = sorted(self.ab)
        proposals = []
        for p, n in zip(matched, matched[1:]):
            d = self.ab[p] - p
            if self.ab[n] - n != d:
                continue
            ia, ja = bisect.bisect_right(self.a.starts, p), bisect.bisect_left(self.a.starts, n)
            ib, jb = bisect.bisect_right(self.b.starts, p + d), bisect.bisect_left(self.b.starts, n + d)
            inside_a, inside_b = self.a.starts[ia:ja], self.b.starts[ib:jb]
            if not inside_a or [x + d for x in inside_a] != inside_b:
                continue
            for x, y in zip(inside_a, inside_b):
                if self.a.body[x] == self.b.body[y] or \
                        body_similarity(self.a.body[x], self.b.body[y]) >= min_similarity:
                    proposals.append((x, y))
        return self.accept(proposals, "neighbours")

    def run(self, use_vtable=True):
        counts = {}
        counts["hash"] = self.by_unique_key(
            lambda p, f: p.body_hash(f) if len(p.body[f]) >= HASH_MIN_INSNS else None, "hash")
        counts["strings"] = self.by_unique_key(lambda p, f: p.string_list[f] or None, "strings")
        if use_vtable:
            counts["vtable"] = self.by_vtable()
        counts["calls"] = self.by_calls()
        counts["neighbours"] = 0
        while True:  # each pass can enable the other
            added = self.by_neighbours()
            added += self.by_calls()
            counts["neighbours"] += added
            if not added:
                return counts

    def similarity(self, x):
        return round(body_similarity(self.a.body[x], self.b.body[self.ab[x]]), 3)


def body_similarity(p, q):
    return difflib.SequenceMatcher(None, p, q, autojunk=False).ratio()


def load(path):
    path = Path(path)
    (name, data), = list(integrity.inputs([path]))
    return Program(data, name)


def holdout(a, b):
    """Precision of the non-vtable passes, scored against the vtable pairs."""
    truth = Matching(a, b)
    truth.by_vtable()
    test = Matching(a, b)
    test.run(use_vtable=False)
    scored = {x: y for x, y in test.ab.items() if x in truth.ab}
    agree = sum(1 for x, y in scored.items() if truth.ab[x] == y)
    by_method = collections.Counter(test.method[x] for x in scored)
    wrong = collections.Counter(test.method[x] for x, y in scored.items() if truth.ab[x] != y)
    return {"vtable_pairs": len(truth.ab), "scored": len(scored), "agree": agree,
            "scored_by_method": dict(by_method), "wrong_by_method": dict(wrong),
            "recall_of_vtable_pairs": round(len(scored) / max(1, len(truth.ab)), 3)}


def transfer(symbols, match):
    """Carry function symbols from image a to image b through the matching."""
    out = []
    for entry in symbols["symbols"]:
        if entry["kind"] != "function":
            continue
        x = int(entry["address"], 16)
        y = match.ab.get(x)
        record = {"name": entry["name"], "a": entry["address"], "b": None}
        if y is not None:
            located = match.b.image.locate(y)
            a0, d = located
            prefix_b = symfile.prefix_hash(d[y - a0:y - a0 + symfile.PREFIX_LEN])
            record.update(b=f"0x{y:08x}", method=match.method[x], similarity=match.similarity(x),
                          prefix_sha256_b=prefix_b, prefix_equal=prefix_b == entry["prefix_sha256"])
        out.append(record)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("a", help="reference update .zip/.bin")
    parser.add_argument("b", help="other update .zip/.bin")
    parser.add_argument("-o", "--output", help="JSON output (keep under work/)")
    parser.add_argument("--symbols", help="symbols JSON for image a, carried to image b")
    parser.add_argument("--holdout-vtable", action="store_true",
                        help="also score the non-vtable passes against the vtable pairs")
    args = parser.parse_args()

    a, b = load(args.a), load(args.b)
    match = Matching(a, b)
    counts = match.run()
    va, vb = ".".join(map(str, a.version)), ".".join(map(str, b.version))
    print(f"{a.label} ({va}): {len(a.starts)} functions; {b.label} ({vb}): {len(b.starts)} functions")
    print(f"matched {len(match.ab)} ({100 * len(match.ab) // len(a.starts)}% of a): {counts}")
    document = {
        "a": {"file": a.label, "sha256": a.sha256, "mmtd_version": va, "functions": len(a.starts)},
        "b": {"file": b.label, "sha256": b.sha256, "mmtd_version": vb, "functions": len(b.starts)},
        "counts": counts,
        "matches": [{"a": f"0x{x:08x}", "b": f"0x{y:08x}", "method": match.method[x],
                     "similarity": match.similarity(x)} for x, y in sorted(match.ab.items())],
    }
    if args.holdout_vtable:
        document["holdout"] = holdout(a, b)
        print("holdout:", document["holdout"])
    if args.symbols:
        document["transferred"] = transfer(json.loads(Path(args.symbols).read_text()), match)
        for t in document["transferred"]:
            print("  ", t)
    if args.output:
        Path(args.output).write_text(json.dumps(document, indent=1) + "\n")
        print("Wrote", args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
