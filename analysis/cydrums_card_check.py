#!/usr/bin/env python3
"""Does CyDrums (1.1.84 or 2.0.97 beta) write to a card that has no /CyDrums folder? (simulated, read-only)

Builds CyDrums' start-up state with analysis/sim_boot.py (copy table, SYS/BIOS module start-up, then all
181 `.init_array` constructors; hardware polls stubbed, heap replaced). It then runs the three code paths a foreign card reaches, with the FatFs API and the disk layer
replaced by hooks that log every call:
  1. the start-up card block of MainDelegate's start-up routine (entered at 0xC24CDFA4, the
     sd_card_inserted call, with A12 = MainDelegate and a fresh stack frame);
  2. the card-insertion lambda (handleCardStateEvent, 0xC25D0140) with event 1 (inserted);
  3. AppNoSystemCore's enter (vtable slot 0, 0xC25D6E54) and update (slot 1, 0xC25D6EA8) methods: the
     "BLANK MEDIA!" page these paths select when SystemCore.bin is missing.
The hooked card: present, mounts, every lookup fails (no file / no path), and every write-side call (f_mkdir,
f_open with a write or create flag, f_write, f_rename, f_mkfs, f_sync, file_unlink, disk_write) is logged
and refused. sim_boot replaces Memory_alloc / Memory_free by a bump allocator (the simulated SYS/BIOS heap
returned NULL, which would hide write paths that allocate first).

Not modelled, and replaced by "return 0" stubs (listed in sim_boot.PRODUCTS["cydrums"]): hardware polls (PSC1
module enable, the codec's I2C busy flags, the USB0 reset and PHY clock), the flash requests behind
settings_load / flash_headers_request and task_sleep. The nested-SPLOOPD table initialiser 0xC253FA24 was
also stubbed until 2026-11-12; it is not reached on these paths (identical output with and without the stub),
and c6sim now models it (claim TOOL-3). Other SYS/BIOS tasks
are not run (the ResourceLoader is only started when SystemCore.bin exists), and USB card-reader mode (the
PC writing the card) is out of scope. Run time: a few minutes (about 4.3 million simulated cycles).

2.0.97 beta: the same paths and hooks at the 2.0 addresses (VERSIONS below; boot state from
sim_boot.PRODUCTS["cydrums-2.0.97"]). The version is chosen by the image's entry point. --system-core runs the
paths on a card where f_stat finds /CyDrums/System/SystemCore.bin and every other lookup still fails: a real
CyDrums card whose other files are missing or unreadable (for example a 1.x folder with no Contents/Samples).

Usage (from the repository root):
  python3 -B analysis/cydrums_card_check.py firmware/cydrums/CyDrums_v1.1.84.zip
  python3 -B analysis/cydrums_card_check.py firmware/cydrums/CyDrums_v2.0.97beta.zip [--system-core]
"""
import argparse
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import c6sim
import sim_boot

SYSTEM_CORE = "/CyDrums/System/SystemCore.bin"
STACK_FRAME = 0x30FFFF00
EVENT = 0x30000100
LAMBDA_THIS = 0x30000200
FR_OK, FR_NO_FILE, FR_NO_PATH, FR_DENIED = 0, 4, 5, 7
WRITE_FLAGS = 0x3E   # FA_WRITE | FA_CREATE_NEW | FA_CREATE_ALWAYS | FA_OPEN_ALWAYS | FA_OPEN_APPEND

def cstr(m, address):
    if not address:
        return None
    out = bytearray()
    while len(out) < 256:
        b = m.mem.byte(address + len(out))
        if b == 0:
            break
        out.append(b)
    return out.decode("latin1")


# Per version: the instances and the hooked functions. 1.1.84 as read in 2026-11-12; 2.0.97 (beta) translated
# with the 1.1.84 -> 2.0.97 function match of analysis/func_match.py (similarity 1.0 unless noted), the
# instances from the code that builds them. Both versions have one call site of each write-side FatFs function,
# the same file wrappers (0xC2565A04-0xC2565BE8 / 0xC25E2D84-0xC25E2F68), and disk_write as the only caller of
# the SD block write, so the same hook set covers 2.0.
VERSIONS = {
    "1.1.84": dict(
        product="cydrums", entry=0xC25F8CA0,
        # no_system_core: mvk -24 / mvkh 0xC2420000 at 0xC24CE6D0 / 0xC24CE6DC and 0xC25D6E28 / 0xC25D6E2C build
        # 0xC242FFE8, where the boot scan finds AppNoSystemCore's vtable 0xC269BB60 (corrected 2026-11-18: was
        # 0xC241FFE8, which holds 0; the paths' output is the same with either).
        main_delegate=0xC242DDF0, no_system_core=0xC242FFE8,
        startup_card_block=0xC24CDFA4, card_lambda=0xC25D0140, nsc_enter=0xC25D6E54, nsc_update=0xC25D6EA8,
        f_mount=0xC24376D0, f_stat=0xC2435D4C, f_open=0xC2437124, f_opendir=0xC2436EC0, f_findfirst=0xC24395EC,
        f_findnext=0xC2439568, f_readdir=0xC2436788, f_closedir=0xC2439640, f_read=0xC2436858,
        f_lseek=0xC2438AF0, f_getfree=0xC243908C, file_close=0xC2565AE0, f_mkdir=0xC243882C, f_write=0xC24326CC,
        f_rename=0xC2436488, f_mkfs=0xC2437AEC, f_sync=0xC24355C8, file_unlink=0xC2565A04,
        disk_write=0xC25DE420, disk_read=0xC25DE478, sd_card_inserted=0xC25C226C,
        sd_card_reader_active=0xC25C23C0, sd_card_ready=0xC25920A8, disk_initialize=0xC25DE538,
        disk_status=0xC25DE458),
    "2.0.97": dict(
        product="cydrums-2.0.97", entry=0xC267D960,
        # MainDelegate: 0xC2664BA0 builds 0xC222288C as a4 for 0xC26851A8 (1.1.84 0xC25FFFE8, which 0xC25E3900
        # calls with MainDelegate 0xC242DDF0); after boot it holds MainDelegate's vtable 0xC27124C0 (RTTI).
        # AppNoSystemCore: its constructor 0xC2659F20 stores vtable 0xC2725868 (RTTI) at 0xC249B2DC (mvk -19748
        # sign-extends, then mvkh 0xC2490000); the message switch loads the same address at 0xC253FBF0 (1.1.84:
        # 0xC24CE6D0). After sim_boot both instances hold their vtables, and no other word does.
        main_delegate=0xC222288C, no_system_core=0xC249B2DC,
        # MainDelegate's start-up routine is 0xC253F320 (1.1.84 0xC24CDE14, same prologue and 64-byte frame). Its
        # card block now starts with two new calls before sd_card_inserted: 0xC267E5C8 and 0xC2611284 (sample
        # slots: 32 x 0xC2646C2C). The entry is the addkpc before them, as at 1.1.84's 0xC24CDFA4.
        startup_card_block=0xC253F4B0,
        card_lambda=0xC264D300,            # match (vtable, 0.95); handleCardStateEvent lambda vtable slot 6 (RTTI)
        nsc_enter=0xC2659F54, nsc_update=0xC2659FA8,     # AppNoSystemCore vtable slots 0 and 1 (RTTI)
        f_mount=0xC24A2AD0, f_stat=0xC24A114C, f_open=0xC24A2524, f_opendir=0xC24A22C0, f_findfirst=0xC24A49EC,
        f_findnext=0xC24A4968, f_readdir=0xC24A1B88, f_closedir=0xC24A4A40, f_read=0xC24A1C58,
        f_lseek=0xC24A3EF0, f_getfree=0xC24A448C, file_close=0xC25E2E60, f_mkdir=0xC24A3C2C, f_write=0xC249DACC,
        f_rename=0xC24A1888, f_mkfs=0xC24A2EEC, f_sync=0xC24A09C8, file_unlink=0xC25E2D84,
        disk_write=0xC26618A0, disk_read=0xC26618F8, sd_card_inserted=0xC2644A2C,
        sd_card_reader_active=0xC2644B80, sd_card_ready=0xC2612328, disk_initialize=0xC26619B8,
        disk_status=0xC26618D8),
}


def card_hooks(log, version="1.1.84", stat_found=()):
    """stat_found: paths for which f_stat returns FR_OK (a card that has them); every other lookup fails."""
    v = VERSIONS[version]

    def call(name, result, path_reg=None, mode_reg=None, write=False, refuse_writes=False, found=()):
        def hook(m):
            mode = m.R.get(mode_reg, 0) if mode_reg else None
            is_write = write or bool(mode is not None and mode & WRITE_FLAGS)
            path = cstr(m, m.R.get(path_reg, 0)) if path_reg else None
            log.append((name, path, None if mode is None else mode, is_write))
            m.R["a4"] = FR_DENIED if (is_write and refuse_writes) else FR_OK if path in found else result
            return m.R["b3"]
        return hook
    hooks = {
        v["f_mount"]: call("f_mount", FR_OK, "b4"),
        v["f_stat"]: call("f_stat", FR_NO_FILE, "a4", found=stat_found),
        v["f_open"]: call("f_open", FR_NO_FILE, "b4", "a6", refuse_writes=True),
        v["f_opendir"]: call("f_opendir", FR_NO_PATH, "b4"),
        v["f_findfirst"]: call("f_findfirst", FR_NO_PATH, "b4"),
        v["f_findnext"]: call("f_findnext", FR_NO_FILE),
        v["f_readdir"]: call("f_readdir", FR_DENIED),
        v["f_closedir"]: call("f_closedir", FR_OK),
        v["f_read"]: call("f_read", FR_DENIED),
        v["f_lseek"]: call("f_lseek", FR_DENIED),
        v["f_getfree"]: call("f_getfree", FR_OK, "a4"),
        v["file_close"]: call("file_close", FR_OK),
        v["f_mkdir"]: call("f_mkdir", FR_DENIED, "a4", write=True),
        v["f_write"]: call("f_write", FR_DENIED, write=True),
        v["f_rename"]: call("f_rename", FR_DENIED, "a4", write=True),
        v["f_mkfs"]: call("f_mkfs", FR_DENIED, "a4", write=True),
        v["f_sync"]: call("f_sync", FR_DENIED, write=True),
        v["file_unlink"]: call("file_unlink", FR_DENIED, "a4", write=True),
        v["disk_write"]: call("disk_write", 1, write=True),
        v["disk_read"]: call("disk_read", 1),
        v["sd_card_inserted"]: c6sim.returns(1),
        v["sd_card_reader_active"]: c6sim.returns(0),
        v["sd_card_ready"]: c6sim.returns(1),
        v["disk_initialize"]: c6sim.returns(0),
        v["disk_status"]: c6sim.returns(0),
    }
    return hooks


def run_path(boot, start, regs, memory=(), extra_memory=None, version="1.1.84", stat_found=(), keep_going=False):
    """keep_going: a path that stops (no return, a jump outside the image) keeps its log; m.stopped says why."""
    log = []
    m = boot.machine(regs, hooks=card_hooks(log, version, stat_found))
    m.stopped = None
    if extra_memory:
        m.mem.overlay.update(extra_memory)
    for address, value in memory:
        m.mem.write(address, struct.pack("<I", value))
    try:
        m.run(start, max_cycles=1500000)
    except (c6sim.SimError, ValueError) as e:
        if not keep_going:
            raise
        m.stopped = str(e)
    return log, m


def paths(version="1.1.84"):
    v = VERSIONS[version]
    return [
        ("start-up card block", v["startup_card_block"],
         {"a12": v["main_delegate"], "b13": c6sim.RET, "b15": STACK_FRAME}, ()),
        ("card inserted (lambda, event 1)", v["card_lambda"], {"a4": LAMBDA_THIS, "b4": EVENT}, ((EVENT, 1),)),
        ("AppNoSystemCore enter", v["nsc_enter"], {"a4": v["no_system_core"]}, ()),
        ("AppNoSystemCore update", v["nsc_update"], {"a4": v["no_system_core"]}, ()),
    ]


PATHS = paths("1.1.84")


def image_version(image):
    """The VERSIONS key whose entry point is the image's."""
    entry = c6sim.Program(image).entry
    for version, v in VERSIONS.items():
        if v["entry"] == entry:
            return version
    raise SystemExit(f"{image}: entry {entry:#x} is not a known CyDrums version ({', '.join(VERSIONS)})")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("image", help="the official CyDrums 1.1.84 or 2.0.97 beta update (.zip/.bin)")
    ap.add_argument("--version", choices=sorted(VERSIONS), help="default: chosen by the image's entry point")
    ap.add_argument("--system-core", action="store_true",
                    help="f_stat finds /CyDrums/System/SystemCore.bin (a real but old CyDrums card); "
                         "every other lookup still fails")
    args = ap.parse_args()
    version = args.version or image_version(args.image)
    stat_found = (SYSTEM_CORE,) if args.system_core else ()
    boot = sim_boot.Boot(VERSIONS[version]["product"], args.image)
    writes = 0
    for name, start, regs, memory in paths(version):
        log, m = run_path(boot, start, regs, memory, version=version, stat_found=stat_found, keep_going=True)
        print(f"{name}: " + (f"stopped ({m.stopped})" if m.stopped else "returned")
              + f" after {m.cyc} cycles, {len(m.calls)} calls")
        for call, path, mode, is_write in log:
            print(f"    {call}({path if path is not None else ''}" + (f", mode {mode:#x}" if mode is not None else "")
                  + ")" + ("   <-- WRITE" if is_write else ""))
            writes += is_write
    print(f"write-side card calls: {writes}")
    return 1 if writes else 0


if __name__ == "__main__":
    sys.exit(main())
