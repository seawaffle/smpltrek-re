"""Real GCC PGO round trip, relocated counters, strict provenance and unseen arithmetic inputs."""
import ctypes as C
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build import WORK, digest
import core_build as build

SOURCE = b"""#include <cstdint>
extern "C" int64_t branchy(int32_t x) {
    if (x < 0) return -int64_t(x) * 3;
    return x < 20 ? int64_t(x) * x + 7 : int64_t(x) * 5 - 4;
}
extern "C" double separate(double a, double b, double c) { return a * b + c; }
"""


@unittest.skipUnless(shutil.which("g++"), "GCC C++ required")
class ProfileBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (WORK / "test-tmp").mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(prefix="pgo-build-", dir=WORK / "test-tmp")
        cls.work = Path(cls.temporary.name)
        cls.compiler, _, cls.recipe = build._snapshot()
        cls.sources = {"core.cpp": SOURCE}
        cls.recipe = {**cls.recipe, "source_sha256": {"core.cpp": digest(SOURCE)}}
        cls.bundle = cls.work / "bundle"; cls.bundle.mkdir()
        with cls.snapshot():
            library, _ = build.instrument_core(cls.bundle)
            child = ("import ctypes as C,sys;lib=C.CDLL(sys.argv[1]);"
                     "lib.branchy.argtypes=[C.c_int32];lib.branchy.restype=C.c_int64;"
                     "lib.separate.argtypes=[C.c_double]*3;lib.separate.restype=C.c_double;"
                     "[lib.branchy(x) for x in [2,3,10,25,64]*1000];lib.separate(1.25,3,-1.5)")
            environment = os.environ.copy()
            for key in ("GCOV_PREFIX", "GCOV_PREFIX_STRIP", "GCOV_ERROR_FILE"):
                environment.pop(key, None)
            subprocess.run([sys.executable, "-B", "-c", child, str(library)], check=True, env=environment)
            build.finalize_profile(cls.bundle, dict(kind="source-only GCC fixture", passed=True))

    @classmethod
    def snapshot(cls, source=SOURCE):
        recipe = {**cls.recipe, "source_sha256": {"core.cpp": digest(source)}}
        return mock.patch.object(build, "_snapshot", return_value=(cls.compiler, {"core.cpp": source}, recipe))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_relocated_frozen_profile_preserves_unseen_integer_and_fp_inputs(self):
        relocated = self.work / "relocated"
        shutil.copytree(self.bundle, relocated)
        # Collection output is no longer an input after finalization.
        for path in (relocated / "collect-counts").iterdir():
            path.write_bytes(b"late collector output")
        with self.snapshot():
            library, manifest = build.build_core(self.work / "relocated-cache", profile=relocated)
            self.assertEqual(manifest["optimization"]["kind"], "gcc-pgo")
            with self.assertRaisesRegex(ValueError, "already finalized"):
                build.collection_core(relocated)
        lib = C.CDLL(str(library))
        lib.branchy.argtypes = [C.c_int32]; lib.branchy.restype = C.c_int64
        # None of the negative/extreme values were in the training process.
        for x in (-2147483648, -100, -1, 0, 19, 20, 2147483647):
            expected = -x * 3 if x < 0 else x * x + 7 if x < 20 else x * 5 - 4
            self.assertEqual(lib.branchy(x), expected)
        lib.separate.argtypes = [C.c_double] * 3; lib.separate.restype = C.c_double
        for a, b, c in ((1 + 2**-27, 1 - 2**-27, -1), (-0.0, 1.0, -0.0),
                        (2**-500, 2**-500, 0.0), (math.inf, 0.0, 0.0), (math.nan, 1.0, 1.0)):
            expected = a * b + c
            actual = lib.separate(a, b, c)
            if math.isnan(expected):
                self.assertTrue(math.isnan(actual))
            else:
                self.assertEqual(struct.pack("<d", actual), struct.pack("<d", expected))

    def test_stale_or_corrupt_profile_is_rejected_and_auto_build_uses_current_code(self):
        active = self.work / "active.json"
        with mock.patch.object(build, "ACTIVE_PROFILE", active), self.snapshot():
            build.activate_profile(self.bundle)
        changed = SOURCE.replace(b"+ 7", b"+ 8")
        with mock.patch.object(build, "ACTIVE_PROFILE", active), self.snapshot(changed):
            with self.assertRaisesRegex(ValueError, "source_sha256 changed"):
                build.build_core(self.work / "stale-explicit", profile=self.bundle)
            with mock.patch.dict(os.environ):
                os.environ.pop(build.PROFILE_ENV, None)
                library, manifest = build.build_core(self.work / "stale-auto")
            self.assertEqual(manifest["optimization"]["kind"], "portable")
            self.assertIn("source_sha256 changed", manifest["profile_selection"])
            lib = C.CDLL(str(library)); lib.branchy.argtypes = [C.c_int32]; lib.branchy.restype = C.c_int64
            self.assertEqual(lib.branchy(2), 12)  # The current source, rather than the old trained code.
        corrupt = self.work / "corrupt"; shutil.copytree(self.bundle, corrupt)
        next((corrupt / "counts").iterdir()).write_bytes(b"corrupt")
        with self.snapshot():
            with self.assertRaisesRegex(ValueError, "counter hash mismatch"):
                build.build_core(self.work / "corrupt-explicit", profile=corrupt)
