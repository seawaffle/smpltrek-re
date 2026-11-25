#!/usr/bin/env python3
"""Turn stock_register_capture.py's raw capture into per-peripheral register-write tables (CSV).

Input: work/register-capture/raw.json (stock_register_capture.py) and emulator/register_map.json
(register_map_build.py: names, widths, reset values and fields from SPRUH79C and SLAS509G). Output, by default
docs/stock-register-writes/:

  usb0.csv           USB0 core and wrapper, SYSCFG0 KICK/CFGCHIP2, PSC1 module 1
  i2c0.csv           I2C0 (the codec's bus), its PINMUX4 field and EDMA claims, PSC1 module (none: always on)
  codec.csv          the AIC3106 register writes over I2C, as (page, register, value)
  mcasp-edma.csv     McASP0, its PINMUX0/1 fields, PSC1 module 7, EDMA3 channel controller rows and the PaRAM
                     sets of McASP's events 0 and 1 (and the sets they link to); PSC0 modules 0-2 (EDMA)
  mmcsd.csv          MMCSD0, PINMUX10, PSC0 module 5, EDMA channels 16/17 and their PaRAM sets
  sd-commands.csv    every SD command the card saw, with argument and response

Options for other captures:
- --raw FILE: any capture in stock_register_capture.py's raw format, such as another firmware's.
- --all-runs: emit every run and phase, each under its own scenario name. By default only main and common runs are listed, plus the card_reader phase of the card-reader run.
- --symbols FILE: a {name: address} JSON naming that firmware's PCs, in place of the stock's symbol file.
- --product: picks the stock product's symbols.
- --collapse-sd: summarises runs of SD data commands.

Rows fold by (PC, register address, register name with its INDEX, direction, value). So a write under another INDEX, which reaches another endpoint's register at the same address, keeps its own row.

Columns (CSV): order, run, phase, step, access (write / read / poll), address, register, width, value, before,
reset, changed, count, pc, function, evidence.
- `before` is the register's last value seen on the bus in this run (written, or read back), else its reset
  value: the software's view. Bits that hardware changes without being read (status, self-clearing bits) can
  differ from it on the chip.
- `changed` names the fields whose value differs between `before` and the write, as FIELD old->new.
- `count`: for a poll, how many identical reads in a row; for a data register (USB FIFOn, MMCDRR/MMCDXR),
  consecutive accesses merged into one row, whose value is always "data": the payload (descriptor bytes, MIDI
  events, card sectors holding Sonicware content) is never written out; for any other row, 1 + the later identical accesses (same PC,
  register, value) in the same phase that were folded into it (periodic interrupt work).
- Width is the register's; an access narrower or wider than the register is shown per register touched.
"""
import argparse
import bisect
import collections
import csv
import json
from pathlib import Path
import pickle
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from build import WORK

DMA_PC = 0xFFFFFFF0
DATA = {0x01E00420, 0x01E00424, 0x01E00428, 0x01E0042C, 0x01E00430, 0x01C40028, 0x01C4002C}
PSC0, PSC1 = 0x01C10000, 0x01E27000
EDMA, PARAM = 0x01C00000, 0x01C04000
CHANNEL_REGISTERS = {0x1000: "ER", 0x1008: "ECR", 0x1010: "ESR", 0x1018: "CER", 0x1020: "EER", 0x1028: "EECR",
                     0x1030: "EESR", 0x1038: "SER", 0x1040: "SECR", 0x1050: "IER", 0x1058: "IECR", 0x1060: "IESR",
                     0x1068: "IPR", 0x1070: "ICR", 0x300: "EMR", 0x308: "EMCR", 0x340: "DRAE0"}
OWNER_CHANNELS = {"mcasp-edma": {0, 1}, "mmcsd": {16, 17}, "i2c0": {24, 25, 26}}
CODEC_I2C = 0x18


SYMBOLS = {"smpltrek": "smpltrek-3.2.174", "lofi12": "lofi-12xt-1.5.205", "cydrums": "cydrums-1.1.84"}


def load_symbol_file(path):
    """A {name: address} JSON (another firmware's symbols): every address is a possible function start."""
    names = {int(address, 16) if isinstance(address, str) else int(address): name
             for name, address in json.loads(Path(path).read_text()).items()}
    return names, sorted(names), False


def load_symbols(product="smpltrek"):
    """({start: name}, sorted starts, whether the starts are complete). Only SmplTrek has a list of every
    function start (work/smpltrek-function-starts.pkl); for the others the named functions are the only starts."""
    data = json.loads((ROOT / "symbols" / f"{SYMBOLS[product]}.json").read_text())
    names = {}
    for entry in data["symbols"]:
        address = entry["address"]
        address = int(address, 16) if isinstance(address, str) else address
        if entry.get("kind") == "function":
            names[address] = entry["name"]
    if product != "smpltrek":
        return names, sorted(names), False
    starts = sorted(pickle.loads((WORK.parent / "smpltrek-function-starts.pkl").read_bytes())
                    if (WORK.parent / "smpltrek-function-starts.pkl").exists() else
                    pickle.loads((ROOT / "work/smpltrek-function-starts.pkl").read_bytes()))
    return names, sorted(set(starts) | set(names)), True   # the starts list misses some named functions


class Tables:
    def __init__(self, register_map, product="smpltrek", symbols=None, all_runs=False):
        self.soc = {int(k, 16): v for k, v in register_map["soc"].items()}
        self.codec = register_map["codec"]
        self.names, self.starts, self.complete = load_symbol_file(symbols) if symbols else load_symbols(product)
        self.all_runs = all_runs

    def function(self, pc):
        if pc == DMA_PC:
            return "(EDMA transfer)"
        at = bisect.bisect_right(self.starts, pc) - 1
        if at < 0:
            return ""
        start = self.starts[at]
        if not self.complete:   # the nearest named function below: the PC may lie in an unnamed one after it
            return f"{self.names[start]}+{pc - start:#x}?"
        return self.names.get(start, f"fn_{start:08X}")

    def registers(self, address, size):
        """[(register address, entry, byte offset of the access within the register, bytes)] the access covers."""
        found = []
        for base in range(address - 3, address + size):
            entry = self.soc.get(base)
            if not entry:
                continue
            width = entry.get("width", 32) // 8
            low, high = max(base, address), min(base + width, address + size)
            if low < high:
                found.append((base, entry, low - base, high - low))
        return found


def owner_of(tables, register, entry, value, write, param_owner):
    """Which table(s) a register access belongs to."""
    name, peripheral = entry["name"], entry["peripheral"]
    if peripheral == "USB0":
        return {"usb0"}
    if peripheral == "I2C0":
        return {"i2c0"}
    if peripheral == "McASP0":
        return {"mcasp-edma"}
    if peripheral == "MMCSD0":
        return {"mmcsd"}
    if peripheral == "SYSCFG0":
        if name in ("KICK0R", "KICK1R"):
            return {"usb0", "mcasp-edma", "mmcsd", "i2c0"}
        if name == "CFGCHIP2":
            return {"usb0"}
        if name == "PINMUX4":
            return {"i2c0"}
        if name in ("PINMUX0", "PINMUX1"):
            return {"mcasp-edma"}
        if name == "PINMUX10":
            return {"mmcsd"}
        return set()
    if peripheral in ("PSC0", "PSC1"):
        module = None
        for prefix in ("MDCTL", "MDSTAT"):
            if name.startswith(prefix):
                module = int(name[len(prefix):])
        table = {("PSC1", 1): "usb0", ("PSC1", 7): "mcasp-edma", ("PSC0", 5): "mmcsd", ("PSC0", 0): "mcasp-edma",
                 ("PSC0", 1): "mcasp-edma", ("PSC0", 2): "mcasp-edma"}
        if module is not None:
            return {table[(peripheral, module)]} if (peripheral, module) in table else set()
        return {"psc-transition"}   # PTCMD / PTSTAT / PDSTAT: placed with the module write next to them
    if peripheral == "EDMA3CC0":
        if register >= PARAM:
            owner = param_owner.get((register - PARAM) // 32)
            return {owner} if owner else set()
        offset = register - EDMA
        if offset in CHANNEL_REGISTERS or 0x2000 <= offset < 0x4000 and (offset & 0x1FF) + 0x1000 in CHANNEL_REGISTERS:
            channels = {bit for bit in range(32) if value >> bit & 1}
            owners = {table for table, own in OWNER_CHANNELS.items() if channels & own}
            return owners or {"mcasp-edma"}   # a read of 0, or the shared set-up
        if offset in range(0x240, 0x250):   # DMAQNUMn: four bits per channel
            n = (offset - 0x240) // 4
            channels = {8 * n + k for k in range(8) if value >> (4 * k) & 7}
            owners = {table for table, own in OWNER_CHANNELS.items() if channels & own}
            return owners or {"mcasp-edma"}
        return {"mcasp-edma"}   # controller-wide set-up (shared by every EDMA user)
    return set()


def fields_changed(entry, before, after, mask):
    if before is None or "fields" not in entry:
        return ""
    changes = []
    for high, low, _, name in entry["fields"]:
        field_mask = ((1 << (high - low + 1)) - 1) << low
        if not field_mask & mask:
            continue
        old, new = (before & field_mask) >> low, (after & field_mask) >> low
        if old != new:
            label = name if name and name != "Reserved" else f"bits {high}:{low}"
            changes.append(f"{label} {old:#x}->{new:#x}")
    return "; ".join(changes)


def build(tables, runs):
    rows = collections.defaultdict(list)
    for run in runs:
        seen = {}            # register -> last value on the bus (this run)
        param_owner = {0: "mcasp-edma", 1: "mcasp-edma", 16: "mmcsd", 17: "mmcsd"}
        recent_psc = {}      # PSC base -> owner of the last module write
        index = 0            # USB0 INDEX: which endpoint 0x410-0x41F and the FIFO size/address registers mean
        mounted = False      # the card's first mount is done: later card traffic is summarised
        for phase in run["phases"]:
            name = phase["name"]
            # The card-reader run repeats the main run's opening phases: they update the tracked state (values
            # seen, INDEX, PaRAM owners) but are not listed again.
            emit = tables.all_runs or run["scenario"] in ("main", "common") or name == "card_reader"
            steps = phase.get("steps", [])
            # The MMC/SD detail stops after the first mount (the card's set-up and its first block read); the file
            # reads that follow are summarised, and listed command by command in sd-commands.csv.
            sd = phase["sd"]
            first_read = next((n for n, c in enumerate(sd) if c["command"] in ("CMD17", "CMD18") and n and
                               any(x["command"] == "CMD13" for x in sd[:n])), None)
            mmc_until = sd[first_read + 1]["cycles"] if first_read is not None and first_read + 1 < len(sd) else None
            rest = len(sd) - first_read - 2 if mmc_until is not None else len(sd)
            if mounted and not any(c["command"] == "CMD0" for c in sd):
                mmc_until = -1   # a phase with no card set-up of its own: all of its card traffic is summarised
            mounted = mounted or mmc_until is not None
            mmc_cut = False
            folded = collections.defaultdict(dict)   # table -> key -> row (later identical accesses)
            for access in phase["mmio"]:
                step = next((s["step"] for s in steps if s["submitted"] <= access["cycles"] <= s["completed"] + 2000), "")
                for register, entry, offset, size in tables.registers(access["address"], access["size"]):
                    width = entry.get("width", 32)
                    raw = (access["value"] >> (8 * (register + offset - access["address"]))) & ((1 << (8 * size)) - 1)
                    in_register = raw << (8 * offset)
                    mask = ((1 << (8 * size)) - 1) << (8 * offset)
                    reset = entry.get("reset")
                    before = seen.get(register, reset)
                    value = ((before or 0) & ~mask | in_register) if access["write"] else in_register
                    owners = owner_of(tables, register, entry, in_register, access["write"], param_owner)
                    if entry["peripheral"] in ("PSC0", "PSC1"):
                        base = PSC0 if entry["peripheral"] == "PSC0" else PSC1
                        if "psc-transition" in owners:
                            owners = {recent_psc[base]} if base in recent_psc else set()
                        elif owners and access["write"]:
                            recent_psc[base] = next(iter(owners))
                    if entry["peripheral"] == "EDMA3CC0" and register >= PARAM and entry["name"].endswith("LINK_BCNTRLD") \
                            and access["write"]:
                        link = in_register & 0xFFFF
                        if link != 0xFFFF and owners:
                            param_owner[(link - 0x4000) // 32] = next(iter(owners))
                    if mmc_until is not None and access["cycles"] > mmc_until and "mmcsd" in owners:
                        owners = owners - {"mmcsd"}
                        if not mmc_cut and emit:
                            mmc_cut = True
                            rows["mmcsd"].append(dict(run=run["scenario"], phase=name, access="summary",
                                                      register=f"(the {'remaining ' if mmc_until >= 0 else ''}{rest} SD "
                                                      "commands of this phase: file "
                                                      "reads and writes, in sd-commands.csv; their register sequence "
                                                      "repeats the first block read's)", evidence="emulated"))
                    if not owners or not emit:
                        seen[register] = value if access["write"] else (before or 0) & ~mask | in_register
                        if register == 0x01E0040E and access["write"]:
                            index = in_register & 0xF
                        continue
                    kind = "write" if access["write"] else ("poll" if access["repeat"] > 1 else "read")
                    label = entry["name"]
                    if 0x01E00410 <= register < 0x01E00420 or 0x01E00462 <= register < 0x01E00468:
                        label = f"{label} [INDEX {index}]"
                    if register == 0x01E0040E and access["write"]:
                        index = in_register & 0xF
                    row = dict(run=run["scenario"], phase=name, step=step, access=kind, address=f"{register:#010x}"
                               + (f"+{offset}" if offset else ""), register=label, width=width,
                               value=f"{in_register >> (8 * offset):#x}" if size * 8 < width else f"{value:#x}",
                               before="" if before is None else f"{before:#x}",
                               reset="" if reset is None else f"{reset:#x}",
                               changed=fields_changed(entry, before, value, mask) if access["write"] else "",
                               count=access["repeat"], pc=f"{access['pc']:#010x}", function=tables.function(access["pc"]),
                               evidence="emulated")
                    if size * 8 < width:
                        row["value"] = f"{in_register:#x} (bytes {offset}..{offset + size - 1})"
                    if register in DATA:   # payload (descriptors, MIDI, card sectors): never written out
                        row.update(value="data", before="", changed="")
                    seen[register] = value if access["write"] else (before or 0) & ~mask | in_register
                    for table in owners:
                        target = rows[table]
                        # The label carries INDEX for the indexed registers: the same address under another INDEX is
                        # another endpoint's register and must not fold into the first one's row.
                        key = (access["pc"], register, label, access["write"], in_register, mask)
                        if register in DATA:
                            last = target[-1] if target else None
                            if last and last["phase"] == name and last["address"] == row["address"] and \
                                    last["access"] == kind and last["pc"] == row["pc"]:
                                last["count"] += 1
                                last["value"] = "data"
                                continue
                        elif key in folded[table] and target and target[-1] is not folded[table][key]:
                            folded[table][key]["count"] += access["repeat"] if kind == "poll" else 1
                            continue
                        copy = dict(row)
                        target.append(copy)
                        folded[table].setdefault(key, copy)
    return rows


def codec_rows(tables, runs):
    out = []
    for run in runs:
        shadow = {}
        for phase in run["phases"]:
            if not tables.all_runs and run["scenario"] == "card_reader" and phase["name"] != "card_reader":
                continue
            for write in phase["codec"]:
                key = f'{write["page"]}/{write["register"]}'
                entry = tables.codec.get(key, dict(name="", reset=None, fields=[]))
                reset = entry.get("reset") if entry.get("known") else None
                before = shadow.get(key, reset)
                if write["page"] == 0 and write["register"] == 1 and write["value"] & 0x80:
                    shadow = {}   # a software reset returns every register to its reset value
                value = write["value"]
                changes = []
                if before is not None and not write["read"]:
                    for high, low, _, name in entry["fields"]:
                        mask = ((1 << (high - low + 1)) - 1) << low
                        old, new = (before & mask) >> low, (value & mask) >> low
                        if old != new:
                            changes.append(f"{name} {old:#x}->{new:#x}")
                if not write["read"] and key != "0/1":
                    shadow[key] = value
                out.append(dict(run=run["scenario"], phase=phase["name"], access="read" if write["read"] else "write",
                                page=write["page"], register=write["register"], name=entry["name"], value=f"{value:#04x}",
                                before="" if before is None else f"{before:#04x}",
                                reset="" if reset is None else f"{reset:#04x}", changed="; ".join(changes),
                                cycles=write["cycles"], evidence="emulated (I2C transfers decoded by the codec model)"))
    return out


DATA_COMMANDS = {"CMD17", "CMD18", "CMD24", "CMD25", "CMD12", "CMD13"}


def sd_rows(runs, collapse=False, all_runs=False):
    """Every SD command; with `collapse`, a run of more than four data commands (block reads and writes, CMD12,
    CMD13) becomes one summary row with the commands counted and the argument range."""
    out = []
    for run in runs:
        for phase in run["phases"]:
            if not all_runs and run["scenario"] == "card_reader" and phase["name"] != "card_reader":
                continue
            commands, n = phase["sd"], 0
            while collapse and n < len(commands):
                end = n
                while end < len(commands) and commands[end]["command"] in DATA_COMMANDS:
                    end += 1
                if end - n > 4:
                    counted = collections.Counter(c["command"] for c in commands[n:end])
                    arguments = [c["argument"] for c in commands[n:end] if c["command"] != "CMD13"]
                    out.append(dict(run=run["scenario"], phase=phase["name"], index_in_phase=f"{n}-{end - 1}",
                                    command="data: " + ", ".join(f"{k} x{v}" for k, v in sorted(counted.items())),
                                    argument=f"{min(arguments):#010x}..{max(arguments):#010x}" if arguments else "",
                                    cycles=commands[n]["cycles"], evidence="emulated (card model)"))
                    n = end
                    continue
                command = commands[n]
                out.append(dict(run=run["scenario"], phase=phase["name"], index_in_phase=n, command=command["command"],
                                argument=f'{command["argument"]:#010x}', answered=command["answered"],
                                response=f'{command["response"]:#010x}' if command["answered"] else "",
                                long_response=command["long"], card_state_after=command["state"], cycles=command["cycles"],
                                evidence="emulated (card model)"))
                n += 1
            for n, command in enumerate([] if collapse else phase["sd"]):
                out.append(dict(run=run["scenario"], phase=phase["name"], index_in_phase=n, command=command["command"],
                                argument=f'{command["argument"]:#010x}', answered=command["answered"],
                                response=f'{command["response"]:#010x}' if command["answered"] else "",
                                long_response=command["long"], card_state_after=command["state"], cycles=command["cycles"],
                                evidence="emulated (card model)"))
    return out


def write_csv(path, rows, columns):
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for order, row in enumerate(rows, 1):
            writer.writerow(dict(row, order=order))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", type=Path, default=WORK / "register-capture" / "raw.json")
    parser.add_argument("--map", type=Path, default=HERE / "register_map.json")
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "stock-register-writes")
    parser.add_argument("--product", choices=tuple(SYMBOLS), default="smpltrek", help="whose symbols name the PCs")
    parser.add_argument("--collapse-sd", action="store_true", help="summarise runs of SD data commands")
    parser.add_argument("--all-runs", action="store_true", help="every run and phase, each under its own scenario name "
                        "(by default: main and common runs, and only the card_reader phase of the card-reader run)")
    parser.add_argument("--symbols", type=Path, help="a {name: address} JSON naming another firmware's PCs "
                        "(nearest symbol below the PC, plus offset, marked ?) instead of the stock's symbols")
    args = parser.parse_args(argv)
    runs = json.loads(args.raw.read_text())
    tables = Tables(json.loads(args.map.read_text()), args.product, args.symbols, args.all_runs)
    args.output.mkdir(parents=True, exist_ok=True)
    columns = ["order", "run", "phase", "step", "access", "address", "register", "width", "value", "before", "reset",
               "changed", "count", "pc", "function", "evidence"]
    built = build(tables, runs)
    for table in ("usb0", "i2c0", "mcasp-edma", "mmcsd"):
        write_csv(args.output / f"{table}.csv", built[table], columns)
        print(f"{table}.csv: {len(built[table])} rows")
    codec = codec_rows(tables, runs)  # honours tables.all_runs
    write_csv(args.output / "codec.csv", codec, ["order", "run", "phase", "access", "page", "register", "name", "value",
                                                 "before", "reset", "changed", "cycles", "evidence"])
    sd = sd_rows(runs, collapse=args.collapse_sd, all_runs=args.all_runs)
    write_csv(args.output / "sd-commands.csv", sd, ["order", "run", "phase", "index_in_phase", "command", "argument",
                                                     "answered", "response", "long_response", "card_state_after", "cycles",
                                                     "evidence"])
    print(f"codec.csv: {len(codec)} rows, sd-commands.csv: {len(sd)} rows")


if __name__ == "__main__":
    main()
