"""Owned process deadlines clean one target tree and preserve original failures."""

import io
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from stage2_live import native_process  # noqa: E402


class FakeProcess:
    def __init__(self, effects, *, pid=4312, returncode=None, polled=None):
        self.pid = pid
        self.returncode = returncode
        self._effects = iter(effects)
        self.communicate_calls = []
        self.kill_calls = 0
        self.polled = polled

    def communicate(self, **kwargs):
        self.communicate_calls.append(kwargs)
        effect = next(self._effects)
        if isinstance(effect, BaseException):
            raise effect
        self.returncode = effect
        return (None, None)

    def kill(self):
        self.kill_calls += 1

    def poll(self):
        return self.polled


class TrackingTemporaryFile(io.BytesIO):
    saved_bytes = None

    def close(self):
        if not self.closed:
            self.saved_bytes = self.getvalue()
        super().close()


def invoke(*, timeout_seconds=None, stdout=None, stderr=None):
    return native_process.run_bound_process(
        ["native", "exec"],
        input=b"prompt",
        env={"SAFE": "1"},
        cwd="workspace",
        stdout=stdout,
        stderr=stderr,
        timeout_seconds=timeout_seconds,
    )


class NativeProcessTests(unittest.TestCase):
    def setUp(self):
        # POSIX Python does not export this Windows-only constant. The Windows
        # branch uses mocked processes on every CI platform, not real taskkill.
        flag = patch.object(subprocess, "CREATE_NEW_PROCESS_GROUP", 512, create=True)
        flag.start()
        self.addCleanup(flag.stop)

    def test_timeout_validation_happens_before_spawn(self):
        for value in (
            True,
            False,
            0,
            -1,
            math.inf,
            -math.inf,
            math.nan,
            10**1000,
            "1",
        ):
            with (
                self.subTest(value=value),
                patch.object(
                    native_process.subprocess,
                    "Popen",
                    side_effect=AssertionError("must validate before spawn"),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "finite positive"):
                    invoke(timeout_seconds=value)
        self.assertIsNone(native_process.validate_timeout_seconds(None))
        self.assertEqual(native_process.validate_timeout_seconds(7), 7)
        self.assertEqual(native_process.validate_timeout_seconds(2.5), 2.5)

    def test_bounded_prompt_setup_uses_deadline_and_closes_file_before_spawn(self):
        prompt_file = TrackingTemporaryFile()
        with (
            patch.object(
                native_process.tempfile, "TemporaryFile", return_value=prompt_file
            ),
            patch.object(native_process.time, "monotonic", side_effect=[10, 12]),
            patch.object(
                native_process.subprocess,
                "Popen",
                side_effect=AssertionError("expired setup must not spawn"),
            ),
        ):
            with self.assertRaises(subprocess.TimeoutExpired):
                invoke(timeout_seconds=1)
        self.assertTrue(prompt_file.closed)
        self.assertEqual(prompt_file.saved_bytes, b"prompt")

    def test_bounded_prompt_file_closes_when_spawn_fails(self):
        prompt_file = TrackingTemporaryFile()
        failure = OSError("spawn failed")
        with (
            patch.object(
                native_process.tempfile, "TemporaryFile", return_value=prompt_file
            ),
            patch.object(native_process.subprocess, "Popen", side_effect=failure),
        ):
            with self.assertRaises(OSError) as raised:
                invoke(timeout_seconds=5)
        self.assertIs(raised.exception, failure)
        self.assertTrue(prompt_file.closed)
        self.assertEqual(prompt_file.saved_bytes, b"prompt")

    def test_normal_and_legacy_calls_use_one_popen(self):
        for timeout, expected_call in (
            (None, call(input=b"prompt")),
            (12, call(timeout=12)),
        ):
            with self.subTest(timeout=timeout):
                process = FakeProcess([0], returncode=0)
                with (
                    patch.object(native_process, "_IS_WINDOWS", False),
                    patch.object(
                        native_process.subprocess, "Popen", return_value=process
                    ) as popen,
                    patch.object(
                        native_process, "_getpgid", return_value=4312
                    ) as getpgid,
                    patch.object(
                        native_process.time,
                        "monotonic",
                        side_effect=[100, 100, 100],
                    ),
                ):
                    self.assertEqual(invoke(timeout_seconds=timeout), 0)
                popen.assert_called_once()
                self.assertEqual(process.communicate_calls, [expected_call.kwargs])
                if timeout is None:
                    getpgid.assert_not_called()
                    self.assertNotIn("start_new_session", popen.call_args.kwargs)
                    self.assertNotIn("creationflags", popen.call_args.kwargs)
                else:
                    self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_posix_timeout_kills_confirmed_group_after_leader_exit(self):
        timeout = subprocess.TimeoutExpired(["native", "exec"], 10)
        process = FakeProcess([timeout, -9], returncode=None, polled=3)
        stdout, stderr = io.BytesIO(b"partial-out"), io.BytesIO(b"partial-err")
        prompt_file = TrackingTemporaryFile()
        with (
            patch.object(native_process, "_IS_WINDOWS", False),
            patch.object(native_process.subprocess, "Popen", return_value=process),
            patch.object(native_process, "_getpgid", return_value=4312),
            patch.object(native_process, "_killpg") as killpg,
            patch.object(
                native_process.tempfile, "TemporaryFile", return_value=prompt_file
            ),
        ):
            with self.assertRaises(subprocess.TimeoutExpired) as raised:
                invoke(timeout_seconds=10, stdout=stdout, stderr=stderr)
        self.assertIs(raised.exception, timeout)
        killpg.assert_called_once_with(4312, native_process._SIGKILL)
        self.assertEqual(raised.exception.cleanup_report["reap_status"], "complete")
        self.assertEqual(raised.exception.cleanup_report["returncode"], -9)
        self.assertFalse(stdout.closed)
        self.assertFalse(stderr.closed)
        self.assertEqual(stdout.getvalue(), b"partial-out")
        self.assertEqual(stderr.getvalue(), b"partial-err")
        self.assertTrue(prompt_file.closed)
        self.assertEqual(prompt_file.saved_bytes, b"prompt")

    def test_legacy_exception_cleans_leader_without_group_claim(self):
        failure = RuntimeError("communicate failed")
        process = FakeProcess([failure, -9])
        with (
            patch.object(native_process, "_IS_WINDOWS", False),
            patch.object(native_process.subprocess, "Popen", return_value=process),
            patch.object(native_process, "_getpgid") as getpgid,
            patch.object(native_process, "_killpg") as killpg,
        ):
            with self.assertRaises(RuntimeError) as raised:
                invoke()
        self.assertIs(raised.exception, failure)
        getpgid.assert_not_called()
        killpg.assert_not_called()
        self.assertEqual(process.kill_calls, 1)
        self.assertFalse(raised.exception.cleanup_report["ownership_confirmed"])

    def test_posix_cleanup_failure_preserves_original_exception(self):
        timeout = subprocess.TimeoutExpired("native", 4)
        process = FakeProcess([timeout, -9])
        with (
            patch.object(native_process, "_IS_WINDOWS", False),
            patch.object(native_process.subprocess, "Popen", return_value=process),
            patch.object(native_process, "_getpgid", return_value=4312),
            patch.object(native_process, "_killpg", side_effect=OSError("denied")),
        ):
            with self.assertRaises(subprocess.TimeoutExpired) as raised:
                invoke(timeout_seconds=4)
        self.assertIs(raised.exception, timeout)
        report = raised.exception.cleanup_report
        self.assertEqual(report["tree_kill_status"], "error")
        self.assertIn("killpg-error: OSError: denied", report["errors"])

    def test_unconfirmed_posix_group_never_receives_group_signal(self):
        process = FakeProcess([RuntimeError("unused"), -9])
        with (
            patch.object(native_process, "_IS_WINDOWS", False),
            patch.object(native_process.subprocess, "Popen", return_value=process),
            patch.object(native_process, "_getpgid", return_value=9000),
            patch.object(native_process, "_killpg") as killpg,
        ):
            with self.assertRaisesRegex(RuntimeError, "owned process group") as raised:
                invoke(timeout_seconds=4)
        killpg.assert_not_called()
        self.assertEqual(process.kill_calls, 0)
        self.assertFalse(raised.exception.cleanup_report["ownership_confirmed"])

    def test_changed_posix_group_identity_is_not_signaled(self):
        timeout = subprocess.TimeoutExpired("native", 4)
        process = FakeProcess([timeout, -9])
        with (
            patch.object(native_process, "_IS_WINDOWS", False),
            patch.object(native_process.subprocess, "Popen", return_value=process),
            patch.object(native_process, "_getpgid", side_effect=[4312, 9000]),
            patch.object(native_process, "_killpg") as killpg,
        ):
            with self.assertRaises(subprocess.TimeoutExpired) as raised:
                invoke(timeout_seconds=4)
        killpg.assert_not_called()
        self.assertEqual(process.kill_calls, 0)
        report = raised.exception.cleanup_report
        self.assertFalse(report["ownership_confirmed"])
        self.assertIn("cleanup-identity-mismatch", report["errors"][0])

    def test_reaped_posix_leader_does_not_target_former_group(self):
        timeout = subprocess.TimeoutExpired("native", 4)
        process = FakeProcess([timeout, 3], returncode=3)
        with (
            patch.object(native_process, "_IS_WINDOWS", False),
            patch.object(native_process.subprocess, "Popen", return_value=process),
            patch.object(native_process, "_getpgid", return_value=4312) as getpgid,
            patch.object(native_process, "_killpg") as killpg,
        ):
            with self.assertRaises(subprocess.TimeoutExpired) as raised:
                invoke(timeout_seconds=4)
        self.assertEqual(getpgid.call_count, 1)
        killpg.assert_not_called()
        self.assertTrue(
            any(
                "leader-already-reaped" in error
                for error in raised.exception.cleanup_report["errors"]
            )
        )

    def test_windows_timeout_targets_only_spawned_pid_tree(self):
        timeout = subprocess.TimeoutExpired("native", 8)
        process = FakeProcess([timeout, 1], returncode=1)
        result = Mock(returncode=0, stdout="terminated\n", stderr="")
        with (
            patch.object(native_process, "_IS_WINDOWS", True),
            patch.object(
                native_process.subprocess, "Popen", return_value=process
            ) as popen,
            patch.object(
                native_process.subprocess, "run", return_value=result
            ) as taskkill,
        ):
            with self.assertRaises(subprocess.TimeoutExpired) as raised:
                invoke(timeout_seconds=8)
        self.assertIs(raised.exception, timeout)
        self.assertEqual(popen.call_count, 1)
        self.assertEqual(
            popen.call_args.kwargs["creationflags"],
            subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        taskkill.assert_called_once_with(
            ["taskkill", "/PID", "4312", "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
            timeout=native_process._CLEANUP_TIMEOUT_SECONDS,
        )
        self.assertEqual(raised.exception.cleanup_report["taskkill_returncode"], 0)

    def test_windows_cleanup_error_preserves_original_interrupt(self):
        interrupt = KeyboardInterrupt("operator interrupt")
        process = FakeProcess([interrupt, -9])
        with (
            patch.object(native_process, "_IS_WINDOWS", True),
            patch.object(native_process.subprocess, "Popen", return_value=process),
            patch.object(
                native_process.subprocess,
                "run",
                side_effect=OSError("taskkill missing"),
            ),
        ):
            with self.assertRaises(KeyboardInterrupt) as raised:
                invoke(timeout_seconds=8)
        self.assertIs(raised.exception, interrupt)
        self.assertEqual(raised.exception.cleanup_report["tree_kill_status"], "error")
        self.assertIn("taskkill-error", raised.exception.cleanup_report["errors"][0])

    def test_windows_taskkill_failure_records_returncode_and_stderr(self):
        timeout = subprocess.TimeoutExpired("native", 8)
        process = FakeProcess([timeout, -9])
        result = Mock(returncode=128, stdout="", stderr="process not found")
        with (
            patch.object(native_process, "_IS_WINDOWS", True),
            patch.object(native_process.subprocess, "Popen", return_value=process),
            patch.object(native_process.subprocess, "run", return_value=result),
        ):
            with self.assertRaises(subprocess.TimeoutExpired) as raised:
                invoke(timeout_seconds=8)
        report = raised.exception.cleanup_report
        self.assertEqual(report["taskkill_returncode"], 128)
        self.assertEqual(report["taskkill_stderr"], "process not found")
        self.assertIn("taskkill-returncode-128", report["errors"][0])

    def test_windows_known_exited_pid_is_not_passed_to_taskkill(self):
        timeout = subprocess.TimeoutExpired("native", 8)
        process = FakeProcess([timeout, 1], returncode=1, polled=1)
        with (
            patch.object(native_process, "_IS_WINDOWS", True),
            patch.object(native_process.subprocess, "Popen", return_value=process),
            patch.object(native_process.subprocess, "run") as taskkill,
        ):
            with self.assertRaises(subprocess.TimeoutExpired) as raised:
                invoke(timeout_seconds=8)
        taskkill.assert_not_called()
        report = raised.exception.cleanup_report
        self.assertFalse(report["ownership_confirmed"])
        self.assertEqual(
            report["tree_kill_status"], "not-attempted-unconfirmed-ownership"
        )

    def test_real_child_receives_exact_finite_timeout_input(self):
        executable = getattr(sys, "_base_executable", None) or sys.executable
        payload = b"exact\x00binary\r\ninput"
        with tempfile.TemporaryFile(mode="w+b") as captured:
            returncode = native_process.run_bound_process(
                [
                    executable,
                    "-c",
                    "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())",
                ],
                input=payload,
                env=os.environ.copy(),
                cwd=os.getcwd(),
                stdout=captured,
                stderr=subprocess.DEVNULL,
                timeout_seconds=5,
            )
            captured.seek(0)
            self.assertEqual(captured.read(), payload)
        self.assertEqual(returncode, 0)

    def test_real_nonreading_child_is_bounded_by_outer_owned_watchdog(self):
        executable = getattr(sys, "_base_executable", None) or sys.executable
        cli_path = str(Path(__file__).resolve().parents[1] / "cli")
        driver = """
import os
import subprocess
import sys

sys.path.insert(0, sys.argv[1])
from stage2_live.native_process import run_bound_process

child = [
    getattr(sys, "_base_executable", None) or sys.executable,
    "-c",
    "import threading; threading.Event().wait(30)",
]
try:
    run_bound_process(
        child,
        input=b"x" * (1024 * 1024),
        env=os.environ.copy(),
        cwd=os.getcwd(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout_seconds=2,
    )
except subprocess.TimeoutExpired as error:
    if not hasattr(error, "cleanup_report"):
        raise
else:
    raise AssertionError("non-reading child unexpectedly completed")
"""
        options = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True
        watchdog = subprocess.Popen(
            [executable, "-c", driver, cli_path],
            **options,
        )
        try:
            stdout, stderr = watchdog.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(watchdog.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                    timeout=5,
                )
            else:
                os.killpg(watchdog.pid, signal.SIGKILL)
            watchdog.communicate(timeout=5)
            self.fail("outer watchdog stopped a blocked finite-timeout input write")
        self.assertEqual(
            watchdog.returncode,
            0,
            (stdout + stderr).decode("utf-8", "replace"),
        )


if __name__ == "__main__":
    unittest.main()
