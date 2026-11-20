# Session D3-audio-pins: where the outputs come from (planned 2026-11-12, not run)

> **Not run.** Folded into session M1 as part H on 2026-11-15; M1 (2026-11-16) ran in core scope and left part H out except H0 (the restore).
>
> **Results:** none; open questions stay in `docs/04-hardware-access.md`.

**Purpose.** Settle by listening, on the stock firmware, the audio-path questions that code cannot answer
(`docs/04-hardware-access.md`, "Audio for a firmware", "What stays unknown"; claims HW-15, HW-16, HW-17). No image
is built or flashed; nothing is written to flash except the settings block the stock app saves at power-off (see
"Settings likely to change").

Device state at start: BOOT 1.0.17, SYSTEM 3.2.174 (stock), MCU as on SYSTEM INFO. Known deviations: none.
Recovery card: not needed (no update is loaded). Second card: not needed.

## Settings likely to change (named before starting)

These are written to the PREF block by the stock app's `settings_save` at power-off, so each must be put back
before switching off:
- SYSTEM > **SPEAKER MUTE** (toggled ON and back to its starting value);
- the **REC SRC** source, its gain (LOW / NORMAL / HI) and **PAD** ON/OFF, and input **monitoring** on/off;
- if used, a project's track settings for the test sample (prefer a scratch project, or note and restore).
Analogue controls that are not saved but must be noted and restored: **VOL** knob, **INPUT L/R gain knobs**, **Mic
gain knob**. Write the starting value of each in the results table before step 1.

## Equipment

Headphones; a powered speaker or interface on STEREO LINE OUTPUTS (TRS); a phone or second device as a line source;
a dynamic mic or guitar if available. Keep levels low before each change (VOL low, monitoring level low).

## Steps

| # | Action | Expected outcome | If different |
| --- | --- | --- | --- |
| 1 | Note every setting/knob above. Play a sample; listen on speaker, phones (unplugged), line out. | Speaker and line out play. | Stop; record. |
| 2 | Plug headphones in while playing. | Speaker stops, headphones play, **line out keeps playing** (HW-15: line drivers feed everything; switched jack cuts the speaker only). | If line out also stops, the jack switch is upstream of the line-out buffer: record, revise HW-15. |
| 3 | Turn VOL from low to mid, phones in. | Phones level changes. Line out level: expected **unchanged** (inference: VOL after the line outputs). | Line out changes too: VOL is before the line-out buffer; record. |
| 4 | Unplug phones. SYSTEM > SPEAKER MUTE = ON. | Speaker silent; line out (and phones when plugged) unchanged (HW-16: GP2[8] mutes the speaker only). | Line out or phones also mute: GP2[8] is a wider mute; record. Restore SPEAKER MUTE. |
| 5 | REC SRC = built-in mic, monitoring ON (VOL low). | Manual: speaker turns off (feedback guard). | Speaker stays on: record (the code path for this was not found). Monitoring OFF afterwards. |
| 6 | REC SRC = stereo line, line source on INPUT L/R; toggle PAD with monitoring on (low level). | About 20 dB level change. | No change: PAD not as documented; record. |
| 7 | Restore every setting and knob from step 1; power off normally. | Settings saved as at start. | Re-enter and correct before switching off. |

What this cannot distinguish: which GPIO does what electrically (no pin is observable without a bare-metal image or
probes); steps 2-4 only locate the VOL pot, the jack switch and the speaker mute relative to the line outputs. The
I2S channel order and GP4[10] / GP4[12..15] roles need a D3 firmware test (a tone on one channel; driving the pins
from bare-metal code) or a schematic.

## Stop rules

- Any unexpected loud output: VOL down, unplug outputs, stop.
- Do not open SYSTEM UPDATE, BOOT MODE or any card function during this session.

## Results (filled in during/after)

| # | Observed | Matches expectation? | Evidence |
| --- | --- | --- | --- |

Settings restored (list with values): ...
Claims updated: ...
