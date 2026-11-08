"""Offline consumer regressions; authored observations confer no acceptance.

Core cases use checkpoint-generated 1.2 records without editing their exports.
The workspace reading case is an explicit synthetic projection fragment: its
2.7 version switch is not full Core admission, live HTML or scientific evidence.
"""
# ruff: noqa: E402 -- repository CLI and authored fixture imports.

from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import shutil
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "cli"), str(HERE)]

from current_core_stage12_fixtures import current_core_stage1_case
from research_workspace.stage2_comparison import build_comparison_view
from research_workspace.stage2_presentation import render_stage2_card
from stage1_deliverable.common import read_json, sha
from stage2_check import export_selection, initialize_run
from stage2_common import Stage2Error, canonical_hash, validate_packet
from stage2_ideation import build_extraction_task, validate_extraction
from stage2_ideation.__main__ import main
from stage2_ideation.report import _evidence_view
from stage2_live.controller import materialize_snapshot_input_root
from stage2_workflow import initialize_workflow, inspect_workflow
from stage2_workflow.import_stage1 import build_stage2_seed
import test_stage2_ideation_report as legacy_report
import test_stage2_literature_versions as literature_versions
import test_stage2_prior_work as prior_work


class CoreConsumerBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stack = ExitStack()
        cls.addClassCleanup(stack.close)
        cls.fixture = stack.enter_context(
            current_core_stage1_case(
                screened=True,
                metadata_observation=True,
            )
        )
        f = cls.fixture
        cls.root, cls.seed_root = f["root"], f["root"] / "consumer-seed"
        build_stage2_seed(
            f["deliverable_dir"],
            f["manifest_sha256"],
            f["handoff_path"],
            f["handoff_sha256"],
            f["brief_path"],
            f["resources_path"],
            cls.seed_root,
            allow_current_core=True,
        )
        cls.packet = read_json(cls.seed_root / "packet.json")
        workflow = cls.root / "consumer-workflow"
        initialize_workflow(
            cls.seed_root / "packet.json",
            cls.seed_root,
            workflow,
            {},
            {},
            expected_packet_sha256=canonical_hash(cls.packet),
        )
        cls.snapshot = inspect_workflow(workflow)["latest_snapshot"]
        # The source association is observed from the real producer output.
        cls.null_observations = [
            row for row in cls.packet["evidence"] if row["source_id"] is None
        ]
        if not cls.null_observations:
            raise AssertionError(
                "Discovery metadata did not yield a nullable source ID"
            )

    def test_controller_copies_reopens_and_guards_complete_core_closure(self):
        snapshot = deepcopy(self.snapshot)
        controller = self.root / "controller-materialization"
        materialized = materialize_snapshot_input_root(snapshot, controller)
        validate_packet(snapshot["packet"], materialized)
        refs = snapshot["packet"]["core_source"]["files"]
        expected = {
            r["path"]: (snapshot["checker"]["root"] / r["path"]).read_bytes()
            for r in refs
        }
        self.assertEqual(
            {name: (materialized / name).read_bytes() for name in expected}, expected
        )
        self.assertEqual(
            materialize_snapshot_input_root(snapshot, controller, create=False),
            materialized,
        )
        path = materialized / refs[0]["path"]
        raw = path.read_bytes()
        path.unlink()
        try:
            with self.assertRaises(Stage2Error):
                materialize_snapshot_input_root(snapshot, controller, create=False)
        finally:
            path.write_bytes(raw)
        # Attack a private checker copy, including its advertised outer hash;
        # the original Core archive's inner bindings must still reject it.
        changed = deepcopy(snapshot)
        clone = self.root / "owned-tampered-checker"
        shutil.copytree(snapshot["checker"]["root"], clone)
        changed["checker"]["root"] = clone
        artifact = next(r for r in refs if "/core_claim_artifacts/" in r["path"])
        target = clone / artifact["path"]
        target.write_bytes(target.read_bytes() + b"\nAuthored tamper.\n")
        for packet in (changed["packet"], changed["checker"]["packet"]):
            next(
                r
                for r in packet["core_source"]["files"]
                if r["path"] == artifact["path"]
            )["sha256"] = sha(target.read_bytes())
        with self.assertRaises(Stage2Error):
            materialize_snapshot_input_root(changed, self.root / "controller-tamper")
        collision = deepcopy(snapshot)
        collision["checker"]["manifest"]["source_snapshots"][0]["original_path"] = refs[
            0
        ]["path"]
        with self.assertRaisesRegex(Stage2Error, "path-conflict|collision|namespace"):
            materialize_snapshot_input_root(
                collision, self.root / "controller-collision"
            )

    def test_public_draft_export_retains_nullable_core_observations(self):
        raw = "Authored offline empty draft; research and scientific acceptance remain pending."
        snapshot_sha = self.snapshot["event"]["payload"]["snapshot_sha256"]
        task = build_extraction_task(raw, self.packet, snapshot_sha)
        extraction = {
            "kind": "Stage2IdeationExtraction",
            "schema_version": task["schema_version"],
            **{
                key: task[key]
                for key in ("packet_sha256", "raw_proposal_sha256", "input_hash")
            },
            "snapshot_sha256": snapshot_sha,
            "receipt": {
                "policy_boundary": "declared-task-policy",
                "tools_policy": "none",
                "tool_calls": [],
                "isolation_verified": False,
            },
            "bibliography": [],
            "comparison_rows": [],
            "candidates": [],
            "unresolved": ["No independent research acceptance is asserted."],
            "research_tables": None,
        }
        validate_extraction(raw, extraction, self.packet, snapshot_sha)
        inputs = self.root / "authored-draft"
        inputs.mkdir()
        (inputs / "raw.md").write_text(raw, encoding="utf-8")
        (inputs / "extraction.json").write_text(
            json.dumps(extraction), encoding="utf-8"
        )
        output = inputs / "export"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(
                main(
                    [
                        "report",
                        "--packet",
                        str(self.seed_root / "packet.json"),
                        "--source-root",
                        str(self.seed_root),
                        "--raw-proposal",
                        str(inputs / "raw.md"),
                        "--extraction",
                        str(inputs / "extraction.json"),
                        "--snapshot-sha256",
                        snapshot_sha,
                        "--output",
                        str(output),
                    ]
                ),
                0,
            )
        view = read_json(output / "proposal-view.json")
        sources = {row["source_id"]: row for row in self.packet["sources"]}
        for original, projected in zip(self.packet["evidence"], view["evidence"]):
            for key, value in original.items():
                self.assertEqual(projected[key], value, key)
            physical = sources.get(original["source_id"])
            self.assertEqual(
                projected["physical_source_access"],
                None
                if physical is None
                else {
                    "source_id": physical["source_id"],
                    "sha256": physical["sha256"],
                    "evidence_level": physical["evidence_level"],
                },
            )
        self.assertTrue(any(row["quote"] is not None for row in view["evidence"]))
        for name in ("proposal.md", "proposal.html"):
            rendered = (output / name).read_text(encoding="utf-8")
            self.assertIn("Unavailable in the original Core observation", rendered)
            self.assertNotIn(">None<", rendered)
            self.assertNotIn("\nNone\n", rendered)
        manifest = read_json(output / "manifest.json")
        self.assertFalse(manifest["scientific_quality_verified"])
        self.assertFalse(manifest["user_selection_recorded"])
        self.assertEqual(
            self.fixture["zero_callback_counts"],
            {"query_runner": 0, "source_service": 0, "model": 0},
        )

    def test_located_core_classification_and_legacy_projection(self):
        legacy = legacy_report.Stage2IdeationReportTests()
        legacy.setUp()
        self.addCleanup(legacy.doCleanups)
        legacy_view = legacy.view()
        self.assertEqual(
            legacy_view["evidence"][0]["evidence_level"],
            legacy.packet["sources"][0]["evidence_level"],
        )
        row = next(
            r
            for r in self.packet["evidence"]
            if r["evidence_level"] == "primary_data_or_table"
        )
        sources = {r["source_id"]: r for r in self.packet["sources"]}
        projected = _evidence_view(row, sources)
        self.assertEqual(projected["evidence_level"], row["evidence_level"])
        source = sources[row["source_id"]]
        self.assertEqual(
            projected["physical_source_access"],
            {
                "source_id": source["source_id"],
                "sha256": source["sha256"],
                "evidence_level": source["evidence_level"],
            },
        )
        for key in ("locator", "start", "end", "quote", "core_artifact"):
            self.assertEqual(projected[key], row[key])


class WorkspaceReadingBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = prior_work.Stage2PriorWorkTests()
        cls.addClassCleanup(fixture.doCleanups)
        fixture.setUp()
        supplement = literature_versions.Stage2LiteratureVersionTests()
        supplement.root, supplement.source_root = fixture.root, fixture.source_root
        supplement.packet = fixture.packet
        fixture.packet = supplement.packet_with_supplement()
        # Author a fresh bounded dossier for this exact synthetic source set.
        fixture.packet["prior_work_reviews"] = [fixture.review()]
        validate_packet(fixture.packet, fixture.source_root)
        packet_path = fixture.root / "reading-packet.json"
        packet_path.write_text(json.dumps(fixture.packet), encoding="utf-8")
        checker = fixture.root / "reading-checker"
        initialize_run(
            packet_path,
            fixture.source_root,
            checker,
            expected_packet_sha256=canonical_hash(fixture.packet),
        )
        cls.selection = export_selection(checker)

    def attachment(self, version):
        selection = deepcopy(self.selection)
        selection["evaluation_packet"]["schema_version"] = version
        # A pure reading fragment, with no scientific judges or audit receipts.
        return {
            "selection": selection,
            "evaluation": {
                "evaluation_status": "incomplete-assessment",
                "rows": [],
                "dimensions": {
                    key: {"score": None, "sum": 0, "assessed": 0, "required": 3}
                    for key in ("P4", "P5", "P6")
                },
            },
        }

    def test_formed_direction_dossier_and_supplement_have_version_parity(self):
        for version in ("2.4.0", "2.7.0"):
            attachment = self.attachment(version)
            packet = attachment["selection"]["evaluation_packet"]
            original = deepcopy(attachment)
            view = build_comparison_view(attachment)
            for field in ("prior_work_reviews", "supplemental_literature"):
                with self.subTest(version=version, field=field):
                    self.assertTrue(view.get(field))
            with self.subTest(version=version, field="direction-dossier"):
                self.assertEqual(
                    view["directions"][0].get("prior_work_review"),
                    packet["prior_work_reviews"][0],
                )
            with self.subTest(version=version, field="same-work-source-versions"):
                self.assertTrue(view["literature"][0].get("source_versions"))
            self.assertEqual(attachment, original)

    def test_content_gate_is_visible_for_existing_and_current_versions(self):
        for version in ("2.4.0", "2.7.0"):
            with self.subTest(version=version):
                self.assertIn(
                    'id="stage2-content-gate"',
                    render_stage2_card(self.attachment(version)),
                )


if __name__ == "__main__":
    unittest.main()
