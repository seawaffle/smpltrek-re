"""Pins the USB audio sample path ("USB audio" in docs/01-platform-map.md) against the simulated code of SmplTrek
3.2.174. Run:
python3 -B -m unittest discover -s analysis -p "test_usb_audio_map.py" -v

Needs firmware/ and the work listing; skipped without them.
"""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hw_compare      # noqa: E402
import usb_audio_map   # noqa: E402

P = hw_compare.PRODUCTS["smpltrek"]


@unittest.skipUnless((ROOT / P["image"]).exists() and (ROOT / P["listing"]).exists(), "official update not present")
class Simulated(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = usb_audio_map.Session()

    def setUp(self):
        self.s.reset()

    def test_interfaces(self):
        s = self.s
        self.assertEqual(s.interface(1, 1), [("buffer init", usb_audio_map.RX_USBBUFFER), ("delegate", 0), ("timer arm", 0)])
        calls = s.interface(2, 1)
        self.assertEqual(calls[0], ("buffer init", usb_audio_map.TX_USBBUFFER))
        self.assertEqual(calls[1][0::2], ("tx", 0))                                  # zero-length packet first
        self.assertEqual(calls[2:], [("delegate", 2), ("timer arm", 0)])
        self.assertEqual((s.get("out_on"), s.get("in_on")), (1, 1))
        self.assertEqual(s.interface(1, 0), [("delegate", 1), ("timer arm", 0)])      # interface 2 still on
        self.assertEqual(s.interface(2, 0), [("delegate", 3), ("timer stop", 0)])
        s.interface(1, 1)
        s.event(1)                                                                     # disconnected
        self.assertEqual((s.get("out_on"), s.get("in_on")), (0, 0))

    def test_out_path(self):
        s = self.s
        s.set(out_on=1, read=0, write=0)
        s.receive(struct.pack("<254h", *range(1, 255)))                               # 508 bytes: under 128 frames
        self.assertEqual(s.get("write"), 508)
        self.assertEqual(s.pull(), (False, [(-0x55555556, -0x55555556)] * 128))      # block left as it was
        s.receive(struct.pack("<4h", 255, 256, 257, 258))
        copied, frames = s.pull()
        self.assertTrue(copied)
        self.assertEqual(frames[:2], [(1 << 16, 2 << 16), (3 << 16, 4 << 16)])        # int16 L, R -> int32 << 16
        self.assertEqual(s.get("read"), 512)

    def test_out_ring_wraps_without_guard(self):
        s = self.s
        s.set(out_on=1, read=0, write=0)
        s.receive(bytes(1200))
        self.assertEqual((s.get("write"), s.get("read")), (48, 0))                     # 1152-byte ring overrun
        self.assertFalse(s.pull()[0])

    def test_read_channels(self):
        s = self.s
        s.set(out_on=1, read=0, write=0)
        s.receive(struct.pack("<8h", 1, 2, 3, 4, 5, 6, 7, 8))
        self.assertEqual(s.read_channels(4, 1, 0)[1], [(2 << 16, 1 << 16), (4 << 16, 3 << 16),
                                                       (6 << 16, 5 << 16), (8 << 16, 7 << 16)])  # swapped
        self.assertEqual(s.get("read"), 16)
        s.set(read=0)
        X = -0x55555556
        self.assertEqual(s.read_channels(4, -1, 1)[1], [(X, 2 << 16), (X, 4 << 16), (X, 6 << 16), (X, 8 << 16)])
        s.set(read=0)
        self.assertEqual(s.read_channels(5), (0, [(X, X)] * 5))                         # 4 waiting: nothing
        self.assertEqual(s.get("read"), 0)
        s.set(out_on=0)
        self.assertEqual(s.read_channels(4)[0], 0)

    def test_usb_track_plays_only_when_started(self):
        s = self.s
        self.assertEqual(s.track("playing"), (2, 0, 0, 0))                  # after start-up: stopped
        self.assertEqual(s.track("start"), (0x20, 1, 0, 1))
        states = [s.track("render") for _ in range(3)]
        self.assertEqual(states[-1], (0x20, 0, 0, 1))                       # request +36 consumed
        self.assertEqual(s.track("stop"), (0x22, 0, 1, 1))                  # still playing
        states = [s.track("render") for _ in range(6)]
        end = next(k for k, st in enumerate(states) if st[3] == 0)
        self.assertGreaterEqual(end, 1)                                     # not on the first block
        self.assertEqual(states[end - 1], (0x22, 0, 1, 1))                  # one block unchanged
        self.assertEqual(states[end:], [(2, 0, 0, 0)] * (6 - end))

    def test_interface_1_stop_clears_block(self):
        self.assertTrue(self.s.interface_1_stop_delegate())

    def test_in_path(self):
        s = self.s
        s.set(in_on=1)
        s.push([0.5, -0.5, 1.0, 3.0] * 32, [0.25] * 128)
        self.assertEqual(s.packet(0)[:8], [16383, 8191, -16383, 8191, 32767, 8191, 32765, 8191])   # 3.0 wraps
        self.assertEqual(s.packet_state(), {"write": 2, "read": 0, "fill": 64, "ready": 1})       # 48 frames each
        self.assertEqual(s.tx_complete(), [("tx", usb_audio_map.PACKETS, 192)])
        self.assertEqual(s.tx_complete(), [("tx", usb_audio_map.PACKETS + 192, 192)])
        self.assertEqual([c[0::2] for c in s.tx_complete()], [("tx", 0)])            # none ready: zero length

    def test_in_off(self):
        self.s.push([0.5] * 128, [0.5] * 128)
        self.assertEqual(self.s.packet_state(), {"write": 0, "read": 0, "fill": 0, "ready": 0})


if __name__ == "__main__":
    unittest.main()
