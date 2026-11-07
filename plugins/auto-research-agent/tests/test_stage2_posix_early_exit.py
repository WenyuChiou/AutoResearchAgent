"""Initial ESRCH needs this Popen's terminal state, never guessed ownership."""

from contextlib import ExitStack
import errno
import io
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from stage2_live import native_process  # noqa: E402


class ObservedProcess:
    def __init__(self, *, polled=7, effects=(7,)):
        self.pid = 4312
        self.returncode = None
        self.poll = Mock(side_effect=self._poll)
        self.polled = polled
        self.effects = iter(effects)
        self.communicate_calls = []
        self.kill = Mock(side_effect=AssertionError("unconfirmed leader"))
        self.stdout = io.BytesIO()
        self.stderr = io.BytesIO()

    def _poll(self):
        self.returncode = self.polled
        return self.polled

    def communicate(self, **kwargs):
        self.communicate_calls.append(kwargs)
        effect = next(self.effects)
        if isinstance(effect, BaseException):
            raise effect
        self.stdout.write(b"synthetic\x00\r\n\xe4\xb8\xad")
        self.stderr.write(b"synthetic-stderr")
        self.returncode = effect


class PosixEarlyExitTests(unittest.TestCase):
    def arrange(self, process, lookup, *, ticks=(100, 100.25, 101.5)):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(native_process, "_IS_WINDOWS", False))
        popen = stack.enter_context(
            patch.object(native_process.subprocess, "Popen", return_value=process)
        )
        getpgid = stack.enter_context(
            patch.object(native_process, "_getpgid", side_effect=lookup)
        )
        killpg = stack.enter_context(patch.object(native_process, "_killpg"))
        stack.enter_context(
            patch.object(native_process.time, "monotonic", side_effect=ticks)
        )
        return popen, getpgid, killpg

    def invoke(self, process):
        return native_process.run_bound_process(
            ["synthetic-native", "exec"],
            input=b"synthetic\x00prompt",
            cwd="synthetic-workspace",
            env={"SYNTHETIC_ONLY": "1"},
            stdout=process.stdout,
            stderr=process.stderr,
            timeout_seconds=5,
        )

    def assert_unconfirmed(self, process, killpg, error):
        killpg.assert_not_called()
        process.kill.assert_not_called()
        report = error.cleanup_report
        self.assertFalse(report["ownership_confirmed_at_spawn"])
        self.assertFalse(report["ownership_confirmed"])
        self.assertEqual(
            report["tree_kill_status"], "not-attempted-unconfirmed-ownership"
        )
        self.assertNotIn("residual_count", report)
        self.assertNotIn("tree_residual_count", report)

    def test_terminal_esrch_collects_exact_output_with_original_deadline(self):
        process = ObservedProcess()
        popen, getpgid, killpg = self.arrange(
            process, ProcessLookupError(errno.ESRCH, "synthetic exited")
        )
        self.assertEqual(self.invoke(process), 7)
        process.poll.assert_called_once_with()
        getpgid.assert_called_once_with(4312)
        killpg.assert_not_called()
        process.kill.assert_not_called()
        self.assertEqual(process.communicate_calls, [{"timeout": 3.5}])
        self.assertEqual(process.stdout.getvalue(), b"synthetic\x00\r\n\xe4\xb8\xad")
        self.assertEqual(process.stderr.getvalue(), b"synthetic-stderr")
        self.assertFalse(process.stdout.closed)
        self.assertFalse(process.stderr.closed)
        popen.assert_called_once()
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertTrue(popen.call_args.kwargs["stdin"].closed)

    def test_live_esrch_preserves_original_failure_without_signals(self):
        failure = ProcessLookupError(errno.ESRCH, "synthetic still live")
        process = ObservedProcess(polled=None)
        _, _, killpg = self.arrange(process, failure)
        with self.assertRaises(ProcessLookupError) as raised:
            self.invoke(process)
        self.assertIs(raised.exception, failure)
        process.poll.assert_called_once_with()
        self.assert_unconfirmed(process, killpg, failure)

    def test_other_lookup_errors_are_not_terminal_evidence(self):
        for failure in (
            PermissionError(errno.EPERM, "synthetic"),
            OSError(errno.EIO, "synthetic"),
        ):
            with self.subTest(error=type(failure).__name__):
                process = ObservedProcess()
                _, _, killpg = self.arrange(process, failure)
                with self.assertRaises(type(failure)) as raised:
                    self.invoke(process)
                self.assertIs(raised.exception, failure)
                process.poll.assert_not_called()
                self.assert_unconfirmed(process, killpg, failure)

    def test_process_lookup_error_requires_exact_esrch(self):
        failure = ProcessLookupError(errno.EINVAL, "synthetic non-ESRCH")
        process = ObservedProcess()
        _, _, killpg = self.arrange(process, failure)
        with self.assertRaises(ProcessLookupError) as raised:
            self.invoke(process)
        self.assertIs(raised.exception, failure)
        process.poll.assert_not_called()
        self.assert_unconfirmed(process, killpg, failure)

    def test_wrong_group_still_rejects_without_poll_or_signals(self):
        process = ObservedProcess()
        _, _, killpg = self.arrange(process, lambda pid: 9000)
        with self.assertRaisesRegex(RuntimeError, "owned process group") as raised:
            self.invoke(process)
        process.poll.assert_not_called()
        self.assert_unconfirmed(process, killpg, raised.exception)

    def test_pid_change_during_successful_lookup_is_not_owned(self):
        process = ObservedProcess()

        def lookup(pid):
            self.assertEqual(pid, 4312)
            process.pid = 9000
            return 9000

        _, _, killpg = self.arrange(process, lookup)
        with self.assertRaisesRegex(RuntimeError, "owned process group") as raised:
            self.invoke(process)
        process.poll.assert_not_called()
        self.assert_unconfirmed(process, killpg, raised.exception)

    def test_pid_change_before_poll_preserves_esrch_without_polling(self):
        process = ObservedProcess()
        failure = ProcessLookupError(errno.ESRCH, "synthetic changed pid")

        def lookup(pid):
            process.pid = 9000
            raise failure

        _, _, killpg = self.arrange(process, lookup)
        with self.assertRaises(ProcessLookupError) as raised:
            self.invoke(process)
        self.assertIs(raised.exception, failure)
        process.poll.assert_not_called()
        self.assert_unconfirmed(process, killpg, failure)

    def test_pid_change_during_poll_preserves_esrch_without_signals(self):
        process = ObservedProcess()
        failure = ProcessLookupError(errno.ESRCH, "synthetic changed pid")

        def poll():
            process.pid = 9000
            process.returncode = 7
            return 7

        process.poll.side_effect = poll
        _, _, killpg = self.arrange(process, failure)
        with self.assertRaises(ProcessLookupError) as raised:
            self.invoke(process)
        self.assertIs(raised.exception, failure)
        process.poll.assert_called_once_with()
        self.assert_unconfirmed(process, killpg, failure)

    def test_poll_error_is_preserved_without_assuming_ownership(self):
        process = ObservedProcess()
        failure = PermissionError(errno.EPERM, "synthetic poll denied")
        process.poll.side_effect = failure
        _, _, killpg = self.arrange(
            process, ProcessLookupError(errno.ESRCH, "synthetic exited")
        )
        with self.assertRaises(PermissionError) as raised:
            self.invoke(process)
        self.assertIs(raised.exception, failure)
        self.assert_unconfirmed(process, killpg, failure)

    def test_terminal_esrch_cannot_renew_expired_deadline(self):
        process = ObservedProcess()
        _, _, killpg = self.arrange(
            process,
            ProcessLookupError(errno.ESRCH, "synthetic exited"),
            ticks=(100, 100.25, 106),
        )
        with self.assertRaises(subprocess.TimeoutExpired) as raised:
            self.invoke(process)
        self.assertEqual(raised.exception.timeout, 5)
        self.assertEqual(process.communicate_calls, [{"timeout": 5}])  # cleanup only
        process.poll.assert_called_once_with()
        self.assert_unconfirmed(process, killpg, raised.exception)

    def test_terminal_collection_errors_preserve_partial_output_and_refusal(self):
        for failure in (
            subprocess.TimeoutExpired("synthetic-native", 3.5),
            OSError(errno.EIO, "synthetic collection error"),
        ):
            with self.subTest(error=type(failure).__name__):
                process = ObservedProcess(effects=(failure, 7))
                process.stdout.write(b"partial-output")
                _, _, killpg = self.arrange(
                    process, ProcessLookupError(errno.ESRCH, "synthetic exited")
                )
                with self.assertRaises(type(failure)) as raised:
                    self.invoke(process)
                self.assertIs(raised.exception, failure)
                self.assertTrue(process.stdout.getvalue().startswith(b"partial-output"))
                self.assertEqual(
                    process.communicate_calls, [{"timeout": 3.5}, {"timeout": 5}]
                )
                self.assert_unconfirmed(process, killpg, failure)


if __name__ == "__main__":
    unittest.main()
