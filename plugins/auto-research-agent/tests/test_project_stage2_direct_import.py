"""Synthetic direct Stage2 delivery admission; no model/research/user authority."""

# ruff: noqa: E402 -- reuse repository deterministic fixtures.
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "cli")]

from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.session_api import SessionApiError
from research_workspace_native.project_stage2 import ProjectStage2Service
from research_workspace_native.project_stage2_selection import (
    ProjectStage2SelectionService,
)
from stage2_ideation.direct_request import prepare_direct_request
from stage2_workflow import initialize_workflow, inspect_workflow
from stage2_workflow.orchestration import prepare_review_batch
from stage2_workflow.delivery import build_delivery


class DirectDeliveryAdmissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        request = self.root / "request.txt"
        request.write_text(
            "Compare bounded synthetic opportunities; preserve unknown access.\n",
            encoding="utf-8",
            newline="",
        )
        self.request_hash = hashlib.sha256(request.read_bytes()).hexdigest()
        seed = prepare_direct_request(
            request, self.root / "seed", expected_request_sha256=self.request_hash
        )
        packet = json.loads(Path(seed["packet"]).read_bytes())
        workflow = self.root / "original-workflow"
        initialize_workflow(
            seed["packet"],
            self.root,
            workflow,
            {},
            {},
            expected_packet_sha256=seed["packet_sha256"],
        )
        state = inspect_workflow(workflow)
        snapshot = state["latest_snapshot"]["event"]["payload"]["snapshot_sha256"]
        batch = prepare_review_batch(
            packet,
            snapshot,
            [],
            "synthetic-direct-admission",
            review_view_version="1.3.0",
        )
        self.delivery_root = self.root / "delivery"
        self.manifest = build_delivery(
            workflow,
            batch,
            [],
            {
                "candidate_resolutions": [],
                "next_step": "No eligible direction; complete source-bound research first.",
            },
            self.delivery_root,
            state["head_sha256"],
            record_registered_history=True,
        )
        self.intake = ProjectIntakeService(
            self.root / "catalog", authenticate=lambda credential: credential
        )
        self.addCleanup(self.intake.close)
        self.service = ProjectStage2Service(self.intake)

    def import_package(self, **changes):
        arguments = dict(
            delivery_dir=self.delivery_root,
            expected_manifest_sha256=self.manifest["manifest_sha256"],
            expected_request_sha256=self.request_hash,
            project_id="synthetic-direct",
            input_version=1,
        )
        arguments.update(changes)
        return self.service.import_direct_request_project(
            "synthetic-owner", **arguments
        )

    def test_direct_delivery_is_readable_without_stage1_lineage(self):
        registered = self.import_package()
        ref = registered["project_ref"]
        project = self.intake.read("synthetic-owner", ref)
        self.assertEqual(project["stage1_status"], "not-applicable-direct-request")
        self.assertFalse(project["stage1_lineage"])
        self.assertIsNone(project["formal_question"])
        self.assertEqual(project["brief"]["decisions"], [])
        ui = ProjectStage2SelectionService(
            self.intake, {ref: registered["selection_binding"]}
        )
        view = ui.read("synthetic-owner", ref)
        self.assertEqual(view["eligible"], [])
        self.assertFalse(view["execution_authorized"])
        self.assertEqual(
            view["workflow_head_sha256"], self.manifest["workflow_head_sha256"]
        )

    def test_external_pins_refuse_before_any_project_is_registered(self):
        for changes in (
            {"expected_manifest_sha256": "0" * 64},
            {"expected_request_sha256": "0" * 64},
        ):
            with self.subTest(changes=changes), self.assertRaises(SessionApiError):
                self.import_package(**changes)
        self.assertEqual(self.intake.list("synthetic-owner"), [])

    def test_import_replay_preserves_one_project_and_one_original_event(self):
        first = self.import_package()
        second = self.import_package()
        self.assertEqual(first, second)
        count = self.intake.db.execute(
            "SELECT COUNT(*) FROM intake_events WHERE project=? AND kind='stage2-direct-input-imported'",
            (first["project_ref"],),
        ).fetchone()[0]
        self.assertEqual(count, 1)
        self.assertEqual(len(self.intake.list("synthetic-owner")), 1)

    def test_foreign_principal_cannot_read_imported_selection(self):
        registered = self.import_package()
        ref = registered["project_ref"]
        ui = ProjectStage2SelectionService(
            self.intake, {ref: registered["selection_binding"]}
        )
        with self.assertRaisesRegex(SessionApiError, "project-unavailable"):
            ui.read("foreign-owner", ref)

    def test_receiving_context_cannot_become_a_stage1_or_research_grant(self):
        registered = self.import_package()
        ref = registered["project_ref"]
        project = self.intake.read("synthetic-owner", ref)
        body = {
            key: project[key] for key in ("revision", "input_version", "brief_sha256")
        }
        body.update(key="forbidden-new-stage1", topic="A different topic")
        with self.assertRaisesRegex(SessionApiError, "imported-intake-is-read-only"):
            self.intake.revise("synthetic-owner", ref, body)
        with self.assertRaisesRegex(SessionApiError, "stage2-direct-receiving-only"):
            self.service.binding(ref)

    def test_copied_workflow_tamper_does_not_rebind_the_source(self):
        registered = self.import_package()
        ref = registered["project_ref"]
        binding = registered["selection_binding"]
        path = Path(binding["workflow_root"]) / "workflow_manifest.json"
        altered = json.loads(path.read_bytes())
        altered["settings"]["unexpected"] = True
        path.write_text(json.dumps(altered), encoding="utf-8")
        ui = ProjectStage2SelectionService(self.intake, {ref: binding})
        with self.assertRaises(SessionApiError):
            ui.read("synthetic-owner", ref)
        self.assertEqual(self.manifest["recommendation_candidate_versions"], [])

    def test_completed_private_copy_recovers_after_catalog_registration_interrupt(self):
        original = self.intake._save

        def interrupt(state, kind, payload):
            if kind == "stage2-direct-input-imported":
                raise OSError(
                    "Synthetic interruption after copy before database commit"
                )
            return original(state, kind, payload)

        with patch.object(self.intake, "_save", side_effect=interrupt):
            with self.assertRaisesRegex(OSError, "Synthetic interruption"):
                self.import_package()
        self.assertEqual(self.intake.list("synthetic-owner"), [])
        recovered = self.import_package()
        self.assertEqual(self.import_package(), recovered)
        self.assertEqual(len(self.intake.list("synthetic-owner")), 1)

    def test_invalid_input_versions_reject_before_import(self):
        for version in (True, 0, 1.0, "", " version "):
            with (
                self.subTest(version=repr(version)),
                self.assertRaises(SessionApiError),
            ):
                self.import_package(input_version=version)
        self.assertEqual(self.intake.list("synthetic-owner"), [])

    def interrupt_write(self, boundary, *, wrong_prefix=False):
        original_open = Path.open
        seen = []

        class BrokenWriter:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.stream.close()

            def __getattr__(self, name):
                return getattr(self.stream, name)

            def write(self, data):
                self.stream.write(b"!" if wrong_prefix else data[:1])
                self.stream.flush()
                raise OSError("Synthetic mid-write interruption")

        def opened(path, mode="r", *args, **kwargs):
            stream = original_open(path, mode, *args, **kwargs)
            location = str(path).replace(chr(92), "/")
            metadata = "/import/receiving-staging/" in location
            if (
                mode == "xb"
                and "receiving-staging" in location
                and not seen
                and metadata == (boundary == "metadata")
            ):
                seen.append(path)
                return BrokenWriter(stream)
            return stream

        with patch.object(Path, "open", new=opened):
            with self.assertRaisesRegex(OSError, "Synthetic mid-write"):
                self.import_package(project_id="partial-" + boundary)
        self.assertEqual(len(seen), 1)
        self.assertEqual(len(seen[0].read_bytes()), 1)
        return seen[0]

    def test_mid_write_metadata_and_workflow_recover_without_reexecution(self):
        for boundary in ("metadata", "workflow"):
            with self.subTest(boundary=boundary):
                self.interrupt_write(boundary)
                first = self.import_package(project_id="partial-" + boundary)
                self.assertEqual(
                    first, self.import_package(project_id="partial-" + boundary)
                )
                count = self.intake.db.execute(
                    "SELECT COUNT(*) FROM intake_events WHERE project=? AND kind='stage2-direct-input-imported'",
                    (first["project_ref"],),
                ).fetchone()[0]
                self.assertEqual(count, 1)
                self.assertFalse(first["execution_authorized"])
        self.assertEqual(len(self.intake.list("synthetic-owner")), 2)

    def test_changed_private_prefix_is_rejected_without_overwrite(self):
        partial = self.interrupt_write("workflow", wrong_prefix=True)
        with self.assertRaisesRegex(
            SessionApiError, "direct-import-partial-bytes-differ"
        ):
            self.import_package(project_id="partial-workflow")
        self.assertEqual(partial.read_bytes(), b"!")
        self.assertEqual(self.intake.list("synthetic-owner"), [])


if __name__ == "__main__":
    unittest.main()
