# Other-product session scripts

The session scripts behind the static profiles of the other Sonicware products (2026-11-23):
`liven/` for [docs/15-liven.md](../../docs/15-liven.md), `elzplay/` for
[docs/16-elz1-play-minimal.md](../../docs/16-elz1-play-minimal.md) (ELZ_1 play and MINIMAL), `elz1/` for
[docs/17-elz1.md](../../docs/17-elz1.md). They are kept so the evidence in those documents and in the LIV, ELP,
MIN and ELZ claims can be re-run. They are single-purpose, untested and not maintained like the tools in
`analysis/`: read a script before running it.

Run them from the repository root with `python3 -B`. Inputs are the updates in `firmware/other/`; outputs and
intermediate files go to `work/other/<group>/`, or to `$OTHER_OUT` if set. Many expect earlier outputs of their
group, not produced by any script here:

- an ELF per image from `analysis/mmtd2elf.py`, with its `.elf.log` (`liven/b14.py` reads the entry from it), and
  for `elz1/` an objdump listing `dis-<version>.txt` in the current directory (`findinit.py`, `xrel.py`);
- `b14.txt` (the output of `liven/b14.py`), `<image>.carried.txt` (`analysis/func_match.py` names carried from
  SmplTrek) and `<image>.hw.json` (`analysis/hw_inventory.py`) for the Liven simulations;
- `analysis/rtti_recover.py` JSON in `work/other/rtti/` (`elz1/classes.py`) or `work/other/other/`
  (`liven/sysexlam.py`), and `analysis/lib_match.py` JSON for `liven/rtsver.py`;
- `elz1/xrel.py` reads `inits.txt`, the `__TI_auto_init` table constants printed by `elz1/findinit.py`;
- `elzplay/rdiff.py` needs the `func_match` tables `work/match-3.2.174-<image>.json`;
- `liven/pmdecode.py` reads TI StarterWare's `hw_syscfg0_C6748.h` (`$STARTERWARE`, default
  `~/ti/C6748_StarterWare_1_20_04_01`, as `analysis/mmio_trace.py`).

The SYS/BIOS 6.76.03.01 library rebuilt with CGT 8.3.10, used for the Liven kernel match, was a scratch build
and is not kept; `analysis/sysbios_match.cfg` rebuilds it. Six older scripts cited by claims (`gpio_scan.py`,
`census2.py`, `codec_scan.py`, `selsim.py`, `padsim.py`, `lofi_press.py`) were not kept anywhere.
