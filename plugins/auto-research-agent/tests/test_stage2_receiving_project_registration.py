"""Receiving saved Stage1 material must not grant Stage2 research authority."""

import json
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage2 import ProjectStage2Service
from research_workspace_native.project_stage1_view_binding import (
    bind_saved_stage1_references,
)
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import sha
import test_saved_source_stage2_intake as saved


class ReceivingOnlyProjectRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        saved.SavedReplayImportIntegrationTests.setUpClass()
        cls.shared = saved.SavedReplayImportIntegrationTests()
        cls.shared.setUp()
        cls.addClassCleanup(cls.shared.doCleanups)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="stage2-receiving-project-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.intake = ProjectIntakeService(
            self.root, authenticate=lambda token: "alice" if token == "own" else "bob"
        )
        self.addCleanup(self.intake.close)
        self.service = ProjectStage2Service(self.intake)
        f = self.shared
        self.args = dict(
            brief_path=f.brief,
            expected_brief_sha256=sha(f.brief.read_bytes()),
            settings=dict(
                mode="stage1-saved-source-receiving-only",
                execution_authorized=False,
                model_calls_authorized=0,
                external_queries_authorized=0,
                source_acquisitions_authorized=0,
                resource_envelope=f.resources.read_text(encoding="utf-8"),
            ),
            deliverable_dir=f.f.package,
            expected_manifest_sha256=f.manifest["sha256"],
            handoff_path=f.handoff_path,
            expected_handoff_sha256=sha(f.handoff_path.read_bytes()),
            resources_path=f.resources,
            expected_resources_sha256=sha(f.resources.read_bytes()),
            policy_ref=dict(
                route="stage1-saved-source-receiving-only",
                schema_version="1.0.0",
                execution_authorized=False,
                scope="import/readback/init/inspect; no Stage2 research",
            ),
            saved_source_root=f.root,
            saved_source_acceptance_sha256=f.acceptance_ref["sha256"],
            **f.replay_args,
        )

    def test_receiving_policy_registers_read_only_original_identity(self):
        before = self.shared.brief.read_bytes()
        with patch(
            "research_workspace_native.project_stage2.build_stage2_seed"
        ) as build:
            result = self.service.import_stage1_project("own", **self.args)
            build.assert_not_called()
        current = self.intake.read("own", result["project_ref"])
        brief = json.loads(before)
        self.assertEqual(current["project_id"], brief["project_id"])
        self.assertEqual(current["input_version"], brief["input_version"])
        self.assertIs(type(current["input_version"]), str)
        self.assertEqual(result["offer"]["status"], "receiving-only")
        self.assertFalse(result["execution_authorized"])
        self.assertEqual(self.shared.brief.read_bytes(), before)

    def test_receiving_offer_cannot_activate_or_initialize_research(self):
        result = self.service.import_stage1_project("own", **self.args)
        ref, offer = result["project_ref"], result["offer"]
        current = self.intake.read("own", ref)
        body = dict(
            key="receiving-cannot-activate",
            revision=current["revision"],
            input_version=current["input_version"],
            brief_sha256=current["brief_sha256"],
            offer_ref=offer["offer_ref"],
            offer_sha256=offer["offer_sha256"],
            confirmed=True,
        )
        with (
            patch(
                "research_workspace_native.project_stage2.build_stage2_seed"
            ) as build,
            patch(
                "research_workspace_native.project_stage2.initialize_workflow"
            ) as init,
        ):
            with self.assertRaisesRegex(
                SessionApiError, "receiving-only-research-not-authorized"
            ):
                self.service.activate("own", ref, body)
            build.assert_not_called()
            init.assert_not_called()
        state = self.service.read("own", ref)
        self.assertIsNone(state["activation"])
        self.assertIsNone(state["frontier"])
        self.assertFalse(state["offers"][0]["activation_allowed"])
        with self.assertRaises(SessionApiError):
            self.service.binding(ref)

    def test_receiving_context_cannot_silently_register_daily_policy(self):
        result = self.service.import_stage1_project("own", **self.args)
        registration = {
            key: value
            for key, value in self.args.items()
            if key not in {"brief_path", "expected_brief_sha256", "settings"}
        }
        registration["policy_ref"] = dict(route="stage2-general-v3/daily_v3")
        with self.assertRaisesRegex(
            SessionApiError, "receiving-only-policy-cannot-escalate"
        ):
            self.service.register(result["project_ref"], **registration)
        self.assertEqual(
            [
                r["status"]
                for r in self.service.read("own", result["project_ref"])["offers"]
            ],
            ["receiving-only"],
        )

    def test_nonzero_or_ambiguous_receiving_budget_refuses_before_write(self):
        for key, value in (
            ("model_calls_authorized", 1),
            ("external_queries_authorized", 1),
            ("source_acquisitions_authorized", 1),
            ("model_calls_authorized", False),
            ("model_calls_authorized", "0"),
            ("execution_authorized", True),
        ):
            with self.subTest(key=key, value=value):
                args = deepcopy(self.args)
                args["settings"][key] = value
                with self.assertRaisesRegex(
                    SessionApiError, "receiving-only-zero-budget-required"
                ):
                    self.service.import_stage1_project("own", **args)
                self.assertEqual(self.intake.list("own"), [])

    def test_invalid_policy_never_registers_a_project(self):
        for policy in (
            dict(route="unknown", execution_authorized=False),
            dict(route="stage1-saved-source-receiving-only"),
            dict(
                route="stage1-saved-source-receiving-only",
                schema_version="1.0.0",
                execution_authorized=True,
            ),
        ):
            with self.subTest(policy=policy):
                args = deepcopy(self.args)
                args["policy_ref"] = policy
                with self.assertRaises(SessionApiError):
                    self.service.import_stage1_project("own", **args)
                self.assertEqual(self.intake.list("own"), [])

    def test_receiving_reopens_and_reuses_exact_project_without_new_actions(self):
        result = self.service.import_stage1_project("own", **self.args)
        ref = result["project_ref"]
        before = self.intake.history("own", ref)
        again = self.service.import_stage1_project("own", **self.args)
        self.assertEqual(again, result)
        self.assertEqual(self.intake.history("own", ref), before)
        self.intake.close()
        reopened = ProjectIntakeService(self.root, authenticate=lambda token: "alice")
        self.addCleanup(reopened.close)
        service = ProjectStage2Service(reopened)
        self.assertEqual(service.import_stage1_project("own", **self.args), result)
        self.assertEqual(reopened.history("own", ref), before)
        self.assertEqual(
            reopened.read("own", ref)["input_version"],
            json.loads(self.shared.brief.read_bytes())["input_version"],
        )

    def test_receiving_material_context_is_principal_scoped(self):
        result = self.service.import_stage1_project("own", **self.args)
        self.assertEqual(self.intake.list("other"), [])
        with self.assertRaises(SessionApiError):
            self.service.read("other", result["project_ref"])

    def saved_view(self):
        brief = json.loads(self.shared.brief.read_bytes())
        return dict(
            ref="saved-original-stage1",
            label="Original saved Stage1 material",
            project_id=brief["project_id"],
            input_version=brief["input_version"],
            index_sha256="1" * 64,
            manifest_sha256="2" * 64,
            html_sha256="3" * 64,
            stage1_manifest_sha256=self.args["expected_manifest_sha256"],
            snapshot_sha256=json.loads(self.shared.handoff_path.read_bytes())[
                "snapshot_ref"
            ]["sha256"],
            url="/project-stage1-saved/saved-original-stage1/index.html",
            fixture=False,
            read_only=True,
            accepted=False,
            execution_authorized=False,
        )

    def import_with_saved_view(self):
        view = self.saved_view()
        args = deepcopy(self.args)
        args["saved_view"] = {
            key: view[key] for key in ("ref", "index_sha256", "manifest_sha256")
        }
        return self.service.import_stage1_project("own", **args), view

    def test_exact_trusted_view_links_same_project_without_authority(self):
        result, view = self.import_with_saved_view()
        linked = bind_saved_stage1_references(self.intake, "own", [view])
        self.assertEqual(linked[0]["project_ref"], result["project_ref"])
        self.assertEqual(
            linked[0]["project_input_sha256"],
            self.intake.binding(result["project_ref"])["imported_input_sha256"],
        )
        self.assertEqual(
            linked[0]["binding_origin"], "trusted-host-stage1-view-binding"
        )
        self.assertFalse(linked[0]["accepted"])
        self.assertFalse(linked[0]["execution_authorized"])
        self.assertNotIn("project_ref", view)
        self.assertNotIn("saved_source_root", json.dumps(linked))
        self.assertEqual(
            bind_saved_stage1_references(self.intake, "other", [view]), [view]
        )

    def test_view_wrong_project_typed_version_or_external_pins_reject(self):
        _, view = self.import_with_saved_view()
        for key, value in (
            ("project_id", "another-project"),
            ("input_version", 1),
            ("input_version", "stale-version"),
            ("index_sha256", "4" * 64),
            ("manifest_sha256", "5" * 64),
            ("stage1_manifest_sha256", "6" * 64),
        ):
            with self.subTest(key=key, value=value):
                wrong = deepcopy(view)
                wrong[key] = value
                with self.assertRaisesRegex(
                    SessionApiError, "saved-view-import-binding-differs"
                ):
                    bind_saved_stage1_references(self.intake, "own", [wrong])
        with self.assertRaisesRegex(SessionApiError, "saved-view-unavailable"):
            bind_saved_stage1_references(self.intake, "own", [])
        wrong_snapshot = deepcopy(view)
        wrong_snapshot["snapshot_sha256"] = "7" * 64
        with self.assertRaisesRegex(SessionApiError, "saved-view-snapshot-differs"):
            bind_saved_stage1_references(self.intake, "own", [wrong_snapshot])

    def test_saved_view_paths_and_partial_pins_refuse_before_write(self):
        for pin in (
            {"ref": "saved-original-stage1", "index_sha256": "1" * 64},
            {
                "ref": "saved-original-stage1",
                "index_sha256": "1" * 64,
                "manifest_sha256": "2" * 64,
                "path": "C:/arbitrary-material",
            },
        ):
            with self.subTest(pin=pin):
                args = deepcopy(self.args)
                args["saved_view"] = pin
                with self.assertRaisesRegex(
                    SessionApiError, "saved-view-reference-invalid"
                ):
                    self.service.import_stage1_project("own", **args)
                self.assertEqual(self.intake.list("own"), [])

    def test_one_saved_view_cannot_silently_choose_between_project_contexts(self):
        _, view = self.import_with_saved_view()
        args = deepcopy(self.args)
        args["settings"]["receiving_context_note"] = "A distinct imported context"
        args["saved_view"] = {
            key: view[key] for key in ("ref", "index_sha256", "manifest_sha256")
        }
        self.service.import_stage1_project("own", **args)
        with self.assertRaisesRegex(
            SessionApiError, "saved-view-project-binding-ambiguous"
        ):
            bind_saved_stage1_references(self.intake, "own", [view])

    def test_receiving_import_preserves_existing_external_source_guards(self):
        args = deepcopy(self.args)
        args["expected_handoff_sha256"] = "0" * 64
        with self.assertRaises(SessionApiError):
            self.service.import_stage1_project("own", **args)
        self.assertEqual(self.intake.list("own"), [])


if __name__ == "__main__":
    unittest.main()
