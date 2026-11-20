# Offline heap snapshots: SmplTrek 3.2.174

`analysis/heap_snapshot.py` validates captured bytes against the default-heap
contract in [07-ram-allocation.md](07-ram-allocation.md). It is a host tool with no
hardware interface. It does not allocate, free, flash, collect RAM or decide that
a retained pointer is safe to release.

```sh
python3 -B analysis/heap_snapshot.py capture.json
python3 -B -m unittest discover -s analysis -p test_heap_snapshot.py -v
```

Exit 0 means the supplied snapshot is structurally consistent. Exit 2 means it
was not validated: corrupt/incomplete data, unsupported configuration or invalid
input. Errors do not by themselves distinguish actual heap corruption from a bad
capture. Successful output always includes `ownership_proven: false`.

## Capture contract

Capture all bytes at one consistent point after heap initialization, during the
same boot. A collector must either hold the recovered heap mutex in task
context while copying the relevant state, or halt all relevant mutators. Holding
the heap gate alone does not prevent arbitrary application/DMA writes to a probe;
its contents must also be stable. The checker trusts the coherence and boot
metadata; it cannot verify how the capture was obtained.

Copy into independently owned storage, then release the gate before serializing
or sending the result. Do not allocate capture storage, call getStats recursively
without a reviewed contract, or perform transport/file I/O while holding the gate.
A bounded collector must report overflow/truncation rather than call it a complete
capture. Traversal itself must validate addresses, order and a node limit before
following a pointer. This document is not an implementation of that collector.

Required JSON fields:

| Field | Meaning |
|---|---|
| `format` | Exactly `smpltrek-heap-snapshot/1` |
| `firmware_sha256` | SHA-256 of the official source BIN from 07-ram-allocation.md; an attestation, not automatic device identification |
| `capture.boot_id` | Nonempty identifier generated afresh for this boot/experiment |
| `capture.phase` | Nonempty lifecycle label, e.g. `after-project-load` |
| `capture.coherent` | Must be JSON `true` |
| `capture.method` | `heap-gate` or `halted`, subject to the stability requirements above |
| `segments` | Array of `{ "address": "0x...", "hex": "..." }`; exact captured bytes, little endian words |

Supply the 24-byte heap object at `0xC16EE910`, plus every reachable eight-byte
free-node header starting at heap+12. Full free blocks need not be copied.
Segments may abut or split a structure, but must not overlap; missing bytes fail
validation. Addresses can be JSON integers or `0x` strings.

Optional `stats` has `total_size`, `total_free_size`, `largest_free_size`. These
must describe the *same coherent state*, not three values sampled before or after
unrelated allocations. They are compared to values computed from the list.

Optional `probe` has:

- `boot_id`: the boot that originally allocated the probe; must match the capture.
- `pointer`: the original malloc result for exactly 256 requested bytes.
- `expected_hex`: exactly 256 expected bytes, saved independently when the probe
  was created. Include an experiment-specific pattern; do not derive the expected
  bytes from the later capture being checked.

Include captured bytes for the probe's eight-byte malloc header and all 256 data
bytes. The checker requires header `{raw=pointer-8, size=264}`, aligned in-heap
bounds, an unchanged pattern, and no overlap with any free block. Only the fixed
simple malloc probe is supported, not arbitrary/aligned allocations.

## Synthetic example

This describes a hypothetical completely free initialized heap. It is **not a
device capture**, evidence of live free capacity, or a suggested source of probe
ownership. Save as JSON to exercise the CLI:

```json
{
  "format": "smpltrek-heap-snapshot/1",
  "firmware_sha256": "3b6848b0f041bcf23c73d4b0357d2f3d6dc9e7e03752b32ff7322e91e6814e53",
  "capture": {
    "boot_id": "synthetic-example",
    "phase": "hypothetical-empty-heap",
    "coherent": true,
    "method": "halted"
  },
  "segments": [
    {"address": "0xc16ee910", "hex": "d0906cc108000000000000c4000000c40000000408000000"},
    {"address": "0xc4000000", "hex": "0000000000000004"}
  ]
}
```

The test fixtures additionally model a live probe between two free blocks and
mutate headers, links, contents, metadata and statistics to exercise failures.

## Limits

The checker requires an ascending, nonoverlapping, coalesced list with eight-byte
alignment and in-heap sizes. It stops after 65,536 nodes with an incomplete-result
error; that is a tooling bound, not a firmware limit. A NULL free-list head is
structurally compatible with both a full live heap and pre-initialization state;
the collector must establish that startup completed.

A heap reset followed by reallocation can leave a probe outside the free list
with its old bytes and header intact. Thus even a successful check across two
phases does not establish continuity of ownership. Identical stats are also not
proof. Retain lifecycle/allocator observations and boot identity independently.
Do not free a pointer whose ownership has become uncertain.

The captures this format is built for: a baseline; one successful 256-byte
allocation holding a per-boot pattern; a capture after each project or sample
operation; release exactly once, and only while ownership is still established
([07-ram-allocation.md](07-ram-allocation.md) "Open"). No such capture has been
taken on the unit. Stack headroom, contention, audio impact and where a collector
would run are not known. No flashable probe or reserved storage is supplied by this tool.
