"""Benchmark CPU binding is local, validated and restored on failures."""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from performance import pinned_cpu, measure


@unittest.skipUnless(hasattr(os, "sched_setaffinity"), "Linux CPU affinity required")
class BenchmarkAffinity(unittest.TestCase):
    def test_binding_restores_allowed_cpus_after_success_and_exception(self):
        before = os.sched_getaffinity(0)
        chosen = min(before)
        with pinned_cpu(chosen) as binding:
            self.assertEqual(os.sched_getaffinity(0), {chosen})
            self.assertEqual(binding["effective_cpus"], [chosen])
        self.assertEqual(os.sched_getaffinity(0), before)
        with self.assertRaisesRegex(RuntimeError, "probe"):
            with pinned_cpu(chosen):
                raise RuntimeError("probe")
        self.assertEqual(os.sched_getaffinity(0), before)

    def test_invalid_cpu_and_sampling_period_fail_before_firmware_loading(self):
        for cpu in (True, -1, max(os.sched_getaffinity(0)) + 1, 0.5):
            with self.subTest(cpu=cpu), self.assertRaises(ValueError):
                with pinned_cpu(cpu):
                    self.fail("invalid affinity was accepted")
        for period in (True, -1, 1000001, 0.5):
            with self.subTest(period=period), self.assertRaises(ValueError):
                measure(guest_sample_period=period)


if __name__ == "__main__":
    unittest.main()
