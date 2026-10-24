"""Run-derived request provenance over the real saved grant, no provider I/O."""

import unittest

from research_workspace_native.project_run_authority import (
    RunActionGuard,
    action_identity,
    saved_run_check,
)
from research_workspace_native.session_api import SessionApiError
import test_project_stage1_run_grant as fixtures


class RunAuthorityTests(unittest.TestCase):
    setUp = fixtures.RunGrantTests.setUp
    body = fixtures.RunGrantTests.body
    authorize = fixtures.RunGrantTests.authorize

    def request(self):
        grant = self.authorize()
        binding = self.intake.binding(self.ref)
        request = dict(
            confirmed=False,
            user_input=self.body()["user_input"],
            input_version=binding["input_version"],
            brief_sha256=binding["brief_sha256"],
            operation="analyze-full-paper",
            work_ref="work-1",
            snapshot_sha256="d" * 64,
        )
        identity = action_identity("model-authorize", request)
        token = self.service.derive(
            "alice-token",
            self.ref,
            grant_ref=grant["grant_ref"],
            grant_sha256=grant["grant_sha256"],
            operation="analyze-full-paper",
            identity=identity,
        )
        request.update(key=token.key + "-work", revision=4)
        return grant, request, token

    def guard(self, request, token):
        return RunActionGuard(
            self.intake,
            "alice",
            self.ref,
            request,
            token,
            operation="analyze-full-paper",
            action="model-authorize",
        )

    def test_exact_request_has_original_consent_and_agent_proof(self):
        _, request, token = self.request()
        guard = self.guard(request, token)
        self.assertFalse(guard.request["confirmed"])
        self.assertFalse(
            guard.request["run_authority"]["human_per_action_confirmation"]
        )
        self.assertEqual(guard.request["run_user_input"], self.body()["user_input"])
        self.assertNotIn("run_authority", request)
        self.assertEqual(guard.remaining_seconds(), 100)

    def test_browser_proof_wrong_action_and_changed_payload_refuse(self):
        _, request, token = self.request()
        for changed in (
            {"confirmed": True},
            {"user_input": "I reviewed every paper"},
            {"snapshot_sha256": "e" * 64},
            {"work_ref": "work-2"},
            {"key": "another-key"},
            {"run_authority": {}},
        ):
            with self.subTest(changed=changed), self.assertRaises(SessionApiError):
                self.guard({**request, **changed}, token)
        with self.assertRaises(SessionApiError):
            self.guard(request, dict(grant_ref=token.grant_ref))
        with self.assertRaises(SessionApiError):
            RunActionGuard(
                self.intake,
                "alice",
                self.ref,
                request,
                token,
                operation="analyze-full-paper",
                action="source-authorize",
            )

    def test_saved_proof_needs_real_issuer_and_exact_saved_intent(self):
        _, request, token = self.request()
        guard = self.guard(request, token)
        proof = guard.request["run_authority"]
        restored = saved_run_check(
            self.service,
            self.intake,
            "alice",
            self.ref,
            proof=proof,
            operation="analyze-full-paper",
            identity=guard.identity,
        )
        self.assertEqual(restored.key, token.key)
        for changed in (
            {**proof, "automated_actor": "human"},
            {**proof, "action_key": "fake"},
        ):
            with self.assertRaises(SessionApiError):
                saved_run_check(
                    self.service,
                    self.intake,
                    "alice",
                    self.ref,
                    proof=changed,
                    operation="analyze-full-paper",
                    identity=guard.identity,
                )

    def test_remaining_time_rejects_its_own_clock_rollback_durably(self):
        _, request, token = self.request()
        guard = self.guard(request, token)
        samples = iter([1050.0, 1050.0, 1001.0])
        self.service.clock = lambda: next(samples)
        with self.assertRaisesRegex(SessionApiError, "clock-regressed"):
            guard.remaining_seconds()
        self.service.clock = lambda: 1051.0
        with self.assertRaisesRegex(SessionApiError, "clock-regressed"):
            self.guard(request, token)
        reopened = fixtures.ProjectStage1RunGrantService(
            self.intake, runtime_sha256="a" * 64, clock=lambda: 1052.0
        )
        with self.assertRaisesRegex(SessionApiError, "clock-regressed"):
            reopened.inspect(
                "alice-token", self.ref, token.grant_ref, token.grant_sha256
            )

    def test_expiry_rechecks_before_followup_action(self):
        _, request, token = self.request()
        guard = self.guard(request, token)
        callback = guard.deadline_check()
        self.now = 1100
        with self.assertRaises(SessionApiError):
            callback()


if __name__ == "__main__":
    unittest.main()
