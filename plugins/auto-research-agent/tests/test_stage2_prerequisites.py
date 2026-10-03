"""Joint budgets and source-bound enabling checks retain honest unknowns."""

import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage2_common import Stage2Error, canonical_hash
from stage2_workflow.prerequisites import (
    KINDS,
    inspect_prerequisite_review,
    prepare_prerequisite_review,
)
from stage2_fixture_helpers import write_stage2_fixture


class PrerequisiteTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.packet = write_stage2_fixture(self.root)
        self.ids = ["candidate-1", "candidate-2"]
        self.checks = [
            {
                "check_id": f"{candidate}:{kind}",
                "candidate_id": candidate,
                "candidate_version": 1,
                "kind": kind,
                "statement": "Recorded requirement",
                "status": "supported",
                "evidence_ids": ["ev-1"],
                "reason": "Supplied source is the claimed basis, not a semantic endorsement.",
                "next_check": None,
            }
            for candidate in self.ids
            for kind in sorted(KINDS)
        ]
        self.demands = [
            {
                "component_id": candidate,
                "candidate_ids": [candidate],
                "unit": "person-weeks",
                "amount": amount,
                "evidence_ids": ["ev-1"],
                "basis": "Synthetic scoped estimate",
            }
            for candidate, amount in zip(self.ids, [7, 8])
        ]
        self.budgets = [
            {
                "unit": "person-weeks",
                "amount": 10,
                "decision_ref": "fixture:researcher-resource-limit",
            }
        ]

    def build(self):
        return prepare_prerequisite_review(
            self.packet, self.root, self.ids, self.checks, self.demands, self.budgets
        )

    def test_individual_fit_does_not_imply_joint_fit(self):
        record = self.build()
        self.assertEqual(
            record["portfolio_resources"],
            [
                {
                    "unit": "person-weeks",
                    "demand": 15,
                    "capacity": 10,
                    "status": "exceeds",
                    "missing_candidate_ids": [],
                }
            ],
        )
        self.assertFalse(record["recommendation_authorized"])
        self.assertFalse(record["stage3_authorized"])

    def test_unknown_capacity_and_cost_not_zero(self):
        self.budgets[0]["amount"] = None
        self.demands[0]["amount"] = None
        self.assertEqual(
            self.build()["portfolio_resources"],
            [
                {
                    "unit": "person-weeks",
                    "demand": None,
                    "capacity": None,
                    "status": "unknown",
                    "missing_candidate_ids": [],
                }
            ],
        )

    def test_shared_component_counted_once(self):
        self.demands = [{**self.demands[0], "candidate_ids": self.ids, "amount": 7}]
        total = self.build()["portfolio_resources"][0]
        self.assertEqual(total["demand"], 7)
        self.assertEqual(total["missing_candidate_ids"], [])

    def test_omitted_candidate_estimate_makes_joint_cost_unknown(self):
        self.demands = [self.demands[0]]
        self.assertEqual(
            self.build()["portfolio_resources"],
            [
                {
                    "unit": "person-weeks",
                    "demand": None,
                    "capacity": 10,
                    "status": "unknown",
                    "missing_candidate_ids": ["candidate-2"],
                }
            ],
        )

    def test_explicit_shared_zero_estimate_is_not_missing_or_unknown(self):
        self.demands = [{**self.demands[0], "candidate_ids": self.ids, "amount": 0}]
        self.assertEqual(
            self.build()["portfolio_resources"],
            [
                {
                    "unit": "person-weeks",
                    "demand": 0,
                    "capacity": 10,
                    "status": "within",
                    "missing_candidate_ids": [],
                }
            ],
        )

    def test_missing_evidence_and_missing_category_fail_closed(self):
        for status in ("supported", "contradicted"):
            with self.subTest(status=status):
                self.checks[0]["status"] = status
                self.checks[0]["evidence_ids"] = []
                with self.assertRaises(Stage2Error):
                    self.build()
        self.checks[0]["status"] = "unknown"
        self.checks[0]["next_check"] = "Obtain the authoritative dictionary."
        self.build()
        self.checks.pop()
        with self.assertRaises(Stage2Error):
            self.build()

    def test_rehash_tamper_rejected_and_version_invalidated(self):
        record = self.build()
        inspect_prerequisite_review(
            record, self.packet, self.root, canonical_hash(record)
        )
        wrong = copy.deepcopy(record)
        wrong["portfolio_resources"][0]["status"] = "within"
        with self.assertRaises(Stage2Error):
            inspect_prerequisite_review(
                wrong, self.packet, self.root, canonical_hash(wrong)
            )
        revised = copy.deepcopy(self.packet["candidates"][0])
        revised.update(version=2, parent_version=1)
        self.packet["candidates"].append(revised)
        with self.assertRaises(Stage2Error):
            inspect_prerequisite_review(
                record, self.packet, self.root, canonical_hash(record)
            )
        self.packet["candidates"].pop()
        self.packet["resources"] = "A changed project limit"
        with self.assertRaises(Stage2Error):
            inspect_prerequisite_review(
                record, self.packet, self.root, canonical_hash(record)
            )

    def test_pure_theory_records_inapplicable_materials_without_semantic_pass(self):
        theory_texts = (
            "A bounded axiom system states premise P and derives consequence Q.\n",
            "A separate theorem gives a proof-checking path for consequence Q.\n",
        )
        quotes = (
            "A bounded axiom system states premise P",
            "A separate theorem gives a proof-checking path",
        )
        for index, (text, quote) in enumerate(zip(theory_texts, quotes)):
            raw = text.encode("utf-8")
            path = self.root / self.packet["sources"][index]["path"]
            path.write_bytes(raw)
            self.packet["sources"][index]["sha256"] = hashlib.sha256(raw).hexdigest()
            self.packet["evidence"][index]["quote"] = quote
        self.packet["brief"]["original_description"] = (
            "Study whether a bounded theorem follows from declared axioms."
        )
        self.packet["brief"]["needs"][0]["question"] = (
            "Does the theorem follow, and how can the proof be checked?"
        )
        self.ids = ["candidate-1"]
        material_kinds = {"data", "model", "tool", "license", "cost"}
        self.checks = []
        for kind in sorted(KINDS):
            if kind in material_kinds:
                status = "not-applicable"
                evidence_ids = []
                reason = (
                    "This bounded proof uses declared axioms and requires no "
                    f"{kind} prerequisite."
                )
            else:
                status = "supported"
                evidence_ids = ["ev-1" if kind == "premise" else "ev-2"]
                reason = "The cited theory source is the structural basis to review."
            self.checks.append(
                {
                    "check_id": f"candidate-1:{kind}",
                    "candidate_id": "candidate-1",
                    "candidate_version": 1,
                    "kind": kind,
                    "statement": "Record the bounded theoretical prerequisite.",
                    "status": status,
                    "evidence_ids": evidence_ids,
                    "reason": reason,
                    "next_check": None,
                }
            )
        self.demands = []
        self.budgets = []

        record = self.build()
        self.assertNotIn("llm", self.packet["brief"]["original_description"].lower())
        self.assertEqual(record["portfolio_resources"], [])
        self.assertEqual(record["semantic_verification"], "not-established")
        self.assertFalse(record["recommendation_authorized"])
        self.assertFalse(record["stage3_authorized"])

    def test_malformed_nested_arrays_raise_typed_stage2_errors(self):
        cases = []
        cases.append(
            (
                "candidate-scope",
                [["candidate-1"]],
                self.checks,
                self.demands,
                self.budgets,
            )
        )
        cases.append(
            (
                "candidate-scope-object",
                [{}],
                self.checks,
                self.demands,
                self.budgets,
            )
        )
        checks = copy.deepcopy(self.checks)
        checks[0]["kind"] = []
        cases.append(("check-kind", self.ids, checks, self.demands, self.budgets))
        checks = copy.deepcopy(self.checks)
        checks[0]["kind"] = {}
        cases.append(
            ("check-kind-object", self.ids, checks, self.demands, self.budgets)
        )
        checks = copy.deepcopy(self.checks)
        checks[0]["status"] = []
        cases.append(("check-status", self.ids, checks, self.demands, self.budgets))
        demands = copy.deepcopy(self.demands)
        demands[0]["candidate_ids"] = [["candidate-1"]]
        cases.append(("demand-scope", self.ids, self.checks, demands, self.budgets))
        demands = copy.deepcopy(self.demands)
        demands[0]["candidate_ids"] = [{}]
        cases.append(
            ("demand-scope-object", self.ids, self.checks, demands, self.budgets)
        )
        demands = copy.deepcopy(self.demands)
        demands[0]["unit"] = []
        cases.append(("demand-unit", self.ids, self.checks, demands, self.budgets))
        budgets = copy.deepcopy(self.budgets)
        budgets[0]["unit"] = []
        cases.append(("capacity-unit", self.ids, self.checks, self.demands, budgets))
        for name, candidate_ids, checks, demands, budgets in cases:
            with self.subTest(name=name), self.assertRaises(Stage2Error):
                prepare_prerequisite_review(
                    self.packet,
                    self.root,
                    candidate_ids,
                    checks,
                    demands,
                    budgets,
                )

        record = self.build()
        record["candidate_refs"] = [[]]
        with self.assertRaises(Stage2Error):
            inspect_prerequisite_review(
                record, self.packet, self.root, canonical_hash(record)
            )

    def test_duplicate_candidate_category_is_rejected(self):
        duplicate = copy.deepcopy(self.checks[0])
        duplicate["check_id"] = "duplicate-category"
        self.checks.append(duplicate)
        with self.assertRaisesRegex(Stage2Error, "duplicate prerequisite category"):
            self.build()

    def test_candidate_versions_require_integers(self):
        for value in (True, 1.0):
            with self.subTest(value=value):
                checks = copy.deepcopy(self.checks)
                checks[0]["candidate_version"] = value
                with self.assertRaisesRegex(
                    Stage2Error, "stale prerequisite candidate"
                ):
                    prepare_prerequisite_review(
                        self.packet,
                        self.root,
                        self.ids,
                        checks,
                        self.demands,
                        self.budgets,
                    )

    def test_huge_and_overflowing_quantities_raise_stage2_error(self):
        demands = copy.deepcopy(self.demands)
        demands[0]["amount"] = 10**400
        with self.assertRaisesRegex(Stage2Error, "unsupported resource quantity"):
            prepare_prerequisite_review(
                self.packet,
                self.root,
                self.ids,
                self.checks,
                demands,
                self.budgets,
            )

        demands = copy.deepcopy(self.demands)
        for row in demands:
            row["amount"] = 1e308
        with self.assertRaisesRegex(
            Stage2Error, "unsupported aggregate resource quantity"
        ):
            prepare_prerequisite_review(
                self.packet,
                self.root,
                self.ids,
                self.checks,
                demands,
                self.budgets,
            )
