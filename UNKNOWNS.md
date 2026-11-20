# What is known and what is still open

An index of the open questions about the SmplTrek family (SmplTrek, Lofi-12 XT, CyDrums: one TI C6748 board, three
firmwares) and the related Sonicware products, by subsystem. It points to where each question is discussed. It does
not replace those documents, and `claims.json` stays the authority on what is established. Answered
questions are in "Resolved" at the end. References give the document and section name. Session codes (M1, D1, C3, ...) are device sessions, listed in
[experiments/README.md](experiments/README.md).

How a question can be answered:
- **S** static reading of the firmware images
- **Sim** the simulator (`analysis/c6sim.py`) or the emulator
- **F** files only: update files, the A4 flash dump, card content
- **D** a non-invasive bench session (a test image on the card, or the stock firmware)
- **B** only with the board open or with another unit. Out of scope: the unit is not opened.

Products: S = SmplTrek, L = Lofi-12 XT, C = CyDrums, all = all three.

## Where the knowledge stands

| Subsystem | Known, with the main claims | Open (routes) |
|---|---|---|
| Update container and CRCs | Fully decoded and resealable; seeds for 14+ products (INT-1..INT-6) | single-release seeds (F) |
| Bootloader 1.0.17 | Traced statically (`docs/05-bootloader.md`); BOOT MODE, recovery, cache hand-off observed (HW-24, HW-52, D0) | logo code, flags, version rules on device (S, D) |
| SPI flash | Layout from the A4 dump; Macronix 128 Mbit x 2, device 0 boot area protected (HW-54) | protect-bit reading, Lofi and CyDrums layouts (S, D) |
| Clocks, DDR, PSC | PLL and divisors decoded (hardware-access "State the bootloader leaves") | DDR timing fields, PSC state at the jump, 744 MHz caveat (S, D) |
| CPU behaviour | Misaligned (all widths, DDR and L2), low and EMIFA reads and stores, reciprocal tables, interrupts in NOP and IDLE measured (HW-57, HW-58, HW-60, HW-62 to HW-67) | the held load data's side (L6), the NOP phase pattern, uncached regions (D) |
| Panel MCU link | Set-up, parser, pad stream rate, LED commands (HW-36, HW-39, HW-46, HW-55) | command meanings, A1 bytes 0-2, start-up needs (D) |
| Keys and encoders | Matrix, bit map, release filter, STEP 1 bounce (HW-47, HW-51, HW-56) | other keys' bounce, filter mechanism, encoder steps on device (S, D) |
| Pads | Channel table, thresholds, hold timings, rate (HW-47, HW-55); Lofi pressure and CyDrums aftertouch (XF-23) | which pages take pressure, CyDrums AT settings, pad feel under foreign apps (S, D) |
| LEDs | Addressing, colours, all buttons, who drives row 0 (HW-48, HW-49) | 101 addresses unseen on the unit, level steps, many callers (Sim, D) |
| Display | Frame layout observed (HW-35); OLED init replayed | controller family, draw_text mode argument (S, B) |
| Audio hardware | Codec, McASP, EDMA, routing, REC SRC, PAD (HW-14..HW-17, HW-26..HW-30) | eleven pins' electrics, MCLK source, receive-side channel order (D; output side observed, HW-61) |
| Audio engine and mixer | Block order, sources, gains, EQ, effect racks, file player, metronome (AUD-13, AUD-1..12) | per-class track renders, recorder details, most effect parameters (S, Sim) |
| Sequencer and sound engine | Clock positions, SYNC tempo (HW-27, HW-31) | VoiceTrack writer, step code, voices: almost unmapped (S) |
| Settings (PREF / PREX) | Every validator, ranges, defaults, many labels (XF-6, XF-13, XF-17) | dozens of unlabelled fields per product (S) |
| Content formats | WAV streams, AFTG and ORSL chunks, PDPT container (XF-11, XF-12) | PDPT fields, slice and tag records, CyDrums SystemCore (F, S) |
| SD card | Command layer, controller, ISR, FatFs disk layer (HW-23, HW-25, HW-42..HW-45) | origin, speed in practice, CyDrums write paths (S, Sim, D) |
| USB | Bring-up, descriptors, usblib origin, MIDI task context, audio path, same in all products (HW-12, HW-18, HW-40, HW-59, XF-10, XF-25) | class-code origin (S) |
| MIDI and SYNC | DIN UART, settings, receive slots, SYNC IN/OUT (HW-27, HW-31) | handler bodies, UART2, SYNC electrics (S, B) |
| Power | Power manager, hold latch, keys, battery thresholds (XF-8, HW-24) | battery channel, GP3[7], busy checks (S, D) |
| RTOS and memory | Tasks, Hwi/Swi, SYS/BIOS 6.76.03.01, heap, copy table (XF-7, LIB-3, MEM-1) | run-time use of the DDR gap, heap headroom (S, D) |
| Factory test mode | Entry and every page's controls in the emulator (HW-50) | seen on the unit, a few page details (D, Sim) |
| Cross-product | Same board and platform layer; button maps; cross-flash proven; hardware layer identical in all 13 releases, per-product hardware use mapped (XF-1..XF-25) | 33 differing app blocks, foreign-app behaviour (S, D) |
| Other Sonicware products | Containers and seeds for the Liven range, ELZ_1, ELZ_1 play; which C674x part each could be (INT-16, INT-17) | content formats, Liven bootloader, product numbers, the Liven part (F) |

## Open questions by subsystem

### Audio engine, mixer and effects (S unless noted)
Mapped in `docs/06-audio-engine.md`, claims AUD-1..AUD-12 (2026-11-17).
- How the VoiceTrack, LoopTrack and GlobalTrack renders use level and pan (track +12 / +16) and fill the send block;
  GlobalTrack byte +948. S, Sim
- `0xC15EF9C4` (gate B14+376) and `0xC165F030` (gate B14+1197) with their gates on. Sim
- The recorder: the stop finaliser 0xC1607794, the auto-record threshold source 0xC158CEE4, the event that turns
  standby into recording (0xC15D7138), the player's int16 mask 0xC15041F4. S
- Effect parameters beyond StereoDigialDelay and Maximizer (SideChainCompressor's especially), the delay buffers'
  location, project word 0xC1500D00 (the master rack's second gate), project word 0xC1500D14's page. S
- Metronome mode 1 versus 2 (accent?), SOURCE values 1 and 2, EQ type names and field +32. S
- `audio_preview_active` / `audio_preview_mix` (0xC1645508 / 0xC1645304): names inferred. S
- Lofi-12 XT's mix (8 sequencer tracks plus USB and EXT) and CyDrums' render callback: not read. `01-platform-map.md`
  "Audio engine interface". S, L / C
- Voice, SoundEngine, SoundEffect and TrackSound behaviour per product. `01-platform-map.md` "How much is shared". S
- On the device: the click pitches, clipping at METRONOME VOLUME 16, no metronome in the USB stream (06-audio-engine.md
  "Bench checks"). D

### Sequencer and sound engine (S)
- Who writes the VoiceTrack entries in `g_track_table` (tracks 0-9 at run time). `06-audio-engine.md`, AUD-13.
- The step code of PrivatePatternTask (0xC2C08700 / 0xC2C53E00) and the PrivateLEDTask object. `01-platform-map.md`
  "Tasks", L / C.
- Whether the internal clock delegate's slot 1 is the clock-position handler 0xC154A264, and whether that handler
  compensates for block-boundary quantisation (2.67 ms) of SYNC OUT and MIDI clock. `04-hardware-access.md` "SYNC".
- The Quick sampling action chain (HomeModeController `on_pad_hold` / `on_pad_hold_long`; on_pad_hold arms the
  pad, on_pad_hold_long acts, identified from the 2.0.129 release notes and the 2800 threshold that first appears in
  2.0.129; the chain itself is not read). `01-platform-map.md` "Panel input".
- Whether one hold count is one pad message (`pad_hold_update` 0xC1657418 counts samples above 2800 and fires after
  60 and 180 more; at 262 messages per second per pad, HW-55, that is about 0.23 / 0.69 s). S, D

### Settings (S unless noted)
- SmplTrek PREF: unclamped words +0x2C, +0x64..+0x78, +0xAC..+0xC4, +0x114; +0x88; +0x28/+0x30/+0x34 unused?; the
  probable labels +0x7C auto save, +0x80 auto record, +0x84 normalise, +0x110 LINK; where the sampling screen's
  monitoring flag lives; which argument carries TIMING REC in the MIDI receive path. `01-platform-map.md` "Settings"
  (584-656). S, Sim
- SmplTrek PREX: +8, +12, +32, +44..+47, +49, +50, the block at +108 and the word at +364; which TRACK COLOR byte
  drives which LED channel. `01-platform-map.md` "Settings block (PREF / PREX)", 674-692. S (older or newer versions may label them)
- Lofi-12 XT and CyDrums PREF: the unlabelled fields (list at `01-platform-map.md` "PREF fields (2026-11-10)"), the page tables for
  +0x134..+0x150, the 4-byte shift, Lofi +0x10 (REC SRC?), CASSETTE index order, PAD VELOCITY 128/129, +0x110 (input
  level?), orphan getters, CyDrums' unclamped words and page labels; PREX meanings. `01-platform-map.md` "PREF fields (2026-11-10)". S, D
- What the per-track channel array is in SmplTrek and Lofi (confirmed per-track MIDI channels only in CyDrums).
  `01-platform-map.md` "MIDI settings (MIDI > CONFIG)". S

### Content formats (F, S)
- PDPT: the fields inside SQPT / SQDK / SQPR / SQDT (and AILS / ACTG), the buffer readers 0xC161E900..0xC166FE60,
  0xC161F0AC, and boot behaviour with no PDPT entry. `01-platform-map.md` "Flash use by the app (cross-flash prerequisites)" ("Flash use by the app").
- Where SmplTrek keeps CHOP / SLICE data (it has no ORSL). `01-platform-map.md` "Audio file commands (AudioFileControlTask; read in each product 2026-11-10)".
- Lofi-12 XT: ORSL slice-record and AFTG field layouts, the Favorite tag bit, odd-pad tag order, whether 0xC2BB84D4
  replaces a file. `01-platform-map.md` "Audio file commands (AudioFileControlTask; read in each product 2026-11-10)", 1700.
- Whether anything calls the `smpl` chunk writer; whether Lofi and CyDrums write the project tempo. `01-platform-map.md` "Audio file commands (AudioFileControlTask; read in each product 2026-11-10)".
- CyDrums: `SystemCore.bin` chunks (WTLS / WTDT / WTNM), `.KitConfig` / `.SoundConfig` / `.EfxConfig`, the three
  ResourceLoader functions (0xC258CBE4, 0xC256F26C, 0xC25B7F98). `01-platform-map.md` "Clock tick (1 ms in all three)".
- CyDrums 2.0.97 beta (XF-18, `01-platform-map.md` "CyDrums 2.0.97 beta"): the auto-rec threshold, the import loader's accepted formats
  (inferred), the mod-LFO and SP-standard sound parameters, and whether the final 2.0 differs from the beta.
- ELZ_1 play `Contents.bin` and its PRESET partitions (PPM1, PPM2, PWD8, PWDG, PWDD, PPTN, PDPT, PKIT). F
- Only formats are recorded here, never Sonicware's content.

### Bootloader and update path
- Which code draws the SONICWARE logo; who reads the flag 0xC707444A; the third store at 0xC7084C50.
  `05-bootloader.md`. S
- When bit 0 of header +12 is cleared, and whether set means "no valid image". `01-platform-map.md` "Flash use by the app (cross-flash prerequisites)". S
- Whether the MCU Boot header written last acts as the install marker. `05-bootloader.md` "Writing (static)". S
- Whether the bootloader's heap or buffers can touch SYSTEM's range before the jump; that it does no cache operation
  at the hand-over (HW-52, second half still static). `05-bootloader.md` "Cache state at the jump". S
- The MCU begin and end command bytes (part of the MCU programming exchange, not traced). `05-bootloader.md` "Panel MCU programming (static)". S
- What ELZ_1 BOOT 1.0.10 shows about which checks predate the seeded format. `05-bootloader.md` "A second bootloader sample: ELZ_1 BOOT 1.0.10 (file, 2026-11-12)". S
- Whether "strictly newer" for BOOT, PRESET and MCU, and "2.0 before 3.x", are enforced on the device (INT-11). S, D
- Whether the bootloader shell is reachable over a UART. S
- What the unit shows after a failed normal boot, and the bad-inner-CRC path after OK (INT-7): read statically only;
  a device test would destroy the installed system, so it is left untested.
- Whether other units carry a bootloader other than 1.0.17 (every claim is from one unit). B (another unit)

### SPI flash
- Reading device 0's status `0C` / configuration `0F` as BP = 0011, TB = 1 by the Macronix register layout, and the
  exact part (MX25L12833F and 12835F share the ID). HW-54, INT-12. S (data sheet), B (marking)
- Whether device 1 is on chip select 1 (both answer the same ID). [M1-bench.md](experiments/sessions/M1-bench.md) "Image 0.3.1", item 2 (FLASH). S
- Lofi-12 XT and CyDrums flash layouts (only the SmplTrek is dumped). `01-platform-map.md` "CyDrums start-up and the card (static, 2026-11-12)". B (another unit)
- Whether CyDrums' device-1 readers (`flash_dev1_read_*`, id 8) are dead code. `01-platform-map.md` "Flash use by the app (cross-flash prerequisites)". S, Sim
- Why A4 revision 1 read differently at device 1 offset 0x500000 (not repeated). `experiments/README.md` "Revision 1 result (2026-11-11)". D

### Clocks, memory and the RTOS
- The DDR2 SDCR (0x00139822) and SDTIMR1/2 fields. `04-hardware-access.md` "State the bootloader leaves, and the clocks". S
- Why PLLOUT 744 MHz exceeds SPRS590 Table 6-4's 600 MHz; whether the ROM table is SPRAB41's (SPRS590 cites SPRAAT2).
  `04-hardware-access.md` "State the bootloader leaves, and the clocks". S, D
- Which PSC modules BOOT 1.0.17 leaves on at the jump. `04-hardware-access.md` "State the bootloader leaves, and the clocks". S, D
- Whether 0xC16FFA98..0xC4000000 (0xC3C00000 in L and C) is used at run time (heaps, stacks, computed addresses).
  `07-ram-allocation.md` "Finding", `01-platform-map.md` "Image layout". S, D
- Heap: whether HeapMem 0xC16EE910 is the only allocator, project and sample lifetimes, teardown paths (0xC154D828,
  0xC161B378), AudioFileStream ownership, assertion paths, the new-handler value; live headroom and stack use. 
  `07-ram-allocation.md`, `08-heap-snapshot.md`. S, D
- Whether the heap configuration and policy hold in Lofi-12 XT and CyDrums. `07-ram-allocation.md` "Open". S
- The 10 differing SYS/BIOS instructions in CyDrums around `mailbox_pend`; the USB task callback at B14+1188;
  AsyncTaskHandler's job type; the tick and Task field layouts. `01-platform-map.md` "Tasks". S, D
- Which stock locks UI-task code must take before calling audio or USB code (menu handlers run on a UI task). S
- Which compiler built `__TI_printfi` (0xC1577B00); the four identical ctor/dtor RTS matches. `01-platform-map.md`
  "Compiler, runtime and SYS/BIOS versions". S

### CPU behaviour (D)
- Misaligned access to uncached or peripheral addresses (every width measured in cached DDR and L2 RAM). HW-57, HW-63.
- Why a load inside an interrupt handler (on .D2T2) left the held load data unchanged while .D1T1 loads replace it:
  per data path, or something about the interrupt (M2 L6). Whether the I6 middle read (4) fits the lane-wise rule.
  Low reads by DMA. HW-58, HW-60, HW-62.
- The NOP interrupt probe's 2:2:1:1 phase pattern: the loop's real length on the unit, or the interrupt period in CPU
  cycles; needs the loop's own period measured (M2 N1). HW-67.
- Tie handling in RCPSP / RSQRSP / RCPDP / RSQRDP rounding (no swept input is a tie). HW-66.
- What the stock's null-read path (getter 0xC1616698) does on hardware after OK on a pool filename (M1 I3, not run).
- Whether `Cache_wbInv(code, size, 0x7FFF, 1)` (0xC16ACA00, SYS/BIOS c64p, through the L2 block registers) invalidates
  L1P.

### Panel MCU and pads
- What `90`, `B1`, `B2` and `C2` mean to the MCU; what `C2`'s other senders 0xC15FBA60 / 0xC15FBC98 are; whether the
  MCU needs `90`, `B1` or `A0` before it streams, and when it starts listening (0.1-2.1 s). HW-46,
  `04-hardware-access.md` "Panel MCU". S, D
- Bytes 0-2 of the `A1` reply (no reader in any app). D (only the MCU side can say)
- A pad press's rise and fall in the stream (M2 P6 failed: its trigger fired on idle noise; fixed in image 0.3.3), the
  battery channel's level on batteries, and whether quick taps change the rate (M1 D4). Order, timing, idle levels and
  rates with pads held: HW-68. D
- Which Lofi pages take the pad pressure (controller slot 10), and the user of Lofi's LED setter table `0xC2DB656C`;
  where CyDrums applies AT THRS, whether VELO CRV or AT CRV picks each curve, how the internal pressure stream (262
  messages per second per held pad) is thinned in the voice code. XF-23, `01-platform-map.md` "Hardware use per
  product". S, Sim
- Whether a foreign product's MCU scales pads the same way, and whether Lofi or CyDrums ship different MCU firmware.
  XF-4. B (another unit)
- What `91` and `B0` do (never sent by the stock, and not sent by any test image here). S, D

### Keys and encoders
- How `control_switch_poll`'s release filter works (history at scanner+32), and why only bits 0-31. HW-51. S, Sim
- Bounce of keys other than STEP 1 (M1 E2). HW-56. D
- Every button sets the bit the table names, with no ghost bits for two keys held; one step per detent and its sign
  on the stock decoder (+10 / -10 for ten detents; 20 or 40 would mean a detent is not one quadrature cycle). HW-37. D
- Which printed key is bit 26 (GP2[3] x GP3[3]): REC by the test page, but AppTuner and AppSystemInfo close on it.
  D1 run 7 points to REC; not stated as settled. `01-platform-map.md` "Key matrix". D
- Whether the board has its own pulls on key, encoder and power inputs. `04-hardware-access.md` "Pin multiplexing (SYSCFG0 PINMUXn, `0x01C14120` + 4n)". D, B

### LEDs
- The 101 addresses not yet seen on the unit, and the level steps (session L1, run as M1 part F: not run). HW-48. D
- The full value range (0-10 work; 11+ spills into the next LED). HW-47. D
- Which page lights which LED and when, per product; STEP LED callers against the manual's colours; REC red;
  input-meter sites 0xC1599F14 / 0xC1599F64; TEMPO white on the bar's first beat; rows 1-4 wrappers. 
  `04-hardware-access.md` "Panel LEDs". Sim, D
- Plane-2 crosstalk, and whether the LEDs sit on three 48-channel drivers. B
- The dormant SPI1 frame engine (3 x 48 outputs, GP2[15], GP7[11..13]): what it was for. S (low value)

### Audio hardware (the D3-audio-pins plan and M1 parts G and H cover most of it; not run)
- GP4[10] (codec RESET?), GP4[12] / GP4[14] / GP4[15] (analogue power or amplifier enables?), GP4[13] (fixed high),
  GP1[2] (built-in mic switch?), GP7[14] (INPUT L front end), GP7[15] (+10 dB stage?), GP3[8] (INPUT or headphone
  jack detect). `04-hardware-access.md` Open 8. D, B
- Whether GP1[3] is the analogue -20 dB line PAD for both inputs; whether GP2[8] mutes only the speaker. D
- The headphone and speaker feed (line outs to the VOL pot to amplifiers, speaker cut by a switched jack); whether line
  out is unaffected by the headphone plug. HW-15. D, B
- The I2S receive-side channel order on the device (a signal on INPUT L alone showing in the even-word peak; D), and
  why the documents read the output side the other way (HW-26, HW-61; S).
- Line-output channels and the input slot order (D3 steps 7 and 9, M1 A7 / A9). D
- The MCLK source (24.576 MHz, inferred to be an oscillator) and the line-out level. HW-14. D (measure fs), B
- Power-off pop with the stock's order; whether a quieter order avoids it; whether the McASP ring survives a codec
  reset. D
- The McASP DIT functions after 0xC16158A0. S
- EDMA channels 25 / 26 under I2C0 after the SPRS590 correction; registers 86 / 93 bits 1:0. S
- The codec part (AIC3106 against 3104 / 3105). B (marking)

### Display
- The controller family (SSD1327 by its commands, inference); grey 0 = black. B, D
- draw_text's mode argument and canvas source; whether 0xC16A1BF0(1000) is a pend with a timeout. S

### SD card
- Whether the protocol layer comes from StarterWare AM335x `mmcsd_proto.c`; card+58 as the CSD TRAN_SPEED byte. S
- Whether the stock runs cards at 23.25 MHz in practice; single-block access cost. D
- CyDrums card writes on user actions, in card-reader mode and with `/CyDrums` present; where CyDrums loads settings
  before `settings_apply_all`; its mount function after `f_mount`. Sim, S
- The role of GP4[1] (second SD pin, driven 0); GP4[0] = card detect, low = card. S, D

### USB
- The origin of the USB audio and MIDI class code (not usblib, not PDK `usbdaudio.c`). S
- Whether any stock caller sends USB SysEx (`MIDIStreamUSB::write` mode != 0); whether 1.0.65 exposed USB MIDI. S, F
- The reserved words with a host attached; the task context of USB MIDI on hardware. D
- Why the DSP crystal is the codec PLL trim reference for an adaptive OUT endpoint. S

### MIDI and SYNC
- The MIDI receive handler bodies per product; MIDI word [2] in Lofi and CyDrums. `01-platform-map.md` "MIDI". S
- Who calls the CC, PC and note senders in Lofi and CyDrums; CyDrums 2.0.97's send block; a simulated check of 2 PPQN
  SYNC in Lofi and CyDrums (XF-24, constants only). S, Sim
- Whether UART2 is set up anywhere. S
- The MIDI TEST page's message sources. Sim
- A GP7[8] edge per pulse at 2 per quarter note (needs a clock source); the SYNC jack electrics. D, B

### Power
- Panel channel 15 as the battery voltage (moves with charge, steady on the adapter); GP3[7] high on batteries;
  whether releasing GP4[11] switches off on the adapter too; GP3[0] low only while held. HW-38. D
- Whether BATTERY TYPE 2 is selectable on Lofi and CyDrums (the LITHIUM label exists in all); whether the second
  battery threshold is hysteresis. `01-platform-map.md` "Interrupts and Swis (2026-11-10; same configuration in all three)". S, D
- Whether the power key feeds the supply in parallel with the hold line. HW-47. D, B

### Factory test mode and UI
- That FUNC at power-on opens it on the unit. HW-50. D
- The ADC page's threshold 3000, LED AUTO, the AUDIO page with its file present, ADC and MIDI pages with pads, the one
  CLR run that did not close LED TEST. `09-factory-test-mode.md`. Sim
- CyDrums' first page with a card mounted (instance 0xC241F168). `01-platform-map.md` "CyDrums start-up and the card (static, 2026-11-12)". S

### Cross-product
- The 33 app blocks that differ between products (`03-platform-shared.md`). S
- Lofi-12 XT's global func + key handling (run-time object at MainDelegate+104) and the bit-27 question; the CyDrums
  button map in its own handlers; func + system over AppNoCard / AppNoSystemCore. `10-cross-flash-button-map.md`. Sim, D
- Lofi-12 XT's own boot clocks (UART and tick would skew on a cross-flash if they differ). B (another unit's dump)
- CyDrums 2.0.97: which input-selector index each sampling label (MIC HIZ DYN LINE USB) passes; its start-up apply
  branch on +0x10. Lofi's input status words 2 and 3. `01-platform-map.md` "Hardware use per product". S, Sim
- Session C3's unreported checklist rows; sessions C4 (its app writes flash) and C5 (no image built), planned, not run.

### Other Sonicware products (F)
- Seeds that rest on one release: MINIMAL, Bass&Beats, Mega Synthesis, Ambient Ø. INT-4.
- Product numbers for the unnumbered products; why CyDrums and ELZ_1 play share family 8.
- What the Liven bootloader checks beyond the container (no bootloader in any file); the Liven backup SysEx protocol.
- ELZ_1 v7.0 rev-1 header variant. `hw_inventory.py` reads the legacy images' sections (2026-11-18); the
  integrity parser still rejects the layout.
- Which DSP part (2026-11-18, INT-16, INT-17): every image was built for the C6742/C6746/C6748 class. ELZ_1 and ELZ_1
  play drive the LCD controller, so need a C6748. SmplTrek, Lofi-12 XT, CyDrums and MINIMAL need at least a C6746. The
  Liven code fits all three, the C6742 included, and the firmware cannot narrow it further; only a board photo can.
  On this unit, C6746 against C6748 could be checked without opening it by reading an LCD controller, SATA or USB 1.1
  register from a test image (present only on the C6748), with care: what a read of an absent block does is not
  known (M1 measured only the reserved low range, HW-58) (D).

### Only with the board or another unit (out of scope)
CN202 as JTAG (HW-4); board and part markings (codec, OLED controller, flash suffix, DSP on this unit); the MCLK
oscillator; the panel MCU's own firmware and any level shifter on its link; the audio amplifier wiring; the SYNC jack
circuit; other units' bootloaders and flash contents.

## Resolved

Questions this index listed that later work answered, with where the answer is:
- Audio engine (2026-11-17, `docs/06-audio-engine.md`, AUD-1..AUD-12): the sources inside `audio_mix_main`, where the
  insert effects run, the track gains and B14+1008, `g_mixer_channels`, the one-index path, the B14+1016 tap,
  0xC1625BF8 / 0xC1625D8C, the generators 0xC1685CEC, `g_settings+4` / `+16`, 0xC158D140, the send and master
  argument roles, 0xC159A44C, whether USB AUDIO and EXT SRC bypass the master effect.
- Recovery from an app that hangs at boot: HOME + power reaches BOOT MODE (device session D0, 2026-11-12, INT-8).
- The flash part family: both devices answer `C2 20 18`, Macronix 128 Mbit, and device 0 carries the boot-area
  protect bits (M1, 2026-11-17, HW-54).
- The I2S output channel order: even words in the left ear (M1 A4-A6, 2026-11-17, HW-61).
- Lofi-12 XT's pad pressure record and CyDrums' extra velocity curve (2026-11-19, XF-23).
- Lofi-12 XT and CyDrums use the same USB audio path, at their 96-frame block; I2C1, EMIFA and TIMER64P2/P3 are unused
  in every product (XF-25).
- CyDrums AUTO POWER OFF 4 = 6 h (2026-11-19, XF-25); the four slot-0 power busy checks and slot 5 (2026-11-14,
  `01-platform-map.md` "Power management").
- CyDrums seeds: confirmed by 2.0.97 beta (2026-11-18, INT-4).
- CyDrums 2.0.97 beta's `SlotInfo.lst` and sampled WAV files (2026-11-18, XF-18).
