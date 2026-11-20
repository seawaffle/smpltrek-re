"""Sample warmed native stock execution with an unprivileged Linux SIGPROF timer."""
import argparse
import collections
import ctypes as C
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import time

from build import HERE, WORK, digest
from stock import Stock


def sampler(work):
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "aarch64"):
        raise ValueError("native sampling requires Linux x86_64 or aarch64")
    compiler = shutil.which("g++")
    if not compiler:
        raise ValueError("native sampling requires g++")
    source = (HERE / "native_sampler.cpp").read_bytes()
    version = subprocess.run([compiler, "--version"], check=True, capture_output=True, text=True).stdout.splitlines()[0]
    flags = ["-std=c++20", "-O2", "-g", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror"]
    manifest = dict(compiler=version, flags=flags, source_sha256=digest(source))
    identity = digest(json.dumps(manifest, sort_keys=True).encode())
    directory = Path(work).resolve() / "samplers" / identity
    directory.mkdir(parents=True, exist_ok=True)
    library = directory / "sampler.so"
    if not library.exists():
        (directory / "sampler.cpp").write_bytes(source)
        result = subprocess.run([compiler, *flags, "sampler.cpp", "-o", "sampler.pending.so"],
                                cwd=directory, capture_output=True, text=True)
        (directory / "compiler.log").write_text(result.stdout + result.stderr)
        if result.returncode:
            raise ValueError(f"sampler build failed:\n{result.stderr}")
        (directory / "sampler.pending.so").replace(library)
    manifest.update(build_id=identity, library_sha256=digest(library.read_bytes()))
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    native = C.CDLL(str(library))
    for name, result, args in (("start", C.c_int, [C.c_uint]), ("stop", C.c_int, []),
                               ("count", C.c_uint, []), ("dropped", C.c_uint, []), ("pc", C.c_size_t, [C.c_uint])):
        fn = getattr(native, "sample_" + name); fn.restype, fn.argtypes = result, args
    return native, manifest


def executable_bias(path, offset):
    """Translate a mapped file offset to its ELF virtual address (PIE, DSO or fixed executable)."""
    with open(path, "rb") as source:
        header = source.read(64)
        if header[:5] != b"\x7fELF\x02" or header[5] not in (1, 2):
            raise ValueError(f"unsupported host ELF: {path}")
        endian = "<" if header[5] == 1 else ">"
        phoff, = struct.unpack_from(endian + "Q", header, 32)
        phsize, phcount = struct.unpack_from(endian + "HH", header, 54)
        if phsize < 56:
            raise ValueError(f"invalid host ELF program headers: {path}")
        source.seek(phoff)
        for _ in range(phcount):
            entry = source.read(phsize)
            kind, flags, file_offset, address, _, _, memory_size, _ = struct.unpack_from(endian + "IIQQQQQQ", entry)
            page = os.sysconf("SC_PAGE_SIZE")
            if kind == 1 and flags & 1 and file_offset // page * page <= offset < file_offset + memory_size:
                return address - file_offset
    raise ValueError(f"no executable ELF segment for {path} at {offset:#x}")


def resolve(pcs):
    addr2line = shutil.which("addr2line")
    if not addr2line:
        raise ValueError("native sampling requires host addr2line")
    mappings = []
    for row in Path("/proc/self/maps").read_text().splitlines():
        fields = row.split(maxsplit=5)
        if len(fields) != 6 or not fields[5].startswith("/") or "x" not in fields[1]:
            continue
        begin, end = (int(value, 16) for value in fields[0].split("-"))
        mappings.append((begin, end, int(fields[2], 16), fields[5]))
    grouped = collections.defaultdict(collections.Counter)
    biases = {}
    unknown = 0
    for pc, count in pcs.items():
        for begin, end, offset, path in mappings:
            if begin <= pc < end:
                key = path, offset
                if key not in biases:
                    try:
                        biases[key] = executable_bias(path, offset)
                    except (OSError, ValueError, struct.error):
                        # Unreadable/deleted ELF mappings remain visible in the accounting.
                        biases[key] = None
                if biases[key] is None:
                    unknown += count
                else:
                    grouped[path][pc - begin + offset + biases[key]] += count
                break
        else:
            unknown += count
    rows = []
    for path, addresses in grouped.items():
        keys = list(addresses)
        for begin in range(0, len(keys), 256):
            batch = keys[begin:begin + 256]
            output = subprocess.run([addr2line, "-a", "-f", "-C", "-i", "-e", path,
                                     *[hex(pc) for pc in batch]], check=True, capture_output=True, text=True).stdout.splitlines()
            current, frames = None, []
            def save():
                if current is not None:
                    rows.append(dict(library=path, address=current, samples=addresses[current], frames=list(frames)))
            index = 0
            while index < len(output):
                if re.fullmatch(r"0x[0-9a-fA-F]+", output[index]):
                    save(); current = int(output[index], 16); frames = []; index += 1
                else:
                    frames.append(dict(function=output[index], source=output[index + 1])); index += 2
            save()
    return sorted(rows, key=lambda row: -row["samples"]), unknown


def profile(work=WORK, boot_cycles=250000000, cycles=500000000, interval_us=1000,
            audio_input=None, loop_audio_input=False):
    if type(interval_us) is not int or not 1 <= interval_us <= 1000000:
        raise ValueError("interval_us must be 1..1000000")
    if len(list(Path("/proc/self/task").iterdir())) != 1:
        raise ValueError("native sampling requires a dedicated single-threaded runner")
    native, manifest = sampler(work)
    with Stock(work=work, audio_input=audio_input, loop_audio_input=loop_audio_input) as stock:
        boot = stock.run(boot_cycles)
        if boot["error"]:
            raise RuntimeError(boot["error"])
        decoded = len(stock.cpu.decoder.text)
        started = time.process_time()
        if native.sample_start(interval_us):
            raise RuntimeError("could not start process CPU sampler")
        try:
            result = stock.run(cycles)
        finally:
            if native.sample_stop():
                raise RuntimeError("could not stop process CPU sampler")
        cpu_seconds = time.process_time() - started
        if not native.sample_count():
            raise RuntimeError("no CPU samples captured; increase the execution budget")
        pcs = collections.Counter(native.sample_pc(i) for i in range(native.sample_count()))
        rows, unknown = resolve(pcs)
        groups = collections.Counter()
        for row in rows:
            frames = row["frames"]
            frame = next((f for f in frames if "Machine::" in f["function"] or "Board::" in f["function"]),
                         frames[0] if frames else {"function": "??"})
            groups[frame["function"]] += row["samples"]
        result["native_profile"] = dict(interval_cpu_us=interval_us, samples=native.sample_count(),
                                        sampler=manifest, host_cpu_seconds=cpu_seconds,
                                        observed_interval_cpu_us=cpu_seconds * 1000000 / native.sample_count(),
                                        dropped=native.sample_dropped(), unmapped=unknown,
                                        decoded_instructions=len(stock.cpu.decoder.text) - decoded,
                                        functions=[dict(function=name, samples=count) for name, count in groups.most_common()],
                                        locations=rows,
                                        limitations=["statistical process-CPU samples; not exact per-function timing",
                                                     "inline attribution depends on compiler DWARF; sampling adds overhead"])
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--boot-cycles", type=int, default=250000000)
    parser.add_argument("--cycles", type=int, default=500000000)
    parser.add_argument("--interval-us", type=int, default=1000)
    parser.add_argument("--audio-input", type=Path)
    parser.add_argument("--loop-audio-input", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = profile(args.work, args.boot_cycles, args.cycles, args.interval_us, args.audio_input, args.loop_audio_input)
    path = args.output or args.work / "performance/native-profile.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    total = report["native_profile"]["samples"]
    for row in report["native_profile"]["functions"][:12]:
        print(f'{row["samples"] / max(1, total):6.1%} {row["function"]}')
    print(f"Samples: {total}; report: {path}")
    if report["error"]:
        raise RuntimeError(report["error"])


if __name__ == "__main__":
    main()
