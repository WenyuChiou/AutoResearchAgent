"""Synthetic tests for freezing a reproducible paired evaluation plan."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = PLUGIN_ROOT / "evals"
sys.path.insert(0, str(PLUGIN_ROOT))

from validators.evaluation_plan import validate_plan  # noqa: E402
from validators.holdout_manifest import canonical_sha256  # noqa: E402


def load(relative_path):
    return json.loads((EVAL_ROOT / relative_path).read_text(encoding="utf-8"))


def bind_modified_holdout(plan, mutate, private=False):
    holdout = load("examples/holdout-manifest.synthetic.json")
    mutate(holdout)
    folder = EVAL_ROOT / ("private" if private else "examples")
    folder.mkdir(exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".json", dir=folder, delete=False
    )
    with handle:
        json.dump(holdout, handle)
    path = Path(handle.name)
    binding = plan["bindings"]["holdout"]
    binding.update(
        {
            "path": path.relative_to(EVAL_ROOT).as_posix(),
            "manifest_id": holdout["manifest_id"],
            "use_class": holdout["use_class"],
            "canonical_sha256": canonical_sha256(holdout),
        }
    )
    return path


class EvaluationPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load("schemas/evaluation-plan.v1.schema.json")
        Draft202012Validator.check_schema(cls.schema)
        cls.example = load("examples/evaluation-plan.synthetic.json")

    def test_frozen_synthetic_plan_is_valid(self):
        self.assertEqual(validate_plan(self.example), [])

    def test_stage_metrics_and_targets_are_bound(self):
        wrong_stage = deepcopy(self.example)
        wrong_stage["stage"] = 2
        self.assertIn(
            "metric_ids must exactly match the selected stage",
            validate_plan(wrong_stage),
        )
        wrong_target = deepcopy(self.example)
        wrong_target["target_metric_ids"] = ["P4"]
        self.assertIn(
            "target_metric_ids must be a nonempty subset of stage metrics",
            validate_plan(wrong_target),
        )

    def test_rubric_catalog_and_holdout_hashes_are_verified(self):
        for path, value, expected in (
            (
                ("bindings", "rubric", "canonical_sha256"),
                "0" * 64,
                "rubric canonical_sha256 does not match the loaded rubric",
            ),
            (
                ("bindings", "criterion_catalog", "record_count"),
                85,
                "criterion catalog record_count does not match the rubric",
            ),
            (
                ("bindings", "capability_registry", "canonical_sha256"),
                "0" * 64,
                "capability registry hash does not match the loaded registry",
            ),
            (
                ("bindings", "holdout", "canonical_sha256"),
                "0" * 64,
                "holdout canonical_sha256 does not match the bound artifact",
            ),
        ):
            invalid = deepcopy(self.example)
            invalid[path[0]][path[1]][path[2]] = value
            self.assertIn(expected, validate_plan(invalid))

    def test_paths_reject_escape_and_formal_holdout_is_private(self):
        escaped = deepcopy(self.example)
        escaped["bindings"]["condition_map"]["path"] = "private/../map.json"
        self.assertTrue(
            any("condition map" in error for error in validate_plan(escaped))
        )
        formal = deepcopy(self.example)
        formal["execution_class"] = "formal"
        self.assertIn(
            "a formal plan requires a private holdout path",
            validate_plan(formal),
        )
        bad_approval = deepcopy(self.example)
        bad_approval["human_approvals"][0]["artifact"]["path"] = "public/a.json"
        self.assertIn(
            "approval 0 artifact must stay under private/",
            validate_plan(bad_approval),
        )

    def test_holdout_must_be_frozen_and_match_case_cutoff_and_use(self):
        cases = (
            (
                lambda value: value.update({"status": "draft", "frozen_at": None}),
                False,
                "an evaluation plan requires a frozen holdout",
            ),
            (
                lambda value: value.update({"case_id": "other-case"}),
                False,
                "holdout case_id must match the evaluation case",
            ),
            (
                lambda value: value.update({"cutoff_date": "2026-09-16"}),
                False,
                "holdout cutoff must match the subject data cutoff",
            ),
            (
                lambda value: None,
                True,
                "a formal plan requires a scientific-use holdout",
            ),
        )
        for mutate, formal, expected in cases:
            plan = deepcopy(self.example)
            plan["execution_class"] = "formal" if formal else "synthetic"
            path = bind_modified_holdout(plan, mutate, private=formal)
            try:
                self.assertIn(expected, validate_plan(plan))
            finally:
                path.unlink()

    def test_baseline_and_treatment_are_distinct(self):
        baseline_extension = deepcopy(self.example)
        baseline_extension["bindings"]["baseline_build"]["capability_ids"] = [
            "skill:stage1-literature"
        ]
        self.assertIn(
            "baseline build must not load custom research capabilities",
            validate_plan(baseline_extension),
        )
        different_core = deepcopy(self.example)
        different_core["bindings"]["treatment_build"]["core_revision"] = "3" * 40
        self.assertIn(
            "baseline and treatment must share the stock core revision",
            validate_plan(different_core),
        )
        unknown = deepcopy(self.example)
        unknown["bindings"]["treatment_build"]["capability_ids"] = ["validator:unknown"]
        self.assertIn(
            "treatment build names an unknown capability", validate_plan(unknown)
        )
        unrelated = deepcopy(self.example)
        unrelated["target_metric_ids"] = ["P1"]
        self.assertIn(
            "every target metric must be covered by a treatment capability",
            validate_plan(unrelated),
        )

    def test_three_judges_are_independent_and_blinded(self):
        duplicate = deepcopy(self.example)
        duplicate["judge_configs"][1]["config_id"] = duplicate["judge_configs"][0][
            "config_id"
        ]
        self.assertIn("judge config IDs must be unique", validate_plan(duplicate))
        different_rater_prompt = deepcopy(self.example)
        different_rater_prompt["judge_configs"][1]["prompt_sha256"] = "f" * 64
        self.assertIn(
            "Auto-R1 and Auto-R2 must share the same prompt_sha256",
            validate_plan(different_rater_prompt),
        )
        same_adjudicator_prompt = deepcopy(self.example)
        same_adjudicator_prompt["judge_configs"][2]["prompt_sha256"] = (
            same_adjudicator_prompt["judge_configs"][0]["prompt_sha256"]
        )
        self.assertIn(
            "Auto-ADJ must use its separately versioned prompt",
            validate_plan(same_adjudicator_prompt),
        )
        different_config = deepcopy(self.example)
        different_config["judge_configs"][1]["evaluation_config_sha256"] = "f" * 64
        self.assertIn(
            "Auto-R1 and Auto-R2 must share the evaluation config hash",
            validate_plan(different_config),
        )
        same_context = deepcopy(self.example)
        same_context["judge_configs"][1]["execution_context_id"] = same_context[
            "judge_configs"
        ][0]["execution_context_id"]
        self.assertIn(
            "judge execution context IDs must be unique", validate_plan(same_context)
        )
        unblinded = deepcopy(self.example)
        unblinded["judge_configs"][0]["condition_blinded"] = False
        self.assertTrue(validate_plan(unblinded))

    def test_pair_order_ids_and_condition_blinding_are_fixed(self):
        wrong_order = deepcopy(self.example)
        wrong_order["paired_repeats"][1]["order"].reverse()
        self.assertIn(
            "paired repeat order must alternate B-T, T-B, B-T",
            validate_plan(wrong_order),
        )
        duplicate = deepcopy(self.example)
        duplicate["paired_repeats"][1]["baseline"]["run_id"] = duplicate[
            "paired_repeats"
        ][0]["baseline"]["run_id"]
        self.assertIn("all paired run IDs must be unique", validate_plan(duplicate))
        leaked = deepcopy(self.example)
        leaked["paired_repeats"][0]["baseline"]["subject_id"] = "baseline-subject"
        self.assertIn(
            "blinded subject IDs must use opaque random identifiers",
            validate_plan(leaked),
        )

    def test_frozen_plan_requires_two_ordered_human_approvals(self):
        one_approval = deepcopy(self.example)
        one_approval["human_approvals"] = one_approval["human_approvals"][:1]
        self.assertIn(
            "a frozen evaluation plan requires two human approvals",
            validate_plan(one_approval),
        )
        late = deepcopy(self.example)
        late["human_approvals"][0]["approved_at"] = "2026-09-17T16:00:00-04:00"
        self.assertTrue(
            any(
                "must occur between creation and freeze" in error
                for error in validate_plan(late)
            )
        )

    def test_decision_constants_fail_closed_in_schema(self):
        for field, value in (
            ("minimum_pairs_improved_per_target", 1),
            ("allow_target_regression", True),
            ("no_composite_total", False),
            ("statistical_claim", "significant"),
        ):
            invalid = deepcopy(self.example)
            invalid["decision_rule"][field] = value
            self.assertTrue(validate_plan(invalid), field)

    def test_fixed_time_limit_requires_a_value(self):
        invalid = deepcopy(self.example)
        invalid["subject_runtime"]["time_limit_policy"] = "fixed-limit"
        self.assertIn(
            "fixed-limit runtime requires fixed_limit_seconds",
            validate_plan(invalid),
        )


if __name__ == "__main__":
    unittest.main()
