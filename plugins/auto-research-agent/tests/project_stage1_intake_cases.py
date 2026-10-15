"""Fresh SQLite/Core intake and passive Host; all execution forbidden."""

from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from planned_query_fixture import get_source_proof, saved_pin
from test_workspace_project_intake import authenticate, compile_body, submit_body
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage1 import ProjectStage1Service
from research_workspace_native.project_stage1_delivery import (
    ProjectStage1DeliveryService,
)
from research_workspace_native.project_stage1_queries import ProjectStage1QueryService
from stage1_deliverable.common import canonical, sha


OBSERVATIONS = []


class FreshIntakeCandidateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="qi2-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.intake = ProjectIntakeService(self.root / "p", authenticate=authenticate)
        self.addCleanup(self.intake.close)
        self.stage1 = ProjectStage1Service(self.intake, limit=3)
        proof = get_source_proof()
        self.queries = ProjectStage1QueryService(
            self.stage1,
            runtime_pin=saved_pin(self.root),
            execution_source_root=proof["repo"],
            execution_source_sha256=sha(canonical(proof["files"])),
            verify_source=lambda _: self.fail("unexpected verify_source"),
            admit=lambda _: self.fail("unexpected admission"),
            caps=dict(
                max_attempts=2,
                max_reserved_seconds=100,
                max_results=3,
                validity_seconds=600,
            ),
            backends=["openalex"],
        )
        self.addCleanup(self.queries.close)
        created = self.intake.create(
            "alice-token",
            {"key": "fresh", "topic": "RL traffic control test-only fresh intake"},
        )
        self.ref = created["project_ref"]
        self.host = object.__new__(ProjectHost)
        self.host.projects, self.host.project_stage1 = self.intake, self.stage1
        self.host.project_models = self.host.project_stage2 = None
        self.host.project_records_prepare = self.host.project_stage1_records = None
        self.host.project_expansions = self.host.project_stage1_sources = None
        self.host.project_stage1_delivery = ProjectStage1DeliveryService(self.stage1)
        self.capture = patch(
            "stage1_retrieval.runtime_identity.capture_identity",
            side_effect=AssertionError("actual probe forbidden"),
        ).start()
        self.addCleanup(patch.stopall)
        self.execute = patch(
            "stage1_retrieval.runner.execute",
            side_effect=AssertionError("actual search forbidden"),
        ).start()
        self.initialize = patch.object(
            self.stage1,
            "initialize",
            side_effect=AssertionError("initialize forbidden"),
        ).start()
        self.backend = patch(
            "research_workspace_native.project_stage1_queries.execute_backend",
            side_effect=AssertionError("backend forbidden"),
        ).start()

    def observation(self):
        rows = {
            name: [
                tuple(row) for row in self.intake.db.execute("SELECT * FROM " + name)
            ]
            for name in ("intake_projects", "intake_actions", "intake_events")
        }
        files = {
            path.relative_to(self.intake.root).as_posix(): sha(path.read_bytes())
            for path in self.intake.root.rglob("*")
            if path.is_file() and not path.name.startswith("project-intake.sqlite")
        }
        return dict(rows=rows, files=files, total_changes=self.intake.db.total_changes)

    def read_without_effects(self):
        before = self.observation()
        view = self.host.overview("alice-token", self.ref)
        repeat = self.host.overview("alice-token", self.ref)
        self.assertEqual(view, repeat)
        self.assertEqual(before, self.observation())
        for mock in (self.capture, self.execute, self.initialize, self.backend):
            mock.assert_not_called()
        self.assertEqual(self.queries.services, {})
        self.assertEqual(self.queries.workers, {})
        self.assertFalse(view["stage1"]["progress"]["research_complete"])
        OBSERVATIONS.append(
            dict(
                case=self.id(),
                query_status=view["stage1"]["query_execution"]["status"],
                refusal=view["stage1"]["query_execution"].get("refusal"),
                next_action=deepcopy(view["stage1"]["progress"]["next_action"]),
                get_mutations=0,
                dispatch_calls=0,
                probes=0,
                services=0,
                workers=0,
            )
        )
        return view

    def change_state(self, **change):
        state = self.intake._load("alice", self.ref)
        state.update(change)
        self.intake.db.execute(
            "UPDATE intake_projects SET state=? WHERE ref=?",
            (json.dumps(state, ensure_ascii=False), self.ref),
        )

    def test_real_fresh_scope_and_get_only_no_effects(self):
        view = self.read_without_effects()
        query = view["stage1"]["query_execution"]
        self.assertEqual(query["status"], "intake-prerequisite-required")
        self.assertEqual(query["refusal"], "project-query-intake-not-ready")
        self.assertFalse(query["execution_authorized"])
        self.assertIsNone(query["authorization_offer"])
        self.assertEqual(query["jobs"], [])
        self.assertEqual(
            view["stage1"]["progress"]["next_action"],
            dict(phase_id="scope", target="scope", reason="scope-required"),
        )

    def test_real_archive_history_damage_is_not_fresh_prerequisite(self):
        self.intake.db.execute(
            "INSERT INTO intake_events(project,kind,payload) VALUES(?,?,?)",
            (
                self.ref,
                "revise-saved",
                json.dumps({"archived_query_scope_sha256": "a" * 64}),
            ),
        )
        view = self.read_without_effects()
        self.assertEqual(
            view["stage1"]["query_execution"]["refusal"],
            "project-query-version-archive-history-differs",
        )
        self.assertEqual(view["stage1"]["progress"]["next_action"]["target"], "history")

    def test_real_resource_event_damage_is_not_fresh_prerequisite(self):
        self.intake.db.execute(
            "INSERT INTO intake_events(project,kind,payload) VALUES(?,?,?)",
            (self.ref, "project-resource-reservation", "{}"),
        )
        view = self.read_without_effects()
        self.assertEqual(
            view["stage1"]["query_execution"]["refusal"],
            "project-resource-reservation-event-differs",
        )
        self.assertEqual(view["stage1"]["progress"]["next_action"]["target"], "history")

    def test_unexpected_budget_exception_retains_generic_hold(self):
        with patch(
            "research_workspace_native.project_stage1_queries.current_budget",
            side_effect=ValueError("test-only unexpected exception"),
        ):
            view = self.read_without_effects()
        self.assertEqual(
            view["stage1"]["query_execution"]["status"], "unavailable-or-stale"
        )
        self.assertEqual(
            view["stage1"]["query_execution"]["refusal"], "query-binding-unavailable"
        )
        self.assertEqual(view["stage1"]["progress"]["next_action"]["target"], "history")

    def test_old_active_run_is_stale_not_fresh_scope(self):
        self.change_state(stage1_active="old-run-not-loaded")
        view = self.read_without_effects()
        self.assertEqual(view["stage1"]["stage1_status"], "stale-input")
        self.assertEqual(
            view["stage1"]["progress"]["next_action"]["reason"], "stale-input"
        )

    def test_unknown_job_is_preserved_and_never_adopted(self):
        self.change_state(
            stage1_query_jobs={
                "unknown": {
                    "key": "unknown",
                    "status": "execution-unknown",
                    "automatic_retry": False,
                }
            }
        )
        view = self.read_without_effects()
        self.assertEqual(
            view["stage1"]["query_execution"]["jobs"][0]["status"], "execution-unknown"
        )
        self.assertEqual(view["stage1"]["progress"]["next_action"]["target"], "history")

    def test_real_confirmed_compiled_permission_offer_still_available(self):
        view = self.intake.read("alice-token", self.ref)
        body = submit_body(view)
        body["budgets"].update(seconds=100, search_calls=2, rounds=1)
        body["consent"]["external_search"] = True
        self.intake.submit("alice-token", self.ref, body)
        self.intake.compile(
            "alice-token",
            self.ref,
            compile_body(self.intake.read("alice-token", self.ref)),
        )
        view = self.read_without_effects()
        self.assertEqual(
            view["stage1"]["query_execution"]["status"], "permission-required"
        )
        self.assertTrue(view["stage1"]["query_execution"]["authorization_offer"])
        self.assertEqual(view["stage1"]["progress"]["next_action"]["target"], "query")

    def test_resource_query_binding_error_is_not_intake_prerequisite(self):
        from research_workspace_native.session_api import SessionApiError

        with patch(
            "research_workspace_native.project_stage1_queries.current_budget",
            side_effect=SessionApiError("project-resource-query-binding-differs", 409),
        ):
            view = self.read_without_effects()
        self.assertEqual(
            view["stage1"]["query_execution"]["refusal"],
            "project-resource-query-binding-differs",
        )
        self.assertEqual(view["stage1"]["progress"]["next_action"]["target"], "history")
