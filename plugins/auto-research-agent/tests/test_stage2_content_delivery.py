"""Synthetic full import/research/extraction/check/judge/Wiki binding, not live quality."""
# ruff: noqa: E402 -- load repository CLI and synthetic fixture helpers.

import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "cli")]

from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_check import initialize_run, inspect_run, apply_assessment  # noqa: E402
from stage2_check.run import build_selection  # noqa: E402
from stage2_eval.evaluation_v3 import (  # noqa: E402
    prepare_content_view_v3,
    prepare_action_view_v3,
    merge_judgments_v3,
)
from stage2_workflow.evaluation_delivery import (
    build_evaluated_delivery,
    inspect_evaluated_delivery,
)  # noqa: E402
from research_workspace.stage2_presentation import render_stage2_card  # noqa: E402
import test_stage2_topic_tables_integration as topic_fixture  # noqa: E402
from test_stage2_checker import assessment  # noqa: E402
from test_stage2_evaluation_v3 import content_assessment, judge  # noqa: E402


class ContentDeliveryTests(unittest.TestCase):
    def setUp(self):
        upstream = topic_fixture.Stage2TopicTablesIntegrationTests()
        upstream.setUp()
        self.addCleanup(upstream.doCleanups)
        self.root = upstream.root
        self.sources = upstream.sources
        packet, _ = upstream.prepared()
        source_id = packet["evidence"][0]["evidence_id"]
        path = self.root / "content-packet.json"
        path.write_text(json.dumps(packet), encoding="utf-8")
        checker = self.root / "content-checker"
        initialize_run(path, self.sources, checker, canonical_hash(packet))
        check = assessment(packet, disposition="park")
        check["candidate_id"] = packet["candidates"][0]["candidate_id"]
        for finding in check["checks"].values():
            finding["evidence_ids"] = [source_id]
        check_path = self.root / "check.json"
        check_path.write_text(json.dumps(check), encoding="utf-8")
        apply_assessment(checker, check_path)
        self.state = inspect_run(checker)
        self.selection = build_selection(self.state)
        self.sources = checker / "sources"
        self.bundle = self.make_bundle(self.selection)

    def make_bundle(self, selection):
        packet = selection["evaluation_packet"]
        evidence_id = packet["evidence"][0]["evidence_id"]
        content = prepare_content_view_v3(
            packet, "anonymous", canonical_hash(selection), "a" * 64
        )
        initial = content_assessment(content, evidence_ids=[evidence_id])
        action = prepare_action_view_v3(
            packet, content, initial, selection["action_record"]
        )
        judgments = {
            role: judge(content, action, packet, role) for role in ("R1", "R2")
        }
        for judgment in judgments.values():
            for row in judgment["criteria"]:
                row["evidence_ids"] = [evidence_id]
        merged = merge_judgments_v3(
            judgments["R1"], judgments["R2"], content, action, packet
        )
        return {
            "kind": "Stage2EvaluationBundle",
            "schema_version": "3.0.0",
            "status": "complete",
            "core_selection_sha256": canonical_hash(selection),
            "sources_sha256": canonical_hash(packet["sources"]),
            "rubric_sha256": content["rubric_sha256"],
            "content_view": content,
            "judgments": judgments,
            "action_views": {role: action for role in judgments},
            "merged": merged,
        }

    def deliver(self, selection=None, bundle=None):
        selection = selection or self.selection
        snapshots = [
            {**row, "path": "sources/" + row["path"]}
            for row in selection["evaluation_packet"]["sources"]
        ]
        return build_evaluated_delivery(
            selection,
            snapshots,
            self.sources,
            bundle or self.bundle,
            self.root / "evaluated",
            expected_bundle_sha256=canonical_hash(bundle or self.bundle),
            event_head=self.state["event_head_sha256"],
            stored_packet_sha256=self.state["manifest"]["stored_packet_sha256"],
        )

    def test_import_to_evaluated_reports_and_wiki_use_same_gate(self):
        manifest = self.deliver()
        self.assertEqual(manifest["presentation_version"], "1.3.0")
        inspect_evaluated_delivery(
            self.root / "evaluated",
            expected_manifest_sha256=manifest["manifest_sha256"],
        )
        gate = json.loads((self.root / "evaluated/content_gate.json").read_bytes())
        self.assertEqual(gate["status"], "content-complete")
        self.assertFalse(gate["scientific_truth_validated"])
        evaluation = json.loads(
            (self.root / "evaluated/evaluation_projection.json").read_bytes()
        )
        wiki = render_stage2_card(
            {"selection": self.selection, "evaluation": evaluation}
        )
        self.assertIn("Selection package: content-complete", wiki)
        self.assertIn("Scenario representation", wiki)
        self.assertIn("Synthetic dataset", wiki)
        for filename in ("selection.html", "selection.md"):
            document = (self.root / "evaluated" / filename).read_text(encoding="utf-8")
            self.assertIn("content-complete", document)
            self.assertIn("Scenario representation", document)
            self.assertIn("R1 source-bound comment", document.replace("\\", ""))

    def test_draft_can_be_previewed_without_promoting_missing_matrix(self):
        # The scientifically changed packet needs a new action/assessment binding.
        selection = copy.deepcopy(self.selection)
        selection["evaluation_packet"]["research_tables"] = None
        packet = selection["evaluation_packet"]
        selection["action_record"]["packet_sha256"] = canonical_hash(packet)
        selection["current_options"][0]["assessment"]["packet_sha256"] = canonical_hash(
            packet
        )
        bundle = self.make_bundle(selection)
        manifest = self.deliver(selection, bundle)
        gate = json.loads((self.root / "evaluated/content_gate.json").read_bytes())
        self.assertEqual(gate["status"], "draft")
        self.assertFalse(manifest["formal_ready"])
        self.assertIn(
            "topic-matrix", {row["check_id"] for row in gate["blocking_items"]}
        )

    def test_matrix_change_cannot_reuse_old_scores(self):
        altered = copy.deepcopy(self.selection)
        altered["evaluation_packet"]["comparison"] += " Changed scientific content."
        with self.assertRaisesRegex(Stage2Error, "science-binding-mismatch"):
            self.deliver(altered)

    def test_rebuilt_scores_cannot_make_foreign_assessment_content_complete(self):
        selection = copy.deepcopy(self.selection)
        selection["current_options"][0]["assessment"]["packet_sha256"] = "b" * 64
        manifest = self.deliver(selection, self.make_bundle(selection))
        inspect_evaluated_delivery(
            self.root / "evaluated",
            expected_manifest_sha256=manifest["manifest_sha256"],
        )
        gate = json.loads((self.root / "evaluated/content_gate.json").read_bytes())
        self.assertEqual(gate["status"], "draft")

    def test_rebuilt_scores_cannot_hide_contradictory_shortlist(self):
        selection = copy.deepcopy(self.selection)
        selection["action_record"]["selected_candidate_ids"] = [
            selection["current_options"][0]["candidate"]["candidate_id"]
        ]
        manifest = self.deliver(selection, self.make_bundle(selection))
        inspect_evaluated_delivery(
            self.root / "evaluated",
            expected_manifest_sha256=manifest["manifest_sha256"],
        )
        gate = json.loads((self.root / "evaluated/content_gate.json").read_bytes())
        self.assertEqual(gate["status"], "draft")

    def test_rehashed_fake_complete_gate_is_rejected(self):
        manifest = self.deliver()
        root = self.root / "evaluated"
        gate_path = root / "content_gate.json"
        gate = json.loads(gate_path.read_bytes())
        gate["scientific_truth_validated"] = True
        raw = json.dumps(gate).encode()
        gate_path.write_bytes(raw)
        for row in manifest["artifacts"]:
            if row["path"] == "content_gate.json":
                row.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        manifest.pop("manifest_sha256")
        manifest["manifest_sha256"] = canonical_hash(manifest)
        (root / "evaluation_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        with self.assertRaisesRegex(Stage2Error, "content-gate-changed"):
            inspect_evaluated_delivery(
                root, expected_manifest_sha256=manifest["manifest_sha256"]
            )

    def test_missing_gate_or_downgraded_presentation_cannot_bypass_reconstruction(self):
        manifest = self.deliver()
        manifest["presentation_version"] = "1.2.0"
        manifest.pop("manifest_sha256")
        manifest["manifest_sha256"] = canonical_hash(manifest)
        (self.root / "evaluated/evaluation_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        with self.assertRaisesRegex(Stage2Error, "unexpected-content-gate"):
            inspect_evaluated_delivery(
                self.root / "evaluated",
                expected_manifest_sha256=manifest["manifest_sha256"],
            )


if __name__ == "__main__":
    unittest.main()
