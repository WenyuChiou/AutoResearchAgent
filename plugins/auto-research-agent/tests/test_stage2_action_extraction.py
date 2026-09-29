# ruff: noqa: E402 -- import the repository CLI without installing a package.
"""Contract tests for span-bound Stage 2 action extraction."""

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
sys.path.insert(0, str(PLUGIN / "cli"))
sys.path.insert(0, str(HERE))

from stage1_eval.common import EvaluationError, canonical
from stage2_common import Stage2Error, canonical_hash
from stage2_fixture_helpers import write_stage2_fixture
from stage2_live.action_extraction import (
    run_action_extraction,
    verify_action_extraction,
)
from test_stage2_evaluation import action_record
from test_stage2_live_judges import POLICY


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class Stub:
    def __init__(self, value):
        self.value = value
        self.labels = []

    def __call__(
        self, _prompt, _schema, _output, label, *, semantic_validator, **_kwargs
    ):
        self.labels.append(label)
        value = copy.deepcopy(self.value)
        semantic_validator(copy.deepcopy(value))
        return value, {"execution_status": "fake", "label": label}


class ActionExtractionTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.sources = self.root / "sources"
        self.packet = write_stage2_fixture(
            self.sources, candidate_count=2, revise_first=True
        )
        self.action = action_record(self.packet)
        self.raw = (
            "Recommend candidate-1 version 2 based on ev-1; proceed to human review.\n"
            "Recommend candidate-2 version 1 based on ev-1; retain it as an option.\n"
            "The earlier candidate-1 version was revised into version 2 for the stated evidence.\n"
            "Select candidate-1 while preserving both decision events and the revision history.\n"
        )
        self.home = self.root / "home"
        self.home.mkdir()
        self.codex = self.root / "codex"
        self.codex.write_bytes(b"native executable")
        self.config = {
            "codex": str(self.codex.resolve()),
            "codex_executable_sha256": sha(self.codex.read_bytes()),
            "evaluator_home": str(self.home.resolve()),
            "model": "test-model",
            "reasoning": "high",
        }

    def generated(self):
        spans = [f"proposal-span-v1-{index:06d}" for index in range(1, 5)]
        latest = [
            {
                "candidate_id": row["candidate_id"],
                "candidate_version": row["candidate_version"],
                "span_ids": [spans[index]],
            }
            for index, row in enumerate(self.action["latest_dispositions"])
        ]
        history = [
            {"event_id": row["event_id"], "span_ids": [spans[min(index, 1)]]}
            for index, row in enumerate(self.action["history"])
        ]
        revisions = [
            {
                "candidate_id": row["candidate_id"],
                "from_version": row["from_version"],
                "to_version": row["to_version"],
                "span_ids": [spans[2]],
            }
            for row in self.action["revision_history"]
        ]
        return {
            "kind": "Stage2ActionExtractionDraft",
            "schema_version": "1.0.0",
            "action_record": copy.deepcopy(self.action),
            "unresolved_reason": None,
            "provenance": {
                "latest_dispositions": latest,
                "history": history,
                "revision_history": revisions,
                "selection": {"span_ids": [spans[3]]},
            },
        }

    def invoke(self, value, name="out", **changes):
        adapter = Stub(value)
        options = {
            "codex": self.codex,
            "evaluator_home": self.home,
            "model": "test-model",
            "reasoning": "high",
            "execution_policy": POLICY,
            "output_dir": self.root / name,
            "call_adapter": adapter,
        }
        options.update(changes)
        return run_action_extraction(
            self.raw, self.packet, self.sources, **options
        ), adapter

    def test_natural_prose_produces_bound_action_without_external_ledger(self):
        result, adapter = self.invoke(self.generated())
        self.assertEqual(adapter.labels, ["action-extraction"])
        self.assertEqual(result["action_record"], self.action)
        self.assertTrue(result["action_record_ready"])
        self.assertFalse(result["formal_score_ready"])
        self.assertEqual(result["evidence_class"], "synthetic-test-only")
        self.assertEqual(
            result["span_provenance"]["selection"]["spans"][0]["quote"],
            self.raw.splitlines(keepends=True)[3],
        )

    def test_omitted_decisions_remain_unresolved(self):
        unresolved = {
            "kind": "Stage2ActionExtractionDraft",
            "schema_version": "1.0.0",
            "action_record": None,
            "unresolved_reason": "The prose does not state dispositions for all candidates.",
            "provenance": None,
        }
        result, _ = self.invoke(unresolved)
        self.assertEqual(result["status"], "unresolved")
        self.assertIsNone(result["action_record"])
        self.assertFalse(result["action_record_ready"])

    def test_foreign_span_packet_hash_and_candidate_fail_closed(self):
        cases = []
        bad_span = self.generated()
        bad_span["provenance"]["selection"]["span_ids"] = ["foreign"]
        cases.append(bad_span)
        bad_hash = self.generated()
        bad_hash["action_record"]["packet_sha256"] = "0" * 64
        cases.append(bad_hash)
        bad_candidate = self.generated()
        bad_candidate["action_record"]["latest_dispositions"][0]["candidate_id"] = (
            "foreign"
        )
        cases.append(bad_candidate)
        for index, value in enumerate(cases):
            with (
                self.subTest(index=index),
                self.assertRaises((EvaluationError, Stage2Error, ValueError)),
            ):
                self.invoke(value, name=f"bad-{index}")
            self.assertTrue((self.root / f"bad-{index}" / "failure.json").is_file())
            self.assertFalse((self.root / f"bad-{index}" / "result.json").exists())

    def test_verified_resume_does_not_reexecute_adapter(self):
        first, adapter = self.invoke(self.generated(), name="resume")

        def replay(*_args, **_kwargs):
            return copy.deepcopy(self.generated()), copy.deepcopy(
                first["model_call_provenance"]["initial"]
            )

        with patch(
            "stage2_live.judges.replay_native_model_call_archive", side_effect=replay
        ):
            second = run_action_extraction(
                self.raw,
                self.packet,
                self.sources,
                codex=self.codex,
                evaluator_home=self.home,
                model="test-model",
                reasoning="high",
                execution_policy=POLICY,
                output_dir=self.root / "resume",
                resume=True,
                resume_receipt=first["replay_receipt"],
                call_adapter=adapter,
            )
        self.assertEqual(second, first)
        self.assertEqual(adapter.labels, ["action-extraction"])

    def test_script_runtime_is_rejected_before_model_use(self):
        shim = self.root / "codex.cmd"
        shim.write_text("vendor.exe", encoding="utf-8")
        adapter = Mock(side_effect=AssertionError("must not dispatch"))
        with self.assertRaisesRegex(Exception, "standalone Codex binary"):
            run_action_extraction(
                self.raw,
                self.packet,
                self.sources,
                codex=shim,
                evaluator_home=self.home,
                model="test-model",
                reasoning="high",
                execution_policy=POLICY,
                output_dir=self.root / "shim",
                call_adapter=adapter,
            )
        adapter.assert_not_called()

    def test_readonly_verifier_checks_native_result_and_missing_call_archive(self):
        result, _ = self.invoke(self.generated(), name="verify")
        output = self.root / "verify"
        request_path = output / "request.json"
        request = json.loads(request_path.read_text(encoding="utf-8"))
        request["adapter_mode"] = "native"
        request_path.write_bytes(canonical(request) + b"\n")
        result_path = output / "result.json"
        saved = json.loads(result_path.read_text(encoding="utf-8"))
        saved["request_sha256"] = canonical_hash(request)
        saved["native_execution_verified"] = True
        saved["evidence_class"] = "host-native-capture"
        result_path.write_bytes(canonical(saved) + b"\n")
        receipt = {
            "result_sha256": sha(result_path.read_bytes()),
            "unit_receipts": result["replay_receipt"]["unit_receipts"],
        }
        unit = json.loads(
            (output / "action-extraction.unit.json").read_text(encoding="utf-8")
        )

        def replay(*_args, **kwargs):
            kwargs["validate"](copy.deepcopy(unit["value"]))
            return {
                "value": copy.deepcopy(unit["value"]),
                "provenance": copy.deepcopy(unit["provenance"]),
                "actual_call_count": 1,
                "archive_sha256s": {"initial": "a" * 64},
                "portable_path_limitation": "same-host",
            }

        with patch("stage2_live.action_extraction.replay_unit", side_effect=replay):
            verified = verify_action_extraction(
                output,
                receipt,
                raw_proposal=self.raw,
                packet=self.packet,
                source_root=self.sources,
                expected_config=self.config,
                expected_policy=POLICY,
            )
        self.assertTrue(verified["result"]["action_record_ready"])
        self.assertEqual(verified["actual_call_count"], 1)

        with self.assertRaisesRegex(Exception, "missing-replay-directory"):
            verify_action_extraction(
                output,
                receipt,
                raw_proposal=self.raw,
                packet=self.packet,
                source_root=self.sources,
                expected_config=self.config,
                expected_policy=POLICY,
            )


if __name__ == "__main__":
    unittest.main()
