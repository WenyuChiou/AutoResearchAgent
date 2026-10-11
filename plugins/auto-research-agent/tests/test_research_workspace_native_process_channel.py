"""Real local fake children and SQLite; never actual Codex/model/research."""

from contextlib import redirect_stderr
import io
import json
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
        # Admission consumes lifetime too; leave room to reach the watchdog.
        channel = self.channel(lifetime=5)
        time.sleep(5.2)
        self.assertTrue(channel.closed)
        self.assertTrue(channel.reap()["leader_reaped"])
        self.assertIn("TimeoutError", channel.failure)

    def test_lifetime_cleanup_survives_slow_admission(self):
        from research_workspace_native.process_channel import OwnedProcessChannel

        admit = OwnedProcessChannel._admit

        def slow_admit(channel):
            time.sleep(0.35)
            return admit(channel)

        with patch.object(OwnedProcessChannel, "_admit", slow_admit):
            self.test_lifetime_expires_even_with_no_ui_calls()

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
        entered, release, left = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )

        def holder():
            with self.store._lock:
                entered.set()
                release.wait(10)
                left.set()

        worker = threading.Thread(target=holder)
        worker.start()
        self.assertTrue(entered.wait(1))
        try:
            start = time.monotonic()
            channel.close()
            self.assertLess(time.monotonic() - start, 0.2)
            until = time.monotonic() + 5
            while channel.process.poll() is None and time.monotonic() < until:
                time.sleep(0.01)
            self.assertIsNotNone(channel.process.poll())
            self.assertFalse(left.is_set())
            self.assertFalse(channel._cleanup_done.is_set())
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertTrue(channel.reap()["leader_reaped"])

    def test_sqlite_writer_lock_cannot_delay_lease_physical_cleanup(self):
        self.child.write_text("import time\ntime.sleep(30)\n", encoding="utf8")
        lease_gate = threading.Event()
        thread_type = threading.Thread
        deferred_leases = []

        def defer_lease(*args, **kwargs):
            target = kwargs.get("target")
            if getattr(target, "__name__", None) == "lease":
                deferred_leases.append(target)

                def gated_lease():
                    lease_gate.wait(10)
                    target()

                kwargs["target"] = gated_lease
            return thread_type(*args, **kwargs)

        competing = None
        try:
            # Constructor admission retains the normal bounded setup lease.
            # Arm the same 0.3-second expiry only after the writer lock exists.
            with patch(
                "research_workspace_native.process_channel.threading.Thread",
                side_effect=defer_lease,
            ):
                channel = self.channel()
            self.assertEqual(len(deferred_leases), 1)
            competing = sqlite3.connect(self.path)
            competing.execute("BEGIN IMMEDIATE")
            channel.deadline = time.monotonic() + 0.3
            lease_gate.set()
            # Close intent and leader exit precede publication of the physical
            # report. Observe that phase while the writer lock still blocks
            # the journal, without treating scheduler latency as a lease limit.
            until = time.monotonic() + 5
            while (
                channel.process.poll() is None
                or not isinstance(channel._cleanup_result, dict)
                or "journal_cleanup_observed" not in channel._cleanup_result
            ) and time.monotonic() < until:
                time.sleep(0.02)
            self.assertTrue(channel.closed)
            self.assertIsNotNone(channel.process.poll())
            self.assertIsInstance(channel._cleanup_result, dict)
            self.assertIn("journal_cleanup_observed", channel._cleanup_result)
            with self.assertRaises(TimeoutError):
                channel.reap(timeout=0.1)
            self.assertFalse(channel._cleanup_result["journal_cleanup_observed"])
        finally:
            lease_gate.set()
            if competing is not None:
                competing.rollback()
                competing.close()
        self.assertTrue(channel.reap()["leader_reaped"])

    def test_sqlite_lease_cleanup_is_independent_of_slow_construction(self):
        from research_workspace_native.process_channel import OwnedProcessChannel

        observe = OwnedProcessChannel._observe

        def slow_started(channel, event, **payload):
            if event == "process-started":
                time.sleep(0.35)
            return observe(channel, event, **payload)

        with patch.object(OwnedProcessChannel, "_observe", slow_started):
            self.test_sqlite_writer_lock_cannot_delay_lease_physical_cleanup()

    def test_sqlite_cleanup_waits_for_physical_report_publication(self):
        import research_workspace_native.process_channel as module

        original = module._cleanup

        def delayed_report(process):
            result = original(process)
            time.sleep(1.8)
            return result

        with patch.object(module, "_cleanup", side_effect=delayed_report):
            self.test_sqlite_writer_lock_cannot_delay_lease_physical_cleanup()

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

    def test_failed_bootstrap_reports_phase_clock_without_resend(self):
        from research_workspace_native.bootstrap import BootstrapSession

        captured = io.StringIO()
        with (
            redirect_stderr(captured),
            patch.object(
                BootstrapSession, "_send", side_effect=ValueError("synthetic failure")
            ) as send,
        ):
            with self.assertRaises(ValueError):
                self._assert_real_fake_child_recording_bootstrap_and_same_transport_handoff()
        report = json.loads(captured.getvalue())
        self.assertEqual(report["kind"], "FakeChildBootstrapTiming")
        self.assertEqual(report["deadline_seconds"], 10)
        self.assertEqual(report["startup_delay_seconds"], 0)
        self.assertGreaterEqual(report["elapsed_seconds"], 0)
        self.assertEqual(len(report["phases"]), 1)
        self.assertEqual(report["phases"][0]["method"], "initialize")
        self.assertEqual(report["phases"][0]["outcome"], "raised")
        self.assertGreaterEqual(report["phases"][0]["seconds"], 0)
        send.assert_called_once()
        self.assertEqual(self.state()["bootstrap"]["phase"], "failed")


if __name__ == "__main__":
    unittest.main()
