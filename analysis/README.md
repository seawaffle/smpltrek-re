# analysis/

The static-analysis and simulation pipeline. Every script reads Sonicware's update files from `firmware/`
and writes regenerated outputs (listings, ELFs, match tables) to `work/`, which is git-ignored because those
outputs contain Sonicware code. Scripts are read-only with respect to devices: nothing here talks to a unit.
Each file's docstring gives its usage; tests are `test_<name>.py` beside it.

```bash
analysis/make_work.sh                                # regenerate work/ (needs firmware/ and tools/tic6x)
python3 -B -m unittest discover -s analysis          # corpus tests skip without firmware/, tools/tic6x or work/
```

## Images and listings

- `mmtd2elf.py`: convert the system image of an update into an ELF32 file (load addresses, entry point).
- `memory_map.py`: loaded sections, run-time initialised data and gaps of an image.
- `init_data.py`: an image's data as it is after `__TI_auto_init`, and its static SYS/BIOS tasks.
- `packets.py`: decode C64x+ fetch and execute packets (compact instructions included) and call-site set-up.
- `ais_extract.py`: the AIS boot-script subset at the start of a flash read; `boot_cache.py`: the cache state the
  bootloader leaves at the jump to SYSTEM.
- `flash_map.py`, `flash_dump_check.py`: account for every byte of a 32 MiB flash read and locate known content.

## Naming

- `rtti_recover.py`: C++ classes, inheritance and vtables from the Itanium-ABI RTTI left in every image.
- `lib_match.py`: TI RTS library functions, matched by object code; `src_match.py`: functions compiled from
  known source (FatFs, for example), matched by body.
- `string_refs.py`: code references to strings and data.
- `func_match.py`, `carry_symbols.py`: match functions between releases and products and carry symbol files
  across ([symbols/](../symbols)); `evidence_audit.py` lists evidence addresses a symbol file cannot explain.
- `platform_map.py`: cross-reference the named symbols of the three products on this board.

## Simulation

- `c6sim.py`: a small concrete C674x simulator that runs one firmware function with modelled memory and
  peripherals; `c6sim_diff.py` checks it against compiled C (`c6sim_diff/tests.c`).
- `sim_boot.py`: a product's state after boot initialisation, so a function sees what it sees in the running app.
- `mmio_trace.py`: record the peripheral register accesses of code run in c6sim.

## Subsystem maps (run in c6sim unless noted)

- Audio: `audio_engine_map.py`, `audio_slot_map.py`, `codec_map.py`, `rec_src_map.py`, `pad_map.py`.
- Panel: `input_map.py` (key matrix and encoders), `panel_map.py`, `panel_rx_map.py` (panel MCU protocol),
  `led_table.py`, `led_callers.py`.
- Storage: `sd_map.py`, `mmc_isr_map.py`, `flash_cmd_map.py`, `cydrums_card_check.py`.
- USB and sync: `usb_desc_map.py`, `usb_audio_map.py`, `sync_map.py`.
- Whole board: `hw_inventory.py` (static: every peripheral an image addresses), `hw_compare.py` (the same
  bring-up steps across the three products), `region_diff.py`, `heap_snapshot.py`.

`ghidra_import.sh` imports a release into a local Ghidra project under `work/` and applies its symbol file
with the scripts in [ghidra/scripts/](../ghidra/scripts).
