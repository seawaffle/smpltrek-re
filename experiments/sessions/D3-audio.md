# Session D3: the audio path from a bare-metal image (planned 2026-11-14; run as part A of M1)

> **Run 2026-11-16 as part A of session M1**, with image 0.3.1 (a superset of 0.3.0): A1-A6 and A8 as expected (first sound, even words = left on headphones, HW-61); A7 and A9 (line outputs, input slot order) skipped for want of a speaker or line source.
>
> **Results:** `M1-bench.md`, "Results", row A; the table at the end of this file stays empty. Image 0.3.0 itself never ran.

**Purpose.** First sound from a firmware with no Sonicware code. Image 0.3.0 of the D1
skeleton brings up the audio path the way the stock app does (04-hardware-access.md "Audio: codec, I2C0, McASP0 and
the DMA ring" and "Audio for a firmware", traced 2026-11-14): the audio GPIOs' mux, directions and levels, EDMA3 and
McASP0, the codec's 40 register writes over I2C0, McASP's start handshake, the unmute and the three analogue power
enables. It then plays a 750 Hz sine at -20 dBFS on a chosen channel from a looping EDMA ring, and shows the receive
ring's peak levels. Every wait is bounded; a stage that fails is reported on the status page, not waited for.

This session is distinct from `D3-audio-pins-plan.md` (listening on the stock firmware; not run).

**Gate:** D1 closed (run 7, 2026-11-14): display, keys, encoders, pads, LEDs, card, loader and the MCU link work.

## What it settles

1. Whether the traced sequence makes sound at all from a bare-metal image (codec over I2C0, McASP0 as clock slave,
   the EDMA ring): the AUD line's stage, codec write failures and transmit block count say where it stopped.
2. **The I2S slot order** (04-hardware-access.md "Channel order", open): the tone on the even buffer words only is
   expected on the LEFT line output and left headphone side, because the stock's buffers carry the left channel in
   even words. Image 0.3.0 copies the stock's one-word-short first transfer (255 words), which audio.c argues is what
   puts even words into slot 1 = left. M1 A4-A6 confirmed this on headphones (operator, 2026-11-17: even words in
   the left ear, HW-61).
3. Which outputs carry sound with the stock's pin states: line outputs, headphones, and the speaker once GP2[8] is
   released (STEP 4).
4. The input path: a signal on INPUT L / R shows as the IN line's peak of the even / odd words.

## Image

`experiments/D3_audio_0.3.0.bin` (size and SHA-256 in `experiments/README.md`; not published), built deterministically. Also in 0.3.0: encoders count one step per detent (run 7 saw four), the LED sweep's
value stops at 10 (run 7: 11 lights the neighbour), the power-off order gains the DAC mute and `C2`.

Status page lines added at 1 x (the rest as 0.2.9):

```
AUD OFF spk 0 0 1234     tone (OFF / L / R / LR), SPK when the speaker is unmuted, audio_init result (0 = every stage
                         done, else -stage: 2 EDMA PSC, 3 McASP PSC, 4 codec writes failed, 5 McASP start handshake),
                         codec write failures, transmit blocks completed (about 375 per second while the ring runs)
IN 0000 0000 1234        receive ring: peak of the even words, of the odd words (16-bit scale), blocks completed
1L 2R 3LR 4SPK  R PAT    STEP 1 / 2 / 3: the tone on the even words / odd words / both (the same key again: off);
                         STEP 4: speaker mute toggle; REC: the pattern page
```

## Settings likely to change

None in flash: the image writes no flash. The stock app's settings block is untouched. The unit is left on 0.3.0 or
restored to 3.2.174 from card B, the operator's choice as after run 7.

## Equipment and levels

Headphones; a line-level destination on STEREO LINE OUTPUTS if available (a powered speaker or interface, level low);
optionally a line source into INPUT L/R. **VOL knob at minimum before power-on.** The tone is -20 dBFS at the codec
(about 0.14 Vrms at the line outputs if they are the codec's 1.414 Vrms full scale through a unity buffer; inference).

## Steps

| # | Action | Expected outcome | If different |
| --- | --- | --- | --- |
| 1 | Card A with `D3_audio_0.3.0.bin` as `SmplTrek.bin`; HOME + power, BOOT MODE, SYSTEM UPDATE; OK; video the write. | `SYSTEM: V0.2.9 -> V0.3.0`, Erasing, Writing, Verifying OK. | CLR out of anything else; stop and report. |
| 2 | VOL at minimum, nothing plugged in. Power on normally, video running. | Splash stages (`AUDIO` is new, between `MCU` and `CARD`), then the hello app's page. HOME: the status page. | Switches off by itself: note the seconds (a fault code); logo stays: unplug, HOME + power, go to step 10. |
| 3 | Read and photograph the status page. | `AUD OFF spk 0 0 nnnn` with the last number climbing (about 375 per second); `IN 0000 0000 nnnn` climbing too. | `AUD` third number not 0: the stage that failed; note it, continue with the keys (the page still works). Transmit count stuck at 0: McASP sends nothing (clocks from the codec absent?); note. |
| 4 | Headphones on, VOL low. Press STEP 1. | `AUD L`. A steady tone, **left side only**. | Right side only: slot order reversed (record: the 255-word inference is wrong). Both sides: note. Silence: note VOL, try STEP 3, then STEP 4 with phones unplugged. |
| 5 | STEP 1 again (off), then STEP 2. | `AUD R`, tone on the right only. | Record. |
| 6 | STEP 2 again, then STEP 3. | `AUD LR`, both sides, same level. | Record. |
| 7 | Line outputs connected (level low): repeat STEP 1 / 2 / 3. | Tone on LEFT / RIGHT / both line outputs; VOL does not change the line level (inference from D3-audio-pins-plan). | Record which jack carries which. |
| 8 | Unplug headphones. STEP 3 on. Press STEP 4. | `SPK`; the speaker plays the tone. STEP 4 again: silent. | Speaker silent with `SPK`: GP2[8] is not the only speaker gate; record. |
| 9 | Optional: a line source into INPUT L, then R (or a phone at low level). | `IN` first number rises with INPUT L, the second with INPUT R. | Reversed: record (the receive slot order). Nothing: record. |
| 10 | Hold the power key one second. | `BYE`, silence at once (the DAC mute precedes the hold release), off on release. | A pop or thump at power-off: note it (the stock's order was copied; the analogue stage is not powered down first). |
| 11 | HOME + power, BOOT MODE, SYSTEM DIAG; photograph. | all OK, SYSTEM 0.3.0. | Record. |
| 12 | Leave 0.3.0 installed, or card B, SYSTEM UPDATE to 3.2.174. | Operator's choice. | — |

## Stop rules

- Any unexpected loud output: VOL down, unplug, power off. The tone is -20 dBFS with VOL at minimum first.
- Noise, smell or heat: unplug.
- Exactly one write in step 1 (plus the optional restore). CLR out of anything else.

## What this cannot distinguish

- A silent codec does not separate a wrong register from a missing MCLK: the 24.576 MHz source is inferred, not seen.
- The electrical roles of GP4[12..15] stay inference even if sound comes out with them high.
- Speaker and headphone switching is in hardware (a switched jack, inference): this session observes it, not its wiring.

## Evidence capture

Video of step 2 and audio of steps 4-8 if convenient (a phone recording is enough to hear which side); stills of the
status page after each step; DIAG at the end. Quote screen text exactly.

## Results (filled in during/after)

| # | Observed | Matches expectation? | Evidence |
| --- | --- | --- | --- |

Device state at end: BOOT __.__  PRESET __.__  SYSTEM __.__  MCU __.__
Claims updated: (on sound: the codec, McASP and EDMA sequences become observed-device; the slot order closes; the
output and speaker gates get device evidence)
