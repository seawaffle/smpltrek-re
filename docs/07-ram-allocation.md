# RAM allocation: SmplTrek 3.2.174

Static investigation, updated 2026-11-11. Source BIN SHA-256:
`3b6848b0f041bcf23c73d4b0357d2f3d6dc9e7e03752b32ff7322e91e6814e53`.
Scope: one stock allocation/release path, its default heap and gate, configured
failure policy, release/coalescing behavior, and a bounded lifetime-reference audit.
No device execution, flashing, live memory reading, or allocation was performed.

## Finding

The default allocation path uses a SYS/BIOS HeapMem-style object at `0xC16EE910`,
backed by **0xC4000000..0xC8000000 (64 MiB)**. An earlier label, "likely sample
memory", is too narrow: samples may use this heap, but it is also reached by
ordinary C/C++ allocation. These are configured bounds, not available bytes.

The separate gap `0xC16FFA98..0xC4000000`, including `0xC3F00000` where the
appended section of device session S2 was placed (EXE-1, EXE-4), is statically
unclaimed, not shown to be free. Finding a heap above it does not exclude another heap,
stack, DMA buffer or computed-address user in that gap.

## Observed stock path

| Stage | Address | Evidence |
|---|---|---|
| Audio-file stream factory | `0xC15B03D4` | Requests 108 bytes from operator new, checks NULL, then calls constructor `0xC15AFE80`. |
| Object identity | `0xC15AFE80` | Constructor stores vptr `0xC16CE690`; RTTI identifies AudioEngine::AudioFileStream. |
| C++ operator new | `0xC169BA40` | Unique relocation-masked match to `_Znwj` in installed CGT 8.3.13 `new.cpp.obj`; whole body checked against local source. |
| malloc wrapper | `0xC169C6C0` | Calls Memory_alloc with NULL heap, size+8, default alignment, local error block. |
| Memory_alloc | `0xC168CC20` | NULL heap selects the pointer at `0xC16C6CC4`; calls heap function table +8. |
| HeapMem_alloc | `0xC168EA40` | Takes the module gate, calls allocation core `0xC1652CC0`, releases the gate. |
| Stock destroy helper | `0xC15B0384` | Cleans up the stream, calls sized delete at `0xC15B03C4`. |
| Sized delete / delete | `0xC16AC620` / `0xC16AC600` | Thunks reach bios_free, ignoring the sized-delete size argument. |
| free wrapper | `0xC16A4820` | Reads the malloc header, then calls Memory_free with NULL heap and original block/size. |
| Memory_free | `0xC16AD1A0` | NULL heap selects the same handle; calls heap function table +12. |
| HeapMem_free | `0xC16A1520` | Takes the same gate, calls free core `0xC1657F00`, releases gate. |

Names other than the library-matched operator new and RTTI class are analytical
names; original source spellings are not established. The kernel code is byte-identical to SYS/BIOS
6.76.03.01 (LIB-3); neighbouring releases with the same code are not ruled out.
The valid-release and coalescing path is described below. Invalid-free assertions
are not a substitute for caller-side ownership tracking.

## Heap configuration and initialization

The loaded word at `0xC16C6CC4` is `0xC16EE910`. The object's contents must be
read from the **decoded TI initialization records**, not from an ELF file offset:

| Offset | Initial value | Interpretation |
|---|---|---|
| +0 | `0xC16C90D0` | IHeap function table |
| +4 | `8` | Buffer alignment |
| +8 | `0xC4000000` | Buffer start |
| +12 | `0` | Free-list head before heap initialization |
| +16 | `0x04000000` | Original heap size, 64 MiB |
| +20 | `8` | Minimum block alignment |

The layout agrees with TI's [HeapMem Instance_State declaration](https://downloads.ti.com/dsps/dsps_public_sw/sdo_sb/targetcontent/sysbios/6_73_01_01/exports/bios_6_73_01_01/docs/cdoc/ti/sysbios/heaps/HeapMem-src.html).
The field meanings are also supported by the allocation, initialization and
statistics instructions; the reference release is not a claimed firmware version.

`HeapMem_init` at `0xC169C2C0` reads a static instance count of **one** from
`0xC16C2E04`. Its object accessor `0xC16A4BA0` selects `0xC16EE910 + index*24`.
The initializer aligns the buffer, writes a free-node header `{next=0,size=64 MiB}`
at its start, and installs that node at heap+12. The startup-first-function table
at `0xC16D4330` points to this initializer; the descriptor at `0xC16D4338` is
`{count=2, functions=0xC16D4330}`. The startup loop at `0xC168CD20` calls it.

This establishes a configured startup heap. It does not establish that this is
the only allocator or that its contents survive every later application operation.
A bounded scan found the initializer pointer in that startup table and no literal
direct branch/call to it in the objdump listing; computed callers and other reset
implementations remain possible.

## Calling and release contract

C6000 scalar arguments use A4, B4, A6, B6; pointer results use A4.

- `bios_malloc(size)` returns NULL for zero. For a nonzero request it adds eight
  bytes, initializes a 32-byte local error block, and calls
  `Memory_alloc(NULL, size+8, 0, &error_block)`.
- Alignment zero is replaced with **8** by helper `0xC16AD1C0`, reading the
  initialized word at `0xC1503E8C`.
- For a successful raw allocation `r`, malloc stores `r` at `r+0`, `size+8` at
  `r+4`, and returns `p=r+8`.
- `bios_free(NULL)` does nothing. Otherwise it reads `r=word(p-8)` and
  `s=word(p-4)`, then calls `Memory_free(NULL,r,s+(p-r)-8)`.
- A raw Memory_alloc result must be released through Memory_free with its
  allocation size. It must **not** be passed to bios_free, which expects that
  extra header.

## Failure behavior: return policy and RAM output sink

The allocation core returns NULL on no fit. `HeapMem_alloc` releases its gate,
then raises the error whose ID is loaded from `0xC16C1DC4` (**0x001D0000**).
The error dispatcher `0xC16AD040` reads `0xC16C6904`, which points to
`0xC1686D40` (analytical name `Error_policyDefault`). Its configured values are:

| Address | Value | Meaning supported by the code |
|---|---|---|
| `0xC16C6954` | `1` | Return/unwind policy; zero selects the abort path |
| `0xC16C69A4` | `0xC16A1220` | Error raise hook |
| `0xC16C076A` (uint16) | `16` | Maximum nesting depth for calling the hook |
| `0xC16C68B4` | `0x00030000` | Memory_alloc fallback error ID |
| `0xC150174C` | `0` after initialization | C++ new-handler pointer; live state not measured |

`bios_malloc` passes a freshly initialized, non-NULL 32-byte error block.
`Error_policyDefault` populates it through `0xC1690F40`; the ID is at block+12.
At `0xC1686E5C..0xC1686E70`, the abort condition is a NULL original error block
or policy zero. Neither applies to the ordinary malloc no-fit path with these
configured values. `Error_check` (`0xC16A4D60`) recognizes the populated block;
Memory_alloc therefore need not raise its fallback error a second time.
This matches TI's [Error policy and Error_check contract](https://software-dl.ti.com/dsps/dsps_public_sw/sdo_sb/targetcontent/sysbios/6_73_00_12/exports/bios_6_73_00_12/docs/cdoc/xdc/runtime/Error.html).
It does **not** justify calling Memory_alloc with a NULL error block.

The configured hook at `0xC16A1220` tests ID **0x00010000**, not the heap
exhaustion ID. Only that special ID takes `0xC16A1280` and the context-state
setter `0xC16AC960(3)`. The ordinary heap-error branch calls the error-print
routine `0xC168CB20` and returns. That printer reaches formatting helpers
`0xC16A5020` / `0xC16A50A0`. Separately, the policy's logging branch calls
`0xC16A19A0` -> `0xC1674BC0` before the hook. The configured logging/output
backend and final character sink are identified:

- `0xC1674BC0` checks a uint16 enable field at logger object+32 before writing.
  The decoded object at `0xC16EE258` has that field **zero**; alternate logger
  pointer `0xC16C6C74` is also zero. Thus the initialized configuration skips
  record writing. This is startup state, not a guarantee that logging stays off.
- The System formatter `0xC1631300` sends characters through `0xC1694EE0` to
  `0xC1694DA0` when no destination string buffer is supplied. Output size
  `0xC16C6E54` is **128**; state at `0xC16D4D24` initializes to
  `{buffer=0xC1500718, index=0, wrapped=0}`. The sink stores one byte, advances
  the index and wraps it at 128. This is a fixed RAM ring, not a device write.
- Each character is protected by `0xC16AD060` / `0xC16AD080`, using gate handle
  `0xC16C6EF4 -> 0xC16EFCC0`. Thunks `0xC16AD260` / `0xC16AD280` reach
  `0xC16ACB40` / `0xC16ACB60`: save CSR and disable interrupts, then restore CSR.
  The character sink itself neither allocates nor waits on a semaphore.

The **whole formatter is not shown to be bounded in time**.
Its extension pointer at `0xC16C73FC` selects `0xC167A060`; that routine handles
extended conversions and can re-enter the formatter (call at `0xC167A1F4`).
Its label/file conversion helpers and every possible runtime configuration have
not been audited transitively. The resolved RAM sink removes an unknown device
I/O dependency; it does not prove arbitrary error formatting is reentrant or
safe under every failure condition.

Conclusion: there is a recoverable NULL path under the configured policy,
conditional on error reporting returning. This is stronger than merely spotting
a NULL-return instruction, but is not proof that exhaustion is harmless or
bounded in time. Heap exhaustion has not been tried on the unit.

Operator new maps zero to one and adds a possible retry loop: on failure it
reads `0xC150174C`, invokes a non-NULL handler, and retries. With the initialized
zero handler it returns NULL. No additional materialization of that pointer was
found beyond its two reads in operator new; indirect writes remain possible.

The malloc wrapper's size+8 addition at `0xC169C6D8` has no overflow guard before
its Memory_alloc call, and the allocator also rounds sizes upward, so a size
within 8 of 2^32 wraps to a small request (inference from the arithmetic).

## Valid release and coalescing

The core `0xC1657F00..0xC16584B8` receives heap/block/size in A4/B4/A6.
The wrapper already holds the heap's mutex. Following the valid-input path:

1. `0xC1658020..0xC1658048` reads minimum alignment at heap+20 and rounds the
   supplied size up to that alignment. It begins with the free-list head at
   heap+12 and uses that field as a sentinel predecessor.
2. `0xC1658164..0xC16582D8` walks next pointers in ascending address order,
   retaining the predecessor until it reaches a node at/above the freed address
   or the end of the list.
3. `0xC16582E8..0xC165830C` installs the freed block as a free node:
   `{next=successor, size=rounded_size}`, then links the predecessor to it.
4. `0xC1658434..0xC1658458` merges the successor when
   `freed_block + rounded_size == successor`, adding its size and skipping its
   node. `0xC1658460..0xC1658498` similarly merges the predecessor if adjacent;
   the sentinel is excluded from that test.

The function also contains assertion paths through `0xC1690E80` for misalignment,
out-of-heap ranges and overlapping free nodes (e.g. source-line values 401, 423,
429 and 446 in the call arguments). Their enabled state and failure behavior
are not established. Apart from them, the free core does not reject double
frees or interior pointers. Release returns capacity to the shared pool.

## Heap lifetime: bounded static result

A scan of MVK/MVKH constant pairs in the full code listing, aligned pointer words
in loaded non-code sections, and aligned words in decoded initialization data
found the following references. Instruction addresses below identify the MVKH
that completes the constant:

| Target | References found |
|---|---|
| Default-handle slot `0xC16C6CC4` | `0xC168CC4C`, `0xC168CC5C` (Memory_alloc); `0xC16AD1A4` (Memory_free) |
| Heap object base `0xC16EE910` | `0xC16A4BB8` (object accessor); loaded pointer at `0xC16C6CC4` |
| Heap initializer `0xC169C2C0` | Loaded startup-table word at `0xC16D4330`; no literal direct call in the listing |
| Object accessor `0xC16A4BA0` | One literal direct call, at `0xC169C2E8`, inside the initializer |
| Backing start `0xC4000000` | Startup zero-fill destination at `0xC16FFA2C`; decoded heap.buffer at `0xC16EE918` |
| Backing end `0xC8000000` | No matching constant pair or aligned pointer word found |

This found **no additional literal-reference reset path**. The only identified
whole-pool reset is startup initialization. It is consistent with a process-wide
heap whose allocations survive until individually released, but project/sample
lifetime is still an inference. The scan misses computed addresses, pointer
aliases, dynamic object construction and generic helpers reached through a
handle. In particular, generic HeapMem_restore-style code need not contain a
literal default-heap address. TI documents that [HeapMem_restore invalidates live allocations](https://software-dl.ti.com/dsps/dsps_public_sw/sdo_sb/targetcontent/sysbios/6_34_02_18/exports/bios_6_34_02_18/docs/cdoc/ti/sysbios/heaps/HeapMem.html);
that reference describes the risk, not evidence that this firmware calls it.

A project/stream lifecycle trace gives concrete call paths:

| Operation | Observed path | What it establishes |
|---|---|---|
| Project selection | DialogProjectSelect control handler `0xC1658F00` calls `0xC1658AA4`; its changed-selection path calls `0xC154D928`, then reaches load helper `0xC158AFE0` | A concrete teardown/load entry point to investigate, rather than only scanning heap-address literals |
| Track reset | `0xC154D928` loops over ten tracks through `0xC154D8B4`; `0xC154D828` dispatches on the track type at `0xC16ED768[index]` | Teardown includes type-dependent callbacks; this dispatch has not been exhaustively followed |
| Project file buffer | `0xC158AFE0 -> 0xC162C5D4 -> 0xC162C528`: open, size, allocate via `0xC1694760`, read, parse via `0xC161B378`, then `bios_free` at `0xC162C594` or `0xC162C5A4`, close | The observed read-success/read-failure paths release a temporary file buffer individually; the parser's transitive effects remain open |
| AudioFileStream owner | `0xC1637D84` with argument B4=1 creates a stream and stores it at owner+48; the other branch destroys a non-NULL owner+48 through `0xC15B0384` and clears the field | One explicit per-object release path; the owners/callers and all sample lifecycle paths remain to be established |

None of these observations proves the absence of a generic heap restore elsewhere.
Not followed: the type-dispatch targets of `0xC154D828` and the project parser
`0xC161B378`, including their indirect calls. Whether an allocation survives
project and sample operations is not observed.

## Gate and measurement interface

HeapMem allocation, release and statistics all load their gate handle from
`0xC16C2D9C`, which contains `0xC16ED4A8`. Its initialized function table is
`0xC16CB44C`. Entry reaches `0xC1681320`; exit reaches `0xC16A4AE0`.

Entry compares gate+4 with the current task. A different owner leads to a call
of `0xC164FAE0` with the embedded semaphore at gate+8 and timeout -1; exit clears
the owner and posts via `0xC1685300` for an outermost entry. This supports
GateMutex identification, including recursive-entry handling. Allocation can
wait on the gate, so it belongs to task context; the audio Swi and interrupts
cannot wait on it. TI describes HeapMem's gate and context restrictions in the
same reference above.

`HeapMem_getStats` at `0xC1690940` is table offset +20. It writes three 32-bit
words: total size, total free bytes, largest free block. It obtains total size
from heap+16, walks free nodes starting at heap+12 under the same gate, sums
node sizes and tracks their maximum. **No live statistics were collected.**

## Reproduce the static data evidence

Requires the official ZIP and the existing tic6x tools. This uses the repository's
copy-table decoder and prints startup configuration, not device RAM:

```sh
python3 -B - <<'PYCODE'
import struct, sys
sys.path.insert(0, 'analysis')
import memory_map
p, _, _, _, _, _, regions = memory_map.build_map('firmware/smpltrek/SmplTrek v3.2.174.zip')
assert p.sha256 == '3b6848b0f041bcf23c73d4b0357d2f3d6dc9e7e03752b32ff7322e91e6814e53'
image = memory_map.Image(p.sections)
heap = image.word(0xc16c6cc4)
for r in regions:
    if 'data' in r and r['start'] <= heap and heap + 24 <= r['end']:
        words = struct.unpack_from('<6I', r['data'], heap - r['start'])
        print('heap:', hex(heap), 'words:', [hex(x) for x in words])
        print('backing interval:', hex(words[2]), hex(words[2] + words[4]))
        print('alloc/free/getStats:', [hex(image.word(words[0] + n)) for n in (8,12,20)])
        break
else:
    raise SystemExit('heap object not found in decoded initialization records')
print('static instance count:', image.word(0xc16c2e04))
PYCODE
```

The existing initialization-data tool also reproduces the failure configuration
and static stack bounds:

```sh
python3 -B analysis/init_data.py "firmware/smpltrek/SmplTrek v3.2.174.zip" \
  0xc16c6904:1 0xc16c6954:1 0xc16c69a4:1 0xc16c0768:1 \
  0xc16c1dc4:1 0xc16c68b4:1 0xc150174c:1 --tasks --b14 0xc16f3320
```

For the bounded lifetime scan, use `string_refs.constant_pairs(program.insns)`
for instruction materializations, `program.image.data_words()` for aligned
loaded non-code pointers, and aligned `<I` reads of `InitData.regions` for decoded
data pointers. Filter for the targets in the lifetime table; scan branch/call
operands separately for `0xC169C2C0` and `0xC16A4BA0`. These are reference
finders, not a store/alias analysis.

Instruction evidence: `tic6x-elf-objdump -d --start-address=... --stop-address=...`
on the regenerated ELF, plus Ghidra's existing project opened with `-readOnly
-noanalysis`. `InspectRanges.java` prints existing listing instructions and
incoming references without modifying analysis; `ListRange.java` can disassemble
an explicit missing start within that disposable read-only session.

The decompiler merged neighboring functions and emitted unreachable-block
warnings for these routines. Its pseudocode was not used as an authoritative
contract. Neither Ghidra's recovered references nor literal-address scans are
complete proofs of absence.

## Task stacks and the graphics caller

The independently recovered [static task map](01-platform-map.md#tasks-static-sysbios-tasks-priorities-per-product)
supplies concrete SmplTrek stack bounds (end exclusive):

| Task | Object | Stack interval | Capacity |
|---|---|---|---|
| Main/application | `0xC16E195C` | `0xC126F590..0xC127F590` | 64 KiB |
| Graphics | `0xC16E1A14` | `0xC127FD90..0xC1280D90` | 4 KiB |

These come from decoded Task fields +28 (size) and +32 (base), not measured
stack headroom. All ten discovered static task stacks occupy
`0xC125D590..0xC1281D90`, below the unclaimed gap above; they say nothing about it.

The **normal System Info title callback runs on the graphics task**, whose
configured stack is 4 KiB and whose application-set priority is 15. The static
call chain is:

1. MainDelegate startup `0xC154A980` passes its `Graphics::RenderingObject`
   subobject at **+52** to `graphics_start` (`0xC16641A8`). The latter obtains
   OLEDDriver via `0xC16A1D78`, initializes it via slot 0, binds the graphics task,
   and stores **display at th+8, RenderingObject at th+12** (an earlier reading
   had the two reversed).
2. GraphicsTaskHandler::run (`0xC1629C54`) calls `graphics_render_pass`
   (`0xC1629A80`) at `0xC1629E50`. The pass calls RenderingObject slot 0 at
   `0xC1629AF4` (no overlay) or `0xC1629B70` (overlay path).
3. MainDelegate's secondary vtable `0xC16BAE74` points to thunk `0xC154C548`,
   which subtracts 52 and enters `0xC154C4B4`. That dispatcher reads the current
   controller at B14+860 (`0xC16F367C`), follows child+8, and invokes slot 12.
4. AppSystemInfo's vtable `0xC16C5338` has slot 12 = inherited renderer
   `0xC15D3638`. Its title call at `0xC15D3812` uses slot 15, which is
   **`0xC1666DA0`**, the slot the vtable hook of device session S2 redirected
   (EXE-2; [11-abi.md](11-abi.md)).

This establishes the normal caller, not the absence of other possible callers.
An allocation from this redraw path could block the high-priority graphics task
on the heap gate; 4 KiB is the configured stack, not measured headroom.

The host-side [heap-snapshot checker](08-heap-snapshot.md) validates captured heap
bytes offline: heap configuration, free-list structure, optional statistics and a
fixed 256-byte probe's header/pattern/free-list exclusion. Its tests use synthetic
data only. It does not collect device RAM or establish allocation identity.

## Open

1. The lifecycle frontier above (`0xC154D828` targets, the parser `0xC161B378`),
   and the extended error-formatting paths that graceful out-of-memory would rely on.
2. Live heap statistics: none collected.
3. Allocation lifetime across project and sample operations. Observing it needs
   captures taken in task context: a baseline; one 256-byte malloc (264 heap bytes
   with the eight-byte header) holding a per-boot pattern; captures after each
   operation. Pattern and free-list absence are not enough: a heap reset followed
   by reallocation passes both, so allocation identity must be tracked too, and a
   reboot ends the observation. The probe state itself cannot be assumed safe at
   `0xC3F00000`.

Nothing in this document is observed on the device.

This investigation is confined to SmplTrek 3.2.174. Symbol-carry matches of some
of these functions in other images do not establish their heap configuration,
failure policy or lifetime.

## Tests

- `python3 -B -m unittest discover -s analysis -p test_heap_snapshot.py -v`:
  10 synthetic tests cover free-list invariants, missing/overlapping capture bytes,
  probe/header corruption, free overlap, boot/version mismatch, statistics and limits.
- `python3 -B -m unittest discover -s analysis -p test_memory_map.py -v`:
  8 tests passed, covering the decoded heap, function table, instance count, gate, failure
  configuration, RAM output state, graphics vtable targets and graphics stack bounds.
- `python3 -B -m unittest discover -s analysis -p test_symbols.py -v`:
  2 tests passed, including the function prefix hashes against official images.
- Both Ghidra inspection scripts ran against the existing project in read-only
  mode; the rest used objdump and initialization data. Listing coverage is partial where the saved project has gaps; no claim relies on
  the malformed decompiler pseudocode. No hardware behavior was tested.

The documented synthetic capture and CLI rejection exit code also passed smoke checks.
