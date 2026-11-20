# Stock project persistence

The unmodified SmplTrek 3.2.174 SYSTEM creates, saves and cold-loads a project through its
original GPIO-driven UI, FatFs and MMCSD/EDMA drivers. It runs with the low-store option and the
built-in USB status response, both later measured on the unit (emulator README, "Bench results
applied").

```sh
python3 -B emulator/tests/stock_project.py --conditional
```

Outputs are under `work/emulator/stock-project/`. `input.img` is an empty synthetic 2 MiB
FAT12 SDSC card. `private.img` is the private guest-modified backing. The create/reload folders
contain execution reports and the actual display frames at each UI stage. No proprietary bytes
or generated cards are committed.

## Original guest path

1. Boot with the private card and dismiss stock's initial format-recommendation message using CLR.
2. Press PROJECT, open SELECT/NEW, rotate VALUE to empty slot 002 and confirm. Select NO at the
   save-current-project question. Wait for the original project creation and DONE message to finish.
3. Open TEMPO with the right selection button. Rotate encoder A once: the guest changes 120.0 to
   121.0 BPM. Return home, choose PROJECT > SAVE and confirm YES.
4. Inspect exported backing independently. The guest created `/SmplTrek/Project/Project002/Config`,
   5,924 bytes with the STPJ header, and selected Project002 in `Project.lst`. The CONFIG tempo word
   at byte 36 is 1210, matching the original `project_get_tempo_x10` RAM word at `0xc1500cf4`.
5. Start a fresh CPU/board with exported backing. Stock selects Project002 from its own list and
   loads 1210 into that RAM word. Its CONFIG data is byte-identical to the saved file. This checks
   persistence rather than just observing a directory or a screen label.

The first phase completes at cycle 3,260,000,000 with 97,352 bytes read and 56,320 written. The fresh
boot reaches the restored project by cycle 1,500,000,000 after reading 239,176 bytes and writing none.
Both retain the exact six known low stores and two reserved USB reads, no guest hooks and zero
modeled audio under/overruns. The original and exported input files remain unchanged by execution;
all guest modifications occur in private memory.

## Independent inspection and limits

`fat_image.py` is a read-only FAT12/16 superfloppy inspector. It decodes BPB geometry, cluster
chains, short/VFAT long names and file sizes without using the guest filesystem or host FatFs.
Malformed chains, disagreeing FAT copies and bad long-name sequences/checksums raise diagnostics.
Source-only tests compare multi-cluster file data against independently built FatFs cards in both
formats and exercise malformed metadata. The inspector does not implement guest file operations,
write cards, or support FAT32/MBR layouts.
The full source/synthetic suite of the time passed (121 tests).

`stock_session.py` advances the real guest, drives GPIO keys/quadrature phases and reads observations.
It never substitutes a constructor, allocator, driver or task, directly invokes a guest function,
or changes guest RAM/registers to navigate the UI. The address watches and assertions are pinned
to the CRC-checked stock hash used by `usb_probe.py`.

This regression does not establish physical card timing, power-loss recovery, arbitrary filesystem
support. Nonzero stock audio is in [the audio investigation](audio-investigation.md).
