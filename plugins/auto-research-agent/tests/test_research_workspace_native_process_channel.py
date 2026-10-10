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

    def test_stdout_burst_survives_delayed_consumer_without_losing_binding(self):
        raw = b"x" * (4096 * 12)
        self.child.write_text(
            "import os,sys\nos.write(1,b'x'*(4096*12))\nfor line in sys.stdin.buffer:pass\n",
            encoding="utf8",
        )
        channel = self.channel(lifetime=30)
        before = self.state()["intents"]["spawn"]["payload"]
        with self.store._lock:
            until = time.monotonic() + 3
            while not channel._stdout.full() and time.monotonic() < until:
                time.sleep(0.01)
            self.assertTrue(
                channel._stdout.full(), "synthetic burst did not fill queue"
            )
            time.sleep(1.25)  # Simulate a consumer occupied by source admission.
            diagnostic = dict(
                closed=channel.closed,
                failure=channel.failure,
                payload_unchanged=self.state()["intents"]["spawn"]["payload"] == before,
            )
            if channel.closed:
                try:
                    channel.read(4096, 0)
                except Exception as error:
                    diagnostic.update(
                        read_error=type(error).__name__, read_reason=str(error)
                    )
            self.assertFalse(channel.closed, diagnostic)
        with patch.object(
            channel.process.stdin, "write", wraps=channel.process.stdin.write
        ) as writes:
            received = b""
            while len(received) < len(raw):
                received += channel.read(4096, 2)
            self.assertEqual(received, raw)
            writes.assert_not_called()
        self.assertEqual(self.state()["intents"]["spawn"]["payload"], before)
        channel.close()
        self.assertTrue(channel.reap()["leader_reaped"])

    def test_full_stdout_queue_close_reaps_and_exits_all_workers(self):
        self.child.write_text(
            "import os,sys\nos.write(1,b'x'*(4096*12))\nfor line in sys.stdin.buffer:pass\n",
            encoding="utf8",
        )
        channel = self.channel(lifetime=30)
        until = time.monotonic() + 3
        while not channel._stdout.full() and time.monotonic() < until:
            time.sleep(0.01)
        self.assertTrue(channel._stdout.full(), "synthetic burst did not fill queue")
        before = tuple(channel._workers)
        channel.close()
        self.assertTrue(channel.reap()["leader_reaped"])
        until = time.monotonic() + 0.5
        while any(worker.is_alive() for worker in before) and time.monotonic() < until:
            time.sleep(0.01)
        self.assertFalse(any(worker.is_alive() for worker in before))

    def test_full_stdout_queue_wait_stays_within_process_lease(self):
        self.child.write_text(
            "import os,sys\nos.write(1,b'x'*(4096*12))\nfor line in sys.stdin.buffer:pass\n",
            encoding="utf8",
        )
        channel = self.channel(lifetime=5)
        until = time.monotonic() + 3
        while not channel._stdout.full() and time.monotonic() < until:
            time.sleep(0.01)
        self.assertTrue(channel._stdout.full(), "synthetic burst did not fill queue")
        time.sleep(max(0, channel.deadline - time.monotonic()) + 0.15)
        self.assertTrue(channel.closed)
        self.assertTrue(channel.reap()["leader_reaped"])
        with patch.object(
            channel.process.stdin, "write", wraps=channel.process.stdin.write
        ) as writes:
            with self.assertRaises(TimeoutError):
                channel.write(b"never", 1)
            writes.assert_not_called()

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
        from types import SimpleNamespace
        import research_workspace_native.process_channel as module

        self.child.write_text("import time\ntime.sleep(30)\n", encoding="utf8")
        channel = self.channel(lifetime=30)
        entered, returned = threading.Event(), threading.Event()
        deadlines, expired = [], []
        deadline, queue, raw_write = (
            module.Deadline,
            module.queue,
            channel.process.stdin.write,
        )
        case = self

        def capture_deadline(timeout, lease):
            value = deadline(timeout, lease)
            deadlines.append(value)
            return value

        def blocked_write(data):
            entered.set()
            try:
                return raw_write(data)
            finally:
                returned.set()

        class ResultAfterEntry(queue.Queue):
            def get(self, *, timeout):
                # Only the completion queue is replaced. Wait for the real OS
                # write entry before expiring this operation, not its setup.
                case.assertTrue(entered.wait(5), "must enter the real stdin write")
                case.assertFalse(returned.is_set(), "write must still be blocked")
                case.assertEqual(len(deadlines), 1)
                deadlines[0].until = time.monotonic() - 1
                expired.append(deadlines[0])
                return super().get(timeout=deadlines[0].left())

        data = b"x" * 262144
        with (
            patch.object(module, "Deadline", side_effect=capture_deadline),
            patch.object(
                module,
                "queue",
                SimpleNamespace(Queue=ResultAfterEntry, Empty=queue.Empty),
            ),
            patch.object(
                channel.process.stdin, "write", side_effect=blocked_write
            ) as write,
        ):
            with self.assertRaisesRegex(ValueError, "unknown") as failure:
                channel.write(data, 10)
            self.assertIsInstance(failure.exception.__cause__, queue.Empty)
            self.assertEqual(expired, deadlines)
            self.assertTrue(entered.is_set())
            write.assert_called_once_with(data)
            self.assertTrue(channel.closed)
            self.assertTrue(channel.reap()["leader_reaped"])
            self.assertTrue(returned.wait(2), "blocked writer must exit after reap")
            with self.assertRaises(ValueError):
                channel.write(b"never", 1)
            write.assert_called_once_with(data)

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

    def test_fake_child_startup_latency_preserves_handoff_identity(self):
        self._assert_real_fake_child_recording_bootstrap_and_same_transport_handoff(
            startup_delay=2.5
        )


if __name__ == "__main__":
    unittest.main()
