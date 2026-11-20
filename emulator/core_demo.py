"""Build and run synthetic C674x code on the C++ core, including executable RAM replacement."""
import json
from pathlib import Path
import subprocess
import time

from build import HERE, ROOT, WORK, digest
from cpu import CPU

BIN = ROOT / "tools/tic6x/bin"


def tools_present():
    return all((BIN / ("tic6x-elf-" + name)).exists() for name in ("as", "ld", "nm", "objdump"))


def symbols(path):
    output = subprocess.run([str(BIN / "tic6x-elf-nm"), str(path)], check=True, capture_output=True, text=True).stdout
    return {parts[2]: int(parts[0], 16) for line in output.splitlines() if len(parts := line.split()) == 3}


def build_fixture(work=WORK, integer=False):
    if not tools_present():
        raise ValueError("DSP binutils are needed for the core demo; build tools/tic6x with tools/toolchain/build_tic6x_binutils.sh")
    output = Path(work).resolve() / "core-demo"
    output.mkdir(parents=True, exist_ok=True)
    sources = HERE / "core/fixtures"
    source = "integer.c" if integer else "ram_copy.s"
    stem = Path(source).stem
    # Snapshot fixtures too, so all compiler outputs and inputs stay in this work area.
    for name in (source, "fixture.ld"):
        (output / name).write_bytes((sources / name).read_bytes())
    if integer:
        compiler = BIN / "tic6x-elf-gcc"
        if not compiler.exists():
            raise ValueError("the optional integer C fixture needs the DSP GCC toolchain")
        command = [str(compiler), "-march=c674x", "-O0", "-ffreestanding", "-fno-builtin", "-msdata=none",
                   "-c", source, "-o", stem + ".o"]
    else:
        command = [str(BIN / "tic6x-elf-as"), "-march=c674x", "-o", stem + ".o", source]
    commands = [command, [str(BIN / "tic6x-elf-ld"), "-T", "fixture.ld", "-o", stem + ".elf", stem + ".o"]]
    for command in commands:
        result = subprocess.run(command, cwd=output, capture_output=True, text=True)
        if result.returncode:
            raise ValueError(f"DSP fixture build failed:\n{result.stderr}")
    return output / (stem + ".elf")


def demo(work=WORK, slice_cycles=10000):
    if type(slice_cycles) is not int or not 1 <= slice_cycles <= 1000000:
        raise ValueError("slice_cycles must be between 1 and 1000000")
    elf = build_fixture(work)
    names = symbols(elf)
    application = 0xC2100000
    with CPU(work) as machine:
        entry = machine.load_elf(elf)
        machine.map(application, 4096, 7)
        machine.reset(entry)
        # Decode the initially empty destination to prove that writes invalidate an existing cache.
        from decoder import Decoder
        machine.decoder = Decoder(machine)
        machine.decoder.populate(application)
        state = machine.run(slice_cycles)
        while state["status"] == "budget":
            if state["cycles"] >= 1000000:
                raise RuntimeError("copied-code demo did not return within one million cycles")
            state = machine.run(slice_cycles)
        first = dict(state)
        copied = machine.read(application, 32)
        if first["registers"]["a4"] != 42 or copied != machine.read(names["payload"], 32):
            raise RuntimeError("execution of copied RAM bytes failed")
        machine.write(application, machine.read(names["replacement"], 32))
        machine.reset(application)
        state = machine.run(slice_cycles)
        while state["status"] == "budget":
            if state["cycles"] >= 1000000:
                raise RuntimeError("replacement-code demo did not return within one million cycles")
            state = machine.run(slice_cycles)
        if state["registers"]["a4"] != 99:
            raise RuntimeError("execution of replaced RAM bytes failed")
        replacement = dict(state)
        machine.reset(names["benchmark"], return_address=None)
        machine.decoder.populate(names["benchmark"])
        started = time.perf_counter()
        measured = machine.run(1000000)
        elapsed = time.perf_counter() - started
        report = {
            "backend": "c++", "abi_version": machine.manifest["abi_version"], "manifest": machine.manifest, "artifacts": machine.artifacts,
            "decoder_sha256": {"objdump": digest((BIN / "tic6x-elf-objdump").read_bytes()),
                               "packets.py": digest((ROOT / "analysis/packets.py").read_bytes()),
                               "ir.py": digest((HERE / "ir.py").read_bytes())},
            "copied_code": {"result": first["registers"]["a4"], "cycles": first["cycles"],
                            "packets": first["packets"], "sha256": digest(copied)},
            "replaced_code": {"result": replacement["registers"]["a4"], "cycles": replacement["cycles"]},
            "benchmark": {"kind": "warm ADD/branch/NOP loop; excludes decoder startup", "seconds": elapsed,
                          "cycles": measured["cycles"], "packets": measured["packets"],
                          "packets_per_second": measured["packets"] / elapsed},
            "approximations": ["integer subset", "always-running cycle counter", "coherent memory",
                               "stores visible at issue", "no interrupts, software loops, caches or MMIO"],
        }
    destination = Path(work).resolve() / "core-demo/result.json"
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report, destination
