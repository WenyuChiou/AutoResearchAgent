"""Real intake/Core adoption and original content-key publication; synthetic source/model."""

import time
from types import SimpleNamespace, MethodType
import unittest

from analysis_run_fixture import analysis_run_fixture
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_records_prepare import (
    ProjectRecordsPrepareService,
)
from research_workspace_native.project_stage1_auto import ProjectStage1AutoDriver
from research_workspace_native.project_stage1_run_actions import ProjectStage1RunActions
from research_workspace_native.project_stage1_run_grant import (
    ProjectStage1RunGrantService,
    STORE,
)
from research_workspace_native.project_model import _output_ref
from research_workspace_native.session_api import SessionApiError


class RunActionsTests(unittest.TestCase):
    def test_actual_saved_adoption_and_original_registry_keys_without_alias_receipts(
        self,
    ):
        with analysis_run_fixture() as run:
            host = SimpleNamespace(
                projects=run.case.intake,
                project_stage1=run.case.delivery.stage1,
                project_models=run.model,
                project_stage2=None,
                project_stage1_delivery=run.case.delivery,
                project_records_prepare=ProjectRecordsPrepareService(run.case.producer),
                project_stage1_records=run.case.producer,
                project_stage1_sources=None,
                project_expansions=None,
            )
            for name in ("overview", "stage1_view"):
                setattr(host, name, MethodType(getattr(ProjectHost, name), host))
            driver = ProjectStage1AutoDriver(host, "alice-token", run.ref)
            clock = SimpleNamespace(now=1_900_000_000)
            issuer = ProjectStage1RunGrantService(
                run.case.intake, runtime_sha256="a" * 64, clock=lambda: clock.now
            )
            grant_ref, grant_row = next(
                iter(run.case.intake._load("alice", run.ref)[STORE].items())
            )
            adapter = ProjectStage1RunActions(
                driver, issuer, grant_ref, grant_row["sha256"]
            )
            original_calls = len(run.calls)
            action = adapter.prepare(
                driver.snapshot(),
                "analysis-adopt",
                dict(
                    output_ref=_output_ref(run.job),
                    draft_sha256=run.job["analysis_draft"]["sha256"],
                ),
            )
            key = adapter.key_for(action)
            adapter.dispatch(action, key, time.monotonic() + 90)
            adoption = run.case.intake.action("alice-token", key, project_ref=run.ref)
            self.assertEqual(adoption["status"], "saved")
            self.assertFalse(adoption["human_per_action_confirmation"])
            action = adapter.prepare(
                driver.snapshot(),
                "register-analysis",
                dict(
                    adoption_key=key,
                    adoption_request_sha256=adoption["request_sha256"],
                    reading_sha256=adoption["reading_sha256"],
                ),
            )
            registry_key = adapter.key_for(action)
            self.assertTrue(registry_key.startswith("stage1-reading-registry-"))
            result = adapter.dispatch(action, registry_key, time.monotonic() + 90)
            self.assertEqual(result["registry_entry"]["ref"], registry_key)
            actual = run.case.intake.action(
                "alice-token", registry_key, project_ref=run.ref
            )
            self.assertEqual(actual["kind"], "stage1-reading-registry")
            self.assertEqual(actual["status"], "saved")
            self.assertEqual(len(run.calls), original_calls)
            self.assertFalse(result["stage1_complete"])
            history = run.case.intake.history("alice-token", run.ref)
            for invalid in ([], "native-untrusted", None):
                with (
                    self.subTest(operation=invalid),
                    self.assertRaises(SessionApiError),
                ):
                    adapter.prepare(driver.snapshot(), invalid, {})
            with self.assertRaises(SessionApiError):
                adapter.prepare(driver.snapshot(), "checkpoint", dict(confirmed=True))
            with self.assertRaises(SessionApiError):
                ProjectStage1RunActions(driver, {}, grant_ref, grant_row["sha256"])
            candidate = adapter.prepare(driver.snapshot(), "checkpoint", {})
            with self.assertRaises(SessionApiError):
                adapter.dispatch(candidate, "forged-key", time.monotonic() + 20)
            self.assertEqual(run.case.intake.history("alice-token", run.ref), history)
            clock.now = grant_row["document"]["expires_at"]
            with self.assertRaises(SessionApiError):
                adapter.prepare(driver.snapshot(), "checkpoint", {})
            self.assertEqual(run.case.intake.history("alice-token", run.ref), history)
            self.assertEqual(len(run.calls), original_calls)


if __name__ == "__main__":
    unittest.main()
