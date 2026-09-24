"""Single-human curation remains explicit and cannot impersonate a second rater."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = PLUGIN_ROOT / "evals"
sys.path.insert(0, str(PLUGIN_ROOT))

from validators.evaluation_plan import validate_plan  # noqa: E402
from validators.holdout_manifest import canonical_sha256  # noqa: E402
from validators.holdout_manifest_v2 import (  # noqa: E402
    SCHEMA_VALIDATOR,
    validate_manifest_v2,
)
from validators.stage1_evaluation_result_v2 import validate_result_v2  # noqa: E402


def load(name):
    return json.loads((EVAL_ROOT / "examples" / name).read_text(encoding="utf-8"))


class SingleHumanContractTests(unittest.TestCase):
    def setUp(self):
        self.holdout = load("holdout-manifest-v2_1.synthetic.json")
        self.plan = load("evaluation-plan-v2_1.synthetic.json")

    def test_one_real_curator_and_one_plan_approval_are_valid(self):
        self.assertEqual(validate_manifest_v2(self.holdout), [])
        self.assertEqual(validate_plan(self.plan), [])
        self.assertEqual(len(self.holdout["curation"]["actors"]), 1)
        self.assertFalse(self.holdout["curation"]["independent_rating"])

    def test_single_human_result_uses_existing_hard_count_validator(self):
        result = load("stage1-evaluation-result-v2.synthetic.json")
        result["benchmark_version"] = self.holdout["manifest_id"]
        result["metric_spec_version"] = "stage1-primary-metrics-v2.1"
        result["holdout_sha256"] = canonical_sha256(self.holdout)
        result["evaluation_plan_sha256"] = canonical_sha256(self.plan)
        self.assertEqual(validate_result_v2(result, self.holdout, self.plan), [])
        result["metric_spec_version"] = "stage1-primary-metrics-v2"
        self.assertIn(
            "metric_spec_version does not match the holdout protocol",
            validate_result_v2(result, self.holdout, self.plan),
        )

    def test_missing_or_false_second_signature_cannot_pass(self):
        missing = deepcopy(self.holdout)
        missing["curation"]["human_approvals"] = []
        self.assertIn(
            "a frozen manifest requires approval from the sole rater",
            validate_manifest_v2(missing),
        )
        doubled = deepcopy(self.holdout)
        doubled["anchors"][0]["independent_ratings"].append(
            deepcopy(doubled["anchors"][0]["independent_ratings"][0])
        )
        self.assertTrue(validate_manifest_v2(doubled))

    def test_schema_keeps_two_rater_shape_for_v2_0(self):
        legacy = deepcopy(self.holdout)
        legacy["schema_version"] = "2.0.0"
        self.assertTrue(list(SCHEMA_VALIDATOR.iter_errors(legacy)))
        self.assertEqual(list(SCHEMA_VALIDATOR.iter_errors(self.holdout)), [])

    def test_duplicate_curator_record_is_rejected(self):
        duplicated = deepcopy(self.holdout)
        duplicated["curation"]["actors"].append(
            deepcopy(duplicated["curation"]["actors"][0])
        )
        self.assertTrue(validate_manifest_v2(duplicated))

    def test_single_human_protocol_rejects_fake_independence_and_disagreement(self):
        fake_independent = deepcopy(self.holdout)
        fake_independent["curation"]["independent_rating"] = True
        self.assertTrue(
            any(
                error.startswith("schema:curation/independent_rating:")
                for error in validate_manifest_v2(fake_independent)
            )
        )
        disputed = deepcopy(self.holdout)
        disputed["disagreements"].append(
            {
                "candidate_id": "fake-dispute",
                "identity": deepcopy(disputed["anchors"][0]["identity"]),
                "independent_ratings": [
                    deepcopy(disputed["anchors"][0]["independent_ratings"][0]),
                    deepcopy(disputed["anchors"][0]["independent_ratings"][0]),
                ],
                "exclusion_reason": "There is no second curator.",
            }
        )
        self.assertTrue(validate_manifest_v2(disputed))

    def test_plan_approval_must_match_the_curator(self):
        wrong = deepcopy(self.plan)
        wrong["human_approvals"][0]["actor_id"] = "pretend-second-human"
        self.assertIn(
            "a single-human plan requires its curator's one approval",
            validate_plan(wrong),
        )
        wrong_attestation = deepcopy(self.plan)
        wrong_attestation["human_approvals"][0]["attestation_ref"] = (
            "course-roster:someone-else"
        )
        self.assertIn(
            "a single-human plan approval must match curator attestation",
            validate_plan(wrong_attestation),
        )

    def test_legacy_two_rater_manifest_does_not_accept_one_rater(self):
        legacy = deepcopy(self.holdout)
        legacy["schema_version"] = "2.0.0"
        self.assertTrue(
            any(
                error.startswith("schema:curation/actors:")
                for error in validate_manifest_v2(legacy)
            )
        )


if __name__ == "__main__":
    unittest.main()
