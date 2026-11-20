#!/usr/bin/env python3
"""The audio engine of SmplTrek 3.2.174 (audio_render_main, audio_mix_main and what they call), run in c6sim: the effect
racks, the file player, the metronome and pre-count clicks, the level curves, the track / USB / EXT mixers, the
track EQ, the sidechain key, the send and master effect roles and the order of the render stages. Read-only and
simulated. B14 = 0xC16F3320. Blocks are {+0 ?, +4 frames (128), +16 L plane, +528 R plane} of floats.

Each check boots once (shared) and starts from the boot state, pokes its inputs and runs one function, hooking
the callees it does not study. What each one runs (SmplTrek addresses; names are this repository's):
  dry_block_getter  0xC15AAAD0(out), which audio_mix_main always calls, returns 0xC16DF790 (the block passed as the
                    send effect's fourth argument, the sidechain key) and writes nothing.
  racks             g_send_effects 0xC14C421C {+0 selected, +4 on, +8 members}, g_master_effects 0xC14C2400 {+0 selected,
                    +4 on, +8 ?, +12 members}, the insert rack 0xC1495288 {+0 selected, +4 on, +8 members}; members are
                    read until a word is not an object with an RTTI vptr, and named from the vptr.
  file_mix          AudioFilePlayer mix 0xC1625D8C(out), state B14+884 = 1, with the stream getters hooked and the
                    resampler 0xC1630228 hooked to write int16 frames (8192, -16384) and to return the source frames it
                    used (frames x rate / 48000, or a given count); the stream advance 0xC15AFEF8 records what it is
                    told. out holds L 0.25 / R -0.25 before: the player adds (sample / 32768 x gain 0xC15041E4 /
                    0xC15041E8). The resampler is asked for 128 frames whatever the rate, and the stream is advanced
                    by the count it returns (117 at 44.1 kHz is the stub's figure; the real 0xC1630228 is not run).
  player_states     the B14+884 queries 0xC1625BF8, 0xC1625F50, 0xC162600C, 0xC16263D0: the states (0-5) each returns
                    1 for (1 playing, 2 rec standby, 3 recording, 4 fading out, 5 waiting for the threshold).
  clicks            the click generator 0xC1685CEC(obj, buf, 128) on Sequencer::Metronome 0xC1503F68 (started by
                    0xC16915AC(obj, mode)) and Sequencer::SequencerPrecount 0xC1501930 (0xC1685E14), 16 blocks into a
                    zero buffer, METRONOME VOLUME set by 0xC158C064(level): frequency, cycles, length and peak.
  curves            0xC167EAC8 (level, 0-127: 100 -> 1.0, 127 -> 2.0) and 0xC167EB74 (send: (v/63)^2 to 63, then
                    1 + (v - 63) / 64).
  mix_tracks        audio_mix_tracks 0xC15AA344(0xC16EFBB8, out, send) with audio_track_render 0xC15A9E6C hooked to
                    fill the dry block 0xC16E03C0 (L 1, R 2) and the send block 0xC16DFBA0 (L 4, R 8), times 1, 10, 100
                    for tracks 10, 11, 12; track +20 = send level; B14+528 = P (copied to B14+1008). out += dry x P,
                    send += send block x track+20 x P.
  mix_usb, mix_ext  audio_mix_usb 0xC15AAFE8(post, send) and audio_mix_ext 0xC15AABD4(0xC16EFBB8, post, send), the
                    USB / EXT track renders (0xC15EB7F8 / 0xC1661DE4) hooked as above, EQ flat (0xC15C5C2C type 0):
                    post += EQ(dry), send += send block x track+20; EXT both times B14+1012 (copied from B14+532).
  track_eq          audio_track_render(10, 0, ctx) with the GlobalTrack render 0xC15E0820 hooked (dry L 1, R 2; send
                    L 3, R 4) and g_mixer_channels 0xC14D60F0 (120-byte biquads) entry 2t or 2t+1 given b0 (+44) = 0.5.
  sidechain         audio_mix_tracks with the send rack on SideChainCompressor (+0 = 10), SEND FX ON 0xC1500D1C = 1 and
                    the key track 0xC1500D34; track renders dry L 0.1 x (t - 9), R 0.05 x (t - 9): the key track's
                    (L + R) / 2 lands in 0xC16DF7A0 (= 0xC16DF790 + 16).
  send_delay        g_send_effects member 0 (StereoDigialDelay), vtbl+8(fx, g_send_bus 0xC16DFFB0, 0xC16DE750, key),
                    as audio_mix_main calls it, block after block: an impulse (L 1.0, R 0.5) in the send bus in block 0,
                    the dry copy 0xC16DE750 refilled with 0.25 / -0.125 before each call, the key with 0.75.
  master_maximizer  g_master_effects member 4 (Maximizer), vtbl+8(fx, send bus, out) on out = +-0.5 (L) / +-0.25 (R),
                    once with the send bus at +-0.3 and once at 0.
  render_order      audio_render_main 0xC159AC24(out 0xC16DEB60) with audio_mix_main 0xC159A0C0 hooked to write out =
                    0.25 / -0.5 and audio_fill_input_block 0xC159A6EC to write the input block 0.0625 / -0.0625;
                    MASTER LEVEL ramp (B14+1132 current, B14+520 target) = 0.5 or 0; g_post_bus 0xC16E07D0 = 0.125;
                    REC SRC (g_settings+0x10) 7 or 25; the metronome started at level 10.
  project_level     B14+360 (the gain audio_mix_main ends with) at boot and after the setter 0xC158AD40(v), which
                    stores v in the project word 0xC1500CF0 and B14+360 = 0xC167EAC8(v).

Usage (from the repository root; needs firmware/ and work/smpltrek-3.2.174.dis and .rtti.json):
  python3 -B analysis/audio_engine_map.py
"""
from pathlib import Path
import json
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
RTTI = ROOT / "work/smpltrek-3.2.174.rtti.json"
B14 = 0xC16F3320
SETTINGS = 0xC14FAC58
REC_SRC, PAD = 0x10, 0x24                       # g_settings offsets
N = 128                                         # frames per block
L_PLANE, R_PLANE = 16, 528                      # block offsets of the two planes

# blocks and buses
SEND_BUS, POST_BUS = 0xC16DFFB0, 0xC16E07D0     # g_send_bus, g_post_bus
DRY_COPY = 0xC16DE750                           # audio_mix_main's copy of out; the send effect's output
KEY = 0xC16DF790                                # 0xC15AAAD0's block: the send effect's 4th argument
TRACK_DRY, TRACK_SEND = 0xC16E03C0, 0xC16DFBA0  # per-track render blocks
IN_BLOCK = 0xC16DEF70                           # g_audio_in_block
RENDER_OUT = 0xC16DEB60                         # the out block audio_render_main is called with
CTX = 0xC16EFBB8                                # first argument of audio_mix_tracks / audio_mix_ext
TRACKS = 0xC16ED728                             # track object table (track t at +4t); +20 send level
OUT, OUT2 = 0xC0010000, 0xC0011000              # scratch blocks (DDR, unused after boot)
SRC, FILE_OBJ, CLICK_BUF = 0xC0020000, 0xC0030000, 0xC0040000

# racks
SEND_FX, MASTER_FX, INSERT_FX = 0xC14C421C, 0xC14C2400, 0xC1495288
RACKS = {"send": (SEND_FX, 8), "master": (MASTER_FX, 12), "insert": (INSERT_FX, 8)}   # base, members offset

# functions
DRY_GETTER = 0xC15AAAD0
PLAYER_MIX = 0xC1625D8C
PLAYER_QUERIES = {"0xC1625BF8": 0xC1625BF8, "0xC1625F50": 0xC1625F50, "0xC162600C": 0xC162600C,
                  "0xC16263D0": 0xC16263D0}
RESAMPLE, ADVANCE = 0xC1630228, 0xC15AFEF8
PLAYER_GETTERS = {0xC15AFD38: SRC, 0xC15AFDB4: 2, 0xC15AFDF4: 16, 0xC15B09C0: 0, 0xC169F9C0: 0}   # data, ch, bits, seek, cb
GET_RATE = 0xC1606EE4
CLICK_RENDER, METRO_START, PRECOUNT_START, METRO_LEVEL = 0xC1685CEC, 0xC16915AC, 0xC1685E14, 0xC158C064
METRONOME, PRECOUNT = 0xC1503F68, 0xC1501930
LEVEL_CURVE, SEND_CURVE = 0xC167EAC8, 0xC167EB74
MIX_TRACKS, TRACK_RENDER = 0xC15AA344, 0xC15A9E6C
MIX_USB, MIX_EXT, USB_RENDER, EXT_RENDER = 0xC15AAFE8, 0xC15AABD4, 0xC15EB7F8, 0xC1661DE4
USB_TRACK, EXT_TRACK = 13, 14
EQ_SET = 0xC15C5C2C                             # (track, type, freq, amount, a8)
MIXER_CHANNELS, EQ_ENTRY, EQ_B0 = 0xC14D60F0, 120, 44
GT_RENDER, GT_SLOT5 = 0xC15E0820, 0xC15E07E8    # GlobalTrack render (vtbl+12) and vtbl+20
RENDER_MAIN, MIX_MAIN, FILL_INPUT = 0xC159AC24, 0xC159A0C0, 0xC159A6EC
PROJECT_LEVEL_SET, PROJECT_LEVEL_WORD = 0xC158AD40, 0xC1500CF0

# player state (B14+880 file, +884 state, +888 loop) and objects
P_FILE, P_STATE, P_LOOP = B14 + 880, B14 + 884, B14 + 888
P_STREAM, P_RAMP, P_GAINS = 0xC1500E48, 0xC1505230, 0xC15041E4   # stream (+64 start, +68 end, +72 pos); ramp; gains, +16 mask

# sidechain project words
SEND_FX_ON, KEY_TRACK = 0xC1500D1C, 0xC1500D34
SIDECHAIN = 10                                  # g_send_effects index of SideChainCompressor


def fw(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def wf(w):
    return struct.unpack("<f", struct.pack("<I", w & 0xFFFFFFFF))[0]


def r6(x):
    return round(x, 6)


class Session:
    def __init__(self):
        import c6sim
        import hw_compare
        import mmio_trace
        self.c6sim = c6sim
        self.t = mmio_trace.Trace(str(hw_compare.ROOT / hw_compare.PRODUCTS["smpltrek"]["image"]), "smpltrek")
        self.t.boot()
        self.hooks = {a: c6sim.returns(1 if a == 0xC16A1BF0 else 0) for a in hw_compare.HOOKS}
        self.reset()

    def reset(self):
        self.t.state = dict(self.t.boot_state.overlay)
        self.t.regs = {}

    @property
    def mem(self):
        m = self.c6sim.Memory(self.t.boot_state.program.image)
        m.overlay = self.t.state
        return m

    def word(self, address):
        return self.mem.word(address)

    def f(self, address):
        return wf(self.mem.word(address))

    def poke(self, address, value, size=4):
        self.mem.write(address, (value & ((1 << 8 * size) - 1)).to_bytes(size, "little"))

    def pokef(self, address, x):
        self.poke(address, fw(x))

    def block(self, address, left, right, channels=2):
        """Header {channels, frames} and two constant planes (callables of the sample index are allowed)."""
        self.poke(address, channels)
        self.poke(address + 4, N)
        data = bytearray()
        for v in (left, right)[:channels]:
            for i in range(N):
                data += struct.pack("<f", v(i) if callable(v) else v)
        self.mem.write(address + L_PLANE, bytes(data))

    def plane(self, address, n=N):
        return list(struct.unpack(f"<{n}f", bytes(self.mem.read(address, 4 * n))))

    def run(self, fn, regs=None, hooks=None, max_cycles=20_000_000):
        r, _ = self.t.run(fn, regs or {}, hooks={**self.hooks, **(hooks or {})}, max_cycles=max_cycles)
        return r

    def track(self, t):
        return self.word(TRACKS + 4 * t)


def fill_hook(blocks):
    """Hook that writes {address: value} floats over a block's two planes and returns."""
    def hook(m):
        data = {a: struct.pack("<f", v) * N for a, v in blocks.items()}
        for a, d in data.items():
            m.mem.write(a, d)
        return m.R["b3"]
    return hook


# --- 1. 0xC15AAAD0 ------------------------------------------------------------------------------------------------

def dry_block_getter(s):
    """(returned A4, words written outside the stack)."""
    s.reset()
    before = dict(s.t.state)
    r = s.run(DRY_GETTER, {"a4": OUT, "b4": 0, "a6": 0})
    stack = s.c6sim.STACK
    changed = sorted(a for a, v in s.t.state.items() if v != before.get(a, 0) and not stack - 0x10000 <= a < stack)
    return r, changed


# --- 2. racks -----------------------------------------------------------------------------------------------------

def vptr_names():
    names = {}
    for c in json.loads(RTTI.read_text())["classes"]:
        for v in c.get("vtables", []):
            names[int(v["address_point"], 16)] = c["name"]
    return names


def racks(s):
    """{rack: {"header": [words before the members], "members": [class names]}} after boot."""
    s.reset()
    names = vptr_names()
    out = {}
    for rack, (base, first) in RACKS.items():
        members = []
        a = base + first
        while len(members) < 32:
            p = s.word(a)
            if not 0xC0000000 <= p < 0xC2000000 or s.word(p) not in names:
                break
            members.append(names[s.word(p)].replace("SoundEffect::", ""))
            a += 4
        out[rack] = {"header": [s.word(base + k) for k in range(0, first, 4)], "members": members}
    return out


# --- 3. AudioFilePlayer -------------------------------------------------------------------------------------------

def file_mix(s, rate=48000, gains=(1.0, 1.0), source=(8192, -16384), consumed=None):
    """(out L, out R after, frames asked of the resampler, frames the stream was advanced by) for state 1 mid-file.
    The resampler stub returns `consumed`, or frames x rate / 48000."""
    s.reset()
    s.block(OUT, 0.25, -0.25)
    for a, v, *n in ((P_STATE, 1), (P_LOOP, 0), (P_FILE, FILE_OBJ), (P_STREAM + 64, 1000), (P_STREAM + 68, 100000),
                     (P_STREAM + 72, 0), (P_RAMP, fw(1.0)), (P_RAMP + 4, 0, 1), (P_RAMP + 5, 0, 1),
                     (P_GAINS, fw(gains[0])), (P_GAINS + 4, fw(gains[1])), (P_GAINS + 16, 0xFFFF, 2)):
        s.poke(a, v, *n)
    seen = {}

    def resample(m):
        n, dst = m.R["a6"], m.R["b4"]
        seen["asked"] = n
        m.mem.write(dst, struct.pack("<hh", *source) * n)
        m.R["a4"] = n * rate // 48000 if consumed is None else consumed
        return m.R["b3"]

    def advance(m):
        seen["advance"] = m.R["b4"]
        m.R["a4"] = m.R["b4"]
        return m.R["b3"]

    hooks = {a: s.c6sim.returns(v) for a, v in PLAYER_GETTERS.items()}
    hooks.update({GET_RATE: s.c6sim.returns(rate), RESAMPLE: resample, ADVANCE: advance})
    s.run(PLAYER_MIX, {"a4": OUT}, hooks=hooks)
    left, right = s.plane(OUT + L_PLANE), s.plane(OUT + R_PLANE)
    assert len(set(left)) == 1 and len(set(right)) == 1, "planes not constant"
    return r6(left[0]), r6(right[0]), seen.get("asked"), seen.get("advance")


def player_states(s):
    """{query: [states 0-5 for which it returns 1]}; none of them changes the state."""
    out = {}
    for name, fn in PLAYER_QUERIES.items():
        yes = []
        for st in range(6):
            s.reset()
            s.poke(P_STATE, st)
            if s.run(fn) == 1:
                yes.append(st)
            assert s.word(P_STATE) == st
        out[name] = yes
    return out


# --- 4. clicks ----------------------------------------------------------------------------------------------------

def clicks(s, level, source, blocks=16):
    """source: "metronome 1", "metronome 2" or "precount". {hz, cycles, samples, peak} of the rendered click."""
    s.reset()
    s.run(METRO_LEVEL, {"a4": level})
    if source == "precount":
        obj = PRECOUNT
        s.run(PRECOUNT_START, {"a4": obj})
    else:
        obj = METRONOME
        s.run(METRO_START, {"a4": obj, "b4": int(source.split()[1])})
    samples = []
    for _ in range(blocks):
        s.mem.write(CLICK_BUF, bytes(8 * N))
        s.run(CLICK_RENDER, {"a4": obj, "b4": CLICK_BUF, "a6": N})
        left, right = s.plane(CLICK_BUF), s.plane(CLICK_BUF + 4 * N)
        assert left == right, "planes differ"
        samples += left
    nz = [i for i, v in enumerate(samples) if v != 0]
    length = nz[-1] + 1 if nz else 0
    falls = [i for i in range(1, length) if samples[i - 1] > 0 > samples[i]]
    period = falls[1] - falls[0] if len(falls) > 1 else None
    return {"hz": 48000 / period if period else 0, "samples": length, "cycles": length // period if period else 0,
            "peak": r6(max(map(abs, samples)))}


# --- 5. curves ----------------------------------------------------------------------------------------------------

def curves(s, values=(0, 1, 32, 63, 64, 100, 127)):
    """{"level": {v: gain}, "send": {v: gain}}."""
    s.reset()
    return {name: {v: r6(wf(s.run(fn, {"a4": v}))) for v in values}
            for name, fn in (("level", LEVEL_CURVE), ("send", SEND_CURVE))}


# --- 6. mixers ----------------------------------------------------------------------------------------------------

def mix_tracks(s, p=0.5, sends=(0.25, 0.5, 0.0)):
    """audio_mix_tracks: {out: (L, R), send: (L, R), b1008, rendered: [tracks]}."""
    s.reset()
    s.block(OUT, 0.0, 0.0)
    s.block(OUT2, 0.0, 0.0)
    s.pokef(B14 + 528, p)
    for t, g in zip((10, 11, 12), sends):
        s.pokef(s.track(t) + 20, g)
    rendered = []

    def render(m):
        k = {10: 1.0, 11: 10.0, 12: 100.0}[m.R["a4"]]
        rendered.append(m.R["a4"])
        return fill_hook({TRACK_DRY + L_PLANE: k, TRACK_DRY + R_PLANE: 2 * k,
                          TRACK_SEND + L_PLANE: 4 * k, TRACK_SEND + R_PLANE: 8 * k})(m)

    s.run(MIX_TRACKS, {"a4": CTX, "b4": OUT, "a6": OUT2}, hooks={TRACK_RENDER: render})
    return {"out": (r6(s.f(OUT + L_PLANE)), r6(s.f(OUT + R_PLANE))),
            "send": (r6(s.f(OUT2 + L_PLANE)), r6(s.f(OUT2 + R_PLANE))), "b1008": r6(s.f(B14 + 1008)),
            "rendered": rendered}


def _mix_aux(s, which, send, b528, b532):
    s.reset()
    tr = USB_TRACK if which == "usb" else EXT_TRACK
    s.run(EQ_SET, {"a4": tr, "b4": 0, "a6": 0, "b6": 0, "a8": 1})
    s.block(OUT, 0.0, 0.0)
    s.block(OUT2, 0.0, 0.0)
    s.pokef(s.track(tr) + 20, send)
    s.pokef(B14 + 528, b528)
    s.pokef(B14 + 532, b532)
    h = fill_hook({TRACK_DRY + L_PLANE: 1.0, TRACK_DRY + R_PLANE: 2.0, TRACK_SEND + L_PLANE: 4.0,
                   TRACK_SEND + R_PLANE: 8.0})
    if which == "usb":
        s.run(MIX_USB, {"a4": OUT, "b4": OUT2}, hooks={USB_RENDER: h})
    else:
        s.run(MIX_EXT, {"a4": CTX, "b4": OUT, "a6": OUT2}, hooks={EXT_RENDER: h})
    return {"post": (r6(s.f(OUT + L_PLANE)), r6(s.f(OUT + R_PLANE))),
            "send": (r6(s.f(OUT2 + L_PLANE)), r6(s.f(OUT2 + R_PLANE))), "b1012": r6(s.f(B14 + 1012))}


def mix_usb(s, send=0.5, b528=0.5, b532=0.25):
    """audio_mix_usb (dry L 1 R 2, send L 4 R 8, flat EQ): {post, send, b1012}."""
    return _mix_aux(s, "usb", send, b528, b532)


def mix_ext(s, send=0.5, b528=0.5, b532=0.25):
    """audio_mix_ext, same inputs: {post, send, b1012}."""
    return _mix_aux(s, "ext", send, b528, b532)


# --- 7. track EQ --------------------------------------------------------------------------------------------------

def track_eq(s, entry, track=10):
    """audio_track_render(track) with g_mixer_channels entry 2 x track + entry (0 or 1) b0 = 0.5 (others flat):
    {dry: (L, R), send: (L, R)} from dry L 1, R 2 and send L 3, R 4."""
    s.reset()
    s.run(EQ_SET, {"a4": track, "b4": 0, "a6": 0, "b6": 0, "a8": 1})
    s.pokef(MIXER_CHANNELS + EQ_ENTRY * (2 * track + entry) + EQ_B0, 0.5)

    def render(m):
        fill_hook({TRACK_DRY + L_PLANE: 1.0, TRACK_DRY + R_PLANE: 2.0, TRACK_SEND + L_PLANE: 3.0,
                   TRACK_SEND + R_PLANE: 4.0})(m)
        m.mem.write(TRACK_DRY + 4, N.to_bytes(4, "little"))
        return m.R["b3"]

    s.run(TRACK_RENDER, {"a4": track, "b4": 0, "a6": CTX}, hooks={GT_RENDER: render, GT_SLOT5: lambda m: m.R["b3"]})
    return {"dry": (r6(s.f(TRACK_DRY + L_PLANE)), r6(s.f(TRACK_DRY + R_PLANE))),
            "send": (r6(s.f(TRACK_SEND + L_PLANE)), r6(s.f(TRACK_SEND + R_PLANE)))}


# --- 8. sidechain -------------------------------------------------------------------------------------------------

def sidechain(s, key_track=11, send_type=SIDECHAIN, send_on=1):
    """audio_mix_tracks with dry L 0.1 x (t - 9), R 0.05 x (t - 9) per track, levels 1.0, B14+528 = 1.0 and the key
    block prefilled with 9.0: {key: (first, last) of 0xC16DF7A0, out: (L, R), send L}."""
    s.reset()
    for a, v in ((SEND_FX_ON, send_on), (KEY_TRACK, key_track), (SEND_FX, send_type)):
        s.poke(a, v)
    for t in (10, 11, 12):
        s.pokef(s.track(t) + 20, 1.0)
    s.pokef(B14 + 528, 1.0)
    s.block(OUT, 0.0, 0.0)
    s.block(SEND_BUS, 0.0, 0.0)
    s.block(KEY, 9.0, 9.0, channels=1)

    def render(m):
        t = m.R["a4"]
        return fill_hook({TRACK_DRY + L_PLANE: 0.1 * (t - 9), TRACK_DRY + R_PLANE: 0.05 * (t - 9),
                          TRACK_SEND + L_PLANE: 0.01 * (t - 9), TRACK_SEND + R_PLANE: 0.0})(m)

    s.run(MIX_TRACKS, {"a4": CTX, "b4": OUT, "a6": SEND_BUS}, hooks={TRACK_RENDER: render})
    key = s.plane(KEY + L_PLANE)
    return {"key": (r6(key[0]), r6(key[-1])), "out": (r6(s.f(OUT + L_PLANE)), r6(s.f(OUT + R_PLANE))),
            "send": r6(s.f(SEND_BUS + L_PLANE))}


# --- 9. send and master effects -----------------------------------------------------------------------------------

def _member(s, base, first, idx):
    return s.word(base + first + 4 * idx)


def send_delay(s, max_blocks=200):
    """StereoDigialDelay as audio_mix_main calls it. {first: (block, sample, L, R) of the first non-zero output,
    dry_after_block0: max |dry copy| after the first call, send_kept, key_kept, class}."""
    s.reset()
    fx = _member(s, SEND_FX, 8, 0)
    fn = s.word(s.word(fx) + 8)
    s.block(KEY, 0.75, 0.75, channels=1)
    res = {"class": vptr_names().get(s.word(fx), "?")}
    for k in range(max_blocks):
        if k == 0:
            s.block(SEND_BUS, lambda i: 1.0 if i == 0 else 0.0, lambda i: 0.5 if i == 0 else 0.0)
        elif k == 1:
            s.block(SEND_BUS, 0.0, 0.0)
        s.block(DRY_COPY, 0.25, -0.125)
        s.run(fn, {"a4": fx, "b4": SEND_BUS, "a6": DRY_COPY, "b6": KEY})
        left, right = s.plane(DRY_COPY + L_PLANE), s.plane(DRY_COPY + R_PLANE)
        if k == 0:
            res["dry_after_block0"] = max(map(abs, left + right))
            sb = s.plane(SEND_BUS + L_PLANE) + s.plane(SEND_BUS + R_PLANE)
            res["send_kept"] = sb[0] == 1.0 and sb[N] == 0.5 and not any(sb[1:N] + sb[N + 1:])
            res["key_kept"] = set(s.plane(KEY + L_PLANE)) == {0.75}
        nz = [i for i in range(N) if left[i] or right[i]]
        if nz:
            res["first"] = (k, nz[0], r6(left[nz[0]]), r6(right[nz[0]]))
            res["first_abs"] = k * N + nz[0]
            break
    return res


def master_maximizer(s, blocks=2):
    """Maximizer (g_master_effects member 4) on out; {out: [(L0, L1, R0)] per block, same: out identical with the
    send bus at +-0.3 and at 0, send_kept, class}."""
    runs = []
    kept = True
    for sendval in (0.3, 0.0):
        s.reset()
        fx = _member(s, MASTER_FX, 12, 4)
        fn = s.word(s.word(fx) + 8)
        res = []
        for _ in range(blocks):
            s.block(SEND_BUS, sendval, -sendval)
            s.block(OUT, lambda i: 0.5 if i % 2 == 0 else -0.5, lambda i: 0.25 if i % 2 == 0 else -0.25)
            s.run(fn, {"a4": fx, "b4": SEND_BUS, "a6": OUT, "b6": KEY})
            res.append(s.plane(OUT + L_PLANE) + s.plane(OUT + R_PLANE))
            kept &= set(s.plane(SEND_BUS + L_PLANE)) == {wf(fw(sendval))}
        runs.append(res)
    return {"class": vptr_names().get(s.word(fx), "?"), "same": runs[0] == runs[1], "send_kept": kept,
            "out": [(r6(r[0]), r6(r[1]), r6(r[N])) for r in runs[0]]}


# --- 10. render order ---------------------------------------------------------------------------------------------

def render_order(s, gain=0.5, post=None, metronome=False, rec_src=7):
    """audio_render_main with out = 0.25 / -0.5 from the hooked audio_mix_main: {out: (L, R) sample 0,
    in_block: (L, R) sample 0}."""
    s.reset()
    s.poke(SETTINGS + REC_SRC, rec_src)
    s.poke(SETTINGS + PAD, 0)
    if post is not None:
        s.block(POST_BUS, post, post)
    s.pokef(B14 + 520, gain)
    s.pokef(B14 + 1132, gain)
    if metronome:
        s.run(METRO_LEVEL, {"a4": 10})
        s.run(METRO_START, {"a4": METRONOME, "b4": 1})

    def mix(m):
        fill_hook({m.R["a4"] + L_PLANE: 0.25, m.R["a4"] + R_PLANE: -0.5})(m)
        m.R["a4"] = 0
        return m.R["b3"]

    hooks = {MIX_MAIN: mix, FILL_INPUT: fill_hook({IN_BLOCK + L_PLANE: 0.0625, IN_BLOCK + R_PLANE: -0.0625})}
    s.run(RENDER_MAIN, {"a4": RENDER_OUT}, hooks=hooks)
    return {"out": (r6(s.f(RENDER_OUT + L_PLANE)), r6(s.f(RENDER_OUT + R_PLANE))),
            "in_block": (r6(s.f(IN_BLOCK + L_PLANE)), r6(s.f(IN_BLOCK + R_PLANE)))}


RENDER_CASES = {"plain": {}, "post 0.125": {"post": 0.125}, "gain 0": {"gain": 0.0},
                "metronome": {"metronome": True}, "metronome, gain 0": {"metronome": True, "gain": 0.0},
                "REC SRC 25, post 0.125": {"rec_src": 25, "post": 0.125}}


# --- 11. PROJECT LEVEL --------------------------------------------------------------------------------------------

def project_level(s, values=(0, 63, 100, 127)):
    """{"boot": (project word, B14+360), v: (project word, B14+360) after the setter}."""
    s.reset()
    out = {"boot": (s.word(PROJECT_LEVEL_WORD), r6(s.f(B14 + 360)))}
    for v in values:
        s.reset()
        s.run(PROJECT_LEVEL_SET, {"a4": v})
        out[v] = (s.word(PROJECT_LEVEL_WORD), r6(s.f(B14 + 360)))
    return out


def main():
    s = Session()
    r, changed = dry_block_getter(s)
    print(f"0xC15AAAD0 returns {r:#010x}, writes {len(changed)} bytes outside the stack")
    for rack, v in racks(s).items():
        print(f"{rack} rack: header {[hex(w) for w in v['header']]}, {len(v['members'])} members: "
              + ", ".join(f"{i} {n}" for i, n in enumerate(v["members"])))
    print("file player, out L 0.25 / R -0.25 before, source (8192, -16384):")
    for label, kw in (("48 kHz", {}), ("44.1 kHz", {"rate": 44100}), ("gains 0.5 / 2.0", {"gains": (0.5, 2.0)}),
                      ("48 kHz, resampler returns 99", {"consumed": 99})):
        left, right, asked, adv = file_mix(s, **kw)
        print(f"  {label}: out L {left} R {right}, resampler asked for {asked}, stream advanced {adv} frames")
    print("player state queries (B14+884 states returning 1):", player_states(s))
    for level in (3, 10, 16, 0):
        for src in ("metronome 1", "metronome 2", "precount"):
            print(f"click level {level:2d} {src}: {clicks(s, level, src)}")
    for name, c in curves(s).items():
        print(f"{name} curve: {c}")
    print("audio_mix_tracks P 0.5, sends (0.25, 0.5, 0):", mix_tracks(s))
    print("audio_mix_usb send 0.5, B14+528 0.5, B14+532 0.25:", mix_usb(s))
    print("audio_mix_ext send 0.5, B14+528 0.5, B14+532 0.25:", mix_ext(s))
    for entry in (0, 1):
        print(f"track EQ entry 2t+{entry} b0 0.5:", track_eq(s, entry))
    for key in (10, 11, 12):
        print(f"sidechain key track {key}:", sidechain(s, key))
    print("send type 6 (Hall), key track 11:", sidechain(s, 11, send_type=6))
    print("send delay:", send_delay(s))
    print("master maximizer:", master_maximizer(s))
    for label, kw in RENDER_CASES.items():
        print(f"render ({label}):", render_order(s, **kw))
    print("PROJECT LEVEL:", project_level(s))


if __name__ == "__main__":
    main()
