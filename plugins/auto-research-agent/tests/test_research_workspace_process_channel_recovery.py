"""Fake child late-observation regressions; no Codex/model/research calls."""

import sqlite3
import time
import unittest
from unittest.mock import patch

from native_process_channel_fixtures import OwnedProcessCase
import research_workspace_native.process_channel as module


class ObservationTests(OwnedProcessCase):
    def test_read_save_timeout_keeps_raw_and_is_not_idle(self):
        channel = self.channel()
        channel._buffer = b"synthetic-retained\n"
        observe = channel._observe

        def failed(event, **payload):
            if event == "read":
                raise TimeoutError("synthetic SQLite busy")
            return observe(event, **payload)

        with patch.object(channel, "_observe", side_effect=failed):
            with self.assertRaisesRegex(ValueError, "unknown"):
                channel.read(262144, 0.1)
        self.assertEqual(channel._buffer, b"synthetic-retained\n")
        self.assertTrue(channel.closed)

    def test_write_result_after_absolute_deadline_is_unknown_not_success(self):
        channel = self.channel(lifetime=30)
        observe = channel._observe
        operation_deadlines, returned = [], []

        def expire_after_result(event, **payload):
            result = observe(event, **payload)
            if event == "write-intent":
                operation_deadlines.append(payload["deadline"])
            if event == "write-returned":
                returned.append((payload["deadline"], payload["count"]))
                # Expire this operation only after its real write observation
                # committed. Physical binding and intent I/O retain their budget.
                payload["deadline"].until = time.monotonic() - 1
            return result

        with (
            patch.object(channel, "_observe", side_effect=expire_after_result),
            patch.object(
                channel.process.stdin, "write", wraps=channel.process.stdin.write
            ) as write,
        ):
            with self.assertRaisesRegex(ValueError, "unknown"):
                channel.write(b"synthetic\n", 10)
            write.assert_called_once_with(b"synthetic\n")
            self.assertEqual(len(operation_deadlines), 1)
            self.assertEqual(returned, [(operation_deadlines[0], 10)])
            self.assertTrue(channel.closed)
            self.assertTrue(channel.reap()["leader_reaped"])
            with self.assertRaises(ValueError):
                channel.write(b"never-resend\n", 1)
            write.assert_called_once_with(b"synthetic\n")
        saved = [
            event["payload"]
            for event in self.store.events("alpha")
            if event["kind"] == "owned-process-write-returned"
        ]
        self.assertEqual(saved, [{"count": 10, "partial": False}])
        self.assertTrue(channel.closed)

    def test_post_spawn_database_busy_cannot_delay_lease_cleanup(self):
        blocker = sqlite3.connect(self.path)
        spawn = module.subprocess.Popen
        processes, blocked_at, startup_deadlines = [], [], []
        deadline = module.Deadline

        def bounded_startup(timeout, lease):
            # Isolate the post-spawn database budget from physical binary hashing
            # and synchronous OS process creation on loaded platform runners.
            value = deadline(min(timeout, 0.3), lease)
            startup_deadlines.append(value)
            return value

        def after_spawn(*args, **kwargs):
            process = spawn(*args, **kwargs)
            processes.append(process)
            blocker.execute("BEGIN IMMEDIATE")
            blocked_at.append(time.monotonic())
            return process

        try:
            with (
                patch.object(module.subprocess, "Popen", side_effect=after_spawn),
                patch.object(module, "Deadline", side_effect=bounded_startup),
            ):
                with self.assertRaises(ValueError):
                    self.channel(lifetime=10)
            self.assertEqual(len(processes), 1, "must reach the post-spawn boundary")
            self.assertEqual(len(startup_deadlines), 1)
            self.assertLess(time.monotonic() - blocked_at[0], 0.8)
            until = time.monotonic() + 1
            while processes[0].poll() is None and time.monotonic() < until:
                time.sleep(0.01)
            self.assertIsNotNone(processes[0].poll())
        finally:
            blocker.rollback()
            blocker.close()
            for process in processes:
                process.wait(timeout=2)


if __name__ == "__main__":
    unittest.main()
