"""Actual local Core round metadata with run consent; no provider or SDK calls."""

import unittest
from copy import deepcopy
from unittest.mock import patch

import test_project_stage1_coverage as coverage_fixture
from research_workspace_native.project_agent_rounds import record_round
from research_workspace_native.project_run_authority import action_identity
from research_workspace_native.project_stage1_run_grant import (
    ProjectStage1RunGrantService,
    SCOPE,
)
from research_workspace_native.session_api import SessionApiError
from test_workspace_project_intake import bound_body


class AgentRoundTests(unittest.TestCase):
    def setUp(self):
        self.base = coverage_fixture.ProjectCoverageTests()
        original = coverage_fixture.submit_body

        def funded(view):
            body = original(view)
            body["budgets"]["seconds"] = 120
            return body

        with patch.object(coverage_fixture, "submit_body", side_effect=funded):
            self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.intake, self.ref = self.base.case.intake, self.base.ref
        self.stage1, self.ledger = self.base.case.service, self.base.ledger
        self.now = 1000.0
        self.grants = ProjectStage1RunGrantService(
            self.intake, runtime_sha256="a" * 64, clock=lambda: self.now
        )
        self.grant = self.grants.authorize(
            "alice-token",
            self.ref,
            dict(
                bound_body(self.intake.read("alice-token", self.ref), "run-consent"),
                confirmed=True,
                user_input="Record local round metadata within saved limits; never accept-stop.",
                scope=SCOPE,
                operations=["agent-adoption"],
                max_seconds=min(
                    30, self.intake.binding(self.ref)["settings"]["budgets"]["seconds"]
                ),
                max_actions=16,
            ),
        )

    def action(self, operation, review, target=None):
        body = self.base.body(operation, review, target)
        body["confirmed"] = False
        token = self.grants.derive(
            "alice-token",
            self.ref,
            grant_ref=self.grant["grant_ref"],
            grant_sha256=self.grant["grant_sha256"],
            operation="agent-adoption",
            identity=action_identity("stage1-coverage", body),
        )
        body.update(
            key=token.key + "-work",
            revision=self.intake.read("alice-token", self.ref)["revision"],
        )
        return body, token

    def submit(self, operation, review, target=None):
        body, token = self.action(operation, review, target)
        return (
            record_round(
                self.stage1, "alice-token", self.ref, body, run_authorization=token
            ),
            body,
            token,
        )

    def test_observed_receipts_close_and_open_original_round_without_human_stop(self):
        for planned in self.ledger.coverage_state().queries:
            event = self.base.observe(planned)
            saved, body, token = self.submit(
                "receipt",
                dict(
                    truncated=None,
                    note="Observed empty fixture; truncation remains Unknown.",
                ),
                event,
            )
            self.assertFalse(saved["human_per_action_confirmation"])
            self.assertIsNone(self.ledger.coverage_state().receipts[event]["truncated"])
            before = self.ledger.events()
            replay = record_round(
                self.stage1,
                "alice-token",
                self.ref,
                dict(body, revision=999),
                run_authorization=token,
            )
            self.assertTrue(replay["replayed"])
            self.assertEqual(self.ledger.events(), before)
        closed, _, _ = self.submit("close-round", {})
        self.assertEqual(closed["operation"], "close-round")
        self.assertEqual(len(self.ledger.coverage_state().closed), 1)
        opened, _, _ = self.submit("open-round", {})
        self.assertEqual(opened["operation"], "open-round")
        self.assertEqual(self.ledger.coverage_state().active, 2)
        self.assertFalse(opened["stage1_complete"])
        self.assertFalse(
            any(
                row["payload"]["kind"] == "CoverageHumanAction"
                for row in self.ledger.events()
            )
        )

    def test_human_and_review_operations_forgery_and_expiry_refuse_before_writes(self):
        body, token = self.action("close-round", {})
        before, history = (
            self.ledger.events(),
            self.intake.history("alice-token", self.ref),
        )
        for operation in ["human-action", "review-work", [], None]:
            with self.subTest(operation=operation), self.assertRaises(SessionApiError):
                record_round(
                    self.stage1,
                    "alice-token",
                    self.ref,
                    dict(body, operation=operation),
                    run_authorization=token,
                )
        for authority in [{}, False, None]:
            with self.subTest(authority=authority), self.assertRaises(SessionApiError):
                record_round(
                    self.stage1,
                    "alice-token",
                    self.ref,
                    deepcopy(body),
                    run_authorization=authority,
                )
        self.now = self.grant["expires_at"]
        with self.assertRaises(SessionApiError):
            record_round(
                self.stage1, "alice-token", self.ref, body, run_authorization=token
            )
        self.assertEqual(self.ledger.events(), before)
        self.assertEqual(self.intake.history("alice-token", self.ref), history)


if __name__ == "__main__":
    unittest.main()
