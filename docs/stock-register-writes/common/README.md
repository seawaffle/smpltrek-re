# The three products compared: SmplTrek 3.2.174, Lofi-12 XT 1.5.205, CyDrums 1.1.84

The same register tables as [the SmplTrek capture](../README.md), for the three products under one product-neutral
scenario, and a diff of each against SmplTrek ([diff.md](diff.md)). Captured 2026-11-24 in the emulator
(`emulator/stock_register_capture.py --common <product>`); every row is emulated, nothing measured on a unit.

**The scenario.** The flash is erased. SmplTrek and Lofi-12 XT get a blank 32 MiB card; CyDrums gets a 128 MiB card with the contents it ships with (`CyDrums_folder.zip`), because with a blank card it behaves differently (below). The phases:
- `boot`: 6 s, then CLR;
- `attach`, `bus_reset`, `enumeration`;
- `bulk_out`: a USB MIDI note on and off, channel 1;
- `interface_on` and `interface_off`: SET_INTERFACE 1 and 2 to alternate setting 1 and back;
- `suspend` and resume;
- `detach`;
- `power_off`: the power key held 3 s.

The product menus (MIDI settings, REC SRC, card-reader mode) are left out, because they differ between products.

**Table differences.** The tables are built as SmplTrek's (`stock_register_tables.py --product <p> --collapse-sd`), with two differences:
- In `sd-commands.csv`, runs of more than four data commands (block reads and writes, CMD12, CMD13) are one summary row with the commands counted.
- In `mmcsd.csv`, card traffic after the first mount is one summary row per phase.

In Lofi-12 XT and CyDrums, `function` is the nearest named function below the PC plus an offset, marked `?`: only SmplTrek has a list of every function start, so the PC may lie in an unnamed function after the named one.

**How the diff works.** `stock_register_diff.py` compares, phase by phase, what a driver does: the access, the register and the value (for the codec, page, register and value; for SD, command, argument, answered). PCs, counts and timing are left out.

## Result

| Table | Lofi-12 XT 1.5.205 | CyDrums 1.1.84 |
|---|---|---|
| usb0 | identical in every phase | identical except one extra endpoint-0 FIFO read during SET_INTERFACE |
| i2c0 | identical | identical |
| codec | identical | identical |
| mcasp-edma | the audio block size and buffer addresses (below); otherwise the same writes | the same as Lofi-12 XT |
| mmcsd | the DMA buffer addresses; the card set-up is the same | the same, plus what the larger card changes (its CSD, the first file's sector) |
| sd-commands | the first mount is identical; what follows is the product's own file work | the same |

The differences in detail:
- **Audio block.** SmplTrek's McASP PaRAM sets move 256 words per block (A_B_CNT 0x01000004, first transfer 255), which is 128 stereo frames. Lofi-12 XT's and CyDrums' move 192 words (0x00C00004, first transfer 191), which is 96 frames. That matches the block sizes in docs/01-platform-map.md. Every other McASP and EDMA write is the same. The buffers sit at different L2 addresses, and the interrupt handler's PaRAM link reads come in a different order because the timing differs.
- **Card work.**
  - Lofi-12 XT on a blank card reads and writes a lot at start-up: 10,162 single and 3,480 multi-block reads, 797 single and 3,480 multi-block writes. It does a little more at power-off.
  - CyDrums streams from its card all the time, in every phase.
  - SmplTrek on a blank card does 72 single-block reads, 96 single-block writes and 2 multi-block writes.

  None of this changes the controller's set-up or command sequence, only how much traffic follows.
- **CyDrums' extra FIFO read** in `interface_off` is its USB class code, not the driver. The usblib driver writes are identical.

So the drivers (usblib, the codec and I2C functions, the McASP/EDMA set-up and the SD protocol layer) do the same register work in the three products, phase for phase. The products differ in the audio block size and in what they do with the card.

**CyDrums with a blank card** (separate capture, `common-cydrums-blank.json` in work/, not tabulated):
- During start-up it first comes up in composite mode (POWER = 0x40), then reinitialises USB0 for mass storage: POWER = 0x20, then 0x60 (high speed), MODE = 3 (generic RNDIS), and the CPPI set-up (linking RAM, descriptor region, RX channel 1, TX channel 0). That is the same sequence as SmplTrek's card-reader mode.
- At the host's bus reset it reaches the CPPI queue manager, where the emulator stops.
- So with no content on the card, CyDrums 1.1.84 offers itself as a card reader by itself (emulated; what its screen says was not looked at).

Regenerate (needs firmware/; each capture takes several minutes, and the Lofi-12 XT and CyDrums raw files are about
1 and 2 GB in work/):

```bash
for p in smpltrek lofi12 cydrums; do python3 -B emulator/stock_register_capture.py --conditional --common $p; done
python3 -B emulator/stock_register_tables.py --raw work/register-capture/common-smpltrek.json --product smpltrek \
    --collapse-sd --output docs/stock-register-writes/common/smpltrek-3.2.174      # likewise lofi12, cydrums
python3 -B emulator/stock_register_diff.py docs/stock-register-writes/common/{smpltrek-3.2.174,lofi-12xt-1.5.205,cydrums-1.1.84} \
    --output docs/stock-register-writes/common/diff.md
```
