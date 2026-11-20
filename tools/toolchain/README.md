# Toolchain: GCC tic6x-elf against TI cl6x

Question (2026-11-12): can C6000 code be built with GCC, which needs no TI login, and call into or be
called by code built with TI's cl6x? Answer: **yes, at the C6000 EABI level, in the simulator.** Six compiler pairings of a 45-value interoperability test
produce identical, independently computed results, with the data-page register preserved.

## What was built

- `tools/toolchain/build_tic6x_gcc.sh`: GCC 13.3.0 for `tic6x-elf`, C only, with libgcc and no libc, into
  `tools/tic6x` next to the binutils (prerequisites fetched and built in-tree; no sudo). GCC 13 was
  chosen because a 2024 report (GCC bug 114910) shows a GCC 14 tic6x cross build failing. The build
  took about ten minutes on 16 cores.
- `abi_funcs.c` and `abi_driver.c`: the test. Register arguments past the first few, twelve
  arguments (two on the stack), 64-bit and double register pairs, mixed float/double/int argument
  lists, float and double conversions, 8-byte and 24-byte structs passed and returned by value,
  variadic calls with int and 64-bit arguments, a callback through a function pointer, signed and
  unsigned 32- and 64-bit division and remainder (the `__c6xabi_*` helpers), two loops (SPLOOP
  candidates) and a register-pressure function. The driver stores every result as 32-bit words.
- `abi_build.py`: compiles both files with both compilers, links six pairings with the GNU linker,
  runs each in the C674x simulator and prints a static comparison. `abi_check.py` holds the
  expected words, worked out in Python, and the comparison. `elfsim.py` runs a function from an
  ordinary ELF in `analysis/c6sim.py`. `test_abi.py` repeats the check as a unittest (skips
  without both compilers).

## Results (2026-11-12)

| Pairing: driver + callees + runtime | Result | Cycles |
|---|---|---|
| cl6x + cl6x + TI rts6740_elf.lib | 45/45 words match | 2834 |
| GCC + GCC + libgcc | 45/45 | 1525 |
| cl6x + GCC + libgcc (cl6x caller, GCC callees) | 45/45 | 1825 |
| GCC + cl6x + TI rts (GCC caller, cl6x callees) | 45/45 | 2534 |
| GCC + GCC + TI rts | 45/45 | 2540 |
| cl6x + cl6x + libgcc | 45/45 | 1814 |

Conventions seen to agree in the disassembly, and confirmed by the matching results: arguments in
A4, B4, A6, B6, A8, B8, A10, B10, A12, B12 and then on the stack at SP+4 upward; 64-bit values and
doubles in odd:even register pairs; structs over 8 bytes passed by reference and returned through a
pointer the caller passes in A3; variadic arguments all on the stack; B14 (the data page) never
written by GCC code; division and remainder through the EABI-named helpers (`__c6xabi_divi`,
`__c6xabi_divu`, `__c6xabi_divull`, `__c6xabi_remu`, `__c6xabi_remlli`, `__c6xabi_fixdlli`,
`__c6xabi_fixdu`), which is why TI's runtime library and libgcc are interchangeable at the link line.
The GNU linker links cl6x objects and TI's runtime library without complaint (relocations are the
EABI ones: ABS32, ABS_L16/H16, PCR_S21; no DP-relative ones at -O2 with the default memory model).

Static: GCC's code for `abi_funcs.c` is 1568 bytes against cl6x's 1440. GCC emits no 16-bit
(compact) instructions, cl6x 184 of them; both use SPLOOP for the loops. The simulator's cycle
counts favour GCC's output and libgcc's division helpers here, but the simulator's timing is a model
and the test is call-heavy, so treat that as "not slower", not as a benchmark.

Flags: cl6x `-mv6740 --abi=eabi -O2`; GCC `-march=c674x -mlittle-endian -O2 -ffreestanding
-fno-builtin`; link `tic6x-elf-ld -EL -Ttext=0xC2000000 -e abi_driver`. libgcc's division helpers
carry unwind tables that pull its unwinder in, which needs an `abort` symbol: `abi_stubs.c` provides
one. Any bare-metal image linked against libgcc needs the same, or its own helpers.

## Simulator changes made for this (analysis/c6sim.py)

- Double-precision sources are read over two cycles (low word first, high word in the next cycle,
  SPRUFE8B). cl6x relies on it: `dmul` writes the constant's high word with `set` in the same packet
  as the `adddp` that reads it. The simulator read both words at once and got 10.0 for 11.5.
- `dmv` (C674x, used by GCC for 64-bit moves) and the register form of `ext`/`extu` (libgcc's
  helpers) were added. The firmware never used either, which is why they were missing.

## Not shown

- Mixed GCC / cl6x code on the device. (GCC-built code alone has run on the unit: the bare-metal test images
  of device sessions D1, M1, M2 and M3 were built with this GCC, 2026-11-13 onwards; see `experiments/README.md`.)
- A libc. GCC was built without one; newlib's tic6x support was not tried (the GCC 14 failure
  report involved it).
- C++ (GCC was built C-only) and the TI runtime's non-trivial parts (I/O, heap).

## Note for bare-metal builds (2026-11-12, from building the test images)

GCC addresses small globals through B14 unless told not to, and the link then fails with "SB-relative
relocation but __c6xabi_DSBT_BASE not defined". Build with `-msdata=none` (the D1 test images do), or define a data
page. GCC also places uninitialised globals in a `.far` section: a linker script must treat it as `.bss`, or the
image ships them as zeros (the first D1 build carried an 8 KiB framebuffer that way).
Also: GCC tic6x emits read-only data into `.const` and jump tables into `.switch` (TI names); a linker script
that maps only `.rodata` leaves them as orphan sections, which `objcopy -O binary -j ...` then omits. One test-image
link dropped its callback table that way. Map them, and link with `--orphan-handling=error`.
