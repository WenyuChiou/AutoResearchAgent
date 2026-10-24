"""Pure key preview versus actual saved run-derived authority, no provider I/O."""

import unittest
from research_workspace_native import project_stage1_run_grant as grants
from research_workspace_native.project_run_authority import (
    RunActionGuard,
    action_identity,
)
from research_workspace_native.session_api import SessionApiError
import test_project_stage1_run_grant as fixtures


class ActionKeyTests(unittest.TestCase):
    setUp = fixtures.RunGrantTests.setUp
    body = fixtures.RunGrantTests.body
    authorize = fixtures.RunGrantTests.authorize

    def test_preview_is_pure_and_matches_actual_typed_derived_work_key(self):
        grant = self.authorize()
        binding = self.intake.binding(self.ref)
        body = dict(
            confirmed=False,
            input_version=binding["input_version"],
            brief_sha256=binding["brief_sha256"],
            work_ref="authored-work",
            snapshot_sha256="d" * 64,
        )
        identity = action_identity("model-authorize", body)
        before = self.intake.history("alice-token", self.ref)
        key = grants.derived_action_key(
            grant["grant_sha256"], "analyze-full-paper", identity
        )
        self.assertEqual(self.intake.history("alice-token", self.ref), before)
        token = self.service.derive(
            "alice-token",
            self.ref,
            grant_ref=grant["grant_ref"],
            grant_sha256=grant["grant_sha256"],
            operation="analyze-full-paper",
            identity=identity,
        )
        self.assertEqual(token.key, key)
        body.update(
            key=key + "-work",
            revision=self.intake.read("alice-token", self.ref)["revision"],
        )
        guard = RunActionGuard(
            self.intake,
            "alice",
            self.ref,
            body,
            token,
            operation="analyze-full-paper",
            action="model-authorize",
        )
        self.assertEqual(guard.request["run_authority"]["action_key"], key)
        self.assertFalse(
            guard.request["run_authority"]["human_per_action_confirmation"]
        )
        repeated = self.service.derive(
            "alice-token",
            self.ref,
            grant_ref=grant["grant_ref"],
            grant_sha256=grant["grant_sha256"],
            operation="analyze-full-paper",
            identity=identity,
        )
        self.assertEqual(repeated.key, key)

    def test_preview_refuses_malformed_inputs_without_grant_or_action(self):
        before = self.intake.history("alice-token", self.ref)
        for pin, operation, identity in [
            ("bad", "query", "b" * 64),
            ("a" * 64, [], "b" * 64),
            ("a" * 64, "stage2-research", "b" * 64),
            ("a" * 64, "query", False),
        ]:
            with self.subTest(operation=operation), self.assertRaises(SessionApiError):
                grants.derived_action_key(pin, operation, identity)
        self.assertEqual(self.intake.history("alice-token", self.ref), before)


if __name__ == "__main__":
    unittest.main()
