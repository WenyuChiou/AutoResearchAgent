# ruff: noqa: E402 -- repository CLIs are imported without installation.
"""Daily CLI policy bindings are explicit and retain external-file safeguards."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from stage2_live.__main__ import main as live_main
from stage2_live.assessment_target_policy import target_policy_binding


COMMANDS = ("daily-v3", "verify-daily-v3")
APIS = {
    "daily-v3": "stage2_live.daily_v3.run_daily_evaluation_v3",
    "verify-daily-v3": "stage2_live.daily_replay_v3.verify_daily_v3",
}


class DailyTargetCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.binding = target_policy_binding()
        self.files = {
            "selection": self.save(
                "selection.json", {"evaluation_packet": {}, "action_record": {}}
            ),
            "policy": self.save("policy.json", {"execution": "frozen"}),
            "receipt": self.save("receipt.json", {"result_sha256": "a" * 64}),
            "config": self.save("config.json", {"model": "test-model"}),
            "context": self.save("context.json", {"context": "frozen"}),
            "target": self.save("target.json", self.binding),
        }
        self.model_guards = []
        for target in (
            "stage1_eval.model_calls.call_model_v31",
            "stage2_live.daily_v3.call_model_v31",
            "stage2_live.daily_v3._run_unit",
        ):
            guard = patch(target, side_effect=AssertionError("unexpected model call"))
            self.model_guards.append(guard.start())
            self.addCleanup(guard.stop)

    def tearDown(self):
        for guard in self.model_guards:
            guard.assert_not_called()

    def save(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def args(self, command, *, target=None, suffix="", context=False):
        args = [
            command,
            "--selection",
            str(self.files["selection"]),
            "--source-root",
            str(self.root / "sources"),
            "--output",
            str(self.root / f"{command}-output{suffix}"),
        ]
        if command == "daily-v3":
            for key, value in {
                "codex": "synthetic-codex",
                "r1-home": self.root / "r1",
                "r2-home": self.root / "r2",
                "adj-home": self.root / "adj",
                "model": "test-model",
                "reasoning": "high",
                "policy": self.files["policy"],
                "replay-receipt-output": self.root / f"new-receipt{suffix}.json",
            }.items():
                args.extend(["--" + key, str(value)])
        else:
            for key, value in {
                "run-dir": self.root / "run",
                "receipt": self.files["receipt"],
                "config": self.files["config"],
            }.items():
                args.extend(["--" + key, str(value)])
        if context:
            args.extend(["--source-context-policy", str(self.files["context"])])
        if target is not None:
            args.extend(["--assessment-target-policy", str(target)])
        return args

    def invoke(self, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = live_main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def expected_call(self, command, *, context=False):
        if command == "daily-v3":
            return (
                (
                    {"evaluation_packet": {}, "action_record": {}},
                    str(self.root / "sources"),
                ),
                {
                    "codex": "synthetic-codex",
                    "r1_home": str(self.root / "r1"),
                    "r2_home": str(self.root / "r2"),
                    "adj_home": str(self.root / "adj"),
                    "model": "test-model",
                    "reasoning": "high",
                    "execution_policy": {"execution": "frozen"},
                    "output_dir": str(self.root / f"{command}-output"),
                    "resume": False,
                    "resume_receipt": None,
                    "audit": None,
                    "source_context_policy": {"context": "frozen"} if context else None,
                },
            )
        return (
            (str(self.root / "run"), {"result_sha256": "a" * 64}),
            {
                "selection": {"evaluation_packet": {}, "action_record": {}},
                "source_root": str(self.root / "sources"),
                "expected_config": {"model": "test-model"},
                "source_context_policy": {"context": "frozen"} if context else None,
            },
        )

    def test_omitted_flag_preserves_exact_legacy_api_calls(self):
        for command in COMMANDS:
            with (
                self.subTest(command=command),
                patch(
                    APIS[command],
                    return_value={
                        "status": "complete",
                        "replay_receipt": {"saved": True},
                    },
                ) as api,
            ):
                code, stdout, stderr = self.invoke(self.args(command))
                self.assertEqual((code, stderr), (0, ""))
                args, kwargs = self.expected_call(command)
                api.assert_called_once_with(*args, **kwargs)
                self.assertEqual(json.loads(stdout)["status"], "complete")

    def test_supplied_binding_is_forwarded_unchanged_with_context_policy(self):
        for command in COMMANDS:
            with (
                self.subTest(command=command),
                patch(
                    APIS[command],
                    return_value={
                        "status": "complete",
                        "replay_receipt": {"saved": True},
                    },
                ) as api,
            ):
                code, _, stderr = self.invoke(
                    self.args(command, target=self.files["target"], context=True)
                )
                self.assertEqual((code, stderr), (0, ""))
                args, kwargs = self.expected_call(command, context=True)
                api.assert_called_once_with(
                    *args, **kwargs, assessment_target_policy=self.binding
                )
                output = (
                    self.root / "new-receipt.json"
                    if command == "daily-v3"
                    else self.root / f"{command}-output"
                )
                if command == "daily-v3":
                    self.assertEqual(json.loads(output.read_bytes()), {"saved": True})
                else:
                    self.assertEqual(
                        json.loads(output.read_bytes())["status"], "complete"
                    )

    def test_resume_forwards_target_binding_and_external_receipt(self):
        with patch(
            APIS["daily-v3"],
            return_value={"status": "complete", "replay_receipt": {"saved": True}},
        ) as api:
            code, _, stderr = self.invoke(
                self.args("daily-v3", target=self.files["target"])
                + ["--resume", "--replay-receipt", str(self.files["receipt"])]
            )
        self.assertEqual((code, stderr), (0, ""))
        args, kwargs = self.expected_call("daily-v3")
        kwargs.update(resume=True, resume_receipt={"result_sha256": "a" * 64})
        api.assert_called_once_with(
            *args, **kwargs, assessment_target_policy=self.binding
        )

    def test_malformed_policy_files_fail_before_api_dispatch(self):
        for data in (
            b"{",
            b'{"schema_version":1,"schema_version":2}',
            b'{"x":NaN}',
            b"\xff",
        ):
            self.files["target"].write_bytes(data)
            for command in COMMANDS:
                with (
                    self.subTest(data=data, command=command),
                    patch(APIS[command]) as api,
                ):
                    code, stdout, stderr = self.invoke(
                        self.args(command, target=self.files["target"])
                    )
                    self.assertEqual((code, stdout), (2, ""))
                    self.assertEqual(json.loads(stderr)["status"], "failed")
                    api.assert_not_called()
                    self.assertFalse((self.root / "new-receipt.json").exists())
                    self.assertFalse((self.root / f"{command}-output").exists())

    def test_non_object_policy_fails_before_api_dispatch(self):
        for value in (None, [], "3.1.0", True, 3.1):
            self.save("target.json", value)
            for command in COMMANDS:
                with (
                    self.subTest(value=value, command=command),
                    patch(APIS[command]) as api,
                ):
                    code, stdout, stderr = self.invoke(
                        self.args(command, target=self.files["target"])
                    )
                    self.assertEqual((code, stdout), (2, ""))
                    self.assertEqual(
                        json.loads(stderr)["error"],
                        "assessment target policy must be a JSON object",
                    )
                    api.assert_not_called()

    def test_unreadable_policy_paths_fail_before_api_dispatch(self):
        for path in (self.root / "missing.json", self.root):
            for command in COMMANDS:
                with (
                    self.subTest(path=path, command=command),
                    patch(APIS[command]) as api,
                ):
                    code, stdout, stderr = self.invoke(self.args(command, target=path))
                    self.assertEqual((code, stdout), (2, ""))
                    self.assertEqual(json.loads(stderr)["status"], "failed")
                    api.assert_not_called()

    def test_existing_api_validators_reject_bare_version_and_tampered_bindings(self):
        for value in (
            {"schema_version": "3.1.0"},
            {**self.binding, "prompt_sha256": "0" * 64},
        ):
            self.save("target.json", value)
            for command in COMMANDS:
                with self.subTest(value=value, command=command):
                    code, stdout, stderr = self.invoke(
                        self.args(command, target=self.files["target"])
                    )
                    self.assertEqual((code, stdout), (2, ""))
                    self.assertEqual(
                        json.loads(stderr)["error"], "assessment-target-policy-binding"
                    )
                    self.assertFalse((self.root / f"{command}-output").exists())

    def test_daily_receipt_and_resume_protections_precede_dispatch(self):
        existing = self.save("existing-receipt.json", {"retained": True})
        args = self.args("daily-v3", target=self.files["target"])
        receipt_index = args.index("--replay-receipt-output") + 1
        for path, extra, error in (
            (existing, [], "replay receipt output already exists"),
            (
                self.root / "daily-v3-output" / "receipt.json",
                [],
                "replay receipt must remain outside daily output",
            ),
            (
                self.root / "new-receipt.json",
                ["--resume"],
                "daily-v3 resume and replay receipt must be supplied together",
            ),
            (
                self.root / "new-receipt.json",
                ["--replay-receipt", str(self.files["receipt"])],
                "daily-v3 resume and replay receipt must be supplied together",
            ),
        ):
            args[receipt_index] = str(path)
            with self.subTest(path=path, extra=extra), patch(APIS["daily-v3"]) as api:
                code, stdout, stderr = self.invoke(args + extra)
                self.assertEqual((code, stdout), (2, ""))
                self.assertEqual(json.loads(stderr)["error"], error)
                api.assert_not_called()
        self.assertEqual(json.loads(existing.read_bytes()), {"retained": True})

    def test_verify_does_not_overwrite_existing_output(self):
        output = self.root / "verify-daily-v3-output"
        output.write_bytes(b"retained bytes\n")
        with patch(
            APIS["verify-daily-v3"], return_value={"authenticated": True}
        ) as api:
            code, stdout, stderr = self.invoke(
                self.args("verify-daily-v3", target=self.files["target"])
            )
        self.assertEqual((code, stdout), (2, ""))
        self.assertEqual(json.loads(stderr)["status"], "failed")
        api.assert_called_once()
        self.assertEqual(output.read_bytes(), b"retained bytes\n")

    def test_command_help_explains_explicit_frozen_binding_without_dispatch(self):
        for command in COMMANDS:
            stdout = io.StringIO()
            with self.subTest(command=command), redirect_stdout(stdout):
                with self.assertRaises(SystemExit) as stopped:
                    live_main([command, "--help"])
                self.assertEqual(stopped.exception.code, 0)
                self.assertIn("--assessment-target-policy", stdout.getvalue())
                self.assertIn("host-frozen binding", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
