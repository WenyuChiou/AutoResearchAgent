"""Synthetic Stage1 import through real HTTP choice and strict Stage3 intake.

The source producer, checker and choice are engineering fixtures. No research,
model evaluation, actual human choice or execution authority is inferred.
"""

# ruff: noqa: E402 -- repository packages and bounded authored fixtures.
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "cli"), str(HERE)]

import test_project_stage1_identity_import as imported_fixture
from project_stage2_selection_fixture import Stage2SelectionFixture
import test_project_stage2_selection_http as selection_fixture
from test_stage2_scientific_argument import argument
import test_stage2_prior_work as prior_fixture
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_stage2_selection import (
    ProjectStage2SelectionService,
)
from stage3_plan.intake import admit_intake


class Stage123ProjectHostE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        imported_fixture.ImportedStage1ProjectTests.setUpClass.__func__(cls)

    def setUp(self):
        self.token = "synthetic-imported-choice-" + "x" * 32
        original_store = imported_fixture.ProjectIntakeService

        def authenticate(key):
            return {
                "own": "local-viewer",
                self.token: "local-viewer",
                "other": "foreign-user",
            }.get(key)

        def local_store(root, *, authenticate):
            return original_store(root, authenticate=self.authenticate)

        self.authenticate = authenticate
        with patch.object(
            imported_fixture, "ProjectIntakeService", side_effect=local_store
        ):
            imported_fixture.ImportedStage1ProjectTests.setUp(self)
        self.original_brief = self.f.brief.read_bytes()
        self.args["policy_ref"]["packet_profile"] = "scientific-v3"
        self.imported = self.service.import_stage1_project("own", **self.args)
        self.ref = self.imported["project_ref"]
        self.choice, _, self.workflow = Stage2SelectionFixture.prepare_choice(
            self,
            ProjectStage2SelectionService,
            packet_transform=self.structured_candidate,
        )
        self.host = ProjectHost(
            projects=self.intake,
            credential=self.token,
            stage2=self.service,
            stage2_selection=self.choice,
            files={},
            views=[],
            port=0,
        )
        thread = threading.Thread(target=self.host.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(
            lambda: (
                self.host.shutdown(),
                self.host.server_close(),
                thread.join(timeout=5),
            )
        )

    def body(self):
        project = self.intake.read("own", self.ref)
        offer = self.imported["offer"]
        return dict(
            key="synthetic-imported-activation",
            revision=project["revision"],
            input_version=project["input_version"],
            brief_sha256=project["brief_sha256"],
            offer_ref=offer["offer_ref"],
            offer_sha256=offer["offer_sha256"],
            confirmed=True,
        )

    def structured_candidate(self, packet, source_root):
        source = packet["sources"][0]
        source_ref = {
            key: source[key] for key in ("source_id", "work_id", "version_id")
        }
        packet["schema_version"] = "2.5.0"
        packet["research_tables"] = None
        packet["supplemental_literature"] = []
        packet["prior_work_reviews"] = []
        packet["candidates"][0]["scientific_argument"] = argument(
            packet["evidence"][0]["evidence_id"], source_ref
        )
        prior = prior_fixture.Stage2PriorWorkTests()
        prior.packet = packet
        prior.source_root = source_root
        prior.receipt_path = "receipts/synthetic-e2e-prior-work.json"
        prior.write_receipt("results")
        packet["prior_work_reviews"] = [prior.review()]
        return packet

    def request(self, path, body=None, *, token=None, origin=None):
        # Observe the server's existing hard30s deadline instead of disconnecting
        # at20s before its bounded metadata operation has returned a status.
        return selection_fixture.ProjectSelectionTests.request(
            self, path, body, token=token, origin=origin, timeout=35
        )

    selection_body = selection_fixture.ProjectSelectionTests.selection_body

    def test_imported_string_version_choice_reaches_structured_stage3_and_replays(self):
        project = self.intake.read(self.token, self.ref)
        body = self.selection_body()
        self.assertIs(type(body["input_version"]), str)
        self.assertEqual(body["input_version"], project["input_version"])
        path = "/api/projects/" + self.ref + "/stage2/select"
        status, raw, _ = self.request(path, body)
        if status != 200:
            self.fail(
                f"HTTP {status}: {raw!r}; retained actions: "
                + json.dumps(self.intake.history(self.token, self.ref)["actions"])
            )
        saved = json.loads(raw)
        self.assertEqual(saved["planning_status"], "verified")
        output = self.intake._path(self.ref, saved["artifact_ref"])
        submission = json.loads((output / "submission.json").read_bytes())
        self.assertEqual(submission["schema_version"], "1.1.0")
        self.assertEqual(submission["decision"], body["decision"])
        self.assertIs(type(submission["input_version"]), str)
        binding = self.choice.bindings[self.ref]
        admitted = admit_intake(
            output / "planning",
            binding["delivery_root"],
            expected_manifest_sha256=saved["planning_manifest_sha256"],
        )
        self.assertEqual(len(admitted["questions"]), 1)
        self.assertEqual(admitted["legacy_candidates"], [])
        self.assertEqual(admitted["brief"], json.loads(self.original_brief))
        self.assertEqual(admitted["unresolved"], body["decision"]["unresolved"])
        self.assertEqual(admitted["input_origin"]["kind"], "projecthost-ui-submission")
        self.assertFalse(admitted["execution_authorized"])
        before = (output / "interaction" / "interaction.json").read_bytes()
        status, raw, _ = self.request(path, body)
        self.assertEqual(status, 200, raw)
        self.assertTrue(json.loads(raw)["replayed"])
        self.assertEqual(
            (output / "interaction" / "interaction.json").read_bytes(), before
        )
        self.assertEqual(self.f.brief.read_bytes(), self.original_brief)
        actions = self.intake.db.execute(
            "SELECT receipt FROM intake_actions WHERE project=? AND key=?",
            (self.ref, body["key"]),
        ).fetchall()
        self.assertEqual(len(actions), 1)


if __name__ == "__main__":
    unittest.main()
