"""Exercise the frozen three-pair A/B decision runner."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator, FormatChecker


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = PLUGIN_ROOT / "evals"
sys.path.insert(0, str(PLUGIN_ROOT))

from validators.holdout_manifest import canonical_sha256  # noqa: E402
from validators.paired_evaluation import (  # noqa: E402
    _close_ordinal,
    _compare,
    _distribution,
    evaluate_request,
)


def load(relative_path):
    return json.loads((EVAL_ROOT / relative_path).read_text(encoding="utf-8"))


class PairedEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load("schemas/paired-evaluation-request.v1.schema.json")
        Draft202012Validator.check_schema(cls.schema)
        cls.schema_validator = Draft202012Validator(
            cls.schema, format_checker=FormatChecker()
        )
        cls.plan = load("examples/evaluation-plan.synthetic.json")
        cls.base_r1 = load("examples/rubric-judge-result-stage1-r1.synthetic.json")
        cls.configs = {item["role"]: item for item in cls.plan["judge_configs"]}
        (EVAL_ROOT / "private").mkdir(exist_ok=True)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=EVAL_ROOT / "private")
        self.temp_path = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write_json(self, name, value):
        path = self.temp_path / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return {
            "path": path.relative_to(EVAL_ROOT).as_posix(),
            "canonical_sha256": canonical_sha256(value),
        }

    def write_bytes(self, name, value):
        path = self.temp_path / name
        path.write_bytes(value)
        return {
            "path": path.relative_to(EVAL_ROOT).as_posix(),
            "sha256": hashlib.sha256(value).hexdigest(),
        }

    @staticmethod
    def set_metric_score(result, metric_id, score):
        rows = [
            row for row in result["metric_results"] if row["metric_id"] == metric_id
        ]
        for row in rows:
            row["score"] = score
            if score == 1:
                row["criterion_results"][0]["outcome"] = "partial"
            elif score == 0:
                row["hard_fact_status"] = "fail"
                row["criterion_results"][0]["outcome"] = "fail"

    def judge_result(self, run_id, subject, role, scores, major_error=False):
        result = deepcopy(self.base_r1)
        result["evaluation_id"] = f"eval-{run_id}-{role}"
        result["run_id"] = run_id
        result["subject_artifact"] = subject
        result["created_at"] = "2026-09-17T16:00:00-04:00"
        config = self.configs[role]
        result["judge"] = {
            "role": role,
            "model": config["model_id"],
            "reasoning": config["reasoning"],
            "config_id": config["config_id"],
            "prompt_sha256": config["prompt_sha256"],
            "evaluation_config_sha256": config["evaluation_config_sha256"],
            "execution_context_id": config["execution_context_id"],
            "condition_blinded": True,
        }
        for metric_id, score in scores.items():
            self.set_metric_score(result, metric_id, score)
        if major_error:
            row = next(
                row for row in result["metric_results"] if row["metric_id"] == "P2"
            )
            row["major_error_ids"] = ["P2.ME.OMITTED_CLOSEST_WORK"]
            row["score"] = 0
            row["hard_fact_status"] = "fail"
            row["criterion_results"][0]["outcome"] = "fail"
            row["needs_human_review"] = True
            result["audit_trigger_ids"] = ["major-error"]
            result["requires_human_audit"] = True
        return result

    def bundle(self, run_id, subject_id, scores, major_error=False):
        subject = self.write_bytes(
            f"subject-{run_id}.json", json.dumps({"run_id": run_id}).encode()
        )
        r1 = self.judge_result(run_id, subject, "auto-r1", scores, major_error)
        r2 = self.judge_result(run_id, subject, "auto-r2", scores, major_error)
        r1_ref = self.write_json(f"judge-{run_id}-r1.json", r1)
        r2_ref = self.write_json(f"judge-{run_id}-r2.json", r2)
        plan_ref = {
            "path": "examples/evaluation-plan.synthetic.json",
            "canonical_sha256": canonical_sha256(self.plan),
        }
        audit = None
        status = "agreed"
        if major_error:
            audit = {
                "audit_id": f"audit-{run_id}",
                "actor_id": "human-organizer-a",
                "actor_type": "human",
                "attestation_ref": "course-roster:organizer-a",
                "reviewed_evaluation_ids": [r1["evaluation_id"], r2["evaluation_id"]],
                "decision": "accept-selected",
                "reason": "Synthetic accepted major-error classification.",
                "artifact": self.write_bytes(f"judge-audit-{run_id}.json", b"{}"),
                "completed_at": "2026-09-17T16:05:00-04:00",
            }
            status = "completed"
        bundle = {
            "kind": "JudgeBundle",
            "schema_version": "1.0.0",
            "bundle_id": f"bundle-{run_id}",
            "plan": {"plan_id": self.plan["plan_id"], "artifact": plan_ref},
            "run_id": run_id,
            "subject_id": subject_id,
            "subject_artifact": subject,
            "artifacts": {
                "auto_r1": r1_ref,
                "auto_r2": r2_ref,
                "auto_adj": None,
                "human_audit": audit,
            },
            "status": status,
            "selected_evaluation_id": r1["evaluation_id"],
            "usable_for_pairing": True,
            "created_at": "2026-09-17T16:10:00-04:00",
        }
        return bundle, self.write_json(f"bundle-{run_id}.json", bundle)

    def request(
        self, treatment_scores=None, include_pair_audits=True, major_error=False
    ):
        treatment_scores = treatment_scores or {"P1": 2, "P2": 2, "P3": 2}
        bundle_refs = []
        bundles = {}
        scores_by_run = {}
        for repeat in self.plan["paired_repeats"]:
            for condition in ("baseline", "treatment"):
                run = repeat[condition]
                if condition == "baseline":
                    scores = {"P1": 2, "P2": 1, "P3": 1}
                elif all(isinstance(key, int) for key in treatment_scores):
                    scores = treatment_scores[repeat["repeat"]]
                else:
                    scores = treatment_scores
                bundle, ref = self.bundle(
                    run["run_id"],
                    run["subject_id"],
                    scores,
                    major_error and condition == "treatment",
                )
                bundles[run["run_id"]] = bundle
                scores_by_run[run["run_id"]] = scores
                bundle_refs.append(ref)
        audits = []
        if include_pair_audits:
            for repeat in self.plan["paired_repeats"]:
                for metric_id in ("P1", "P2", "P3"):
                    baseline = bundles[repeat["baseline"]["run_id"]]
                    treatment = bundles[repeat["treatment"]["run_id"]]
                    before = scores_by_run[repeat["baseline"]["run_id"]][metric_id]
                    after = scores_by_run[repeat["treatment"]["run_id"]][metric_id]
                    if abs(after - before) != 1:
                        continue
                    # fmt: off
                    audits.append(
                        {
                            "audit_id": f"pair-audit-{repeat['repeat']}-{metric_id}", "repeat": repeat["repeat"], "metric_id": metric_id,
                            "actor_id": "human-organizer-a", "actor_type": "human",
                            "attestation_ref": "course-roster:organizer-a",
                            "reviewed_bundle_ids": [baseline["bundle_id"], treatment["bundle_id"]], "decision": "accept-comparison",
                            "reason": "Synthetic close-pair comparison follows the rubric.",
                            "artifact": self.write_bytes(f"pair-audit-{repeat['repeat']}-{metric_id}.json", b"{}"),
                            "completed_at": "2026-09-17T16:20:00-04:00",
                        }
                    )
                    # fmt: on
        # fmt: off
        run_costs = [{"run_id": run_id, "runtime_seconds": 10, "tool_calls": 2, "model_calls": 1, "human_interventions": 0, "cost_usd": None} for run_id in bundles]
        runtime_hash = canonical_sha256(self.plan["subject_runtime"])
        run_attestations = []
        for repeat in self.plan["paired_repeats"]:
            for condition in ("baseline", "treatment"):
                run = repeat[condition]
                build = self.plan["bindings"][f"{condition}_build"]
                run_attestations.append(
                    {
                        "run_id": run["run_id"], "subject_id": run["subject_id"], "condition": condition,
                        "build_version_id": build["version_id"], "core_revision": build["core_revision"],
                        "extension_revision": build["extension_revision"], "reviewed_diff_sha256": build["reviewed_diff_sha256"],
                        "runtime_profile_sha256": runtime_hash, "prompt_sha256": self.plan["bindings"]["prompt"]["artifact"]["sha256"],
                        "condition_map_sha256": self.plan["bindings"]["condition_map"]["sha256"],
                        "subject_artifact": bundles[run["run_id"]]["subject_artifact"],
                        "artifact_bytes_attested": True, "process_boundary_attested": True, "attestor_id": "synthetic-runner",
                        "attestation_artifact": self.write_bytes(f"run-attestation-{run['run_id']}.json", b"{}"),
                        "created_at": "2026-09-17T16:08:00-04:00",
                    }
                )
        return {
            "kind": "PairedEvaluationRequest",
            "schema_version": "1.0.0",
            "request_id": "paired-synthetic-v1",
            "plan": {
                "path": "examples/evaluation-plan.synthetic.json",
                "canonical_sha256": canonical_sha256(self.plan),
            },
            "bundles": bundle_refs,
            "pair_audits": audits,
            "run_attestations": run_attestations,
            "run_costs": run_costs,
            "created_at": "2026-09-17T17:00:00-04:00",
        }
        # fmt: on

    def test_two_target_improvements_no_regression_is_improved(self):
        request = self.request()
        self.schema_validator.validate(request)
        result, errors = evaluate_request(request)
        self.assertEqual(errors, [])
        self.assertEqual(result["decision"], "improved")
        self.assertFalse(result["external_claim_ready"])
        self.assertEqual(result["request_canonical_sha256"], canonical_sha256(request))
        self.assertEqual(result["bundle_bindings"], request["bundles"])
        self.assertEqual(
            {item["metric_id"] for item in result["metric_decisions"]},
            {"P1", "P2", "P3"},
        )

    def test_missing_close_pair_audits_is_inconclusive(self):
        result, errors = evaluate_request(self.request(include_pair_audits=False))
        self.assertEqual(errors, [])
        self.assertEqual(result["decision"], "inconclusive")
        self.assertTrue(
            any(row["direction"] == "audit-required" for row in result["pair_results"])
        )

    def test_target_regression_and_added_major_error_are_not_improved(self):
        request = self.request(
            treatment_scores={"P1": 2, "P2": 0, "P3": 2}, major_error=True
        )
        result, errors = evaluate_request(request)
        self.assertEqual(errors, [])
        self.assertEqual(result["decision"], "not-improved")
        self.assertEqual(len(result["added_major_errors"]), 3)

    def test_stage2_distribution_changes_are_close_and_conservative(self):
        baseline = {"direction_distribution": _distribution([0, 1])}
        treatment = {"direction_distribution": _distribution([0, 2])}
        self.assertEqual(_compare(baseline, treatment), "improved")
        self.assertTrue(_close_ordinal(baseline, treatment))
        mixed = deepcopy(treatment)
        mixed["direction_distribution"]["minimum"] = -1
        self.assertEqual(_compare(baseline, mixed), "regressed")

    def test_two_improvements_one_same_and_non_target_regression(self):
        per_repeat = {
            1: {"P1": 2, "P2": 2, "P3": 2},
            2: {"P1": 2, "P2": 2, "P3": 2},
            3: {"P1": 2, "P2": 1, "P3": 2},
        }
        result, errors = evaluate_request(self.request(treatment_scores=per_repeat))
        self.assertEqual(errors, [])
        self.assertEqual(result["decision"], "improved")

        result, errors = evaluate_request(
            self.request(treatment_scores={"P1": 1, "P2": 2, "P3": 2})
        )
        self.assertEqual(errors, [])
        self.assertEqual(result["decision"], "not-improved")

    def test_rejected_audit_and_bad_attestation_fail_closed(self):
        request = self.request()
        request["pair_audits"][0]["decision"] = "reject"
        result, errors = evaluate_request(request)
        self.assertEqual(errors, [])
        self.assertEqual(result["decision"], "inconclusive")

        request = self.request()
        request["run_attestations"][0]["condition"] = "treatment"
        result, errors = evaluate_request(request)
        self.assertIsNone(result)
        self.assertTrue(any("attestation condition" in error for error in errors))

    def test_draft_plan_is_rejected_without_exception(self):
        draft = deepcopy(self.plan)
        draft["status"] = "draft"
        draft["frozen_at"] = None
        request = self.request()
        request["plan"] = self.write_json("draft-plan.json", draft)
        result, errors = evaluate_request(request)
        self.assertIsNone(result)
        self.assertIn("paired evaluation requires a frozen plan", errors)


if __name__ == "__main__":
    unittest.main()
