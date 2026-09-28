"""Targeted contract tests for the isolated Stage 2 judge adapter."""

import copy
import json
import sys
import tempfile
import unittest
from unittest.mock import Mock
from pathlib import Path


HERE = Path(__file__).resolve().parent
PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PLUGIN / "cli"))
sys.path.insert(0, str(PLUGIN / "tests"))

from stage1_eval.common import EvaluationError  # noqa: E402
from stage2_fixture_helpers import write_stage2_fixture  # noqa: E402
from stage2_live.judges import run_stage2_judges, _verify_provenance, _obtain, _run_unit  # noqa: E402
from test_stage2_evaluation import action_record, content_assessment, judge  # noqa: E402


POLICY = {
    "schema_version": "3.1.0",
    "evaluator_bundle_sha256": "a" * 64,
    "timeout_seconds": 600,
    "max_transient_transport_retries": 1,
    "max_semantic_corrections_per_unit": 1,
    "retry_timeouts": False,
}


class FakeCallAdapter:
    def __init__(self, packet, *, disagreement=False, invalid=False, technical=False):
        self.packet = packet
        self.disagreement = disagreement
        self.invalid = invalid
        self.technical = technical
        self.calls = []

    def __call__(
        self,
        prompt,
        schema_path,
        output_dir,
        label,
        *,
        evaluator_home,
        semantic_validator,
        **_options,
    ):
        self.calls.append(
            {
                "label": label,
                "prompt": prompt,
                "home": str(Path(evaluator_home).resolve()),
                "schema": json.loads(Path(schema_path).read_text(encoding="utf-8")),
            }
        )
        if self.invalid:
            value = {"kind": "invalid-model-output", "scores": [0, 0, 0]}
            return value, {"execution_status": "fake", "label": label}

        payload = json.loads(prompt.splitlines()[-1])
        role = label.split("-", 1)[0].upper()
        if "content" in label:
            view = payload["content_view"]
            value = content_assessment(
                view,
                statement=f"{role} independently supports the bounded finding.",
            )
        else:
            view = payload["content_view"]
            action = payload["action_view"]
            value = judge(
                view,
                action,
                self.packet,
                role,
                technical=self.technical and role == "R1",
            )
            if self.disagreement and role == "R2":
                value["criteria"][1]["score"] = 2
        semantic_validator(copy.deepcopy(value))
        return value, {"execution_status": "fake", "label": label}


class Stage2JudgeAdapterTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.sources = self.root / "sources"
        self.packet = write_stage2_fixture(self.sources, candidate_count=2)
        self.actions = action_record(self.packet)
        self.homes = {}
        for role in ("r1", "r2", "adj"):
            path = self.root / f"home-{role}"
            path.mkdir()
            self.homes[role] = path
        self.codex = self.root / "codex"
        self.codex.write_bytes(b"mocked executable")

    def invoke(self, adapter, output="out", **changes):
        options = {
            "packet": self.packet,
            "source_root": self.sources,
            "subject_id": "opaque-subject-01",
            "input_sha256": "1" * 64,
            "config_sha256": "2" * 64,
            "action_record": self.actions,
            "r1_home": self.homes["r1"],
            "r2_home": self.homes["r2"],
            "adj_home": self.homes["adj"],
            "codex": self.codex,
            "model": "test-model",
            "reasoning": "high",
            "execution_policy": POLICY,
            "output_dir": self.root / output,
            "call_adapter": adapter,
        }
        options.update(changes)
        return run_stage2_judges(**options)

    def test_agreement_runs_content_before_action_and_skips_adjudicator(self):
        adapter = FakeCallAdapter(self.packet)
        result = self.invoke(adapter)

        self.assertEqual(
            [row["label"] for row in adapter.calls],
            ["r1-content", "r1-judge", "r2-content", "r2-judge"],
        )
        self.assertEqual(
            [row["home"] for row in adapter.calls],
            [
                str(self.homes["r1"].resolve()),
                str(self.homes["r1"].resolve()),
                str(self.homes["r2"].resolve()),
                str(self.homes["r2"].resolve()),
            ],
        )
        for row in (adapter.calls[0], adapter.calls[2]):
            self.assertNotIn("action_record", row["prompt"])
            self.assertNotIn("latest_dispositions", row["prompt"])
            self.assertNotIn("other reviewer output", row["prompt"].splitlines()[-1])
        self.assertNotIn("R2 independently supports", adapter.calls[1]["prompt"])
        self.assertNotIn("R1 independently supports", adapter.calls[3]["prompt"])
        self.assertEqual(result["status"], "complete")
        self.assertIsNone(result["judgments"]["ADJ"])
        self.assertFalse(result["bundle"]["external_claim_ready"])
        self.assertFalse(result["formal_claim_ready"])

    def test_disagreement_runs_independent_adj_content_then_requests_real_audit(self):
        adapter = FakeCallAdapter(self.packet, disagreement=True)
        result = self.invoke(adapter)

        self.assertEqual(
            [row["label"] for row in adapter.calls],
            [
                "r1-content",
                "r1-judge",
                "r2-content",
                "r2-judge",
                "adj-content",
                "adj-judge",
            ],
        )
        adj_content = adapter.calls[4]["prompt"]
        self.assertNotIn("R1 independently supports", adj_content)
        self.assertNotIn("R2 independently supports", adj_content)
        self.assertNotIn('"disagreement"', adj_content)
        self.assertIn('"disagreement"', adapter.calls[5]["prompt"])
        self.assertEqual(result["status"], "audit-required")
        self.assertIsNotNone(result["judgments"]["ADJ"])
        self.assertIsNone(result["bundle"])
        self.assertFalse(result["claim_gates"]["required_audit_accepted"])

    def test_resolved_home_aliases_are_rejected_before_model_calls(self):
        adapter = FakeCallAdapter(self.packet)
        alias = self.homes["r1"] / "nested" / ".."
        with self.assertRaisesRegex(EvaluationError, "must resolve uniquely"):
            self.invoke(adapter, r2_home=alias)
        self.assertEqual(adapter.calls, [])

    def test_validation_failure_is_evaluator_failure_without_subject_scores(self):
        adapter = FakeCallAdapter(self.packet, invalid=True)
        result = self.invoke(adapter)

        self.assertEqual(
            [row["label"] for row in adapter.calls],
            ["r1-content", "r1-content-correction"],
        )
        self.assertEqual(result["status"], "evaluator-failure")
        self.assertEqual(result["evaluator_status"], "evaluator_failure")
        self.assertIsNone(result["bundle"])
        self.assertEqual(result["judgments"], {"R1": None, "R2": None, "ADJ": None})
        self.assertNotIn("score", result)
        self.assertTrue((self.root / "out" / "result.json").is_file())

    def test_existing_units_and_correction_archives_cannot_bypass_resume_receipt(self):
        adapter = Mock(side_effect=AssertionError("must not call model"))
        output = self.root / "existing"
        output.mkdir()
        (output / "test.unit.json").write_text(
            '{"value":{"score":2}}', encoding="utf-8"
        )
        with self.assertRaisesRegex(EvaluationError, "receipted resume"):
            _run_unit(
                call_adapter=adapter,
                prompt="test",
                schema={},
                output_dir=output,
                label="test",
                options={"resume_verified": False},
                validate=lambda x: None,
            )
        for label in ("initial", "initial-correction"):
            (output / f"{label}.model-call").mkdir()
            with self.assertRaisesRegex(EvaluationError, "receipted replay"):
                _obtain(
                    adapter,
                    "test",
                    output / "schema.json",
                    output,
                    label,
                    {},
                    lambda x: None,
                )
        adapter.assert_not_called()

    def test_technical_failure_is_not_successful_judging_or_a_subject_zero(self):
        adapter = FakeCallAdapter(self.packet, technical=True)
        result = self.invoke(adapter)
        self.assertEqual(result["status"], "evaluator-failure")
        self.assertEqual(result["evaluator_status"], "evaluator_failure")
        self.assertFalse(result["bundle"]["usable"])
        self.assertEqual(result["bundle"]["criteria"], [])
        self.assertFalse(any(x["label"].startswith("adj-") for x in adapter.calls))

    def test_injected_adapter_cannot_claim_native_resume(self):
        adapter = FakeCallAdapter(self.packet)
        first = self.invoke(adapter)
        calls = len(adapter.calls)
        self.assertEqual(first["status"], "complete")
        with self.assertRaisesRegex(EvaluationError, "cannot prove native resume"):
            self.invoke(adapter, resume=True)
        self.assertEqual(len(adapter.calls), calls)

    def test_resume_rejects_runtime_change_before_call(self):
        adapter = FakeCallAdapter(self.packet)
        self.invoke(adapter)
        calls = len(adapter.calls)
        self.codex.write_bytes(b"changed runtime")
        with self.assertRaisesRegex(EvaluationError, "input or configuration changed"):
            self.invoke(adapter, resume=True)
        self.assertEqual(len(adapter.calls), calls)

        with self.assertRaisesRegex(EvaluationError, "input or configuration changed"):
            self.invoke(adapter, resume=True, model="changed-model")
        self.assertEqual(len(adapter.calls), calls)

    def test_resume_provenance_rejects_changed_runtime_or_call_receipt(self):
        actual = {
            "initial": {
                "execution_status": "native-replayed",
                "model": "frozen",
                "attempt_record_sha256": "a" * 64,
            },
            "correction": None,
        }
        saved = copy.deepcopy(actual)
        saved["initial"]["execution_status"] = "executed"
        _verify_provenance(saved, actual)
        for field in ("model", "attempt_record_sha256"):
            changed = copy.deepcopy(saved)
            changed["initial"][field] = "forged"
            with self.assertRaisesRegex(EvaluationError, "provenance changed"):
                _verify_provenance(changed, actual)

    def test_generated_schemas_are_closed_and_keep_unknown_null(self):
        adapter = FakeCallAdapter(self.packet)
        self.invoke(adapter)
        content_schema = adapter.calls[0]["schema"]
        judge_schema = adapter.calls[1]["schema"]
        self.assertFalse(content_schema["additionalProperties"])
        self.assertEqual(
            content_schema["properties"]["evaluator_status"], {"const": "complete"}
        )
        self.assertFalse(judge_schema["additionalProperties"])
        criterion = judge_schema["properties"]["criteria"]["items"]["anyOf"][0]
        self.assertEqual(criterion["properties"]["score"]["type"], ["integer", "null"])
        self.assertIn(None, criterion["properties"]["unknown_reason"]["enum"])
        self.assertEqual(
            len(judge_schema["properties"]["criteria"]["items"]["anyOf"]), 7
        )


if __name__ == "__main__":
    unittest.main()
