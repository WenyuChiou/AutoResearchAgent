"""Imported string-version HTTP choice recovery with synthetic saved sources."""

# ruff: noqa: E402 -- repository packages and the bounded imported fixture.
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "cli"), str(HERE)]

import test_stage123_projecthost_e2e as imported_e2e
from research_workspace_native.project_stage2 import ProjectStage2Service
from research_workspace_native.session_api import SessionApiError
from stage2_workflow import inspect_workflow
from stage3_plan.intake import admit_intake


def raw_files(root):
    return {
        file.relative_to(root): file.read_bytes()
        for file in root.rglob("*")
        if file.is_file()
    }


class ImportedSelectionRecoveryE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        imported_e2e.Stage123ProjectHostE2ETests.setUpClass.__func__(cls)

    # Reuse setup without importing or inheriting the fixture's test methods.
    setUp = imported_e2e.Stage123ProjectHostE2ETests.setUp
    body = imported_e2e.Stage123ProjectHostE2ETests.body
    structured_candidate = imported_e2e.Stage123ProjectHostE2ETests.structured_candidate
    request = imported_e2e.Stage123ProjectHostE2ETests.request
    selection_body = imported_e2e.Stage123ProjectHostE2ETests.selection_body

    def test_same_imported_http_choice_recovers_only_its_interrupted_frontier(self):
        project = self.intake.read(self.token, self.ref)
        body = self.selection_body()
        original_body = json.dumps(body, sort_keys=True)
        self.assertIs(type(body["input_version"]), str)
        self.assertEqual(body["input_version"], project["input_version"])
        path = "/api/projects/" + self.ref + "/stage2/select"

        with patch.object(
            ProjectStage2Service,
            "advance_frontier",
            side_effect=SessionApiError("synthetic-imported-frontier-interruption"),
        ) as interrupted:
            status, raw, _ = self.request(path, body)
        self.assertEqual(status, 409, raw)
        self.assertEqual(
            json.loads(raw)["error"], "stage2-selection-frontier-needs-recovery"
        )
        self.assertEqual(interrupted.call_count, 1)

        rows = self.intake.db.execute(
            "SELECT receipt FROM intake_actions WHERE project=? AND key=?",
            (self.ref, body["key"]),
        ).fetchall()
        self.assertEqual(len(rows), 1)
        original_choice_receipt = rows[0][0]
        saved_choice = json.loads(original_choice_receipt)
        self.assertEqual(saved_choice["status"], "saved")
        self.assertEqual(saved_choice["planning_status"], "verified")
        self.assertEqual(
            saved_choice["request"],
            {key: value for key, value in body.items() if key != "revision"},
        )
        self.assertFalse(saved_choice["execution_authorized"])
        output = self.intake._path(self.ref, saved_choice["artifact_ref"])
        original_artifacts = raw_files(output)
        original_workflow = raw_files(self.workflow)
        source_package = Path(self.args["deliverable_dir"])
        original_sources = raw_files(source_package)
        self.assertIn(Path("submission.json"), original_artifacts)
        self.assertIn(Path("interaction/interaction.json"), original_artifacts)
        before = inspect_workflow(self.workflow)
        self.assertEqual(before["latest_snapshot"]["packet"]["schema_version"], "2.5.0")
        interactions = [
            action
            for action in before["actions"].values()
            if action["request"]["action_kind"] == "human-interaction"
        ]
        self.assertEqual(len(interactions), 1)
        frontier_key = "frontier-" + saved_choice["request_sha256"]
        self.assertEqual(
            self.intake.db.execute(
                "SELECT COUNT(*) FROM intake_actions WHERE project=? AND key=?",
                (self.ref, frontier_key),
            ).fetchone()[0],
            0,
        )

        # The production transport and frontier are restored for the exact retry.
        status, raw, _ = self.request(path, body)
        self.assertEqual(status, 200, raw)
        recovered = json.loads(raw)
        self.assertTrue(recovered["replayed"])
        self.assertEqual(recovered["request_sha256"], saved_choice["request_sha256"])
        self.assertEqual(recovered["artifact_ref"], saved_choice["artifact_ref"])
        self.assertEqual(json.dumps(body, sort_keys=True), original_body)
        self.assertEqual(
            self.intake.db.execute(
                "SELECT receipt FROM intake_actions WHERE project=? AND key=?",
                (self.ref, body["key"]),
            ).fetchall(),
            rows,
        )
        frontier_rows = self.intake.db.execute(
            "SELECT receipt FROM intake_actions WHERE project=? AND key=?",
            (self.ref, frontier_key),
        ).fetchall()
        self.assertEqual(len(frontier_rows), 1)
        frontier = json.loads(frontier_rows[0][0])
        self.assertEqual(frontier["status"], "saved")
        self.assertEqual(
            frontier["request"]["new_workflow_head_sha256"],
            recovered["workflow_head_sha256"],
        )
        self.assertEqual(
            self.service.binding(self.ref)["workflow_head_sha256"],
            recovered["workflow_head_sha256"],
        )
        self.assertEqual(inspect_workflow(self.workflow), before)

        submission = json.loads(original_artifacts[Path("submission.json")])
        self.assertEqual(submission["schema_version"], "1.1.0")
        self.assertIs(type(submission["input_version"]), str)
        self.assertEqual(submission["input_version"], project["input_version"])
        self.assertEqual(submission["decision"], body["decision"])
        binding = self.choice.bindings[self.ref]
        admitted = admit_intake(
            output / "planning",
            binding["delivery_root"],
            expected_manifest_sha256=recovered["planning_manifest_sha256"],
        )
        self.assertEqual(len(admitted["questions"]), 1)
        self.assertEqual(admitted["legacy_candidates"], [])
        self.assertEqual(admitted["brief"], json.loads(self.original_brief))
        self.assertEqual(admitted["input_origin"]["kind"], "projecthost-ui-submission")
        self.assertEqual(
            admitted["selection_conditions"], body["decision"]["conditions"]
        )
        self.assertEqual(admitted["unresolved"], body["decision"]["unresolved"])
        self.assertIs(admitted["execution_authorized"], False)
        self.assertEqual(raw_files(output), original_artifacts)
        self.assertEqual(raw_files(self.workflow), original_workflow)
        self.assertEqual(raw_files(source_package), original_sources)
        self.assertEqual(self.f.brief.read_bytes(), self.original_brief)


if __name__ == "__main__":
    unittest.main()
