# Compiled C674x execution core

The C++ backend executes the C674x instruction set with persistent CPU state and sparse mapped
memory. Python invokes bounded runs and fills the decode cache on misses. Instruction execution,
register dependencies, branch delays, memory access and cache validation stay inside C++.

It supports function-level tests, user-supplied programs and the unmodified stock firmware, which
starts up to its sequencer and runs its UI with the low-store option (strict mode stops in USB
setup; see the [emulator README](../README.md#stock-runs-in-detail)). Unsupported behaviour stops
with a diagnostic.

## Run stock SYSTEM initialization

```sh
python3 -B emulator/stock.py --cycles 250000000 --until-frame
```

The default input is the local `firmware/smpltrek/SmplTrek v3.2.174.zip`. No proprietary bytes are shipped
with the emulator or its synthetic tests. The runner checks the container CRCs and section hashes,
loads its entry and sections unchanged, and maps DDR, L2, L1P/L1D and shared RAM. DSP-local addresses
alias their global RAM. It assumes clocks/DDR established by the bootloader, with explicitly modeled
cache and SYSCFG handoff state; it does not execute the bootloader or ROM.

The runner uses real guest instructions, including the stock runtime initializer and constructors.
There are no allocator, task, constructor or driver function hooks. Optional hash-matched symbols
only supply breakpoint labels. Reports include source/core hashes, reached checkpoints, final CPU
state, recent MMIO and limitations. Unknown device accesses stop explicitly.

The runner initially holds the power key for 600 guest milliseconds, then releases it. Stock's
power-on check samples this GPIO while sleeping through SYS/BIOS. `--power-held-ms 0` reproduces
the released-key path; it continues servicing input/timer tasks without entering normal startup.

3.2.174 returns from runtime initialization at cycle 6,968,245 and reaches its task entry at cycle
6,978,114. A held-key run completes the stock power-on check, initializes the OLED and delivers its
SmplTrek splash through real guest framebuffer code, modeled EDMA and clocked SPI transfers. The
raw 8192-byte frame and rendered PNG are exported with the report. First-frame arrival records an
exact device-cycle timestamp; stopping happens at the end of the current host slice.

A released-key run reaches 100 million cycles with 251 dispatched interrupts and repeated stock
key scans. These are emulator-profile counts, not measured hardware timing or proof of full boot.
The optional local-corpus smoke check reproduces runtime/task entry, interrupts and key scanning:

```sh
python3 -B emulator/tests/stock_smoke.py
python3 -B emulator/tests/stock_smoke.py --first-frame
```

## Run a user-supplied program

`python3 -B emulator/custom.py --elf program.elf` runs a linked C6000 ELF on the same board model
(see the emulator README's "Custom DSP programs"). Board handoff profile 1 (`--handoff gpio`, the
default) inherits the GPIO functional clock enabled, for programs that drive the power hold before
their other initializers; profile 0 (`--handoff stock`) is the stock SYSTEM model. ELF allocations
are checked against pre-mapped board RAM, including required execute permissions. With `--card`, a
private copy of an SDSC image is inserted; input backing stays unchanged and `--export-card` saves
private mutations. Raw audio capture is a digital boundary with unverified physical channel routing.

Requires host `g++` with C++20 support and the existing DSP binutils under `tools/tic6x/bin`.
Generated code, shared libraries and reports stay in `work/emulator/`.
`tune_core.py` optionally collects GCC execution counters and compiles an optimized host core.
Only matching source/compiler/ABI/flag/counter hashes permit profile use. An activated profile
applies to subsequent CPU sessions; source changes select the current portable build instead.
`SMPLTREK_CORE_PGO=off` disables selection, while a bundle path requires that exact compatible
profile. Both builds retain the same C ABI, original guest execution and strict MMIO. Builds keep
IEEE arithmetic and explicitly disable FP contraction; no fast math or guest hooks are enabled.
See [the workflow and measurements](../performance-investigation.md#gcc-profile-guided-compilation).

```sh
python3 -B emulator/core_run.py
python3 -B emulator/core_run.py --slice-cycles 1
```

The source-built C674x assembly fixture:

1. Copies 32 executable bytes into a separately mapped RAM page using guest LDW/STW instructions.
2. Branches into that page and returns **42**.
3. Replaces those RAM bytes with a second function, resets the CPU and returns **99**.

The initially empty destination is decoded before the copy, so this also checks invalidation of an
existing instruction cache. There is no separate app ELF loaded at the destination. Large execution
slices and one-cycle slices produce the same deterministic results: the copy/execute path takes
124 cycles and the replacement function takes 7 cycles for this fixture.

The report is `work/emulator/core-demo/result.json`. It records the compiled core, decoder and
input hashes, results and a warm ADD/branch/NOP benchmark. The benchmark excludes initial decoding
and is not a full firmware performance measurement.

## Run a linked ELF function

```sh
python3 -B emulator/core_run.py \
  --elf work/emulator/core-demo/integer.elf \
  --entry integer_mix \
  --map 0x30ff0000:0x10000:rw \
  --register b15=0x30fffff8 \
  --register a4=0x12345678 \
  --register b4=0x87654321 \
  --slice-cycles 1
```

The integer ELF is created by the optional DSP-GCC test below, or explicitly with
`core_demo.build_fixture(integer=True)`. It contains only this directory's C fixture. The example
returns `A4=0xb480a6ae` after 84 cycles.

The entry defaults to the ELF entry point; `--entry` accepts a symbol or an integer address.
Additional RAM requires explicit `--map BASE:SIZE[:rwx]` options. The harness installs a caller return
sentinel in B3 by default; `--no-return-sentinel` disables it. `--cycles` bounds total guest cycles;
`--slice-cycles` limits each native call. A JSON report is saved on a normal stop or an execution
fault. Missing instructions and unmapped MMIO stop with the PC, instruction and cycle count.

## Interfaces and execution model

- [`core.h`](core.h) defines a fixed-width C ABI with version checking. No Python objects cross it.
  [`cpu.py`](../cpu.py) provides memory, register, reset, ELF and bounded-run methods.
- `c6_key_input`/`CPU.key_input` operate ideal external key switches, leaving guest scanners intact.
  GP2[0..5] drive six rows, gated by GPIO output mux and direction; GP3[1..6,9,11] supply columns.
  SPRS590G 3.6 keeps peripheral input paths live regardless of PINMUX. Column inputs and GP5[10]
  therefore require no GPIO output mux; this matters for stock's reset-mux PLAY column GP3[9].
  Key 4 instead pulls GP5[10] low independently of row selection. Key changes, row output changes
  and pin mux changes propagate configured GPIO edges. Bounce, ghosting and settling are absent.
- ELF32/C6000 allocated sections populate zero-initialized sparse RAM pages. Pages containing code
  are executable; ELF allocation pages are writable RAM. Unallocated pages remain unmapped. This is
  a harness memory profile, not a complete C6748 board memory map or permission model.
- Host writes initialize or replace RAM, including read-only debug mappings. Guest stores must
  satisfy write permissions. Reads, execution, overlap, overflow and alignment checks are explicit.
- Sparse RAM uses two direct pointer indices: 1,024 optional groups of 1,024 optional pages.
  Missing backing reads as zero after permission checks; aliases retain their 32-byte alignment.
  Pages and their fetch-version counters stay stable across RAM growth and CPU reset. Stores copy
  and invalidate each fetch span using one page lookup. Original code, MMIO and DMA retain the
  existing execution and permission rules. Paired stock slices measured 9.5% more startup
  throughput and 3.7% more nonzero WAV preview throughput, with exact state agreement; see
  [measurements and discarded experiments](../performance-investigation.md#direct-ram-page-lookup).
- Fast-forward: when the CPU state recurs at a branch landing with no net RAM change, MMIO, TSCL
  read or interrupt, the core adds whole periods to the cycle and packet counts up to the next
  device event, and runs an event inside the next period early when the loop's RAM is constant.
  State at every `c6_run` boundary equals every-cycle execution. `c6_fast_forward` switches it;
  `c6_fast_forward_stats` reports it; guest profiling and eager polling disable it. See
  [the proof conditions and limits](../performance-investigation.md#fast-forward-of-repeating-guest-state).
- Decoded instructions keep resolved source pointers and, for common forms, a compact `Micro`
  record executed by `issue_fast` in the same read-then-commit order as the general switch, which
  still handles every other form. The common forms include moves from control registers that read
  as their stored value and to those that only hold what is written, the `TSCL` read, writes to
  CSR and IER, `DINT`, `RINT` and `ROTL`. `c6_micro(machine, 0)` turns the lean path off, so that
  the two can be compared. Wholly ordinary RAM pages are reached through direct tables;
  device, partial and unmapped pages keep the checked path. Delayed results use a ring by due cycle.
- `c6_uart_sent` returns the bytes a UART finished transmitting (the most recent 4,096). The peer
  stays silent; this only observes, for example, stock's panel LED commands on UART1.
- All instructions in a packet read registers before the packet's register results are committed.
  Loads have four delay slots; supported 16-bit multiplies have one; supported 32-bit multiplies
  and MVD have three. Protected loads stall subsequent issue for their result.
- Saturation flags: `CSR.SAT` and the functional unit's `SSR` bit are set one cycle after a
  saturating instruction writes a clipped result (`SADD`, `SSUB`, `SSHL`, `SAT`, `SMPY`, `SMPYH`,
  `SMPYHL`, `SMPYLH`, `SMPY2`). The packed saturating forms leave both alone, as the manual says.
  The instructions GCC needs beyond the stock firmware's (half-word multiplies, saturating and
  packed arithmetic, `BITR`, `SWAP4`, `SHLMB`, `SHRMB`) run in the general interpreter path only;
  a packet holding one is not compiled into host code.
- Branches take effect after five delay slots. Multiple branches can remain in flight. A taken
  branch ends a multi-cycle NOP at its scheduled cycle, including BNOP counts larger than five.
  Predicated-false BNOP still consumes its specified wait, and so does a predicated-false ADDKPC
  with a NOP count (SPRUFE8B 3.8.10; until 2026-11-17 the ADDKPC's wait was dropped, which made
  GCC's integer division helpers return twice for non-negative operands). The reference simulator
  had the same fault and the same fix.
- CALLP retains its implicit wait and explicit A3/B3 link destination across slices. Pending
  loads, multiply results, branch targets and remaining wait cycles survive budget exhaustion.
- SPLOOP/D/W, SPMASK and SPKERNEL preserve loop-buffer and overlapping epilog state across slices.
  Loop control is decoded from original bytes even when the kernel crosses a decode-page boundary.
- An SPLOOPW ends at a stage boundary when its condition register was zero (or non-zero, for an
  inverted predicate) at the start of the cycle 4 before that boundary (SPRUFE8B 7.10.2), not on its
  current value. TI's compiler sets the register exactly 5 cycles ahead of the boundary that must
  act on it and lets the later stages of the last iterations run meanwhile.
- Nested loops reload the buffer (7.9.6): at an SPMASKR in the post-loop code, or with the post-loop
  code itself when the body ends in SPKERNELR. RILC = 0 at the reload point skips the invocation:
  nothing issues until its last stage boundary, where the reload condition is judged again (taken
  here as the predicate 4 cycles before that boundary; the manual does not name the cycle). Still
  refused with an error: the reload condition of a nested loop that ran fewer than 4 cycles, a
  reloaded invocation that ends before its body is loaded again, an SPMASKR after an SPKERNELR
  loop, and SPKERNELR outside a loop body.
- Floating-point operations include single precision, conversions and double precision with staged
  high-word source reads and staggered low/high results. Denormals flush to signed zero; output NaNs
  use TI's canonical encodings. Reciprocal estimates (`RCPSP`, `RSQRSP`, `RCPDP`, `RSQRDP`) use the top eight mantissa
  bits of the input and round the exact result to nearest at eight bits, as measured on the unit
  (device sessions M2 and M3).
- Stores become visible at issue. Memory is coherent; physical caches and bus latency
  are not modeled. TSCL starts disabled, is enabled by its first write, and latches TSCH on reads;
  repeated TSCL writes do not reset the timestamp.
- Controllers advance at their next event deadline, with invalidation on MMIO and external input.
  Guest instructions and CPU cycles still execute normally. PSC clock transitions preserve MMC's
  fractional/stopped-clock state. Packet issue reuses scratch vectors without changing write order.
  `CPU.board_eager_polling()` retains the every-cycle device reference; `performance.py --eager-board`
  measures that path. Scheduled and reference runs have identical CPU/audio/OLED state at cycle
  350 million. Sharing RAM translation/page lookups and retaining direct fetch-version counter
  pointers subsequently improves a repeated benchmark from 0.0873× to 0.1100× real time, with exact
  CPU/audio/OLED agreement at cycle 400 million. Sparse page growth and aliased code rewrites retain
  correct invalidation.
- A tagged 4096-slot fetch table points into stable packet-map nodes. Every hit retains execute
  permission and RAM-version checks; collisions fall back to the owning map. Packet replacement
  updates the same node, including loop-control classification. Loop/epilog assembly reuses packet
  storage and ordinary issue skips scans for absent loop control. With strict-FP `-O3` and LTO, the
  nonzero-input benchmark improves from 0.1115× to 0.1312× on this host (about 18%), with identical
  CPU/audio/OLED state at cycle 400 million (the speed history is in
  [the performance notes](../performance-investigation.md#throughput-history-2026-11-14-to-2026-11-15)).
  `profile_native.py` samples host PCs outside the guest ABI in a dedicated Linux process. Its
  reports retain build hashes, source/inline attribution and actual timer granularity. Before these
  changes, 1,166 samples attributed about 58% to issue/run-loop work, 12% to tick and 4% to devices;
  guest decoding was absent. Sampling is statistical, and kernel timer rounding affects resolution.
- Ordinary packets now construct loop state only when their decoded opcode actually starts a loop.
  Empty delayed-write/branch vectors do not append, and wait cycles skip absent epilog work. Five
  warmed slices improve from 0.1373× to 0.1495× real time (8.9%), with identical CPU/audio/OLED at
  cycle 500 million. The complete stock WAV regression and all 125 source/synthetic tests pass;
  every original instruction, pending result, branch and device event retains its modeled cycle.
- Single unconditional constant NOPs cache their wait count alongside decoded instructions. A RAM
  change invalidates that classification with the packet. After issue, eligible wait cycles advance
  to the earliest queued result/branch/IRQ, device deadline, wait end or host budget. The final
  boundary uses normal tick ordering. Loops, draining epilogs, late FP source reads and interrupt
  entry retain ordinary ticks. `board_eager_polling(True)` also retains every-cycle wait processing;
  one-cycle slices provide a second reference. Four independent regressions cover pipeline/TSC
  boundaries, timer interrupt entry, strict NOP diagnostics and real-byte aliased replacement.
  Five warmed slices now reach 0.1595× real time, up 16.1% from the pre-dispatch baseline. All
  129 source/synthetic tests and the full stock WAV regression pass with exact baseline output.
- Reset clears CPU/pipeline state and retains RAM and decoded packets. Closed sessions reject
  further access. Breakpoints stop before issue. Save/restore snapshots remain future work.
- `CPU.profile_guest(1009)` enables optional jittered packet samples and exact cycle-class/loop/
  wait/interrupt counters; zero freezes the window and reset clears it. `CPU.guest_profile()` returns
  a bounded snapshot with original PCs, using the SPLOOP control PC for loop packets. Profiled and
  unprofiled runs retain identical guest state. The disabled path is a separate compile-time run
  specialization with no profiling counter work in its hot loop. Fixed-width ABI additions leave
  the existing state/IR layouts unchanged. See [the measurements](../performance-investigation.md).

The optional board model supplies interrupt event latches/muxes, coherent cache maintenance, protected
SYSCFG writes, pull configuration, dual-32-bit timer counting/period events and PSC module transitions.
PSC completion takes a deterministic functional 16 cycles. Each timer's 1:2 half raises its own DSP event (4, 40, 25, 86 for timers 0-3). Timer rates assume a 372 MHz DSP, 24 MHz timer0/1 and
186 MHz timer2/3 input. Maskable interrupts select the lowest enabled pending CPU interrupt, honor
GIE/NMIE and branch delay slots, save IRP/ITSR, and enter the ISTP vector with nine cycles of overhead.
ISR/ICR updates have one delay slot; incoming events take precedence over clears. `B IRP` restores
TSR and the shared CSR bits. Pending instructions finish during entry. A multi-cycle NOP (`IDLE`
included) is interrupted like any instruction: after its first cycle the return address is the
next packet's and the rest of it is dropped (SPRUFE8B 5.5.4). Interrupts wait for a draining
epilog to complete.

An interrupt during a hardware loop follows SPRUFE8B 7.13. It is accepted on a stage boundary once
the body is loaded, the termination condition is false, the first 3 cycles of an SPLOOPD or SPLOOPW
have passed and, for SPLOOP and SPLOOPD, ILC is at least the number of loading stages. The loop
then starts no further iteration, the started ones finish with program fetch off, and the interrupt
is entered with IRP = the SPLOOP packet and ITSR.SPLX set. When `B IRP` restores SPLX, that packet
executes nothing, SPMASKed instructions do not run again, an SPLOOPD tests and counts like an
SPLOOP, and the loop is piped up from the ILC it had. An SPLOOPW whose condition ends it while it
drains goes idle and the interrupt is taken at the packet after its body (7.10.3). Differences from
the manual: an invocation started by a reload is not interrupted (the interrupt waits for its end),
interrupts are not blocked in the 2 cycles before an SPLOOP packet, and TSR.SPLX does not read as 1
while a loop runs. `c6_loop_interrupt_count` counts the interrupts entered this way.

GPIO provides directions, output latches/set/clear, external input levels and rising/falling bank
interrupts. The default inputs have released keys, encoder detents, no SD card, USB/external power
and a configurable power key; no physical jack/switch polarity is claimed beyond the profile.
EDMA CC0 implements configuration, PaRAM, shadow-region access masks/aliases, A/AB synchronization,
signed B/C indices, count reloads, null/link reloads, software triggers and SPI device events. Completed
transfers set IPR and signal the region-1 completion interrupt through event 8. DMA uses the mapped
bus and normal executable-memory invalidation; trace PC `0xfffffff0` marks DMA accesses. Transfers
are functional bus operations with no separate TC/bus latency model. QDMA,
static descriptors, early completion and chaining remain explicit unsupported modes. Constant-source
and constant-destination transfers support one 32-bit word per array (FWID=2, ACNT=4, a 32-byte-aligned
port), ignoring indices on the constant side. Other FIFO widths/bursts fault explicitly.

SPI0/1 provide reset, configuration, pin readiness, a shift register and transmit/receive buffers,
clocked completion, loopback and receive-read side effects. Upper control-byte writes do not send
data. Missing SPIPC0/pinmux setup leaves queued transfers waiting. The OLED endpoint accepts the
documented stock B3/81/A0/AF stream and captures raw frame bytes. Its controller identity/additional
commands remain unverified. SPI delay counters, parity,
LSB-first and interrupt dispatch are incomplete.

SPI0 connects two independent 16 MiB NOR profiles, initially erased (`0xff`). Commands `03/05/06/04`
provide sequential reads, status, WREN and WRDI; `02/20/52/D8` provide page programming and aligned
4/32/64 KiB erases. Mutations begin at CS release, require WEL, expose WIP, clear WEL on completion
and change private sparse backing only. Programming clears bits and wraps within a 256-byte page;
payloads over 256 bytes fault. `9F` answers `C2 20 18` on both devices and `15` answers `0F` on device 0 and `07` on
device 1, as the unit did (bench M1, step C1); the status byte's protection bits that device 0 showed there (`0C`)
are not modelled, and nothing is write-protected. Unknown commands, status
protection/configuration writes and multiple asserted selects fault explicitly. Recognized commands
other than status are ignored while busy, following NOR behavior. This generic profile uses the
common semantics in the [Macronix reference, sections 9-1/2/7/10/20-24](https://www.macronix.com/Lists/Datasheet/Attachments/8373/MX25L12835F%2C%203V%2C%20128Mb%2C%20v1.1.pdf),
not a confirmed part identity. Functional program/erase delays are 1/50/200/400 ms, respectively;
they are deterministic assumptions. The raw backing C API initializes/exports media, never guest
functions. `stock.py --flash` copies a 32 MiB input and `--export-flash` saves the private state.

With a held power key, stock OLED initialization reaches cycle 195,964,885. The first-frame smoke
check passes with a readable SmplTrek logo. Continuing completes MMC/SD controller initialization,
reaches audio hardware setup at cycle 216,387,122, and reads the two settings sectors from SPI NOR
device 1 through paired SPI0 TX/RX EDMA. SPI0 events use channels 14/15 and SPI1 uses 18/19, as in
the C6748 datasheet table 6-12 and local StarterWare `include/c674x/c6748/edma_event.h`.
I2C0 begins at cycle 217,211,195; the stock ISR completes 40 codec writes (80 data bytes and 40
STOPs, zero NACKs), then configures McASP0 starting at cycle 221,531,904. The first captured slot
completes at cycle 221,537,625 and the original `audio_render_main` enters at cycle 222,522,330.
At 350 million cycles, 33,152 words per direction have passed through McASP/EDMA with zero
under/overruns; the splash is the only complete display frame by then.
The guest then waits until its three-second startup deadline (cycle 1,333,214,927). Continuing
reaches a null-pointer byte store at address `0x00000008`, PC `0xc162a4f0`, cycle 1,333,972,500.
At that fault the audio ring has exchanged 287,080 words per direction without under/overruns.
USB audio class setup reads a null device-descriptor pointer from `0xc16ecfd4 + 48`. The copy-table
file-format decoder independently produces the same null pointer, and all 147 guest constructors
leave it unchanged. RAM at address 0 is deliberately not mapped.
The [USB investigation](../usb-investigation.md) shows that composite setup updates a valid
descriptor before audio setup executes standalone descriptor fixups through a null class pointer.
The same initialized fields/store pattern occurs in three stock releases. Its cycle-stepped probe
keeps strict faults by default.
The `--reserved-low-writes` policy logs/discards CPU stores below L2 ROM without creating RAM or
allowing reads/fetches, host/DMA writes or unresolved error observations; such stores do nothing on
the unit either (device session M2, rows W1-W3). See the investigation for its exception-mask/routing
guards. The USB0 disconnected control plane implements wrapper
reset (16 functional DSP cycles), source/mask/set/clear/EOI interrupts, core address/POWER/enables,
idle status and CFGCHIP2 PHY clock-good (64 functional cycles, internal 24 MHz reference).
Software SOFTCONN produces no host traffic. Indexed endpoints, FIFOs, host/OTG, CPPI DMA and unknown
MMIO remain strict faults. `tests/stock_smoke.py --usb-reset` verifies original reset/PHY polling.
The next accesses are the shared StarterWare `USBIntStatusControl` reads at `0x01e0080c` (PC
`0xc15e2034`) and `0x01e0084c`, a Stellaris external-power and ID status pair that the C6748
register table does not define. The M1 bench session (2026-11-16, row I5) measured both words as 0
on the unit with no host attached, and stores of 0 to the matching disable words `0x01e00808` and
`0x01e00848` as having no effect. That is the model's built-in behaviour: the accesses are counted
and logged. Host/DMA, byte/halfword reads, non-zero stores and other addresses still fault. (Before
the measurement this was an opt-in `--usb-reserved-status-zero` hypothesis with guards; it no longer
exists.) See "Bench results applied" in the emulator README for this, the misaligned-access rule,
EMIFA stores and the opt-in `--reserved-low-reads`.
With the low-store option, original start-up returns and stock renders its sequencer screen.
`tests/stock_boot.py --conditional` validates startup/codec unmute and GPIO-driven UI interactions;
reports classify this as conditional execution.
`stock_smoke.py --startup-delay`
stops at the preceding verified checkpoint. `stock.py --cycles 1500000000` reproduces the strict fault.
The DDR controller's read-only revision/status registers
support SYS/BIOS's dummy write/read cache barrier under the coherent-memory model.

MMCSD0 supplies the chapter-25 register reset values, command/reset state, clock divider/DIV4,
clock stop and PSC gating, response registers/timeouts and INT0 event 15. The default socket is empty;
commands requiring a card response time out after programmed TOR clocks (zero waits indefinitely).
Status reads clear all addressed flags, including DXRDY/DRRDY, without draining FIFO data. Retaining
DXRDY previously trapped the stock card-present ISR in its status polling loop. The fix follows
section 25.2.10.1 and has a regression checking a second status read returns zero with the FIFO full.
While data is received the model asks for an event only at a byte that ends a block, changes
DRRDY or fills the FIFO; the bytes between are clocked in when it is next consulted, as every
register and DMA access does first. A test compares interrupt cycles, status words and data with a
run polled every cycle, at both FIFO thresholds.

Optional private SD 2.0 SDSC backing accepts power-of-two 2 MiB to 1 GiB images, synthetic CID/CSD with
CRC7 and actual capacity, native 1/4-bit bus width, byte addresses and block PIO/DMA. CMD0/2/3/6/7/8/
9/10/12/13/16/17/18/24/25/55 and ACMD6/23/41/51 form the supported subset; MMC/SDIO probes time out,
known illegal card commands return card status, and unimplemented operations fault explicitly.
The 64-byte FIFO supports 32/64-byte thresholds and 1/2/3/4-byte access widths. Wire bytes advance
at the programmed card clock; full receive/empty transmit FIFOs pause transfer. TRNDNE precedes
CRC completion/DATDNE; each completed write block affects private backing after its functional busy
interval. MMCNBLC counts remaining blocks; multiblock card state persists until CMD12. Media size,
state, bus width, command history and read/write counts are exposed through the fixed C ABI.

Pinmux and functional clock are required for card traffic. Configuration registers stay accessible
with the clock disabled. Responses assume an eight-clock gap; write busy takes 32 clocks after the
CRC/end clocks. Electrical edges, CRC-error injection, real flash timings, hotplug, SDHC, high speed,
erase, SDIO, endian/edge modes and stream transfers remain unsupported. CMD6 check/switch status
supports default functions and reports unsupported selections as 0xF. Combined DMATRIG/data commands
enable EDMA RX16/TX17 events, transmit prefill, 32/64-byte request credits and final short RX flushing.
DMATRIG reads as zero. Standalone trigger writes and stopping during CRC/programming remain unsupported.
The guest's AB-synchronized PaRAM transfers use ordinary increment addressing with zero index on
the controller side; no new EDMA FIFO mode or host driver hook is needed.

Card-present stock completes identification, SCR, speed negotiation, FAT reads and directory
creation, including multiblock writes and CMD12. `stock_smoke.py --sd-card` independently decodes
the exported FAT directories. The generated HELLO-card run reads 36,936 bytes, writes 30,208 bytes,
completes the startup delay and reaches the strict USB null-descriptor stop at cycle 1,333,974,292.
Register behavior follows
[SPRUH79C chapter 25](https://www.ti.com/lit/ug/spruh79c/spruh79c.pdf); local StarterWare
`include/hw/hw_mmcsd.h` and the read-only open driver provide cross-checks.

I2C0 implements 7-bit, 8-bit, nonrepeat master transmit/receive, the transmit holding/shift registers,
repeated START, address/data ACKs, NACK/ARDY, STOP, receive backpressure, reset, masked interrupt
event 36 and ICIVR priority/acknowledgment (including XRDY/RRDY). ICSTR reads retain flags;
write-one-to-clear and byte-lane effects are explicit. ICCNT remains the programmed value while an
internal counter decrements. Its 24 MHz input and ICPSC/ICCLKL/H dividers schedule each nine-clock
address/data phase in half-DSP-cycle units; START is folded into the address phase and STOP takes
one serial clock. Unknown addresses or missing I2C pinmux produce a clocked address NACK. Clock
stretching by an external slave, arbitration, slave/10-bit/repeat/loopback/early-NACK modes, DMA,
and GPIO pin mode remain unsupported. Register semantics follow
[SPRUH79C chapter 21](https://www.ti.com/lit/ug/spruh79c/spruh79c.pdf), cross-checked with local
StarterWare `drivers/i2c.c` and `include/hw/hw_i2c.h`.

The peer at `0x18` implements the AIC3106-compatible page/pointer protocol, documented startup
registers, byte auto-increment, software reset, writable masks and ADC high-pass coefficients from
[SLAS509G section 10.6](https://www.ti.com/lit/ds/symlink/tlv320aic3106.pdf). Other codec register
accesses fault. It assumes a powered codec with reset released; the physical part number, inferred
GPIO reset wiring, analog settling/power status transitions and ADC/DAC processing are unmodeled.
Output gain/power status retains documented reset values; writes cannot set the read-only bits.
Reports expose the original byte values in a bounded 256-write trace and masked register contents.
`stock_smoke.py --codec` independently checks the entire startup configuration at the McASP boundary.

McASP0 implements the stock synchronous, externally clocked I2S configuration: two 32-bit slots,
AXR13 transmit, AXR14 receive, and the non-FIFO data port at `0x01d02000`. GBLCTL and its receive/
transmit aliases control reset release and initial XDATA; paired events 0/1 service the stock linked
EDMA ring. The codec profile requires its stock PLL and serial settings and assumes the inferred
24.576 MHz MCLK. Slots complete every 3875 DSP cycles (48 kHz frames); the initial phase is aligned
to a deterministic global frame boundary, rather than measured physical clock phase. Clock/pinmux
omissions prevent shifting; other formats/serializers, internal clocks, AFIFO, DIT, loopback and mute
control modes fault. Reset synchronization is functional and has no modeled electrical latency.
Control accesses are available before the functional clock is enabled; shifting requires PSC1 module 7.

Receive words default to digital silence. `c6_audio_input` / `CPU.audio_input` can copy a private
raw LE 32-bit slot-pair source before the first RX word (64 MiB maximum). The source starts at the
first completed RX slot and pauses while reception is stopped. Complete pairs can loop; finite
sources supply zeros at EOF. Source position, consumed/padded words and nonzero RX counts are
exposed separately from controller errors. Reconfiguration after RX starts is rejected.
Transmit words come from guest XBUF/EDMA and
are captured in a bounded 65536-word ring. RDATA/XDATA and serializer flags track buffer service;
overrun overwrites the old receive word, and underrun transmits zeros until serializer reset.
Status W1C, slot counters, aggregate errors and interrupt event 61 follow
[SPRUH79C sections 23.0.21.1/2/6 and 23.1](https://www.ti.com/lit/ug/spruh79c/spruh79c.pdf).
DMA-error and start-of-frame flags have different bit positions in STAT and INTCTL; the mapping is
explicit. Clock checking, electrical bit edges and same-cycle flag-set/clear priority are incomplete.
The raw capture labels slots 0/1 without claiming physical channel routing. ADC/DAC filtering, gains,
analog settling and live host input/playback are not modeled. `stock_smoke.py --audio`
checks original render-task entry, multiple complete blocks, clock continuity and silent output.
`--audio-input` also verifies nonzero receive data through real DMA and the guest's floating-point
input planes. The stock initial RX descriptor has 255 words; recurring links have 256, changing the
settled buffers' pair phase. The regression records that guest configuration explicitly.

UART supports divisor/framing timing, transmit and receive FIFOs, loopback, reset, status side
effects and receive/transmit interrupts. The peer is silent until bytes are explicitly injected,
or, on UART1, until `c6_panel_stream` turns on the panel MCU's continuous analogue reports (rate
and channel order as measured in device sessions M1 and M2; even spacing and idle level 0 are
assumptions; see the emulator README). Other panel MCU messages (`A1`), receive timeout and modem
support are not modelled. The configuration
plane stays accessible with the PSC functional clock disabled, because the stock driver disables
PWREMU before enabling that clock. This is a model assumption; shifting requires the clock.

Only implemented register offsets are accepted. RAM reset does not reset board state; create a new
`Stock` instance for a cold run.

[`decoder.py`](../decoder.py) reads the **current guest RAM**, uses the repository's patched GNU
objdump and packet helpers, then translates instruction text into the C ABI in [`ir.py`](../ir.py).
It decodes pages on demand, including an execute packet that spans the next page. The native cache
tracks every fetch packet involved, so a store to an instruction or compact-fetch header invalidates
dependent decoded packets. Tests cover changes confined to the next page and changes confined to
the PROT header bit. Symbol files are optional debug metadata, not an instruction source.

## Coverage and verification

```sh
python3 -B -m unittest discover -s emulator/tests -p test_core.py -v
python3 -B -m unittest discover -s emulator/tests -v
```

The pure execution checks need host g++; real instruction-byte checks also need DSP binutils. The
optional C fixture comparison needs DSP GCC. Tests use no proprietary inputs and do not run any
firmware or mapping builders.

Coverage is the whole C674x instruction set (the emulator README's "CPU model" section lists how
each group was added and checked). Unsupported operations fault explicitly. The first differential
check compares sixty-six operation forms over thirty input pairs each (1980 vectors) against the
Python reference simulator; random-operand audits of every instruction form and compiled C from
two compilers followed. Independently computed C results and source-built DSP functions provide
additional checks. Timing tests use TI's stated pipeline behavior instead of relying solely on
agreement between implementations.

The specification for packet behavior, pipeline delays and multi-cycle NOP cancellation is
[TI SPRUFE8B](https://www.ti.com/lit/ug/sprufe8b/sprufe8b.pdf), particularly sections 3.10 and 4.4.2,
and the individual instruction entries. The compiled backend follows the documented NOP cancellation
rule even where the existing Python reference waits until the complete NOP finishes; its sources
are left unchanged.

Loop fixtures compare real assembled binaries with independent expected memory and reference state;
one-cycle and large slices agree. Separate checks exercise staged double sources/results, controller
register side effects, timer events, timestamp activation and aliased RAM.

The synthetic/source suite covers fetch-table collisions, owning-map growth and aliased
real-code replacement, sparse 4 MiB group boundaries and the last bytes of the 32-bit address space,
plus native sampler signal/timer restoration and ELF address translation.
GCC build regressions execute a real profile generation/use round trip, relocate counter inputs,
check unseen integer extremes and FP values, reject corrupted/stale profiles, and verify that
automatic fallback executes changed current source. Final profile counters are frozen copies;
later collector writes cannot alter optimized-build inputs.
It also compares scheduled/every-cycle device execution and MMC
clock-stop fractions; runs a user-supplied ELF (`tests/test_custom.py`) and validates
ELF permissions in pre-mapped RAM; McASP clock/pin omissions, reset aliases, status/IRQ
mapping and error handling, exact nonzero TX/RX sample ordering, finite/looped ADC backing, EOF
padding, receiver reset and linked constant-port EDMA across
execution slices; I2C timing, vector acknowledgment, NACKs, pinmux,
repeated START/receive backpressure, codec pages/masks/reset and slice consistency; NOR chip isolation, CS edges, wrapping reads, WEL/WIP,
program/erase semantics and full-duplex SPI0 DMA bytes across slices; MMC reset/timing/timeouts/clock gating and interrupts,
SDSC identification/capacity, response CRC/index, PIO FIFO backpressure and delayed write commits,
short SCR DMA flush, CMD6 status, EDMA TX prefill, multiblock counts/commits and CMD12 across slices;
SPI buffering/widths, UART timing/FIFO interrupts,
GPIO edge latches, EDMA strides and linked descriptors, and SPI DMA byte delivery/completion. Optional
stock smoke checks execute the CRC-checked local image without guest hooks. A protected-load
regression verifies that the four decode-inserted NOPs remain when the predicate is false; this
prevented bad stack restoration in the actual SYS/BIOS interrupt path.

Nested loops reload the buffer through a conditional SPLOOP(D) and an SPMASKR in the post-loop code
(SPRUFE8B 7.9.6); the loop tests check this against the reference simulator, C-level expected values and a
nested loop taken from a CyDrums image; SPKERNELR, a reload with RILC = 0 and interrupted loop
draining are covered too (the refusals that remain are listed under "Interfaces and execution
model"). Not implemented: complete floating-point status flags and rounding modes,
full control-register side effects, memory/cache timing and the board devices the firmware does not
use. Software exceptions (`SWE`, `SWENR`) are taken; NMI and internal or external hardware
exceptions are not delivered. Nonzero AMR is rejected. Functional-unit resource conflicts and every invalid instruction form
are not exhaustively validated.
