# Stock USB null-descriptor investigation

The stop at PC `0xc162a4f0` is an original firmware byte store through a null audio-class
device-descriptor pointer. The evidence points to an incomplete adaptation of TI's standalone
audio initializer for Sonicware's composite device. Nothing identifies a missing constructor,
failed allocation or omitted USB register implementation that could supply the pointer. On the unit
such stores to reserved low memory store nothing and raise nothing (device session M2, 2026-11-18,
rows W1-W3: `STW`, `STH`, `STB` at `0x0`, `0x10`, `0x200`). Strict mode faults explicitly; the opt-in
low-write policy lets the original stores execute while keeping faults on reads, fetches and
unresolved error observations. The strict diagnostic is not an observed SYS/BIOS exception or a sign
that the unit crashes.

Reproduce the original guest execution and the independent release comparison:

```sh
python3 -B emulator/usb_probe.py --compare \
  'firmware/smpltrek/SmplTrek v1.0.65.zip' \
  'firmware/smpltrek/SmplTrek v3.0.148.zip' \
  'firmware/smpltrek/SmplTrek v3.2.174.zip'
```

The runtime probe requires the CRC-checked 3.2.174 image with SHA-256
`3b6848b0f041bcf23c73d4b0357d2f3d6dc9e7e03752b32ff7322e91e6814e53`.
It boots normally through the real runtime initializer, scheduler, startup delay and USB composite
entry. Breakpoints only observe execution. From audio entry it advances one guest cycle at a time,
recording the original fetch bytes, decoded packets and register changes until the store faults.
No guest RAM/register values are replaced and no function is hooked. Generated reports and temporary
decoder inputs stay under `work/emulator/usb-investigation/`.

The report records core/firmware hashes, TI source hashes, four RAM/register snapshots, the final
stock report, explicit validation assertions and the release comparisons. It distinguishes emulator
observations, file-format decoding, source references and unverified hardware behavior.
Exit status zero means the expected diagnostic was reproduced; it does not mean stock boot succeeded.

The runtime observations on the empty-card/erased-flash profile are:

| Observation | Cycle | Meaning |
| --- | ---: | --- |
| Runtime initializer returns | 6,968,245 | Original copy-table processing and all 147 constructors have executed. |
| Composite initializer enters at `0xc165be20` | 1,333,972,447 | B4 points to the composite device at `0xc16cb32c`. |
| Audio initializer enters at `0xc162a4a0` | 1,333,972,481 | B4 points to the audio device at `0xc16c8c9c`. |
| Store at `0xc162a4f0` | 1,333,972,500 | B7 is zero; A3 is VID `0x2fd7`; the destination is `0x00000008`. |

There are two distinct `tDeviceInfo` objects:

| Object | Address | Device descriptor at +48 | Configuration headers at +52 |
| --- | --- | --- | --- |
| Composite | `0xc16ecf8c` | `0xc16eec28` | `0xc16d49e0` |
| Audio class | `0xc16ecfd4` | zero | zero |

Both audio fields are zero in the copy-table decoder's output, after actual runtime initialization,
at composite entry and at audio entry. The original composite initializer successfully writes VID
`0x2fd7` and PID `0x0004` into the valid composite descriptor before calling the audio initializer.
The composite descriptor is therefore present and usable; its successful update supplies a useful
control against a general descriptor-load or byte-store failure.

The audio initializer then performs this sequence, decoded from current guest RAM:

```text
0xc162a4b6  stw  a3,*+b5(4)       ; audio instance->info = 0xc16ecfd4
0xc162a4c4  ldw  *+b5(4),b8
0xc162a4d8  ldw  *+b8(48),b7      ; audio info->device_descriptor = 0
0xc162a4f0  stb  a3,*+b7(8)       ; VID low byte to address 8
0xc162a4f4  stb  a3,*+b7(9)       ; VID high byte, if execution could continue
0xc162a50c  stb  b9,*+b7(10)      ; PID low byte
0xc162a514  stb  b9,*+b7(11)      ; PID high byte
```

The null load has completed before the first store; the trace is not a delayed-load interpretation
of a nonzero pointer. Audio instance `0xc150370c` also has a zero configuration-descriptor pointer at
offset 8. The later code loads that pointer and writes attributes at +7 and power at +8. This predicts
additional invalid stores if only the first descriptor pointer were worked around. Strict execution
stops at the first one; the explicit continuation below confirms all six stores. There is no USB0
controller access in the final bounded MMIO trace before the strict fault.

The independent initialized-data decoder finds the same pattern in three releases:

| Release | Audio initializer | Audio info | First VID store | Initial descriptor / config pointers |
| --- | --- | --- | --- | --- |
| 1.0.65 | `0xc170f560` | `0xc17c318c` | `0xc170f5b0` | zero / zero |
| 3.0.148 | `0xc16cf560` | `0xc178a834` | `0xc16cf5b0` | zero / zero |
| 3.2.174 | `0xc162a4a0` | `0xc16ecfd4` | `0xc162a4f0` | zero / zero |

This comparison identifies the explicit initializer/store instruction pattern and reads its target
structure through the copy-table decoder. It is not a claim that the entire functions are identical
or that earlier releases have been booted in the C++ emulator. Each input's CRCs and SHA-256 are
recorded in the report.

TI source references, read without modification:

- `~/ti/C6748_StarterWare_1_20_04_01/usblib/include/usblib.h`: `tDeviceInfo` follows twelve 32-bit
  callback pointers with `pDeviceDescriptor` at +48 and configuration-header pointers at +52.
- `~/ti/pdk_omapl138_1_0_11/packages/ti/drv/usb/src/usb_func/device/usbdaudio.c`: the initialized
  `g_sAudioDeviceInfo` supplies `g_pAudioDeviceDescriptor`. `USBDAudioCompositeInit` assigns a
  configuration descriptor and fixes VID/PID through the device-descriptor pointer. The stock audio
  routine retains these fixups while its corresponding initial fields are zero and its initial
  configuration-pointer assignment is absent. This is a source-level structural comparison, not a
  byte-identical library attribution.
- `~/ti/C6748_StarterWare_1_20_04_01/usblib/device/usbdcomp.c`: the composite device owns its own
  descriptor and VID/PID initialization. Sonicware's composite initializer likewise updates a
  separate valid descriptor. Its MIDI initializer omits the standalone VID/PID/config fixups that
  remain in the audio initializer.

The existing `analysis/usb_desc_map.py` descriptor reconstruction is useful static evidence but
does not settle this fault. Its reference interpreter, `c6sim.Memory`, permits writes at arbitrary
addresses and supplies zero for unmapped reads; its separate boot harness also uses hooks. It can
assemble the valid composite configuration despite the unused audio-class null writes. Successful
descriptor reconstruction in that tool is not proof of hardware reserved-address semantics or of a
complete, strict stock boot.

[TI's C6748 datasheet, section 3.4](https://www.ti.com/lit/ds/symlink/tms320c6748.pdf#page=20)
does not define a normal DSP RAM region at address zero and warns that reserved accesses can have
undefined behavior. [SPRUFK5A sections 7.3 and 10.3–10.4](https://www.ti.com/lit/ug/sprufk5a/sprufk5a.pdf#page=209)
document bus-error status/clear registers and event 127. They do not establish which response this
particular reserved address produces. The runtime probe observes all four EXPMASK registers as
`0xffffffff` at the USB boundaries, so event 127 is masked in the exception combiner. This makes
masked bus-error reporting a plausible avenue, but it does not prove that address zero returns an
error or specify that error's type. Normal unit boots and the unconditional call path support that
these particular stores do not prevent startup. The M2 bench session later measured the CPU side:
such stores complete with no exception and no event flag (EFR, IERR and EVTFLAG0-3 unchanged), and a
read-back returns the CPU's held load data, not the stored value. Bus-error status registers were not
read there.

The model therefore keeps the original stores, distinguishes reserved-bus behaviour from unsupported
device MMIO, and reports every discarded store. Mapping writable null RAM or patching either class
pointer would hide the fault and would not reproduce stock execution.

## Guarded continuation and USB0 model

```sh
python3 -B emulator/tests/stock_smoke.py --usb-reset
python3 -B emulator/stock.py --cycles 1500000000 --reserved-low-writes \
  --output work/emulator/usb-disconnected/result.json
```

The smoke check stops before the legacy status reads described below; it does not claim complete
USB initialization. The longer command continues past the stores. The default runner and
`usb_probe.py` fault at the original null store.

`--reserved-low-writes` applies to CPU stores in `0x00000000..0x006fffff`, below L2 ROM. It matches
what M2 measured at three addresses and widths; it is not a documented SCR/VBUSP behaviour, and the
rest of the range is assumed to behave alike. It creates no low RAM. Every accepted
store records its actual instruction PC, cycle, address, width and value in `reserved_low.writes`.
Reads, fetches, host writes and DMA transfers into that range still fault. The policy requires all
EXPMASK registers masked and conservatively rejects interrupt-combiner or memory-error routing.
After a discarded store, attempts to expose unresolved error events or read group-3 event/error
status fault; BUSERR remains unsupported. A full trace faults instead of losing records. These
guards prevent continuation from supplying invented readback or claiming to model error latches.

[SPRU600I sections 2.2 and 4.2](https://www.ti.com/lit/ug/spru600i/spru600i.pdf) describe configurable
**TI simulator memory checking**, including discarded writes/zero reads when detection is disabled.
That is a simulator policy, not documentation of the C6748 interconnect. No reviewed primary source
establishes a general discarded-write rule for this silicon's reserved regions; the M2 measurement
is the evidence.

The original guest performs these stores with the empty-card/erased-flash profile:

| Cycle | PC | Address | Byte |
| ---: | --- | --- | --- |
| 1,333,972,500 | `0xc162a4f0` | `0x08` | `d7` |
| 1,333,972,501 | `0xc162a4f4` | `0x09` | `2f` |
| 1,333,972,507 | `0xc162a50c` | `0x0a` | `04` |
| 1,333,972,508 | `0xc162a514` | `0x0b` | `00` |
| 1,333,972,511 | `0xc162a522` | `0x07` | `c0` |
| 1,333,972,515 | `0xc162a52c` | `0x08` | `01` |

No low reads/fetches occur before the next fault. This bounds the observation; it does not establish
that no later path can read the region.

(Since 2026-11-20 USB0 also models endpoints, FIFOs and a scripted host: see "USB device and scripted
host" in the [emulator README](README.md). What follows describes the model with no cable, which is
unchanged apart from the endpoint and FIFO registers no longer faulting.)

The disconnected USB0 model implements the C6748 wrapper reset, interrupt source/mask/set/clear/EOI,
core address/POWER/interrupt enables, frame/status reads and CFGCHIP2 PHY status. Reset requires the
PSC1 module-1 clock. Reset completion takes 16 DSP cycles and PHY settling takes 64 cycles, both
functional latencies rather than measured hardware timings. CLKGood/VBUSSense are read-only;
the profile uses the internal 24 MHz reference with no cable or OTG override. Software SOFTCONN
alone generates no host traffic, SOFs, enumeration or interrupts. FIFO/indexed endpoint access,
CPPI DMA, host/session requests, test modes and unimplemented addresses fault.

Stock first reads CTRLR at cycle 1,333,973,605, sets RESET, polls it clear, then polls CLKGood and
disconnects POWER. It next reads **`0x01e0080c`, PC `0xc15e2034`, cycle 1,333,973,723**, an actual
original load, not another descriptor access. Stock's `USBIntStatusControl`
matches the shared StarterWare `drivers/usb.c` routine, including a read of `USB_O_EPCISC` at
core base + `0x40c`; core base is `0x01e00400`. A subsequent unconditional read targets
`USB_O_IDVISC`, core base + `0x44c` (`0x01e0084c`). The shared `hw/hw_usb.h` defines these
Stellaris external-power/ID status registers, but the C6748-specific USB header and
[SPRUH79C table 33-30](https://www.ti.com/lit/ug/spruh79c/spruh79c.pdf) do not list them.
Their C6748 response was measured on the unit in device session M1 (2026-11-16, row I5): both read
0 with no host attached, and stores of 0 to `0x01e00808` and `0x01e00848` have no effect. The model
returns exactly that for aligned CPU word accesses (built in; before the measurement it was the
opt-in `--usb-reserved-status-zero`, since removed); it does not define the Stellaris registers.
With the low-write policy, original USB initialization, codec unmute and start-up all return; stock
reaches the sequencer and responds to GPIO input. Default faults and all other unsupported accesses
remain.
See [the boot investigation](boot-investigation.md) and `tests/stock_boot.py --conditional` for the
bounded conditional result, exact observations and limitations.

Validation includes independent reset/PHY/IRQ/unsupported-access tests and low-write width, trace,
slice, boundary, mask/routing and DMA-rejection tests. The stock smoke stops at cycle 1,333,973,722,
before that reserved read, with 4,856 dispatched interrupts and no audio under/overruns. With the USB
model added, a warmed nonzero-input benchmark measured 0.1280× real time (previous 0.1312×), with CPU
state, audio and OLED equal to the previous core at cycle 400 million: device coverage, not a speed
change.
