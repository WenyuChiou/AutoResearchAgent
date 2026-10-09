"""Real local fake children and SQLite; never actual Codex/model/research."""

from pathlib import Path
import sys
import sqlite3
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from research_workspace_native.frame_journal import FrameJournal
from native_process_channel_fixtures import OwnedProcessCase


class OwnedProcessTests(OwnedProcessCase):
    def test_echo_fixed_argv_write_counts_read_chunks_stderr_and_reap(self):
        channel = self.channel()
        self.assertEqual(
            channel.process.args,
            [str(Path(sys.executable).resolve()), "app-server", "--stdio"],
        )
        self.assertEqual(channel.write(b"hello\n", 2), 6)
        self.assertEqual(channel.read(3, 2), b"syn")
        self.assertEqual(channel.read(262144, 2), b"thetic:hello\n")
        channel.close()
        result = channel.reap()
        self.assertTrue(result["leader_reaped"])
        self.assertFalse(result["process_tree_containment_verified"])
        self.assertEqual(self.state()["intents"]["spawn"]["status"], "completed")
        self.assertFalse(
            self.state()["process_channels"]["synthetic-epoch"]["authenticated_process"]
        )

    def test_nonliteral_source_admission_owner_and_version_have_zero_spawn(self):
        before = self.state()
        with patch(
            "research_workspace_native.process_channel.subprocess.Popen"
        ) as spawn:
            for changes in (
                {"admit_spawn": lambda offer: 1},
                {"verify_binding": lambda: None},
                {"owner": "wrong"},
                {"input_version": "c" * 64},
            ):
                with self.assertRaises(ValueError):
                    self.channel(**changes)
            spawn.assert_not_called()
        self.assertEqual(self.state(), before)

    def test_spawn_failure_is_retained_and_cannot_relaunch(self):
        with patch(
            "research_workspace_native.process_channel.subprocess.Popen",
            side_effect=OSError("synthetic spawn failure"),
        ) as spawn:
            with self.assertRaises(ValueError):
                self.channel()
            with self.assertRaises(ValueError):
                self.channel()
            self.assertEqual(spawn.call_count, 1)
        self.assertEqual(self.state()["intents"]["spawn"]["status"], "dispatching")
        self.assertGreater(
            self.state()["process_channels"]["synthetic-epoch"]["events"], 0
        )

    def test_read_timeout_is_idle_and_source_drift_faults_before_write(self):
        channel = self.channel()
        with self.assertRaises(TimeoutError):
            channel.read(10, 0.1)
        channel.verify_binding = lambda: False
        with self.assertRaises(ValueError):
            channel.write(b"never\n", 1)
        self.assertTrue(channel.closed)
        self.assertTrue(channel.reap()["leader_reaped"])

    def test_lifetime_expires_even_with_no_ui_calls(self):
        self.child.write_text("import time\ntime.sleep(30)\n", encoding="utf8")
        channel = self.channel(lifetime=0.3)
        time.sleep(0.5)
        self.assertTrue(channel.closed)
        self.assertTrue(channel.reap()["leader_reaped"])
        self.assertIn("TimeoutError", channel.failure)

    def test_stream_overflow_closes_and_reports_failure(self):
        self.child.write_text(
            "import os,time\nos.write(1,b'x'*65536)\ntime.sleep(30)\n", encoding="utf8"
        )
        channel = self.channel(max_stream_bytes=1024)
        until = time.monotonic() + 3
        while not channel.closed and time.monotonic() < until:
            time.sleep(0.02)
        self.assertTrue(channel.closed)
        self.assertTrue(channel.reap()["leader_reaped"])
        self.assertIn("ValueError", channel.failure)

    def test_blocked_write_timeout_retains_unknown_and_kills_without_resend(self):
        self.child.write_text("import time\ntime.sleep(30)\n", encoding="utf8")
        channel = self.channel()
        with self.assertRaisesRegex(ValueError, "unknown"):
            channel.write(b"x" * 262144, 0.1)
        self.assertTrue(channel.closed)
        self.assertTrue(channel.reap()["leader_reaped"])
        with self.assertRaises(ValueError):
            channel.write(b"never", 1)

    def test_reopen_keeps_history_and_never_spawns_again(self):
        channel = self.channel()
        channel.close()
        channel.reap()
        self.store.close()
        self.store = FrameJournal(self.path)
        self.addCleanup(self.store.close)
        self.owner = self.store.acquire_owner("alpha", "recovered")
        with patch(
            "research_workspace_native.process_channel.subprocess.Popen"
        ) as spawn:
            with self.assertRaises(ValueError):
                self.channel(connection_id="new")
            spawn.assert_not_called()
        self.assertTrue(self.state()["process_channels"])

    def test_write_lock_and_expired_journal_wait_do_not_dispatch(self):
        self._assert_write_lock_and_expired_journal_wait_do_not_dispatch()

    def test_zero_timeout_consumes_already_buffered_stdout(self):
        self._assert_zero_timeout_consumes_already_buffered_stdout()

    def test_expired_slow_spawn_gate_and_refused_transition_have_zero_spawn(self):
        def slow(offer):
            time.sleep(0.1)
            return True

        with patch(
            "research_workspace_native.process_channel.subprocess.Popen"
        ) as spawn:
            with self.assertRaises(TimeoutError):
                self.channel(admit_spawn=slow, lifetime=0.05)
            with patch.object(
                self.store,
                "transition_intent",
                return_value={"status": "execution-unknown"},
            ):
                with self.assertRaises(ValueError):
                    self.channel()
            spawn.assert_not_called()

    def test_close_starts_physical_cleanup_while_other_thread_holds_store(self):
        channel = self.channel()
        entered, release = threading.Event(), threading.Event()

        def holder():
            with self.store._lock:
                entered.set()
                release.wait(2)

        worker = threading.Thread(target=holder)
        worker.start()
        self.assertTrue(entered.wait(1))
        try:
            start = time.monotonic()
            channel.close()
            self.assertLess(time.monotonic() - start, 0.2)
            until = time.monotonic() + 1
            while channel.process.poll() is None and time.monotonic() < until:
                time.sleep(0.01)
            self.assertIsNotNone(channel.process.poll())
        finally:
            release.set()
            worker.join(2)
        self.assertTrue(channel.reap()["leader_reaped"])

    def test_sqlite_writer_lock_cannot_delay_lease_physical_cleanup(self):
        self.child.write_text("import time\ntime.sleep(30)\n", encoding="utf8")
        channel = self.channel(lifetime=0.3)
        competing = sqlite3.connect(self.path)
        competing.execute("BEGIN IMMEDIATE")
        try:
            until = time.monotonic() + 1.5
            while channel.process.poll() is None and time.monotonic() < until:
                time.sleep(0.02)
            self.assertTrue(channel.closed)
            self.assertIsNotNone(channel.process.poll())
            with self.assertRaises(TimeoutError):
                channel.reap(timeout=0.1)
            self.assertFalse(channel._cleanup_result["journal_cleanup_observed"])
        finally:
            competing.rollback()
            competing.close()
        self.assertTrue(channel.reap()["leader_reaped"])

    def test_store_lock_and_sqlite_busy_raw_write_return_at_deadline(self):
        channel = self.channel()
        entered, release = threading.Event(), threading.Event()

        def hold():
            with self.store._lock:
                entered.set()
                release.wait(2)

        worker = threading.Thread(target=hold)
        worker.start()
        self.assertTrue(entered.wait(1))
        with patch.object(
            channel.process.stdin, "write", wraps=channel.process.stdin.write
        ) as write:
            start = time.monotonic()
            try:
                with self.assertRaises(TimeoutError):
                    channel.write(b"never", 0.05)
                self.assertLess(time.monotonic() - start, 0.3)
            finally:
                release.set()
                worker.join(2)
            competing = sqlite3.connect(self.path)
            competing.execute("BEGIN IMMEDIATE")
            start = time.monotonic()
            try:
                with self.assertRaises(TimeoutError):
                    channel.write(b"never", 0.05)
                self.assertLess(time.monotonic() - start, 0.3)
            finally:
                competing.rollback()
                competing.close()
            write.assert_not_called()

    def test_slow_source_callback_cannot_delay_or_dispatch_raw_write(self):
        channel = self.channel()
        channel.verify_binding = lambda: time.sleep(0.4) or True
        with patch.object(
            channel.process.stdin, "write", wraps=channel.process.stdin.write
        ) as write:
            start = time.monotonic()
            with self.assertRaises(TimeoutError):
                channel.write(b"never", 0.05)
            self.assertLess(time.monotonic() - start, 0.3)
            write.assert_not_called()

    def test_real_fake_child_recording_bootstrap_and_same_transport_handoff(self):
        self._assert_real_fake_child_recording_bootstrap_and_same_transport_handoff()


if __name__ == "__main__":
    unittest.main()
