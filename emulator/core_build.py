"""Build the C++ core; optionally use an exact-source GCC execution profile."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt

from build import HERE, WORK, digest

SOURCES = ("core.h", "core.cpp", "block.h", "board.h", "board.cpp", "edma.h", "edma.cpp", "spi.h", "spi.cpp",
           "uart.h", "uart.cpp", "oled.h", "mmcsd.h", "mmcsd.cpp", "sdcard.h", "sdcard.cpp", "nor.h", "nor.cpp",
           "i2c.h", "i2c.cpp", "codec.h", "codec.cpp", "mcasp.h", "mcasp.cpp", "usb.h", "usb.cpp")
FLAGS = ["-std=c++20", "-O3", "-flto", "-fno-semantic-interposition", "-ffp-contract=off", "-g", "-fPIC",
         "-shared", "-Wall", "-Wextra", "-Werror", "-Wl,-z,defs"]
# Linux with GCC is the developed and measured configuration. Elsewhere the same sources
# build with the platform's own linker conventions and without warnings-as-errors.
if platform.system() == "Darwin":
    FLAGS = [flag for flag in FLAGS if flag not in ("-Werror", "-Wl,-z,defs")]
elif platform.system() == "Windows":
    FLAGS = [flag for flag in FLAGS if flag not in ("-Werror", "-Wl,-z,defs", "-fPIC")] + ["-static-libgcc", "-static-libstdc++"]
COMPILER_ENV = "CXX"
PROFILE_ENV = "SMPLTREK_CORE_PGO"
ACTIVE_PROFILE = WORK / "pgo/active.json"
_override = ContextVar("compiled_core_override", default=None)


@lru_cache(maxsize=8)
def _toolchain(compiler, modified, size):
    version = subprocess.run([compiler, "--version"], check=True, capture_output=True, text=True).stdout.splitlines()[0]
    target = subprocess.run([compiler, "-dumpmachine"], check=True, capture_output=True, text=True).stdout.strip()
    return version, target


def _snapshot():
    compiler = next((found for found in map(shutil.which, filter(None, (os.environ.get(COMPILER_ENV), "g++", "clang++", "c++")))
                     if found), None)
    if not compiler:
        raise ValueError("the compiled CPU core requires a host C++20 compiler (g++ or clang++; set CXX to choose one)")
    stamp = Path(compiler).stat()
    version, target = _toolchain(compiler, stamp.st_mtime_ns, stamp.st_size)
    sources = {name: (HERE / "core" / name).read_bytes() for name in SOURCES}
    recipe = dict(abi_version=2, compiler=version, compiler_target=target, flags=FLAGS.copy(),
                  source_sha256={name: digest(data) for name, data in sources.items()})
    return compiler, sources, recipe


def _json(path, value):
    temporary = path.with_name(path.name + f".{os.getpid()}.pending")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


@contextmanager
def selected_core(library, manifest):
    """Select a host build for CPUs created in this context; guest execution is unchanged."""
    token = _override.set((Path(library), manifest))
    try:
        yield
    finally:
        _override.reset(token)


def _profile(bundle, recipe):
    bundle = Path(bundle).resolve()
    data = json.loads((bundle / "profile.json").read_text())
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("unsupported PGO profile version")
    for key in ("abi_version", "compiler", "compiler_target", "flags", "source_sha256"):
        if data.get(key) != recipe[key]:
            raise ValueError(f"PGO {key} changed; retrain this core")
    expected = {f"core.pending.so-{Path(name).stem}.gcda" for name in recipe["source_sha256"] if name.endswith(".cpp")}
    hashes = data.get("profile_sha256", {})
    if set(hashes) != expected:
        raise ValueError("missing or unexpected PGO counter files")
    if not isinstance(data.get("training"), dict) or data["training"].get("passed") is not True:
        raise ValueError("PGO training did not pass")
    for name, sha in hashes.items():
        if digest((bundle / "counts" / name).read_bytes()) != sha:
            raise ValueError(f"PGO counter hash mismatch: {name}")
    return bundle, data


def _build(work, compiler, sources, recipe, profile=None, instrument=None):
    manifest = dict(recipe)
    if profile:
        bundle, data = profile
        manifest["optimization"] = dict(kind="gcc-pgo", bundle=str(bundle), profile_sha256=data["profile_sha256"])
    elif instrument:
        manifest["optimization"] = dict(kind="gcc-profile-generate", counters=str(instrument / "collect-counts"))
    else:
        manifest["optimization"] = dict(kind="portable")
    identity = digest(json.dumps(manifest, sort_keys=True).encode())
    output = instrument / "instrumented" if instrument else Path(work).resolve() / "cores" / identity
    output.mkdir(parents=True, exist_ok=True)
    library = output / "libc6core.so"
    flags = recipe["flags"].copy()
    if profile:
        flags += [f"-fprofile-use={bundle / 'counts'}", f"-fprofile-prefix-path={output}"]
    elif instrument:
        flags += [f"-fprofile-generate={instrument / 'collect-counts'}", "-fprofile-update=single",
                  f"-fprofile-prefix-path={output}"]
    manifest.update(flags=flags, build_id=identity)
    # A collector and regular runners may build concurrently. Never expose a
    # partial library, mixed source snapshot or manifest from a competing build.
    with (output / ".build.lock").open("a") as lock:
        if fcntl:
            fcntl.flock(lock, fcntl.LOCK_EX)
        else:
            lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        if not library.exists():
            for name, contents in sources.items():
                (output / name).write_bytes(contents)
            units = [name for name in sources if name.endswith(".cpp")]
            command = [compiler, *flags, f"-ffile-prefix-map={output}=.", *units, "-o", "core.pending.so"]
            result = subprocess.run(command, cwd=output, capture_output=True, text=True)
            (output / "compiler.log").write_text(result.stdout + result.stderr)
            if result.returncode:
                raise ValueError(f"C++ core build failed:\n{result.stderr}")
            (output / "core.pending.so").replace(library)
        manifest["library_sha256"] = digest(library.read_bytes())
        _json(output / "manifest.json", manifest)
    return library, manifest


def build_core(work=WORK, profile=None):
    if _override.get() is not None:
        return _override.get()
    compiler, sources, recipe = _snapshot()
    requested = profile if profile is not None else os.environ.get(PROFILE_ENV)
    automatic = not requested
    selected, reason = None, "not configured"
    try:
        if automatic:
            if ACTIVE_PROFILE.exists():
                pointer = json.loads(ACTIVE_PROFILE.read_text())
                requested = pointer["bundle"]
                if digest((Path(requested) / "profile.json").read_bytes()) != pointer["profile_sha256"]:
                    raise ValueError("active PGO manifest hash mismatch")
        if requested and str(requested) != "off":
            selected = _profile(requested, recipe)
            reason = "selected"
        elif requested:
            reason = "disabled"
    except (OSError, ValueError, KeyError, TypeError) as error:
        if not automatic:
            raise ValueError(f"cannot use PGO profile: {error}") from error
        reason = f"inactive: {error}"
    library, manifest = _build(work, compiler, sources, recipe, profile=selected)
    manifest["profile_selection"] = reason
    return library, manifest


def instrument_core(bundle):
    """Freeze sources for one collection process. Its counters are never final inputs."""
    bundle = Path(bundle).resolve()
    if any(bundle.iterdir()):
        raise ValueError("PGO collection directory must be empty")
    (bundle / "collect-counts").mkdir()
    compiler, sources, recipe = _snapshot()
    library, manifest = _build(bundle, compiler, sources, recipe, instrument=bundle)
    _json(bundle / "collection.json", dict(recipe=recipe, library=str(library), manifest=manifest))
    return library, manifest


def collection_core(bundle):
    bundle = Path(bundle).resolve()
    if (bundle / "profile.json").exists():
        raise ValueError("this PGO collection is already finalized")
    data = json.loads((bundle / "collection.json").read_text())
    library = Path(data["library"])
    if digest(library.read_bytes()) != data["manifest"]["library_sha256"]:
        raise ValueError("instrumented core hash mismatch")
    return library, data["manifest"]


def finalize_profile(bundle, training):
    bundle = Path(bundle).resolve()
    if (bundle / "profile.json").exists():
        raise ValueError("this PGO collection is already finalized")
    if training.get("passed") is not True:
        raise ValueError("PGO training did not pass")
    compiler, sources, recipe = _snapshot()
    collection = json.loads((bundle / "collection.json").read_text())
    if collection["recipe"] != recipe:
        raise ValueError("core sources or toolchain changed during PGO collection; retrain")
    expected = {f"core.pending.so-{Path(name).stem}.gcda" for name in sources if name.endswith(".cpp")}
    observed = {path.name for path in (bundle / "collect-counts").iterdir()}
    if observed != expected:
        raise ValueError("PGO collection did not emit every translation unit's counters")
    # Freeze copies after the collector exits. A late gcov write cannot mutate
    # counters that a later optimized build consumes.
    counts = bundle / "counts"; counts.mkdir()
    hashes = {}
    for name in sorted(expected):
        contents = (bundle / "collect-counts" / name).read_bytes()
        if not contents:
            raise ValueError("empty PGO counter file")
        (counts / name).write_bytes(contents); hashes[name] = digest(contents)
    _json(bundle / "profile.json", dict(schema_version=1, **recipe, profile_sha256=hashes, training=training))
    return build_core(bundle, profile=bundle)


def activate_profile(bundle):
    _, _, recipe = _snapshot()
    bundle, _ = _profile(bundle, recipe)
    ACTIVE_PROFILE.parent.mkdir(parents=True, exist_ok=True)
    _json(ACTIVE_PROFILE, dict(bundle=str(bundle), profile_sha256=digest((bundle / "profile.json").read_bytes())))
