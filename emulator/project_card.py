#!/usr/bin/env python3
"""Build an SD card holding the factory drum kits and one generated stock project.

Three steps, each cached under the work folder:
  1. Tools. The pinned npm packages in projects/package-lock.json (smpltrek-builder and
     drum-pattern-engine, MIT, by Alexander Schornberg) are installed with `npm ci` into the work
     folder. Nothing of theirs is kept in this repository.
  2. Preset card. The unmodified stock firmware runs with a factory-like flash (flash_image.py) and a
     blank card, and is driven through SYSTEM MENU > CARD > DUPLICATE PRESETS > DRUM KIT, so the kits
     and drum sounds on the card are the ones the firmware itself writes.
  3. Project. projects/make_config.mjs writes a project Config from a seeded generated song; the card
     is rebuilt from the preset files with that Config as /SmplTrek/Project/Project001/Config.

Step 2 uses the same logged reserved low-store assumption as the other stock checks.
Requires node and npm (18 or later), host GCC, and the 3.2.174 and 2.0.129 updates under firmware/.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from build import WORK, digest
from fat_image import FatImage
from flash_image import factory_flash
from media import build_card
from stock import Stock

HERE = Path(__file__).resolve().parent
MS = 372000
FUNC, HOME, OK, CLR, DOWN = 19, 27, 23, 30, 25
KITS = 15
INSTRUMENTS = 24


def tools(work=WORK):
    """Folder with the pinned packages installed and make_config.mjs beside them."""
    sources = {name: (HERE / "projects" / name).read_bytes() for name in ("package.json", "package-lock.json", "make_config.mjs")}
    folder = Path(work) / "project-tools" / digest(b"".join(sources[name] for name in sorted(sources)))[:16]
    if not (folder / "node_modules/smpltrek-builder").is_dir():
        npm = shutil.which("npm")
        if not npm or not shutil.which("node"):
            raise ValueError("generating a project needs node and npm")
        folder.mkdir(parents=True, exist_ok=True)
        for name, data in sources.items():
            (folder / name).write_bytes(data)
        result = subprocess.run([npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=folder, capture_output=True, text=True)
        if result.returncode:
            raise ValueError(f"npm ci failed:\n{result.stderr[-2000:]}")
    return folder


def project_config(genre="FUNK", seed=1, work=WORK):
    """(Config bytes, the generator's description) for one seeded song."""
    folder = tools(work)
    output = folder / f"config-{genre}-{seed}.bin"
    result = subprocess.run([shutil.which("node"), "make_config.mjs", output.name, genre, str(seed)], cwd=folder, capture_output=True, text=True)
    if result.returncode:
        raise ValueError(result.stderr.strip() or "project generation failed")
    return output.read_bytes(), json.loads(result.stdout)


def duplicate_presets(card, flash, work, target):
    """FatImage of `card` after SYSTEM MENU > CARD > DUPLICATE PRESETS with the target `target` entries down the list."""
    with Stock(card=card, flash_image=flash, work=work, reserved_low_writes=True) as stock:
        def advance(milliseconds):
            report = stock.run(milliseconds * MS, 1000000)
            if report["error"]:
                raise RuntimeError(report["error"])

        def press(*keys):
            for key in keys:
                stock.key_input(key, True); advance(70)
            for key in reversed(keys):
                stock.key_input(key, False); advance(70)
            advance(450)

        advance(6000)
        press(CLR)                                   # the "format recommended" notice on a foreign card
        press(FUNC, HOME)                            # SYSTEM MENU
        for _ in range(6): press(DOWN)               # CARD is the seventh entry
        press(OK)
        press(DOWN); press(DOWN); press(OK)          # DUPLICATE PRESETS
        for _ in range(target): press(DOWN)          # DRUM KIT is first, INST second
        press(OK)
        start = stock.cpu.sd_state()["bytes_written"]
        written, quiet = -1, 0
        for _ in range(240):                         # until the card has been idle for three guest seconds
            advance(1000)
            now = stock.cpu.sd_state()["bytes_written"]
            quiet = quiet + 1 if now == written else 0
            written = now
            if quiet >= 3 and written - start > 1000000:
                break
        return FatImage(stock.cpu.sd_read())


def preset_files(work=WORK, size_mb=256, instruments=False):
    """{card path: local file} of everything the firmware writes for DUPLICATE PRESETS > DRUM KIT, and the flash image.

    With `instruments`, DUPLICATE PRESETS > INST is run on a card that already holds the kits, so the
    result has both."""
    flash, _ = factory_flash()
    folder = Path(work) / "project-cards" / f"presets-{digest(flash)[:16]}-{size_mb}"
    if instruments:
        base, flash_path = preset_files(work, size_mb)
        folder = folder.with_name(folder.name + "-inst")
    listing = folder / "files.json"
    if not listing.exists():
        folder.mkdir(parents=True, exist_ok=True)
        if instruments:
            card = duplicate_presets(build_card(folder / "kits.img", base, size_mb=size_mb, work=work, long_names=True), flash_path, work, 1)
        else:
            (folder / "flash.img").write_bytes(flash)
            card = duplicate_presets(build_card(folder / "blank.img", size_mb=size_mb, work=work), folder / "flash.img", work, 0)
        files = {}
        for entry in card.entries.values():
            if not entry.directory:
                local = folder / "tree" / entry.path.lstrip("/")
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(card.read(entry.path))
                files[entry.path] = str(local)
        kits = [path for path in files if path.lower().endswith(".stk")]
        if len(kits) != KITS:
            raise RuntimeError(f"the firmware wrote {len(kits)} kits, expected {KITS}: the menu path may differ in this image")
        sounds = [path for path in files if "/preset/audio/inst/" in path.lower()]
        if instruments and len(sounds) != INSTRUMENTS:
            raise RuntimeError(f"the firmware wrote {len(sounds)} instrument sounds, expected {INSTRUMENTS}: the menu path may differ in this image")
        listing.write_text(json.dumps(files, indent=1, sort_keys=True) + "\n")
    return {name: Path(local) for name, local in json.loads(listing.read_text()).items()}, folder.with_name(folder.name.removesuffix("-inst")) / "flash.img"


def project_card(destination, genre="FUNK", seed=1, work=WORK, size_mb=256):
    """(card image path, flash image path, description). The card holds the kits and one project."""
    files, flash = preset_files(work, size_mb)
    config, description = project_config(genre, seed, work)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    local = destination.with_suffix(".config")
    local.write_bytes(config)
    files = dict(files)
    files["/SmplTrek/Project/Project001/Config"] = local
    card = build_card(destination, files, size_mb=size_mb, work=work, long_names=True)
    description.update(config_sha256=digest(config), files=len(files))
    return card, flash, description


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--genre", default="FUNK", help="one of the builder's genre presets, e.g. FUNK, JAZZ, HOUSE, DNB")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--output", type=Path, default=WORK / "project-cards/project.img")
    args = parser.parse_args(argv)
    card, flash, description = project_card(args.output, args.genre, args.seed)
    print(json.dumps(description, sort_keys=True))
    print(f"Card:  {card}\nFlash: {flash}")
    print(f"Try:   python3 -B emulator/stock_ui.py --card {card} --flash {flash}")


if __name__ == "__main__":
    main()
