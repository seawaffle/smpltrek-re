# Stock digital audio playback

The unmodified 3.2.174 SYSTEM plays an SD-card WAV through its original SAMPLE POOL preview. It
runs with the low-store option and the built-in USB status response (both later measured on the
unit; emulator README, "Bench results applied"); neither was broadened for audio. Default strict
execution stops at the USB null store.

```sh
python3 -B emulator/tests/stock_audio.py --conditional
python3 -B -m unittest discover -s emulator/tests -p "test_*.py"
```

The optional stock regression generates a two-second, 48 kHz, stereo PCM16 fixture and a private
2 MiB FAT12 SDSC image under `work/emulator/stock-audio/`. An independent read-only FAT parser
first recovers the exact WAV bytes from `/SMPLTREK/POOL/AUDIO/TONE.WAV`. All subsequent file access
and audio work is performed by guest instructions. No constructor, allocator, task, filesystem,
audio processor or driver is replaced.

The input sequence follows reference-manual pages 40–41: FUNC+PROJECT, SAMPLE, Pool, AUDIO,
TONE.WAV, left to the preview column, OK. GPIO input goes through the original scanner/controller.
The stock firmware continues to use its actual SYS/BIOS scheduling and its original McASP/EDMA
programming.

## Observations

The first WAV second contains 750 Hz / 1500 Hz channels with peaks 4096 / 8192. The second second
halves those peaks. At each steady capture, the last 4,096 samples in each output slot match the
appropriate input sine table exactly, with a scale of 16,384 per PCM16 unit. That is one-quarter
of full PCM16-to-PCM32 scaling on this empty-settings profile.
Source channel 1 reaches output slot 0 and source channel 0 reaches slot 1. On the unit, even
buffer words (slot 1) are the left headphone channel (device session M1, HW-61); line outputs were not
checked. Within complete slot-0/1 frames,
the source-left samples lead source-right by one source frame. That offset remains stable across
start, restart, the second half and looping. It is recorded as a profile observation, not a hardware
correctness assertion. McASP/I2S startup phase and the guest's initial TX descriptor alignment need
independent validation; the exporter does not compensate for this offset.

The probe checks initial silence, nonzero playback, silence after OK stop, exact playback after
restart, the quieter second half, and the return to the louder first half beyond the two-second
file duration. It stops again and checks silence. The amplitude change distinguishes progression
through the file and looping from a stuck repeating DMA block. RX/TX counts stay equal, the slot
clock stays at 3,875 DSP cycles per word, and modeled under/overrun counters remain zero. Both the
input card and source WAV stay unchanged, and an independent FAT read checks the private WAV.

Reports retain firmware/core/fixture hashes, external inputs, reached PCs, SD transfers, audio
statistics, exact tone comparisons, stage frames and WAV snapshots. The report still lists exactly
the six known low stores and two USB reserved status reads. Other low reads and unknown MMIO fault.

The completed regression passes 20 checks at cycle 3,610,000,000, after 15,857 dispatched interrupts
and 874,442 transmitted/received words per direction. SD traffic is 787,016 bytes read and 22,528
bytes written. The generated WAV fixture SHA-256 is
`f711333af7cce1723fd42bcef6ab259218796c0a239682b74db3c21d34bf8bdd`.
The source/synthetic suite then (125 tests) passed, including four new independent PCM32 WAV
framing cases. Both firmware CLIs (stock.py, custom.py) reject exporting over their ADC input.

## Separate filename-action fault

OK on the filename invokes a different stop/open path. In the initially idle profile, original
code at `0xc1640b20` calls `0xc16262d0` with A4 = 0. Its global preview pointer at `0xc16f3690` is
also zero. The path eventually calls wrapper `0xc1606ee4`, which adds eight to the null pointer,
then the getter at `0xc1616698` loads from object offset four. Strict execution stops on address
`0x0000000c`, PC `0xc16166a0`. Read-only breakpoints reproduce this without changing registers or
RAM. The longer browser-navigation reproduction reaches it at cycle 2,121,145,843.

The preview column instead calls the original stream opener at `0xc1606fa8`, executes the WAV
header reader at `0xc1616aa0`, and calls `0xc16262d0` with a valid guest allocation. The same getter
then accesses that allocation normally. This route needs no new memory policy. The filename fault
is left explicit under strict mode. With `--reserved-low-reads` the measured low-read rule applies
(emulator README, "Bench results applied"); what the unit does on this path was not measured (the
stock part of sessions M1 to M3 was not run).

## Capture and performance

`audio_capture.py` packages digital output as signed PCM32 WAV at 48 kHz. Channels retain slot 0/1
order. It trims a leading slot-1 word and a trailing incomplete frame as necessary, records those
counts, and never rescales words. Both runners export `audio.wav` beside the original raw
`audio.pcm32`; snapshots hold at most 65,536 words, about 0.683 seconds. This is offline capture,
without analog gain, physical output modeling, or live host playback.

Measured before fast-forward and compiled blocks (2026-11-15; current speed in the emulator README):
a warmed 200-million-cycle active-playback window ran at 0.1408× real time on this host. A
separate 100-million-cycle statistical profile measured 0.1350× with 198 native samples and no
newly decoded guest instructions. About 37% of samples were attributed to packet issue, 29% to
the run loop, 11% to cycle updates and 6% to register-result handling; inline attribution and host
timer granularity limit precision. Host load changes these numbers.

Open here: more WAV formats and rates, the one-frame slot-pair offset, and evidence for the codec's
analogue path. (Track playback, polyphony and real-time host audio came later: the six-track project
and generated songs in the emulator README's "Stock checks", and the stock panel.)

The subsequent dispatch-bookkeeping optimization preserves all 20 checks and the exact observed
states/output at every stage through cycle 3.61 billion. A separate five-slice warmed benchmark
improves from 0.1373× to 0.1495× (8.9%), with exact CPU/audio/OLED state at cycle 500 million.
Generated before/after reports and comparisons are in `work/emulator/performance/dispatch-*.json`.
These are throughput improvements, not a real-time playback claim.

Constant-NOP specialization and event-bounded wait advancement then reach 0.1595× real time in
the same five-slice benchmark: 16.1% above the original 0.1373× baseline. Logical cycles, CPU state,
digital audio and OLED output match exactly at cycle 500 million. All 20 WAV checks and all 54
recorded stage/state/device comparisons also match the original core through cycle 3.61 billion
(the generated input-card path is the sole excluded metadata field). Reports are
`performance/nop-after.json` and `performance/waits-stock-comparison.json` under emulator work.
The source/synthetic suite then passed 129 tests. No guest instructions are skipped: the
optimization only combines wait cycles with no intervening event, preserving every boundary through
normal tick processing.
