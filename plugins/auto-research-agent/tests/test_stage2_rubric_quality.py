"""Rubric-quality calibration stays complete, blinded, and diagnostic-only."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
import sys
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_eval.evaluation import CRITERIA  # noqa: E402
from stage2_eval.rubric_quality import (
    evaluate_quality,
    validate_dataset,
    validate_judgment,
)  # noqa: E402
from stage2_live.rubric_quality import _archived_native_attempts, run_rubric_quality  # noqa: E402
import stage2_live.rubric_quality as live_quality  # noqa: E402


def fixtures(version="1.1.0"):
    cases = []
    chosen = []
    for criterion_index, criterion in enumerate(CRITERIA):
        for anchor_index in range(4):
            case_id = f"c{criterion_index}-{anchor_index}"
            facts = [
                {
                    "evidence_id": f"e{criterion_index}-{anchor_index}",
                    "text": f"fact {criterion_index}-{anchor_index}",
                }
            ]
            case = {
                "case_id": case_id,
                "criterion_id": criterion,
                "base_case_id": None,
                "transformation": None,
                "facts": facts,
                "presentation": f"anchor {case_id}",
            }
            if version == "1.1.0":
                case["observation"] = {
                    "status": "observed",
                    "record_ref": f"record:{case_id}",
                }
            cases.append(case)
            if anchor_index == 0:
                chosen.append(cases[-1])
    for anchor in chosen:
        for transform in ("order", "length", "prestige", "preference"):
            case = {
                "case_id": f"{anchor['case_id']}-{transform}",
                "criterion_id": anchor["criterion_id"],
                "base_case_id": anchor["case_id"],
                "transformation": transform,
                "facts": copy.deepcopy(anchor["facts"]),
                "presentation": f"{transform} presentation",
            }
            if version == "1.1.0":
                case["observation"] = copy.deepcopy(anchor["observation"])
            cases.append(case)
    dataset = {
        "kind": "Stage2RubricQualityDataset",
        "schema_version": version,
        "cases": cases,
    }
    reference = {
        "kind": "Stage2RubricQualityReference",
        "schema_version": "1.0.0",
        "rows": [_reference_row(case) for case in cases],
    }
    return dataset, reference


def judgments(dataset, role, bindings):
    return {
        "role": role,
        "bindings": bindings,
        "judgments": [_judgment_row(case) for case in dataset["cases"]],
    }


def _anchor_index(case):
    return int((case["base_case_id"] or case["case_id"]).split("-")[1])


def _reference_row(case):
    anchor = _anchor_index(case)
    unknown = anchor == 3
    return {
        "case_id": case["case_id"],
        "status": "unknown" if unknown else "scored",
        "allowed_scores": [None] if unknown else [anchor],
        "major_error": None if unknown else False,
        "critical": case["case_id"] == "c0-0",
    }


def _judgment_row(case):
    anchor = _anchor_index(case)
    unknown = anchor == 3
    return {
        "case_id": case["case_id"],
        "status": "unknown" if unknown else "scored",
        "score": None if unknown else anchor,
        "evidence_ids": [] if unknown else [case["facts"][0]["evidence_id"]],
        "reason": "subject record unavailable" if unknown else "supported",
        "major_error": None if unknown else False,
    }


class RubricQualityTests(unittest.TestCase):
    def setUp(self):
        self.dataset, self.reference = fixtures()
        self.dataset_sha = canonical_hash(self.dataset)
        self.reference_sha = canonical_hash(self.reference)
        self.base_bindings = {
            "rubric_sha256": "a" * 64,
            "code_sha256": "b" * 64,
            "guidance_sha256": "f" * 64,
            "runtime_sha256": "c" * 64,
            "execution_policy_sha256": "d" * 64,
            "model": "gpt-test",
            "reasoning": "medium",
            "evaluator_homes": {"R1": "C:/r1", "R2": "C:/r2"},
        }
        self.bindings = {**self.base_bindings, "dataset_sha256": self.dataset_sha}
        self.r1 = judgments(self.dataset, "R1", self.bindings)
        self.r2 = judgments(self.dataset, "R2", self.bindings)

    def evaluate(self, r1=None, r2=None):
        return evaluate_quality(
            self.dataset,
            self.reference,
            r1 or self.r1,
            r2 or self.r2,
            dataset_sha256=self.dataset_sha,
            reference_sha256=self.reference_sha,
            bindings=self.base_bindings,
        )

    def test_thresholds_fixed_denominators_and_unresolved_difference(self):
        report = self.evaluate()
        self.assertEqual(
            report["counts"],
            {
                "within_range_correct": 112,
                "within_range_total": 112,
                "agreement_exact": 56,
                "agreement_total": 56,
                "invariant_exact": 56,
                "invariant_total": 56,
            },
        )
        self.assertTrue(report["passed"])
        changed = copy.deepcopy(self.r2)
        changed["judgments"][1]["score"] = 2
        report = self.evaluate(r2=changed)
        self.assertEqual(
            (
                report["counts"]["within_range_correct"],
                report["counts"]["agreement_exact"],
            ),
            (111, 55),
        )
        self.assertGreaterEqual(report["rates"]["r1_r2_agreement"], 0.85)
        self.assertTrue(report["passed"])
        self.assertEqual(report["unresolved_disagreements"], ["c0-1"])
        self.assertEqual(report["minor_disagreements"], ["c0-1"])
        critical = copy.deepcopy(self.r2)
        critical["judgments"][0]["major_error"] = True
        report = self.evaluate(r2=critical)
        self.assertEqual(report["counts"]["agreement_exact"], 56)
        self.assertEqual(report["critical_mismatches"], ["R2:c0-0"])
        self.assertFalse(report["passed"])
        for result in (self.r1, self.r2):
            result["judgments"][28]["major_error"] = True
        report = self.evaluate()
        self.assertEqual(report["counts"]["invariant_exact"], 56)
        self.assertEqual(len(report["major_error_invariance_mismatches"]), 2)
        self.assertFalse(report["passed"])

    def test_missing_failure_and_null_never_shrink_or_inflate(self):
        missing = copy.deepcopy(self.r1)
        missing["judgments"].pop()
        failed = copy.deepcopy(self.r2)
        failed["judgments"][1].update(
            status="evaluator_failure", score=None, evidence_ids=[], major_error=None
        )
        report = self.evaluate(missing, failed)
        self.assertEqual(report["counts"]["within_range_total"], 112)
        self.assertFalse(report["complete"])
        report = self.evaluate()
        self.assertEqual(report["counts"]["within_range_correct"], 112)

    def test_malformed_role_case_id_is_typed(self):
        for invalid in ([], {}, None, 1):
            with self.subTest(case_id=invalid):
                result = copy.deepcopy(self.r1)
                result["judgments"][0]["case_id"] = invalid
                with self.assertRaisesRegex(Stage2Error, "R1 invalid case ID"):
                    self.evaluate(r1=result)

    def test_anchor_reference_coverage_cannot_be_all_scored_one(self):
        invalid = copy.deepcopy(self.reference)
        for row in invalid["rows"]:
            row.update(status="scored", allowed_scores=[1], major_error=False)
        with self.assertRaisesRegex(Stage2Error, "exact 0/1/2/unknown"):
            evaluate_quality(
                self.dataset,
                invalid,
                self.r1,
                self.r2,
                dataset_sha256=self.dataset_sha,
                reference_sha256=canonical_hash(invalid),
                bindings=self.base_bindings,
            )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "codex.exe"
            binary.write_bytes(b"synthetic executable")
            (root / "r1").mkdir()
            (root / "r2").mkdir()
            with self.assertRaisesRegex(Stage2Error, "exact 0/1/2/unknown"):
                run_rubric_quality(
                    self.dataset,
                    invalid,
                    dataset_sha256=self.dataset_sha,
                    reference_sha256=canonical_hash(invalid),
                    codex=binary,
                    r1_home=root / "r1",
                    r2_home=root / "r2",
                    model="gpt-test",
                    reasoning="medium",
                    execution_policy={},
                    output_dir=root / "out",
                    call_adapter=lambda *args, **kwargs: self.fail("must not dispatch"),
                )

    def test_malformed_dataset_version_and_evidence_ids_raise_stage2_error(self):
        malformed = copy.deepcopy(self.dataset)
        malformed["schema_version"] = []
        with self.assertRaisesRegex(Stage2Error, "wrong dataset version"):
            validate_dataset(malformed, canonical_hash(malformed))
        judgment = copy.deepcopy(self.r1["judgments"][0])
        judgment["evidence_ids"] = [{}]
        with self.assertRaisesRegex(Stage2Error, "invalid evidence IDs"):
            validate_judgment(judgment, self.dataset["cases"][0])
        malformed_reference = copy.deepcopy(self.reference)
        malformed_reference["rows"][0]["allowed_scores"] = [{}]
        with self.assertRaisesRegex(Stage2Error, "invalid scored reference"):
            evaluate_quality(
                self.dataset,
                malformed_reference,
                self.r1,
                self.r2,
                dataset_sha256=self.dataset_sha,
                reference_sha256=canonical_hash(malformed_reference),
                bindings=self.base_bindings,
            )

    def test_malformed_container_and_status_are_typed(self):
        from stage2_eval.rubric_quality import validate_reference

        cases = validate_dataset(self.dataset, self.dataset_sha)
        for value in (None, []):
            with self.subTest(container=value):
                with self.assertRaises(Stage2Error):
                    validate_dataset(value, canonical_hash(value))
                with self.assertRaises(Stage2Error):
                    validate_reference(value, canonical_hash(value), cases)
        bad = copy.deepcopy(self.dataset)
        bad["cases"][0]["observation"]["status"] = []
        with self.assertRaises(Stage2Error):
            validate_dataset(bad, canonical_hash(bad))
        for field in ("status", "case_id"):
            bad = copy.deepcopy(self.reference)
            bad["rows"][0][field] = []
            with self.subTest(reference_field=field):
                with self.assertRaises(Stage2Error):
                    validate_reference(bad, canonical_hash(bad), cases)
        bad = copy.deepcopy(self.r1["judgments"][0])
        bad["status"] = []
        with self.assertRaises(Stage2Error):
            validate_judgment(bad, self.dataset["cases"][0])

    def test_rehashed_variant_or_wrong_case_evidence_is_rejected(self):
        changed = copy.deepcopy(self.dataset)
        changed["cases"][-1]["facts"][0]["text"] = "changed fact"
        with self.assertRaisesRegex(Stage2Error, "variant facts"):
            validate_dataset(changed, canonical_hash(changed))
        wrong = copy.deepcopy(self.r1)
        wrong["judgments"][0]["evidence_ids"] = [
            self.dataset["cases"][1]["facts"][0]["evidence_id"]
        ]
        with self.assertRaisesRegex(Stage2Error, "another case"):
            self.evaluate(r1=wrong)
        leaked = copy.deepcopy(self.dataset)
        leaked["cases"][0]["facts"][0]["allowed_scores"] = [1]
        with self.assertRaisesRegex(Stage2Error, "unexpected fact fields"):
            validate_dataset(leaked, canonical_hash(leaked))

    def test_observation_contract_retains_v10_and_rejects_leaks_or_mismatch(self):
        legacy, _ = fixtures("1.0.0")
        self.assertEqual(len(validate_dataset(legacy, canonical_hash(legacy))), 56)
        leaked = copy.deepcopy(self.dataset)
        leaked["cases"][0]["observation"]["allowed_scores"] = [1]
        with self.assertRaisesRegex(Stage2Error, "invalid observation"):
            validate_dataset(leaked, canonical_hash(leaked))
        changed = copy.deepcopy(self.dataset)
        changed["cases"][28]["observation"]["status"] = "unavailable"
        with self.assertRaisesRegex(Stage2Error, "variant observation"):
            validate_dataset(changed, canonical_hash(changed))
        unavailable = copy.deepcopy(self.dataset["cases"][0])
        unavailable["observation"]["status"] = "unavailable"
        with self.assertRaisesRegex(Stage2Error, "must remain unknown"):
            validate_judgment(self.r1["judgments"][0], unavailable)

    def test_binding_mismatch_fails_closed(self):
        wrong = copy.deepcopy(self.r2)
        wrong["bindings"]["code_sha256"] = "e" * 64
        with self.assertRaisesRegex(Stage2Error, "bindings mismatch"):
            self.evaluate(r2=wrong)
        wrong = copy.deepcopy(self.r1)
        wrong["bindings"]["guidance_sha256"] = "0" * 64
        with self.assertRaisesRegex(Stage2Error, "bindings mismatch"):
            self.evaluate(r1=wrong)

    def test_fake_native_batches_are_blinded_and_never_real_ready(self):
        calls = []

        def adapter(prompt, schema_path, output_dir, label, **options):
            lowered = prompt.lower()
            self.assertNotIn("allowed_scores", lowered)
            self.assertNotIn("reference_sha256", lowered)
            payload = json.loads(prompt.split("\n", 1)[1])
            self.assertEqual(payload["guidance"]["kind"], "Stage2JudgeGuidance")
            payload = payload["cases"]
            role = json.loads(Path(schema_path).read_text(encoding="utf-8"))[
                "properties"
            ]["role"]["const"]
            value = {
                "kind": "Stage2RubricQualityBatch",
                "schema_version": "1.0.0",
                "role": role,
                "judgments": [
                    {
                        "case_id": case["case_id"],
                        "status": "scored",
                        "score": 1,
                        "evidence_ids": [case["facts"][0]["evidence_id"]],
                        "reason": "supported",
                        "major_error": False,
                    }
                    for case in payload
                ],
            }
            options["semantic_validator"](value)
            calls.append((label, prompt))
            return value, {"test_adapter": True}

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "codex.exe"
            binary.write_bytes(b"synthetic executable")
            (root / "r1").mkdir()
            (root / "r2").mkdir()
            result = run_rubric_quality(
                self.dataset,
                self.reference,
                dataset_sha256=self.dataset_sha,
                reference_sha256=self.reference_sha,
                codex=binary,
                r1_home=root / "r1",
                r2_home=root / "r2",
                model="gpt-test",
                reasoning="medium",
                execution_policy={},
                output_dir=root / "out",
                call_adapter=adapter,
            )
        self.assertEqual(len(calls), 16)
        self.assertEqual(result["execution"]["completed_units"], 16)
        self.assertEqual(len(result["bindings"]["guidance_sha256"]), 64)
        self.assertEqual(result["evidence_class"], "injected-fake-test-only")
        self.assertFalse(result["quality_report"]["native_qa_pass"])
        self.assertFalse(result["quality_report"]["passed"])
        self.assertFalse(result["formal_ready"])

    def test_failure_preserves_partial_receipts_and_actual_counts(self):
        calls = []

        def adapter(prompt, schema_path, output_dir, label, **options):
            calls.append(label)
            if len(calls) == 2:
                raise ValueError("synthetic transport failure")
            payload = json.loads(prompt.split("\n", 1)[1])["cases"]
            role = json.loads(Path(schema_path).read_text(encoding="utf-8"))[
                "properties"
            ]["role"]["const"]
            value = {
                "kind": "Stage2RubricQualityBatch",
                "schema_version": "1.0.0",
                "role": role,
                "judgments": [
                    {
                        "case_id": case["case_id"],
                        "status": "scored",
                        "score": 1,
                        "evidence_ids": [case["facts"][0]["evidence_id"]],
                        "reason": "supported",
                        "major_error": False,
                    }
                    for case in payload
                ],
            }
            return value, {"test_adapter": True}

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "codex.exe"
            binary.write_bytes(b"synthetic executable")
            (root / "r1").mkdir()
            (root / "r2").mkdir()
            result = run_rubric_quality(
                self.dataset,
                self.reference,
                dataset_sha256=self.dataset_sha,
                reference_sha256=self.reference_sha,
                codex=binary,
                r1_home=root / "r1",
                r2_home=root / "r2",
                model="gpt-test",
                reasoning="medium",
                execution_policy={},
                output_dir=root / "out",
                call_adapter=adapter,
            )
            self.assertEqual(
                (
                    result["status"],
                    result["execution"]["started_units"],
                    result["execution"]["completed_units"],
                ),
                ("evaluator-failure", 2, 1),
            )
            self.assertEqual(result["evidence_class"], "injected-fake-test-only")
            self.assertEqual(len(result["unit_receipts"]), 1)
            self.assertTrue((root / "out" / "result.json").is_file())

    def test_missing_guidance_fails_before_adapter(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / "missing-guidance.json"
            with (
                mock.patch.object(live_quality, "GUIDANCE_PATH", missing),
                self.assertRaisesRegex(Stage2Error, "cannot load"),
            ):
                run_rubric_quality(
                    self.dataset,
                    self.reference,
                    dataset_sha256=self.dataset_sha,
                    reference_sha256=self.reference_sha,
                    codex=missing,
                    r1_home=missing,
                    r2_home=missing,
                    model="gpt-test",
                    reasoning="medium",
                    execution_policy={},
                    output_dir=Path(temp) / "out",
                    call_adapter=lambda *args, **kwargs: self.fail("must not dispatch"),
                )

    def test_native_attempt_count_uses_archived_transport_attempts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for label, count in (("r1-01", 2), ("r1-02-correction", 1)):
                archive = root / f"{label}.model-call"
                archive.mkdir()
                for number in range(1, count + 1):
                    (archive / f"attempt-{number:02d}.record.json").write_text(
                        "{}", encoding="utf-8"
                    )
            self.assertEqual(_archived_native_attempts(root, True), 3)
            self.assertEqual(_archived_native_attempts(root, False), 0)


if __name__ == "__main__":
    unittest.main()
