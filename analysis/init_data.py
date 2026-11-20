#!/usr/bin/env python3
"""Read a Sonicware image's data as it is after __TI_auto_init, and list its static SYS/BIOS tasks.

Much of what matters at run time (object vptrs, SYS/BIOS instance handles, the static Task objects) is
not in the image's loaded sections: the copy table fills it before main. memory_map.build_map decodes the
copy table; this tool reads words through it (falling back to the loaded sections).

Static tasks (--tasks): SYS/BIOS Task objects are found as 92-byte records whose queue element links to
itself, whose stack size (+28) is non-zero and below 1 MiB, and whose fxn (+40) is in the code section.
Fields (read against SYS/BIOS Task_Object, probable): +8 priority, +20 mode (4 = inactive), +28 stack
size, +32 stack, +40 fxn. With --b14 the B14-relative globals that hold each task's handle are listed
(B14 per product: docs/01-platform-map.md "Image layout"). See 01-platform-map.md "Tasks" for what the app
does with them (task_handler_bind / task_handler_set).

Usage (from the repository root):
  python3 -B analysis/init_data.py "firmware/smpltrek/SmplTrek v3.2.174.zip" 0xC16DB68C:2 0xC16ECF18
  python3 -B analysis/init_data.py "firmware/smpltrek/SmplTrek v3.2.174.zip" --tasks --b14 0xC16F3320
"""
import argparse
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import memory_map

TASK_SIZE = 92
HANDLE_WINDOW = 4096  # bytes of B14-relative data searched for task handles


class InitData:
    def __init__(self, path):
        self.program, *_, regions = memory_map.build_map(path)
        self.regions = [r for r in regions if r.get("data") is not None]
        self.image = memory_map.Image(self.program.sections)

    def word(self, address):
        for r in self.regions:
            if r["start"] <= address <= r["end"] - 4:
                return struct.unpack_from("<I", r["data"], address - r["start"])[0]
        return self.image.word(address)

    def tasks(self):
        """[(address, fields)] of static Task objects; fields = the first 23 words."""
        lo, hi = self.program.image.code
        found = []
        for r in self.regions:
            d = r["data"]
            for o in range(0, len(d) - TASK_SIZE + 1, 4):
                a = r["start"] + o
                w = struct.unpack_from("<23I", d, o)
                if w[0] == a and w[1] == a and lo <= w[10] < hi and 0 < w[7] < 0x100000:
                    found.append((a, w))
        return found

    def handles(self, b14, targets):
        """{target: [B14 offsets whose word equals target]}."""
        out = {t: [] for t in targets}
        for off in range(0, HANDLE_WINDOW, 4):
            v = self.word(b14 + off)
            if v in out:
                out[v].append(off)
        return out


def signed(v):
    return v - (1 << 32) if v & 0x80000000 else v


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("image", help="official update .zip/.bin")
    parser.add_argument("words", nargs="*", metavar="ADDR[:N]", help="print N (default 8) words at ADDR")
    parser.add_argument("--tasks", action="store_true", help="list the static SYS/BIOS Task objects")
    parser.add_argument("--b14", help="data page pointer, to list each task's handle global")
    args = parser.parse_args()
    data = InitData(args.image)
    for spec in args.words:
        address, _, n = spec.partition(":")
        address = int(address, 16)
        values = [data.word(address + 4 * i) for i in range(int(n or 8))]
        print(f"{address:#010x}: " + " ".join("--------" if v is None else f"{v:08x}" for v in values))
    if args.tasks:
        tasks = data.tasks()
        handles = data.handles(int(args.b14, 16), [a for a, _ in tasks]) if args.b14 else {}
        print(f"{len(tasks)} static tasks")
        for a, w in tasks:
            where = ", ".join(f"B14+{o}" for o in handles.get(a, [])) or "-"
            print(f"  {a:#010x} priority {signed(w[2]):3d} mode {w[5]} stack {w[7]:#7x} at {w[8]:#010x} "
                  f"fxn {w[10]:#010x} handle {where}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
