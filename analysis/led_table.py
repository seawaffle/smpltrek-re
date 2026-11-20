#!/usr/bin/env python3
"""Every panel LED address (a 0-2, b 0-5, c 0-7: 144) of the SmplTrek, with what it lights and how that is known.

Static part, simulated in SmplTrek 3.2.174 through panel_map.py (c6sim, read-only): the addresses pad_rgb_set reaches
for pads 0-14 (v1, v2, v3), the STEP setters (step_led_set_rg) and the three clear-all group functions, which together
are every address the stock app drives. Names and colours come from the device evidence already recorded:
- HW-47: pad channel -> printed pad label;
- HW-48: v1/v2/v3 = red/green/blue; two-channel LEDs green at even c, red at c + 1; the row-0 names on planes 0 and 1;
  addresses seen dark; six STEP anchors and four pad anchors;
- 04-hardware-access.md "Button LEDs": the ten button LEDs, green channel checked by a button sweep on the unit (2026-11-14).

Each row is graded:
  device         this exact address was seen to light that LED (or stay dark)
  device-group   the same LED's other channel, or the same table entry pattern, was seen on the device
  static         only the simulation says so
  unused         the stock app never drives the address (seen dark, or untested)

Usage (from the repository root; needs firmware/ and the work listings, as panel_map.py):
  python3 -B analysis/led_table.py               # markdown table on stdout
  python3 -B analysis/led_table.py --check-list  # only the addresses a device session still needs to check
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

PAD_LABEL = {0: "TRK 8", 1: "TRK 1", 2: "TRK 9", 3: "TRK 2", 4: "TRK 10", 5: "TRK 3", 6: "GLOBAL 1", 7: "TRK 4",
             8: "GLOBAL 2", 9: "TRK 5", 10: "GLOBAL 3", 11: "TRK 6", 12: "USB AUDIO", 13: "TRK 7", 14: "EXT SRC"}  # HW-47
PAD_COLOURS = ("red", "green", "blue")                                       # v1, v2, v3 (HW-48)
ROW0 = {0: "VOL L", 1: "VOL R", 2: "microphone", 3: "VALUE encoder blue", 4: "VALUE encoder green",
        5: "VALUE encoder red"}                                              # HW-48, planes 0 and 1
BUTTONS = {(0, 5, 2): "HOME", (0, 5, 4): "MIXER", (1, 5, 0): "REC", (1, 5, 2): "PROJECT", (1, 5, 4): "EDIT",
           (0, 5, 0): "FUNC", (0, 5, 6): "STOP", (1, 5, 6): "PLAY", (0, 4, 6): "CLR", (1, 4, 6): "OK"}  # green; red at c+1
# Exact addresses seen on the unit (HW-48 and the button sweep): address -> what lit ("dark" = nothing)
DEVICE = {(0, 1, 0): "TRK 4 blue", (0, 1, 1): "TRK 2 green", (0, 1, 2): "TRK 2 red", (0, 1, 3): "TRK 2 blue",
          (0, 1, 4): "TRK 9 green", (0, 1, 5): "TRK 9 red", (0, 1, 6): "TRK 9 blue", (0, 2, 0): "USB AUDIO green",
          (0, 1, 7): "dark", (0, 0, 6): "dark", (0, 0, 7): "dark", (1, 0, 6): "dark", (1, 0, 7): "dark",
          (0, 3, 0): "STEP 10 green", (0, 3, 1): "STEP 10 red", (0, 3, 2): "STEP 3 green", (0, 3, 3): "STEP 3 red",
          (0, 3, 4): "STEP 4 green", (0, 3, 6): "STEP 5 green", (0, 4, 0): "STEP 6 green", (0, 4, 2): "STEP 15 green"}
for c, name in ROW0.items():
    DEVICE[(0, 0, c)] = DEVICE[(1, 0, c)] = name
for (a, b, c), name in BUTTONS.items():
    DEVICE[(a, b, c)] = f"{name} green"


def build(session):
    """{(a, b, c): (what, grade, source)} for all 144 addresses."""
    table = {}
    for pad, addresses in session.pads():
        for colour, abc in zip(PAD_COLOURS, addresses):
            table[abc] = (f"{PAD_LABEL[pad]} {colour}", "pad_rgb_set pad %d v%d" % (pad, PAD_COLOURS.index(colour) + 1))
    for step, green, red in session.steps():
        table[green] = (f"STEP {step} green", f"step setter {step} green")
        table[red] = (f"STEP {step} red", f"step setter {step} red")
    for (a, b, c), name in BUTTONS.items():
        table[(a, b, c)] = (f"{name} green", "button setter, green")
        table[(a, b, c + 1)] = (f"{name} red", "button setter, red")
    driven = {abc for group in session.groups().values() for abc in group}
    for c, name in ROW0.items():
        for a in range(3):
            table[(a, 0, c)] = (name, "row-0 helper (all planes)")
    rows = {}
    for a in range(3):
        for b in range(6):
            for c in range(8):
                abc = (a, b, c)
                what, source = table.get(abc, (None, None))
                if abc in DEVICE:
                    seen = DEVICE[abc]
                    if what is None and seen == "dark":
                        rows[abc] = ("nothing", "unused", "device: dark")
                    elif what is not None and seen == what:
                        rows[abc] = (what, "device", source)
                    else:
                        rows[abc] = (what or "?", "CONFLICT", f"device saw {seen!r}; {source}")
                elif what is None:
                    rows[abc] = ("nothing", "unused", "never driven" + (" (but in a clear-all group)" if abc in driven else ""))
                else:
                    led = what.rsplit(" ", 1)[0]
                    sibling = any(v.startswith(led + " ") or v == led for v in DEVICE.values())
                    rows[abc] = (what, "device-group" if sibling else "static", source)
    return rows, driven


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check-list", action="store_true", help="only rows still to check on the device")
    args = ap.parse_args()
    import panel_map
    rows, driven = build(panel_map.Session("smpltrek"))
    counts = {}
    for _, grade, _ in rows.values():
        counts[grade] = counts.get(grade, 0) + 1
    if args.check_list:
        for abc, (what, grade, _) in sorted(rows.items()):
            if grade not in ("device", "unused") or (grade == "unused" and abc not in DEVICE):
                print(f"{abc[0]} {abc[1]} {abc[2]}  sweep {48 * abc[0] + 8 * abc[1] + abc[2]:3d}  expect {what}  ({grade})")
        return
    print("| a,b,c | sweep | lights | grade | from |")
    print("|---|---|---|---|---|")
    for abc, (what, grade, source) in sorted(rows.items()):
        print(f"| {abc[0]},{abc[1]},{abc[2]} | {48 * abc[0] + 8 * abc[1] + abc[2]} | {what} | {grade} | {source} |")
    print()
    print("Totals: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) +
          f"; clear-all groups drive {len(driven)} addresses")


if __name__ == "__main__":
    main()
