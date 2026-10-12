"""Versioned query ownership over real Core/SQLite; probe/backend are mocked."""

from copy import deepcopy
import unittest
from unittest.mock import patch

import project_stage1_query_cases as helpers
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage1 import ProjectStage1Service
from research_workspace_native.project_query_versions import (
    archive_revision,
    check_revision,
)
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, sha
from test_workspace_project_intake import (
    authenticate,
    bound_body,
    compile_body,
    submit_body,
)


class ProjectQueryVersionCases(unittest.TestCase):
    def setUp(self):
        # Composition deliberately does not rediscover the parent's test_* suite.
        self.case = helpers.ProjectQueryCases()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()

    def current(self):
        return self.case.intake.read("alice-token", self.case.ref)

    def saved(self):
        return deepcopy(self.case.intake._load("alice", self.case.ref))

    def revise_body(self, key="revise-v2"):
        return dict(
            bound_body(self.current(), key),
            topic="Autonomous driving RL with uncertain sensors",
        )

    def revise(self, key="revise-v2"):
        case = self.case
        return case.intake.revise("alice-token", case.ref, self.revise_body(key))

    def confirm_compile(self):
        case = self.case
        body = submit_body(self.current())
        body["key"] = "confirm-v2"
        body["budgets"].update(seconds=100, search_calls=2, rounds=1)
        body["consent"]["external_search"] = True
        case.intake.submit("alice-token", case.ref, body)
        body = compile_body(self.current())
        body["key"] = "compile-v2"
        case.intake.compile("alice-token", case.ref, body)

    def authorize_v2(self):
        case = self.case
        body = case.body("authorization_offer", "authorization-v2", authorize=True)
        return body, case.queries.authorize("alice-token", case.ref, body)

    def bootstrap_v2(self):
        case = self.case
        body = case.body("bootstrap_offer", "bootstrap-v2")
        with patch(
            "stage1_retrieval.runtime_identity.verify_identity",
            side_effect=lambda pin, **kw: helpers.verify_identity(pin),
        ) as probe:
            case.queries.bootstrap("alice-token", case.ref, body)
            case.queries.workers[case.ref].join(30)
            self.assertFalse(case.queries.workers[case.ref].is_alive())
        self.assertTrue(any(c.kwargs.get("probe") for c in probe.call_args_list))
        view = case.queries.read("alice-token", case.ref)
        self.assertEqual(view["jobs"][0]["status"], "completed", view)
        return body

    def execute(self, key):
        case = self.case
        body = case.body("query_offer", key)
        with case.fake_runner(), case.no_probe():
            result = case.queries.execute("alice-token", case.ref, body)
            service = case.queries.services[case.ref]
            service._workers[case.ref].join(30)
            self.assertFalse(service._workers[case.ref].is_alive())
        observed = service.get_action(
            "alice-token", case.ref, result["query_action_key"]
        )
        self.assertEqual(observed["status"], "completed", observed)
        self.assertEqual(observed["outcome"], "observed", observed)
        return body

    def assert_archive(self, before, receipt, budget):
        old = before["stage1_query_authorization"]
        archive = self.saved()["stage1_query_versions"][old["sha256"]]
        self.assertEqual(archive["authorization"], old)
        self.assertEqual(archive["jobs"], before.get("stage1_query_jobs", {}))
        self.assertEqual(archive["budget"], budget)
        self.assertEqual(archive["input_version"], before["input_version"])
        self.assertEqual(
            archive["brief_sha256"], old["permit"]["binding"]["input_bytes_sha256"]
        )
        self.assertEqual(archive["run_ref"], before.get("stage1_active"))
        self.assertEqual(archive["revise_request_sha256"], receipt["request_sha256"])
        self.assertEqual(
            receipt["archived_query_scope_sha256"], sha(canonical(archive))
        )
        root = self.case.intake._path(self.case.ref, old["path"])
        self.assertEqual(sha(root.read_bytes()), old["sha256"])
        self.assertEqual(
            sha(
                self.case.intake._path(self.case.ref, old["snapshot_path"]).read_bytes()
            ),
            old["permit"]["binding"]["index_sha256"],
        )

    def assert_refused_unchanged(self, code):
        before = self.saved()
        with self.assertRaisesRegex(SessionApiError, code):
            self.revise()
        after = self.saved()
        for key in (
            "input_version",
            "briefs",
            "settings",
            "plan",
            "stage1_query_authorization",
            "stage1_query_budget",
        ):
            self.assertEqual(after[key], before[key], key)
        self.assertEqual(
            after.get("stage1_query_versions"), before.get("stage1_query_versions")
        )

    def reopen(self):
        case = self.case
        case.queries.close()
        case.stage1.query_service = None
        case.intake.close()
        case.intake = ProjectIntakeService(case.root / "p", authenticate=authenticate)
        self.addCleanup(case.intake.close)
        case.stage1 = ProjectStage1Service(case.intake, limit=3)
        case.queries = case.bridge()

    def test_unused_permission_archives_then_requires_fresh_explicit_authorization(
        self,
    ):
        case = self.case
        case.authorize()
        before = self.saved()
        with (
            case.no_probe(),
            patch(
                "stage1_retrieval.runtime_identity.capture_identity",
                side_effect=AssertionError("probe"),
            ),
        ):
            receipt = self.revise()
            self.assert_archive(before, receipt, dict(probes=0, attempts=0, seconds=0))
            self.assertEqual(self.current()["input_version"], 2)
            self.assertIsNone(self.current()["settings"])
            self.assertIsNone(self.current()["plan"])
            self.assertIsNone(
                case.queries.read("alice-token", case.ref)["bootstrap_offer"]
            )
            self.confirm_compile()
            view = case.queries.read("alice-token", case.ref)
            self.assertIsNotNone(view["authorization_offer"])
            self.assertIsNone(view["bootstrap_offer"])
            _, authorized = self.authorize_v2()
        old = before["stage1_query_authorization"]
        new = self.saved()["stage1_query_authorization"]
        self.assertNotEqual(authorized["permit_sha256"], old["sha256"])
        self.assertNotEqual(new["path"], old["path"])
        self.assertEqual(new["permit"]["binding"]["project_input_version"], 2)
        self.assertEqual(case.children, [])

    def test_settled_search_revision_keeps_lifetime_budget_and_both_ledgers(self):
        case = self.case
        case.authorize()
        case.bootstrap()
        self.execute("query-v1")
        before = self.saved()
        old_run = before["stage1_active"]
        old_ledger = case.intake._path(case.ref, before["stage1_runs"][old_run]["path"])
        original_manifest = (old_ledger / "run_manifest.json").read_bytes()
        receipt = self.revise()
        self.assert_archive(before, receipt, dict(probes=1, attempts=1, seconds=62))
        self.assertNotIn(case.ref, case.queries.services)
        self.confirm_compile()
        self.authorize_v2()
        self.bootstrap_v2()
        self.execute("query-v2")
        state = self.saved()
        view = case.queries.read("alice-token", case.ref)
        self.assertEqual(view["budget"], dict(probes=1, attempts=1, seconds=62))
        self.assertEqual(
            view["lifetime_budget"], dict(probes=2, attempts=2, seconds=124)
        )
        self.assertEqual(state["stage1_query_budget"], view["lifetime_budget"])
        self.assertIn(old_run, state["stage1_runs"])
        self.assertNotEqual(old_run, state["stage1_active"])
        self.assertEqual(
            (old_ledger / "run_manifest.json").read_bytes(), original_manifest
        )
        self.assertEqual(len(case.children), 2)

    def test_unknown_bootstrap_cannot_change_version_or_replace_permission(self):
        case = self.case
        case.authorize()
        body = case.body("bootstrap_offer", "bootstrap-unknown")
        with patch(
            "stage1_retrieval.runtime_identity.verify_identity",
            side_effect=RuntimeError("unobserved probe"),
        ):
            case.queries.bootstrap("alice-token", case.ref, body)
            case.queries.workers[case.ref].join(30)
        self.assertEqual(
            case.queries.read("alice-token", case.ref)["jobs"][0]["status"],
            "execution-unknown",
        )
        self.assert_refused_unchanged("project-query-revision-unsettled")
        self.assertIsNone(
            case.queries.read("alice-token", case.ref)["authorization_offer"]
        )
        self.assertEqual(case.children, [])

    def test_admitted_inner_unknown_remains_held_without_losing_reservation(self):
        case = self.case
        case.authorize()
        case.bootstrap()
        body = case.body("query_offer", "inner-unknown")
        with (
            case.no_probe(),
            patch(
                "stage1_coverage.run.CoverageLedger.start_planned",
                side_effect=RuntimeError("mutation unobserved"),
            ),
        ):
            result = case.queries.execute("alice-token", case.ref, body)
            service = case.queries.services[case.ref]
            service._workers[case.ref].join(30)
        observed = service.get_action(
            "alice-token", case.ref, result["query_action_key"]
        )
        self.assertEqual(observed["status"], "execution-unknown", observed)
        self.assert_refused_unchanged("query-unreconciled-action")
        self.assertEqual(
            self.saved()["stage1_query_budget"], dict(probes=1, attempts=1, seconds=62)
        )
        self.assertEqual(case.children, [])

    def test_true_reopen_requires_explicit_history_owner_before_revision(self):
        case = self.case
        case.authorize()
        body, _, _ = case.bootstrap()
        self.reopen()
        with (
            case.no_probe(),
            patch(
                "stage1_retrieval.runtime_identity.capture_identity",
                side_effect=AssertionError("reprobe"),
            ),
        ):
            self.assert_refused_unchanged("project-query-revision-owner-required")
            self.assertEqual(case.queries.services, {})
            case.queries.restore_owner(
                "alice-token", case.ref, case.body("owner_offer", "restore-old-owner")
            )
            self.assertTrue(
                case.queries.bootstrap("alice-token", case.ref, body)["replayed"]
            )
            receipt = self.revise("revise-after-restore")
        self.assertIn("archived_query_scope_sha256", receipt)
        self.assertEqual(self.current()["input_version"], 2)
        self.assertEqual(case.children, [])

    def test_reopen_old_keys_replay_without_adopting_a_new_version_owner(self):
        case = self.case
        authorization, _ = case.authorize()
        bootstrap, _, _ = case.bootstrap()
        before = self.saved()
        revise = self.revise()
        self.confirm_compile()
        self.authorize_v2()
        self.reopen()
        snapshot = self.saved()
        with (
            case.no_probe(),
            patch(
                "stage1_retrieval.runtime_identity.capture_identity",
                side_effect=AssertionError("reprobe"),
            ),
        ):
            self.assertTrue(
                case.queries.authorize("alice-token", case.ref, authorization)[
                    "replayed"
                ]
            )
            self.assertTrue(
                case.queries.bootstrap("alice-token", case.ref, bootstrap)["replayed"]
            )
        self.assertEqual(self.saved(), snapshot)
        self.assert_archive(before, revise, dict(probes=1, attempts=0, seconds=30))
        self.assertEqual(case.queries.services, {})
        self.assertEqual(case.children, [])

    def test_pipeline_transport_commit_gap_is_held_before_any_owner_close(self):
        # Guard-only injected state, not a source receipt/causality acceptance.
        case = self.case
        case.authorize()
        case.bootstrap()
        state = self.saved()
        job = {
            "status": "source-observation-saved",
            "binding": {"pipeline_sha256": "a" * 64},
            "result": {"body_complete": True},
            "followup": None,
        }
        state["stage1_source_operations"] = {"jobs": {"guard-only-source": job}}
        service = case.queries.services[case.ref]
        before = self.saved()
        with patch.object(
            service, "close", side_effect=AssertionError("closed in transport gap")
        ) as close:
            with self.assertRaisesRegex(
                SessionApiError, "project-query-revision-unsettled"
            ):
                archive_revision(case.queries, "alice-token", state, "b" * 64)
            close.assert_not_called()
            job["followup"] = {"status": "source-core-registered"}
            check_revision(case.queries, "alice-token", state)
            close.assert_not_called()
        self.assertEqual(self.saved(), before)
        self.assertEqual(case.children, [])

    def test_removed_archive_refuses_new_permission_without_repair_or_dispatch(self):
        case = self.case
        case.authorize()
        self.revise()
        self.confirm_compile()
        body = case.body("authorization_offer", "archive-tamper", authorize=True)
        state = self.saved()
        state["stage1_query_versions"] = {}
        case.intake.db.execute(
            "UPDATE intake_projects SET state=? WHERE ref=?",
            (canonical(state).decode(), case.ref),
        )
        with case.no_probe():
            view = case.queries.read("alice-token", case.ref)
            self.assertIsNone(view["authorization_offer"])
            self.assertEqual(
                view["refusal"], "project-query-version-archive-history-differs"
            )
            with self.assertRaisesRegex(
                SessionApiError, "intake-operation-failed"
            ) as refused:
                case.queries.authorize("alice-token", case.ref, body)
            self.assertEqual(
                refused.exception.receipt["error"],
                "project-query-version-archive-history-differs",
            )
        self.assertNotIn("stage1_query_authorization", self.saved())
        self.assertEqual(
            self.saved()["stage1_query_budget"], dict(probes=0, attempts=0, seconds=0)
        )
        self.assertEqual(case.children, [])

    def test_brief_write_failure_after_close_preserves_alias_and_replays_without_reclose(
        self,
    ):
        case = self.case
        case.authorize()
        case.bootstrap()
        before = self.saved()
        authorization = before["stage1_query_authorization"]
        files = {
            name: case.intake._path(case.ref, authorization[name]).read_bytes()
            for name in ("path", "snapshot_path")
        }
        request = self.revise_body("revise-write-failure")
        service = case.queries.services[case.ref]
        with (
            patch.object(service, "close", wraps=service.close) as close,
            patch.object(
                case.intake,
                "_write_brief",
                side_effect=OSError("injected brief write failure"),
            ),
            self.assertRaises(SessionApiError) as refused,
        ):
            case.intake.revise("alice-token", case.ref, request)
        self.assertEqual(close.call_count, 1)
        self.assertTrue(service._closed)
        self.assertNotIn(case.ref, case.queries.services)
        after = self.saved()
        for key in (
            "input_version",
            "briefs",
            "settings",
            "plan",
            "stage1_query_authorization",
            "stage1_query_jobs",
            "stage1_query_budget",
        ):
            self.assertEqual(after[key], before[key], key)
        self.assertEqual(
            after.get("stage1_query_versions"), before.get("stage1_query_versions")
        )
        for name, raw in files.items():
            self.assertEqual(
                case.intake._path(case.ref, authorization[name]).read_bytes(), raw
            )
        with (
            patch.object(
                service, "close", side_effect=AssertionError("reclosed")
            ) as close,
            case.no_probe(),
            patch(
                "stage1_retrieval.runtime_identity.capture_identity",
                side_effect=AssertionError("reprobe"),
            ),
        ):
            replay = case.intake.revise("alice-token", case.ref, request)
            self.assertTrue(replay["replayed"])
            self.assertEqual(
                replay["request_sha256"], refused.exception.receipt["request_sha256"]
            )
            self.assertEqual(replay["status"], refused.exception.receipt["status"])
            close.assert_not_called()
            self.assertEqual(
                case.queries.read("alice-token", case.ref)["status"],
                "owner-reopen-required",
            )
            case.queries.restore_owner(
                "alice-token",
                case.ref,
                case.body("owner_offer", "restore-after-write-failure"),
            )
        self.assertEqual(case.children, [])
        receipt = self.revise("revise-after-write-failure-restore")
        self.assert_archive(before, receipt, dict(probes=1, attempts=0, seconds=30))
