"""Actual Python fake children; these checks never start the Codex executable."""

import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from research_workspace_native import codex_probe as probe  # noqa: E402


CHILD = r"""
import json, os, sys, time
scenario = SCENARIO
for raw in sys.stdin.buffer:
    row = json.loads(raw)
    if row['method'] == 'initialize':
        if scenario == 'timeout': time.sleep(10)
        if scenario == 'invalid-utf8':
            sys.stdout.buffer.write(b'\xff\n'); sys.stdout.buffer.flush(); continue
        if scenario == 'duplicate':
            print('{"id":1,"id":1,"result":{}}', flush=True); continue
        if scenario == 'large':
            print('x' * 262145, flush=True); continue
        if scenario == 'eof': sys.exit(0)
        if scenario == 'server-request':
            print(json.dumps(dict(id=99, method='item/tool/requestUserInput', params={})), flush=True)
        if scenario == 'notices':
            for _ in range(33): print('{"method":"notice"}', flush=True)
        identity = True if scenario == 'bool-id' else 1
        print(json.dumps(dict(id=identity, result=dict(userAgent='codex-cli 0.153.0', platformOs='windows'))), flush=True)
    elif row['method'] == 'account/read':
        if scenario == 'leader-exit':
            import subprocess
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with open(DESCENDANT_PATH, 'w') as handle: handle.write(str(child.pid))
        entry = None if scenario == 'login' else dict(type='chatgpt', email='PRIVATE@example.org', access_token='PRIVATE-TOKEN')
        result = dict(account=entry, requiresOpenaiAuth=True)
        if scenario == 'invalid-account': result['requiresOpenaiAuth'] = 'yes'
        print(json.dumps(dict(id=2, result=result)), flush=True)
        if scenario == 'leader-exit': sys.exit(0)
    elif row['method'] != 'initialized':
        sys.exit(99)
"""


class CodexProbeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.cwd = self.root / "cwd"
        self.cwd.mkdir()
        self.receipt = self.root / "receipt.jsonl"
        self.executable = Path(sys.executable).resolve()
        self.digest = hashlib.sha256(self.executable.read_bytes()).hexdigest()
        self.real_popen = subprocess.Popen

    def tearDown(self):
        self.temporary.cleanup()

    def execute(self, scenario="success", timeout=3):
        def launch(command, **options):
            if command != [str(self.executable), "app-server", "--stdio"]:
                return self.real_popen(command, **options)
            self.assertEqual(command, [str(self.executable), "app-server", "--stdio"])
            before = json.loads(self.receipt.read_text().splitlines()[0])
            self.assertEqual(before["event"], "launch-intent")
            self.assertEqual(before["executable_sha256"], self.digest)
            return self.real_popen(
                [
                    str(self.executable),
                    "-u",
                    "-c",
                    CHILD.replace("SCENARIO", repr(scenario)).replace(
                        "DESCENDANT_PATH", repr(str(self.root / "descendant.pid"))
                    ),
                ],
                **options,
            )

        with patch.object(probe.subprocess, "Popen", side_effect=launch):
            return probe.run_probe(
                self.executable, self.digest, self.cwd, self.receipt, timeout
            )

    def test_fixed_protocol_sanitized_receipt_precedes_process(self):
        result = self.execute()
        self.assertEqual(result["status"], "check-passed")
        self.assertEqual(result["account_type"], "chatgpt")
        self.assertEqual(result["server_version"], "0.153.0")
        self.assertFalse(result["model_turn_tested"])
        self.assertFalse(result["research_session_started"])
        self.assertTrue(result["cleanup"]["leader_reaped"])
        raw = self.receipt.read_text()
        self.assertNotIn("PRIVATE", raw + json.dumps(result))
        rows = [json.loads(row) for row in raw.splitlines()]
        methods = [row["method"] for row in rows if row["event"] == "rpc-intent"]
        self.assertEqual(methods, ["initialize", "initialized", "account/read"])
        self.assertEqual(rows[-1]["event"], "probe-completed")
        self.assertEqual(
            [row["sequence"] for row in rows], list(range(1, len(rows) + 1))
        )

    def test_missing_account_is_login_needed(self):
        self.assertEqual(self.execute("login")["status"], "needs-login")

    def test_timeout_is_bounded_and_cleanup_is_saved(self):
        start = time.monotonic()
        result = self.execute("timeout", timeout=0.1)
        self.assertLess(time.monotonic() - start, 6)
        self.assertEqual(result["status"], "check-failed")
        self.assertTrue(result["cleanup"]["leader_reaped"])
        self.assertEqual(
            json.loads(self.receipt.read_text().splitlines()[-1])["status"],
            "check-failed",
        )

    def test_malformed_bound_and_unsolicited_request_fail_closed(self):
        for scenario in (
            "invalid-utf8",
            "duplicate",
            "large",
            "eof",
            "server-request",
            "notices",
            "bool-id",
            "invalid-account",
        ):
            with self.subTest(scenario=scenario):
                self.receipt = self.root / (scenario + ".jsonl")
                result = self.execute(scenario)
                self.assertEqual(result["status"], "check-failed")
                self.assertTrue(result["cleanup"]["leader_reaped"])
                self.assertNotIn("PRIVATE", self.receipt.read_text())

    def test_preflight_hash_empty_directory_and_deadline_reject_without_spawn(self):
        cases = (
            ("0" * 64, 3),
            (self.digest, True),
            (self.digest, float("nan")),
            (self.digest, 31),
        )
        with patch.object(probe.subprocess, "Popen") as launch:
            for digest, timeout in cases:
                with self.assertRaises(probe.ProbeError):
                    probe.run_probe(
                        self.executable, digest, self.cwd, self.receipt, timeout
                    )
            (self.cwd / "source.txt").write_text("existing source")
            with self.assertRaises(probe.ProbeError):
                probe.run_probe(self.executable, self.digest, self.cwd, self.receipt)
            launch.assert_not_called()
        self.assertFalse(self.receipt.exists())

    def test_exclusive_receipt_cannot_overwrite_prior_attempt(self):
        self.receipt.write_text("prior attempt")
        with patch.object(probe.subprocess, "Popen") as launch:
            with self.assertRaises(FileExistsError):
                probe.run_probe(self.executable, self.digest, self.cwd, self.receipt)
            launch.assert_not_called()
        self.assertEqual(self.receipt.read_text(), "prior attempt")

    def test_launch_failure_retains_final_attempt_without_sensitive_exception(self):
        with patch.object(
            probe.subprocess, "Popen", side_effect=OSError("PRIVATE-TOKEN")
        ):
            result = probe.run_probe(
                self.executable, self.digest, self.cwd, self.receipt
            )
        self.assertEqual(result["status"], "check-failed")
        self.assertEqual(result["failure_type"], "OSError")
        self.assertNotIn("PRIVATE", self.receipt.read_text())
        self.assertTrue(result["cleanup"]["not_started"])

    def test_receipt_failure_blocks_launch(self):
        with patch.object(probe._Receipt, "append", side_effect=OSError("disk full")):
            with patch.object(probe.subprocess, "Popen") as launch:
                with self.assertRaises(OSError):
                    probe.run_probe(
                        self.executable, self.digest, self.cwd, self.receipt
                    )
                launch.assert_not_called()

    def test_blocked_write_deadline_cannot_dispatch_late_suffix(self):
        release, entered = threading.Event(), threading.Event()
        expired, completed = threading.Event(), threading.Event()
        queue_type = probe.queue.Queue

        class CompletionQueue(queue_type):
            def get(self, *args, **kwargs):
                # Real scheduler delay is fixture setup, not the logical budget.
                if not entered.wait(2):
                    raise AssertionError("fixture writer did not enter")
                if not expired.wait(2):
                    raise AssertionError("fixture deadline did not expire")
                raise probe.queue.Empty

            def put(self, value, *args, **kwargs):
                super().put(value, *args, **kwargs)
                completed.set()

        def clock():
            return 11.0 if expired.is_set() else 10.0

        class BlockedPipe:
            calls = 0

            def write(self, raw):
                self.calls += 1
                entered.set()
                expired.set()
                if not release.wait(2):
                    raise TimeoutError("fixture release missing")
                return 1

        class Process:
            stdin = BlockedPipe()
            stdout = io.BytesIO()

        receipt = probe._Receipt(self.receipt)
        exchange = probe._Exchange(Process(), receipt, 10.05)
        # Setup and receipt fsync cannot expire this controlled first-write case.
        # The same 50 ms budget expires only after the first write has entered.
        with (
            patch.object(probe.time, "monotonic", side_effect=clock),
            patch.object(probe.queue, "Queue", CompletionQueue),
        ):
            try:
                with self.assertRaises((probe.queue.Empty, TimeoutError)):
                    exchange.send(dict(method="initialized"))
                self.assertTrue(entered.is_set())
                self.assertTrue(expired.is_set())
                self.assertFalse(completed.is_set())
            finally:
                release.set()
                finished = completed.wait(2)
                receipt.stream.close()
        self.assertTrue(finished, "writer must finish before fixture teardown")
        self.assertEqual(Process.stdin.calls, 1)
        self.assertNotIn("rpc-write-observed", self.receipt.read_text())

    def test_expired_before_first_write_has_zero_calls(self):
        completed = threading.Event()
        queue_type = probe.queue.Queue

        class CompletionQueue(queue_type):
            def put(self, value, *args, **kwargs):
                super().put(value, *args, **kwargs)
                completed.set()

        class NeverPipe:
            calls = 0

            def write(self, raw):
                self.calls += 1
                return len(raw)

        class Process:
            stdin = NeverPipe()
            stdout = io.BytesIO()

        receipt = probe._Receipt(self.receipt)
        exchange = probe._Exchange(Process(), receipt, 9.95)
        with (
            patch.object(probe.time, "monotonic", return_value=10.0),
            patch.object(probe.queue, "Queue", CompletionQueue),
        ):
            try:
                with self.assertRaises(TimeoutError):
                    exchange.send(dict(method="initialized"))
            finally:
                finished = completed.wait(2)
                receipt.stream.close()
        self.assertTrue(finished, "rejected writer must finish before teardown")
        self.assertEqual(Process.stdin.calls, 0)
        self.assertNotIn("rpc-write-observed", self.receipt.read_text())

    def test_exited_leader_cannot_certify_descendant_cleanup(self):
        cleanup = probe._cleanup
        pid_path = self.root / "descendant.pid"

        def after_exit(process):
            process.wait(timeout=2)
            return cleanup(process)

        try:
            with patch.object(probe, "_cleanup", side_effect=after_exit):
                result = self.execute("leader-exit")
            self.assertEqual(result["status"], "check-failed")
            self.assertEqual(result["failure_type"], "CleanupIncomplete")
            self.assertTrue(result["cleanup"]["leader_reaped"])
            self.assertEqual(
                result["cleanup"]["tree_cleanup"], "unverified-leader-exited"
            )
            self.assertFalse(result["cleanup"]["process_tree_containment_verified"])
            self.assertEqual(
                json.loads(self.receipt.read_text().splitlines()[-1])["status"],
                "check-failed",
            )
        finally:
            if pid_path.exists():
                pid = int(pid_path.read_text())
                if os.name == "nt":
                    result = subprocess.run(
                        [
                            str(
                                Path(os.environ["SystemRoot"])
                                / "System32"
                                / "taskkill.exe"
                            ),
                            "/PID",
                            str(pid),
                            "/T",
                            "/F",
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=3,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    self.assertEqual(result.returncode, 0)
                else:
                    os.kill(pid, signal.SIGKILL)


if __name__ == "__main__":
    unittest.main()
