"""Project query history cannot be rebound by mutable SQLite state."""

import atlas_test_paths  # noqa: F401
from copy import deepcopy
import json
from pathlib import Path
import shutil
from unittest.mock import patch

from planned_query_fixture import QueryCase
import project_stage1_query_cases as helpers
from research_workspace_native.session_api import SessionApiError
from research_workspace_native.project_stage1_library import ProjectStage1LibraryService
from stage1_deliverable.common import canonical, sha
from stage1_ledger.validation import validate_run
from test_workspace_project_intake import bound_body


class ProjectQueryHistoryCases(QueryCase):
    def setUp(self):
        # Composition runs the actual fixture without inheriting its test_* cases.
        self.case = helpers.ProjectQueryCases()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()

    def initialized(self):
        case = self.case
        case.authorize()
        case.bootstrap()
        return case

    def change_intake_state(self, change):
        case = self.case
        with case.intake._lock:
            state = case.intake._load("alice", case.ref)
            change(state)
            case.intake.db.execute(
                "UPDATE intake_projects SET state=? WHERE ref=?",
                (canonical(state).decode(), case.ref),
            )

    def execute_mocked(self, body):
        """Keep both runtime probe and backend mocked through worker completion."""
        case, result, error = self.case, None, None
        with case.fake_runner(), case.no_probe():
            try:
                result = case.queries.execute("alice-token", case.ref, body)
            except SessionApiError as refused:
                error = refused
            finally:
                service = case.queries.services[case.ref]
                worker = service._workers.get(case.ref)
                if worker is not None:
                    worker.join(30)
                    self.assertFalse(worker.is_alive(), "bounded fake worker")
        return result, error

    def completed_query(self, key="query-one"):
        case = self.case
        result, error = self.execute_mocked(case.body("query_offer", key))
        self.assertIsNone(error)
        service = case.queries.services[case.ref]
        observed = service.get_action(
            "alice-token", case.ref, result["query_action_key"]
        )
        self.assertEqual(observed["status"], "completed", observed)
        self.assertEqual(observed.get("outcome"), "observed", observed)
        return observed

    def saved_inventory(self):
        """Semantic stores plus physical artifacts, excluding SQLite lock files."""
        case = self.case
        service = case.queries.services[case.ref]
        return (
            {
                path.relative_to(case.root).as_posix(): sha(path.read_bytes())
                for path in case.root.rglob("*")
                if path.is_file() and ".sqlite" not in path.name
            },
            tuple(case.intake.db.iterdump()),
            tuple(service.store.db.iterdump()),
            len(case.children),
        )

    def test_screening_get_refuses_closing_and_replaced_outer_owner_without_restore(
        self,
    ):
        case = self.initialized()
        library = ProjectStage1LibraryService(case.stage1)
        original = library.read("alice-token", case.ref)
        before = self.saved_inventory()
        with (
            patch.object(case.queries, "closing", True),
            patch.object(
                case.queries, "reopen", side_effect=AssertionError("GET restored")
            ),
            patch.object(
                case.queries,
                "restore_owner",
                side_effect=AssertionError("GET restored"),
            ),
            self.assertRaisesRegex(
                SessionApiError, "project-query-saved-owner-unavailable"
            ),
        ):
            library.read("alice-token", case.ref)
        self.assertEqual(before, self.saved_inventory())
        self.assertEqual(original, library.read("alice-token", case.ref))

        # A new real bridge has no live owner. GET must not adopt the still-held
        # old owner's connection or perform explicit restore_owner on its behalf.
        case.stage1.query_service = None
        replacement = case.bridge()
        before = self.saved_inventory()
        with (
            patch.object(
                replacement, "reopen", side_effect=AssertionError("GET restored")
            ),
            patch.object(
                replacement, "restore_owner", side_effect=AssertionError("GET restored")
            ),
        ):
            with self.assertRaisesRegex(
                SessionApiError, "project-query-saved-owner-unavailable"
            ):
                case.queries.saved_frontier(case.ref)
            with self.assertRaisesRegex(
                SessionApiError, "project-query-owner-reopen-required"
            ):
                library.read("alice-token", case.ref)
        self.assertEqual(replacement.services, {})
        self.assertEqual(before, self.saved_inventory())
        self.assertEqual(case.children, [])

    def test_screening_get_refuses_inner_closing_and_real_sqlite_owner_loss(self):
        case = self.initialized()
        library = ProjectStage1LibraryService(case.stage1)
        original = library.read("alice-token", case.ref)
        service = case.queries.services[case.ref]
        before = self.saved_inventory()
        with (
            patch.object(service, "_closing", True),
            self.assertRaisesRegex(SessionApiError, "query-service-closing"),
        ):
            library.read("alice-token", case.ref)
        self.assertEqual(before, self.saved_inventory())
        self.assertEqual(original, library.read("alice-token", case.ref))

        # Release the actual SQLite owner transaction, not a synthetic facade.
        project = service._projects[case.ref]
        connection = service.store._owners[project["pid"]][1]
        self.assertTrue(connection.in_transaction)
        connection.rollback()
        self.assertFalse(connection.in_transaction)
        before = self.saved_inventory()
        with (
            patch.object(
                case.queries, "reopen", side_effect=AssertionError("GET reclaimed")
            ),
            patch.object(
                case.queries,
                "restore_owner",
                side_effect=AssertionError("GET reclaimed"),
            ),
            self.assertRaisesRegex(SessionApiError, "query-ledger-owner-lost"),
        ):
            library.read("alice-token", case.ref)
        self.assertFalse(connection.in_transaction)
        self.assertEqual(before, self.saved_inventory())
        self.assertEqual(case.children, [])

    def test_outer_counter_reset_rejects_before_a_new_backend_attempt(self):
        case = self.initialized()
        body = case.body("query_offer", "query-after-reset")
        self.change_intake_state(
            lambda state: state["stage1_query_budget"].update(
                probes=0, attempts=0, seconds=0
            )
        )
        result, error = self.execute_mocked(body)
        self.assertIsNotNone(error, result)
        self.assertEqual(case.children, [])
        self.assertEqual(
            case.intake._load("alice", case.ref)["stage1_query_budget"],
            dict(probes=0, attempts=0, seconds=0),
        )

    def test_inner_counter_reset_cannot_hide_one_already_observed_attempt(self):
        case = self.initialized()
        self.completed_query()
        body = case.body("query_offer", "query-two")
        service = case.queries.services[case.ref]
        project = service._projects[case.ref]
        saved = service.store.snapshot(project["pid"])
        saved["query_budget"].update(attempts=0, seconds=0)
        service.store.db.execute(
            "UPDATE projects SET state=? WHERE id=?",
            (canonical(saved).decode(), project["pid"]),
        )
        before = len(case.children)
        result, error = self.execute_mocked(body)
        if error is None:
            observed = service.get_action(
                "alice-token", case.ref, result["query_action_key"]
            )
            self.assertEqual(observed.get("outcome"), "refused-known-unsent", observed)
        self.assertEqual(len(case.children), before)

    def test_admission_requires_the_exact_outer_intent_client_key(self):
        case = self.initialized()
        self.completed_query()
        service = case.queries.services[case.ref]
        project = service._projects[case.ref]
        offer = service.offer("alice-token", case.ref)
        wrong = dict(
            project_ref=case.ref,
            principal="alice",
            client_key="project-" + "f" * 64,
            permit_sha256=project["item"]["permit_sha256"],
            execution_source_sha256=project["item"]["execution_source_sha256"],
            offer=deepcopy(offer["document"]),
            budget=deepcopy(service.view("alice-token", case.ref)["budget"]),
            phase="before-runner",
        )
        before = len(case.children)
        with self.assertRaises(SessionApiError):
            service._admit(wrong)
        self.assertEqual(len(case.children), before)

    def test_sibling_ledger_copy_cannot_replace_the_query_owned_run(self):
        case = self.initialized()
        stage = case.stage1.read("alice-token", case.ref)
        body = dict(
            bound_body(case.intake.read("alice-token", case.ref), "checkpoint-fork"),
            ledger_state_sha256=stage["ledger"]["state_sha256"],
            confirmed=True,
        )
        state = case.intake._load("alice", case.ref)
        run = state["stage1_runs"][state["stage1_active"]]
        original = case.intake._path(case.ref, run["path"])
        sibling = case.intake._path(case.ref, "sibling-ledger")
        shutil.copytree(original, sibling)
        self.assertEqual(
            validate_run(original)["state_sha256"],
            validate_run(sibling)["state_sha256"],
        )
        self.change_intake_state(
            lambda saved: saved["stage1_runs"][saved["stage1_active"]].update(
                path="sibling-ledger"
            )
        )
        with patch(
            "stage1_coverage.run.CoverageLedger.checkpoint",
            side_effect=AssertionError("fork reached the producer"),
        ) as producer:
            with self.assertRaises(SessionApiError):
                case.stage1.checkpoint("alice-token", case.ref, body)
        producer.assert_not_called()
        self.assertEqual(case.children, [])

    def test_rehashed_registration_reopen_rejects_before_owner_construction(self):
        case = self.initialized()
        case.queries.close()
        case.stage1.query_service = None
        case.queries = case.bridge()
        body = case.body("owner_offer", "restore-tampered")

        def rehash(saved):
            job = next(iter(saved["stage1_query_jobs"].values()))
            registration = job["registration"]
            registration["project_binding_sha256"] = "0" * 64
            permit_path = Path(registration["permit_path"])
            permit = json.loads(permit_path.read_bytes())
            permit["binding"]["project_binding_sha256"] = "0" * 64
            raw = canonical(permit) + b"\n"
            permit_path.write_bytes(raw)
            registration["permit_sha256"] = sha(raw)

        self.change_intake_state(rehash)
        with patch(
            "research_workspace_native.project_stage1_queries.PlannedQueryService",
            side_effect=AssertionError("tampered registration constructed owner"),
        ) as constructor:
            with self.assertRaises(SessionApiError):
                case.queries.restore_owner("alice-token", case.ref, body)
        constructor.assert_not_called()
        self.assertEqual(case.children, [])
