"""Original broker/dispatcher with authored receipt bytes; no HTTP, SDK or model."""

import time
from types import SimpleNamespace, MethodType
import unittest

from project_source_run_cases import setup_case
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_stage1_auto import ProjectStage1AutoDriver
from research_workspace_native.project_stage1_delivery import (
    ProjectStage1DeliveryService,
)
from research_workspace_native.project_stage1_run_actions import ProjectStage1RunActions
from research_workspace_native.project_source_dispatcher import ProjectSourceDispatcher


class RunSourceDispatchTests(unittest.TestCase):
    def test_actual_broker_queue_is_dispatched_once_and_replayed_without_resend(self):
        with setup_case() as (case, issuer, grant, consent, derived, revoke):
            stage1 = case.sources.stage1
            dispatcher = ProjectSourceDispatcher(case.sources)
            try:
                host = SimpleNamespace(
                    projects=case.intake,
                    project_stage1=stage1,
                    project_models=None,
                    project_stage2=None,
                    project_stage1_delivery=ProjectStage1DeliveryService(stage1),
                    project_records_prepare=None,
                    project_stage1_records=None,
                    project_stage1_sources=case.sources,
                    project_expansions=None,
                    project_stage1_source_dispatcher=dispatcher,
                )
                for name in ("overview", "stage1_view"):
                    setattr(host, name, MethodType(getattr(ProjectHost, name), host))
                driver = ProjectStage1AutoDriver(host, case.token, case.ref)
                actions = ProjectStage1RunActions(
                    driver, issuer, grant["grant_ref"], grant["grant_sha256"]
                )
                offer = case.offered()
                action = actions.prepare(
                    driver.snapshot(),
                    "source-authorize",
                    dict(
                        work_ref=offer["work_ref"],
                        offer_ref=offer["offer_ref"],
                        offer_sha256=offer["offer_sha256"],
                    ),
                )
                saved = actions.dispatch(
                    action, actions.key_for(action), time.monotonic() + 30
                )
                extra = dict(
                    grant_ref=saved["grant_ref"], grant_sha256=saved["grant_sha256"]
                )
                action = actions.prepare(driver.snapshot(), "source-execute", extra)
                key = actions.key_for(action)
                result = actions.dispatch(action, key, time.monotonic() + 30)
                self.assertEqual(result["status"], "saved")
                worker = dispatcher._workers[(case.ref, key)]
                worker.join(30)
                self.assertFalse(worker.is_alive())
                job = case.sources.read(case.token, case.ref)["jobs"][key]
                self.assertEqual(job["status"], "source-observation-saved", job)
                self.assertEqual(len(case.transport.calls), 1)
                self.assertFalse(job["result"]["reading_complete"])
                before = case.intake.history(case.token, case.ref)
                replay = actions.prepare(driver.snapshot(), "source-execute", extra)
                self.assertEqual(actions.key_for(replay), key)
                result = actions.dispatch(replay, key, time.monotonic() + 30)
                self.assertTrue(result["replayed"])
                self.assertEqual(len(case.transport.calls), 1)
                self.assertEqual(case.intake.history(case.token, case.ref), before)
            finally:
                dispatcher.close()


if __name__ == "__main__":
    unittest.main()
