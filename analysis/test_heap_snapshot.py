"""Synthetic captures exercise invariants, not firmware execution or ownership."""
import struct
import unittest
from unittest.mock import patch

import heap_snapshot as hs


def segment(address, data):
    return {"address": hex(address), "hex": data.hex()}


def words(address, *values):
    return segment(address, struct.pack("<" + "I" * len(values), *values))


def capture():
    # A live 264-byte malloc block between two free blocks. No firmware bytes.
    raw = hs.START + 0x100
    after = raw + 264
    pattern = bytes(range(256))
    return {
        "format": "smpltrek-heap-snapshot/1", "firmware_sha256": hs.SHA256,
        "capture": {"boot_id": "synthetic-boot", "phase": "after-allocation",
                    "method": "halted", "coherent": True},
        "segments": [words(hs.HEAP, 0xC16C90D0, 8, hs.START, hs.START, hs.END - hs.START, 8),
                     words(hs.START, after, 0x100),
                     segment(raw, struct.pack("<II", raw, 264) + pattern),
                     words(after, 0, hs.END - after)],
        "probe": {"boot_id": "synthetic-boot", "pointer": hex(raw + 8),
                  "expected_hex": pattern.hex()},
    }


class SnapshotTests(unittest.TestCase):
    def reject(self, snapshot, message):
        with self.assertRaisesRegex(ValueError, message):
            hs.validate(snapshot)

    def test_consistent_capture_is_not_ownership_proof(self):
        result = hs.validate(capture())
        self.assertFalse(result["ownership_proven"])
        self.assertEqual(result["free_nodes"], 2)
        self.assertEqual(result["total_free_size"], hs.END - hs.START - 264)
        self.assertEqual(result["largest_free_size"], hs.END - hs.START - 0x100 - 264)

    def test_adjacent_capture_segments_can_split_a_header(self):
        s = capture()
        original = s["segments"].pop(0)
        data = bytes.fromhex(original["hex"])
        s["segments"] += [segment(hs.HEAP, data[:3]), segment(hs.HEAP + 3, data[3:])]
        self.assertEqual(hs.validate(s)["free_nodes"], 2)

    def test_missing_and_overlapping_capture_bytes(self):
        s = capture()
        del s["segments"][-1]
        self.reject(s, "missing captured bytes")
        s = capture()
        s["segments"].append(words(hs.HEAP + 4, 8))
        self.reject(s, "overlapping capture")

    def test_cycle_descending_overlap_and_adjacent_free_nodes(self):
        for following in (hs.START, hs.START - 8, hs.START + 8, hs.START + 0x100):
            with self.subTest(following=hex(following)):
                s = capture()
                s["segments"][1] = words(hs.START, following, 0x100)
                self.reject(s, "invalid free-node|cycles, descends")

    def test_invalid_sizes_and_addresses(self):
        for length in (0, 7, 9, 0xFFFFFFFF, hs.END - hs.START + 8):
            s = capture()
            s["segments"][1] = words(hs.START, 0, length)
            self.reject(s, "invalid free-node size")
        for address in (hs.START + 1, hs.END, hs.START - 8):
            s = capture()
            s["segments"][0] = words(hs.HEAP, 0xC16C90D0, 8, hs.START,
                                     address, hs.END - hs.START, 8)
            self.reject(s, "invalid free-node address")

    def test_probe_header_pattern_and_free_overlap(self):
        for offset, message in ((0, "header changed"), (100, "pattern changed")):
            s = capture()
            data = bytearray.fromhex(s["segments"][2]["hex"])
            data[offset] ^= 1
            s["segments"][2]["hex"] = data.hex()
            self.reject(s, message)
        s = capture()
        # Stale bytes can remain intact inside a block that has become free.
        s["segments"][1] = words(hs.START, 0, hs.END - hs.START)
        self.reject(s, "overlaps a free block")

    def test_probe_requires_fixed_size_same_boot_and_valid_pointer(self):
        for key, value, message in (("boot_id", "old-boot", "another boot"),
                                    ("expected_hex", "aa", "exactly 256"),
                                    ("pointer", hex(hs.END), "outside the heap")):
            s = capture()
            s["probe"][key] = value
            self.reject(s, message)

    def test_metadata_and_heap_are_version_pinned(self):
        s = capture()
        s["firmware_sha256"] = "0" * 64
        self.reject(s, "unsupported firmware")
        for key, value in (("coherent", False), ("method", "running-read")):
            s = capture()
            s["capture"][key] = value
            self.reject(s, "coherent")
        s = capture()
        s["segments"][0] = words(hs.HEAP, 0xC16C90D0, 8, hs.START, 0, 4096, 8)
        self.reject(s, "unexpected heap configuration")

    def test_stats_and_node_limit(self):
        s = capture()
        result = hs.validate(s)
        s["stats"] = {k: result[k] for k in ("total_size", "total_free_size", "largest_free_size")}
        hs.validate(s)
        s["stats"]["total_free_size"] += 8
        self.reject(s, "statistics disagree")
        with patch.object(hs, "MAX_NODES", 1):
            self.reject(capture(), "result incomplete")

    def test_empty_free_list_does_not_prove_startup_completed(self):
        s = capture()
        del s["probe"]
        s["segments"] = [words(hs.HEAP, 0xC16C90D0, 8, hs.START, 0, hs.END - hs.START, 8)]
        result = hs.validate(s)
        self.assertEqual(result["total_free_size"], 0)
        self.assertFalse(result["ownership_proven"])


if __name__ == "__main__":
    unittest.main()
