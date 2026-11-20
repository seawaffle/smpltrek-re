# Conditional stock startup and UI

The unmodified 3.2.174 SYSTEM returns from its startup routine and reaches the sequencer UI when
two reserved-bus accesses are given a response: the six CPU stores to reserved low memory are
discarded (`--reserved-low-writes`), and the two USB status reads return zero (built in). Both
responses were later measured on the unit: the USB words in device session M1 (2026-11-16, row I5),
the low stores in M2 (2026-11-18, rows W1-W3). The low-store response stays an option because strict
mode is the default for every unmeasured or undefined access. This result is not a claim of
complete hardware fidelity.

```sh
python3 -B emulator/tests/stock_boot.py --conditional
python3 -B emulator/stock.py --cycles 1800000000 \
  --reserved-low-writes \
  --output work/emulator/boot-continuation/result.json
```

The first command verifies a fixed sequence of guest UI operations and writes a report plus raw
frames/PNGs under `work/emulator/stock-boot/`. It requires the CRC-checked local stock image;
its address assertions are pinned to the image hash used by `usb_probe.py`. The second command
captures the sequencer without input. Default stock mode keeps the original null-store fault.

## Boundaries and assumptions

The low-write policy records six original CPU stores without creating RAM below L2 ROM.
The zero-read response was first an opt-in experiment that accepted only aligned 32-bit **CPU reads** at `0x01e0080c` and
`0x01e0084c`, after USB0's PSC clock and PHY are ready. Those reads come from the shared StarterWare
`USBIntStatusControl` legacy external-power/ID checks, which are absent from the C6748 register map.
The newer local PDK `src/musb/musb.c` version omits those checks. That source comparison supports
the port-leftover interpretation; it does not establish the hardware return value.
The M1 bench session of 2026-11-16 (row I5) did: both words read 0 on the unit with no host attached.
The zero return is built in since, without the option; the guards described below apply to the
low-store option.

Each diagnostic read records its actual instruction PC, cycle, address, width and assumed value.
Host/DMA accesses, narrower reads, writes and neighboring addresses still fault. The common guard
requires every EXPMASK bit masked and rejects combiners or direct memory-error routing. After
either kind of reserved access, unresolved error-status reads or exposure of error events fault.
The complete bounded traces fault on overflow. There is no blanket reserved-MMIO zero return.

Reports retain `complete_emulation: false`, `conditional_execution: true`, empty guest-hook lists
and separate `hardware_response_verified` metadata (`false` for the low stores; `true` for the USB words since that session). Firmware code/data, drivers, tasks,
constructors and allocation functions are unchanged and execute as guest instructions.

## Observations on empty card / erased flash

| Original guest boundary | DSP cycle |
| --- | ---: |
| First reserved USB read at `0xc15e2034`, address `0x01e0080c` | 1,333,973,723 |
| Second reserved USB read at `0xc15e2060`, address `0x01e0084c` | 1,333,973,736 |
| USB start returns to `0xc154a828` | 1,371,160,558 |
| Codec unmute returns to `0xc154a840` | 1,371,433,870 |
| Startup returns to `0xc154aa24` | 1,372,170,255 |
| Stable sequencer captured | 1,500,000,000 |

Only those two reserved reads and the six previously documented low stores are used through the
UI test. The codec's 49 actual register writes leave DAC volume registers 43/44 unmuted. USB0 sets
SOFTCONN but has no host peer or traffic. The visible home frame reads NO CARD, 120 BPM and the
track/scene grid; its raw-frame SHA-256 is
`4ac7d90cd81d4a25caf37cb16c1300ec62a1fba79222d2489e75338095e0d4bc`.

The integration then presses/releases PLAY and STOP, holds FUNC while pressing HOME, rotates VALUE
through all four quadrature phases, opens METRONOME, changes OFF to ON and returns home. The guest
held-switch word, current/modal controller pointers, setting word and each transmitted frame are
observed without modifying them. By cycle 2,180,000,000 it has produced 42 frames, exchanged
505,410 audio words in each direction and dispatched 8,080 interrupts. Audio has no modeled clock
discontinuity or under/overruns; this empty-project digital output is still silent.

The follow-up receive fixture sends `A1 01 02 03 04 05 06`, `B3 00 08`, then `B3 00 00` through
UART1, one completed byte every 8000 DSP cycles (stock's 8N1/divisor-25 configuration). The original
UART ISR, receive task and `ADControllerUART::parse` store all six information bytes at
`0xc15019d0 + 70`, then channel 3 pressure 1024 and release 0 at `+42`. No parser is called directly
or hooked. These are explicitly synthetic input fixtures, not an automatic MCU reply or a physical
MCU version. The host API rejects integers, preventing Python's `bytes(integer)` conversion from
silently injecting a zero-filled stream. Automatic panel replies (`A1`) are not modelled; the
continuous analogue report stream was added on 2026-11-17 (emulator README, "Panel MCU stream").

## GPIO input correction

PLAY (key 22) exposed a bug in the earlier ideal matrix: column sensing incorrectly required a
GPIO pin-mux selection. [SPRS590G section 3.6](https://www.ti.com/lit/ds/symlink/tms320c6748.pdf)
keeps the input pad connected to every sharing peripheral regardless of PINMUX. Stock leaves
GP3[9], column 6, at its tri-state reset mux, so that column must still be readable by GPIO.
The model gates **row output drive** on mux/direction, but never gates column or GP5[10]
input sensing on mux. Independent regressions check this reset-mux PLAY column, the separate
active-low key, row selection/direction and GPIO edge delivery. Switch bounce, ghosting and
electrical contention remain outside this ideal-switch model.

The source/synthetic suite then passed 117 tests, including the default strict USB faults and
diagnostic trace/width/host/DMA/mask guards.

## Related results

The [project persistence regression](storage-investigation.md) automates original UI creation and
save of Project002 and a cold boot that loads its saved 121 BPM tempo. Nonzero stock output is in
[the audio investigation](audio-investigation.md), and speed in
[the performance notes](performance-investigation.md). The panel MCU's `A1` reply, USB host traffic
and the remaining device and CPU details listed in the emulator README are not modelled.
