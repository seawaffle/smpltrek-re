#!/usr/bin/env bash
# Regenerate the standard work/ outputs the analysis scripts and tests read: per reference image an ELF, an objdump
# listing and the recovered RTTI, plus the function matches from SmplTrek 3.2.174 to the other products and the
# 3.2.174 string references. The outputs contain Sonicware code, so work/ is git-ignored.
#
# Needs: the update files in firmware/ (firmware/README.md) and tools/tic6x (tools/toolchain/build_tic6x_binutils.sh).
# Not produced here: work/a4/ (a flash read of a unit) and the TI library match (needs TI's compiler libraries).
# Run from anywhere: analysis/make_work.sh [--force]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OBJDUMP=tools/tic6x/bin/tic6x-elf-objdump
FORCE=${1:-}
[ -x "$OBJDUMP" ] || { echo "missing $OBJDUMP: run tools/toolchain/build_tic6x_binutils.sh" >&2; exit 1; }
mkdir -p work

ST="firmware/smpltrek/SmplTrek v3.2.174.zip"
declare -A IMAGES=(
  [smpltrek-3.2.174]="$ST"
  [lofi-1.5.205]="firmware/lofi12/Lofi-12XT_v1.5.205.zip"
  [cydrums-1.1.84]="firmware/cydrums/CyDrums_v1.1.84.zip"
)

gen() {    # gen OUTPUT COMMAND...: run unless OUTPUT exists (or --force)
  local out=$1; shift
  if [ -s "$out" ] && [ "$FORCE" != "--force" ]; then echo "have  $out"; return; fi
  echo "make  $out"
  rm -f "$out"
  "$@"
}

for name in "${!IMAGES[@]}"; do
  src=${IMAGES[$name]}
  [ -f "$src" ] || { echo "missing $src (see firmware/README.md)" >&2; exit 1; }
  gen "work/$name.elf"       python3 -B analysis/mmtd2elf.py "$src" "work/$name.elf"
  gen "work/$name.seg.elf"   python3 -B analysis/mmtd2elf.py --segments-only "$src" "work/$name.seg.elf"
  gen "work/$name.dis"       sh -c "\"$OBJDUMP\" -d \"work/$name.elf\" > \"work/$name.dis\""
  gen "work/$name.rtti.json" python3 -B analysis/rtti_recover.py "$src" "work/$name.rtti.json"
done

gen work/smpltrek-3.2.174.strings.json \
  python3 -B analysis/string_refs.py "$ST" work/smpltrek-3.2.174.strings.json --rtti work/smpltrek-3.2.174.rtti.json

match() {  # match OTHER_ZIP OUTPUT
  gen "$2" python3 -B analysis/func_match.py "$ST" "$1" -o "$2" --symbols symbols/smpltrek-3.2.174.json
}
match "firmware/smpltrek/SmplTrek v3.0.148.zip"     work/match-3.2.174-3.0.148.json
match "firmware/lofi12/Lofi-12XT_v1.5.205.zip"      work/match-3.2.174-Lofi-12XT_v1.5.205.json
match "firmware/cydrums/CyDrums_v1.1.84.zip"        work/match-3.2.174-CyDrums_v1.1.84.json
echo "work/ is up to date"
