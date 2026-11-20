# SmplTrek 3.2.174 calling convention

Scope: the image with SHA-256
`3b6848b0f041bcf23c73d4b0357d2f3d6dc9e7e03752b32ff7322e91e6814e53`.
How the stock code calls its functions (TI's C6000 EABI as compiled by CGT 8.3.13, LIB-3), checked in the stock
code, and the stock interfaces that code from outside the image has called on the unit in device sessions S2 and A4
([`experiments/README.md`](../experiments/README.md)). Scalar and pointer calls only; not a complete description of
the ABI.

## Register and stack convention

Ordinary 32-bit scalar/pointer parameters go in A4, B4, A6, B6, A8, B8, A10, B10, A12, B12; a scalar result in A4.
B3 holds the return PC. A10–A15, B10–B15, ILC and RILC are callee-saved. B14 is DP; B15 is SP. SP stays 8-byte
aligned and points below the allocated frame. The stock code addresses its near data through B14, so code calling
into it from outside the image must leave DP as the stock set it. AMR's low 16 bits are zero across calls.
Aggregates, floating-point pairs, variadic calls and exceptions follow further rules not covered here.
See TI [C6000 EABI, §§3–4](https://www.ti.com/lit/an/sprab89b/sprab89b.pdf).

Stock evidence, checked in the local disassembly:

- Startup loads B15 with `0xc16f1cdc`, then **ANDs it with -8 at 0xc1694594**, producing `0xc16f1cd8`. (The
  unrounded value is not 8-byte aligned; an earlier reading missed this instruction.)
- B14 is initialised to `0xc16f3320` at 0xc1694598–0xc169459c.
- `draw_text` (0xc166f4e0) saves A11, B13:B12, B11:B10 and A10, with four 8-byte SP decrements, keeps B3 in B13
  across calls, and restores the frame. This agrees with the ABI's alignment and preservation rules.

## The session S2 callback

The vtable hook of device session S2 (EXE-2: AppSystemInfo slot 15 redirected to code in an appended section at
0xC3F00000, EXE-1) is a callback that keeps this convention inside the stock graphics task. Its assembly allocates
24 bytes, keeps this/canvas/B3 at SP+4/+8/+12, leaves SP+0 available for a callee, and restores the exact incoming
SP. It never changes the other preserved registers or control registers. All calls use explicit absolute addresses
and register branches: 0xC3F00000 is too far from stock functions for a direct PC-relative call. Branches have five
delay cycles; loads are allowed four intervening cycles. No compact packets, parallel instructions, BSS, run-time
relocations, constructors, heap allocation or exceptions are involved.

## Recovered stock interfaces

Called by the S2 callback on the unit (EXE-5):

| Address | Interface |
| --- | --- |
| 0xc1666da0 | `draw_title(this=A4, canvas=B4)`; original slot 15 |
| 0xc166f4e0 | `draw_text(canvas=A4, text=B4, Point*=A6, grey=B6, mode=A8)` |
| 0xc16aca00 | `Cache_wbInv(address=A4, bytes=B4, type=A6, wait=B6)` |

Called by the session A4 flash-dump code, from the graphics task (all `probable` in the symbol file, from the
wrappers' bodies and their stock call sites; `request_read` is also in EXE-5):

| Address | Interface |
| --- | --- |
| 0xc1602b88 | `file_open(path=A4, mode=B4)` returns `FIL*` in A4 or NULL; allocates the 556-byte FIL itself; `mode` is the FatFs byte (0x32 = `FA_OPEN_APPEND \| FA_WRITE`) |
| 0xc1602b6c | `file_size(FIL*=A4)` returns `f_size` (objsize at FIL+524) |
| 0xc1602ae0 | `file_write(FIL*=A4, buffer=B4, unsigned *count=A6)`: writes `*count` bytes, stores the count written back, returns FRESULT |
| 0xc1602b0c | `file_close(FIL*=A4)`: `f_close` then frees the FIL; returns FRESULT |
| 0xc1694760 | `bios_memalign(align=A4, size=B4)` returns a pointer or NULL; release with `bios_free` |
| 0xc16a4820 | `bios_free(pointer=A4)` |
| 0xc15dfb6c | `HAL::FlashMemoryDriver::request_read(this=A4, address=B4, buffer=A6, length=B6, id=A8)`; `this` is `g_flash_memory_driver` 0xc15033b4; `address` is 24-bit on the **currently selected device**; id -1 waits for completion (task context only); the return value does not report read errors |
| 0xc15fdec0 | `flash_select_address(address=A4)` returns the address on the selected device in A4: device 0 for addresses below 0x01000000, else device 1 and address minus 0x01000000. Must precede every `request_read`; the driver remembers the choice |
| 0xc16ac9e0 | `Cache_inv(address=A4, bytes=B4, type=A6, wait=B6)`, same shape as `Cache_wbInv` |

`Point` holds two 32-bit integers, x then y. Grey is 0–15; the S2 callback uses 15 and mode 1, matching stock call
sites. Mode's meaning is unknown. The original title stub moves canvas from B4 to A4 and tail-branches to
`draw_page_title` with the stock title string. The S2 callback's final branch restores both callback arguments and
B3 first; the normal title and body stay stock.

## Cache operations and code the bootloader loads

The recovered wrapper passes L2WIBAR `0x01844010` to `cache_block_op` (0xc1681140), forwards wait, and ignores type.
TI documents that a ranged L2 writeback/invalidate also writes back/invalidates L1D and invalidates L1P, even with L2
cache disabled. Ranges cover whole 128-byte L2 lines.
See [C674x cache guide, §2.4.3, Table 2-1](https://www.ti.com/lit/ug/sprug82a/sprug82a.pdf).
The S2 `hello` code calls the wrapper with its aligned 4096-byte section, type 0x7fff and wait 1, while execution
is in stock code.

That call happens **after the first fetch of the appended section's code**, so it cannot repair an incoherent
initial entry. The bootloader loads an appended section the same way it loads stock code (EXE-3), and the appended
S2 section loaded and ran (EXE-1). The cache state at the jump is observed (HW-52: no L2 cache, L1P and L1D caches
on), and the bootloader's flash reads go by EDMA straight to DDR with no cache operation on the path (HW-53, static;
[05-bootloader.md](05-bootloader.md) "Cache state at the jump"). A coherence fault with a larger section is not
excluded. Code placed in memory later by code already running (from the card, say) would need its range written
back and L1P invalidated, from already executable code, before a branch into it.
