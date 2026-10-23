"""Real project/query continuation with synthetic lawful backend/probe evidence.

No listener, model, Hub executable, search request or download is launched.
The existing project, compiler, sealed permit, query owner, receipts, ledger,
resource accounting, host views and continuation driver all run unchanged.
"""

from contextlib import ExitStack
from copy import deepcopy
import json
import time
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch

import planned_query_fixture
import project_stage1_query_cases as project_query_fixture
from planned_query_fixture import QueryCase
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage1 import ProjectStage1Service
from research_workspace_native.project_stage1_delivery import (
    ProjectStage1DeliveryService,
)
from research_workspace_native.session_api import SessionApiError
from stage1_retrieval.runtime_identity import verify_identity
from test_workspace_project_intake import authenticate, compile_body, submit_body


class ProjectStage1AutoCases(QueryCase):
    # Reuse fixture methods without inheriting its unrelated test_* scenarios.
    bridge = project_query_fixture.ProjectQueryCases.bridge
    body = project_query_fixture.ProjectQueryCases.body
    authorize = project_query_fixture.ProjectQueryCases.authorize

    def setUp(self):
        super().setUp()
        self.intake = ProjectIntakeService(self.root / "p", authenticate=authenticate)
        self.addCleanup(self.intake.close)
        self.stage1 = ProjectStage1Service(self.intake, limit=3)
        self.queries = self.bridge()
        self.admission = Mock(wraps=self.queries.admit)
        self.queries.admit = self.admission
        created = self.intake.create(
            "alice-token",
            {"key": "create", "topic": "RL traffic control with robust validation"},
        )
        self.ref = created["project_ref"]
        submitted = submit_body(self.intake.read("alice-token", self.ref))
        submitted["budgets"].update(seconds=100, search_calls=2, rounds=1)
        submitted["consent"]["external_search"] = True
        self.intake.submit("alice-token", self.ref, submitted)
        self.intake.compile(
            "alice-token",
            self.ref,
            compile_body(self.intake.read("alice-token", self.ref)),
        )
        self.host = SimpleNamespace(
            projects=self.intake,
            project_stage1=self.stage1,
            project_models=None,
            project_stage2=None,
            project_stage1_delivery=ProjectStage1DeliveryService(self.stage1),
            project_records_prepare=None,
            project_expansions=None,
            project_stage1_sources=None,
            project_stage1_records=None,
        )
        for name in ("overview", "stage1_view", "continue_stage1"):
            setattr(self.host, name, MethodType(getattr(ProjectHost, name), self.host))

    def continue_run(self, run_id="synthetic-auto"):
        return self.host.continue_stage1(
            "alice-token",
            self.ref,
            run_id=run_id,
            deadline=time.monotonic() + 90,
            max_actions=8,
        )

    def saved_identity_only(self, pin, **options):
        self.assertFalse(options.get("probe", False), "no new SDK probe")
        return verify_identity(pin, **options)

    def test_authorized_two_backend_queries_advance_then_stop_at_screening(self):
        self.authorize()
        modes = iter(("empty", "rows"))
        observed_modes = []
        original_audit = planned_query_fixture.synthetic_audit

        def backend_audit(root, backend, _mode, argv):
            mode = next(modes)
            observed_modes.append(mode)
            return original_audit(root, backend, mode, argv)

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "stage1_retrieval.runtime_identity.verify_identity",
                    side_effect=lambda pin, **kw: verify_identity(pin),
                )
            )
            stack.enter_context(self.no_probe())
            stack.enter_context(self.fake_runner())
            stack.enter_context(
                patch.object(
                    planned_query_fixture,
                    "synthetic_audit",
                    side_effect=backend_audit,
                )
            )
            result = self.continue_run()
        if observed_modes != ["empty", "rows"]:
            # Only synthetic fixture state enters the private test failure log.
            with self.intake._lock:
                state = self.intake._load("alice", self.ref)
                jobs = {
                    digest: {
                        key: job.get(key)
                        for key in (
                            "key",
                            "request_sha256",
                            "status",
                            "error",
                        )
                    }
                    for digest, job in state.get("stage1_query_jobs", {}).items()
                }
                receipts = []
                for action in result["actions"]:
                    receipt = self.intake.action(
                        "alice-token",
                        action["key"],
                        project_ref=self.ref,
                    )
                    receipts.append(
                        {
                            key: receipt.get(key)
                            for key in (
                                "key",
                                "request_sha256",
                                "kind",
                                "status",
                                "query_action_key",
                            )
                        }
                    )
            print(
                "SYNTHETIC_AUTO_FAILURE="
                + json.dumps(
                    {"jobs": jobs, "receipts": receipts},
                    sort_keys=True,
                ),
                flush=True,
            )
        self.assertEqual(observed_modes, ["empty", "rows"], result)
        self.assertEqual(len(self.children), 2, result)
        self.assertEqual(result["action_count"], 3, result)
        self.assertEqual(result["status"], "partial", result)
        self.assertEqual(result["reason"], "no-next-action", result)
        self.assertFalse(result["stage1_complete"])
        self.assertFalse(result["scientific_acceptance"])
        self.assertFalse(result["stage2_started"])
        overview = self.host.overview("alice-token", self.ref)
        self.assertEqual(
            overview["stage1"]["progress"]["next_action"]["phase_id"], "screening"
        )
        self.assertEqual(overview["stage1"]["ledger"]["counts"]["works"], 1)
        query_view = self.queries.read("alice-token", self.ref)
        self.assertEqual(
            query_view["budget"], {"probes": 1, "attempts": 2, "seconds": 94}
        )
        owner = self.queries.services[self.ref]
        history = owner.view("alice-token", self.ref)["history"]
        self.assertEqual(len(history), 2)
        self.assertTrue(all(row["status"] == "completed" for row in history), history)
        self.assertFalse(self.queries.workers[self.ref].is_alive())
        self.assertFalse(owner._workers[self.ref].is_alive())
        saved_actions = deepcopy(self.intake.history("alice-token", self.ref))
        saved_budget = deepcopy(query_view["budget"])
        saved_admissions = self.admission.call_count
        self.assertGreater(saved_admissions, 0)
        with (
            patch(
                "stage1_retrieval.runtime_identity.verify_identity",
                side_effect=self.saved_identity_only,
            ),
            patch(
                "stage1_retrieval.runner.execute",
                side_effect=AssertionError("no repeat search"),
            ),
        ):
            repeated = self.continue_run()
        self.assertEqual(repeated["action_count"], 0, repeated)
        self.assertEqual(repeated["reason"], "no-next-action", repeated)
        self.assertEqual(self.intake.history("alice-token", self.ref), saved_actions)
        self.assertEqual(
            self.queries.read("alice-token", self.ref)["budget"], saved_budget
        )
        self.assertEqual(self.admission.call_count, saved_admissions)
        self.assertEqual(len(self.children), 2)

    def test_permission_required_and_invalid_credential_dispatch_nothing(self):
        before = deepcopy(self.intake.history("alice-token", self.ref))
        with (
            patch(
                "stage1_retrieval.runtime_identity.verify_identity",
                side_effect=self.saved_identity_only,
            ),
            patch(
                "stage1_retrieval.runner.execute",
                side_effect=AssertionError("no authorized search"),
            ),
        ):
            result = self.continue_run()
            with self.assertRaises(SessionApiError):
                self.host.continue_stage1(
                    "invalid-token",
                    self.ref,
                    run_id="unauthorized",
                    deadline=time.monotonic() + 30,
                    max_actions=8,
                )
        self.assertEqual(result["action_count"], 0, result)
        self.assertFalse(result["stage1_complete"])
        view = self.queries.read("alice-token", self.ref)
        self.assertEqual(view["status"], "permission-required")
        self.assertEqual(view["budget"], {"probes": 0, "attempts": 0, "seconds": 0})
        self.assertEqual(self.intake.history("alice-token", self.ref), before)
        self.assertEqual(self.admission.call_count, 0)
        self.assertEqual(self.children, [])

    def test_unknown_owned_bootstrap_stays_stopped_without_resend(self):
        self.authorize()
        with patch(
            "stage1_retrieval.runtime_identity.verify_identity",
            side_effect=RuntimeError("synthetic probe outcome unobserved"),
        ) as probe:
            result = self.continue_run("synthetic-unknown")
        self.assertEqual(probe.call_count, 1)
        self.assertEqual(result["action_count"], 1, result)
        self.assertEqual(result["status"], "held", result)
        self.assertEqual(result["reason"], "durable-action-execution-unknown", result)
        view = self.queries.read("alice-token", self.ref)
        self.assertEqual(view["jobs"][0]["status"], "execution-unknown", view)
        self.assertEqual(view["budget"], {"probes": 1, "attempts": 0, "seconds": 30})
        history = deepcopy(self.intake.history("alice-token", self.ref))
        saved_admissions = self.admission.call_count
        with (
            patch(
                "stage1_retrieval.runtime_identity.verify_identity",
                side_effect=self.saved_identity_only,
            ),
            patch(
                "stage1_retrieval.runner.execute",
                side_effect=AssertionError("no search after unknown"),
            ),
        ):
            repeated = self.continue_run("synthetic-unknown")
        self.assertEqual(repeated["action_count"], 0, repeated)
        self.assertEqual(
            repeated["reason"], "durable-action-execution-unknown", repeated
        )
        self.assertEqual(
            self.queries.read("alice-token", self.ref)["budget"], view["budget"]
        )
        self.assertEqual(self.intake.history("alice-token", self.ref), history)
        self.assertEqual(self.admission.call_count, saved_admissions)
        self.assertEqual(self.children, [])
