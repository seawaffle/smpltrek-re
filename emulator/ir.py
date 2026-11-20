"""Translate objdump instruction text to the fixed C ABI, outside the CPU execution loop."""
import ctypes as C
from pathlib import Path
import re

REGISTERS = ([f"a{i}" for i in range(32)] + [f"b{i}" for i in range(32)]
             + ["csr", "ier", "ifr", "isr", "icr", "irp", "nrp", "istp", "tsr", "amr",
                "tscl", "tsch", "ilc", "rilc", "fadcr", "fmcr", "faucr", "itsr", "ntsr",
                "efr", "ecr", "dier", "rep", "gfpgfr", "ssr", "pce1", "dnum", "gplya", "gplyb", "ierr"])
REGISTER = {name: i for i, name in enumerate(REGISTERS)}
UNITS = {unit: 1 << i for i, unit in enumerate(("L1", "S1", "M1", "D1", "L2", "S2", "M2", "D2"))}
header = (Path(__file__).resolve().parent / "core/core.h").read_text()
body = re.search(r"enum c6_opcode\s*\{([^}]+)\}", header).group(1)
OPCODES = {name.removeprefix("C6_").lower(): i for i, name in enumerate(re.findall(r"\bC6_\w+\b", body))}


class Operand(C.Structure):
    _fields_ = [("kind", C.c_uint32), ("reg", C.c_int32), ("value", C.c_int64),
                ("aux", C.c_int32), ("flags", C.c_uint32)]


class Instruction(C.Structure):
    _fields_ = [("address", C.c_uint32), ("opcode", C.c_uint32), ("predicate", C.c_int32),
                ("invert", C.c_uint32), ("count", C.c_uint32), ("reserved", C.c_uint32),
                ("operands", Operand * 4)]


class State(C.Structure):
    _fields_ = [("cycles", C.c_uint64), ("packets", C.c_uint64), ("pc", C.c_uint32),
                ("status", C.c_uint32), ("idle_cycles", C.c_uint32), ("pending_writes", C.c_uint32),
                ("pending_branches", C.c_uint32), ("fault_address", C.c_uint32),
                ("registers", C.c_uint32 * 96)]


def operand(text, branch=False):
    text = text.strip()
    if text in REGISTER:
        return Operand(1, REGISTER[text], 0, -1, 0)
    if ":" in text:
        high, low = text.split(":")
        if high not in REGISTER or low not in REGISTER:
            raise ValueError("invalid register pair")
        return Operand(3, REGISTER[high], 0, REGISTER[low], 0)
    if text.startswith("*"):
        match = re.fullmatch(r"\*(\+\+|--|\+|-)?([ab]\d+)(\+\+|--)?(?:\((-?\w+)\)|\[(-?\w+)\])?", text)
        if not match:
            raise ValueError(f"unsupported address mode {text}")
        pre, base, post, byte_offset, element_offset = match.groups()
        if pre and post:
            raise ValueError("both pre and post address updates")
        flags = (2 if pre in ("++", "--") else 0) | (4 if post else 0)
        if pre in ("-", "--") or post == "--":
            flags |= 8
        displacement = byte_offset if byte_offset is not None else element_offset
        if displacement is None:
            displacement = "1" if flags & 6 else "0"
            if flags & 6:
                flags |= 1
        elif element_offset is not None:
            flags |= 1
        offset_reg = REGISTER.get(displacement, -1)
        value = int(displacement, 0) if offset_reg < 0 else 0
        return Operand(2, REGISTER[base], value, offset_reg, flags)
    token = text.split()[0]
    value = int(token, 16) if branch else int(token, 0)
    return Operand(0, -1, value, -1, 0)


def instruction(address, text):
    result = Instruction(address=address, predicate=-1)
    text = text.replace("||", "").strip()
    pred = re.match(r"\[(!?)([ab]\d+)\]\s*(.*)", text)
    if pred:
        result.predicate = REGISTER[pred[2]]
        result.invert = bool(pred[1])
        text = pred[3]
    match = re.fullmatch(r"(\w+)(?:\s+\.(\w+))?(?:\s+(.*))?", text)
    if not match or match[1] not in OPCODES:
        return result
    op, rest = match[1], match[3] or ""
    result.reserved = UNITS.get((match[2] or "")[:2], 0)
    args = [part.strip() for part in re.split(r",(?![^()]*\))", rest)] if rest else []
    if op in ("spmask", "spmaskr"):
        if any(arg not in UNITS for arg in args):
            return result
        result.opcode, result.count = OPCODES[op], 1
        result.operands[0] = Operand(0, -1, sum(UNITS[arg] for arg in set(args)), -1, 0)
        return result
    if len(args) > 4:
        return result
    try:
        for i, arg in enumerate(args):
            result.operands[i] = operand(arg, branch=i == 0 and op in ("b", "bnop", "bdec", "bpos", "callp", "addkpc"))
    except (KeyError, ValueError):
        return result
    result.opcode, result.count = OPCODES[op], len(args)
    return result
