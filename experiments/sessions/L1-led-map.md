# Session L1: which LED each panel address lights (planned 2026-11-15; not run)

> **Not run.** Folded into session M1 as part F on 2026-11-15; M1 (2026-11-16) ran in core scope and left part F out.
>
> **Results:** none; the partial LED table from D1 run 7 is in `D1-hello.md`.

**Goal.** Close the panel LED map: see what each of the 101 addresses not yet confirmed on the unit lights, and
how the level (0-10) maps to brightness. `analysis/led_table.py` (from `panel_map.py`'s simulation plus HW-47,
HW-48 and the 2026-11-14 button sweep) currently grades the 144 addresses as 38 seen on the device, 24 whose LED was
seen but not this channel, 53 static only, and 29 the stock never drives (5 seen dark). Nothing the device has shown
so far conflicts with the static table.

**Image.** `experiments/D3_audio_0.3.0.bin` (SHA-256 `38cb0e391d56d69e66971f74a37705d9412cccfc6f5fdd7344d7ef47cc3dfc96`), the
D3 image, which also carries the LED sweep with one step per VALUE detent (0.2.9, the last image run, counts four
steps per detent and would skip addresses). 0.3.0 never ran on the unit; its successors 0.3.1, 0.3.2 and 0.3.4
(sessions M1-M3) carry the same sweep. With no app on the card, VALUE moves the lit address (index 48a + 8b + c,
shown on the status page's LED line as index, a, b, c and level), and encoder D sets the level (0-10, starts at 3).
STEP 1-4 are the D3 tone keys; leave them alone here.

Device state at start: BOOT 1.0.17, PRESET 2.0.22, SYSTEM 3.2.174, MCU 1.00.06 (expected; check SYSTEM INFO)
Known deviations from stock: none
Recovery card prepared: official SmplTrek 3.2.174 update as `SmplTrek.bin` (SHA-256 checked on the card)
Settings: the bring-up image never writes flash, so the stock settings and sounds are untouched; only the SYSTEM image
changes, and step 6 restores it.

## Files on the card (as SmplTrek.bin)

| File | SHA-256 | What it is |
| --- | --- | --- |
| experiments/D3_audio_0.3.0.bin | 38cb0e39...3dfc96 | bring-up image with the LED sweep |
| official SmplTrek 3.2.174 update | (as on the recovery card) | restore at the end |

## Steps

| # | Action | Expected outcome | If different |
| --- | --- | --- | --- |
| 1 | Install 0.3.0 (BOOT MODE, SYSTEM UPDATE), restart, no card or a card without `/APPS/APP.BIN` | status page; LED line reads OFF | stop; follow D3's failure table (it is the same image) |
| 2 | Turn VALUE one detent at a time from index 0 to 143; at each index note what lights (or "dark") in the table below | each address lights the expected LED and colour | record exactly what lit; a mismatch is the finding, do not re-run to "fix" it |
| 3 | At index 63 (1,1,7) and 111 (2,1,7), and over 120-139 (2,3,0 .. 2,5,3): confirm dark | dark | note any LED that lights: an LED the stock never uses |
| 4 | At index 9 (0,1,1, TRK 2 green): turn D from 0 to 10, one step at a time | brightness rises with the level, 0 off | note whether steps look even, and whether any level looks the same as its neighbour |
| 5 | At index 42 (0,5,2, HOME green) set level 6, then index 43 (HOME red) at 6 | HOME green, then HOME red | note the colours |
| 6 | Restore: install the official 3.2.174 update | stock firmware starts | follow the recovery card procedure |

What this cannot distinguish: a dark address could be an unfitted LED or a channel the MCU ignores; either way no
firmware can use it. Brightness is judged by eye, so step 4 only tells whether the levels are roughly even.

## Stop rules

- The image writes no flash; BOOT MODE's update is the only write, and only of the SYSTEM image.
- Abort if the unit does not reach the status page within 10 s (power off by holding the key, then BOOT MODE).

## Evidence capture

A photo or short video at each address where the LED differs from the expectation, and at step 4; stills of
each. Fill in the Seen column below.

## Addresses to check (step 2)

Rows not listed were already seen on the unit (HW-48, button sweep) or seen dark. "device-group" means the same LED
was seen on another channel.

| Sweep | a b c | Expected | Grade now | Seen |
|---|---|---|---|---|
| 17 | 0 2 1 | USB AUDIO red | device-group | |
| 18 | 0 2 2 | USB AUDIO blue | device-group | |
| 19 | 0 2 3 | GLOBAL 3 green | static | |
| 20 | 0 2 4 | GLOBAL 3 red | static | |
| 21 | 0 2 5 | GLOBAL 3 blue | static | |
| 22 | 0 2 6 | TRK 4 green | device-group | |
| 23 | 0 2 7 | TRK 4 red | device-group | |
| 29 | 0 3 5 | STEP 4 red | device-group | |
| 31 | 0 3 7 | STEP 5 red | device-group | |
| 33 | 0 4 1 | STEP 6 red | device-group | |
| 35 | 0 4 3 | STEP 15 red | device-group | |
| 36 | 0 4 4 | STEP 16 green | static | |
| 37 | 0 4 5 | STEP 16 red | static | |
| 39 | 0 4 7 | CLR red | device-group | |
| 41 | 0 5 1 | FUNC red | device-group | |
| 43 | 0 5 3 | HOME red | device-group | |
| 45 | 0 5 5 | MIXER red | device-group | |
| 47 | 0 5 7 | STOP red | device-group | |
| 56 | 1 1 0 | TRK 5 blue | static | |
| 57 | 1 1 1 | TRK 3 green | static | |
| 58 | 1 1 2 | TRK 3 red | static | |
| 59 | 1 1 3 | TRK 3 blue | static | |
| 60 | 1 1 4 | TRK 10 green | static | |
| 61 | 1 1 5 | TRK 10 red | static | |
| 62 | 1 1 6 | TRK 10 blue | static | |
| 63 | 1 1 7 | nothing | unused | |
| 64 | 1 2 0 | EXT SRC green | static | |
| 65 | 1 2 1 | EXT SRC red | static | |
| 66 | 1 2 2 | EXT SRC blue | static | |
| 67 | 1 2 3 | GLOBAL 2 green | static | |
| 68 | 1 2 4 | GLOBAL 2 red | static | |
| 69 | 1 2 5 | GLOBAL 2 blue | static | |
| 70 | 1 2 6 | TRK 5 green | static | |
| 71 | 1 2 7 | TRK 5 red | static | |
| 72 | 1 3 0 | STEP 1 green | static | |
| 73 | 1 3 1 | STEP 1 red | static | |
| 74 | 1 3 2 | STEP 2 green | static | |
| 75 | 1 3 3 | STEP 2 red | static | |
| 76 | 1 3 4 | STEP 12 green | static | |
| 77 | 1 3 5 | STEP 12 red | static | |
| 78 | 1 3 6 | STEP 13 green | static | |
| 79 | 1 3 7 | STEP 13 red | static | |
| 80 | 1 4 0 | STEP 14 green | static | |
| 81 | 1 4 1 | STEP 14 red | static | |
| 82 | 1 4 2 | STEP 7 green | static | |
| 83 | 1 4 3 | STEP 7 red | static | |
| 84 | 1 4 4 | STEP 8 green | static | |
| 85 | 1 4 5 | STEP 8 red | static | |
| 87 | 1 4 7 | OK red | device-group | |
| 89 | 1 5 1 | REC red | device-group | |
| 91 | 1 5 3 | PROJECT red | device-group | |
| 93 | 1 5 5 | EDIT red | device-group | |
| 95 | 1 5 7 | PLAY red | device-group | |
| 96 | 2 0 0 | VOL L | device-group | |
| 97 | 2 0 1 | VOL R | device-group | |
| 98 | 2 0 2 | microphone | device-group | |
| 99 | 2 0 3 | VALUE encoder blue | device-group | |
| 100 | 2 0 4 | VALUE encoder green | device-group | |
| 101 | 2 0 5 | VALUE encoder red | device-group | |
| 102 | 2 0 6 | nothing | unused | |
| 103 | 2 0 7 | nothing | unused | |
| 104 | 2 1 0 | TRK 6 blue | static | |
| 105 | 2 1 1 | TRK 1 green | static | |
| 106 | 2 1 2 | TRK 1 red | static | |
| 107 | 2 1 3 | TRK 1 blue | static | |
| 108 | 2 1 4 | TRK 8 green | static | |
| 109 | 2 1 5 | TRK 8 red | static | |
| 110 | 2 1 6 | TRK 8 blue | static | |
| 111 | 2 1 7 | nothing | unused | |
| 112 | 2 2 0 | TRK 7 green | static | |
| 113 | 2 2 1 | TRK 7 red | static | |
| 114 | 2 2 2 | TRK 7 blue | static | |
| 115 | 2 2 3 | GLOBAL 1 green | static | |
| 116 | 2 2 4 | GLOBAL 1 red | static | |
| 117 | 2 2 5 | GLOBAL 1 blue | static | |
| 118 | 2 2 6 | TRK 6 green | static | |
| 119 | 2 2 7 | TRK 6 red | static | |
| 120 | 2 3 0 | nothing | unused | |
| 121 | 2 3 1 | nothing | unused | |
| 122 | 2 3 2 | nothing | unused | |
| 123 | 2 3 3 | nothing | unused | |
| 124 | 2 3 4 | nothing | unused | |
| 125 | 2 3 5 | nothing | unused | |
| 126 | 2 3 6 | nothing | unused | |
| 127 | 2 3 7 | nothing | unused | |
| 128 | 2 4 0 | nothing | unused | |
| 129 | 2 4 1 | nothing | unused | |
| 130 | 2 4 2 | nothing | unused | |
| 131 | 2 4 3 | nothing | unused | |
| 132 | 2 4 4 | nothing | unused | |
| 133 | 2 4 5 | nothing | unused | |
| 134 | 2 4 6 | nothing | unused | |
| 135 | 2 4 7 | nothing | unused | |
| 136 | 2 5 0 | nothing | unused | |
| 137 | 2 5 1 | nothing | unused | |
| 138 | 2 5 2 | nothing | unused | |
| 139 | 2 5 3 | nothing | unused | |
| 140 | 2 5 4 | STEP 9 green | static | |
| 141 | 2 5 5 | STEP 9 red | static | |
| 142 | 2 5 6 | STEP 11 green | static | |
| 143 | 2 5 7 | STEP 11 red | static | |
