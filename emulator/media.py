"""Private SD media inputs and a source-snapshotted synthetic FAT image builder (FatFs host tool)."""
import json
from pathlib import Path
import re
import shutil
import subprocess

from build import WORK, digest

HERE = Path(__file__).resolve().parent


def sd_input(path):
    if path is None:
        return None, {"profile": "empty socket"}
    path = Path(path)
    size = path.stat().st_size
    if size < 2 * 1024 * 1024 or size > 1024 * 1024 * 1024 or size & (size - 1):
        raise ValueError("SDSC backing must be a power-of-two size from 2 MiB to 1 GiB")
    data = path.read_bytes()
    return data, {"profile": "SD 2.0 SDSC, private copy, byte addressing", "path": str(path),
                  "size": len(data), "sha256": digest(data), "synthetic_cid_csd": True,
                  "response_gap_clocks": 8, "write_busy_clocks": 32,
                  "timing": "functional; electrical edges, CRC faults and real flash latency are not modeled"}


def build_card(destination, files=None, size_mb=2, work=WORK, long_names=False):
    """FAT12/16 card holding `files` ({card path: local file}). `long_names` builds the image with a
    FatFs that writes VFAT long names (ASCII only); without it, names must be 8.3."""
    if type(size_mb) is not int or size_mb not in (2, 4, 8, 16, 32, 64, 128, 256, 512, 1024):
        raise ValueError("card size must be a power of two from 2 to 1024 MiB")
    compiler = shutil.which("gcc")
    if not compiler:
        raise ValueError("building a synthetic FAT card requires host GCC")
    sources = {name: (HERE / "third_party/fatfs" / name).read_bytes() for name in ("ff.c", "ff.h", "diskio.h")}
    sources.update({name: (HERE / "native" / name).read_bytes() for name in ("mkimage.c", "ffconf.h")})
    units = ["mkimage.c", "ff.c"]
    if long_names:
        # Change only the staged copy; the conversion routines FatFs then needs are ASCII stand-ins.
        config, count = re.subn(rb"(#define\s+FF_USE_LFN\s+)0\b", rb"\g<1>1", sources["ffconf.h"])
        if count != 1:
            raise ValueError("expected FF_USE_LFN=0 in the host tool's FatFs configuration")
        sources["ffconf.h"] = config
        sources["ascii_names.c"] = (HERE / "native/ascii_names.c").read_bytes()
        units.append("ascii_names.c")
    version = subprocess.run([compiler, "--version"], check=True, capture_output=True, text=True).stdout.splitlines()[0]
    manifest = dict(compiler=version, flags=["-O2", "-Wall"], source_sha256={name: digest(data) for name, data in sources.items()})
    identity = digest(json.dumps(manifest, sort_keys=True).encode())
    directory = Path(work).resolve() / "card-tools" / identity
    directory.mkdir(parents=True, exist_ok=True)
    tool = directory / "mkimage"
    if not tool.exists():
        for name, data in sources.items():
            (directory / name).write_bytes(data)
        result = subprocess.run([compiler, *manifest["flags"], *units, "-o", "mkimage.pending"],
                                cwd=directory, text=True, capture_output=True)
        (directory / "compiler.log").write_text(result.stdout + result.stderr)
        if result.returncode:
            raise ValueError(f"card builder failed:\n{result.stderr}")
        (directory / "mkimage.pending").replace(tool)
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(tool), str(destination), str(size_mb),
                    *[f"{name}={Path(local).resolve()}" for name, local in (files or {}).items()]], check=True)
    if destination.stat().st_size != size_mb * 1024 * 1024:
        raise ValueError(f"card image {destination} is {destination.stat().st_size} bytes, expected {size_mb} MiB")
    return destination
