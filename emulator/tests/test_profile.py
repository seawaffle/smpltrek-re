"""The optional host sampler must preserve process signals and resolve real native PCs."""
import collections
import ctypes as C
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from build import WORK
from profile_native import executable_bias, profile, resolve, sampler


@unittest.skipUnless(platform.system() == "Linux" and platform.machine() in ("x86_64", "aarch64")
                     and shutil.which("g++") and shutil.which("addr2line"), "Linux host sampling tools required")
class NativeProfile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        WORK.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(dir=WORK, prefix="test-profile-")
        cls.work = Path(cls.temporary.name)
        cls.native, cls.manifest = sampler(cls.work)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_timer_captures_pcs_and_restores_signal_handler_and_timer(self):
        # A separate process keeps ITIMER_PROF out of the test runner and other tests.
        script = r'''
import os, signal, sys, time
sys.path.insert(0, sys.argv[1])
from profile_native import sampler
native, _ = sampler(sys.argv[2])
received = []
signal.signal(signal.SIGPROF, lambda signum, frame: received.append(signum))
signal.setitimer(signal.ITIMER_PROF, 2.0, 3.0)
saved_remaining, saved_interval = signal.getitimer(signal.ITIMER_PROF)
assert native.sample_start(0) == -1
assert native.sample_start(1000) == 0
assert native.sample_start(1000) == -1
end = time.process_time() + 0.3
while time.process_time() < end:
    pass
assert native.sample_stop() == 0
assert native.sample_stop() == -1
remaining, interval = signal.getitimer(signal.ITIMER_PROF)
signal.setitimer(signal.ITIMER_PROF, 0)
# Linux may round both installing and restoring an ITIMER_PROF timer to ticks.
assert abs(remaining - saved_remaining) < 0.05, (remaining, saved_remaining)
assert interval == saved_interval, interval
assert native.sample_count() > 0
assert native.sample_dropped() == 0
assert all(native.sample_pc(i) for i in range(native.sample_count()))
assert native.sample_pc(native.sample_count()) == 0
assert not received
os.kill(os.getpid(), signal.SIGPROF)
assert received == [signal.SIGPROF], received
'''
        result = subprocess.run([sys.executable, "-B", "-c", script, str(HERE), str(self.work)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_resolver_accounts_for_relocated_library_and_unmapped_samples(self):
        pc = C.cast(self.native.sample_start, C.c_void_p).value
        # ctypes keeps libraries mapped after their temporary build directories are
        # removed. Unrelated stale mappings must not prevent resolving a valid PC.
        with tempfile.TemporaryDirectory(dir=self.work) as directory:
            path = Path(directory) / "deleted.so"
            shutil.copyfile(self.native._name, path)
            deleted = C.CDLL(str(path))
            deleted_pc = C.cast(deleted.sample_start, C.c_void_p).value
        rows, unknown = resolve(collections.Counter({pc: 7, deleted_pc: 3, 0: 5}))
        self.assertEqual(unknown, 8)
        self.assertEqual(sum(row["samples"] for row in rows), 7)
        self.assertTrue(any(frame["function"] == "sample_start" for row in rows for frame in row["frames"]))
        self.assertTrue(any("sampler.cpp:" in frame["source"] for row in rows for frame in row["frames"]))

    def test_invalid_interval_rejected_before_firmware_loading(self):
        for interval in (0, -1, 1000001, True, 1.5):
            with self.subTest(interval=interval), self.assertRaisesRegex(ValueError, "interval_us"):
                profile(self.work, interval_us=interval)

    def test_fixed_address_executables_and_shared_objects_use_elf_virtual_addresses(self):
        # ELF64 little-endian fixtures with one executable PT_LOAD segment. A fixed
        # executable needs its 0x400000 virtual base added back before addr2line.
        for base in (0, 0x400000):
            header = bytearray(64)
            header[:6] = b"\x7fELF\x02\x01"
            struct.pack_into("<Q", header, 32, 64)
            struct.pack_into("<HH", header, 54, 56, 1)
            segment = struct.pack("<IIQQQQQQ", 1, 5, 0x10000, base + 0x10000, 0, 4096, 4096, 4096)
            path = self.work / "host.elf"
            path.write_bytes(header + segment)
            self.assertEqual(executable_bias(path, 0x10000), base)


if __name__ == "__main__":
    unittest.main()
