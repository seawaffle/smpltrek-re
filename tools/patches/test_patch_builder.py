"""Self-contained conformance tests plus an optional official-image check; no device access."""
import contextlib
import copy
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import patch_builder as builder


SPEC = {"load_address": "0xc3f00000", "entry_offset": 0,
        "reserved_region": {"start": "0xc3f00000", "end": "0xc3f01000",
                            "evidence": "Synthetic test placement only; not a hardware reservation."}}
PAYLOAD = bytes(range(64))  # Deliberately data, not a claim of executable/safe code.


def synthetic_source():
    """Reproduce container/section geometry with synthetic bytes, without shipping firmware."""
    parts = [(0xC16F40A0, 0xB9F8), (0xC16F39AC, 0x24C), (0xC16F3C00, 0x200),
             (0xC1505400, 0x1A7F20), (0xC15052B8, 0x148), (0xC16AD320, 0x27A01),
             (0xC16F1CE0, 0x163C)]
    data = bytearray(builder.SOURCE_SIZE)
    struct.pack_into("<4s5I", data, 0, b"cmtd", len(data), 0, 0, 5, 1)
    struct.pack_into("<6I", data, 24, 3, 3, 2, 174, 48, len(data) - 48)
    struct.pack_into("<4s8I", data, 48, b"mmtd", len(data) - 48, 0, 0, 3, 2, 174, 0xC1694580, 7)
    pos = 84
    for base, size in parts:
        struct.pack_into("<4sII", data, pos, b"sect", base, size)
        pos += 12 + size
    assert pos == len(data)
    struct.pack_into("<I", data, builder.SLOT_OFFSET, builder.OLD_TARGET)
    return builder.integrity.reseal(data, "smpltrek")


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.source = synthetic_source()
        # Only tests substitute the pinned hash; production has no override flag.
        self.hash_patch = patch.object(builder, "SOURCE_HASH", builder.digest(self.source))
        self.hash_patch.start()
        self.addCleanup(self.hash_patch.stop)
        self.output, self.recipe = builder.build(self.source, PAYLOAD, SPEC)

    def refresh_receipt(self, output, recipe):
        """Attacker can recompute hashes and CRC fields; semantic policy must still reject."""
        recipe["output"] = {"length": len(output), "sha256": builder.digest(output)}
        for edit in recipe["replacements"]:
            off = edit["offset"]
            edit["new_hex"] = output[off:off + 4].hex()

    def test_deterministic_build_and_exact_replay(self):
        self.assertEqual(builder.build(self.source, PAYLOAD, SPEC), (self.output, self.recipe))
        self.assertEqual(builder.replay(self.source, self.recipe), self.output)
        builder.verify(self.source, self.recipe, self.output)
        self.assertEqual(len(self.output) - len(self.source), 12 + len(PAYLOAD))
        self.assertEqual(len(self.recipe["replacements"]), 7)
        self.assertEqual(self.recipe["append"]["new_hex"], self.output[len(self.source):].hex())
        self.assertEqual(builder.integrity.word(self.output, builder.SLOT_OFFSET), 0xC3F00000)
        self.assertEqual(builder.integrity.word(self.output, 0x4C), 0xC1694580)
        self.assertTrue(all(a == b for _, a, b in builder.integrity.verify(self.output, "smpltrek")))

    def test_original_sections_preserved_except_slot(self):
        old_image = builder.integrity.parse(self.source)[1]
        new_image = builder.integrity.parse(self.output)[1]
        old = builder.sections(self.source, old_image)
        self.assertEqual(builder.sections(self.output, new_image)[:7], old)
        for _, off, size in old:
            expected = bytearray(self.source[off:off + size])
            if off <= builder.SLOT_OFFSET < off + size:
                at = builder.SLOT_OFFSET - off
                expected[at:at + 4] = struct.pack("<I", 0xC3F00000)
            self.assertEqual(self.output[off:off + size], expected)

    def test_nonzero_compact_entry_offset(self):
        spec = copy.deepcopy(SPEC)
        spec["entry_offset"] = 2
        output, recipe = builder.build(self.source, PAYLOAD, spec)
        self.assertEqual(builder.integrity.word(output, builder.SLOT_OFFSET), 0xC3F00002)
        builder.verify(self.source, recipe, output)

    def test_wrong_source_and_already_patched_source(self):
        altered = bytearray(self.source)
        altered[100] ^= 1
        for source in (altered, self.source[:-1], self.output):
            with self.subTest(length=len(source)), self.assertRaises(ValueError):
                builder.build(source, PAYLOAD, SPEC)

    def test_wrong_original_pointer_even_with_pinned_hash(self):
        source = bytearray(self.source)
        struct.pack_into("<I", source, builder.SLOT_OFFSET, 0xC1666DA2)
        source = builder.integrity.reseal(source, "smpltrek")
        with patch.object(builder, "SOURCE_HASH", builder.digest(source)), self.assertRaisesRegex(ValueError, "original vtable"):
            builder.build(source, PAYLOAD, SPEC)

    def test_invalid_placements(self):
        mutations = [
            ("load_address", "0xc3f00002"), ("load_address", "0xffffffe0"),
            ("load_address", "0xc3f01000"), ("load_address", "0xc1505400"),
            ("entry_offset", 1), ("entry_offset", 64), ("entry_offset", -2), ("entry_offset", True),
        ]
        for key, value in mutations:
            spec = copy.deepcopy(SPEC)
            spec[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                builder.build(self.source, PAYLOAD, spec)
        for start, end in [("0xc0000000", "0xc0001000"), ("0xc4000000", "0xc4001000"),
                           ("0xc1505400", "0xc1506400"), ("0xc3f00000", "0xc3f00000")]:
            spec = copy.deepcopy(SPEC)
            spec["reserved_region"].update(start=start, end=end)
            with self.subTest(start=start), self.assertRaises(ValueError):
                builder.build(self.source, PAYLOAD, spec)

    def test_system_image_must_fit_the_flash_area(self):
        """The updater erases 4 MiB from 0x40000; a larger image would run into PRESET. Build and replay both refuse."""
        spec = copy.deepcopy(SPEC)
        spec.update(load_address="0xc2000000", reserved_region={"start": "0xc2000000", "end": "0xc2400000",
                                                                "evidence": "Synthetic test placement only."})
        room = (builder.SYSTEM_FLASH_CAPACITY - (builder.SOURCE_SIZE - 48) - 12) & ~1   # whole halfwords
        builder.build(self.source, bytes(room), spec)                       # exactly full is allowed
        with self.assertRaisesRegex(ValueError, "4 MiB"):
            builder.build(self.source, bytes(room + 2), spec)
        with patch.object(builder, "SYSTEM_FLASH_CAPACITY", 2 ** 25):      # a builder with the cap removed
            output, recipe = builder.build(self.source, bytes(room + 2), spec)
        with self.assertRaisesRegex(ValueError, "4 MiB"):                  # replay and verify still refuse it
            builder.verify(self.source, recipe, output)

    def test_missing_evidence_and_unknown_spec_fields(self):
        for change in (lambda s: s["reserved_region"].update(evidence="  "),
                       lambda s: s.update(extra=True), lambda s: s.pop("entry_offset")):
            spec = copy.deepcopy(SPEC)
            change(spec)
            with self.assertRaises(ValueError):
                builder.build(self.source, PAYLOAD, spec)

    def test_empty_odd_and_oversized_payloads(self):
        for payload in (b"", b"x", bytes(65), bytes(0x1002)):
            with self.subTest(length=len(payload)), self.assertRaises(ValueError):
                builder.build(self.source, payload, SPEC)

    def test_recipe_replacement_preconditions(self):
        for mode in ("missing", "duplicate", "unexpected", "old", "length", "reason"):
            r = copy.deepcopy(self.recipe)
            edits = r["replacements"]
            if mode == "missing":
                edits.pop()
            elif mode == "duplicate":
                edits.append(copy.deepcopy(edits[0]))
            elif mode == "unexpected":
                edits[0]["offset"] = 0x4C
            elif mode == "old":
                edits[0]["old_hex"] = "00000000"
            elif mode == "length":
                edits[0]["new_hex"] = "00"
            else:
                edits[0]["reason"] = "other"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                builder.replay(self.source, r)

    def test_bad_append_and_metadata(self):
        for mutate in (lambda r: r["append"].update(offset=0),
                       lambda r: r["append"].update(old_hex="00"),
                       lambda r: r["append"].update(new_hex="zz"),
                       lambda r: r["source"].update(sha256="0" * 64),
                       lambda r: r["output"].update(sha256="0" * 64),
                       lambda r: r["payload"].update(length=2),
                       lambda r: r["hook"].update(slot=14),
                       lambda r: r.update(format="unknown")):
            r = copy.deepcopy(self.recipe)
            mutate(r)
            with self.assertRaises(ValueError):
                builder.replay(self.source, r)

    def test_unauthorized_edit_with_valid_crcs_and_output_hash(self):
        for offset in (12, 0x4C, 0x58, 0xBECC):
            output = bytearray(self.output)
            output[offset] ^= 1
            output = builder.integrity.reseal(output, "smpltrek")
            r = copy.deepcopy(self.recipe)
            self.refresh_receipt(output, r)
            with self.subTest(offset=offset), self.assertRaisesRegex(ValueError, "changed|outside"):
                builder.verify_structure(self.source, r, output)
            with self.assertRaises(ValueError):
                builder.verify(self.source, r, output)

    def test_wrong_hook_target_with_valid_crcs(self):
        output = bytearray(self.output)
        struct.pack_into("<I", output, builder.SLOT_OFFSET, builder.OLD_TARGET)
        output = builder.integrity.reseal(output, "smpltrek")
        r = copy.deepcopy(self.recipe)
        self.refresh_receipt(output, r)
        with self.assertRaisesRegex(ValueError, "vtable pointer"):
            builder.replay(self.source, r)

    def test_payload_tampering_with_valid_crcs(self):
        output = bytearray(self.output)
        output[-1] ^= 1
        output = builder.integrity.reseal(output, "smpltrek")
        r = copy.deepcopy(self.recipe)
        r["append"]["new_hex"] = output[len(self.source):].hex()
        self.refresh_receipt(output, r)
        with self.assertRaisesRegex(ValueError, "payload hash"):
            builder.replay(self.source, r)

    def test_stale_crc_is_rejected_even_with_updated_output_hash(self):
        output = bytearray(self.output)
        output[8] ^= 1
        r = copy.deepcopy(self.recipe)
        self.refresh_receipt(output, r)
        with self.assertRaisesRegex(ValueError, "output CRC"):
            builder.replay(self.source, r)

    def test_malformed_appended_section_length(self):
        output = bytearray(self.output)
        struct.pack_into("<I", output, len(self.source) + 8, len(PAYLOAD) + 2)
        r = copy.deepcopy(self.recipe)
        r["append"]["new_hex"] = output[len(self.source):].hex()
        self.refresh_receipt(output, r)
        with self.assertRaises(ValueError):
            builder.replay(self.source, r)

    def test_cli_build_verify_replay_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, payload, spec = (root / n for n in ("stock.bin", "payload.bin", "placement.json"))
            output, recipe, replayed = (root / n for n in ("patched.bin", "recipe.json", "replayed.bin"))
            source.write_bytes(self.source)
            payload.write_bytes(PAYLOAD)
            spec.write_text(json.dumps(SPEC))
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(builder.main(["build", *map(str, (source, payload, spec, output, recipe))]), 0)
                self.assertEqual(builder.main(["verify", *map(str, (source, recipe, output))]), 0)
                self.assertEqual(builder.main(["replay", *map(str, (source, recipe, replayed))]), 0)
                self.assertEqual(builder.main(["replay", *map(str, (source, recipe, output))]), 2)
            self.assertEqual(output.read_bytes(), replayed.read_bytes())
            self.assertEqual(source.read_bytes(), self.source)

    def test_output_pair_cleanup_and_distinct_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            a = Path(directory) / "output.bin"
            with self.assertRaises(OSError):
                builder.write_new([(a, b"output"), (Path(directory) / "missing/recipe.json", b"recipe")])
            self.assertFalse(a.exists())
            with self.assertRaises(ValueError):
                builder.write_new([(a, b"one"), (a, b"two")])
            a.write_bytes(b"original")
            with self.assertRaises(ValueError):
                builder.write_new([(a, b"replacement")])
            self.assertEqual(a.read_bytes(), b"original")


OFFICIAL = builder.ROOT / "firmware/smpltrek/SmplTrek v3.2.174.zip"


@unittest.skipUnless(OFFICIAL.exists(), "official firmware not present")
class OfficialImageTests(unittest.TestCase):
    def test_real_source_hash_slot_and_roundtrip(self):
        source = builder.read_source(OFFICIAL)
        output, recipe = builder.build(source, PAYLOAD, SPEC)
        builder.verify(source, recipe, output)
        self.assertEqual(recipe["source"]["sha256"], builder.SOURCE_HASH)
        self.assertEqual(next(e["old_hex"] for e in recipe["replacements"]
                              if e["offset"] == builder.SLOT_OFFSET), "a06d66c1")


if __name__ == "__main__":
    unittest.main()
