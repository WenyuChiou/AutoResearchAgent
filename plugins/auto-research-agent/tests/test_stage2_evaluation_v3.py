"""Regression tests for the standalone Stage 2 general v3 evaluator."""

import copy
import tempfile
import unittest
from pathlib import Path
import sys


PLUGIN = Path(__file__).resolve().parents[1]
CLI = PLUGIN / "cli"
sys.path.insert(0, str(CLI))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ruff: noqa: E402 -- repository CLIs are intentionally imported without install.
from stage2_common import Stage2Error, canonical_hash, validate_packet
from stage2_eval.evaluation import CRITERIA as CRITERIA_V2
from stage2_eval.evaluation_v3 import (
    CRITERIA_V3,
    compare_pairs_v3,
    dimension_scores_v3,
    merge_judgments_v3,
    prepare_action_view_v3,
    prepare_content_view_v3,
    validate_bundle_v3,
    validate_judge_output_v3,
)
from stage2_fixture_helpers import write_stage2_fixture


def content_assessment(view, *, evidence_ids=None):
    return {
        "kind": "Stage2ContentAssessment",
        "schema_version": "1.0.0",
        **{
            key: view[key]
            for key in (
                "subject_id",
                "packet_sha256",
                "input_sha256",
                "config_sha256",
                "rubric_id",
                "rubric_sha256",
            )
        },
        "content_view_sha256": canonical_hash(view),
        "evaluator_status": "complete",
        "findings": [
            {
                "finding_id": "finding-1",
                "statement": "The fixture supports a bounded comparison.",
                "evidence_ids": evidence_ids or ["ev-1"],
            }
        ],
    }


def action_record(packet):
    latest = {}
    candidates = {}
    for row in packet["candidates"]:
        key = (row["candidate_id"], row["version"])
        candidates[key] = row
        latest[row["candidate_id"]] = max(
            row["version"], latest.get(row["candidate_id"], 0)
        )

    def disposition(candidate_id, version):
        candidate = candidates[(candidate_id, version)]
        return {
            "candidate_id": candidate_id,
            "candidate_version": version,
            "disposition": "recommend",
            "reason": "The evidence supports retaining this bounded option.",
            "evidence_ids": candidate["evidence_ids"],
            "next_step": "Obtain a human choice before Stage 3.",
        }

    return {
        "kind": "Stage2ActionRecord",
        "schema_version": "1.0.0",
        "packet_sha256": canonical_hash(packet),
        "history": [
            {
                "event_id": f"event-{row['candidate_id']}-v{row['version']}",
                **disposition(row["candidate_id"], row["version"]),
            }
            for row in packet["candidates"]
        ],
        "latest_dispositions": [
            disposition(candidate_id, version)
            for candidate_id, version in sorted(latest.items())
        ],
        "selected_candidate_ids": [next(iter(sorted(latest)))] if latest else [],
        "choice_rationale": (
            "The first evidence-supported option remains available."
            if latest
            else "The bounded evidence supports no recommendation."
        ),
        "revision_history": [
            {
                "candidate_id": row["candidate_id"],
                "from_version": row["version"] - 1,
                "to_version": row["version"],
                "reason": "New evidence required a substantive revision.",
                "evidence_ids": row["evidence_ids"],
            }
            for row in packet["candidates"]
            if row["version"] > 1
        ],
    }


def judge(view, action, packet, role="R1", scores=None, *, technical=False):
    scores = scores or {key: 1 for key in CRITERIA_V3}
    rows = [
        {
            "criterion_id": key,
            "status": "unknown" if technical else "assessed",
            "score": None if technical else scores[key],
            "rationale": (
                "The evaluator transport failed."
                if technical
                else f"{role} source-bound comment for {key}."
            ),
            "evidence_ids": [] if technical else ["ev-1"],
            "unknown_reason": "evaluator-failure" if technical else None,
        }
        for key in CRITERIA_V3
    ]
    latest = {}
    for row in packet["candidates"]:
        latest[row["candidate_id"]] = max(
            row["version"], latest.get(row["candidate_id"], 0)
        )
    return {
        "kind": "Stage2JudgeAssessment",
        "schema_version": "1.0.0",
        "role": role,
        **{
            key: view[key]
            for key in (
                "subject_id",
                "packet_sha256",
                "input_sha256",
                "config_sha256",
                "rubric_id",
                "rubric_sha256",
            )
        },
        "content_view_sha256": canonical_hash(view),
        "action_view_sha256": canonical_hash(action),
        "candidate_coverage": [
            {"candidate_id": key, "version": latest[key]} for key in sorted(latest)
        ],
        "evaluator_status": "technical-failure" if technical else "complete",
        "failure_reason": "offline evaluator unavailable" if technical else None,
        "criteria": rows,
        "major_error_ids": [],
        "audit_required": False,
        "audit_reasons": [],
        "audit_status": "not-required",
        "confidence": "high",
        "central_evidence_inaccessible": False,
    }


def named_audit(selected):
    return {
        "kind": "Stage2NamedAudit",
        "schema_version": "1.0.0",
        **{
            key: selected[key]
            for key in (
                "subject_id",
                "packet_sha256",
                "input_sha256",
                "config_sha256",
                "rubric_id",
                "rubric_sha256",
                "content_view_sha256",
                "action_view_sha256",
            )
        },
        "assessment_sha256": canonical_hash(selected),
        "reviewer": "Named reviewer",
        "reviewer_role": "human",
        "decision": "accepted",
        "reason": "The evidence-bound result was reviewed.",
    }


class Stage2EvaluationV3Tests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.packet = write_stage2_fixture(self.root, revise_first=True)
        validate_packet(self.packet, self.root)
        self.view = prepare_content_view_v3(
            self.packet, "opaque-v3-a", "1" * 64, "2" * 64
        )
        self.content = content_assessment(self.view)
        self.action = prepare_action_view_v3(
            self.packet, self.view, self.content, action_record(self.packet)
        )

    def bundle(
        self, subject, scores=None, *, unknown=None, technical=False, major=None
    ):
        packet = copy.deepcopy(self.packet)
        view = prepare_content_view_v3(packet, subject, "1" * 64, "2" * 64)
        action = prepare_action_view_v3(
            packet, view, content_assessment(view), action_record(packet)
        )
        r1 = judge(view, action, packet, "R1", scores, technical=technical)
        r2 = judge(view, action, packet, "R2", scores, technical=technical)
        if unknown is not None:
            for output in (r1, r2):
                output["criteria"][unknown].update(
                    status="unknown",
                    score=None,
                    evidence_ids=[],
                    unknown_reason="evidence-unavailable",
                )
        if major is not None:
            for output in (r1, r2):
                output["major_error_ids"] = [major]
        return merge_judgments_v3(
            r1,
            r2,
            view,
            action,
            packet,
            audit=named_audit(r1) if major is not None else None,
        )

    def test_nine_criteria_and_fixed_six_point_dimensions(self):
        scores = {key: 2 for key in CRITERIA_V3}
        bundle = self.bundle("complete", scores)
        self.assertEqual(
            [row["criterion_id"] for row in bundle["criteria"]],
            list(CRITERIA_V3),
        )
        self.assertEqual(
            dimension_scores_v3(bundle),
            {
                key: {
                    "score": 100.0,
                    "sum": 6,
                    "max": 6,
                    "assessed": 3,
                    "required": 3,
                }
                for key in ("P4", "P5", "P6")
            },
        )
        self.assertNotEqual(CRITERIA_V3, CRITERIA_V2)

    def test_any_unknown_nulls_only_its_complete_dimension(self):
        scores = dimension_scores_v3(self.bundle("unknown", unknown=4))
        self.assertEqual(
            scores["P5"],
            {"score": None, "sum": None, "max": 6, "assessed": 2, "required": 3},
        )
        self.assertEqual(scores["P4"]["sum"], 3)
        self.assertEqual(scores["P6"]["sum"], 3)

    def test_source_version_hash_evidence_and_stale_view_rejected(self):
        broken = copy.deepcopy(self.packet)
        broken["sources"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(Stage2Error, "hash mismatch"):
            validate_packet(broken, self.root)
        broken = copy.deepcopy(self.packet)
        broken["evidence"][0]["version_id"] = "wrong-version"
        with self.assertRaisesRegex(Stage2Error, "work/version mismatch"):
            validate_packet(broken, self.root)
        broken = copy.deepcopy(self.packet)
        broken["evidence"][0]["quote"] = "not an exact source span"
        with self.assertRaisesRegex(Stage2Error, "exact contiguous"):
            validate_packet(broken, self.root)
        output = judge(self.view, self.action, self.packet)
        stale = copy.deepcopy(self.packet)
        stale["comparison"] = "Changed after the view was frozen."
        with self.assertRaisesRegex(Stage2Error, "version-locked|packet_sha256"):
            validate_judge_output_v3(output, self.view, self.action, stale)
        missing_ref = judge(self.view, self.action, self.packet)
        missing_ref["criteria"][0]["evidence_ids"] = ["missing"]
        with self.assertRaisesRegex(Stage2Error, "unknown evidence"):
            validate_judge_output_v3(missing_ref, self.view, self.action, self.packet)

    def test_evaluator_failure_is_not_subject_zero(self):
        failed = self.bundle("technical", technical=True)
        self.assertFalse(failed["usable"])
        self.assertEqual(failed["criteria"], [])
        self.assertIsNone(dimension_scores_v3(failed))
        invalid = judge(self.view, self.action, self.packet, technical=True)
        invalid["criteria"][0].update(
            status="assessed", score=0, evidence_ids=["ev-1"], unknown_reason=None
        )
        with self.assertRaisesRegex(Stage2Error, "technical failure cannot score"):
            validate_judge_output_v3(invalid, self.view, self.action, self.packet)

    def test_disagreement_on_score_status_or_major_requires_adj(self):
        for mutation in ("score", "status", "major"):
            with self.subTest(mutation=mutation):
                r1 = judge(self.view, self.action, self.packet, "R1")
                r2 = judge(self.view, self.action, self.packet, "R2")
                if mutation == "score":
                    r2["criteria"][0]["score"] = 2
                elif mutation == "status":
                    r2["criteria"][0].update(
                        status="unknown",
                        score=None,
                        evidence_ids=[],
                        unknown_reason="evidence-unavailable",
                    )
                else:
                    r2["major_error_ids"] = ["false-verification"]
                with self.assertRaisesRegex(Stage2Error, "requires ADJ"):
                    merge_judgments_v3(r1, r2, self.view, self.action, self.packet)

    def test_adjudication_preserves_all_role_comments_and_confidence(self):
        r1 = judge(self.view, self.action, self.packet, "R1")
        r2 = judge(self.view, self.action, self.packet, "R2")
        r2["criteria"][0]["score"] = 2
        r2["confidence"] = "medium"
        adj = judge(self.view, self.action, self.packet, "ADJ")
        adj["criteria"][0]["score"] = 2
        bundle = merge_judgments_v3(
            r1,
            r2,
            self.view,
            self.action,
            self.packet,
            adj=adj,
            audit=named_audit(adj),
        )
        first = bundle["criteria"][0]
        self.assertEqual(first["selected_role"], "ADJ")
        self.assertEqual(first["score"], 2)
        self.assertEqual(first["judgments"]["R1"]["confidence"], "high")
        self.assertEqual(first["judgments"]["R2"]["confidence"], "medium")
        self.assertIn("R1 source-bound comment", first["judgments"]["R1"]["rationale"])
        self.assertIn(
            "ADJ source-bound comment", first["judgments"]["ADJ"]["rationale"]
        )
        validate_bundle_v3(bundle)

    def test_replay_validation_rejects_rehashed_summary_tamper(self):
        bundle = self.bundle("tamper")
        bundle["criteria"][0]["score"] = 2
        with self.assertRaisesRegex(Stage2Error, "replayed raw judgments"):
            validate_bundle_v3(bundle)

    def test_anchor_semantics_allow_correct_infeasibility_and_partial_revision(self):
        scores = {key: 2 for key in CRITERIA_V3}
        scores["P5V3.REVISION"] = 1
        bundle = self.bundle("anchors", scores)
        rows = {row["criterion_id"]: row for row in bundle["criteria"]}
        self.assertEqual(rows["P6V3.FEASIBILITY"]["score"], 2)
        self.assertEqual(rows["P5V3.REVISION"]["score"], 1)
        self.assertEqual(dimension_scores_v3(bundle)["P5"]["sum"], 5)

    def test_zero_candidates_do_not_cap_choice_or_feasibility(self):
        packet = write_stage2_fixture(self.root / "empty", candidate_count=0)
        validate_packet(packet, self.root / "empty")
        view = prepare_content_view_v3(packet, "zero-candidates", "1" * 64, "2" * 64)
        action = prepare_action_view_v3(
            packet, view, content_assessment(view), action_record(packet)
        )
        scores = {key: 2 for key in CRITERIA_V3}
        r1 = judge(view, action, packet, "R1", scores)
        r2 = judge(view, action, packet, "R2", scores)
        bundle = merge_judgments_v3(r1, r2, view, action, packet)
        self.assertEqual(bundle["raw"]["r1"]["candidate_coverage"], [])
        self.assertEqual(dimension_scores_v3(bundle)["P6"]["sum"], 6)

    def test_three_pair_deltas_and_v2_contract_remain_independent(self):
        pairs = []
        for index, order in enumerate(("AB", "BA", "AB"), 1):
            baseline_scores = {key: 1 for key in CRITERIA_V3}
            treatment_scores = dict(baseline_scores)
            for key in CRITERIA_V3[3:]:
                treatment_scores[key] = 2
            baseline = self.bundle(f"a-{index}", baseline_scores)
            treatment = self.bundle(f"b-{index}", treatment_scores)
            pairs.append(
                {
                    "pair_id": f"pair-{index}",
                    "order": order,
                    "A": baseline,
                    "B": treatment,
                    "A_content_view_sha256": baseline["content_view_sha256"],
                    "B_content_view_sha256": treatment["content_view_sha256"],
                }
            )
        result = compare_pairs_v3(pairs)
        self.assertEqual(result["decision"], "diagnostic-improvement")
        self.assertEqual(result["pairs"][0]["A"]["P4"]["sum"], 3)
        self.assertEqual(result["pairs"][0]["B"]["P5"]["sum"], 6)
        self.assertEqual(
            result["pairs"][0]["delta"], {"P4": 0.0, "P5": 50.0, "P6": 50.0}
        )
        self.assertEqual(len(CRITERIA_V2), 7)
        self.assertEqual(len(CRITERIA_V3), 9)


if __name__ == "__main__":
    unittest.main()
