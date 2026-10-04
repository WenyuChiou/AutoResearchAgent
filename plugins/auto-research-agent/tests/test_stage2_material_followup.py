"""Opt-in material partial checks preserve legacy and unmeasured-effect behavior."""

import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage2_common import Stage2Error
from stage2_live.controller import _followups

POLICY = {
    "kind": "Stage2FollowupPolicy",
    "schema_version": "2.0.0",
    "investigate_material_partial": True,
}


class MaterialFollowupTests(unittest.TestCase):
    def setUp(self):
        self.assessment = {
            "checks": {
                "materials": {
                    "status": "assessed",
                    "score": 1,
                    "blocking": False,
                    "next_check": "Inspect the variable linkage dictionary.",
                }
            },
            "disposition": "revise",
            "next_step": "Find a linkable alternative.",
            "scope_change_requested": False,
            "reason": "Linkage could change selection.",
        }
        self.input = {
            "candidates": [
                {
                    "candidate_id": "candidate-1",
                    "candidate_version": 2,
                    "reconciliation": {"assessment": self.assessment},
                }
            ]
        }

    def test_partial_material_check_routes_without_changing_legacy(self):
        self.assertEqual(_followups(self.input), [])
        result = _followups(self.input, POLICY)
        self.assertEqual(
            result[0]["missing_evidence"],
            [
                "Find a linkable alternative.",
                "Inspect the variable linkage dictionary.",
            ],
        )
        self.assertEqual(result[0]["candidate_version"], 2)

    def test_counterevidence_routes_when_repair_changes_selection(self):
        self.assessment["checks"]["materials"]["score"] = 0
        self.assertTrue(_followups(self.input, POLICY))
        self.assessment["disposition"] = "reject"
        self.assertEqual(_followups(self.input, POLICY), [])

    def test_new_method_unmeasured_effect_does_not_require_proven_success(self):
        self.assessment.update(disposition="recommend", next_step=None)
        self.assessment["checks"]["materials"].update(
            status="unknown",
            score=None,
            next_check="Measure method effectiveness during the proposed study.",
        )
        self.assertEqual(_followups(self.input, POLICY), [])

    def test_unknown_enabling_evidence_still_blocks_legacy_and_new(self):
        self.assessment["checks"]["materials"].update(
            status="unknown", score=None, blocking=True
        )
        self.assessment["next_step"] = None
        self.assertEqual(_followups(self.input), _followups(self.input, POLICY))

    def test_missing_reviewer_does_not_create_followup_approval(self):
        partial = copy.deepcopy(self.input)
        partial["candidates"][0]["reconciliation"] = {"status": "pending-review"}
        self.assertEqual(_followups(partial, POLICY), [])
        with self.assertRaises(Stage2Error):
            _followups(self.input, {**POLICY, "schema_version": "1.0.0"})

    def test_numeric_truth_does_not_enable_explicit_opt_in(self):
        for value in (1, 1.0, False, [], None):
            with self.subTest(value=value):
                with self.assertRaises(Stage2Error):
                    _followups(
                        self.input, {**POLICY, "investigate_material_partial": value}
                    )
