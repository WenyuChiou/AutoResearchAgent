"""Business clocks exclude bounded local verification; a controlled clock only."""

from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from research_workspace_native import process_deadline
from research_workspace_native.process_deadline import Deadline
from stage1_retrieval import verification_clock as vc


class FakeTime:
    def __init__(self, now=1_000_000.0):
        self.now = now
        self._lock = threading.Lock()

    def monotonic(self):
        with self._lock:
            return self.now

    time = monotonic

    def advance(self, seconds):
        with self._lock:
            self.now += seconds


class ClockCase(unittest.TestCase):
    def setUp(self):
        self.clock = FakeTime()
        for target in (vc, process_deadline):
            patcher = patch.object(target, "time", self.clock)
            patcher.start()
            self.addCleanup(patcher.stop)

    def business(self):
        # The pattern each business clock uses: raw clock minus excluded time.
        return self.clock.monotonic() - vc.excluded()

    def meter(self, **limits):
        values = dict(base_seconds=10, pass_seconds=1, per_file_seconds=0.005)
        values.update(limits)
        return vc.Meter(**values)


class MeterTests(ClockCase):
    def test_without_meter_everything_is_the_raw_clock_and_spans_are_free(self):
        with vc.local_verification(10**6):
            self.clock.advance(5000)
        self.assertEqual(self.business(), self.clock.now)
        self.assertEqual(vc.excluded(), 0)

    def test_verification_is_excluded_but_other_time_is_not(self):
        with vc.metering(self.meter()) as meter:
            start = self.business()
            with vc.local_verification(13696):
                self.clock.advance(50)
            self.clock.advance(3)  # an external action
            self.assertEqual(self.business() - start, 3)
            snapshot = meter.snapshot()
            self.assertAlmostEqual(snapshot.pop("allowance"), 10 + 1 + 13696 * 0.005)
            self.assertEqual(snapshot, dict(seconds=50, passes=1, files=13696))

    def test_nested_and_concurrent_spans_count_wall_time_once(self):
        with vc.metering(self.meter()) as meter:
            with vc.local_verification(100):
                self.clock.advance(2)
                with vc.local_verification(100):
                    self.clock.advance(3)
            self.assertEqual(meter.snapshot()["seconds"], 5)
            self.assertEqual(meter.snapshot()["passes"], 2)

    def test_pass_over_its_own_budget_fails_with_a_distinct_reason(self):
        with vc.metering(self.meter(base_seconds=1, pass_seconds=0)) as meter:
            start = self.business()
            with self.assertRaises(vc.LocalVerificationBudgetExceeded) as caught:
                with vc.local_verification(200):  # allowance 1 + 1 = 2 s
                    self.clock.advance(7)
            self.assertEqual(caught.exception.code, vc.BUDGET_CODE)
            self.assertNotIsInstance(caught.exception, LookupError)
            # Time beyond the allowance is business time: no unbounded skip.
            self.assertEqual(self.business() - start, 5)
            self.assertEqual(meter.excluded(), 2)

    def test_running_verification_stops_being_excluded_at_its_allowance(self):
        with vc.metering(self.meter(base_seconds=4, pass_seconds=0)):
            start = self.business()
            with self.assertRaises(vc.LocalVerificationBudgetExceeded):
                with vc.local_verification(0):
                    self.clock.advance(3)
                    self.assertEqual(self.business(), start)
                    self.clock.advance(6)  # still running: 5 s now count
                    self.assertEqual(self.business() - start, 5)

    def test_failing_pass_keeps_its_own_error(self):
        with vc.metering(self.meter(base_seconds=0, pass_seconds=0)):
            with self.assertRaisesRegex(ValueError, "bytes differ"):
                with vc.local_verification(0):
                    self.clock.advance(9)
                    raise ValueError("bytes differ")

    def test_pass_count_is_bounded(self):
        with vc.metering(self.meter(max_passes=2)):
            for _ in range(2):
                with vc.local_verification(1):
                    pass
            with self.assertRaises(vc.LocalVerificationBudgetExceeded):
                with vc.local_verification(1):
                    self.fail("third pass ran")

    def test_meter_is_scoped_to_its_context(self):
        seen = []
        with vc.metering(self.meter()):
            with vc.local_verification(1):
                self.clock.advance(4)
            thread = threading.Thread(target=lambda: seen.append(vc.excluded()))
            thread.start()
            thread.join()
        self.assertEqual(seen, [0])  # plain threads do not inherit the meter
        self.assertIsNone(vc.current())


class DeadlineTests(ClockCase):
    def test_guard_thread_verification_extends_io_timeout(self):
        def verify():
            with vc.local_verification(4000):
                self.clock.advance(20)
            return True

        with vc.metering(self.meter()):
            deadline = Deadline(1, self.clock.now + 600)
            deadline.guard(verify)
            self.assertEqual(deadline.left(), 1)

    def test_guard_non_verification_time_still_expires(self):
        def verify():
            self.clock.advance(2)  # not a verification pass
            return True

        with vc.metering(self.meter()):
            deadline = Deadline(1, self.clock.now + 600)
            with self.assertRaises(TimeoutError):
                deadline.guard(verify)

    def test_process_lease_is_never_extended(self):
        def verify():
            with vc.local_verification(4000):
                self.clock.advance(20)
            return True

        with vc.metering(self.meter()):
            deadline = Deadline(30, self.clock.now + 5)
            with self.assertRaises(TimeoutError):
                deadline.guard(verify)
            self.assertEqual(deadline.left(), 0)

    def test_plain_thread_reads_the_same_remaining_time(self):
        seen = []
        with vc.metering(self.meter()):
            with vc.local_verification(4000):
                self.clock.advance(15)  # excluded before the Deadline exists
            deadline = Deadline(1, self.clock.now + 600)
            thread = threading.Thread(target=lambda: seen.append(deadline.left()))
            thread.start()
            thread.join()
            with vc.local_verification(4000):
                self.clock.advance(5)  # excluded after: extends it
            thread = threading.Thread(target=lambda: seen.append(deadline.left()))
            thread.start()
            thread.join()
            seen.append(deadline.left())
        self.assertEqual(seen, [1, 1, 1])

    def test_without_meter_deadline_is_unchanged(self):
        deadline = Deadline(30, self.clock.now + 5)
        self.assertEqual(deadline.left(), 5)
        self.clock.advance(2)
        self.assertEqual(deadline.left(), 3)


if __name__ == "__main__":
    unittest.main()
