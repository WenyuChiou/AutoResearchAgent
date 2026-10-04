# ruff: noqa: E402 -- load repository CLI and fixture helpers without installation.
"""End-to-end mechanics use explicit injected calls, never scientific live claims."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / "cli"),
    str(Path(__file__).resolve().parent),
]

from stage2_common import Stage2Error, canonical_hash
from stage2_check import initialize_run, inspect_run, apply_assessment
from stage2_check.run import build_selection
from stage2_live.daily_v3 import run_daily_evaluation_v3
from stage2_eval.evaluation_v3 import CRITERIA_V3
from stage2_workflow.evaluation_delivery import (
    build_evaluated_delivery,
    inspect_evaluated_delivery,
    evaluation_projection,
    _evaluated_html,
    _evaluation_markdown_fragment,
)
from stage2_fixture_helpers import write_stage2_fixture
from test_stage2_checker import assessment
from test_stage2_evaluation_v3 import content_assessment, judge


class DailyV3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # macOS /var is a system alias; fixtures use its physical temp location.
        self.root = Path(self.temp.name).resolve()
        private = patch(
            "stage2_workflow.evaluation_delivery.private_output",
            side_effect=lambda path: Path(path).absolute(),
        )
        private.start()
        self.addCleanup(private.stop)
        packet = write_stage2_fixture(self.root / "sources", candidate_count=1)
        packet["unresolved"] = []
        (self.root / "packet.json").write_text(json.dumps(packet))
        initialize_run(
            self.root / "packet.json",
            self.root / "sources",
            self.root / "checker",
            canonical_hash(packet),
        )
        (self.root / "assessment.json").write_text(json.dumps(assessment(packet)))
        apply_assessment(self.root / "checker", self.root / "assessment.json")
        self.state = inspect_run(self.root / "checker")
        self.selection = build_selection(self.state)
        self.packet = self.selection["evaluation_packet"]
        self.sources = self.root / "checker" / "sources"
        self.homes = {}
        for role in ("r1", "r2", "adj"):
            self.homes[role] = self.root / role
            self.homes[role].mkdir()
        self.calls = []

    def run_judges(
        self, *, disagree=False, fail=False, fail_label=None, source_context_policy=None
    ):
        self.disagree = disagree
        self.prompts = {}

        def unit(**kwargs):
            self.calls.append(kwargs["label"])
            self.prompts[kwargs["label"]] = kwargs["prompt"]
            payload, _ = json.JSONDecoder().raw_decode(
                kwargs["prompt"].split("\n", 1)[1]
            )
            view = payload["content_view"]
            if kwargs["label"].endswith("content"):
                result = content_assessment(view)
            else:
                if fail or kwargs["label"] == fail_label:
                    raise Stage2Error("synthetic evaluator transport failed")
                role = payload["role"]
                scores = {
                    key: 1 if disagree and role == "R2" else 2 for key in CRITERIA_V3
                }
                result = judge(view, payload["action_view"], self.packet, role, scores)
            kwargs["validate"](result)
            return result, {"injected": True}

        with (
            patch("stage2_live.daily_v3.codex_runtime_sha", return_value="a" * 64),
            patch("stage2_live.daily_v3._run_unit", side_effect=unit),
        ):
            return run_daily_evaluation_v3(
                self.selection,
                self.sources,
                codex="synthetic-codex",
                r1_home=self.homes["r1"],
                r2_home=self.homes["r2"],
                adj_home=self.homes["adj"],
                model="test-model",
                reasoning="high",
                execution_policy={},
                output_dir=self.root / "judges",
                call_adapter=lambda: None,
                source_context_policy=source_context_policy,
            )

    def delivery(self, bundle):
        snapshots = [
            {**row, "path": "sources/" + row["path"]} for row in self.packet["sources"]
        ]
        return build_evaluated_delivery(
            self.selection,
            snapshots,
            self.sources,
            bundle,
            self.root / "delivery",
            expected_bundle_sha256=canonical_hash(bundle),
            event_head=self.state["event_head_sha256"],
            stored_packet_sha256=self.state["manifest"]["stored_packet_sha256"],
        )

    def test_regular_selection_automatically_scores_and_renders(self):
        bundle = self.run_judges()
        self.assertEqual(
            self.calls, ["r1-content", "r1-judge", "r2-content", "r2-judge"]
        )
        manifest = self.delivery(bundle)
        inspect_evaluated_delivery(
            self.root / "delivery", expected_manifest_sha256=manifest["manifest_sha256"]
        )
        html = (self.root / "delivery" / "selection.html").read_text(encoding="utf-8")
        self.assertIn("P4V3.FIDELITY", html)
        self.assertIn("R1 source-bound comment", html)
        self.assertIn("R2 source-bound comment", html)
        self.assertLess(
            html.index('id="summary"'), html.index('id="evaluation-overview"')
        )
        self.assertLess(
            html.index('id="evaluation-overview"'), html.index('id="brief"')
        )
        self.assertIn("100% (6/6)", html)
        self.assertEqual(manifest["presentation_version"], "1.2.0")
        self.assertFalse(manifest["stage3_authorized"])
        self.assertFalse(bundle["improvement_demonstrated"])

    def test_disagreement_keeps_comments_and_pending_real_audit(self):
        bundle = self.run_judges(disagree=True)
        self.assertEqual(self.calls[-2:], ["adj-content", "adj-judge"])
        self.assertEqual(bundle["status"], "audit-required")
        self.assertIsNone(bundle["merged"])
        manifest = self.delivery(bundle)
        view = json.loads(
            (self.root / "delivery" / "evaluation_projection.json").read_bytes()
        )
        self.assertEqual(view["rows"][0]["final"]["audit_status"], "required")
        self.assertEqual(view["evaluation_status"], "audit-required")
        self.assertEqual(view["rows"][0]["judges"]["R2"]["score"], 1)
        self.assertFalse(manifest["formal_ready"])
        html = (self.root / "delivery" / "selection.html").read_text(encoding="utf-8")
        self.assertIn("the required named audit is pending", html)
        self.assertEqual(html.count("<dt>Provisional score</dt>"), 9)
        self.assertNotIn("<dt>Final score</dt>", html)
        markdown = (self.root / "delivery" / "selection.md").read_text(encoding="utf-8")
        self.assertEqual(markdown.count("- Provisional score:"), 9)
        self.assertNotIn("- Final score:", markdown)

    def test_v11_pending_audit_receipt_replays_without_rescoring(self):
        bundle = self.run_judges(disagree=True)
        manifest = self.delivery(bundle)
        root = self.root / "delivery"
        snapshots = [
            {**row, "path": "sources/" + row["path"]} for row in self.packet["sources"]
        ]
        view = evaluation_projection(
            bundle,
            self.selection,
            self.sources,
            expected_bundle_sha256=canonical_hash(bundle),
        )
        current_markdown = (root / "selection.md").read_bytes()
        new_fragment = _evaluation_markdown_fragment(view, "1.2.0").encode()
        self.assertTrue(current_markdown.endswith(new_fragment))
        old_markdown = current_markdown[: -len(new_fragment)] + (
            _evaluation_markdown_fragment(view, "1.1.0").encode()
        )
        old_html = _evaluated_html(self.selection, snapshots, view, "1.1.0").encode()
        self.assertIn(b"<dt>Final score</dt>", old_html)
        self.assertIn(b"- Final score:", old_markdown)
        values = {"selection.html": old_html, "selection.md": old_markdown}
        for name, raw in values.items():
            (root / name).write_bytes(raw)
        for row in manifest["artifacts"]:
            if row["path"] in values:
                raw = values[row["path"]]
                row.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        manifest["presentation_version"] = "1.1.0"
        manifest.pop("manifest_sha256")
        manifest["manifest_sha256"] = canonical_hash(manifest)
        (root / "evaluation_manifest.json").write_text(json.dumps(manifest))
        inspect_evaluated_delivery(
            root, expected_manifest_sha256=manifest["manifest_sha256"]
        )
        self.assertEqual(len(self.calls), 6)

    def test_provisional_labels_preserve_quoted_original_comment(self):
        bundle = self.run_judges(disagree=True)
        view = evaluation_projection(
            bundle,
            self.selection,
            self.sources,
            expected_bundle_sha256=canonical_hash(bundle),
        )
        quote = (
            "Original quoted label - Final score: 2; - Final status: assessed; "
            "- Final rationale: evidence."
        )
        view["rows"][0]["judges"]["R1"]["rationale"] = quote
        old = _evaluation_markdown_fragment(view, "1.1.0")
        new = _evaluation_markdown_fragment(view, "1.2.0")
        old_comment = next(line for line in old.splitlines() if quote[:21] in line)
        self.assertIn(old_comment, new.splitlines())
        self.assertEqual(
            sum(line.startswith("- Provisional score:") for line in new.splitlines()), 9
        )

    def test_failure_still_delivers_readable_research_without_zero(self):
        bundle = self.run_judges(fail=True)
        self.assertEqual(bundle["status"], "failed")
        self.delivery(bundle)
        view = json.loads(
            (self.root / "delivery" / "evaluation_projection.json").read_bytes()
        )
        self.assertIsNone(view["dimensions"]["P4"]["score"])
        html = (self.root / "delivery" / "selection.html").read_text(encoding="utf-8")
        overview = html.split('id="evaluation-overview"', 1)[1].split("</section>", 1)[
            0
        ]
        self.assertIn("Unknown", overview)
        self.assertNotIn("0%", overview)
        self.assertIn(
            "Evaluation not completed",
            (self.root / "delivery" / "selection.html").read_text(),
        )

    def test_legacy_presentation_receipt_replays_without_new_judge_calls(self):
        bundle = self.run_judges()
        manifest = self.delivery(bundle)
        root = self.root / "delivery"
        snapshots = [
            {**row, "path": "sources/" + row["path"]} for row in self.packet["sources"]
        ]
        projection = evaluation_projection(
            bundle,
            self.selection,
            self.sources,
            expected_bundle_sha256=canonical_hash(bundle),
        )
        legacy = _evaluated_html(
            self.selection, snapshots, projection, "1.0.0"
        ).encode()
        self.assertNotIn(b'id="evaluation-overview"', legacy)
        (root / "selection.html").write_bytes(legacy)
        manifest.pop("presentation_version")
        for row in manifest["artifacts"]:
            if row["path"] == "selection.html":
                row.update(sha256=hashlib.sha256(legacy).hexdigest(), bytes=len(legacy))
        manifest.pop("manifest_sha256")
        manifest["manifest_sha256"] = canonical_hash(manifest)
        (root / "evaluation_manifest.json").write_text(json.dumps(manifest))
        inspect_evaluated_delivery(
            root, expected_manifest_sha256=manifest["manifest_sha256"]
        )
        self.assertEqual(len(self.calls), 4)

    def test_r2_failure_retains_all_r1_comments(self):
        bundle = self.run_judges(fail_label="r2-judge")
        self.assertEqual(bundle["status"], "failed")
        self.assertEqual(set(bundle["judgments"]), {"R1"})
        expected = {
            row["criterion_id"]: row["rationale"]
            for row in bundle["judgments"]["R1"]["criteria"]
        }
        self.delivery(bundle)
        view = json.loads(
            (self.root / "delivery" / "evaluation_projection.json").read_bytes()
        )
        self.assertEqual(len(view["rows"]), 9)
        self.assertTrue(
            all(
                row["judges"]["R1"]["rationale"] == expected[row["criterion_id"]]
                and row["judges"]["R2"] is None
                for row in view["rows"]
            )
        )

    def test_rehashed_audit_bypass_is_rejected(self):
        bundle = self.run_judges(disagree=True)
        forged = copy.deepcopy(bundle)
        forged["status"] = "complete"
        self.assertIsNone(forged["merged"])
        with self.assertRaisesRegex(Stage2Error, "complete-needs-validated-merge"):
            evaluation_projection(
                forged,
                self.selection,
                self.sources,
                expected_bundle_sha256=canonical_hash(forged),
            )

    def test_science_change_and_rehashed_tamper_rejected(self):
        bundle = self.run_judges()
        manifest = self.delivery(bundle)
        forged = copy.deepcopy(bundle)
        forged["core_selection_sha256"] = "0" * 64
        with self.assertRaisesRegex(Stage2Error, "science-binding"):
            evaluation_projection(
                forged,
                self.selection,
                self.sources,
                expected_bundle_sha256=canonical_hash(forged),
            )
        (self.root / "delivery" / "selection.html").write_text("Tampered report")
        with self.assertRaisesRegex(Stage2Error, "artifact-changed"):
            inspect_evaluated_delivery(
                self.root / "delivery",
                expected_manifest_sha256=manifest["manifest_sha256"],
            )


if __name__ == "__main__":
    unittest.main()
