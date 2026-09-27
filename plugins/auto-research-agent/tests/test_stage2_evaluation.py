"""Regression tests for the offline Stage 2 evaluator and packet contract."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
CLI = PLUGIN / "cli"
sys.path.insert(0, str(CLI))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ruff: noqa: E402 -- repository CLIs are intentionally imported without install.
from stage2_common import Stage2Error, canonical_hash, validate_packet
from stage2_eval import (
    compare_pairs,
    merge_judgments,
    prepare_action_view,
    prepare_content_view,
    validate_content_assessment,
    validate_judge_output,
)
from stage2_eval.evaluation import CRITERIA
from stage2_fixture_helpers import write_stage2_fixture


def content_assessment(
    view,
    *,
    evidence_ids=None,
    statement="The controlled source supports a bounded comparison.",
):
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
                "statement": statement,
                "evidence_ids": evidence_ids or ["ev-1"],
            }
        ],
    }


def action_record(packet):
    latest = {}
    for row in packet["candidates"]:
        latest[row["candidate_id"]] = max(
            row["version"], latest.get(row["candidate_id"], 0)
        )
    candidate_by_key = {
        (row["candidate_id"], row["version"]): row for row in packet["candidates"]
    }

    def disposition(candidate_id, version):
        candidate = candidate_by_key[(candidate_id, version)]
        return {
            "candidate_id": candidate_id,
            "candidate_version": version,
            "disposition": "recommend",
            "reason": "The synthetic evidence supports retaining this option.",
            "evidence_ids": candidate["evidence_ids"],
            "next_step": "Obtain a human decision before Stage 3.",
        }

    history = []
    for candidate in packet["candidates"]:
        history.append(
            {
                "event_id": f"event-{candidate['candidate_id']}-v{candidate['version']}",
                **disposition(candidate["candidate_id"], candidate["version"]),
            }
        )
    return {
        "kind": "Stage2ActionRecord",
        "schema_version": "1.0.0",
        "packet_sha256": canonical_hash(packet),
        "history": history,
        "latest_dispositions": [
            disposition(candidate_id, version)
            for candidate_id, version in sorted(latest.items())
        ],
        "selected_candidate_ids": [next(iter(sorted(latest)))] if latest else [],
        "choice_rationale": (
            "The first synthetic option is retained for diagnostic comparison."
            if latest
            else "No candidate is selected because the controlled packet has none."
        ),
        "revision_history": [
            {
                "candidate_id": row["candidate_id"],
                "from_version": row["version"] - 1,
                "to_version": row["version"],
                "reason": "New source evidence required a substantive revision.",
                "evidence_ids": row["evidence_ids"],
            }
            for row in packet["candidates"]
            if row["version"] > 1
        ],
    }


def judge(view, action, packet, role="R1", scores=None, *, technical=False):
    scores = scores or {key: 1 for key in CRITERIA}
    rows = []
    for key in CRITERIA:
        rows.append(
            {
                "criterion_id": key,
                "status": "unknown" if technical else "assessed",
                "score": None if technical else scores[key],
                "rationale": "Evaluator transport failed."
                if technical
                else "The source-bound fixture supports this score.",
                "evidence_ids": [] if technical else ["ev-1"],
                "unknown_reason": "evaluator-failure" if technical else None,
            }
        )
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
        "failure_reason": "offline evaluator output was unavailable"
        if technical
        else None,
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
        "reason": "The source-bound decision was reviewed.",
    }


class Stage2EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.packet = write_stage2_fixture(self.root, revise_first=True)
        validate_packet(self.packet, self.root)
        self.view = prepare_content_view(
            self.packet, "opaque-subject-a", "1" * 64, "2" * 64
        )
        self.content = content_assessment(self.view)
        self.action = prepare_action_view(
            self.packet, self.view, self.content, action_record(self.packet)
        )

    def test_stage2_source_binding(self):
        broken = copy.deepcopy(self.packet)
        broken["sources"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(Stage2Error, "hash mismatch"):
            validate_packet(broken, self.root)
        broken = copy.deepcopy(self.packet)
        broken["evidence"][0]["version_id"] = "v2"
        with self.assertRaisesRegex(Stage2Error, "work/version mismatch"):
            validate_packet(broken, self.root)
        broken = copy.deepcopy(self.packet)
        broken["evidence"][0]["quote"] = "paraphrased source text"
        with self.assertRaisesRegex(Stage2Error, "exact contiguous"):
            validate_packet(broken, self.root)
        outside = self.root.parent / "stage2-outside.txt"
        outside.write_text("outside", encoding="utf-8")
        self.addCleanup(outside.unlink, missing_ok=True)
        broken = copy.deepcopy(self.packet)
        broken["sources"][0]["path"] = "../stage2-outside.txt"
        broken["sources"][0]["sha256"] = canonical_hash("not-the-file")
        with self.assertRaisesRegex(Stage2Error, "portable and relative"):
            validate_packet(broken, self.root)
        broken = copy.deepcopy(self.packet)
        broken["evidence"].append(copy.deepcopy(broken["evidence"][0]))
        with self.assertRaisesRegex(Stage2Error, "duplicate evidence_id"):
            validate_packet(broken, self.root)

    def test_packet_requires_contiguous_version_history_and_exact_parent(self):
        broken = copy.deepcopy(self.packet)
        revised = next(row for row in broken["candidates"] if row["version"] == 2)
        revised["version"] = 3
        with self.assertRaisesRegex(Stage2Error, "non-contiguous"):
            validate_packet(broken, self.root)
        broken = copy.deepcopy(self.packet)
        next(row for row in broken["candidates"] if row["version"] == 2)[
            "parent_version"
        ] = 2
        with self.assertRaisesRegex(Stage2Error, "wrong candidate parent"):
            validate_packet(broken, self.root)

    def test_views_are_version_locked_blind_and_latest_only(self):
        rendered = json.dumps(self.view)
        for forbidden in ("condition", "internal_scores", "actions", "model_identity"):
            self.assertNotIn(forbidden, rendered)
        versions = {
            row["candidate_id"]: row["version"]
            for row in self.view["scientific_content"]["candidates"]
        }
        self.assertEqual(versions, {"candidate-1": 2, "candidate-2": 1})
        self.assertEqual(self.view["schema_version"], "1.0.0")
        self.assertEqual(
            self.view["scientific_content"]["resources"], self.packet["resources"]
        )
        self.assertIn("confirmed_scope", self.view["scientific_content"])
        self.assertIn("requirements", self.view["scientific_content"]["candidates"][0])
        self.assertEqual(
            self.action["content_assessment_sha256"], canonical_hash(self.content)
        )
        self.assertIn("latest_dispositions", self.action["action_record"])
        retained = self.action["candidate_revision_history"]
        candidate_one = [
            row for row in retained if row["candidate_id"] == "candidate-1"
        ]
        self.assertEqual([row["version"] for row in candidate_one], [1, 2])
        self.assertEqual(
            candidate_one[0]["opportunity"],
            "A controlled source identifies an unresolved measurement issue.",
        )
        self.assertEqual(candidate_one[0]["evidence_ids"], ["ev-1"])

    def test_stage2_content_before_action(self):
        broken = copy.deepcopy(self.content)
        broken["content_view_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            Stage2Error, "content assessment content_view_sha256 mismatch"
        ):
            prepare_action_view(
                self.packet, self.view, broken, action_record(self.packet)
            )
        broken = content_assessment(self.view, evidence_ids=["missing"])
        with self.assertRaisesRegex(Stage2Error, "unknown evidence"):
            validate_content_assessment(broken, self.view, self.packet)
        invalid_actions = action_record(self.packet)
        invalid_actions["latest_dispositions"].pop()
        with self.assertRaisesRegex(Stage2Error, "latest dispositions"):
            prepare_action_view(self.packet, self.view, self.content, invalid_actions)
        invalid_actions = action_record(self.packet)
        invalid_actions["latest_dispositions"][0]["evidence_ids"] = []
        with self.assertRaisesRegex(Stage2Error, "lacks source evidence"):
            prepare_action_view(self.packet, self.view, self.content, invalid_actions)
        tampered_action = copy.deepcopy(self.action)
        tampered_action["candidate_revision_history"][0]["opportunity"] = (
            "Rewritten old candidate text."
        )
        tampered_output = judge(self.view, tampered_action, self.packet)
        with self.assertRaisesRegex(Stage2Error, "version-locked admitted view"):
            validate_judge_output(
                tampered_output, self.view, tampered_action, self.packet
            )

    def test_independent_content_assessments_and_action_views_merge(self):
        r2_content = content_assessment(
            self.view,
            statement="A second independent wording reaches the same source-bound finding.",
        )
        r2_action = prepare_action_view(
            self.packet, self.view, r2_content, action_record(self.packet)
        )
        self.assertNotEqual(canonical_hash(self.action), canonical_hash(r2_action))
        r1 = judge(self.view, self.action, self.packet, "R1")
        r2 = judge(self.view, r2_action, self.packet, "R2")
        bundle = merge_judgments(
            r1,
            r2,
            self.view,
            self.action,
            self.packet,
            action_view_r2=r2_action,
        )
        self.assertTrue(bundle["usable"])
        self.assertNotEqual(
            bundle["action_view_sha256s"]["R1"],
            bundle["action_view_sha256s"]["R2"],
        )
        self.assertEqual(
            bundle["raw"]["action_view_r2"]["content_assessment"], r2_content
        )

    def test_nondefault_rubric_override_is_rejected(self):
        alternate = self.root / "alternate-rubric.json"
        alternate.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "custom Stage 2 rubrics"):
            prepare_content_view(
                self.packet,
                "opaque-custom-rubric",
                "1" * 64,
                "2" * 64,
                rubric_path=alternate,
            )

    def test_rehash_tamper_rejected(self):
        original_hash = self.view["packet_sha256"]
        tampered = copy.deepcopy(self.packet)
        tampered["comparison"] = "Rewritten after view creation."
        self.assertNotEqual(canonical_hash(tampered), original_hash)
        output = judge(self.view, self.action, tampered)
        with self.assertRaisesRegex(
            Stage2Error, "version-locked allowlist|candidate coverage|packet_sha256"
        ):
            validate_judge_output(output, self.view, self.action, tampered)

    def test_stage2_unknown_distinct(self):
        output = judge(self.view, self.action, self.packet)
        output["criteria"][0].update(
            status="unknown",
            score=0,
            evidence_ids=[],
            unknown_reason="source-lookup-failure",
        )
        with self.assertRaisesRegex(Stage2Error, "unknown criterion needs null"):
            validate_judge_output(output, self.view, self.action, self.packet)
        failed = judge(self.view, self.action, self.packet, technical=True)
        failed["criteria"][0].update(
            status="assessed", score=0, evidence_ids=["ev-1"], unknown_reason=None
        )
        with self.assertRaisesRegex(Stage2Error, "technical failure cannot score"):
            validate_judge_output(failed, self.view, self.action, self.packet)
        r1 = judge(self.view, self.action, self.packet, "R1", technical=True)
        r2 = judge(self.view, self.action, self.packet, "R2", technical=True)
        r1["confidence"] = "low"
        bundle = merge_judgments(r1, r2, self.view, self.action, self.packet)
        self.assertFalse(bundle["usable"])
        self.assertEqual(bundle["audit_status"], "blocked-technical-failure")

    def test_disagreement_requires_adjudication_and_named_audit(self):
        r1 = judge(self.view, self.action, self.packet, "R1")
        r2 = judge(self.view, self.action, self.packet, "R2")
        r2["criteria"][1]["score"] = 2
        with self.assertRaisesRegex(Stage2Error, "requires ADJ"):
            merge_judgments(r1, r2, self.view, self.action, self.packet)
        adj_content = content_assessment(
            self.view,
            statement="The adjudicator independently rechecked the disputed criterion.",
        )
        adj_action = prepare_action_view(
            self.packet, self.view, adj_content, action_record(self.packet)
        )
        adj = judge(self.view, adj_action, self.packet, "ADJ")
        with self.assertRaisesRegex(Stage2Error, "named audit"):
            merge_judgments(
                r1,
                r2,
                self.view,
                self.action,
                self.packet,
                adj=adj,
                action_view_adj=adj_action,
            )
        adj["audit_required"] = True
        adj["audit_reasons"] = ["A major decision boundary needs human review."]
        adj["audit_status"] = "required"
        with self.assertRaisesRegex(Stage2Error, "named audit"):
            merge_judgments(
                r1,
                r2,
                self.view,
                self.action,
                self.packet,
                adj=adj,
                action_view_adj=adj_action,
            )
        audit = named_audit(adj)
        bundle = merge_judgments(
            r1,
            r2,
            self.view,
            self.action,
            self.packet,
            adj=adj,
            action_view_adj=adj_action,
            audit=audit,
        )
        self.assertTrue(bundle["usable"])
        self.assertEqual(bundle["audit_status"], "accepted")

    def _bundle(self, subject, p4, p5a, p5b, p6, *, unknown=False, major=None):
        packet = copy.deepcopy(self.packet)
        view = prepare_content_view(packet, subject, "1" * 64, "2" * 64)
        action = prepare_action_view(
            packet, view, content_assessment(view), action_record(packet)
        )
        scores = {
            CRITERIA[0]: p4,
            CRITERIA[1]: p5a,
            CRITERIA[2]: p5b,
            **{key: p6 for key in CRITERIA[3:]},
        }
        r1 = judge(view, action, packet, "R1", scores)
        r2 = judge(view, action, packet, "R2", scores)
        if unknown:
            for output in (r1, r2):
                output["criteria"][1].update(
                    status="unknown",
                    score=None,
                    evidence_ids=[],
                    unknown_reason="evidence-unavailable",
                )
        if major:
            for output in (r1, r2):
                output["major_error_ids"] = [major]
        return merge_judgments(
            r1,
            r2,
            view,
            action,
            packet,
            audit=named_audit(r1) if major else None,
        )

    def test_three_pair_rule_and_regression_major_error_unknown_guards(self):
        pairs = []
        for index, order in enumerate(("AB", "BA", "AB"), 1):
            baseline = self._bundle(f"a-{index}", 1, 1, 1, 1)
            treatment = self._bundle(f"b-{index}", 1, 2, 1, 2)
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
        result = compare_pairs(pairs)
        self.assertEqual(result["decision"], "diagnostic-improvement")
        self.assertEqual(result["pairs"][0]["B"]["P4"], 50.0)
        self.assertEqual(result["pairs"][0]["B"]["P5"], 75.0)
        self.assertEqual(result["pairs"][0]["B"]["P6"], 100.0)
        self.assertFalse(result["external_claim_ready"])
        self.assertEqual(result["formal_claim_status"], "rejected")
        repeated = copy.deepcopy(pairs)
        repeated[1]["A"] = repeated[0]["A"]
        repeated[1]["A_content_view_sha256"] = repeated[0]["A_content_view_sha256"]
        with self.assertRaisesRegex(Stage2Error, "subject reused"):
            compare_pairs(repeated)
        regressed = copy.deepcopy(pairs)
        regressed[0]["B"] = self._bundle("b-regress", 0, 2, 1, 2)
        regressed[0]["B_content_view_sha256"] = regressed[0]["B"]["content_view_sha256"]
        self.assertEqual(compare_pairs(regressed)["decision"], "not-improved")
        major = copy.deepcopy(pairs)
        major[0]["B"] = self._bundle("b-major", 1, 2, 1, 2, major="fabricated-evidence")
        major[0]["B_content_view_sha256"] = major[0]["B"]["content_view_sha256"]
        self.assertEqual(compare_pairs(major)["decision"], "not-improved")
        shared_major = copy.deepcopy(major)
        shared_major[0]["A"] = self._bundle(
            "a-major", 1, 1, 1, 1, major="fabricated-evidence"
        )
        shared_major[0]["A_content_view_sha256"] = shared_major[0]["A"][
            "content_view_sha256"
        ]
        self.assertEqual(compare_pairs(shared_major)["decision"], "inconclusive")
        unknown = copy.deepcopy(pairs)
        unknown[0]["B"] = self._bundle("b-unknown", 1, 2, 1, 2, unknown=True)
        unknown[0]["B_content_view_sha256"] = unknown[0]["B"]["content_view_sha256"]
        unknown_result = compare_pairs(unknown)
        self.assertEqual(unknown_result["decision"], "inconclusive")
        self.assertIsNone(unknown_result["pairs"][0]["B"]["P5"])
        self.assertEqual(unknown_result["pairs"][0]["B"]["P4"], 50.0)
        self.assertEqual(unknown_result["pairs"][0]["B"]["P6"], 100.0)
        forged = copy.deepcopy(pairs)
        forged[0]["B"]["criteria"][0]["score"] = 2
        with self.assertRaisesRegex(Stage2Error, "replayed raw judgments"):
            compare_pairs(forged)

    def test_stage2_disposition_independent(self):
        empty = write_stage2_fixture(self.root / "empty", candidate_count=0)
        validate_packet(empty, self.root / "empty")
        view = prepare_content_view(empty, "reject-all", "1" * 64, "2" * 64)
        action = prepare_action_view(
            empty, view, content_assessment(view), action_record(empty)
        )
        output = judge(view, action, empty)
        output["criteria"][5]["score"] = 0
        output["criteria"][6]["score"] = 0
        validate_judge_output(output, view, action, empty)
        self.assertEqual(output["candidate_coverage"], [])
        # A justified zero-candidate portfolio may independently receive 2;
        # count neither caps the criterion nor awards it automatically.
        output["criteria"][5]["score"] = 2
        output["criteria"][6]["score"] = 2
        validate_judge_output(output, view, action, empty)
        self.assertEqual(output["candidate_coverage"], [])

    def test_cli_prepare_content_smoke(self):
        packet_path = self.root / "packet.json"
        output_path = self.root / "view.json"
        assessment_path = self.root / "content-assessment.json"
        action_record_path = self.root / "action-record.json"
        action_path = self.root / "action-view.json"
        action_r2_path = self.root / "action-view-r2.json"
        r1_path = self.root / "r1.json"
        r2_path = self.root / "r2.json"
        bundle_path = self.root / "bundle.json"
        packet_path.write_text(json.dumps(self.packet), encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "stage2_eval",
                "prepare-content",
                "--packet",
                str(packet_path),
                "--source-root",
                str(self.root),
                "--subject-id",
                "opaque-cli",
                "--input-sha256",
                "1" * 64,
                "--config-sha256",
                "2" * 64,
                "--output",
                str(output_path),
            ],
            cwd=CLI,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            json.loads(output_path.read_text(encoding="utf-8"))["kind"],
            "Stage2ContentView",
        )
        cli_view = json.loads(output_path.read_text(encoding="utf-8"))
        assessment_path.write_text(
            json.dumps(content_assessment(cli_view)), encoding="utf-8"
        )
        action_record_path.write_text(
            json.dumps(action_record(self.packet)), encoding="utf-8"
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "stage2_eval",
                "prepare-action",
                "--packet",
                str(packet_path),
                "--source-root",
                str(self.root),
                "--content-view",
                str(output_path),
                "--content-assessment",
                str(assessment_path),
                "--action-record",
                str(action_record_path),
                "--output",
                str(action_path),
            ],
            cwd=CLI,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            json.loads(action_path.read_text(encoding="utf-8"))["kind"],
            "Stage2ActionView",
        )
        cli_action = json.loads(action_path.read_text(encoding="utf-8"))
        r2_content = content_assessment(
            cli_view, statement="Independent R2 content wording."
        )
        cli_action_r2 = prepare_action_view(
            self.packet, cli_view, r2_content, action_record(self.packet)
        )
        action_r2_path.write_text(json.dumps(cli_action_r2), encoding="utf-8")
        r1_path.write_text(
            json.dumps(judge(cli_view, cli_action, self.packet, "R1")),
            encoding="utf-8",
        )
        r2_path.write_text(
            json.dumps(judge(cli_view, cli_action_r2, self.packet, "R2")),
            encoding="utf-8",
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "stage2_eval",
                "merge",
                "--packet",
                str(packet_path),
                "--source-root",
                str(self.root),
                "--content-view",
                str(output_path),
                "--action-view",
                str(action_path),
                "--action-view-r2",
                str(action_r2_path),
                "--r1",
                str(r1_path),
                "--r2",
                str(r2_path),
                "--output",
                str(bundle_path),
            ],
            cwd=CLI,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        cli_bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        self.assertNotEqual(
            cli_bundle["action_view_sha256s"]["R1"],
            cli_bundle["action_view_sha256s"]["R2"],
        )


if __name__ == "__main__":
    unittest.main()
