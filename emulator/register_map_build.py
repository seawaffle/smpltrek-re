#!/usr/bin/env python3
"""Build emulator/register_map.json: names, widths, reset values and fields of the C6748 registers the stock
firmware touches (SPRUH79C) and of the AIC3106 codec (SLAS509G), read from the documents' text.

The SoC part comes from each chapter's register summary table (address or offset, acronym) and each register's
figure (bit numbers, field names, access and reset value "R/W-1"); families the tables give as one row (PSC
MDCTLn, McASP SRCTLn, USB endpoint registers at 0x500 + 16n, EDMA PaRAM entries, the CPPI and queue-manager
words) are expanded by rule. A reset is recorded per field; `known` is the mask of bits whose reset the figure
gives (an "X" field leaves its bits out). The codec part comes from SLAS509G's per-register tables (Table 10-n,
"Page p / Register r"), one row per bit field with its reset bits.

Usage (from the repository root; pdftotext from poppler):
  python3 -B emulator/register_map_build.py --trm spruh79c.pdf --codec tlv320aic3106.pdf
Text files (pdftotext -layout output) can be given instead of the PDFs.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

TOKEN = re.compile(r'(?<!\S)((?:R/W|R/WC|R/W1C|R/W1S|RW|R|W|W1C|W1S|WC|RC|R/C|R/S|R/W0C)\s?[-−–]\s?([0-9A-Fa-fx]+h?))(?!\S)')
NUMBERS = re.compile(r'^\s*(\d+\s+)*\d+\s*$')
OUTPUT = Path(__file__).resolve().parent / "register_map.json"


def text(path):
    path = Path(path)
    if path.suffix.lower() != ".pdf":
        return path.read_text()
    return subprocess.run(["pdftotext", "-layout", str(path), "-"], check=True, capture_output=True, text=True).stdout


def split(numbers, tokens):
    """Partition the bit numbers (by column) into len(tokens) consecutive groups of one number (a one-bit field)
    or two (high and low bit), in token order, minimising each token's distance to its group's centre."""
    m_count, n_count, inf = len(numbers), len(tokens), float("inf")
    best = [[inf] * (n_count + 1) for _ in range(m_count + 1)]
    back = [[None] * (n_count + 1) for _ in range(m_count + 1)]
    best[0][0] = 0
    for m in range(m_count):
        for n in range(n_count):
            if best[m][n] == inf:
                continue
            for size in (1, 2):
                if m + size > m_count or (size == 2 and numbers[m][1] <= numbers[m + 1][1]):
                    continue
                centre = sum(column for column, _ in numbers[m:m + size]) / size
                cost = best[m][n] + abs(centre - tokens[n][0])
                if cost < best[m + size][n + 1]:
                    best[m + size][n + 1], back[m + size][n + 1] = cost, size
    if best[m_count][n_count] == inf:
        return None
    groups, m, n = {}, m_count, n_count
    while n:
        size = back[m][n]
        groups[n - 1] = [value for _, value in numbers[m - size:m]]
        m, n = m - size, n - 1
    return groups


def figure(lines, start):
    """(reset, width, known mask, fields [[high, low, reset or None, name]]) of the figure at line `start`."""
    value = known = width = 0
    fields = []
    i = start + 1
    while i < len(lines) and "LEGEND" not in lines[i] and i < start + 60:
        if not (NUMBERS.match(lines[i]) and lines[i].strip()):
            i += 1
            continue
        numbers = sorted((m.start() + len(m.group()) / 2, int(m.group())) for m in re.finditer(r"\d+", lines[i]))
        width = max(width, max(n for _, n in numbers) + 1)
        j = i + 1
        while j < len(lines) and not TOKEN.search(lines[j]) and not NUMBERS.match(lines[j]) and "LEGEND" not in lines[j]:
            j += 1
        if j >= len(lines) or not TOKEN.search(lines[j]):
            i += 1
            continue
        tokens = [(m.start() + len(m.group()) / 2, m.group(2)) for m in TOKEN.finditer(lines[j])]
        names = [(m.start() + len(m.group()) / 2, re.sub(r"\s*\(\w\)$", "", m.group()))
                 for k in range(i + 1, j) for m in re.finditer(r"\S+(?: \S+)*", lines[k]) if not re.fullmatch(r"\(\w\)", m.group())]
        groups = split(numbers, tokens)
        if groups is None:
            i = j + 1
            continue
        for k, (column, raw) in enumerate(tokens):
            if not groups[k]:
                continue
            high, low = max(groups[k]), min(groups[k])
            name = min(names, key=lambda n: abs(n[0] - column))[1] if names else ""
            raw = raw.lower()
            if "x" in raw.replace("h", ""):
                fields.append([high, low, None, name])
                continue
            reset = (int(raw[:-1], 16) if raw.endswith("h") else int(raw, 2) if set(raw) <= {"0", "1"} and len(raw) > 1
                     else int(raw) if raw.isdigit() else int(raw, 16))
            mask = (1 << (high - low + 1)) - 1
            value |= (reset & mask) << low
            known |= mask << low
            fields.append([high, low, reset, name])
        i = j + 1
    return value, width, known, fields


def find(lines, acronym, start, end):
    pattern = re.compile(r"Figure \d+-\d+\.\s.*\(" + re.escape(acronym) + r"\)\s*$")
    return next((i for i in range(start, min(end, len(lines))) if pattern.search(lines[i]) and "...." not in lines[i]), None)


# name: (base, summary table title, whether its rows give absolute addresses)
CHAPTERS = {
    "PSC0": (0x01C10000, r"Table 8-6\. Power and Sleep Controller 0 \(PSC0\) Registers", True),
    "PSC1": (0x01E27000, r"Table 8-7\. Power and Sleep Controller 1 \(PSC1\) Registers", True),
    "SYSCFG0": (0x01C14000, r"Table 10-3\. System Configuration Module 0 \(SYSCFG0\) Registers", True),
    "EDMA3CC0": (0x01C00000, r"Table 16-23\. EDMA3 Channel Controller \(EDMA3CC\) Registers", False),
    "I2C0": (0x01C22000, r"Table 21-4\. Inter-Integrated Circuit \(I2C\) Registers", False),
    "McASP0": (0x01D00000, r"Table 23-7\. McASP Registers Accessed by CPU/EDMA Through", False),
    "MMCSD0": (0x01C40000, r"Table 25-5\. Multimedia Card/Secure Digital \(MMC/SD\) Card Controller Registers", False),
    "USB0": (0x01E00000, r"Table 33-30\. Universal Serial Bus OTG \(USB0\) Registers", False),
}
ROW_ABSOLUTE = re.compile(r"^\s*([0-9A-F]{4}) ([0-9A-F]{4})h(-?)\s+([A-Za-z_][A-Za-z0-9_\[\]]*-?)")
ROW_OFFSET = re.compile(r"^\s*([0-9A-F]+)h(-?)\s+([A-Za-z_][A-Za-z0-9_\[\]]*-?)\s")


def soc(lines):
    starts = {name: next(i for i, line in enumerate(lines) if re.search(title, line) and "...." not in line)
              for name, (_, title, _) in CHAPTERS.items()}
    ordered = sorted(set(starts.values()))
    registers = {}

    def bounds(chapter):
        """From the chapter's summary table to the next chapter's (PSC0 and PSC1 share a chapter)."""
        start = starts[chapter]
        return start, min([s for s in ordered if s - start > 100] + [start + 9000])

    def describe(chapter, acronym):
        start, end = bounds(chapter)
        found = find(lines, acronym, start, end)
        if found is None:
            return {}
        reset, width, known, fields = figure(lines, found)
        return dict(reset=reset, width=width or 32, known=known, fields=fields, figure=lines[found].strip())

    def add(address, name, chapter, acronym=None, width=None, **extra):
        key = acronym or name
        entry = dict(name=name, peripheral=chapter, **describe(chapter, key))
        if "reset" not in entry:
            for alternative in (re.sub(r"\d+$", "n", key), re.sub(r"\d+$", "m", key), re.sub(r"\d+$", "", key),
                                re.sub(r"\[\d+\]", "[n]", key), re.sub(r"\[\d+\]", "[R]", key)):
                entry.update(describe(chapter, alternative))
                if "reset" in entry:
                    break
        if width:
            entry["width"] = width
        entry.setdefault("width", 32)
        entry.update(extra)
        registers[address] = entry

    for chapter, (base, _, absolute) in CHAPTERS.items():
        start, pending = starts[chapter], None
        for i in range(start + 1, start + 1200):
            title = re.match(r"^\s*Table (\d+-\d+)\.", lines[i])
            if title and title.group(1) != re.match(r"^\s*Table (\d+-\d+)\.", lines[start]).group(1):
                break
            match = (ROW_ABSOLUTE if absolute else ROW_OFFSET).match(lines[i])
            if not match:
                continue
            if absolute:
                address, dash, name = int(match.group(1) + match.group(2), 16), match.group(3), match.group(4)
            else:
                address, dash, name = base + int(match.group(1), 16), match.group(2), match.group(3)
            if pending:   # the end of a range row: "MDCTL0-" ... "MDCTL15"
                first_address, first_name = pending
                pending = None
                low, high = re.match(r"(.*?)(\d+)$", first_name), re.match(r"(.*?)(\d+)$", name)
                if low and high:
                    stem, first, last = low.group(1), int(low.group(2)), int(high.group(2))
                    step = (address - first_address) // max(1, last - first)
                    for k in range(first, last + 1):
                        if first_address + (k - first) * step not in registers:
                            add(first_address + (k - first) * step, f"{stem}{k}", chapter, stem + "n")
                continue
            if dash or name.endswith("-"):
                pending = (address, name.rstrip("-"))
            elif address not in registers:
                add(address, name, chapter)

    for n in range(128):   # EDMA3 PaRAM: RAM, no reset value
        for k, name in enumerate(("OPT", "SRC", "A_B_CNT", "DST", "SRC_DST_BIDX", "LINK_BCNTRLD", "SRC_DST_CIDX", "CCNT")):
            registers[0x01C04000 + 32 * n + 4 * k] = dict(name=f"PaRAM{n}.{name}", peripheral="EDMA3CC0", width=32,
                                                           note="PaRAM is RAM: no reset value")
    for offset, name in ((0x30C, "EMCRH"), (0x34C, "DRAEH1")):
        registers.setdefault(0x01C00000 + offset, dict(name=f"{name} (offset {offset:#x})", peripheral="EDMA3CC0", width=32,
                                                       note="not in the C6748 EDMA3CC table (a 64-channel register)"))
    usb = 0x01E00000
    endpoint = [(0, "TXMAXP", 16, "TXMAXP"), (2, "TXCSR", 16, "PERI_TXCSR"), (4, "RXMAXP", 16, "RXMAXP"),
                (6, "RXCSR", 16, "PERI_RXCSR"), (8, "RXCOUNT", 16, "RXCOUNT"), (10, "TXTYPE", 8, "HOST_TXTYPE"),
                (11, "TXINTERVAL", 8, "HOST_TXINTERVAL"), (12, "RXTYPE", 8, "HOST_RXTYPE"),
                (13, "RXINTERVAL", 8, "HOST_RXINTERVAL"), (15, "CONFIGDATA", 8, "CONFIGDATA")]
    for n in range(5):
        for offset, name, width, acronym in endpoint:
            if n == 0 and name == "TXCSR":
                name, acronym = "CSR0", "PERI_CSR0"
            elif n == 0 and name == "RXCOUNT":
                name, acronym = "COUNT0", "COUNT0"
            elif n and name == "CONFIGDATA":
                continue
            add(usb + 0x500 + 16 * n + offset, f"EP{n}.{name}", "USB0", acronym, width)
    for offset, width in ((0x462, 8), (0x463, 8)):
        registers[usb + offset]["width"] = width
    for offset, acronym in ((0x464, "TXFIFOADDR"), (0x466, "RXFIFOADDR")):
        add(usb + offset, acronym, "USB0", width=16)
    for offset in (0x808, 0x80C, 0x848, 0x84C):
        registers[usb + offset] = dict(name=f"reserved {offset:#x}", peripheral="USB0", width=32,
                                       note="not in SPRUH79C; reads 0 on the unit with no host (M1 bench I5)")
    for n in range(64):
        add(usb + 0x2800 + 4 * n, f"WORD[{n}]", "USB0")
    for offset, acronym in ((0x4080, "LRAM0BASE"), (0x4084, "LRAM0SIZE"), (0x4088, "LRAM1BASE")):
        add(usb + offset, acronym, "USB0")
    for n in range(16):
        add(usb + 0x5000 + 16 * n, f"QMEMRBASE[{n}]", "USB0")
        add(usb + 0x5004 + 16 * n, f"QMEMRCTRL[{n}]", "USB0")
    return registers


TITLE = re.compile(r"Table 10-\d+\. Page (\d) / Register (\d+)(?:–(\d+))?:\s*(.*?)\s*(?:\(continued\))?\s*$")
FIELD = re.compile(r"^\s*D(\d)(?:\s*[–-]\s*D(\d))?\s+(R/W|R|W|RC)\S*\s+([01Xx]+(?: [01Xx]+)*)\s+(.*)$")


def codec(lines):
    registers, current = {}, None
    for line in lines:
        title = TITLE.search(line)
        if title and "...." not in line:
            page, first, last = int(title.group(1)), int(title.group(2)), title.group(3)
            current = [f"{page}/{r}" for r in (range(first, int(last) + 1) if last else [first])]
            for key in current:
                registers.setdefault(key, dict(name=title.group(4).rstrip(), reset=0, known=0, fields=[]))
            continue
        match = FIELD.match(line) if current else None
        if not match:
            continue
        high = int(match.group(1))
        low = int(match.group(2)) if match.group(2) else high
        raw = match.group(4).replace(" ", "")
        name = re.split(r"\s{2,}", match.group(5).strip())[0]
        for key in current:
            entry = registers[key]
            if any(f[0] == high and f[1] == low for f in entry["fields"]):
                continue
            reset = int(raw, 2) if set(raw) <= {"0", "1"} and len(raw) == high - low + 1 else None
            if reset is not None:
                entry["reset"] |= reset << low
                entry["known"] |= ((1 << (high - low + 1)) - 1) << low
            entry["fields"].append([high, low, reset, name])
    return registers


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trm", required=True, help="SPRUH79C (C6748 TRM), PDF or pdftotext -layout text")
    parser.add_argument("--codec", required=True, help="SLAS509G (TLV320AIC3106 data sheet), PDF or text")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    soc_map = soc(text(args.trm).split("\n"))
    codec_map = codec(text(args.codec).split("\n"))
    result = dict(sources=dict(soc="TI SPRUH79C (April 2013, revised September 2016)", codec="TI SLAS509G (July 2021)"),
                  soc={f"{address:08X}": entry for address, entry in sorted(soc_map.items())}, codec=codec_map)
    args.output.write_text(json.dumps(result, indent=1) + "\n")
    print(f"{len(soc_map)} SoC registers, {len(codec_map)} codec registers -> {args.output}")


if __name__ == "__main__":
    main()
