"""Compile hot guest code to host code (see core/block.h).

The core writes C++ for a run of packets; this module compiles batches with the host
compiler, loads them and installs the functions. Libraries are cached by source hash, and each
block is recorded by its own source, so a later run finds it in whatever library holds it.
"""
from concurrent.futures import ThreadPoolExecutor
import ctypes as C
import os
from pathlib import Path
import shutil
import subprocess

from build import HERE, digest
from core_build import COMPILER_ENV

FLAGS = ["-std=c++20", "-O2", "-ffp-contract=off", "-fPIC", "-shared", "-DC6_BLOCK_CODE"]
BATCH = 128  # blocks per library; batches compile in parallel
# Host compilers one build may run at once. A program that runs several machines side by side sets it
# (share_compilers) so that together they stay near the number of CPUs; each compiler takes a few hundred MB.
JOBS_ENV = "SMPLTREK_BLOCK_JOBS"
_loaded = []  # Libraries must outlive every machine that calls into them.


def collect(cpu, minimum_heat=64, limit=4000, known=()):
    """Sources {pc: C++} for hot entry points not in `known`. Call on the machine's thread."""
    sources, queue = {}, [pc for pc, heat in cpu.block_hot() if heat >= minimum_heat and pc not in known][:limit]
    while queue:
        pc = queue.pop()
        if pc in sources or pc in known:
            continue
        planned = cpu.block_source(pc)
        if planned is None:
            continue
        sources[pc] = planned[0]
        if planned[2]:
            queue.append(planned[2])
    return sources


def build_one(work, header, text):
    directory = Path(work) / "blocks" / digest(header + text.encode())
    library = directory / "blocks.so"
    if not library.exists():
        compiler = next(found for found in map(shutil.which, filter(None, (os.environ.get(COMPILER_ENV), "g++", "clang++", "c++"))) if found)
        directory.mkdir(parents=True, exist_ok=True)
        # Several processes may build the same text at once: each compiles its own copy of the
        # source and the finished files are moved into place whole.
        pending, source = f"blocks.{os.getpid()}.pending", f"blocks.{os.getpid()}.cpp"
        (directory / source).write_text(text)
        result = subprocess.run([compiler, *FLAGS, f"-I{HERE / 'core'}", source, "-o", pending],
                                cwd=directory, capture_output=True, text=True)
        if result.returncode:
            raise ValueError(f"block compilation failed:\n{result.stderr[-4000:]}")
        (directory / source).replace(directory / "blocks.cpp")
        (directory / pending).replace(library)
    return library


def _marker(work, header, text):
    """Where the library holding the block compiled from `text` is recorded (the name of its folder)."""
    key = digest(header + text.encode())
    return Path(work) / "blocks" / "by-source" / key[:2] / key


def build(work, sources, jobs=None):
    """Libraries holding sources, as [(library, [pc])]; touches no machine, so any thread may call it.

    A block whose source was compiled before, in whatever batch, is taken from the library that holds it: a
    later run of the same guest code then waits for no compiler, though it finds its hot code in another order.
    Only the others are compiled, in batches."""
    header = (HERE / "core/block.h").read_bytes()
    found, missing = {}, []
    for pc in sorted(sources):
        try:
            library = Path(work) / "blocks" / _marker(work, header, sources[pc]).read_text() / "blocks.so"
        except OSError:
            library = None
        if library is not None and library.exists():
            found.setdefault(library, []).append(pc)
        else:
            missing.append(pc)
    batches = [missing[start:start + BATCH] for start in range(0, len(missing), BATCH)]
    texts = ['#include "block.h"\n' + "".join(sources[pc] for pc in batch) for batch in batches]
    jobs = jobs or int(os.environ.get(JOBS_ENV) or 0) or max(1, (os.cpu_count() or 2) - 1)
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        libraries = list(pool.map(lambda text: build_one(work, header, text), texts))
    for library, batch in zip(libraries, batches):
        for pc in batch:
            marker = _marker(work, header, sources[pc])
            marker.parent.mkdir(parents=True, exist_ok=True)
            pending = marker.with_name(f"{marker.name}.{os.getpid()}.pending")
            pending.write_text(library.parent.name)
            pending.replace(marker)
    return [*found.items(), *zip(libraries, batches)]


def install(cpu, built, sources):
    """Install built blocks whose guest code still plans to the compiled source; returns how many."""
    installed = 0
    for library, batch in built:
        loaded = C.CDLL(str(library))
        _loaded.append(loaded)
        for pc in batch:
            planned = cpu.block_source(pc)
            function = getattr(loaded, f"c6blk_{pc:08x}", None)   # None: a record that names the wrong library
            if function is not None and planned is not None and planned[0] == sources[pc]:
                cpu.block_install(pc, C.cast(function, C.c_void_p))
                installed += 1
    return installed


def share_compilers(machines):
    """Before starting `machines` worker processes that each compile blocks: divide the CPUs among them."""
    os.environ[JOBS_ENV] = str(max(1, (os.cpu_count() or 2) // max(1, machines)))


def memory_jobs(wanted, gigabytes_each):
    """`wanted` workers, or as many as the memory now available holds at `gigabytes_each` (Linux; elsewhere `wanted`)."""
    try:
        with open("/proc/meminfo") as file:
            available = next(int(line.split()[1]) for line in file if line.startswith("MemAvailable:")) / 1048576
    except (OSError, StopIteration, ValueError):
        return wanted
    return max(1, min(wanted, int(available / gigabytes_each)))


def compile_blocks(cpu, minimum_heat=64, limit=4000):
    """Compile and install blocks for the hot entry points seen so far; returns how many."""
    sources = collect(cpu, minimum_heat, limit)
    return install(cpu, build(cpu.work, sources), sources) if sources else 0
