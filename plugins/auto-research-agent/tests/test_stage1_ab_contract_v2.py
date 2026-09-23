"""Reject false six-cluster counts and non-independent holdout curation."""

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

from validators.holdout_manifest_v2 import validate_manifest_v2  # noqa: E402
from validators.holdout_manifest import canonical_sha256  # noqa: E402
from validators.evaluation_plan import validate_plan  # noqa: E402
from validators.stage1_evaluation_result_v2 import validate_result_v2  # noqa: E402


def load(relative_path):
    return json.loads((EVAL_ROOT / relative_path).read_text(encoding="utf-8"))


class Stage1ABContractV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Draft202012Validator.check_schema(
            load("schemas/holdout-manifest.v2.schema.json")
        )
        Draft202012Validator.check_schema(
            load("schemas/stage1-evaluation-result.v2.schema.json")
        )
        cls.holdout = load("examples/holdout-manifest-v2.synthetic.json")
        cls.plan = load("examples/evaluation-plan-v2.synthetic.json")
        cls.result = load("examples/stage1-evaluation-result-v2.synthetic.json")

    def test_public_synthetic_contract_is_valid_but_not_scientific_evidence(self):
        self.assertEqual(validate_manifest_v2(self.holdout), [])
        self.assertEqual(validate_result_v2(self.result, self.holdout, self.plan), [])
        self.assertEqual(self.holdout["use_class"], "synthetic")
        self.assertNotIn("judgment_scores", self.result)

    def test_count_result_does_not_force_unneeded_adjudication(self):
        with_judge_scores = deepcopy(self.result)
        with_judge_scores["judgment_scores"] = {"P1": {"ADJ": 1}}
        self.assertTrue(validate_result_v2(with_judge_scores, self.holdout, self.plan))

    def test_missing_use_class_or_approval_is_rejected(self):
        missing_class = deepcopy(self.holdout)
        missing_class.pop("use_class")
        self.assertTrue(validate_manifest_v2(missing_class))
        one_approval = deepcopy(self.holdout)
        one_approval["curation"]["human_approvals"].pop()
        self.assertIn(
            "a frozen manifest requires approval from both raters",
            validate_manifest_v2(one_approval),
        )

    def test_disputed_anchor_cannot_be_counted_as_included(self):
        disputed = deepcopy(self.holdout)
        disputed["anchors"][0]["independent_ratings"][1]["decision"] = "exclude"
        self.assertIn(
            "synthetic-anchor-001 requires unanimous inclusion",
            validate_manifest_v2(disputed),
        )

    def test_disagreement_is_preserved_outside_anchors(self):
        recorded = deepcopy(self.holdout)
        item = {
            "candidate_id": "synthetic-disputed-002",
            "identity": {
                "title": "Disputed synthetic study",
                "authors": ["Example Author"],
                "year": 2020,
                "venue_or_version": "Synthetic fixture",
                "doi_or_url": "https://example.invalid/synthetic-disputed-002",
            },
            "independent_ratings": deepcopy(
                recorded["anchors"][0]["independent_ratings"]
            ),
            "exclusion_reason": "Independent raters disagreed; excluded by v2 policy.",
        }
        item["independent_ratings"][1]["decision"] = "exclude"
        recorded["disagreements"].append(item)
        self.assertEqual(validate_manifest_v2(recorded), [])
        item["independent_ratings"][1]["decision"] = "include"
        self.assertIn(
            "synthetic-disputed-002 must preserve an actual rater disagreement",
            validate_manifest_v2(recorded),
        )

    def test_private_answer_and_screening_paths_cannot_escape(self):
        for field in ("answer_key", "candidate_screening_log"):
            escaped = deepcopy(self.holdout)
            escaped[field]["path"] = "private/../answers.json"
            self.assertTrue(validate_manifest_v2(escaped), field)

    def test_six_cluster_and_frozen_anchor_denominators_are_bound(self):
        wrong_cluster = deepcopy(self.result)
        wrong_cluster["fact_metrics"]["coverage"]["clusters_total"] = 4
        self.assertTrue(validate_result_v2(wrong_cluster, self.holdout, self.plan))
        wrong_core = deepcopy(self.result)
        wrong_core["fact_metrics"]["coverage"]["core_total"] = 10
        self.assertIn(
            "core_total must equal the frozen core-anchor count",
            validate_result_v2(wrong_core, self.holdout, self.plan),
        )
        wrong_must_have = deepcopy(self.result)
        wrong_must_have["fact_metrics"]["coverage"]["must_have_total"] = 2
        self.assertIn(
            "must_have_total must equal the frozen must-have count",
            validate_result_v2(wrong_must_have, self.holdout, self.plan),
        )

    def test_historical_v1_result_is_not_reinterpreted_as_v2(self):
        legacy = load("examples/stage1-evaluation-result.synthetic.json")
        self.assertTrue(validate_result_v2(legacy, self.holdout, self.plan))

    def test_result_rejects_changed_answer_key_under_same_manifest_id(self):
        changed = deepcopy(self.holdout)
        changed["answer_key"]["sha256"] = "1" * 64
        self.assertIn(
            "evaluation plan must bind these exact holdout bytes",
            validate_result_v2(self.result, changed, self.plan),
        )
        changed_result = deepcopy(self.result)
        changed_result["holdout_sha256"] = "1" * 64
        self.assertIn(
            "result holdout_sha256 must match these exact holdout bytes",
            validate_result_v2(changed_result, self.holdout, self.plan),
        )

    def test_v2_holdout_cannot_claim_the_historical_v1_case(self):
        wrong_case = deepcopy(self.holdout)
        wrong_case["case_id"] = "aging-bidirectional-development-v1"
        self.assertTrue(validate_manifest_v2(wrong_case))

    def test_rehash_tamper_rejected_for_v2_holdout_binding(self):
        plan = deepcopy(self.plan)
        holdout = deepcopy(self.holdout)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            dir=EVAL_ROOT / "examples",
            delete=False,
        ) as handle:
            json.dump(holdout, handle)
            path = Path(handle.name)
        try:
            plan["bindings"]["holdout"] = {
                "manifest_id": holdout["manifest_id"],
                "use_class": holdout["use_class"],
                "path": path.relative_to(EVAL_ROOT).as_posix(),
                "canonical_sha256": canonical_sha256(holdout),
            }
            self.assertEqual(validate_plan(plan), [])
            plan["bindings"]["holdout"]["canonical_sha256"] = "0" * 64
            self.assertIn(
                "holdout canonical_sha256 does not match the bound artifact",
                validate_plan(plan),
            )
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
