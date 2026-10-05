"""Verified Stage 2 reading imports; synthetic calls cannot prove research quality."""

from copy import deepcopy
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import test_stage2_daily_v3 as daily_fixture
from test_research_workspace_view import fixture_index
from stage1_deliverable.common import DeliverableError, canonical, sha
from stage2_common import Stage2Error
from research_workspace.stage2_import import (
    import_evaluated_delivery,
    prepare_stage2_bridge,
)
from research_workspace.view import REFERENCE_HASHES, write_workspace


class WorkspaceStage2ImportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = daily_fixture.DailyV3Tests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.manifest = self.fixture.delivery(self.fixture.run_judges())
        self.delivery = self.fixture.root / "delivery"
        self.index = fixture_index()
        self.bridge = prepare_stage2_bridge(
            self.index,
            self.delivery,
            expected_manifest_sha256=self.manifest["manifest_sha256"],
        )
        self.bridge_sha = sha(canonical(self.bridge))

    def import_delivery(self):
        return import_evaluated_delivery(
            self.index,
            self.delivery,
            self.bridge,
            expected_bridge_sha256=self.bridge_sha,
        )

    def test_import_keeps_index_and_all_scores_comments_and_source_bytes(self):
        before = deepcopy(self.index)
        attachment, files = self.import_delivery()
        self.assertEqual(self.index, before)
        self.assertEqual(attachment["project_id"], self.index["project_id"])
        self.assertEqual(len(attachment["evaluation"]["rows"]), 9)
        self.assertIn("R1 source-bound comment", str(attachment["evaluation"]))
        for row in self.manifest["artifacts"]:
            self.assertEqual(
                files["stage2/" + row["path"]],
                (self.delivery / row["path"]).read_bytes(),
            )
        self.assertFalse(attachment["bridge_receipt"]["formal_ready"])
        self.assertFalse(
            attachment["bridge_receipt"]["original_stage1_lineage_attested"]
        )

    def test_equal_topic_other_project_and_changed_index_reject(self):
        for field, value in (("project_id", "other-project"), ("as_of", "2026-10-05")):
            with self.subTest(field=field):
                before = deepcopy(self.index)
                self.index[field] = value
                with self.assertRaisesRegex(DeliverableError, "version differs"):
                    self.import_delivery()
                self.index = before

    def test_external_receipt_and_rehashed_project_or_extra_fields_reject(self):
        self.bridge["project_id"] = "wrong"
        with self.assertRaisesRegex(DeliverableError, "external bridge"):
            self.import_delivery()
        self.bridge_sha = sha(canonical(self.bridge))
        with self.assertRaisesRegex(DeliverableError, "version differs"):
            self.import_delivery()
        self.bridge["project_id"] = self.index["project_id"]
        self.bridge["accepted_by"] = "invented"
        self.bridge_sha = sha(canonical(self.bridge))
        with self.assertRaisesRegex(DeliverableError, "version differs"):
            self.import_delivery()

    def test_tampered_report_or_wrong_original_manifest_reject(self):
        with self.assertRaises(Stage2Error):
            prepare_stage2_bridge(
                self.index, self.delivery, expected_manifest_sha256="0" * 64
            )
        (self.delivery / "selection.html").write_bytes(b"tampered report")
        with self.assertRaises(Stage2Error):
            self.import_delivery()

    def test_partial_import_parameters_fail_before_any_output_or_asset_read(self):
        destination = self.fixture.root / "workspace"
        with patch("research_workspace.view.safe_path") as path_read:
            with self.assertRaisesRegex(DeliverableError, "receipt hash are required"):
                write_workspace(
                    self.index, ".", destination, stage2_delivery=self.delivery
                )
        path_read.assert_not_called()
        self.assertFalse(destination.exists())

    def test_pending_audit_and_failed_judging_stay_unresolved_in_real_import(self):
        for options, status in (
            ({"disagree": True}, "audit-required"),
            ({"fail_label": "r2-judge"}, "failed"),
        ):
            with self.subTest(status=status):
                fixture = daily_fixture.DailyV3Tests()
                fixture.setUp()
                self.addCleanup(fixture.doCleanups)
                manifest = fixture.delivery(fixture.run_judges(**options))
                directory = fixture.root / "delivery"
                bridge = prepare_stage2_bridge(
                    self.index,
                    directory,
                    expected_manifest_sha256=manifest["manifest_sha256"],
                )
                attachment, _ = import_evaluated_delivery(
                    self.index,
                    directory,
                    bridge,
                    expected_bridge_sha256=sha(canonical(bridge)),
                )
                evaluation = attachment["evaluation"]
                self.assertEqual(evaluation["evaluation_status"], status)
                self.assertEqual(len(evaluation["rows"]), 9)
                self.assertFalse(attachment["bridge_receipt"]["formal_ready"])
                if status == "failed":
                    from research_workspace.stage2_presentation import (
                        render_stage2_card,
                    )

                    rendered = render_stage2_card(attachment)
                    self.assertIn("Incomplete assessment", rendered)
                    self.assertNotIn("Final recorded evaluation", rendered)
                    for row in evaluation["rows"]:
                        self.assertIn(row["judges"]["R1"]["rationale"], rendered)
                    self.assertIsNone(evaluation["dimensions"]["P4"]["score"])
                    self.assertTrue(
                        all(
                            row["judges"]["R1"] is not None
                            and row["judges"]["R2"] is None
                            for row in evaluation["rows"]
                        )
                    )
                else:
                    self.assertTrue(
                        all(
                            row["judges"]["ADJ"] is not None
                            and row["final"]["audit_status"] == "required"
                            for row in evaluation["rows"]
                        )
                    )

    def test_workspace_import_copies_verified_proposal_and_notes_with_bound_receipt(
        self,
    ):
        checkout = self.fixture.root / "checkout"
        command = ["git", "-c", "core.autocrlf=true", "checkout-index"]
        command.extend([f"--prefix={checkout.as_posix()}/", "--"])
        asset_dir = "plugins/auto-research-agent/references/research-workspace"
        command.extend(f"{asset_dir}/{name}" for name in REFERENCE_HASHES)
        subprocess.run(command, cwd=Path(__file__).parents[3], check=True)
        reference = checkout / asset_dir
        destination = self.fixture.root / "workspace"
        receipt = write_workspace(
            self.index,
            reference,
            destination,
            stage2_delivery=self.delivery,
            stage2_bridge=self.bridge,
            expected_stage2_bridge_sha256=self.bridge_sha,
        )
        html = (destination / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="stage2-delivery"', html)
        self.assertIn("stage2/report-reader.html", html)
        self.assertIn("R1 source-bound comment", html)
        self.assertEqual(
            (destination / "stage2/selection.html").read_bytes(),
            (self.delivery / "selection.html").read_bytes(),
        )
        self.assertEqual(
            receipt["stage2_attachment"]["bridge_receipt_sha256"], self.bridge_sha
        )
        self.assertFalse(receipt["stage2_attachment"]["stage3_authorized"])
        for name, digest in receipt["files"].items():
            self.assertEqual(sha((destination / name).read_bytes()), digest)
