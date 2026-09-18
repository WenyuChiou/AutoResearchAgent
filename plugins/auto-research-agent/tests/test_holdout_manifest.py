"""Public synthetic tests for the private holdout contract."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = PLUGIN_ROOT / "evals"
sys.path.insert(0, str(PLUGIN_ROOT))

from validators.holdout_manifest import canonical_sha256, validate_manifest  # noqa: E402


def load(relative_path):
    return json.loads((EVAL_ROOT / relative_path).read_text(encoding="utf-8"))


class HoldoutManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load("schemas/holdout-manifest.v1.schema.json")
        Draft202012Validator.check_schema(cls.schema)
        cls.example = load("examples/holdout-manifest.synthetic.json")

    def test_synthetic_manifest_is_valid_and_hash_is_canonical(self):
        self.assertEqual(validate_manifest(self.example), [])
        reordered = json.loads(json.dumps(self.example, sort_keys=True))
        self.assertEqual(canonical_sha256(self.example), canonical_sha256(reordered))
        utf8_copy = deepcopy(self.example)
        utf8_copy["anchors"][0]["identity"]["title"] = "合成研究"
        parsed_with_whitespace = json.loads(json.dumps(utf8_copy, indent=4))
        self.assertEqual(
            canonical_sha256(utf8_copy), canonical_sha256(parsed_with_whitespace)
        )
        reordered_array = deepcopy(self.example)
        reordered_array["coverage_clusters"].reverse()
        self.assertNotEqual(
            canonical_sha256(self.example), canonical_sha256(reordered_array)
        )

    def test_manifest_covers_exact_frozen_clusters_and_roles(self):
        missing_role = deepcopy(self.example)
        missing_role["anchors"][0]["roles"].remove("validation")
        self.assertIn(
            "anchors must collectively cover all six curation roles",
            validate_manifest(missing_role),
        )

    def test_private_artifact_paths_reject_escape_and_ambiguous_segments(self):
        for path in (
            "answers/key.json",
            "../private/key.json",
            "private\\key.json",
            "private/../answer.json",
            "private/a/../../answer.json",
            "private//answer.json",
        ):
            invalid = deepcopy(self.example)
            invalid["answer_key"]["path"] = path
            self.assertTrue(validate_manifest(invalid), path)
        invalid_approval = deepcopy(self.example)
        invalid_approval["curation"]["human_approvals"][0]["approval_artifact"][
            "path"
        ] = "private/../approval.json"
        self.assertTrue(validate_manifest(invalid_approval))

    def test_frozen_manifest_needs_two_human_approvals(self):
        invalid = deepcopy(self.example)
        invalid["curation"]["human_approvals"] = invalid["curation"]["human_approvals"][
            :1
        ]
        self.assertIn(
            "a frozen manifest requires two human approvals",
            validate_manifest(invalid),
        )

    def test_raters_are_independent_and_disagreement_is_adjudicated(self):
        same_person = deepcopy(self.example)
        same_person["curation"]["actors"][2]["actor_id"] = "human-rater-a"
        self.assertIn(
            "curation actor_id values must be unique",
            validate_manifest(same_person),
        )
        disputed = deepcopy(self.example)
        disputed["anchors"][0]["anchor_type"] = "core"
        disputed["anchors"][0]["independent_ratings"][1]["decision"] = "exclude"
        self.assertIn(
            "synthetic-anchor-001 has unresolved rater disagreement",
            validate_manifest(disputed),
        )
        disputed["anchors"][0]["adjudication"] = {
            "adjudicator_id": "human-adjudicator-c",
            "decision": "include",
            "reason": "Synthetic adjudication resolves the disagreement.",
            "evidence_ids": ["synthetic-adjudication-evidence"],
            "decided_at": "2026-09-17T12:45:00-04:00",
        }
        self.assertNotIn(
            "synthetic-anchor-001 has unresolved rater disagreement",
            validate_manifest(disputed),
        )

    def test_final_anchor_decision_must_be_include(self):
        excluded = deepcopy(self.example)
        for rating in excluded["anchors"][0]["independent_ratings"]:
            rating["decision"] = "exclude"
        self.assertIn(
            "synthetic-anchor-001 final curation decision must be include",
            validate_manifest(excluded),
        )
        unnecessary = deepcopy(self.example)
        unnecessary["anchors"][0]["adjudication"] = {
            "adjudicator_id": "human-adjudicator-c",
            "decision": "include",
            "reason": "This should not exist for unanimous ratings.",
            "evidence_ids": ["synthetic-adjudication-evidence"],
            "decided_at": "2026-09-17T12:45:00-04:00",
        }
        self.assertIn(
            "synthetic-anchor-001 has unnecessary adjudication for unanimous ratings",
            validate_manifest(unnecessary),
        )

    def test_classic_rule_is_not_just_a_citation_count(self):
        too_recent = deepcopy(self.example)
        too_recent["anchors"][0]["identity"]["year"] = 2025
        self.assertIn(
            "synthetic-anchor-001 classic status contradicts the frozen rule",
            validate_manifest(too_recent),
        )

    def test_must_have_rule_requires_decision_critical_direct_evidence(self):
        substitute = deepcopy(self.example)
        substitute["anchors"][0]["importance"]["equally_direct_substitute"] = True
        self.assertIn(
            "synthetic-anchor-001 does not satisfy the aggregate must-have rule",
            validate_manifest(substitute),
        )
        rejected = deepcopy(self.example)
        rejected["anchors"][0]["independent_ratings"][1]["must_have_assessment"][
            "directness"
        ] = 1
        self.assertIn(
            "synthetic-anchor-001 needs two passing must-have rater confirmations",
            validate_manifest(rejected),
        )

    def test_frozen_timestamps_are_ordered(self):
        invalid = deepcopy(self.example)
        invalid["frozen_at"] = "2026-09-17T11:00:00-04:00"
        self.assertIn(
            "frozen_at must not precede created_at", validate_manifest(invalid)
        )
        late_approval = deepcopy(self.example)
        late_approval["curation"]["human_approvals"][0]["approved_at"] = (
            "2026-09-17T14:00:00-04:00"
        )
        self.assertTrue(
            any(
                "must occur between creation and freeze" in error
                for error in validate_manifest(late_approval)
            )
        )


if __name__ == "__main__":
    unittest.main()
