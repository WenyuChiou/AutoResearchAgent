"""Pure locks/SQLite/source workers only; no model or process dispatch."""

from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from research_workspace_native.frame_journal import FrameJournal
from research_workspace_native.process_deadline import Deadline


class DeadlineTests(unittest.TestCase):
    def test_held_lock_times_out_instead_of_waiting_for_release(self):
        lock = threading.Lock()
        lock.acquire()
        start = time.monotonic()
        try:
            with self.assertRaises(TimeoutError), Deadline(0.05, start + 2).hold(lock):
                self.fail("lock acquired")
        finally:
            lock.release()
        self.assertLess(time.monotonic() - start, 0.3)

    def test_slow_readonly_guard_times_out_and_late_true_is_not_admitted(self):
        start = time.monotonic()
        with self.assertRaises(TimeoutError):
            Deadline(0.05, start + 2).guard(lambda: time.sleep(0.2) or True)
        self.assertLess(time.monotonic() - start, 0.3)
        time.sleep(0.2)

    def test_database_busy_wait_is_bounded_and_original_timeout_restored(self):
        with tempfile.TemporaryDirectory() as folder:
            store = FrameJournal(Path(folder).resolve() / "synthetic.sqlite")
            try:
                blocker = sqlite3.connect(store.path)
                blocker.execute("BEGIN IMMEDIATE")
                start = time.monotonic()
                try:
                    with (
                        self.assertRaises(TimeoutError),
                        Deadline(0.05, start + 2).database(store),
                    ):
                        self.assertEqual(
                            store.db.execute("PRAGMA busy_timeout").fetchone()[0], 0
                        )
                        store.db.execute("BEGIN IMMEDIATE")
                    elapsed = time.monotonic() - start
                finally:
                    blocker.rollback()
                    blocker.close()
                self.assertLess(elapsed, 0.3)
                self.assertEqual(
                    store.db.execute("PRAGMA busy_timeout").fetchone()[0], 5000
                )
            finally:
                store.close()

    def test_zero_timeout_database_allows_passive_nonblocking_reads(self):
        with tempfile.TemporaryDirectory() as folder:
            store = FrameJournal(Path(folder).resolve() / "synthetic.sqlite")
            try:
                with Deadline(0, time.monotonic() + 2).database(store):
                    self.assertEqual(store.db.execute("SELECT 1").fetchone()[0], 1)
                    self.assertEqual(
                        store.db.execute("PRAGMA busy_timeout").fetchone()[0], 0
                    )
                self.assertEqual(
                    store.db.execute("PRAGMA busy_timeout").fetchone()[0], 5000
                )
            finally:
                store.close()

    def test_refresh_never_reenables_database_busy_wait(self):
        with tempfile.TemporaryDirectory() as folder:
            store = FrameJournal(Path(folder).resolve() / "synthetic.sqlite")
            try:
                deadline = Deadline(1, time.monotonic() + 2)
                with deadline.database(store):
                    deadline.refresh(store)
                    self.assertEqual(
                        store.db.execute("PRAGMA busy_timeout").fetchone()[0], 0
                    )
                self.assertEqual(
                    store.db.execute("PRAGMA busy_timeout").fetchone()[0], 5000
                )
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
