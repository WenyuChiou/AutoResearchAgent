"""Observe the actual shared transport request before any child can start."""

from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


CLI = Path(__file__).resolve().parents[1] / "cli"
PRELUDE = """
import io
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import Mock, patch

sys.path.insert(0, sys.argv[1])
from stage2_live import native_process

EVENT = "autoresearch.bound_submission"
executable = getattr(sys, "_base_executable", None) or sys.executable
"""


class BoundSubmissionTests(unittest.TestCase):
    def isolated(self, source):
        # Audit hooks cannot be removed. Each case gets its own interpreter so
        # neither observing nor rejecting hooks affect other plugin tests.
        result = subprocess.run(
            [
                getattr(sys, "_base_executable", None) or sys.executable,
                "-X",
                "utf8",
                "-c",
                PRELUDE + textwrap.dedent(source),
                str(CLI),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_no_hook_preserves_real_python_echo_and_returncode(self):
        self.isolated(
            """
            for timeout in (None, 5):
                for payload in (None, "中文 prompt ' spaced\\x00\\r\\n".encode()):
                    with tempfile.TemporaryFile() as captured:
                        result = native_process.run_bound_process(
                            [executable, "-c", "import sys; "
                             "sys.stdout.buffer.write(sys.stdin.buffer.read()); "
                             "sys.exit(7)"],
                            input=payload, env=None, cwd=None, stdout=captured,
                            stderr=subprocess.DEVNULL, timeout_seconds=timeout,
                        )
                        captured.seek(0)
                        assert (result, captured.read()) == (7, payload or b"")
            """
        )

    def test_real_transport_emits_exact_five_fields_once_before_popen(self):
        self.isolated(
            """
            events = []
            expected = None
            def observe(event, args):
                if event == EVENT:
                    assert len(args) == 5
                    assert all(actual is original
                               for actual, original in zip(args, expected))
                    events.append("bound")
                elif event == "subprocess.Popen":
                    assert events[-1:] == ["bound"]
                    events.append("popen")
            sys.addaudithook(observe)
            with tempfile.TemporaryDirectory(prefix="space ' 中文 ") as root:
                cwd = Path(root).resolve()
                env = {"BOUND_TEST": "中文 ' value", "PYTHONUTF8": "1",
                       "SYSTEMROOT": "C:/Windows"}
                command = [executable, "-c", "import os,sys; "
                           "assert os.environ['BOUND_TEST'] == sys.argv[1]; "
                           "assert os.getcwd() == sys.argv[2]; "
                           "sys.stdout.buffer.write(sys.stdin.buffer.read())",
                           env["BOUND_TEST"], str(cwd)]
                for timeout in (None, 5.0):
                    payload = "中文 ' prompt\\x00\\r\\n".encode()
                    expected = (command, payload, cwd, env, timeout)
                    with tempfile.TemporaryFile() as captured:
                        result = native_process.run_bound_process(
                            command, input=payload, env=env, cwd=cwd,
                            stdout=captured, stderr=subprocess.DEVNULL,
                            timeout_seconds=timeout,
                        )
                        captured.seek(0)
                        assert (result, captured.read()) == (0, payload)
            assert events == ["bound", "popen", "bound", "popen"], events
            """
        )

    def test_hook_preserves_none_and_existing_argument_types_and_identity(self):
        self.isolated(
            """
            class Commands(list):
                pass
            class Environment(dict):
                pass
            class Seconds(int):
                pass
            class FractionalSeconds(float):
                pass
            seen = []
            expected = None
            def observe(event, args):
                if event == EVENT:
                    assert len(args) == 5
                    assert all(actual is original
                               for actual, original in zip(args, expected))
                    seen.append(args)
            sys.addaudithook(observe)
            cases = [
                (["python", "echo"], b"bytes", "space ' 中文", {}, None),
                (("python", "echo"), None, None, None, None),
                (Commands([Path(executable)]), bytearray(b"mutable"),
                 Path("space ' 中文"), Environment(SAFE="1"), Seconds(5)),
                ((Path(executable),), memoryview(b"view"), None, None,
                 FractionalSeconds(5.5)),
            ]
            for expected in cases:
                command, payload, cwd, env, timeout = expected
                process = Mock(pid=4312, returncode=17)
                def spawn(actual_command, **options):
                    assert seen[-1] == expected
                    assert actual_command is command
                    assert options["cwd"] is cwd and options["env"] is env
                    if timeout is not None:
                        assert options["stdin"].read() == bytes(payload)
                    return process
                with patch.object(native_process.subprocess, "Popen",
                                  side_effect=spawn) as popen, \
                     patch.object(native_process, "_getpgid", return_value=4312):
                    result = native_process.run_bound_process(
                        command, input=payload, cwd=cwd, env=env,
                        stdout=None, stderr=None, timeout_seconds=timeout,
                    )
                    assert result == 17 and popen.call_count == 1
                    if timeout is None:
                        assert process.communicate.call_args.kwargs["input"] is payload
                    else:
                        assert 0 < process.communicate.call_args.kwargs["timeout"] <= timeout
            assert len(seen) == len(cases)
            """
        )

    def test_invalid_timeout_rejects_before_event_or_transport_setup(self):
        self.isolated(
            """
            seen = []
            sys.addaudithook(lambda event, args: seen.append(args)
                            if event == EVENT else None)
            invalid = (True, False, 0, -1, math.inf, -math.inf, math.nan,
                       10**1000, "1")
            with patch.object(native_process.subprocess, "Popen") as popen, \
                 patch.object(native_process.tempfile, "TemporaryFile") as temporary:
                for timeout in invalid:
                    try:
                        native_process.run_bound_process(
                            ["unused"], input=b"prompt", env=None, cwd=None,
                            stdout=None, stderr=None, timeout_seconds=timeout,
                        )
                    except ValueError as error:
                        assert "finite positive" in str(error)
                    else:
                        raise AssertionError("invalid timeout accepted")
                assert seen == [] and popen.call_count == temporary.call_count == 0
            """
        )

    def test_observer_exception_propagates_with_zero_popen_or_prompt_files(self):
        self.isolated(
            """
            seen = []
            failure = RuntimeError("trusted observer denied submission")
            def reject(event, args):
                if event == EVENT:
                    seen.append(args)
                    raise failure
            sys.addaudithook(reject)
            with patch.object(native_process.subprocess, "Popen") as popen, \
                 patch.object(native_process.tempfile, "TemporaryFile") as temporary:
                for timeout in (None, 5):
                    output = io.BytesIO()
                    try:
                        native_process.run_bound_process(
                            ["unused"], input=b"prompt", env=None, cwd=None,
                            stdout=output, stderr=output, timeout_seconds=timeout,
                        )
                    except RuntimeError as error:
                        assert error is failure
                        assert not hasattr(error, "cleanup_report")
                    else:
                        raise AssertionError("observer denial ignored")
                    assert not output.closed and output.getvalue() == b""
                assert len(seen) == 2
                assert popen.call_count == temporary.call_count == 0
            """
        )


if __name__ == "__main__":
    unittest.main()
