"""Opt-in Stage 2 quality records fail closed without inferring truth."""

import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from stage2_common import Stage2Error, canonical_hash
from stage2_fixture_helpers import write_stage2_fixture
from stage2_ideation.extraction import (
    IdeationError,
    prepare_completeness_record,
    validate_extraction,
)
from stage2_workflow.prerequisites import KINDS, prepare_prerequisite_review
from stage2_workflow.quality_guards import (
    inspect_quality_record,
    prepare_quality_record,
    prepare_quality_task,
)
from stage2_workflow.reviews import prepare_review, reconcile_reviews
from test_stage2_checker import assessment
from test_stage2_ideation import valid_extraction


SNAPSHOT = "a" * 64


class QualityGuardTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.packet = write_stage2_fixture(self.root, candidate_count=2)

    def checks(self, candidate_id="candidate-1"):
        named = {
            "comparability": ("counterexample", "different outcome interval"),
            "evidence-dependency": ("premise", "source access remains available"),
            "mechanism-distinction": (
                "distinguishing-observation",
                "held-out errors diverge",
            ),
            "critical-premise": ("premise", "measurements share an outcome"),
        }
        return [
            {
                "check_id": f"{candidate_id}:{category}",
                "candidate_id": candidate_id,
                "candidate_version": 1,
                "category": category,
                "critical": category in {"mechanism-distinction", "critical-premise"},
                "statement": f"Assess {kind} '{element}' against the bounded sources.",
                "named_element_kind": kind,
                "named_element": element,
                "status": "supported",
                "rationale": "The caller identifies ev-1 as the basis; semantic truth is not inferred.",
                "evidence_ids": ["ev-1"],
                "next_check": None,
            }
            for category, (kind, element) in named.items()
        ]

    def prerequisite(self, candidate_ids=("candidate-1",), amounts=(4,), capacity=5):
        checks = [
            {
                "check_id": f"{candidate_id}:{kind}",
                "candidate_id": candidate_id,
                "candidate_version": 1,
                "kind": kind,
                "statement": f"Check {kind} prerequisite.",
                "status": "supported",
                "evidence_ids": ["ev-1"],
                "reason": "Caller-supplied evidence basis.",
                "next_check": None,
            }
            for candidate_id in candidate_ids
            for kind in sorted(KINDS)
        ]
        demands = [
            {
                "component_id": candidate_id,
                "candidate_ids": [candidate_id],
                "unit": "person-weeks",
                "amount": amount,
                "evidence_ids": ["ev-1"],
                "basis": "Bounded estimate",
            }
            for candidate_id, amount in zip(candidate_ids, amounts)
        ]
        capacities = [
            {
                "unit": "person-weeks",
                "amount": capacity,
                "decision_ref": "fixture:capacity",
            }
        ]
        return prepare_prerequisite_review(
            self.packet, self.root, list(candidate_ids), checks, demands, capacities
        )

    def reviews(self):
        rows = []
        for role, digest in (("challenger", "b"), ("feasibility", "c")):
            view = prepare_review(self.packet, "candidate-1", SNAPSHOT, role)
            rows.append(
                {
                    "role": role,
                    "view_sha256": canonical_hash(view),
                    "snapshot_sha256": SNAPSHOT,
                    "candidate_id": "candidate-1",
                    "candidate_version": 1,
                    "assessment": assessment(self.packet),
                    "session_id": f"session-{role}",
                    "native_artifact": {
                        "path": f"native/{role}.jsonl",
                        "sha256": digest * 64,
                    },
                    "initial": True,
                    "assumptions": ["The observations concern the same outcome."],
                    "strongest_alternative": "Measurement differences explain the result.",
                    "change_conditions": ["A source contradicts the shared outcome."],
                }
            )
        return rows

    def resolution(self, rows):
        return {
            "review_sha256s": [canonical_hash(row) for row in rows],
            "method": "synthesis",
            "reason": "The two independent reviews use the bounded evidence.",
            "evidence_ids": ["ev-1"],
            "addressed": [],
            "assessment": assessment(self.packet),
            "substantive_disagreements": [],
            "changed_judgment_reason": None,
        }

    def bundle(
        self,
        quality,
        prerequisite,
        *,
        mode="alternatives",
        selected=None,
        joint="not-claimed",
    ):
        return {
            "quality_record": quality,
            "quality_sha256": canonical_hash(quality),
            "prerequisite_record": prerequisite,
            "prerequisite_sha256": canonical_hash(prerequisite),
            "source_root": self.root,
            "resource_mode": mode,
            "selected_candidate_ids": selected or ["candidate-1"],
            "joint_feasibility": joint,
        }

    def reconcile(self, quality, prerequisite, **bundle_changes):
        rows = self.reviews()
        bundle = self.bundle(quality, prerequisite)
        bundle.update(bundle_changes)
        return reconcile_reviews(
            self.packet,
            "candidate-1",
            SNAPSHOT,
            rows,
            self.resolution(rows),
            guard_bundle=bundle,
        )

    def test_valid_method_may_retain_noncritical_unknown_effectiveness(self):
        checks = self.checks()
        row = next(x for x in checks if x["category"] == "evidence-dependency")
        row.update(
            status="unknown", evidence_ids=[], next_check="Run the bounded comparison."
        )
        quality = prepare_quality_record(self.packet, "candidate-1", SNAPSHOT, checks)
        self.assertTrue(
            self.reconcile(quality, self.prerequisite())["recommendation_eligible"]
        )

    def test_same_score_shared_false_premise_and_indistinguishable_mechanisms_block(
        self,
    ):
        for category, status in (
            ("critical-premise", "contradicted"),
            ("mechanism-distinction", "unknown"),
        ):
            with self.subTest(category=category):
                checks = self.checks()
                row = next(x for x in checks if x["category"] == category)
                row["status"] = status
                if status == "unknown":
                    row.update(
                        evidence_ids=[],
                        next_check="Measure the distinguishing observation.",
                    )
                quality = prepare_quality_record(
                    self.packet, "candidate-1", SNAPSHOT, checks
                )
                self.assertFalse(
                    self.reconcile(quality, self.prerequisite())[
                        "recommendation_eligible"
                    ]
                )

    def test_unknown_enabling_dependency_blocks_and_theory_not_applicable_is_valid(
        self,
    ):
        quality = prepare_quality_record(
            self.packet, "candidate-1", SNAPSHOT, self.checks()
        )
        prerequisite = self.prerequisite()
        prerequisite["checks"][0].update(
            status="unknown", evidence_ids=[], next_check="Obtain dependency."
        )
        prerequisite = prepare_prerequisite_review(
            self.packet,
            self.root,
            ["candidate-1"],
            prerequisite["checks"],
            prerequisite["demands"],
            prerequisite["capacities"],
        )
        self.assertFalse(
            self.reconcile(quality, prerequisite)["recommendation_eligible"]
        )

        checks = self.checks()
        for row in checks:
            row.update(status="not-applicable", evidence_ids=[], next_check=None)
            row["rationale"] = (
                "The pure theory case has no empirical dependency for this check."
            )
        quality = prepare_quality_record(self.packet, "candidate-1", SNAPSHOT, checks)
        prereq_checks = copy.deepcopy(prerequisite["checks"])
        for row in prereq_checks:
            row.update(status="not-applicable", evidence_ids=[], next_check=None)
            row["reason"] = (
                "The declared proof is independent of this material prerequisite."
            )
        theory = prepare_prerequisite_review(
            self.packet, self.root, ["candidate-1"], prereq_checks, [], []
        )
        self.assertTrue(self.reconcile(quality, theory)["recommendation_eligible"])

    def test_alternatives_do_not_require_joint_capacity_but_joint_claim_does(self):
        quality = prepare_quality_record(
            self.packet, "candidate-1", SNAPSHOT, self.checks()
        )
        prerequisite = self.prerequisite(("candidate-1", "candidate-2"), (4, 4), 5)
        result = self.reconcile(
            quality,
            prerequisite,
            selected_candidate_ids=["candidate-1", "candidate-2"],
        )
        self.assertTrue(result["recommendation_eligible"])
        result = self.reconcile(
            quality,
            prerequisite,
            resource_mode="simultaneous",
            selected_candidate_ids=["candidate-1", "candidate-2"],
            joint_feasibility="exceeds",
        )
        self.assertFalse(result["recommendation_eligible"])
        with self.assertRaisesRegex(Stage2Error, "joint feasibility claim mismatch"):
            self.reconcile(
                quality,
                prerequisite,
                resource_mode="simultaneous",
                selected_candidate_ids=["candidate-1", "candidate-2"],
                joint_feasibility="within",
            )

    def test_missing_guard_default_unchanged_and_opt_in_tamper_or_stale_fails(self):
        rows = self.reviews()
        legacy = reconcile_reviews(
            self.packet, "candidate-1", SNAPSHOT, rows, self.resolution(rows)
        )
        self.assertTrue(legacy["recommendation_eligible"])
        quality = prepare_quality_record(
            self.packet, "candidate-1", SNAPSHOT, self.checks()
        )
        bundle = self.bundle(quality, self.prerequisite())
        bundle["quality_record"]["checks"][0]["rationale"] = "rehash attempt"
        bundle["quality_sha256"] = canonical_hash(bundle["quality_record"])
        with self.assertRaisesRegex(Stage2Error, "reconstruction mismatch"):
            reconcile_reviews(
                self.packet,
                "candidate-1",
                SNAPSHOT,
                rows,
                self.resolution(rows),
                guard_bundle=bundle,
            )

        revised = copy.deepcopy(self.packet["candidates"][0])
        revised.update(version=2, parent_version=1)
        self.packet["candidates"].append(revised)
        with self.assertRaisesRegex(Stage2Error, "stale quality"):
            inspect_quality_record(
                quality, self.packet, SNAPSHOT, canonical_hash(quality)
            )

    def test_multiple_critical_premises_are_checked_without_a_fixed_quota(self):
        checks = self.checks()
        second = copy.deepcopy(checks[-1])
        second.update(
            check_id="second-premise",
            status="unknown",
            evidence_ids=[],
            next_check="Check the second enabling premise.",
        )
        checks.append(second)
        quality = prepare_quality_record(self.packet, "candidate-1", SNAPSHOT, checks)
        self.assertFalse(
            self.reconcile(quality, self.prerequisite())["recommendation_eligible"]
        )

    def test_theory_alternative_is_not_blocked_by_another_options_cost(self):
        quality = prepare_quality_record(
            self.packet, "candidate-1", SNAPSHOT, self.checks()
        )
        original = self.prerequisite(("candidate-1", "candidate-2"), (None, 4), 5)
        checks = copy.deepcopy(original["checks"])
        for row in checks:
            if row["candidate_id"] == "candidate-1" and row["kind"] == "cost":
                row.update(
                    status="not-applicable",
                    evidence_ids=[],
                    reason="No additional material cost applies to this theoretical alternative.",
                )
        other_only = prepare_prerequisite_review(
            self.packet,
            self.root,
            ["candidate-1", "candidate-2"],
            checks,
            [x for x in original["demands"] if x["candidate_ids"] == ["candidate-2"]],
            original["capacities"],
        )
        self.assertTrue(
            self.reconcile(
                quality,
                other_only,
                selected_candidate_ids=["candidate-1", "candidate-2"],
            )["recommendation_eligible"]
        )

    def test_rehashing_both_layers_cannot_replace_the_retained_quality_receipt(self):
        quality = prepare_quality_record(
            self.packet, "candidate-1", SNAPSHOT, self.checks()
        )
        receipt = canonical_hash(quality)
        quality["checks"][0]["rationale"] = (
            "Changed after independent receipt was retained."
        )
        quality["record_sha256"] = canonical_hash(
            {k: v for k, v in quality.items() if k != "record_sha256"}
        )
        with self.assertRaisesRegex(Stage2Error, "external quality hash mismatch"):
            inspect_quality_record(quality, self.packet, SNAPSHOT, receipt)

    def test_quality_task_has_evidence_but_no_prefilled_verdict(self):
        task = prepare_quality_task(self.packet, "candidate-1", SNAPSHOT)
        self.assertEqual(len(task["questions"]), 4)
        self.assertEqual(task["semantic_verification"], "not-performed")
        self.assertNotIn("assessment", task)
        self.assertFalse(task["actual_execution_attested"])


class CompletenessTests(unittest.TestCase):
    def setUp(self):
        self.raw = (
            "A formed idea improves the measure. A vague thought remains unformed."
        )
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.packet = write_stage2_fixture(self.root, candidate_count=0)
        self.extraction = valid_extraction(
            "The monthly and annual outcomes are not directly comparable.\n"
            "Both reports reuse the same survey frame.\n"
            "Improve the existing measure with a prespecified alignment rule.\n"
            "A new concept uses disagreement as the measured signal."
        )
        self.raw = (
            "The monthly and annual outcomes are not directly comparable.\n"
            "Both reports reuse the same survey frame.\n"
            "Improve the existing measure with a prespecified alignment rule.\n"
            "A new concept uses disagreement as the measured signal."
        )

    def span(self, quote):
        start = self.raw.index(quote)
        return {"start": start, "end": start + len(quote), "quote": quote}

    def ideas(self):
        return [
            {
                "idea_id": "idea-1",
                "span": self.span(
                    "Improve the existing measure with a prespecified alignment rule."
                ),
                "outcome": "extracted",
                "candidate_id": "candidate-improve",
                "reason": "The span states a formed method change.",
            },
            {
                "idea_id": "idea-2",
                "span": self.span(
                    "A new concept uses disagreement as the measured signal."
                ),
                "outcome": "extracted",
                "candidate_id": "candidate-new",
                "reason": "The span states a formed exploratory concept.",
            },
        ]

    def test_exact_supplied_spans_are_accounted_for_and_raw_is_preserved(self):
        before = self.raw
        record = prepare_completeness_record(
            self.raw, self.extraction, self.packet, SNAPSHOT, self.ideas()
        )
        result = validate_extraction(
            self.raw,
            self.extraction,
            self.packet,
            SNAPSHOT,
            completeness_record=record,
            expected_completeness_sha256=canonical_hash(record),
        )
        self.assertEqual(self.raw, before)
        self.assertEqual(len(result["candidates"]), 2)

    def test_zero_genuine_ideas_is_legal_but_dropped_formed_idea_is_not(self):
        empty = copy.deepcopy(self.extraction)
        empty["candidates"] = []
        record = prepare_completeness_record(self.raw, empty, self.packet, SNAPSHOT, [])
        validate_extraction(
            self.raw,
            empty,
            self.packet,
            SNAPSHOT,
            completeness_record=record,
            expected_completeness_sha256=canonical_hash(record),
        )
        with self.assertRaisesRegex(IdeationError, "formed extracted idea omitted"):
            prepare_completeness_record(
                self.raw, self.extraction, self.packet, SNAPSHOT, self.ideas()[:1]
            )

    def test_completeness_rehash_tamper_and_missing_pair_fail_closed(self):
        record = prepare_completeness_record(
            self.raw, self.extraction, self.packet, SNAPSHOT, self.ideas()
        )
        record["ideas"][0]["reason"] = "changed"
        with self.assertRaisesRegex(IdeationError, "reconstruction mismatch"):
            validate_extraction(
                self.raw,
                self.extraction,
                self.packet,
                SNAPSHOT,
                completeness_record=record,
                expected_completeness_sha256=canonical_hash(record),
            )
        with self.assertRaisesRegex(IdeationError, "expected hash required"):
            validate_extraction(
                self.raw,
                self.extraction,
                self.packet,
                SNAPSHOT,
                completeness_record=record,
            )

    def test_cli_preserves_receipt_and_rejects_forged_completeness_before_export(self):
        import contextlib
        import io
        import json
        from stage2_ideation.__main__ import main

        record = prepare_completeness_record(
            self.raw, self.extraction, self.packet, SNAPSHOT, self.ideas()
        )
        for name, value in (
            ("packet", self.packet),
            ("extraction", self.extraction),
            ("completeness", record),
        ):
            (self.root / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
        (self.root / "raw.txt").write_bytes(self.raw.encode("utf-8"))
        args = [
            "report",
            "--packet",
            str(self.root / "packet.json"),
            "--source-root",
            str(self.root),
            "--raw-proposal",
            str(self.root / "raw.txt"),
            "--extraction",
            str(self.root / "extraction.json"),
            "--snapshot-sha256",
            SNAPSHOT,
            "--completeness-record",
            str(self.root / "completeness.json"),
            "--expected-completeness-sha256",
            canonical_hash(record),
            "--output",
            str(self.root / "export"),
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(args), 0)
        manifest = json.loads((self.root / "export" / "manifest.json").read_bytes())
        self.assertEqual(manifest["schema_version"], "1.1.0")
        self.assertEqual(manifest["completeness_scope"], "caller-supplied-spans-only")
        self.assertIn("idea_completeness.json", manifest["files"])
        record["ideas"][0]["reason"] = "Forged"
        record["record_sha256"] = canonical_hash(
            {k: v for k, v in record.items() if k != "record_sha256"}
        )
        (self.root / "completeness.json").write_text(
            json.dumps(record), encoding="utf-8"
        )
        args[-1] = str(self.root / "forged-export")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(args), 2)
        self.assertFalse((self.root / "forged-export").exists())


if __name__ == "__main__":
    unittest.main()
