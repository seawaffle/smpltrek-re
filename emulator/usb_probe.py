"""Trace the stock 3.2.174 USB null store without modifying guest state or accepting reserved accesses."""
import argparse
import json
from pathlib import Path
import struct
import sys
import tempfile

from build import ROOT, WORK, digest
from cpu import CoreFault
from stock import DEFAULT_FIRMWARE, Stock, firmware

IMAGE_SHA256 = "3b6848b0f041bcf23c73d4b0357d2f3d6dc9e7e03752b32ff7322e91e6814e53"
COMPOSITE, AUDIO, STORE = 0xc165be20, 0xc162a4a0, 0xc162a4f0
COMPOSITE_INFO, AUDIO_INFO, AUDIO_INSTANCE = 0xc16ecf8c, 0xc16ecfd4, 0xc150370c


def words(cpu, address, count):
    return list(struct.unpack(f"<{count}I", cpu.read(address, 4 * count)))


def snapshot(cpu, label):
    infos = {}
    for name, address in (("composite", COMPOSITE_INFO), ("audio", AUDIO_INFO)):
        values = words(cpu, address, 18)
        descriptor = values[12]
        infos[name] = dict(address=address, words=values, descriptor=descriptor,
                           descriptor_bytes=cpu.read(descriptor, 18).hex() if descriptor else None,
                           configuration_headers=values[13])
    return dict(label=label, state=cpu.state(), infos=infos,
                audio_instance=dict(address=AUDIO_INSTANCE, words=words(cpu, AUDIO_INSTANCE, 16)),
                exception_masks=[words(cpu, 0x018000c0 + i * 4, 1)[0] for i in range(4)])


def probe(work=WORK, image=DEFAULT_FIRMWARE):
    metadata, _ = firmware(image)
    if metadata["sha256"] != IMAGE_SHA256:
        raise ValueError("USB runtime probe addresses require the original SmplTrek 3.2.174 image")
    with Stock(image=image, work=work) as stock:
        for pc, name in ((COMPOSITE, "usb_composite_entry"), (AUDIO, "usb_audio_entry")):
            stock.expected[pc] = name
            stock.cpu.breakpoint(pc)
        snapshots = []
        for label, checkpoint, budget in (("runtime_initialized", "auto_init_return_site", 10000000),
                                           ("composite_entry", "usb_composite_entry", 1500000000),
                                           ("audio_entry", "usb_audio_entry", 100000)):
            report = stock.run(budget, until_checkpoint=checkpoint)
            if report["error"] or report["stop_reason"] != "checkpoint":
                raise RuntimeError(f"did not reach {checkpoint}: {report['error'] or report['stop_reason']}")
            snapshots.append({**snapshot(stock.cpu, label), "execution_window": report["execution_window"],
                              "elapsed_seconds": report["elapsed_seconds"]})
            print(f"{label}: cycle {report['state']['cycles']}, PC {report['state']['pc']:#010x}", flush=True)
        trace, error = [], None
        for _ in range(128):
            before = stock.cpu.state()
            try:
                stock.cpu.run(1)
            except CoreFault as fault:
                error = str(fault)
            after = stock.cpu.state()
            packet = stock.cpu.packet_info(before["pc"])
            trace.append(dict(cycles=before["cycles"], pc=before["pc"], packet=packet,
                              fetch_bytes=stock.cpu.read(before["pc"] & ~31, 32).hex(),
                              assembly=[stock.cpu.decoder.text.get(ins["address"], "") for ins in packet["instructions"]],
                              changes={reg: value for reg, value in after["registers"].items()
                                       if before["registers"][reg] != value},
                              b7_before=before["registers"]["b7"], error=error))
            if error:
                break
        final = snapshot(stock.cpu, "fault")
        result = stock.run(1)
        assertions = dict(
            expected_fault=bool(error) and final["state"]["pc"] == STORE,
            target_address_is_8=final["state"]["registers"]["b7"] + 8 == 8,
            audio_descriptor_always_null=all(s["infos"]["audio"]["descriptor"] == 0 for s in [*snapshots, final]),
            audio_config_always_null=all(s["audio_instance"]["words"][2] == 0 for s in [*snapshots, final]),
            composite_vid_pid_written=stock.cpu.read(snapshots[-1]["infos"]["composite"]["descriptor"] + 8, 4)
                                      == struct.pack("<HH", 0x2fd7, 4),
            no_usb_controller_access=not any(0x01e00000 <= a["address"] < 0x01e10000 for a in result["mmio_trace"]),
            no_null_ram=not any(r["address"] == 0 for r in result["memory_regions"]),
            no_guest_hooks=result["guest_function_hooks"] == [])
        result["usb_investigation"] = dict(snapshots=[*snapshots, final], trace=trace, assertions=assertions,
                                           hardware_reserved_write_response_verified=False,
                                           limitations=["registers and RAM are emulator observations, not hardware measurements",
                                                        "only the retained bounded MMIO trace is inspected for USB accesses",
                                                        "null stores remain strict faults; no guest patch or reserved-bus assumption"])
        return result


def compare_release(image):
    """Independent file-format decoder; the analysis implementation remains read-only."""
    sys.path.insert(0, str(ROOT / "analysis"))
    try:
        import init_data
        import string_refs
    finally:
        sys.path.pop(0)
    metadata, _ = firmware(image)
    data = init_data.InitData(image)
    insns = data.program.insns
    constants = {high: value for value, high, _ in string_refs.constant_pairs(insns)}
    hits = []
    for index, (pc, op, args) in enumerate(insns[:-40]):
        if op != "ldw" or args != ".D2T2 *+b4(40),b5":
            continue
        if insns[index + 1][1] != "mvk" or not insns[index + 1][2].endswith(",a3"):
            continue
        info = constants.get(insns[index + 3][0])
        stores = [a for a, m, operands in insns[index:index + 40]
                  if m == "stb" and operands == ".D2T1 a3,*+b7(8)"]
        if info is not None and stores:
            hits.append(dict(entry=pc, info=info, descriptor=data.word(info + 48),
                             configuration_headers=data.word(info + 52), vendor_stores=stores,
                             words=[data.word(info + 4 * k) for k in range(18)]))
    return dict(input=metadata, matches=hits,
                limitation="matches an explicit instruction pattern and initialized data, not a hardware execution")


def sdk_references():
    ti = Path.home() / "ti"
    paths = [ti / "C6748_StarterWare_1_20_04_01/usblib/include/usblib.h",
             ti / "C6748_StarterWare_1_20_04_01/usblib/device/usbdcomp.c",
             ti / "pdk_omapl138_1_0_11/packages/ti/drv/usb/src/usb_func/device/usbdaudio.c"]
    return [dict(path=str(path), sha256=digest(path.read_bytes())) for path in paths if path.is_file()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--firmware", type=Path, default=DEFAULT_FIRMWARE)
    parser.add_argument("--compare", nargs="*", type=Path, default=[], help="also inspect these stock releases statically")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.work / "usb-investigation/result.json"
    scratch = args.work.resolve() / "usb-investigation/temporary"
    scratch.mkdir(parents=True, exist_ok=True)
    previous = tempfile.tempdir
    tempfile.tempdir = str(scratch)
    try:
        report = probe(args.work, args.firmware)
        report["usb_investigation"]["releases"] = [compare_release(path) for path in args.compare]
        report["usb_investigation"]["sdk_sources"] = sdk_references()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        if not all(report["usb_investigation"]["assertions"].values()):
            raise RuntimeError(f"USB investigation expectations changed; inspect {output}")
        print(f"Confirmed original USB null store; full boot remains incomplete. Report: {output}")
    finally:
        tempfile.tempdir = previous


if __name__ == "__main__":
    main()
