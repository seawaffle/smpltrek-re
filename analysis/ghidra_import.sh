#!/usr/bin/env bash
# Import and analyse a Sonicware system image in Ghidra with ghidra-c6000, then apply RTTI symbols.
#
# Usage (from the repository root):
#   analysis/ghidra_import.sh "firmware/smpltrek/SmplTrek v3.2.174.zip" smpltrek-3.2.174
#
# Produces work/<name>.seg.elf, work/<name>.rtti.json and the Ghidra project
# work/ghidra/smpltrek (program <name>.seg.elf). About 6 minutes for 3.2.174.
#
# Why each step (ghidra-c6000 v1.2.0, Ghidra 12.1.4, found 2026-11-08):
#   --segments-only ELF + RemoveNonLoadedBlocks: the "C6000 Delayed Calls" analyzer throws on
#       non-loaded blocks (_elfHeader, .shstrtab), and without it calls are not followed.
#   -loader ElfLoader -processor ...: the extension's ELF opinion does not match, so no auto-select.
#   DisableAnalyzers: "C6000 Register Branch Flow" and "C6000 Late Branch Flow" took ~5100 s of a
#       5400 s run that timed out; a timed-out headless run saves nothing.
#   ApplyRttiSymbols as a POST-script: disassembling before auto-analysis (before the packet
#       analyzer primes the decode context) yields broken code that analysis never revisits.
set -euo pipefail
input=$1
name=$2
ghidra=${GHIDRA_INSTALL_DIR:-$HOME/ghidra/ghidra_12.1.4_PUBLIC}
root=$(cd "$(dirname "$0")/.." && pwd)
work=$root/work
mkdir -p "$work/ghidra"

python3 -B "$root/analysis/mmtd2elf.py" --segments-only "$input" "$work/$name.seg.elf"
python3 -B "$root/analysis/rtti_recover.py" "$input" "$work/$name.rtti.json"

"$ghidra/support/analyzeHeadless" "$work/ghidra" smpltrek \
  -import "$work/$name.seg.elf" -overwrite \
  -loader ElfLoader -processor C6000:LE:32:default \
  -scriptPath "$root/ghidra/scripts" \
  -preScript RemoveNonLoadedBlocks.java \
  -preScript DisableAnalyzers.java "C6000 Register Branch Flow" "C6000 Late Branch Flow" \
  -postScript DecompileAt.java \
  -postScript ApplyRttiSymbols.java "$work/$name.rtti.json" \
  -postScript DecompileAt.java \
  > "$work/ghidra-import-$name.log" 2>&1

grep -E 'ApplyRttiSymbols:|STATS|timed out' "$work/ghidra-import-$name.log" | sed 's/ (GhidraScript)\s*$//'
