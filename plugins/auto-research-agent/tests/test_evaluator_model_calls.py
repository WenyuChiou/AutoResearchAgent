import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))

from stage1_eval.common import EvaluationError, sha  # noqa: E402
from stage1_eval.model import (  # noqa: E402
    call_model,
    replay_native_model_call_archive,
    verify_model_call_archive,
)


SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}
POLICY = {
    "schema_version": "3.1.0",
    "evaluator_bundle_sha256": "a" * 64,
}


def transcript(value):
    rows = [
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": json.dumps(value)},
        },
        {"type": "turn.completed"},
    ]
    return ("\n".join(json.dumps(row) for row in rows) + "\n").encode()


class ModelCallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "output"
        self.home = self.root / "home"
        self.home.mkdir()
        self.codex = self.root / "codex"
        self.codex.write_bytes(b"fake executable")
        self.schema = self.root / "schema.json"
        self.schema.write_text(json.dumps(SCHEMA), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, **kwargs):
        options = {
            "codex": self.codex,
            "evaluator_home": self.home,
            "model": "test-model",
            "reasoning": "high",
            "execution_policy": POLICY,
        }
        options.update(kwargs)
        return call_model("raw prompt", self.schema, self.output, "judge", **options)

    @staticmethod
    def success(command, **_kwargs):
        value = {"ok": True}
        Path(command[command.index("-o") + 1]).write_bytes(json.dumps(value).encode())
        return SimpleNamespace(returncode=0, stdout=transcript(value), stderr=b"")

    def test_default_timeout_is_600_and_success_is_bound_to_native_json(self):
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run", side_effect=self.success
        ) as run:
            result, provenance = self.invoke()
        self.assertEqual(result, {"ok": True})
        self.assertEqual(run.call_args.kwargs["timeout"], 600)
        self.assertEqual(provenance["execution_status"], "executed")
        record = json.loads(
            (self.output / "judge.model-call/attempt-01.record.json").read_text()
        )
        self.assertEqual(record["timeout_seconds"], 600)
        self.assertEqual(record["status"], "completed")
        self.assertEqual(set(record["files"]), {"stdout", "stderr", "output"})

    def test_transient_transport_retries_once_then_stops(self):
        failed = SimpleNamespace(
            returncode=1, stdout=b"", stderr=b"HTTP 429 rate limit"
        )
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run",
            side_effect=[failed, failed],
        ) as run:
            with self.assertRaisesRegex(EvaluationError, "transient-transport"):
                self.invoke()
        self.assertEqual(run.call_count, 2)
        for number in (1, 2):
            archive = self.output / "judge.model-call"
            self.assertTrue((archive / f"attempt-{number:02d}.stdout.jsonl").is_file())
            self.assertTrue((archive / f"attempt-{number:02d}.stderr.txt").is_file())
            self.assertTrue((archive / f"attempt-{number:02d}.output.json").is_file())
            record = json.loads(
                (archive / f"attempt-{number:02d}.record.json").read_text()
            )
            self.assertEqual(record["failure_class"], "transient-transport")

    def test_frozen_zero_retry_policy_stops_after_first_transport_failure(self):
        failed = SimpleNamespace(
            returncode=1, stdout=b"", stderr=b"HTTP 429 rate limit"
        )
        policy = {**POLICY, "max_transient_transport_retries": 0}
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run", return_value=failed
        ) as run:
            with self.assertRaisesRegex(EvaluationError, "transient-transport"):
                self.invoke(execution_policy=policy)
        self.assertEqual(run.call_count, 1)
        self.assertFalse(
            (self.output / "judge.model-call/attempt-02.record.json").exists()
        )

    def test_transient_retry_can_succeed(self):
        failed = SimpleNamespace(
            returncode=1, stdout=b"", stderr=b"connection reset by peer"
        )
        calls = iter((failed, "success"))

        def response(command, **kwargs):
            value = next(calls)
            return self.success(command, **kwargs) if value == "success" else value

        with mock.patch(
            "stage1_eval.model_calls.subprocess.run",
            side_effect=response,
        ) as run:
            result, provenance = self.invoke()
        self.assertEqual(run.call_count, 2)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(provenance["attempt"], 2)

    def test_auth_failure_does_not_retry(self):
        failed = SimpleNamespace(
            returncode=1, stdout=b"", stderr=b"HTTP 401 Unauthorized"
        )
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run", return_value=failed
        ) as run:
            with self.assertRaisesRegex(EvaluationError, "process"):
                self.invoke()
        self.assertEqual(run.call_count, 1)

    def test_timeout_is_saved_and_does_not_retry(self):
        timeout = subprocess.TimeoutExpired(
            ["codex"], 600, output=b"partial stdout", stderr=b"partial stderr"
        )
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run", side_effect=timeout
        ) as run:
            with self.assertRaisesRegex(EvaluationError, "timed out"):
                self.invoke()
        self.assertEqual(run.call_count, 1)
        archive = self.output / "judge.model-call"
        self.assertEqual(
            (archive / "attempt-01.stdout.jsonl").read_bytes(), b"partial stdout"
        )
        record = json.loads((archive / "attempt-01.record.json").read_text())
        self.assertTrue(record["timed_out"])
        self.assertEqual(record["failure_class"], "timeout")

    def test_valid_resume_reuses_without_subprocess(self):
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run", side_effect=self.success
        ):
            self.invoke()
        with mock.patch("stage1_eval.model_calls.subprocess.run") as run:
            result, provenance = self.invoke(
                resume_verified=True, semantic_validator=lambda value: value["ok"]
            )
        run.assert_not_called()
        self.assertEqual(result, {"ok": True})
        self.assertEqual(provenance["execution_status"], "reused")
        self.assertTrue(provenance["reused_completed_generation"])

    def test_resume_rejects_changed_prompt_schema_and_config_without_execution(self):
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run", side_effect=self.success
        ):
            self.invoke()
        cases = [
            ("prompt", {"prompt": "changed"}),
            ("schema", {"schema": {**SCHEMA, "description": "changed"}}),
            ("config", {"model": "other-model"}),
        ]
        for name, change in cases:
            with (
                self.subTest(name=name),
                mock.patch("stage1_eval.model_calls.subprocess.run") as run,
            ):
                schema = self.schema
                if "schema" in change:
                    schema = self.root / f"{name}.json"
                    schema.write_text(json.dumps(change["schema"]), encoding="utf-8")
                options = {
                    "codex": self.codex,
                    "evaluator_home": self.home,
                    "model": change.get("model", "test-model"),
                    "reasoning": "high",
                    "execution_policy": POLICY,
                    "resume_verified": True,
                    "semantic_validator": lambda value: value["ok"],
                }
                with self.assertRaises(EvaluationError):
                    call_model(
                        change.get("prompt", "raw prompt"),
                        schema,
                        self.output,
                        "judge",
                        **options,
                    )
                run.assert_not_called()

    def test_resume_rejects_tampered_native_and_output(self):
        for target in ("stdout", "output"):
            with self.subTest(target=target):
                output = self.root / f"output-{target}"
                self.output = output
                with mock.patch(
                    "stage1_eval.model_calls.subprocess.run", side_effect=self.success
                ):
                    self.invoke()
                archive = output / "judge.model-call"
                record = json.loads((archive / "attempt-01.record.json").read_text())
                path = archive / record["files"][target]["path"]
                path.write_bytes(b"{}")
                with mock.patch("stage1_eval.model_calls.subprocess.run") as run:
                    with self.assertRaisesRegex(EvaluationError, "bytes changed"):
                        self.invoke(
                            resume_verified=True,
                            semantic_validator=lambda value: value["ok"],
                        )
                    run.assert_not_called()

    def test_semantic_validator_rejects_execution_and_resume(self):
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run", side_effect=self.success
        ) as run:
            with self.assertRaisesRegex(EvaluationError, "semantic-mismatch"):
                self.invoke(semantic_validator=lambda _value: False)
        self.assertEqual(run.call_count, 1)
        record = json.loads(
            (self.output / "judge.model-call/attempt-01.record.json").read_text()
        )
        self.assertEqual(record["failure_class"], "semantic-mismatch")
        self.assertEqual(record["generation_status"], "completed")
        self.assertEqual(record["semantic_status"], "rejected")
        request = json.loads(
            (self.output / "judge.model-call/request.json").read_text()
        )
        native, native_meta = replay_native_model_call_archive(
            self.output / "judge.model-call",
            expected_prompt="raw prompt",
            expected_schema=self.schema,
            expected_config=request["config"],
            expected_policy=POLICY,
        )
        self.assertEqual(native, {"ok": True})
        self.assertEqual(native_meta["execution_status"], "native-replayed")
        self.assertFalse(native_meta["reused_completed_generation"])

        self.output = self.root / "resume-semantic"
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run", side_effect=self.success
        ):
            self.invoke()
        with mock.patch("stage1_eval.model_calls.subprocess.run") as run:
            with self.assertRaisesRegex(EvaluationError, "semantic validation"):
                self.invoke(
                    resume_verified=True,
                    semantic_validator=lambda _value: False,
                )
            run.assert_not_called()

    def test_schema_mismatch_and_spawn_failure_are_saved_without_retry(self):
        def invalid(command, **_kwargs):
            value = {"ok": "not-a-boolean"}
            Path(command[command.index("-o") + 1]).write_bytes(
                json.dumps(value).encode()
            )
            return SimpleNamespace(returncode=0, stdout=transcript(value), stderr=b"")

        with mock.patch(
            "stage1_eval.model_calls.subprocess.run", side_effect=invalid
        ) as run:
            with self.assertRaisesRegex(EvaluationError, "schema-mismatch"):
                self.invoke()
        self.assertEqual(run.call_count, 1)
        record = json.loads(
            (self.output / "judge.model-call/attempt-01.record.json").read_text()
        )
        self.assertIn("local schema validation", record["failure_detail"])

        self.output = self.root / "spawn"
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run",
            side_effect=FileNotFoundError("missing codex"),
        ) as run:
            with self.assertRaisesRegex(EvaluationError, "spawn"):
                self.invoke()
        self.assertEqual(run.call_count, 1)
        record = json.loads(
            (self.output / "judge.model-call/attempt-01.record.json").read_text()
        )
        self.assertEqual(record["failure_class"], "spawn")
        self.assertIn("missing codex", record["failure_detail"])

        self.output = self.root / "spawn-connection"
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run",
            side_effect=ConnectionResetError("spawn connection reset"),
        ) as run:
            with self.assertRaisesRegex(EvaluationError, "spawn"):
                self.invoke()
        self.assertEqual(run.call_count, 1)
        self.assertFalse(
            (self.output / "judge.model-call/attempt-02.record.json").exists()
        )

    def test_stdout_model_text_cannot_trigger_transport_retry(self):
        malicious = SimpleNamespace(
            returncode=1,
            stdout=transcript({"message": "HTTP 429 connection reset"}),
            stderr=b"",
        )
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run", return_value=malicious
        ) as run:
            with self.assertRaisesRegex(EvaluationError, "process"):
                self.invoke()
        self.assertEqual(run.call_count, 1)

    def test_replay_rejects_tampered_prior_attempt_and_unsafe_file_reference(self):
        failed = SimpleNamespace(
            returncode=1, stdout=b"", stderr=b"HTTP 429 rate limit"
        )
        calls = iter((failed, "success"))

        def response(command, **kwargs):
            value = next(calls)
            return self.success(command, **kwargs) if value == "success" else value

        with mock.patch("stage1_eval.model_calls.subprocess.run", side_effect=response):
            self.invoke()
        archive = self.output / "judge.model-call"
        (archive / "attempt-01.stderr.txt").write_bytes(b"edited")
        with self.assertRaisesRegex(EvaluationError, "bytes changed"):
            self.invoke(
                resume_verified=True, semantic_validator=lambda value: value["ok"]
            )

        self.output = self.root / "rehashed-prior"
        calls = iter((failed, "success"))
        with mock.patch("stage1_eval.model_calls.subprocess.run", side_effect=response):
            self.invoke()
        archive = self.output / "judge.model-call"
        stderr_path = archive / "attempt-01.stderr.txt"
        stderr_path.write_bytes(b"ordinary non-transient process failure")
        record_path = archive / "attempt-01.record.json"
        record = json.loads(record_path.read_text())
        record["files"]["stderr"]["sha256"] = sha(stderr_path.read_bytes())
        record_path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaisesRegex(EvaluationError, "unauthorized retry"):
            self.invoke(
                resume_verified=True, semantic_validator=lambda value: value["ok"]
            )

        self.output = self.root / "unsafe"
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run", side_effect=self.success
        ):
            self.invoke()
        archive = self.output / "judge.model-call"
        record_path = archive / "attempt-01.record.json"
        record = json.loads(record_path.read_text())
        record["files"]["output"]["path"] = "../outside.json"
        record_path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaisesRegex(EvaluationError, "unsafe"):
            self.invoke(
                resume_verified=True, semantic_validator=lambda value: value["ok"]
            )

    def test_public_replay_helper_checks_expected_request(self):
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run", side_effect=self.success
        ):
            _result, provenance = self.invoke()
        request = json.loads(
            (self.output / "judge.model-call/request.json").read_text()
        )
        result, replay = verify_model_call_archive(
            provenance["call_archive"],
            expected_prompt="raw prompt",
            expected_schema=self.schema,
            expected_config=request["config"],
            expected_policy=POLICY,
            semantic_validator=lambda value: value["ok"],
        )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(replay["execution_status"], "reused")

    def test_archive_path_alias_is_canonical_before_execution_and_replay(self):
        self.output = self.root / "alias" / ".." / "output"
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run", side_effect=self.success
        ):
            _, provenance = self.invoke()
        archive = Path(provenance["call_archive"])
        self.assertEqual(archive, self.output.resolve() / "judge.model-call")
        request = json.loads((archive / "request.json").read_text())
        record_path = archive / "attempt-01.record.json"
        record = json.loads(record_path.read_text())
        self.assertEqual(
            record["command"][record["command"].index("-o") + 1],
            str(archive / "attempt-01.output.json"),
        )
        args = dict(
            expected_prompt="raw prompt",
            expected_schema=self.schema,
            expected_config=request["config"],
            expected_policy=POLICY,
            semantic_validator=lambda value: value["ok"],
        )
        with mock.patch("stage1_eval.model_calls.subprocess.run") as execute:
            value, _ = verify_model_call_archive(archive, **args)
        execute.assert_not_called()
        self.assertEqual(value, {"ok": True})
        record["command"][record["command"].index("-o") + 1] = str(
            archive.parent / "foreign.output.json"
        )
        record_path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaisesRegex(EvaluationError, "command changed"):
            verify_model_call_archive(archive, **args)

    def test_replay_rejects_renamed_attempt_record(self):
        with mock.patch(
            "stage1_eval.model_calls.subprocess.run", side_effect=self.success
        ):
            self.invoke()
        archive = self.output / "judge.model-call"
        (archive / "attempt-01.record.json").rename(archive / "attempt-00.record.json")
        with self.assertRaisesRegex(EvaluationError, "attempt"):
            self.invoke(
                resume_verified=True,
                semantic_validator=lambda value: value["ok"],
            )


if __name__ == "__main__":
    unittest.main()
