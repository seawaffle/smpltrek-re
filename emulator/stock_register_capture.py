#!/usr/bin/env python3
"""Capture the stock SmplTrek 3.2.174's peripheral register accesses, phase by phase, in the emulator.

Runs the stock image with the generated drum project (as tests/stock_usb.py) and records, with the MMIO capture
(cpu.capture_start), every access to USB0 (core and wrapper), SYSCFG0 (KICK, PINMUX, CFGCHIP0-4), PSC0/PSC1, I2C0, McASP0's
registers, the EDMA3 channel controller and its PaRAM, and MMCSD0; reads are kept too, a poll folded into one row
with a repeat count. The codec's I2C register writes (cpu.codec_log) and the SD card's commands (cpu.sd_log) are
recorded alongside. Each phase is the stretch of guest time between two marks:

  boot           reset to the idle home screen (6 s, then CLR)
  attach         cable in (VBUS), to the start of the host's bus reset
  bus_reset      the 10 ms reset and the 10 ms recovery
  enumeration    usb_enumerate(): descriptors, SET_ADDRESS, SET_CONFIGURATION (rows tagged with the step)
  bulk_out       the first bulk OUT transfers: a USB MIDI note on and off on endpoint 0x03
  midi_menu      SYSTEM MENU > MIDI > CONFIG: CLOCK OUT on, COMMAND RX/TX (so the stock sends on 0x83)
  bulk_in        PLAY, the first bulk IN transfers on endpoint 0x83, STOP
  interface_on   SET_INTERFACE 1 alt 1, then 2 alt 1 (the audio streams opened; no packets sent)
  interface_off  SET_INTERFACE 1 alt 0, then 2 alt 0
  suspend        start-of-frame off until the device suspends, then on again (resume)
  detach         cable out
  rec_src_N      REC SRC (FUNC + EDIT, encoder A) stepped to source N: down to 0, then up to 12 (the input routes)
  power_off      the power key held 3 s (the power-off handler), then released

`--common PRODUCT` runs instead one product-neutral scenario on SmplTrek 3.2.174, Lofi-12 XT 1.5.205 or CyDrums
1.1.84 (erased flash, a blank 32 MiB card, a MIDI note on channel 1 for bulk OUT; CyDrums gets the card contents it
ships with instead, because with a blank card it switches USB to mass storage at start-up): boot, attach, bus_reset,
enumeration, bulk_out, interface_on, interface_off, suspend, detach and power_off, written to
common-<product>.json, so the three products' drivers can be compared on equal terms (stock_register_diff.py).

A second run, from reset again, covers card-reader mode, which the emulator can only start:

  boot           as above
  attach, bus_reset, enumeration   as above (the manual connects the computer first)
  card_reader    SYSTEM MENU > CARD > CARD READER, "SAVE CURRENT PRJ?" > NO: the stock unmounts the card and
                 switches USB to mass storage. Its CPPI DMA set-up stops the emulator at the first queue-manager
                 access (USB0 + 0x3200, not modelled), so this phase ends in that fault and the remount after
                 leaving the mode is not reached (read statically instead).

Output: work/register-capture/raw.json (a list of the two runs) (the rows contain no Sonicware code, only register values; work/ stays
untracked as usual). stock_register_tables.py turns it into the per-peripheral tables.

Requires explicit --conditional (the logged reserved low-store assumption), as tests/stock_usb.py.
"""
import argparse
import json
from pathlib import Path
import struct
import sys
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from build import WORK
from media import build_card
from project_card import MS, project_card
from stock import Stock

SELECT_RIGHT, FUNC, PLAY, OK, DOWN, HOME, EDIT, STOP, CLR = 9, 19, 22, 23, 25, 27, 28, 29, 30
SETTINGS = 0xc14fac58                          # g_settings; +0x10 REC SRC, +0x8c track MIDI channels
CARD_READER_ACTIVE = 0xC16F3320 + 444          # B14 + 444, usb_msc_mode_set's flag (sd_card_reader_active)
RANGES = [(0x01E00000, 0x01E10000),            # USB0: core, wrapper, CPPI
          (0x01C14000, 0x01C14200),            # SYSCFG0: KICK0/1, PINMUX0-19, CFGCHIP0-4
          (0x01C10000, 0x01C11000),            # PSC0
          (0x01E27000, 0x01E28000),            # PSC1
          (0x01C22000, 0x01C22060),            # I2C0
          (0x01D00000, 0x01D00300),            # McASP0 registers (not the DMA data port)
          (0x01C00000, 0x01C08000),            # EDMA3 CC0 registers and PaRAM
          (0x01C40000, 0x01C40078)]            # MMCSD0


FIRMWARE = {"smpltrek": ROOT / "firmware/smpltrek/SmplTrek v3.2.174.zip",
            "lofi12": ROOT / "firmware/lofi12/Lofi-12XT_v1.5.205.zip",
            "cydrums": ROOT / "firmware/cydrums/CyDrums_v1.1.84.zip"}


def capture(output, scenario, product="smpltrek", genre="FUNK", seed=1):
    if scenario == "common" and product == "cydrums":
        # With a blank card CyDrums 1.1.84 switches USB to mass storage at start-up (CPPI DMA, which the emulator
        # stops at), so it gets the card contents it ships with (CyDrums_folder.zip, extracted under work/ only).
        folder = output / "cydrums-card"
        with zipfile.ZipFile(ROOT / "firmware/cydrums/CyDrums_folder.zip") as archive:
            archive.extractall(folder)
        files = {"/" + str(path.relative_to(folder)): path for path in sorted(folder.rglob("*")) if path.is_file()}
        card = build_card(output / "card-cydrums.img", files, size_mb=128, long_names=True)
        flash, description = None, dict(card="128 MiB card with CyDrums_folder.zip's contents", flash="erased")
    elif scenario == "common":
        # The same for every product: erased flash, a blank card, no product-specific menus.
        card, flash = build_card(output / f"blank-{product}.img", size_mb=32), None
        description = dict(card="blank 32 MiB FAT card", flash="erased")
    else:
        card, flash, description = project_card(output / "card.img", genre, seed)
    result = dict(scenario=scenario, product=product, firmware=FIRMWARE[product].name, project=description,
                  phases=[], fault=None)
    with Stock(FIRMWARE[product], card=card, flash_image=flash, reserved_low_writes=True, profile=product,
               reserved_low_reads=product != "smpltrek") as stock:
        cpu = stock.cpu
        codec_since = sd_since = 0
        cpu.capture_start(RANGES)

        pending = []   # rows taken during the phase, so the capture never fills up

        def advance(milliseconds):
            for part in [100] * (milliseconds // 100) + [milliseconds % 100] * bool(milliseconds % 100):
                report = stock.run(part * MS, 1000000)
                if report["error"]:
                    raise RuntimeError(report["error"])
                pending.extend(cpu.capture_take())

        def press(*keys):
            for key in keys:
                stock.key_input(key, True); advance(70)
            for key in reversed(keys):
                stock.key_input(key, False); advance(70)
            advance(450)

        def turn(encoder, detents):
            for _ in range(abs(detents)):
                for phase in ((2, 0, 1, 3) if detents > 0 else (1, 0, 2, 3)):
                    stock.encoder_phase(encoder, phase); advance(10)
            advance(300)

        def until_port(state, limit_ms=500):
            for _ in range(limit_ms):
                if cpu.usb_state()["port"] == state:
                    return
                advance(1)
            raise RuntimeError(f"the USB port never reached {state}")

        current = ["boot"]

        psc_since = 0

        def mark(name, **extra):
            nonlocal codec_since, sd_since, psc_since
            mmio = pending + cpu.capture_take()
            pending.clear()
            codec, codec_since = cpu.codec_log(codec_since)
            sd, sd_since = cpu.sd_log(sd_since)
            psc, psc_since = cpu.psc_violations(psc_since)
            result["phases"].append(dict(name=name, end=cpu.cycles(), mmio=mmio, codec=codec, sd=sd, psc_violations=psc,
                                         **extra))
            current[0] = None

        def source():
            return struct.unpack("<I", cpu.read(SETTINGS + 0x10, 4))[0]

        try:
            advance(6000); press(CLR)
            mark("boot")
            current[0] = "attach"
            cpu.usb_attach(); until_port("reset")
            mark("attach")
            current[0] = "bus_reset"
            until_port("enabled", 100)
            mark("bus_reset")
            current[0] = "enumeration"
            found = cpu.usb_enumerate()
            advance(10)
            mark("enumeration", steps=[dict(step=s["step"], status=s["status"], submitted=s["submitted"],
                                            completed=s["completed"]) for s in found["steps"]])
            if scenario == "card_reader":
                current[0] = "card_reader"
                press(FUNC, HOME)
                for _ in range(6): press(DOWN)
                press(OK); press(OK)                 # CARD, then CARD READER (the first entry)
                press(DOWN); press(OK)               # "SAVE CURRENT PRJ?" > NO
                advance(3000)
                mark("card_reader", active=struct.unpack("<I", cpu.read(CARD_READER_ACTIVE, 4))[0])
                return result
            channel = 0 if scenario == "common" else struct.unpack("<I", cpu.read(SETTINGS + 0x8c, 4))[0]
            sent = [cpu.usb_out(0x03, bytes([0x09, 0x90 | channel, 36, 110]))["status"]]
            advance(300)
            sent.append(cpu.usb_out(0x03, bytes([0x08, 0x80 | channel, 36, 0]))["status"])
            advance(50)
            mark("bulk_out", transfers=sent)
            if scenario == "common":
                replies = [cpu.usb_set_interface(1, 1)["status"], cpu.usb_set_interface(2, 1)["status"]]
                advance(20)
                mark("interface_on", replies=replies)
                replies = [cpu.usb_set_interface(1, 0)["status"], cpu.usb_set_interface(2, 0)["status"]]
                advance(20)
                mark("interface_off", replies=replies)
                cpu.usb_sof(False); advance(10)
                suspended = cpu.usb_state()["suspended"]
                cpu.usb_sof(True); advance(10)
                mark("suspend", suspended=suspended, resumed=not cpu.usb_state()["suspended"])
                cpu.usb_detach(); advance(50)
                mark("detach")
                cpu.gpio_input(3, 0, False); advance(3000)
                cpu.gpio_input(3, 0, True); advance(1000)
                mark("power_off")
                return result
            press(FUNC, HOME)
            for _ in range(4): press(DOWN)
            press(OK); press(DOWN); press(DOWN); press(OK)
            press(SELECT_RIGHT)
            turn(0, 1); turn(2, 3)
            press(HOME)
            mark("midi_menu")
            stock.key_input(PLAY, True)
            packets = []
            for _ in range(3):
                packet = cpu.usb_in(0x83, 64, timeout_ms=200)
                packets.append([packet["status"], packet["data"].hex()])
            stock.key_input(PLAY, False)
            press(STOP)
            mark("bulk_in", packets=packets)
            replies = [cpu.usb_set_interface(1, 1)["status"], cpu.usb_set_interface(2, 1)["status"]]
            advance(20)
            mark("interface_on", replies=replies)
            replies = [cpu.usb_set_interface(1, 0)["status"], cpu.usb_set_interface(2, 0)["status"]]
            advance(20)
            mark("interface_off", replies=replies)
            cpu.usb_sof(False); advance(10)
            suspended = cpu.usb_state()["suspended"]
            cpu.usb_sof(True); advance(10)
            mark("suspend", suspended=suspended, resumed=not cpu.usb_state()["suspended"])
            cpu.usb_detach(); advance(50)
            mark("detach")
            press(FUNC, EDIT)                        # REC SRC
            for _ in range(12):
                if not source():
                    break
                turn(0, -1); mark(f"rec_src_{source()}")
            while source() < 12:
                turn(0, 1); mark(f"rec_src_{source()}")
            press(HOME)
            mark("rec_src_closed")
            cpu.gpio_input(3, 0, False); advance(3000)   # the power key (GP3[0], low = pressed)
            cpu.gpio_input(3, 0, True); advance(1000)
            mark("power_off")
        except Exception as error:   # keep what was captured; the fault is reported with the phase it ended
            result["fault"] = f"{type(error).__name__}: {error}"
            try:
                mark(current[0] or "after_" + result["phases"][-1]["name"], fault=result["fault"])
            except Exception:
                pass
        result["cycles"] = cpu.cycles()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--conditional", action="store_true", help="accept the logged reserved low-store assumption")
    parser.add_argument("--output", type=Path, default=WORK / "register-capture")
    parser.add_argument("--common", choices=tuple(FIRMWARE), help="instead of SmplTrek's full runs, the common "
                        "scenario for one product (common-<product>.json)")
    args = parser.parse_args(argv)
    if not args.conditional:
        parser.error("--conditional is required")
    args.output.mkdir(parents=True, exist_ok=True)
    if args.common:
        runs = [capture(args.output, "common", args.common)]
        (args.output / f"common-{args.common}.json").write_text(json.dumps(runs) + "\n")
    else:
        runs = [capture(args.output, scenario) for scenario in ("main", "card_reader")]
        (args.output / "raw.json").write_text(json.dumps(runs) + "\n")
    for result in runs:
        print(f'== {result["scenario"]}')
        for phase in result["phases"]:
            writes = sum(1 for row in phase["mmio"] if row["write"])
            print(f'{phase["name"]:14} {len(phase["mmio"]):6} MMIO rows ({writes} writes), {len(phase["psc_violations"])} PSC violations, {len(phase["codec"])} codec, '
                  f'{len(phase["sd"])} SD commands', {k: v for k, v in phase.items() if k not in ("name", "end", "mmio", "codec", "sd", "steps", "psc_violations")})
        print("fault:", result["fault"])
    # The card-reader run is expected to end in the emulator's unmodelled CPPI access.
    return 1 if runs[0]["fault"] else 0


if __name__ == "__main__":
    sys.exit(main())
