# SmplTrek audio engine (3.2.174)

Mapped 2026-11-17 from the disassembly and by running the functions in c6sim. *Simulated* means run in c6sim.
`analysis/audio_engine_map.py` (test: `test_audio_engine_map.py`) reproduces the racks, the file player's mix
and state queries, the clicks, the two curves, the track / USB / EXT mixers, the track EQ planes, the sidechain key,
the send delay and Maximizer roles, the render order and PROJECT LEVEL. The other simulated items (the gain
setters for SEND, level / pan and balance, the EQ filter shapes, the player's state transitions, the TrackDelegate
tap, the SideChainCompressor's gain, Hall and Room, the SOURCE switch, `0xC159A44C`) were run with scripts made
during the mapping and not kept; treat them as readings until a tool repeats them. *Read* means a static reading of
the named addresses; *inference* is said where it applies. Nothing here is observed on the device (see "Checks on
the unit" at the end). SmplTrek only: Lofi-12 XT and CyDrums have their own engines behind the same render callback
(`01-platform-map.md` "Audio engine interface"). Claims AUD-1 to AUD-12; the track / USB / EXT routing is also AUD-13.

DP is B14 = `0xC16F3320`. Blocks are the engine's float blocks: +4 frames (128), +16 the L plane, +528 the R plane
(mono blocks have header {1, 128}).

## One block, in order (AUD-1)

`audio_render_main` (`0xC159AC24`, the render callback at B14+904), every 2.67 ms in Swi context:

1. Input: `audio_fill_input_block` into `g_audio_in_block` (`0xC16DEF70`); input filter, analysis, snapshot to
   `0xC16DF380`. For REC SRC below 12 the record tap (`0xC1599DB8`) and the input
   meter (`0xC1617368`) run on the input block here; the input insert effect runs before or after them (below).
2. `audio_mix_main(out, 0)` (`0xC159A0C0`, read, and simulated in parts):
   1. Clears `g_send_bus` (`0xC16DFFB0`) and `g_post_bus` (`0xC16E07D0`).
   2. The sources: `audio_preview_active()` ? `audio_preview_mix` : `audio_mix_tracks(0xC16EFBB8, out, send)`; then,
      unless the second argument is 1, `audio_mix_usb(post, send)` and `audio_mix_ext(0xC16EFBB8, post, send)`.
   3. Copies `out` into the block `0xC16DE750` (planes `0xC16DE760` / `0xC16DE960`).
   4. If the file player is playing (`0xC1625BF8`: state 1 or 4), `0xC1625D8C(out)` adds the file into `out`.
   5. `0xC15AAAD0()`, a getter returning `0xC16DF790` (the sidechain key block); it does nothing else (simulated).
      The two branches at `0xC159A264`-`0xC159A284` are in flight together, so both paths reach it.
   6. Send effect: if `g_send_effects`+4, `fx[index]->process(send_bus, 0xC16DE750, 0xC16DF790)` (vtable +8; +12
      for index 10, same arguments); otherwise the `0xC16DE750` planes are zeroed.
   7. `out += 0xC16DE750` block, with interrupts disabled.
   8. Master effect: if `g_master_effects`+4 and +8, `fx[index]->process(send_bus, out)` (vtable +8).
   9. `audio_gain_ramp(B14+1128, B14+360, out)`: PROJECT LEVEL, de-zippered over the block.
3. `0xC159A9F8(out)`: with REC SRC 25 and the line PAD off, `0xC1599E64(out)` copies `out` into
   `g_audio_in_block` (mono (L+R)/2 with header 1 when byte `0xC14FB648` is set) and runs the recorder chain
   (input meter, record tap, `0xC15AAAE0`). So "ReSmp" of the whole mix takes the project mix before USB AUDIO,
   EXT SRC, the monitor and MASTER LEVEL (simulated).
4. `0xC15EF9C4(out+16)` (gated by B14+376) and the peak meter slot 15 (`0xC15134B4(15, out)`): no change to the
   samples at boot state (simulated); what `0xC15EF9C4` does when its gate is on is open.
5. `out += g_post_bus` at unity (inline at `0xC159B3C8`-`0xC159B524`, interrupts disabled; simulated).
6. `0xC165F030(out)`: a tap gated by byte B14+1197, then `0xC1688414`; no change at boot state.
7. `audio_mix_input_monitor` (`0xC159AA54`): the input snapshot times the monitor gain (HW-30 for the built-in mic).
8. `audio_output_gain_ramp` (`0xC159ABF0`): ramp B14+1132 towards B14+520 = curve(MASTER LEVEL, g_settings+0x44)
   (`0xC158D06C`).
9. Output meter `0xC16173C8` (peaks at `0xC1503A30`).
10. USB audio send to the computer (`0xC168F014`, HW-40).
11. Pre-count, then metronome clicks (`0xC1685CEC`), added last: after MASTER LEVEL and after the USB send (simulated
    with the output gain at 0: the click is still in `out` at full amplitude). That the click is therefore not sent
    over USB follows from the order (not simulated on the USB side).

## Track mix

`audio_track_render` (`0xC15A9E6C`) for track *i*, all simulated with hooked track renders (AUD-2, AUD-3, AUD-4):

1. The track's render, vtable +12 (VoiceTrack `0xC163782C`, LoopTrack `0xC1552260`, GlobalTrack `0xC15E0820`), into
   `g_track_dry_block` and `g_track_send_block`.
2. The insert effect, in place on the dry block, only for the insert track (project word `0xC1500D18`) while INSERT FX
   is on (`0xC1500CFC`, MIDI CC 36); `audio_mix_tracks` passes that test in B4.
3. The track EQ: `g_mixer_channels` (`0xC14D60F0`) are 30 biquads of 120 bytes, entry 2*i* on the dry L plane and
   2*i*+1 on the dry R plane. The send block is not filtered, so sends leave before the EQ.
4. Track vtable +20 with (obj, dry, send): a no-op for USB and EXT; GlobalTrack `0xC15E07E8` with byte +948 = 1 scales
   dry L / R by +12 / +16 and copies dry into the send block (read; what +948 means is open).
5. The `TrackDelegate` tap (MainDelegate + 76, stored at B14+1016): per-track peak meters at `0xC1500B80` + 8*i* (when
   byte `0xC1503400` is set), and the ReSmp feed: when REC SRC = *i* + 12 it records track *i*'s dry block,
   after insert and EQ, before the balance gain (REC SRC 22 = track 10, simulated).

Then `audio_mix_tracks` adds, for tracks 0-12: `out += dry * P` and `send_bus += send * track[+20] * P`, where P is
B14+1008, which `audio_mix_tracks` copies on every call from B14+528. `audio_mix_usb`: `post += dry` and
`send += send * usb[+20]` (no P). `audio_mix_ext`: `post += dry * E` and `send += send * ext[+20] * E`, E = B14+1012
copied from B14+532.

**The gains** (AUD-2, AUD-9; the setters simulated with scripts not kept):

| Field | Set from | Curve |
|---|---|---|
| track +20 (send gain) | TRACK SEND, 0-127 (CC 63), by `0xC15C6008(track, value, mute)`; mute gives 0 | `0xC167EB74`: (v/63)² up to 63, then 1 + (v - 63)/64; 63 = 1.0, 127 = 2.0 |
| track +12 / +16 (level, pan) | `0xC15C5B50(track, level, pan, mute)` | +12 = G (1.5 - 0.5 pan/63), +16 = G pan/63, G = level curve; mute zeroes both. How each track class's render uses them is not read |
| B14+528 / B14+532 (P, E) | PRJ-EXT BALANCE (g_settings+0x3C; CC 35, DialogExtBalance), `0xC158BEE4` | v ≤ 0: P = 1; v > 0: P = curve(63 - v) (1 = 0.952, 32 = 0.236, 63 = 0); E mirrors for v < 0 |
| B14+360 (project gain) | PROJECT LEVEL, project word `0xC1500CF0`, 0-127, default 100 (DialogProjectLevel, CC 34), setter `0xC158AD40` | level curve `0xC167EAC8`: 100 = 1.0, 127 = 2.0, 63 = 0.2512 |
| B14+520 (output gain) | MASTER LEVEL (g_settings+0x44) | the same level curve |

So the balance trades the project tracks (P) against EXT SRC (E); USB AUDIO is not on the balance. PROJECT LEVEL
scales the tracks and the effects but not USB AUDIO or EXT SRC, which join after it on the post bus.

**EQ filter types** (`0xC15C5C2C(track, type, freq, amount, …)`, simulated shapes, names inferred): 0 or amount 0 flat;
1 high-pass; 2 and 5 shelf-like (also set the pre / post scale fields +104 / +108 to 0.41 / 2.43); 3 band-pass; 4
peaking; 6 low-pass. Fields: +0 48000, +4 1/fs, +8 2π/fs, +12 π/fs, +36 / +40 a1 / a2, +44 / +48 / +52 b0 / b1 / b2;
+32 not read. At boot all coefficients are 0 (dry muted until a project applies its EQ).

## Effects (AUD-4, AUD-5, AUD-6)

Three racks, each {+0 index, +4 enabled, pointers to embedded objects}; process is vtable +8, parameters through
vtable +24, reset vtable +0 (read). The setters store a project word, then the rack field through a clamped store
`0xC168D7E0` (simulated):

| Rack | Address | Members | Enable / select / parameter setters | Project words |
|---|---|---|---|---|
| Send | `0xC14C421C` | 0 StereoDigialDelay, 1 PingPongDelay, 2 ReverseDelay, 3 TapeEcho, 4 Room, 5 Plate, 6 Hall, 7 Arena, 8 Tunnel, 9 Infinity, 10 SideChainCompressor | `0xC158AAD0` (CC 42) / `0xC158B078` (max 10) / `0xC158B22C` | on `0xC1500D1C`, type `0xC1500D20`, parameters `0xC15001B0` + 16 type + 4 p |
| Master | `0xC14C2400` (+8 a second gate) | 0 AnalogRecord, 1 CassetteTape, 2 MultiBandCompressor, 3 EQandLimiter, 4 Maximizer | `0xC158A8A4` / `0xC158AB60` (max 4) / — | on `0xC1500D3C`, type `0xC1500D40`, parameters `0xC1500818` + 20 type + 4 p |
| Insert | `0xC1495288` | 0 Chorus, 1 Flanger, 2 Phaser, 3 InsertDelay, 4 AnalogDelay, 5 Vibrate, 6 AutoWah, 7 Tremolo, 8 RingModulator, 9 SamplerateCrusher, 10 AutoPan, 11 Isolator, 12 TiltFilter, 13 Compressor, 14 RackComp, 15 CleanAmp, 16 CrunchAmp, 17 RockAmp, 18 MetalAmp, 19 BassAmp | `0xC158A930` (CC 36) / `0xC158AC00` / `0xC158AE80` | on `0xC1500CFC`, track `0xC1500D18` (-1 = the input) |

A second set of send setters (`0xC15D9454` / `0xC15D9510` / `0xC15D96F4`, mirrors B14+236 / 240, parameter table
`0xC1500100`) writes the same send rack fields; that it belongs to the drum kit's send FX page is inference.
The master rack's +8 gate is written only in `0xC15139A0`-`0xC1513B1A`: 1 when a new value of project word
`0xC1500D00` is at most 14 (its meaning is open).

**Send effect** (AUD-5, simulated): input the send bus, output the block `0xC16DE750`, third argument the key block
`0xC16DF790`. The dry copy put in `0xC16DE750` by step 2.3 is overwritten, never read, by every member tried. The
output is 100% wet: StereoDigialDelay with an impulse (L 1.0, R 0.5) gives nothing in the first block and the first
echo 23,624 samples later (field +20 = 23623.5), amplitude 0.2698 / 0.1349; Hall and Room start their tail after
about 5 blocks and zero the send bus as they go. Delay parameters (StereoDigialDelay at `0xC14C4250`): p0 and p1 set
the time (+84 / +88 raw, +20 samples), p2 the feedback (+92 raw, +32: 30 = 0.438), p3 the level (+80 raw, +24 = v/63).
Delays, AutoPan, Tremolo and Vibrate override vtable +16 / +20 (a stored value at +96 and a recompute; tempo sync is
inference).

**Master effect** (simulated on Maximizer and EQandLimiter): in place on `out`; the send bus argument is not read
(outputs identical with the bus at 0.3 or 0, the bus unchanged). Maximizer turns a 0.5 square wave into 0.79478.

**Sidechain** (AUD-6, simulated with hooked renders and poked gains): when SEND FX is on and the send type is 10,
`audio_mix_tracks` runs its second loop (`0xC15AA670`): the key track (project word `0xC1500D34`) writes
(L + R)/2 of its dry block into the key block (`0xC16DF7A0` = `0xC16DF790` + 16, header {1, 128}); every track with a
send gain above 0 goes wholly to the send bus (dry gain 0, send gain P), the others to `out` as usual; the key track's
own send is dropped. SideChainCompressor (vtable +12 = `0xC1681C20`) multiplies the send bus by a gain driven by the
key (key 0.9: gain 0.022 within about 5 blocks; release about 20 blocks), writes the result to `0xC16DE750` and zeroes
the key block. So in sidechain mode the compressor's output is those tracks' only path. Its parameters were not read.

## File player and recorder (AUD-7)

`AudioEngine::AudioFilePlayer`, a single module around `0xC1625B74`-`0xC1626400` (class name from the four
`{lambda(AudioEngine::AudioFilePlayer::State)}` callback classes in the RTTI); its stream is an
`AudioEngine::AudioFileStream` at `0xC1500E48` (vptr `0xC16CE690`), its file handle at B14+880, its state at B14+884:

| State | Meaning | Entered by |
|---|---|---|
| 0 | idle | stop `0xC1625C90`; end of file without loop; end of a fade-out; `0xC16262D0` (bind a file, no callback) |
| 1 | playing | `0xC1625C2C(loop)` from 0 or 2 (gain first through `0xC1625C14`) |
| 2 | recording standby | `0xC1626060`, when the sequencer is playing at record start (`0xC1549120`) |
| 3 | recording | `0xC1625BB8` from 0 or 2 (AppSampleRecording, a sequencer-side event at `0xC15D7310`, global track recording) |
| 4 | playback fading out | `0xC1625C90(0)` while playing |
| 5 | auto-record, waiting for the threshold | `0xC1626024`; the next block whose peak exceeds the threshold (`0xC158CEE4`) starts recording with a one-block fade-in |

`0xC1625B74` sets the state and calls the page's callback when it changes. Playback (`0xC1625D8C`, simulated) adds,
not replaces: it asks the resampler (`0xC1630228`, into `0xC14F8798`; not itself simulated) for 128 output frames,
advances the stream by the source frame count the resampler returns (simulated with a stand-in resampler; the rate
read from the file goes into it), and adds the frames with the per-channel gains `0xC15041E4` / `E8` and one-block linear
fades (`0xC1505230`: +4 fade-in, +5 fade-out flag); near the end it fades out and seeks back, staying in state 1 when
looping. An int16 AND mask at `0xC15041F4` (0xFFFF at boot) is applied to the source samples; its use is open.
Recording (state 3) is the input tap `0xC1599DB8`: the block is written to the stream and its peak kept at B14+892.
Users: the AUDIO TEST page (plays `SmplTrekTestAudio.wav`, looped, gain 1.0), SAMPLE POOL and drum instrument file
selection, sample slice and region editing, the SAMPLING page.

## Metronome and pre-count (AUD-8)

`Sequencer::Metronome` (`0xC1503F68`) and `Sequencer::SequencerPrecount` (`0xC1501930`), both `SequencerBeat`, render
through `0xC1685CEC(obj, out+16, frames)`: a square wave of ±127 × amplitude, the same in L and R (simulated):

| Click | Frequency | Length |
|---|---|---|
| Metronome mode 1 | 750 Hz (64-sample period) | 31 cycles, 1984 samples (41 ms) |
| Metronome mode 2 | 375 Hz | 15 cycles, 1920 samples (40 ms) |
| Pre-count | 375 Hz | 15 cycles, 1920 samples |

Volume: METRONOME VOLUME (g_settings+0x4C) through a cubic curve (`0xC158BFD4`): level 3 peaks at 0.0122, 10 at 0.452,
16 at 1.85, past full scale (the float-to-int32 conversion then decides what is heard); 0 silences it. Triggered from
the clock-position handler (`0xC154A460`) while METRONOME is on (g_settings+0x58) or the pre-count is running; the mode
comes from `0xC1572AEC` (mode 1 as the accent is inference).

## Other settings in the path (AUD-10, AUD-11)

- g_settings+4 is SOURCE: 0 advances the internal clock (`0xC1681738`), 1 and 2 the external clock object of HW-31
  (simulated switch; that 1 and 2 are MIDI and SYNC is inference).
- Project word `0xC1500D14` (`0xC158D140`): 1 runs the input insert effect before the record tap and meter (the
  recording is wet), otherwise after (dry). The input insert effect (`0xC159A92C`) runs only when INSERT FX is on and
  the insert track is -1. Which page sets `0xC1500D14` is open.
- `0xC159A44C`'s return value (said to be 1 with PAD on, 3 off) is a leftover register nobody reads (simulated:
  overwriting it changes nothing).

## Open

The per-class track renders (VoiceTrack, LoopTrack, GlobalTrack) and how they use level and pan; GlobalTrack +948;
`0xC15EF9C4` and `0xC165F030` with their gates on; the stop-recording finaliser `0xC1607794`; the auto-record
threshold source; the player's mask word; SideChainCompressor's and most effects' parameters; the delay buffers'
location; project word `0xC1500D00`; the EQ field +32 and the type names. Lofi-12 XT's and CyDrums' engines.

## Checks on the unit (none run)

On the stock firmware, by ear: the metronome's two pitches (750 Hz and 375 Hz) and whether level 16 distorts; that the
metronome is not in the USB audio stream to a computer; that ReSmp of the whole mix leaves out USB AUDIO and EXT SRC;
that a send delay set to 100% shows no dry signal in the send path.
