"""Synthetic native-protocol mechanics; no scientific or isolation attestation."""

import copy
import hashlib
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

from stage1_eval.common import EvaluationError, canonical  # noqa: E402
from stage1_eval.model_calls import _normalize_policy  # noqa: E402
from stage2_common import Stage2Error  # noqa: E402
from stage2_live.judge_worker import (  # noqa: E402
    execute_worker_unit,
    verify_worker_output,
    worker_sha256,
)
from stage2_live.native import codex_runtime_sha  # noqa: E402
from test_evaluator_model_calls import transcript  # noqa: E402


SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": ["integer", "null"], "minimum": 0, "maximum": 2},
        "flag": {"type": "boolean"},
        "reason": {"type": "string", "minLength": 1},
    },
    "required": ["score", "flag", "reason"],
    "additionalProperties": False,
}
VALUE = {"score": 1, "flag": False, "reason": "Synthetic native output only."}
RUN = "stage1_eval.model_calls._execute_bound_process"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_bytes())


def write_json(path, value):
    Path(path).write_bytes(canonical(value) + b"\n")


class JudgeWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="stage2-judge-worker-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.codex = self.root / "codex"
        self.codex.write_bytes(b"synthetic standalone binary")
        self.output = self.root / "output"
        self.request = self.inputs / "unit.json"
        self.unit = {
            "kind": "Stage2NativeJudgeUnit",
            "schema_version": "1.0.0",
            "role": "R1",
            "label": "r1-synthetic",
            "prompt": "Return the synthetic object without tools.\n",
            "schema": copy.deepcopy(SCHEMA),
            "model": "synthetic-model",
            "reasoning": "high",
            "runtime_sha256": codex_runtime_sha(self.codex),
            "worker_sha256": worker_sha256(),
            "execution_policy": _normalize_policy(
                {"schema_version": "3.1.0", "evaluator_bundle_sha256": "a" * 64},
                None,
            ),
        }
        self.save_request()

    def save_request(self):
        write_json(self.request, self.unit)
        self.request_sha256 = digest(self.request)

    def execute(self):
        return execute_worker_unit(
            self.request,
            self.request_sha256,
            output_dir=self.output,
            codex=self.codex,
            evaluator_home=self.home,
        )

    def verify(self, receipt):
        return verify_worker_output(
            self.output,
            receipt,
            request_file=self.request,
            request_sha256=self.request_sha256,
            codex=self.codex,
            evaluator_home=self.home,
        )

    @staticmethod
    def success(command, **_kwargs):
        Path(command[command.index("-o") + 1]).write_bytes(canonical(VALUE))
        return SimpleNamespace(returncode=0, stdout=transcript(VALUE), stderr=b"")

    def completed(self):
        with mock.patch(RUN, side_effect=self.success) as run:
            receipt = self.execute()
        self.assertEqual(run.call_count, 1)
        return receipt

    def snapshot(self):
        return {
            path.relative_to(self.output).as_posix(): path.read_bytes()
            for path in self.output.rglob("*")
            if path.is_file()
        }

    def test_standard_native_protocol_and_exact_disabled_feature_command(self):
        with mock.patch(RUN, side_effect=self.success) as run:
            receipt = self.execute()
        result = receipt["result"]
        archive = self.output / "r1-synthetic.model-call"
        disables = (
            "shell_tool",
            "unified_exec",
            "code_mode_host",
            "computer_use",
            "browser_use",
            "apps",
            "plugins",
            "view_image",
            "multi_agent",
            "skill_search",
            "hooks",
        )
        command = [str(self.codex), "exec", "--json"]
        for name in reversed(disables):
            command.extend(("--disable", name))
        command.extend(
            (
                "--ignore-user-config",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "-m",
                "synthetic-model",
                "-c",
                'model_reasoning_effort="high"',
                "--output-schema",
                str(archive / "generation-schema.json"),
                "-o",
                str(archive / "attempt-01.output.json"),
                "-",
            )
        )
        self.assertEqual(run.call_args.args[0], command)
        self.assertEqual(run.call_args.kwargs["input"], self.unit["prompt"].encode())
        self.assertEqual(run.call_args.kwargs["timeout"], 600)
        self.assertEqual(run.call_args.kwargs["env"]["CODEX_HOME"], str(self.home))
        self.assertFalse(Path(run.call_args.kwargs["cwd"]).is_relative_to(self.output))
        self.assertEqual(read_json(archive / "schema.json"), SCHEMA)
        self.assertEqual(
            read_json(archive / "generation-schema.json"),
            {
                "type": "object",
                "properties": {
                    "score": {
                        "type": ["integer", "null"],
                        "description": 'Additional locally enforced constraints: {"maximum": 2, "minimum": 0}',
                    },
                    "flag": {"type": "boolean"},
                    "reason": {
                        "type": "string",
                        "description": 'Additional locally enforced constraints: {"minLength": 1}',
                    },
                },
                "required": ["score", "flag", "reason"],
                "additionalProperties": False,
            },
        )
        self.assertEqual(result["value"], VALUE)
        self.assertEqual(result["actual_root_attempts"], 1)
        self.assertEqual(
            result["native_provenance"]["semantic_status"], "not-requested"
        )
        self.assertEqual(result["semantic_validation"], "host-required")
        self.assertEqual(result["namespace_isolation"], "external-attestation-required")
        self.assertEqual(result["nested_usage_accounting"], "not-attested")
        self.assertEqual(
            result["tool_event_policy"], "native-transcript-rejects-tool-events"
        )
        self.assertEqual(
            result["offered_tool_inventory"], "external-attestation-required"
        )
        self.assertEqual(result["cost"], "unknown")
        self.assertIsNone(result["calibration_pass"])
        self.assertIs(result["formal_ready"], False)
        self.assertEqual(
            receipt["result_sha256"], digest(self.output / "worker-result.json")
        )

    def test_r1_r2_and_adjudicator_roles_retain_their_native_binding(self):
        for role in ("R1", "R2", "ADJ"):
            with self.subTest(role=role):
                self.unit.update(role=role, label=role.lower() + "-synthetic")
                self.save_request()
                self.output = self.root / role
                receipt = self.completed()
                with mock.patch(RUN) as run:
                    self.assertEqual(
                        self.verify(receipt["result_sha256"]), receipt["result"]
                    )
                run.assert_not_called()
                self.assertEqual(receipt["result"]["role"], role)

    def test_readonly_replay_performs_no_call_or_evidence_write(self):
        receipt = self.completed()
        before = self.snapshot()
        with mock.patch(RUN) as run:
            result = self.verify(receipt["result_sha256"])
        run.assert_not_called()
        self.assertEqual(result, receipt["result"])
        self.assertEqual(self.snapshot(), before)

    def test_duplicate_execution_rejects_without_rerun(self):
        self.completed()
        before = self.snapshot()
        with mock.patch(RUN) as run:
            with self.assertRaisesRegex(Stage2Error, "not-fresh"):
                self.execute()
        run.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_request_hash_and_exact_shape_reject_before_native_call(self):
        original = copy.deepcopy(self.unit)
        cases = (
            {"unexpected": True},
            {"kind": "OtherUnit"},
            {"schema_version": "2.0.0"},
            {"role": "HOST"},
            {"label": "r2-wrong-role"},
            {"label": "r1-../outside"},
            {"prompt": " "},
            {"schema": {"type": "array"}},
            {"worker_sha256": "b" * 64},
            {"schema": {"type": "object", "properties": {"bad": {"type": "invalid"}}}},
            {"runtime_sha256": "b" * 64},
            {"execution_policy": {"schema_version": "3.1.0"}},
        )
        for change in cases:
            with self.subTest(change=change), mock.patch(RUN) as run:
                self.unit = {**original, **change}
                self.save_request()
                with self.assertRaises((Stage2Error, EvaluationError)):
                    self.execute()
                run.assert_not_called()
                self.assertFalse(self.output.exists())
        self.unit = original
        self.save_request()
        self.request.write_bytes(self.request.read_bytes() + b" ")
        with mock.patch(RUN) as run:
            with self.assertRaisesRegex(Stage2Error, "request-hash-mismatch"):
                self.execute()
        run.assert_not_called()

    def test_replay_rejects_changed_request_schema_runtime_worker_and_role(self):
        original = copy.deepcopy(self.unit)
        changes = (
            {"prompt": "Changed prompt"},
            {"schema": {**SCHEMA, "description": "changed schema"}},
            {"model": "other-model"},
            {"reasoning": "low"},
            {"runtime_sha256": "b" * 64},
            {"worker_sha256": "b" * 64},
            {"role": "R2", "label": "r2-synthetic"},
        )
        for index, change in enumerate(changes):
            with self.subTest(change=change):
                self.unit = copy.deepcopy(original)
                self.save_request()
                self.output = self.root / f"binding-{index}"
                receipt = self.completed()
                self.unit.update(change)
                self.save_request()
                # Rehashing both copies cannot replace the native request binding.
                write_json(self.output / "worker-request.json", self.unit)
                with mock.patch(RUN) as run:
                    with self.assertRaises((Stage2Error, EvaluationError, OSError)):
                        self.verify(receipt["result_sha256"])
                run.assert_not_called()

    def test_schema_references_reject_before_call_and_before_output_creation(self):
        for schema in (
            {"type": "object", "$ref": "#/$defs/missing"},
            {"type": "object", "$ref": "https://example.invalid/schema"},
            {"type": "object", "$dynamicRef": "#node"},
            {"type": "object", "properties": {"x": {"$recursiveRef": "#"}}},
        ):
            with self.subTest(schema=schema), mock.patch(RUN) as run:
                self.unit["schema"] = schema
                self.save_request()
                with self.assertRaisesRegex(Stage2Error, "references-unsupported"):
                    self.execute()
                run.assert_not_called()
                self.assertFalse(self.output.exists())

    def test_rehashed_native_role_label_rejected_against_original_request(self):
        receipt = self.completed()
        archive = self.output / "r1-synthetic.model-call"
        request_path = archive / "request.json"
        native = read_json(request_path)
        native["label"] = "r2-other-role"
        binding = {
            key: value
            for key, value in native.items()
            if key != "request_fingerprint_sha256"
        }
        native["request_fingerprint_sha256"] = hashlib.sha256(
            canonical(binding)
        ).hexdigest()
        write_json(request_path, native)
        attempt_path = archive / "attempt-01.record.json"
        attempt = read_json(attempt_path)
        attempt["request_fingerprint_sha256"] = native["request_fingerprint_sha256"]
        write_json(attempt_path, attempt)
        result = receipt["result"]
        result["native_provenance"]["request_fingerprint_sha256"] = native[
            "request_fingerprint_sha256"
        ]
        rows = []
        for path in sorted(archive.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_file():
                rows.append(
                    {
                        "path": path.relative_to(archive).as_posix(),
                        "sha256": digest(path),
                    }
                )
                result["files"][path.relative_to(self.output).as_posix()] = digest(path)
        result["archive_sha256"] = hashlib.sha256(canonical(rows)).hexdigest()
        path = self.output / "worker-result.json"
        write_json(path, result)
        with mock.patch(RUN) as run:
            with self.assertRaisesRegex(Stage2Error, "native-label-mismatch"):
                self.verify(digest(path))
        run.assert_not_called()

    def test_changed_executable_bytes_reject_on_readonly_replay(self):
        receipt = self.completed()
        self.codex.write_bytes(b"changed synthetic standalone binary")
        with mock.patch(RUN) as run:
            with self.assertRaisesRegex(Stage2Error, "runtime-mismatch"):
                self.verify(receipt["result_sha256"])
        run.assert_not_called()

    def test_rehashed_result_score_and_attestation_flags_reject(self):
        changes = (
            {"value": {**VALUE, "score": 2}},
            {"formal_ready": True},
            {"calibration_pass": True},
            {"semantic_validation": "passed"},
            {"namespace_isolation": "passed"},
            {"nested_usage_accounting": "complete"},
            {"offered_tool_inventory": "empty"},
            {"tool_event_policy": "all-tools-unavailable"},
            {"actual_root_attempts": 0},
            {"role": "R2"},
        )
        for index, change in enumerate(changes):
            with self.subTest(change=change):
                self.output = self.root / f"result-tamper-{index}"
                receipt = self.completed()
                path = self.output / "worker-result.json"
                write_json(path, {**receipt["result"], **change})
                with mock.patch(RUN) as run:
                    with self.assertRaisesRegex(Stage2Error, "recomputation-mismatch"):
                        self.verify(digest(path))
                run.assert_not_called()

    def test_rehashed_sidecar_tampering_rejects_native_disagreement(self):
        for index, suffix in enumerate(("json", "jsonl", "stderr.txt")):
            with self.subTest(suffix=suffix):
                self.output = self.root / f"sidecar-{index}"
                receipt = self.completed()
                path = self.output / f"r1-synthetic.{suffix}"
                path.write_bytes(b"edited display copy")
                result = receipt["result"]
                result["files"][path.name] = digest(path)
                result_path = self.output / "worker-result.json"
                write_json(result_path, result)
                with mock.patch(RUN) as run:
                    with self.assertRaisesRegex(Stage2Error, "display-copy-mismatch"):
                        self.verify(digest(result_path))
                run.assert_not_called()

    def test_unexpected_root_and_archive_additions_reject_even_when_rehashed(self):
        additions = (
            "extra.json",
            "r1-synthetic.model-call/extra.json",
            "empty/",
            "r1-synthetic.model-call/empty/",
        )
        for index, name in enumerate(additions):
            with self.subTest(name=name):
                self.output = self.root / f"inventory-{index}"
                receipt = self.completed()
                path = self.output / name
                result = receipt["result"]
                if name.endswith("/"):
                    path.mkdir()
                else:
                    path.write_bytes(b"unlisted bytes")
                    result["files"][name] = digest(path)
                archive = self.output / "r1-synthetic.model-call"
                rows = [
                    {
                        "path": item.relative_to(archive).as_posix(),
                        "sha256": digest(item),
                    }
                    for item in sorted(
                        archive.rglob("*"), key=lambda item: item.as_posix()
                    )
                    if item.is_file()
                ]
                result["archive_sha256"] = hashlib.sha256(canonical(rows)).hexdigest()
                result_path = self.output / "worker-result.json"
                write_json(result_path, result)
                with mock.patch(RUN) as run:
                    with self.assertRaisesRegex(Stage2Error, "unexpected-output"):
                        self.verify(digest(result_path))
                run.assert_not_called()

    def test_schema_constraints_fail_as_evaluator_failure_without_score(self):
        def invalid(command, **_kwargs):
            Path(command[command.index("-o") + 1]).write_bytes(canonical(value))
            return SimpleNamespace(returncode=0, stdout=transcript(value), stderr=b"")

        for index, value in enumerate(({**VALUE, "score": 3}, None)):
            with self.subTest(value=value):
                self.output = self.root / f"invalid-schema-{index}"
                with mock.patch(RUN, side_effect=invalid) as run:
                    with self.assertRaisesRegex(EvaluationError, "schema-mismatch"):
                        self.execute()
                self.assertEqual(run.call_count, 1)
                failure = read_json(self.output / "worker-failure.json")
                self.assertEqual(failure["status"], "evaluator_failure")
                self.assertNotIn("score", failure)
                self.assertNotIn("value", failure)
                self.assertFalse((self.output / "worker-result.json").exists())

    def test_timeout_retains_native_attempt_and_cannot_be_rerun(self):
        timeout = subprocess.TimeoutExpired(
            ["codex"], 600, output=b"partial stdout", stderr=b"partial stderr"
        )
        with mock.patch(RUN, side_effect=timeout) as run:
            with self.assertRaisesRegex(EvaluationError, "timed out"):
                self.execute()
        self.assertEqual(run.call_count, 1)
        archive = self.output / "r1-synthetic.model-call"
        self.assertEqual(
            (archive / "attempt-01.stdout.jsonl").read_bytes(), b"partial stdout"
        )
        self.assertEqual(
            (archive / "attempt-01.stderr.txt").read_bytes(), b"partial stderr"
        )
        record = read_json(archive / "attempt-01.record.json")
        self.assertIs(record["timed_out"], True)
        self.assertEqual(record["failure_class"], "timeout")
        self.assertEqual(
            read_json(self.output / "worker-failure.json")["status"],
            "evaluator_failure",
        )
        before = self.snapshot()
        with mock.patch(RUN) as run:
            with self.assertRaisesRegex(Stage2Error, "not-fresh"):
                self.execute()
            with self.assertRaises((Stage2Error, OSError)):
                self.verify("a" * 64)
        run.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_transport_retry_records_actual_root_attempts_and_readonly_replay(self):
        failed = SimpleNamespace(
            returncode=1, stdout=b"", stderr=b"HTTP 429 rate limit"
        )
        responses = iter((failed, None))

        def respond(command, **kwargs):
            value = next(responses)
            return value if value is not None else self.success(command, **kwargs)

        with mock.patch(RUN, side_effect=respond) as run:
            receipt = self.execute()
        self.assertEqual(run.call_count, 2)
        self.assertEqual(receipt["result"]["actual_root_attempts"], 2)
        self.assertEqual(receipt["result"]["native_provenance"]["attempt"], 2)
        archive = self.output / "r1-synthetic.model-call"
        self.assertEqual(
            read_json(archive / "attempt-01.record.json")["failure_class"],
            "transient-transport",
        )
        with mock.patch(RUN) as run:
            self.assertEqual(self.verify(receipt["result_sha256"]), receipt["result"])
        run.assert_not_called()

    def test_exhausted_transport_failure_is_not_a_scientific_zero(self):
        failed = SimpleNamespace(returncode=1, stdout=b"", stderr=b"connection reset")
        with mock.patch(RUN, return_value=failed) as run:
            with self.assertRaisesRegex(EvaluationError, "transient-transport"):
                self.execute()
        self.assertEqual(run.call_count, 2)
        self.assertEqual(
            read_json(self.output / "worker-failure.json")["status"],
            "evaluator_failure",
        )
        self.assertFalse((self.output / "worker-result.json").exists())
        self.assertEqual(
            len(list(self.output.glob("*.model-call/attempt-*.record.json"))), 2
        )

    def test_null_score_remains_unknown_and_does_not_gain_scientific_status(self):
        def unknown(command, **_kwargs):
            value = {
                **VALUE,
                "score": None,
                "reason": "Necessary evidence unavailable.",
            }
            Path(command[command.index("-o") + 1]).write_bytes(canonical(value))
            return SimpleNamespace(returncode=0, stdout=transcript(value), stderr=b"")

        with mock.patch(RUN, side_effect=unknown):
            receipt = self.execute()
        result = receipt["result"]
        self.assertIsNone(result["value"]["score"])
        self.assertIsNone(result["calibration_pass"])
        self.assertIs(result["formal_ready"], False)
        self.assertEqual(result["semantic_validation"], "host-required")
        with mock.patch(RUN) as run:
            self.assertEqual(self.verify(receipt["result_sha256"]), result)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
