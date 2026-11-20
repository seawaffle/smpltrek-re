"""Decode panel bytes independently of the firmware drawing routines."""
import struct
import zlib

WIDTH = HEIGHT = 128
FRAME_BYTES = 8192


def pixels(frame):
    if len(frame) != FRAME_BYTES:
        raise ValueError("a panel frame must contain 8192 bytes")
    result = bytearray(WIDTH * HEIGHT)
    for y in range(HEIGHT):
        for x in range(WIDTH):
            packed = frame[128 * (y // 2) + 64 * (x % 2) + x // 2]
            result[y * WIDTH + x] = ((packed >> (4 * (y % 2))) & 15) * 17
    return bytes(result)


def png(frame):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    gray = pixels(frame)
    rows = b"".join(b"\0" + gray[y * WIDTH:(y + 1) * WIDTH] for y in range(HEIGHT))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
