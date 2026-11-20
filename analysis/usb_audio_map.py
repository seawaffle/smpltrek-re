#!/usr/bin/env python3
"""The USB audio sample path of SmplTrek 3.2.174, run in c6sim. Read-only and simulated.

Computer -> unit (interface 1, EP1 OUT). The receive tUSBBuffer at 0xC16CB350 (StarterWare usbbuffer.h order:
receive, callback 0xC15E92A0, handle = the audio device 0xC16C8C9C, buffer 0xC14EE430, 0x480 bytes) calls
`usb_audio_rx_event` (0xC15E92A0). On event 2 (USB_EVENT_RX_AVAILABLE) it asks the buffer how many bytes are
waiting (USBBufferDataAvailable 0xC164AD88) and `usb_audio_rx_copy` (0xC15E91E0) reads them (USBBufferRead
0xC164A8A4) into a 1152-byte ring at
0xC14EED30, write offset B14+760. Once per audio block `audio_fill_input_block` calls 0xC168F01C, which runs
`usb_audio_pull` (0xC15E99D0, read offset B14+756) for 128 frames into the block at 0xC14F19F8; the getter
0xC168F048 returns that block to `TrackSound::USBTrack::render`. A second reader of the same ring,
`usb_audio_read_channels` (0xC15E970C, directly after `usb_audio_push` and inside its code range), takes
(chA, dstA, dstB, chB, n): for each of n frames it stores sample chA (0 = L, 1 = R; negative = skip) as int32
`sample << 16` at dstA and sample chB at dstB, each pointer advancing 8 bytes; it copies nothing (returns 0) when
the interface is off or fewer than n frames are waiting, as the pull does. Nothing in the image calls it, branches
to it, or holds its address (also in SmplTrek 1.0.65 / 3.0.148, Lofi-12 XT 1.5.205 and CyDrums 1.1.84, always
push + 0x18C), so it is unused code in these builds.

Unit -> computer (interface 2, EP2 IN). After the mix, the render code (0xC159B548) calls 0xC168F014, which runs
`usb_audio_push` (0xC15E9580) on the 128 L and 128 R floats: each sample * 32767.0, truncated, stored as int16
into 32 packets of 192 bytes (48 frames) at 0xC14C78AC; packet write index 0xC14C90AC, offset in the packet
(halfwords) 0xC14C90B4, ready byte 0xC14C90B8. The transmit tUSBBuffer at 0xC16CB374 calls `usb_audio_tx_event`
(0xC15E8DA4); on event 5 (USB_EVENT_TX_COMPLETE) it sends the next packet through 0xC162A6E8, read index
0xC14C90B0.

Interfaces. Event 14 (USB_EVENT_COMP_IFACE_CHANGE; message data {interface, alternate setting} as two words) on
`usb_audio_rx_event` sets B14+764 (interface 1) or B14+768 (interface 2) to the alternate setting, re-initialises
that direction's tUSBBuffer (USBBufferInit 0xC164A938) on start and calls the USBAudioStreamingDelegate at B14+772: slot 0 / 1 for
interface 1 start / stop, 2 / 3 for interface 2. 0xC1661230 (arm the TIMER64P1 loop) runs while either is on,
0xC16612E0 when both are off. Event 1 (USB_EVENT_DISCONNECTED) clears both. The real delegate (installed by
`usb_start` 0xC168EFE4: the static object 0xC16DB68C, RTTI class `USBAudioEnvetReceiver`, vtable 0xC16CE678) does
nothing in slots 0, 2 and 3; slot 1 (interface 1 stop, 0xC16A66A0) is memset(0xC14F19F8, 0, 1024), so stopping the
stream zeroes the input block. This tool installs a recording stub instead (reset()).

The USB track. `TrackSound::USBTrack::render` (0xC15EB7F8) on `g_usb_track` (0xC15035E8) reads the block only
while the track's flags word (+8) is above 31, i.e. bit 5 ("playing") is set. Bit 5 is set by the track's vtable
slot +24 (0xC15EB8C8; also sets the request byte +36), reached through `tracks_start` (0xC15AA9E0; index, or -1
for every track), which the app pages call as a play toggle when `track_is_playing` (0xC15A9D8C: bit 5 of +8;
index -1 = any track) is false, and `tracks_stop` (0xC15AA8E0) otherwise. Stop (slot +32, 0xC15EB8A0) only sets
bit 1 and the request byte +37; one render block later the helper 0xC15EAAD0 clears +37 and render stores 2
(simulated: on the second block after stop), which ends playing.

Usage (from the repository root; needs firmware/ and the work listing, as hw_compare.py):
  python3 -B analysis/usb_audio_map.py
"""
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

RX_EVENT, RX_COPY, PULL, PUSH, TX_EVENT = 0xC15E92A0, 0xC15E91E0, 0xC15E99D0, 0xC15E9580, 0xC15E8DA4
TRACK, RENDER, TRACKS_START, TRACKS_STOP, TRACK_PLAYING = 0xC15035E8, 0xC15EB7F8, 0xC15AA9E0, 0xC15AA8E0, 0xC15A9D8C
DELEGATE_STOP_1 = 0xC16A66A0                                               # USBAudioEnvetReceiver slot 1
SCRATCH_L, SCRATCH_R = 0xC16E03C0, 0xC16DFBA0                              # audio_mix_usb's render buffers
READ_CHANNELS = 0xC15E970C                                                   # unreferenced
BUF_AVAILABLE, BUF_READ, BUF_INIT, TX_PACKET = 0xC164AD88, 0xC164A8A4, 0xC164A938, 0xC162A6E8
TIMER_ARM, TIMER_STOP = 0xC1661230, 0xC16612E0
DEVICE, RX_USBBUFFER, TX_USBBUFFER = 0xC16C8C9C, 0xC16CB350, 0xC16CB374
RING, RING_SIZE, BLOCK = 0xC14EED30, 1152, 0xC14F19F8
PACKETS, PACKET_SIZE, PACKET_WRITE, PACKET_READ, PACKET_FILL, PACKET_READY = \
    0xC14C78AC, 192, 0xC14C90AC, 0xC14C90B0, 0xC14C90B4, 0xC14C90B8
READ, WRITE, OUT_ON, IN_ON, DELEGATE_PTR = 756, 760, 764, 768, 772            # B14 offsets
DELEGATE, VTABLE, SLOTS, SCRATCH = 0xC0000100, 0xC0000140, 0xC0000180, 0xC0002000   # zero-filled DDR


class Session:
    def __init__(self):
        import c6sim
        import hw_compare
        import mmio_trace
        self.c6sim = c6sim
        self.t = mmio_trace.Trace(str(hw_compare.ROOT / hw_compare.PRODUCTS["smpltrek"]["image"]), "smpltrek")
        self.boot = self.t.boot()
        self.b14 = self.boot.cfg["b14"]
        self.calls, self.incoming = [], b""
        self.hooks = {a: c6sim.returns(0) for a in hw_compare.HOOKS}
        for k in range(8):
            self.hooks[SLOTS + 4 * k] = self.record(("delegate", k))
        for a, n in ((BUF_INIT, "buffer init"), (TIMER_ARM, "timer arm"), (TIMER_STOP, "timer stop")):
            self.hooks[a] = self.record((n,), args=("a4",))
        self.hooks[TX_PACKET] = self.tx_packet
        self.hooks[BUF_AVAILABLE] = self.available
        self.hooks[BUF_READ] = self.read
        self.reset()

    def reset(self):
        self.t.state, self.t.regs = dict(self.boot.overlay), {}
        self.w32(DELEGATE, VTABLE)
        for k in range(8):
            self.w32(VTABLE + 4 * k, SLOTS + 4 * k)
        self.w32(self.b14 + DELEGATE_PTR, DELEGATE)

    def record(self, name, args=()):
        def f(m):
            self.calls.append(name + tuple(m.R.get(r, 0) for r in args))
            m.R["a4"] = 0
            return m.R["b3"]
        return f

    def tx_packet(self, m):
        n = m.R.get("a6", 0)
        self.calls.append(("tx", m.R.get("b4", 0), n))
        m.R["a4"] = n
        return m.R["b3"]

    def available(self, m):
        m.R["a4"] = len(self.incoming)
        return m.R["b3"]

    def read(self, m):
        n = min(m.R.get("a6", 0), len(self.incoming))
        m.mem.write(m.R["b4"], self.incoming[:n])
        self.incoming = self.incoming[n:]
        m.R["a4"] = n
        return m.R["b3"]

    def w32(self, address, value):
        for i in range(4):
            self.t.state[address + i] = (value >> (8 * i)) & 0xFF

    def r32(self, address, signed=False):
        return int.from_bytes(bytes(self.t.state.get(address + i, 0) for i in range(4)), "little", signed=signed)

    def get(self, name):
        return self.r32(self.b14 + {"read": READ, "write": WRITE, "out_on": OUT_ON, "in_on": IN_ON}[name])

    def set(self, **kw):
        for name, value in kw.items():
            self.w32(self.b14 + {"read": READ, "write": WRITE, "out_on": OUT_ON, "in_on": IN_ON}[name], value)

    def run(self, fn, regs):
        self.calls.clear()
        return self.c6sim.s32(self.t.run(fn, regs, hooks=self.hooks, max_cycles=2000000)[0])

    # computer -> unit
    def receive(self, data):
        """Event 2 with `data` waiting in the receive tUSBBuffer; returns the bytes left unread."""
        self.incoming = bytes(data)
        self.run(RX_EVENT, {"a4": DEVICE, "b4": 2, "a6": 0, "b6": 0})
        return len(self.incoming)

    def ring(self, offset, n):
        return bytes(self.t.state.get(RING + (offset + i) % RING_SIZE, 0) for i in range(n))

    def pull(self, fill=0xAA):
        """usb_audio_pull for 128 frames into BLOCK (first filled with `fill`): (copied, [(L, R) int32] * 128)."""
        for i in range(1024):
            self.t.state[BLOCK + i] = fill
        r = self.run(PULL, {"a4": BLOCK, "b4": 128})
        frames = [(self.r32(BLOCK + 8 * k, True), self.r32(BLOCK + 8 * k + 4, True)) for k in range(128)]
        return r != self.c6sim.s32(BLOCK), frames

    def read_channels(self, n, ch_a=0, ch_b=1, fill=0xAA):
        """usb_audio_read_channels(ch_a, BLOCK, BLOCK + 4, ch_b, n): (returned, [(dstA, dstB) int32] * n)."""
        for i in range(max(8 * n, 8)):
            self.t.state[BLOCK + i] = fill
        r = self.run(READ_CHANNELS, {"a4": ch_a & 0xFFFFFFFF, "b4": BLOCK, "b6": BLOCK + 4, "a6": ch_b & 0xFFFFFFFF, "a8": n})
        return r, [(self.r32(BLOCK + 8 * k, True), self.r32(BLOCK + 8 * k + 4, True)) for k in range(n)]

    def track(self, op):
        """op 'start' / 'stop' on track 13 (tracks_start / tracks_stop), 'render' (one block), or 'playing'.
        Returns (flags word +8, request byte +36, request byte +37, track_is_playing(13))."""
        if op == "start":
            self.run(TRACKS_START, {"a4": 13, "b4": 0})
        elif op == "stop":
            self.run(TRACKS_STOP, {"a4": 13, "b4": 0})
        elif op == "render":
            self.run(RENDER, {"a4": TRACK, "b4": 0, "a6": SCRATCH_L, "b6": SCRATCH_R})
        playing = self.run(TRACK_PLAYING, {"a4": 13})
        return self.r32(TRACK + 8), self.t.state.get(TRACK + 36, 0), self.t.state.get(TRACK + 37, 0), playing

    def interface_1_stop_delegate(self, fill=0x5A):
        """Run the real delegate's slot 1 on a block filled with `fill`; True when the 1024 bytes are zero after."""
        for i in range(1024):
            self.t.state[BLOCK + i] = fill
        self.run(DELEGATE_STOP_1, {"a4": 0})
        return all(self.t.state.get(BLOCK + i, 0) == 0 for i in range(1024))

    # unit -> computer
    def push(self, left, right):
        """usb_audio_push on 128 L and 128 R floats."""
        data = struct.pack("<128f", *left) + struct.pack("<128f", *right)
        for i, x in enumerate(data):
            self.t.state[SCRATCH + i] = x
        self.run(PUSH, {"a4": SCRATCH})

    def packet(self, n):
        raw = bytes(self.t.state.get(PACKETS + PACKET_SIZE * n + i, 0) for i in range(PACKET_SIZE))
        return list(struct.unpack("<96h", raw))

    def packet_state(self):
        return {"write": self.r32(PACKET_WRITE), "read": self.r32(PACKET_READ), "fill": self.r32(PACKET_FILL),
                "ready": self.t.state.get(PACKET_READY, 0)}

    def tx_complete(self, read=None, write=None, ready=None):
        if read is not None:
            self.w32(PACKET_READ, read)
        if write is not None:
            self.w32(PACKET_WRITE, write)
        if ready is not None:
            self.t.state[PACKET_READY] = ready
        self.run(TX_EVENT, {"a4": DEVICE, "b4": 5, "a6": 0, "b6": 0})
        return [c for c in self.calls if c[0] == "tx"]

    # interfaces
    def interface(self, number, alternate):
        msg = SCRATCH + 0x1000
        self.w32(msg, number)
        self.w32(msg + 4, alternate)
        self.run(RX_EVENT, {"a4": DEVICE, "b4": 14, "a6": 0, "b6": msg})
        return list(self.calls)

    def event(self, code):
        self.run(RX_EVENT, {"a4": DEVICE, "b4": code, "a6": 0, "b6": 0})
        return list(self.calls)


def main():
    s = Session()
    for number, alt in ((1, 1), (2, 1), (1, 0), (2, 0)):
        calls = s.interface(number, alt)
        print(f"interface {number} alt {alt}: out_on {s.get('out_on')} in_on {s.get('in_on')} "
              f"calls {[tuple(hex(x) if isinstance(x, int) and x > 255 else x for x in c) for c in calls]}")
    s.set(out_on=1, in_on=1, read=0, write=0)
    left = s.receive(struct.pack("<300h", *range(300)))
    print(f"receive 600 bytes: write offset {s.get('write')}, {left} left unread")
    copied, frames = s.pull()
    print(f"pull: copied {copied}, read offset {s.get('read')}, frames {frames[:2]}")
    s.push([k / 128 for k in range(128)], [-k / 128 for k in range(128)])
    print("push 128 frames:", s.packet_state(), "packet 0 starts", s.packet(0)[:6])
    print("tx complete:", [(hex(b), n) for _, b, n in s.tx_complete()])


if __name__ == "__main__":
    main()
