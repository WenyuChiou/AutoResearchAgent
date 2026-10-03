"""Adjudication must replay immutable QA evidence before resolving disagreements."""

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from stage1_eval.common import canonical  # noqa: E402
from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_eval.evaluation import RUBRIC_PATH, _load_rubric  # noqa: E402
from stage2_eval.rubric_quality import evaluate_quality, validate_reference  # noqa: E402
import stage2_live.rubric_adjudication as adjudication  # noqa: E402
from stage2_live.judges import _execution_policy  # noqa: E402
from stage2_live.native import codex_runtime_sha  # noqa: E402
from stage2_live.rubric_quality import _load_guidance  # noqa: E402
from test_stage2_rubric_quality import fixtures, judgments  # noqa: E402


class RubricAdjudicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.run = self.root / "run"
        self.run.mkdir()
        self.output = self.root / "resolution"
        self.binary = self.root / "codex.exe"
        self.binary.write_bytes(b"synthetic codex")
        for name in ("r1", "r2", "adj"):
            (self.root / name).mkdir()
        self.dataset, self.reference = fixtures()
        self.dataset_sha, self.reference_sha = (
            canonical_hash(self.dataset),
            canonical_hash(self.reference),
        )
        rubric, rubric_sha = _load_rubric(RUBRIC_PATH)
        _, guidance_sha = _load_guidance(rubric)
        self.code_sha = "a" * 64
        self.policy = _execution_policy({"evaluator_bundle_sha256": self.code_sha})
        self.bindings = {
            "dataset_sha256": self.dataset_sha,
            "rubric_sha256": rubric_sha,
            "guidance_sha256": guidance_sha,
            "code_sha256": self.code_sha,
            "runtime_sha256": codex_runtime_sha(self.binary),
            "model": "gpt-test",
            "reasoning": "medium",
            "execution_policy_sha256": canonical_hash(self.policy),
            "evaluator_homes": {
                "R1": str((self.root / "r1").resolve()),
                "R2": str((self.root / "r2").resolve()),
            },
        }
        self.r1 = judgments(self.dataset, "R1", self.bindings)
        self.r2 = judgments(self.dataset, "R2", self.bindings)
        self.case_id = self.dataset["cases"][1]["case_id"]
        self.r2["judgments"][1]["major_error"] = True
        bare = {
            key: value
            for key, value in self.bindings.items()
            if key != "dataset_sha256"
        }
        report = evaluate_quality(
            self.dataset,
            self.reference,
            self.r1,
            self.r2,
            dataset_sha256=self.dataset_sha,
            reference_sha256=self.reference_sha,
            bindings=bare,
        )
        report["native_qa_pass"] = report["passed"]
        self.request = {
            "kind": "Stage2RubricQualityRequest",
            "schema_version": "1.0.0",
            **self.bindings,
            "reference_sha256": self.reference_sha,
            "adapter_mode": "native",
            "batch_size": 7,
            "units_per_role": 8,
            "planned_units": 16,
            "cost": "unknown",
            "resume_supported": False,
        }
        receipts = {label: "b" * 64 for label in adjudication._base_labels()}
        self.result = {
            "kind": "Stage2RubricQualityRun",
            "schema_version": "1.0.0",
            "status": "complete",
            "adapter_mode": "native",
            "evidence_class": "native-live-diagnostic",
            "request_sha256": canonical_hash(self.request),
            "bindings": self.bindings,
            "roles": {"R1": self.r1, "R2": self.r2},
            "quality_report": report,
            "unit_receipts": receipts,
            "formal_ready": False,
        }
        (self.run / "request.json").write_bytes(canonical(self.request) + b"\n")
        (self.run / "result.json").write_bytes(canonical(self.result) + b"\n")
        self.result_sha = hashlib.sha256(
            (self.run / "result.json").read_bytes()
        ).hexdigest()
        for label in adjudication._base_labels():
            (self.run / f"{label}.schema.json").write_text("{}", encoding="utf-8")
            (self.run / f"{label}.unit.json").write_text("{}", encoding="utf-8")
            archive = self.run / f"{label}.model-call"
            archive.mkdir()
            (archive / "request.json").write_bytes(
                canonical({"execution_policy": self.policy}) + b"\n"
            )
        self.seen = []

    def tearDown(self):
        self.temporary.cleanup()

    def fake_unit(self, **kwargs):
        label, prompt = kwargs["label"], kwargs["prompt"]
        self.seen.append((label, prompt))
        if label.startswith(("r1-", "r2-")):
            role = label[:2].upper()
            index = int(label[-2:]) - 1
            rows = self.result["roles"][role]["judgments"][index * 7 : (index + 1) * 7]
            value = {
                "kind": "Stage2RubricQualityBatch",
                "schema_version": "1.0.0",
                "role": role,
                "judgments": copy.deepcopy(rows),
            }
        else:
            case = next(
                row for row in self.dataset["cases"] if row["case_id"] == self.case_id
            )
            row = {
                "case_id": self.case_id,
                "status": "scored",
                "score": 0,
                "evidence_ids": [case["facts"][0]["evidence_id"]],
                "reason": "The record supports this decision.",
                "major_error": False,
            }
            if label.endswith("initial"):
                value = {
                    "kind": "Stage2RubricQualityAdjInitial",
                    "schema_version": "1.0.0",
                    **row,
                }
            else:
                value = {
                    "kind": "Stage2RubricQualityAdjResolution",
                    "schema_version": "1.0.0",
                    **row,
                    "change_explanation": None,
                }
        kwargs["validate"](copy.deepcopy(value))
        sink = kwargs["options"].get("receipt_sink")
        if sink is not None and label.startswith("adj-"):
            sink[label] = "c" * 64
        return value, {"execution_status": "injected-test", "label": label}

    def resolve(self, **overrides):
        arguments = dict(
            dataset=self.dataset,
            reference=self.reference,
            dataset_sha256=self.dataset_sha,
            reference_sha256=self.reference_sha,
            run_dir=self.run,
            run_result_sha256=self.result_sha,
            codex=self.binary,
            adj_home=self.root / "adj",
            model="gpt-test",
            reasoning="medium",
            execution_policy={},
            output_dir=self.output,
            call_adapter=lambda *args, **kwargs: self.fail(
                "dispatch belongs inside patched unit"
            ),
        )
        arguments.update(overrides)
        with mock.patch.object(adjudication, "_run_unit", side_effect=self.fake_unit):
            return adjudication.resolve_rubric_quality(**arguments)

    def test_replays_sixteen_units_then_fake_adjudication_cannot_accept(self):
        result = self.resolve()
        self.assertEqual(
            [label for label, _ in self.seen[:16]], adjudication._base_labels()
        )
        self.assertEqual(result["raw_report"], self.result["quality_report"])
        self.assertEqual(result["execution"]["completed_units"], 2)
        self.assertEqual(len(result["unit_receipts"]), 2)
        self.assertFalse(result["quality_accepted"])
        self.assertFalse(result["formal_ready"])
        self.assertIsNone(result["human_audit"])
        adj_prompts = "\n".join(
            prompt for label, prompt in self.seen if label.startswith("adj-")
        )
        self.assertNotIn("allowed_scores", adj_prompts)
        self.assertNotIn("reference_sha256", adj_prompts)

    def test_external_result_hash_tamper_fails_closed(self):
        (self.run / "result.json").write_bytes(
            (self.run / "result.json").read_bytes() + b" "
        )
        with self.assertRaisesRegex(Stage2Error, "result hash"):
            self.resolve()

    def test_missing_archive_fails_closed(self):
        (self.run / "r1-01.schema.json").unlink()
        with self.assertRaisesRegex(Stage2Error, "missing base"):
            self.resolve()

    def test_optimistic_report_rewrite_is_rejected_even_when_rehashed(self):
        self.result["quality_report"]["critical_mismatches"] = []
        self.result["quality_report"]["counts"]["within_range_correct"] = 0
        (self.run / "result.json").write_bytes(canonical(self.result) + b"\n")
        digest = hashlib.sha256((self.run / "result.json").read_bytes()).hexdigest()
        with self.assertRaisesRegex(Stage2Error, "report was rewritten"):
            self.resolve(run_result_sha256=digest)

    def test_original_critical_error_cannot_be_laundered(self):
        raw = copy.deepcopy(self.result["quality_report"])
        raw["critical_mismatches"] = ["R1:critical-case"]
        resolved = [
            {
                "case_id": self.case_id,
                "resolution": {
                    "status": "scored",
                    "score": 1,
                    "evidence_ids": ["e"],
                    "reason": "x",
                    "major_error": False,
                },
            }
        ]
        refs = validate_reference(
            self.reference,
            self.reference_sha,
            {row["case_id"]: row for row in self.dataset["cases"]},
        )
        clean = copy.deepcopy(self.result["quality_report"])
        self.assertTrue(adjudication._quality_acceptance(clean, resolved, refs, True))
        self.assertFalse(adjudication._quality_acceptance(raw, resolved, refs, True))

    def test_adjudicated_score_outside_reference_blocks_acceptance(self):
        refs = validate_reference(
            self.reference,
            self.reference_sha,
            {row["case_id"]: row for row in self.dataset["cases"]},
        )
        resolved = [
            {
                "case_id": self.case_id,
                "resolution": {
                    "status": "scored",
                    "score": 0,
                    "evidence_ids": ["e"],
                    "reason": "source-supported but outside the private reference",
                    "major_error": False,
                },
            }
        ]
        self.assertFalse(
            adjudication._quality_acceptance(
                self.result["quality_report"], resolved, refs, True
            )
        )

    def test_unavailable_case_cannot_be_adjudicated_to_score(self):
        case = copy.deepcopy(self.dataset["cases"][0])
        case["observation"]["status"] = "unavailable"
        value = {
            "kind": "Stage2RubricQualityAdjInitial",
            "schema_version": "1.0.0",
            "case_id": case["case_id"],
            "status": "scored",
            "score": 0,
            "evidence_ids": [case["facts"][0]["evidence_id"]],
            "reason": "scored",
            "major_error": False,
        }
        with self.assertRaisesRegex(Stage2Error, "must remain unknown"):
            adjudication._validate_initial(value, case)


if __name__ == "__main__":
    unittest.main()
