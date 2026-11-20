# Guest workload and the real-time gap

**Status:** on the development host the interpreter runs the stock WAV preview at about real time
(0.14× before) and warmed start-up audio at about 1.15× (0.17× before), since two changes of
2026-11-15: exact fast-forward of provably repeating guest state, and a leaner execution path for
common instructions ([Fast-forward and the lean path](#fast-forward-and-the-lean-path)). Since
2026-11-16 hot guest code can also be compiled to host code ("Compiled blocks" below; on by default
in the stock panel since 2026-11-17), which runs the idle project screen at about 3.4× and a
generated song at about 1.2× with the panel MCU stream on. The sections between record the
measurements that led there; their "times below real time" figures describe the core at each step
([Throughput history](#throughput-history-2026-11-14-to-2026-11-15)).

The original decision was based on the stock WAV preview workload. The guest profiler measures
original code; it does not replace the idle task, stack checker, scheduler, allocator or audio routines.

## Tools

`python3 -B emulator/performance.py` boots stock once, then measures warmed audio slices (three by
default; `--samples`) and reports guest and host time, real-time ratio, packet and sample counts and
guest audio errors. Results are under `work/emulator/performance/`; `--output` keeps comparison
runs. `--cpu 0 --guest-sample-period 1009` adds thread affinity (choose an allowed CPU) and a guest
PC/cycle profile; the same options work with `tests/stock_audio.py --conditional` to measure nonzero
preview playback. Reports include ns/packet, the real-time cost target, SPLOOP activity, interrupt
rate and wait advancement. Profiling is off by default and leaves execution unchanged.
`--eager-board` measures the every-cycle device reference path. The `--audio-input` and
`--loop-audio-input` options of the stock runner are accepted.

`python3 -B emulator/profile_native.py` samples host instruction pointers during 500 million warmed
guest cycles after a 250-million-cycle boot. It needs a dedicated single-threaded Linux
x86_64/aarch64 process, host `g++` and `addr2line`; no performance-counter privileges. The report,
`work/emulator/performance/native-profile.json`, includes core and sampler hashes, native functions,
source/inline frames, sample counts, dropped/unmapped counts, new guest decodes and observed timer
granularity. SIGPROF uses process CPU time; the kernel may round the requested interval (this host
delivered roughly 10 ms for a 1 ms request). Attribution is statistical and sampling adds overhead.

GCC profile-guided compilation of the core is available through `tune_core.py`:

```sh
python3 -B emulator/tune_core.py --workload stock-audio --conditional --cpu 0 --activate
python3 -B emulator/performance.py --cpu 0 --samples 5
```

Training and compiled artifacts stay under `work/emulator/`. Automatic selection requires matching
core sources, ABI, compiler/target, flags and counter hashes; a stale profile selects the current
portable build and records the reason. `SMPLTREK_CORE_PGO=off` forces that reference build; set the
variable to a bundle directory to require a particular profile, and an incompatibility then stops
set-up. The synthetic default workload checks the build workflow without stock firmware; it does not
establish a stock speed gain. Floating-point contraction is disabled and fast math stays off.
Measurements in [GCC profile-guided compilation](#gcc-profile-guided-compilation).

## Reproduction

On Linux, choose a CPU in `os.sched_getaffinity(0)`. These examples use CPU 0:

```sh
python3 -B emulator/performance.py --cpu 0 --samples 5
python3 -B emulator/performance.py --cpu 0 --samples 5 --guest-sample-period 1009
python3 -B emulator/tests/stock_audio.py --conditional --cpu 0 --guest-sample-period 1009
```

`--cpu` pins only the calling emulation thread and restores its previous affinity on success or
failure. It does not isolate a host CPU or remove VM/scheduler noise. Reports retain the binding,
nanoseconds per issued packet, required nanoseconds per packet at 372 MHz, packet density and
interrupts per guest second. The ordinary benchmark measures startup audio, before USB setup;
the optional stock regression profiles the first warmed, nonzero preview window at cycles
2,020,000,000–2,220,000,000. Conditional boot still uses the two existing explicit bus hypotheses.

Generated measurements for this investigation are under `work/emulator/packet-profile/` and
`work/emulator/stock-audio-profile/`. The latter retains all 20 audio checks and matches the
preceding core's 54 recorded state/device comparisons through cycle 3.61 billion, excluding only
the input-card path. These are local model observations, not device timing measurements.

## Guest measurements

The nonzero playback window covers 200 million cycles, 108,828,900 issued packets, 934 accepted
interrupts (1,737.24 per guest second), and 107,921 jittered packet samples. No samples were dropped.
The four exclusive cycle classes sum to exactly 200 million:

| Cycle class | Cycles | Fraction |
| --- | ---: | ---: |
| Ordinary/drain packet issue | 104,576,908 | 52.288% |
| Wait after issue | 89,744,516 | 44.872% |
| Active software-loop execution | 5,670,170 | 2.835% |
| Interrupt entry | 8,406 | 0.004% |

Draining epilogs overlap 47,606 ordinary issue/wait cycles. Existing wait advancement succeeds
21,641,422 times and coalesces 59,822,482 ticks, or 29.911% of all logical cycles. Software loops
issue 4,251,992 packets. PC samples count issued packets rather than cycles; the two distributions
must not be treated as interchangeable.

These verified/inferred source ranges account for approximately 86.9% of packet samples:

| Original address range, end excluded | Attribution | Packet samples |
| --- | --- | ---: |
| `0xc169c3c0`–`0xc169c440` | SYS/BIOS `Idle_run` | 40.02% |
| `0xc16ace00`–`0xc16ace20` | `Idle_loop`, inferred from its call/back-branch and TI source | 5.25% |
| `0xc169c140`–`0xc169c1c0` | Idle stack-check callback, matching `Hwi_checkStack` | 20.72% |
| `0xc1694a80`–`0xc1694b20` | `Hwi_getStackInfo` | 20.90% |

Evidence is the original listing `work/smpltrek-3.2.174.dis`, read-only symbols/platform mapping,
and local SYS/BIOS 6.76.03.01 sources: `packages/ti/sysbios/knl/Idle.c`, `hal/Hwi_stack.c`,
`hal/Hwi.xs` and `family/c64p/Hwi.c`. TI's configuration adds `Hwi_checkStack` to the idle list;
the original callback calls `Hwi_getStackInfo` with `computeStackDepth = FALSE`, checks the return,
and raises an error on overflow. The existing symbol at `0xc169c140` is named `Cache_wait`, but
that name conflicts with this directly observed body/source match. No symbols or mappings were
changed; the callback attribution here is an explicit inference.

Idle housekeeping is therefore the main guest packet workload in this single-WAV profile.
SPLOOP pre-expansion is still useful to investigate for heavier DSP loads, but these measurements
do not establish it as the first large win. Idle housekeeping includes real RAM reads and stack/
output stores, so a rule for a store-free polling loop would not directly cover it. Acceleration
must retain the effects of these original instructions, RAM/code changes, interrupt boundaries
and debugger stops. Replacing the idle/stack-check functions with host hooks remains out of scope.
Compiled packet/block execution, with the interpreter as an exact-state oracle, was the stronger
structural candidate (built later: "Compiled blocks" below). This preview workload does not establish performance at high polyphony.

## Host measurements and limits

A separate native profile of warmed playback at cycles 2.22–2.72 billion captured 828 samples
without newly decoded guest instructions. About 37.2% were attributed to packet issue, 28.3% to
the run loop and 13.5% to tick processing. Sampling resolution, inlining and host load limit these
fractions. A breakpoint rejection filter experiment changed a five-slice result from 0.1624× to
0.1627×, within host variation, so that experiment was removed.

CPU-0-pinned five-slice runs measured 31.91 ns/packet with guest profiling disabled and 34.08
ns/packet enabled at period 1009 (0.1560× / 0.1461× real time). The required cost was 4.98
ns/packet. These separate runs illustrate diagnostic overhead; they are not a precise overhead
estimate or a speedup claim. The guest CPU, audio and OLED states agree exactly at cycle 500
million. Disabled profiling uses a separately instantiated, uninstrumented run loop, so there are
no per-packet counter or sampler branches in that path. Both paths retain normal timing and strict
MMIO behavior. Host audio and real-time throughput remain incomplete.

`CPU.profile_guest(period)` starts a fresh window; zero freezes it. CPU reset clears/disables
profiling. Period 1 records every packet. Larger nominal periods use deterministic jitter to reduce
sampling alignment with short loops. Software-loop samples use their original SPLOOP control PC;
ordinary/draining samples use the program PC. Counters are exact model counts, while PC shares are
samples. The PC table holds at most 65,536 entries and reports omitted samples explicitly. Reading
stats snapshots the histogram; profiling does not read or alter guest registers/RAM or dispatch
guest functions. Fixed-width ABI additions retain the existing CPU state and instruction layouts.

## Direct RAM-page lookup

RAM backing now uses two pointer indices instead of an `unordered_map` lookup. The top level has
1,024 entries; each allocated second level covers 4 MiB with 1,024 page pointers. Absent mapped
RAM still reads as zero. A page retains its address and fetch-version counters until machine
destruction, including across CPU reset. Partial aliases, permissions and MMIO use their existing
checks. Stores update each affected fetch-version counter while copying that same 32-byte span,
avoiding a second alias translation and page lookup. DMA uses this common memory path as before.

Five alternating pairs of 50-million-cycle stock slices, following a 250-million-cycle warmup,
were pinned to CPU 0. Against the preceding core, aggregate host time fell from 4.4734 to 4.0862
seconds: 0.1502× to 0.1645× real time, or **9.5% more throughput**. CPU, audio, OLED, codec, USB,
SD, recent MMIO and reserved-write reports agree exactly at all five boundaries through cycle
500 million. The generated paired reports and comparison script are under
`work/emulator/lowering/compare-pages.json` and `compare_pages.py`. This is the warmed startup
audio workload, not a high-polyphony performance claim. Host load still affects the result, and
approximately six times more throughput is needed for real time.

A second alternating, CPU-0-pinned comparison measures **nonzero WAV preview**, from cycles
2.22 to 2.47 billion, after both cores execute the original boot and the same external UI inputs.
Across five 50-million-cycle pairs, the new core has **3.7% more throughput**: 0.1554× to 0.1611×
real time, or 31.81 to 30.68 ns/packet. All paired CPU and audio/display/device reports agree
exactly at every boundary. This smaller gain is the more
relevant result for the audio goal; the startup result must not be generalized to playback.
Generated reports and the script are `lowering/compare-preview-pages.json` and `compare_preview.py`
under emulator work. These measurements still cover only the single-WAV workload.

The source suite passes all 137 checks, including new guest copies through partial aliases at a
4 MiB boundary and the last bytes of the 32-bit address space, plus real instruction replacement
through an alias across two pointer groups. The full stock WAV regression passes all 20 checks
through cycle 3.61 billion. Its six captured stages match the preceding core's CPU/device states,
including flash and checkpoints; inputs, UI observations and exact audio matches also agree
(66 comparisons, normalizing only the private card path). Reports and raw/WAV/frame artifacts are
under `work/emulator/stock-audio-pages/`. The existing reserved-bus hypotheses remain explicit.

Two alternatives were measured and removed before this change. Compact, specialized integer/
memory/control handlers with whole-packet fallback passed the existing pipeline tests and new
differential checks, but their final paired stock benchmark had 7.2% less throughput. They still
required packet fetch/version/interrupt/tick processing and staged writes; handler dispatch alone did not
remove that cost. A 16-slot delayed-result/IRQ queue also preserved the tested state but measured
1.7% less throughput. These host-dependent experiments establish no useful gain for this workload.
Their patches and reports remain only in ignored work files, and neither changes the shipped backend.
Native block translation still needs its own design, exact-state comparisons and measurements.

## GCC profile-guided compilation

`tune_core.py` freezes the current C++ sources, builds an instrumented host library, and runs a
separate collecting process. The stock workload executes the complete original WAV-preview UI
regression with its existing explicit bus hypotheses; no guest function is intercepted. GCC writes
counters only when that child exits. The parent then freezes copies of every translation unit's
counters, records their hashes and the training report, and compiles the optimized library. A
source-built copy/replace/execute check also runs through the optimized core before activation.

```sh
python3 -B emulator/tune_core.py --workload stock-audio --conditional --cpu 0 --activate
python3 -B emulator/performance.py --cpu 0 --samples 5
SMPLTREK_CORE_PGO=off python3 -B emulator/performance.py --cpu 0 --samples 5
```

Use an allowed CPU. Omit `--activate` to build without changing automatic selection. Without the
stock workload option, the tool collects a source-built integer/RAM-copy fixture instead; that
checks the workflow and does not establish a stock throughput result. A bundle path in
`SMPLTREK_CORE_PGO` requires compatible data, whereas `off` forces the portable reference.
Automatic selection reads `work/emulator/pgo/active.json`. Source, ABI, compiler version/target,
flags and all counter hashes must match. An incompatible automatic profile falls back to the
current portable core and reports why; an incompatible explicitly requested profile is an error.
Native build locks and atomic library/manifest publication protect concurrent builders.

Both builds retain `-O3`, LTO and strict floating-point arithmetic. FP contraction is explicitly
off; `-march=native` is not used, and fast math is off. A host-native experiment did
not show a reliable gain, so it is not part of this workflow. PGO changes host compilation, leaving
current-RAM decoding, invalidation, pipeline timing, interrupts and unsupported-MMIO faults intact.
There are no runtime profile counters in the optimized library.

With the profiled core, the completed workflow measures **9.2% more nonzero playback throughput**:
0.1626× to 0.1775× real time, or 30.38 to 27.83 ns/packet. Five alternating,
CPU-0-pinned pairs each execute 50 million cycles, following original startup/UI inputs through
cycle 2.22 billion. Other validation jobs finish before the measured pairs begin. CPU, audio, OLED,
codec, USB, SD, MMIO, reserved-write, checkpoint and flash reports agree at every boundary through
cycle 2.47 billion. The generated report is `work/emulator/host-tuning/compare-swe-preview.json`.

All 141 source/synthetic tests of the time passed using the optimized build. The optimized stock WAV run passes all 20 checks and matches 66
state/output comparisons with the preceding ordinary core through cycle 3.61 billion. Artifacts
are under `work/emulator/stock-audio-pgo-swe/`; the activated profile bundle is
`work/emulator/pgo/stock-audio-swe/`. The 32 core/build tests also pass with PGO disabled.

These measurements cover one WAV, not high polyphony or live host deadlines. Roughly 5.6 times
more throughput was then needed for real time; fast-forward and compiled blocks (below) followed. Earlier experiment reports remain under `work/emulator/host-tuning/` and
`stock-audio-pgo-training/`; use the final paired measurement above for this milestone.

## Throughput history (2026-11-14 to 2026-11-15)

The interpreter's speed before fast-forward, step by step, on the development host. Each step left
CPU state, audio and OLED output identical to the step before at the cycle named; no guest
instruction or device event was skipped. "Gap" is the factor still missing to real time then.

| Step | Benchmark | Before → after | Agreement checked at | Gap |
|---|---|---|---|---|
| first stock run | one billion cycles, 2.69 guest seconds in 118.76 host seconds | 0.023× | — | — |
| next-deadline device scheduling, reused packet scratch storage | two warmed slices | 0.0221× → 0.0879× (about 4×) | cycle 350 million, also against `--eager-board` | 11.4× |
| shared RAM translation per load/store, direct fetch-version pointers | three warmed slices | 0.0873× → 0.1100× (26%) | cycle 400 million | 9.1× |
| first nonzero-input benchmark | 46,055 nonzero RX words by cycle 400 million, no under/overruns | 0.1080× | — | 9-10× |
| after the storage additions | empty card, nonzero input | 0.1115× | cycle 400 million | — |
| tagged fetch table, cached loop-control classification, reused loop/epilog packets, strict-FP `-O3` + LTO | nonzero input | 0.1115× → 0.1312× (about 18%) | cycle 400 million, incl. 46,055 nonzero RX words | 7.6× |
| USB, key and audio models (113 source/synthetic tests) | warmed stock run | 0.1280× (USB run), 0.1400× | cycle 400 million | 7-8× (host/load variation, not a speed change) |
| first warmed active-playback window (WAV preview) | | 0.141× | — | about 7× |
| loop state only for loop packets, no empty vector appends, no absent epilog work | five warmed 50-million-cycle slices | 0.1373× → 0.1495× (8.9%) | cycle 500 million; full stock WAV regression | 6.7× |
| cached constant-NOP metadata, wait advance to the next event | five warmed slices | 0.1373× → 0.1595× (16.1%) | cycle 500 million; stock WAV run at every captured stage | 6.3× |
| direct sparse RAM-page lookup, shared store/invalidation lookup | CPU-pinned alternating five slices | 0.1502× → 0.1645× (9.5%); paired WAV preview +3.7% | cycle 500 million | about 6× |
| GCC profile-guided core build | paired nonzero playback | 0.1626× → 0.1775× (9.2%); 141 source tests and 20 stock WAV checks pass | exact | 5.6× |

Host profile with `profile_native.py`: before the fetch-table step, 1,166 samples put about 58% in
packet issue and the run loop, 12% in cycle updates and 4% in device advancement, with no new guest
decoding. After it, 1,005 samples (none dropped or unmapped): about 67% issue/run, 14% cycle
updates, 5% devices; CPU, audio and OLED state equal to the earlier core's profiled run at cycle
750 million. The preview spends 2.835% of guest cycles in software loops and about 86.9% of sampled
packets in idle-loop and stack-check housekeeping, which is why fast-forward of repeating guest
state, not a faster interpreter, closed the gap for light loads. Packet handlers and a queue for
pending results showed no gain and were removed.

## Fast-forward and the lean path

### Fast-forward of repeating guest state

The profile above shows about 87% of packets in SYS/BIOS idle housekeeping. That loop does real
loads and stores, so it cannot be treated as a NOP, and replacing it stays out of scope. But its
state repeats exactly: on 3.2.174 every 96 cycles and 50 packets. The core now proves that at run
time and skips whole periods. Nothing about the idle loop is built in; any guest loop qualifies.

A snapshot of the CPU is taken when a branch lands with an empty pipeline. Until the same PC is
reached again the core records every word the CPU loads and stores. The period is proven when:

- all 96 registers, the interrupt-block distance, the timestamp state and the last issued
  instruction address are equal, with no pending result, branch, interrupt entry or loop;
- every stored word holds what it held at the snapshot (the net RAM change is nil);
- the CPU made no MMIO access and no TSCL read, no interrupt was taken, and at most 65,536
  cycles passed.

Execution is a function of that state and of the RAM the CPU touched, so the next period is
identical. The core adds `n × period` cycles and `n × packets`, with `n` chosen so that the CPU
stops before the next device deadline and before the end of the host's cycle budget. The proof
is dropped by an interrupt, a different state at the anchor, a device or host write to a word
the period touched or to decoded code, and at every `c6_run` entry.

Device events are never skipped. Stock's McASP raises one every 3,875 cycles (each slot word),
so stopping before each cost one executed period per event. When every store of the proven
period rewrote the value already there, RAM is the same at every cycle of the period. A device
event inside the next period then finds exactly the RAM it would have found, and the core runs
it early, with its own cycle number, while the CPU waits at the anchor. If the event raised no
new interrupt flag and wrote nothing the period touches, that period is skipped too. Otherwise
its interrupt flags are held, any write into touched RAM is undone, and both are applied when
ordinary execution reaches the event's cycle. An event beyond the current budget never runs
early, so the host never sees a device ahead of the cycle count it is given.

Fast-forward is on by default. `CPU.fast_forward(False)`, `performance.py --no-fast-forward` and
`stock_ui.py --no-fast-forward` execute every cycle. Guest profiling and eager board polling
disable it, so both remain every-cycle references. `CPU.fast_forward_state()` reports skipped
cycles and packets, snapshots, proofs, events run ahead and events held back.

Limits: a loop whose landing always has a load or multiply result in flight never produces a
snapshot; a loop that polls MMIO or TSCL is never skipped; a device-model fault raised by an
event that ran early is reported at the anchor instead of mid-period.

### Lean execution path

The interpreter spent 500 to 700 host instructions per guest packet, spread over generic operand
decoding, staging vectors, per-cycle bookkeeping and device-range checks. No single item
dominated, apart from two accidental ones: an `std::optional<Loop>` and a local `std::pair`
array were zero-filled on every packet.

- Each decoded instruction keeps pointers to its plain sources (a register or a pooled constant)
  and, for the common forms, a compact `Micro` record. A packet whose instructions all have one
  runs through `issue_fast`, which keeps the general path's order: read everything, then commit
  stores, registers and delayed results. Other packets, and malformed operand counts, use the
  unchanged general switch.
- Delayed register results sit in a 16-slot ring indexed by due cycle instead of a scanned vector.
- RAM pages that are wholly ordinary RAM under one mapping are entered in direct read and write
  tables, replacing the device-range, permission and alias lookups on every access. Device,
  partial and unmapped pages are never entered.
- Software-loop rows are selected by precomputed phase instead of a division per row, and loop
  and epilog packets pass instruction pointers instead of copying 120-byte records.
- Breakpoints are filtered by a bitmap before the hash lookup; packet dependencies are inline.

### Decode cache

Decoding a 4 KiB page through objdump costs about 30 ms, and stock start-up decodes 322 pages:
9.6 of 13.8 host seconds. `decoder.py` now stores each page's installed packets under
`<work>/decode-cache/<sources>/`, keyed by the page bytes and address. The directory name hashes
the decoding sources (`decoder.py`, `ir.py`, `core.h`, `packets.py`, `string_refs.py`,
`memory_map.py`). A damaged entry is decoded again and rewritten. `SMPLTREK_DECODE_CACHE=off`
disables it; another value moves it. The disassembler binary is not part of the key: clear the
cache after changing it. The stock cache is about 14 MiB.

### Measurements

AMD Ryzen 7 9800X3D under WSL2, GCC 13.3, portable build, emulation thread pinned to CPU 0.
"Executed" is the share of guest cycles that were interpreted, not skipped.

| Workload | Core before fast-forward | Now, every cycle | Now, fast-forward | Executed |
| --- | ---: | ---: | ---: | ---: |
| Warmed startup audio, `performance.py --cpu 0 --samples 5` | 0.174× | 0.216× | 1.15× | 7.7% |
| Nonzero WAV preview, 200 M cycles, `tests/stock_forward.py` | 0.142× | 0.205× | 1.00× | 9.4% |
| Start-up to the sequencer, 1.5 G cycles (4.0 guest s) | 14.8 s | | 5.7 s, warm decode cache | |

`performance.py` builds a full report after each 50 M-cycle sample; timing bare `c6_run` calls
over the same startup window gives about 1.25×. `tests/stock_audio.py` reports 0.97× for its
playback window. The lean path alone reduces the cost of a packet from about 34 ns to about 23 ns
on the idle-heavy mix. With fast-forward the packets that remain are the heavier audio and scheduler ones, at 35 to
37 ns each. A GCC profile trained with `tune_core.py --workload stock-audio --conditional` on
these sources measured 3 to 5% more (1.26× to 1.32× on bare startup runs, 1.00× to 1.03× preview) with exact
state agreement. It was not activated; any core source change makes a profile stale and the
build then falls back to portable by itself.

**What this does not establish.** Both workloads leave the guest CPU idle about 90% of the time.
A project that loads the DSP more leaves less to skip, and interpreted packets still cost about
seven times the 5 ns real-time budget. A fully loaded guest would run near 0.15×. Closing that
needs translated blocks, as the earlier sections conclude. These are also throughput averages on
one fast desktop CPU, not a host deadline guarantee.

### Verification

- The complete WAV-preview scenario (start-up, original UI navigation, 200 M cycles of playback)
  was run on the core before fast-forward and on the new core. CPU state, captured audio, display,
  SD state and the MMIO trace are identical at all eight stage boundaries through cycle 2.22
  billion, for the portable and the profile-guided build. The reference executed 108,828,900
  packets in the playback window, the count recorded above.
- `python3 -B emulator/tests/stock_forward.py --conditional` repeats that scenario with
  fast-forward on and off and compares the same observations at every stage.
- `tests/test_fast_forward.py` uses source-built loops on the board model. Every boundary state
  matches an every-cycle run, including one-cycle slices: a spin loop, a loop that stores the
  same value, a loop whose RAM alternates over several iterations, a counting loop and a TSCL
  reader (never skipped), Timer0 interrupts with dense boundaries around entry and return, a
  masked timer flag, and SPI receive DMA writing into the word the loop loads. In the last one
  the guest counts iterations after the byte arrives; disabling the undo makes the test fail.
- `tests/test_decode_cache.py` checks that replayed packets, listing text and final state equal
  a fresh decode, that changed bytes decode again and that damaged entries are rewritten.
- All 215 source/synthetic tests pass. The nine `stock_smoke.py` variants and the conditional
  boot, project and audio regressions pass with their checks unchanged.

### Sustained runs (2026-11-15)

Host time was taken for every 10 ms of guest time over one to two guest minutes, on a 32 MiB
card holding six samples, from the settled project screen onwards. "Lag" is how far a player
paced at real time would have fallen behind by the end.

| Stock state | Guest time | Rate | 1 s windows min / median | Cycles executed | Lag |
| --- | --- | --- | --- | --- | --- |
| Project (home) screen, idle | 60 s | 0.80× | 0.75 / 0.80 | 12.3% | 15 s |
| Sample-pool preview of a 30 s WAV | 120 s | 0.99× | 0.92 / 0.99 | 9.3% | 2 s |
| Project screen, every cycle | 20 s | 0.19× | 0.19 / 0.19 | 100% | 85 s |

- Final CPU state, audio, display, SD state and MMIO trace of 20-second fast-forward runs equal
  the every-cycle runs for both states. No McASP underrun occurred in any run.
- The host executes about 35 million guest cycles per second here, so real time holds only
  while stock needs under about 9.4% of its cycles. The preview sits at that edge; nothing
  heavier has headroom. PLAY on the empty project does not start the transport, so it measured
  the same as idle.
- The project screen redraws about 25 frames per second. Each display byte's receive DMA
  stores the same `0xff` into one RAM byte in a page that also holds code, which ended the
  proof 188,000 times per guest second (0.62×, 19.6% executed). A device write that leaves
  memory as it was no longer ends the proof or is journaled.
- A project with samples on tracks could not be built: OK on a pool filename is the
  null-object read described in [the audio investigation](audio-investigation.md).

### Compiled blocks (2026-11-16)

`blocks.py` turns hot guest code into C++ that the host compiler builds into libraries the core
calls in place of interpreting it. The core leaves it off unless asked; the stock panel turns it on by
default since 2026-11-17 (`--no-blocks` to disable). `cpu.blocks(True, heat=True)` counts
entries while running; `compile_blocks(cpu)` builds and installs what is hot (about 4 s for 500
blocks on 16 threads, cached under the work directory). `stock_ui.py --blocks` does the same in
the background every few seconds while the panel runs.

Two shapes are compiled:

- **Straight runs.** From a branch landing along the fall-through path to the landing of the
  first always-taken branch, at most 48 cycles. Delayed results are locals assigned at their
  landing cycle.
- **SPLOOP, SPLOOPD and SPLOOPW iterations.** Once every stage of the loop body is running and
  while the loop counter is not exhausted (or the while-predicate holds), whole iterations run
  in host code; a result that lands in a later iteration is carried in a local. The
  interpreter still runs the first and last iterations, where stages start and drain.

The core enters host code only when no device event, held event, interrupt, breakpoint or
fast-forward recording falls inside it. Host code touches plain RAM only: before a packet that
would access anything else, or misaligned, it returns to the interpreter, which then runs that
packet and raises any fault with the usual state.

Fast-forward recording had been active for about a quarter of executed cycles at landings that
never repeat. A failed attempt now waits far longer before the next one when a proven anchor
exists, which also speeds the interpreter.

MPYLI and LMBD, which kept the per-sample code of the audio interrupt out of host code, gained
fast forms (also used by the interpreter).

| Stock state (20 s, same card) | Interpreter | Straight runs | With loops | 1 s window min |
| --- | --- | --- | --- | --- |
| Project (home) screen, idle | 0.98× | 1.72× | 3.43× | 3.28× |
| Sample-pool preview of a 30 s WAV | 1.20× | 1.89× | 4.42× | 4.12× |

- Final CPU state, audio, display, SD state and MMIO trace equal the interpreter's in both
  states. Host code ran 90% of the executed cycles, hardware loops 21 to 28%.
- What is left is mostly code around control-register moves (MVC, DINT, RINT), the first and
  last iterations of loops, and exits at branch landings. `cpu.block_refusal(pc)` says why an
  address has no host code.
- The panel itself, unpaced (`--speed 8 --blocks`), settles at about 3× on the project screen
  some 20 s after start; until then background compilation costs some speed.
- `tests/test_blocks.py` compares host code and interpreter state at dense cycle boundaries: a
  source-built loop with a reader one cycle before and after each delayed result, and four
  assembled SPLOOP bodies (several stages, results landing one or more iterations later,
  predicates, a masked instruction). A guest fault reached in host code must leave the
  interpreter's fault state. Moving a load, multiply or float result by one cycle, landing the
  wrong carried value or dropping an in-flight result at a loop exit makes it fail.
- Not measured: any load heavier than the preview.

## Panel MCU stream (2026-11-17)

The panel MCU stream (emulator README) adds about 12,600 UART interrupts a second. Measured over
four guest seconds at the idle sequencer with compiled blocks, three interleaved runs each:

| | Stream off | Stream on |
| --- | --- | --- |
| Cycles skipped by fast-forward | 83.5% | 77.5% |
| Cycles in host code | 15% | 18% |
| Cycles interpreted | under 1% | about 2% |
| Interrupts taken | 5,600 | 55,900 |
| Entries into host code | 8.1 million | 14.2 million |
| Speed | 2.23× | 1.30× |

A host profile of that window (`perf`) puts the time in the run loop around host code, not in the
interpreter: looking up the block for a PC (cache misses in the 1 MB slot table), checking that
its code is unchanged, the ordinary tick after it, and the block's memory helpers.

- **Kept:** the memory and delayed-result helpers in `core/block.h` are now always inlined into
  host code (GCC had left `c6b_load` as a call). Idle 2.23× to 2.38×, six-track playback 1.80× to
  1.90×; with the stream 1.30× to 1.34× and 1.18× to 1.20×. No change in behaviour.
- **Tried and dropped: keeping a fast-forward proof through an interrupt.** Every interrupt ends
  the proof of the idle period, and it is recorded again by the interpreter. A version that set
  the proof aside and took it up again at the anchor kept half of them, and only after three
  additions, because the handler leaves the state different in ways that do not matter to the
  period: it rewrites words that share a 32-byte span with code, IRP holds a new return address,
  and other task code leaves its temporaries in stack bytes the period writes before reading.
  Speed with the stream did not change (1.29× against 1.32×), and without the stream it fell 7%
  (2.07× against 2.23×). Recording was not the cost.
- **Tried and dropped: host-code entries behind packets that cannot start a block.** Straight
  code that begins with `DINT` or a control-register move never became an entry (the per-sample
  audio code at `0xc15a3394` is one). Passing the entry search on to the next packet added 50
  blocks and 0.6% of cycles in host code, with no measurable change in speed.
- **Kept (2026-11-17): a longer back-off for fast-forward recording that keeps failing.** Host
  code is not entered while a period is being recorded. A GCC-built firmware whose main loop reads
  `TSCL` on every pass, under about 13,000 interrupts a second, never gave one proof, yet a new
  recording started about 11,000 times a second, and about a million entries into host code a
  second were refused for it. After a failed recording the wait before the next one doubles; its
  limit was 32,768 packets and is now 262,144. A place that has proved before is still retried at
  once, so firmware that idles in a repeating loop is not affected. Two interleaved runs of each,
  with compiled blocks:

  | Workload | Limit 32,768 | Limit 262,144 | Limit 4,194,304 |
  | --- | --- | --- | --- |
  | That firmware playing a four-note synthesiser | 0.76×, 0.77× | 1.10×, 1.11× | 1.19×, 1.18× |
  | The same, silent | 1.53×, 1.61× | 1.91×, 1.90× | 1.96×, 1.97× |
  | Stock idle | 2.89×, 2.99× | 3.03×, 3.14× | 2.97×, 3.06× |
  | Stock idle, panel stream | 1.41×, 1.47× | 1.48×, 1.47× | 1.44×, 1.49× |
  | Stock six-track playback | 1.69×, 1.86× | 1.82×, 1.83× | 1.77×, 1.82× |
  | Stock six-track playback, panel stream | 1.10×, 1.12× | 1.14×, 1.13× | 0.92×, 1.07× |
  | LoFi-12 idle, panel stream | 1.02×, 1.00× | 0.98×, 1.00× | 1.03×, 1.02× |

  Another program was using the host during these runs, so differences of a few percent mean
  nothing. The stock proofs are the same to within a few at every limit and the playback audio is
  identical. The largest limit was not chosen because of its two low readings for six-track
  playback with the stream, which two runs can neither confirm nor dismiss. Firmware that polls in
  a loop without ever sleeping stays slow whatever the limit (the same synthesiser on a polling
  main loop ran at 0.44×, and 0.55× with the largest limit): every cycle of the loop has to be
  executed.
- Measured on that firmware then, and acted on below: a `TSCL` read could not be compiled into
  host code (1.4 million returns to the interpreter a second on the polling loop). Entries into
  host code average 11 cycles.
- **Kept (2026-11-18): control-register moves, `DINT`/`RINT`, `ROTL` and the `TSCL` read on the
  lean path and in host code.** A count of every packet the interpreter issued while blocks were
  on (temporary counters, since removed) gave 11.7 million a second for CyDrums idling on its
  main screen and 6.1 million for a GCC-built synthesiser playing two notes. Most were not slow
  instructions themselves: a packet that no block can start with handed over to the interpreter,
  and the straight code after it was never offered as an entry, so the interpreter ran on to the
  next branch target. Those packets were `MVC` (CSR, IER and the others around interrupt masking;
  `TSCL` in the synthesiser's clock), `DINT`, `RINT` and, in GCC code, `ROTL`. Now:
  - `MVC` is a plain move when its source reads as its stored value and its destination only
    holds what is written (a general register, IRP, NRP, ILC, RILC, NTSR, REP); a read of `TSCL`,
    a write to CSR or IER, `DINT`, `RINT` and `ROTL` have lean forms of their own, each a copy of
    what the general path does. Other control-register writes keep the general path.
  - A block ends with a packet holding `RINT` or a write to CSR or IER, so that the run loop
    looks for an interrupt at once, as it does after the interpreter runs one. Loop bodies in
    host code take none of these, nor the `TSCL` read.
  - After a packet that no block can start with, an entry is looked for (and counted) again at
    the next packet.
  - `CPU.micro(False)` sends every instruction down the general path, for comparing the two.

  Two runs of each on a quiet host, compiled blocks on, the old core first:

  | Workload | Before | After |
  | --- | --- | --- |
  | Stock idle | 3.04×, 2.99× | 3.01×, 3.09× |
  | Stock idle, panel stream | 1.48×, 1.45× | 1.63×, 1.66× |
  | Stock six-track playback | 1.80×, 1.83× | 1.84×, 1.91× |
  | Stock six-track playback, panel stream | 1.08×, 1.13× | 1.22×, 1.20× |
  | CyDrums 1.1.84 idle on its main screen, panel stream | 0.89×, 0.90× | 1.01×, 1.00× |
  | GCC-built synthesiser, two notes, panel stream | 1.38×, 1.37× | 1.62×, 1.74× |
  | The same, silent | 1.97×, 1.96× | 2.33×, 2.29× |

  The two sets were run one after the other, not interleaved. Playback audio is identical.
  `tests/test_lean.py` runs one program down the general path, the lean path and compiled blocks
  with interrupts requested at random boundaries and requires the same state at each of 400, and
  checks that a pending interrupt enters right after the `RINT`, the write to IER or the write to
  CSR that lets it in; three deliberate faults in the new code each fail it. What is left on
  CyDrums, about 190,000 hand-overs a second, is `LDDW`/`STDW` beside an `MVC`, `RCPSP`, `ABS`
  and the pack instructions. In the panel, newly hot code still runs on the interpreter until the
  host compiler has finished with it: about 45 seconds of start-up for CyDrums and about 10
  seconds after a new kind of sound on the synthesiser.
- **Kept (2026-11-18): the SD card model asks for an event only where something visible changes.**
  The 45 seconds were not mostly the compiler. CyDrums spends its first ten guest seconds
  reading about 85 MB from the card, and through those seconds the emulator ran at 0.31×: MMCSD0
  had an event for every received byte (8.5 million a second), and host code is not entered
  across a device event, so 3.7 million entries a second were refused. Now a received byte that
  ends no block, leaves DRRDY as it is and does not fill the FIFO has no event of its own; it is
  clocked in the next time the model is consulted, which every register and DMA access does
  first. Card-loading seconds run at 0.64×, with the same interrupts, bytes read and skipped
  cycles in each second as before. A new test in `test_board.py` reads a block by interrupt at
  both FIFO thresholds and requires the cycle of every interrupt, every status word and every
  byte to equal a run in which the board is polled every cycle; the stock checks' saved cycles
  did not move. Three deliberate faults in the rule fail the new test or `stock_inst.py`; a
  fourth turned out to change nothing (DRRDY is only ever set with the FIFO at its threshold).
- **Kept (2026-11-18): a block compiled before is found again whatever batch it was in.**
  `blocks.build` used to find a library only if the same set of blocks was asked for again, so a
  second run of the same firmware, which meets its hot code in a slightly different order,
  compiled nearly everything again. It now records, per block source, the library that holds
  it, and the panel looks for newly hot code every second (it was every five). In the panel at
  full pace with no browser, second run of each:

  | | Before these two | After |
  | --- | --- | --- |
  | CyDrums: wall time to its main screen | 41 to 43 s | 20 to 23 s |
  | CyDrums: idle on the main screen | 0.82× | 0.92× to 1.08× |
  | Synthesiser: from start, silent | 0.7× to 0.85× for 15 s, then 2.1× | 2.3× to 2.4× throughout |
  | Synthesiser: first seconds of two new notes | 0.86× to 0.96× for about 10 s | 1.37× for under 5 s |
  | Synthesiser: two notes held | 1.38× | 1.5× to 1.66× |

  The first run of a firmware still waits for the compiler as before. The idle and held-note
  rows also include the lean-path change above.
- **Tried and dropped (2026-11-17): a slot that holds everything an entry needs.** The slot
  repeated the block's function and length, and one machine-wide counter of stores into decoded
  code and of breakpoint changes replaced the walk through each block's dependencies, so an entry
  read one record instead of four. Three interleaved runs against the core without it: stock
  idle 2.87× to 3.00×, with the stream 1.41× to 1.43×, six-track playback 1.77× to 1.79×, with
  the stream 1.07× to 1.08×, a GCC-built synthesiser 1.13× to 1.16×. Those gains of 1% to 4%
  are inside the spread between runs (5% to 10%), and the change adds a counter that every path
  writing guest memory must keep right, so it was not kept.
- Not tried: joining blocks so that one entry covers more cycles.

