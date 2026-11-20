"""Corpus and mutation checks. Run: python3 -B -m unittest discover -s tools -p test_integrity.py -v

The corpus tests need the copyrighted files in firmware/ (never committed) and are skipped with a message when
firmware/ is absent. SyntheticIntegrityTests exercise the same CRC, reseal, nesting and parsing rules on a
synthetic container and run everywhere.
"""
from pathlib import Path
import struct
import sys
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import sonicware_integrity as integrity


BINS = ROOT / "firmware"
NO_CORPUS = "needs official update files in firmware/ (git-ignored, see firmware/README.md); synthetic tests still run"


def firmware(relative):
    return next(integrity.inputs([ROOT / relative]))[1]


def needs(*relatives):
    """Skip unless every named corpus file exists. A partial corpus is skipped file by file, not failed."""
    missing = [r for r in relatives if not (ROOT / r).exists()]
    return unittest.skipIf(missing, f"{NO_CORPUS} (missing: {', '.join(missing)})")


def needs_set(pattern, count):
    """Skip unless firmware/PATTERN matches exactly COUNT files (a test over a whole product's releases)."""
    found = len(list(BINS.glob(pattern)))
    return unittest.skipIf(found != count, f"{NO_CORPUS} (firmware/{pattern}: {found} of {count})")


def bitwise_crc(data, seed):
    """zlib-compatible CRC-32, bit by bit, independent of zlib's tables."""
    state = seed ^ 0xFFFFFFFF
    for byte in data:
        state ^= byte
        for _ in range(8):
            state = (state >> 1) ^ (0xEDB88320 if state & 1 else 0)
    return state ^ 0xFFFFFFFF


def synthetic_container(family=5):
    """A cmtd holding one pmtd (two partitions) and one mmtd (two sections), synthetic bytes, unsealed."""
    parts = [bytes(range(40)), b"\xa5" * 24]
    pmtd = struct.pack("<4s7I", b"pmtd", 0, 0, 0, 2, 0, 22, len(parts))
    pmtd += b"".join(struct.pack("<3I", 0x1000 * (k + 1), 0, len(p)) for k, p in enumerate(parts)) + b"".join(parts)
    pmtd = pmtd[:4] + struct.pack("<I", len(pmtd)) + pmtd[8:]
    sects = [(0xC0000000, b"\x11" * 20), (0xC0001000, bytes(range(255, 215, -1)))]
    mmtd = struct.pack("<4s8I", b"mmtd", 0, 0, 0, 3, 2, 174, 0xC0000000, len(sects))
    mmtd += b"".join(struct.pack("<4sII", b"sect", base, len(b)) + b for base, b in sects)
    mmtd = mmtd[:4] + struct.pack("<I", len(mmtd)) + mmtd[8:]
    offset = 24 + 2 * 24
    total = offset + len(pmtd) + len(mmtd)
    data = struct.pack("<4s5I", b"cmtd", total, 0, 0, family, 2)
    data += struct.pack("<6I", 2, 2, 0, 22, offset, len(pmtd))
    data += struct.pack("<6I", 3, 3, 2, 174, offset + len(pmtd), len(mmtd))
    return data + pmtd + mmtd


class SyntheticIntegrityTests(unittest.TestCase):
    """The corpus tests' mechanics on a synthetic container; these run on a fresh clone without firmware/."""

    def setUp(self):
        self.sealed = integrity.reseal(synthetic_container(), "smpltrek")

    def test_parse_layout(self):
        images = integrity.parse(self.sealed)
        self.assertEqual([i.tag for i in images], ["cmtd", "pmtd", "mmtd"])
        self.assertEqual([i.version for i in images[1:]], [(2, 0, 22), (3, 2, 174)])

    def test_reseal_valid_and_idempotent(self):
        self.assertTrue(all(a == b for _, a, b in integrity.verify(self.sealed, "smpltrek")))
        self.assertEqual(integrity.reseal(self.sealed, "smpltrek"), self.sealed)
        raw = synthetic_container()
        allowed = {i.offset + j for i in integrity.parse(raw) for j in range(8, 12)}
        self.assertTrue(all(a == b or k in allowed for k, (a, b) in enumerate(zip(raw, self.sealed))))

    def test_checksum_matches_bitwise_crc(self):
        for image in integrity.parse(self.sealed):
            b = bytearray(self.sealed[image.offset:image.offset + image.size])
            b[8:12] = bytes(4)
            seed = integrity.PROFILES["smpltrek"][image.tag]
            self.assertEqual(bitwise_crc(b, seed), integrity.word(self.sealed, image.offset + 8))
        self.assertEqual(bitwise_crc(b"123456789", 0), 0xCBF43926)

    def test_child_mutation_and_nested_repair(self):
        _, pmtd, mmtd = integrity.parse(self.sealed)
        changed = bytearray(self.sealed)
        changed[pmtd.offset + pmtd.size - 1] ^= 1
        self.assertEqual([a == b for _, a, b in integrity.verify(changed, "smpltrek")], [False, False, True])
        repaired = integrity.reseal(changed, "smpltrek")
        self.assertTrue(all(a == b for _, a, b in integrity.verify(repaired, "smpltrek")))
        allowed = {i.offset + j for i in integrity.parse(changed) for j in range(8, 12)}
        self.assertTrue(all(a == b or k in allowed for k, (a, b) in enumerate(zip(changed, repaired))))
        self.assertEqual(repaired[mmtd.offset:], self.sealed[mmtd.offset:])

    def test_wrong_repair_order(self):
        changed = bytearray(self.sealed)
        changed[-1] ^= 1
        wrong_order = bytearray(changed)
        for image in integrity.parse(changed):  # parent first: its CRC covers the child's stale field
            value = integrity.checksum(wrong_order, image, integrity.PROFILES["smpltrek"][image.tag])
            struct.pack_into("<I", wrong_order, image.offset + 8, value)
        self.assertEqual([a == b for _, a, b in integrity.verify(wrong_order, "smpltrek")], [False, True, True])

    def test_family_word_checked(self):
        other = integrity.reseal(synthetic_container(family=8), "elz1play")
        with self.assertRaises(ValueError):
            integrity.verify(other, "smpltrek")
        checks = integrity.verify(other, "smpltrek", allow_family_mismatch=True)
        self.assertFalse(any(a == b for _, a, b in checks))

    def test_image_type_without_seed_refused(self):
        # CyDrums shares family word 8 with ELZ_1 play but has no pmtd seed: a clean refusal, not a KeyError.
        other = integrity.reseal(synthetic_container(family=8), "elz1play")
        for call in (integrity.verify, integrity.reseal):
            with self.assertRaisesRegex(ValueError, "no seed for a pmtd image"):
                call(other, "cydrums")

    def test_malformed_rejected(self):
        data = self.sealed
        for bad in (b"", b"cmtd", data[:-1], data + b"\0"):
            with self.assertRaises(ValueError):
                integrity.parse(bad)
        for offset, value in ((20, 0xFFFFFFFF), (24, 9), (40, 71), (44, len(data))):
            bad = bytearray(data)
            struct.pack_into("<I", bad, offset, value)
            with self.assertRaises(ValueError):
                integrity.parse(bad)

    def test_cli_verify_skips_a_zip_without_an_update(self):
        """A batch verify over a folder with a non-update zip (like CyDrums_folder.zip) skips it with a notice."""
        import subprocess, tempfile, zipfile
        with tempfile.TemporaryDirectory() as tmp:
            update, folder = Path(tmp) / "update.zip", Path(tmp) / "folder.zip"
            with zipfile.ZipFile(update, "w") as archive:
                archive.writestr("update/SMPLTREK.bin", self.sealed)
            with zipfile.ZipFile(folder, "w") as archive:
                archive.writestr("card/System/data.bin", b"not an update")
            run = lambda *paths: subprocess.run(
                [sys.executable, "-B", str(ROOT / "tools/sonicware_integrity.py"), "verify", "--profile", "smpltrek",
                 *map(str, paths)], capture_output=True, text=True)
            result = run(folder, update)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("skipped", result.stderr)
            self.assertIn("3/3 integrity fields match", result.stdout)
            self.assertEqual(run(folder).returncode, 2)
            damaged = Path(tmp) / "damaged.zip"   # stored, so the flipped byte is the container magic itself
            with zipfile.ZipFile(damaged, "w") as archive:
                archive.writestr("update/SMPLTREK.bin", self.sealed)
            raw = bytearray(damaged.read_bytes())
            raw[raw.index(b"cmtd")] ^= 1
            damaged.write_bytes(raw)
            result = run(damaged, update)
            self.assertEqual(result.returncode, 2)
            self.assertIn("damaged", result.stderr)

    def test_seed_recovery(self):
        for image in integrity.parse(self.sealed):
            self.assertEqual(integrity.recover_seed(self.sealed, image), integrity.PROFILES["smpltrek"][image.tag])


# The whole-corpus tests need every release below. firmware/ itself always exists (it ships its README), so the gate
# is on the files, not the folder.
CORPUS = (("smpltrek", "smpltrek/*.zip", 8), ("lofi12", "lofi12/*.zip", 3),
          ("elz1play", "other/ELZ_1_play*.zip", 3),
          ("liven8bit", "other/LIVEN_8SYSTEM*.syx", 3),
          ("livenlofi12", "other/LIVEN_LOFI*.syx", 2),
          ("livenxfm", "other/LIVEN_XFM*.syx", 2),
          ("cydrums", "cydrums/CyDrums_v*.zip", 2))
CORPUS_MISSING = [f"{pattern} ({len(list(BINS.glob(pattern)))} of {count})" for _, pattern, count in CORPUS
                  if len(list(BINS.glob(pattern))) != count]

# Applied per test, not to the class: a test over the whole corpus skips unless all of it is present, and a test on
# named files runs whenever those files are present.
WHOLE_CORPUS = unittest.skipIf(CORPUS_MISSING, f"{NO_CORPUS} (incomplete: {', '.join(CORPUS_MISSING)})")


class IntegrityTests(unittest.TestCase):
    @WHOLE_CORPUS
    def test_all_validated_releases_and_unchanged_reseal(self):
        fields = files = 0
        for profile, pattern, count in CORPUS:
            paths = sorted((ROOT / "firmware").glob(pattern))
            self.assertEqual(len(paths), count)
            for name, data in integrity.inputs(paths):
                with self.subTest(file=name):
                    checks = integrity.verify(data, profile)
                    self.assertTrue(all(a == b for _, a, b in checks))
                    self.assertEqual(integrity.reseal(data, profile), data)
                    files += 1
                    fields += len(checks)
        self.assertEqual((files, fields), (23, 56))

    @WHOLE_CORPUS
    def test_verified_corpus_record_matches_the_files(self):
        """tools/verified_corpus.json is the published record: every validated release, its hash and every field."""
        import hashlib, json
        record = {entry["source"]: entry for entry in json.loads((ROOT / "tools/verified_corpus.json").read_text())}
        seen = set()
        for profile, pattern, _ in CORPUS:
            for path in sorted(BINS.glob(pattern)):
                for name, data in integrity.inputs([path]):
                    source = str(path.relative_to(ROOT)) + name[len(str(path)):]
                    with self.subTest(source=source):
                        entry = record[source]
                        self.assertEqual((entry["profile"], entry["size"], entry["sha256"]),
                                         (profile, len(data), hashlib.sha256(data).hexdigest()))
                        checks = [(image.tag, image.offset, image.size, f"{a:08x}", f"{b:08x}")
                                  for image, a, b in integrity.verify(data, profile)]
                        self.assertEqual(checks, [(c["tag"], c["offset"], c["size"], c["stored"], c["computed"])
                                                  for c in entry["checks"]])
                        seen.add(source)
        self.assertEqual(seen, set(record))

    @WHOLE_CORPUS
    @needs("firmware/other/MINIMAL_v1.0.58.zip", "firmware/other/LIVEN_AMBIENT_1_5_45.syx",
           "firmware/other/LIVEN_BnB_SYSTEM_1_1_27.syx", "firmware/other/LIVEN_MEGA_SYSTEM_1_1_37.syx")
    def test_all_modern_descriptors(self):
        files = images = 0
        for path in sorted(list((ROOT / "firmware").rglob("*.zip")) + list((ROOT / "firmware").rglob("*.syx"))):
            if path.name == "CyDrums_folder.zip" or path.name.startswith("ELZ_1 v"):
                continue  # card content folder; the original ELZ_1's legacy header layout
            for _, data in integrity.inputs([path]):
                parsed = integrity.parse(data)
                files += 1
                images += len(parsed)
        self.assertEqual((files, images), (27, 65))

    @needs("firmware/smpltrek/SmplTrek v2.0.129.zip")
    def test_preset_mutation_and_nested_repair(self):
        """The one-byte content edit of experiments/README.md (one WAV byte at 0x1266CD4, C0 -> BF, CRCs left stale),
        rebuilt from the official file."""
        original = firmware("firmware/smpltrek/SmplTrek v2.0.129.zip")
        self.assertEqual(original[0x1266CD4], 0xC0)
        changed = original[:0x1266CD4] + b"\xbf" + original[0x1266CD4 + 1:]
        self.assertEqual([a == b for _, a, b in integrity.verify(changed, "smpltrek")], [False, False, True])
        repaired = integrity.reseal(changed, "smpltrek")
        self.assertTrue(all(a == b for _, a, b in integrity.verify(repaired, "smpltrek")))
        allowed = {i.offset + j for i in integrity.parse(changed) for j in range(8, 12)}
        self.assertTrue(all(a == b or k in allowed for k, (a, b) in enumerate(zip(changed, repaired))))
        self.assertEqual(repaired[0x1266CD4], 0xBF)
        mmtd = integrity.parse(original)[-1]
        self.assertEqual(repaired[mmtd.offset:], original[mmtd.offset:])

    @needs("firmware/smpltrek/SmplTrek v3.2.174.zip")
    def test_system_mutation_and_wrong_repair_order(self):
        original = firmware("firmware/smpltrek/SmplTrek v3.2.174.zip")
        changed = bytearray(original)
        changed[-1] ^= 1
        self.assertEqual([a == b for _, a, b in integrity.verify(changed, "smpltrek")], [False, False])
        repaired = integrity.reseal(changed, "smpltrek")
        self.assertTrue(all(a == b for _, a, b in integrity.verify(repaired, "smpltrek")))
        self.assertEqual(repaired[-1], changed[-1])
        parent, child = integrity.parse(changed)
        wrong_order = bytearray(changed)
        for image in (parent, child):
            value = integrity.checksum(wrong_order, image, integrity.PROFILES["smpltrek"][image.tag])
            struct.pack_into("<I", wrong_order, image.offset + 8, value)
        self.assertEqual([a == b for _, a, b in integrity.verify(wrong_order, "smpltrek")], [False, True])

    @WHOLE_CORPUS
    def test_seed_recovery_validates_on_another_release(self):
        first = firmware("firmware/lofi12/Lofi-12XT_v1.1.156.zip")
        second = firmware("firmware/lofi12/Lofi-12XT_v1.5.205.zip")
        for image, other in zip(integrity.parse(first), integrity.parse(second)):
            seed = integrity.recover_seed(first, image)
            self.assertEqual(seed, integrity.PROFILES["lofi12"][image.tag])
            self.assertEqual(integrity.checksum(second, other, seed), integrity.word(second, other.offset + 8))
        # ELZ_1 play: three releases (1.1.62, 2.0.109, 3.1.149) each recover the same three seeds.
        for _, data in integrity.inputs(sorted((ROOT / "firmware/other").glob("ELZ_1_play*.zip"))):
            for image in integrity.parse(data):
                self.assertEqual(integrity.recover_seed(data, image), integrity.PROFILES["elz1play"][image.tag])
        # Liven (SysEx updates): 8bit warps over three releases, Lofi-12 and XFM over two; CyDrums 1.1.84 and
        # 2.0.97 beta.
        for profile, pattern in (("liven8bit", "other/LIVEN_8SYSTEM*.syx"), ("livenlofi12", "other/LIVEN_LOFI*.syx"),
                                 ("livenxfm", "other/LIVEN_XFM*.syx"), ("cydrums", "cydrums/CyDrums_v*.zip")):
            for _, data in integrity.inputs(sorted((ROOT / "firmware").glob(pattern))):
                for image in integrity.parse(data):
                    self.assertEqual(integrity.recover_seed(data, image), integrity.PROFILES[profile][image.tag])

    @needs_set("other/LIVEN_*.syx", 10)
    def test_liven_sysex_device_byte_is_family_word(self):
        paths = sorted((ROOT / "firmware/other").glob("LIVEN_*.syx"))
        self.assertEqual(len(paths), 10)
        for path in paths:
            raw = path.read_bytes()
            data = integrity.unwrap_sysex(raw)
            self.assertEqual(raw[:6], integrity.SYSEX_HEADER)
            self.assertEqual(integrity.word(data, 16), raw[6])
            self.assertEqual(integrity.word(data, 4), len(data))
            with self.assertRaises(ValueError):
                integrity.unwrap_sysex(raw[:-250])  # a data message lost: length mismatch

    @needs("firmware/other/LIVEN_LOFI_SYSTEM_2_1_65.syx", "firmware/smpltrek/SmplTrek v3.2.174.zip")
    def test_cli_reseal_takes_syx_and_zip(self):
        """reseal unwraps a .syx and opens an official .zip like verify does; an unchanged file comes back as is."""
        import subprocess, tempfile
        cases = (("firmware/other/LIVEN_LOFI_SYSTEM_2_1_65.syx", "livenlofi12"),
                 ("firmware/smpltrek/SmplTrek v3.2.174.zip", "smpltrek"))
        for relative, profile in cases:
            with self.subTest(file=relative), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "out.bin"
                result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/sonicware_integrity.py"), "reseal",
                                         "--profile", profile, str(ROOT / relative), str(out)],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(out.read_bytes(), firmware(relative))

    @needs("firmware/smpltrek/SmplTrek v3.2.174.zip", "firmware/other/ELZ_1 v7.0.zip")
    def test_malformed_and_legacy_rejected(self):
        data = firmware("firmware/smpltrek/SmplTrek v3.2.174.zip")
        for bad in (b"", b"cmtd", data[:-1]):
            with self.assertRaises(ValueError):
                integrity.parse(bad)
        for offset, value in ((20, 0xFFFFFFFF), (24, 2), (40, 49), (44, len(data))):
            bad = bytearray(data)
            struct.pack_into("<I", bad, offset, value)
            with self.assertRaises(ValueError):
                integrity.parse(bad)
        with self.assertRaises(ValueError):
            integrity.parse(firmware("firmware/other/ELZ_1 v7.0.zip"))

    @needs("firmware/smpltrek/SmplTrek v3.2.174.zip")
    def test_independent_bitwise_crc(self):
        # Independent of zlib's table implementation: full genuine system image.
        data = firmware("firmware/smpltrek/SmplTrek v3.2.174.zip")
        image = integrity.parse(data)[-1]
        b = bytearray(data[image.offset:image.offset + image.size])
        b[8:12] = bytes(4)
        state = integrity.PROFILES["smpltrek"][image.tag] ^ 0xFFFFFFFF
        for byte in b:
            state ^= byte
            for _ in range(8):
                state = (state >> 1) ^ (0xEDB88320 if state & 1 else 0)
        self.assertEqual(state ^ 0xFFFFFFFF, integrity.word(data, image.offset + 8))
        self.assertEqual(zlib.crc32(b"123456789"), 0xCBF43926)

    # The SmplTrek bootloader (BOOT 1.0.17) does not zero the field and seed: it runs zlib CRC-32 from 0
    # with the CRC field replaced by a constant built in code (docs/05-bootloader.md, "CRC rule").
    FILL = {"cmtd": 0xF2970822, "pmtd": 0xB02C53FD, "mmtd": 0x88E83CEB}

    @needs_set("smpltrek/*.zip", 8)
    def test_bootloader_fill_constants_match_every_smpltrek_image(self):
        images = 0
        for _, data in integrity.inputs(sorted((ROOT / "firmware/smpltrek").glob("*.zip"))):
            for image in integrity.parse(data):
                b = data[image.offset:image.offset + image.size]
                filled = b[:8] + struct.pack("<I", self.FILL[image.tag]) + b[12:]
                self.assertEqual(zlib.crc32(filled), integrity.word(b, 8))
                self.assertEqual(zlib.crc32(filled), integrity.checksum(data, image, integrity.PROFILES["smpltrek"][image.tag]))
                images += 1
        self.assertEqual(images, 22)

    @unittest.skipUnless((ROOT / "work/a4/A4DUMP.BIN").exists(), "device flash dump not present")
    def test_installed_boot_image_matches_bootloader_constant(self):
        dump = (ROOT / "work/a4/A4DUMP.BIN").read_bytes()
        header = bytearray(dump[0x3FFE4:0x40000])
        stored = integrity.word(header, 8)
        struct.pack_into("<II", header, 8, 0xE255264C, 0xFFFFFFFF)  # fill constant; install marker as shipped
        self.assertEqual(zlib.crc32(bytes(header) + dump[:0x3FFE4]), stored)


if __name__ == "__main__":
    unittest.main()
