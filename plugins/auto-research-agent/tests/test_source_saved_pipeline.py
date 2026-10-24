"""One exact fresh-loader engineering case; no discovery/full inherited suite."""

import os
import unittest

import atlas_test_paths  # noqa: F401
from planned_query_raw_runner import run_cases


@unittest.skipUnless(os.name == "nt", "actual Windows Job containment")
class SourceSavedPipelineIntegrationTests(unittest.TestCase):
    def test_authored_transport_actual_sdk_core_registry_and_same_key_no_repeat(self):
        run_cases(
            "source_saved_pipeline_cases.SourceSavedPipelineCases."
            "test_authored_transport_actual_sdk_core_registry_and_same_key_no_repeat",
            self,
            complete_plugin=True,
            # The saved-parser job retains its original 300-second maximum;
            # this test also prepares and verifies the complete SDK snapshot.
            timeout_seconds=600,
        )

    def test_run_grant_actual_sdk_core_registry_and_same_key_no_repeat(self):
        run_cases(
            "source_saved_pipeline_cases.SourceSavedPipelineCases.test_run_grant_actual_sdk_core_registry_and_same_key_no_repeat",
            self,
            complete_plugin=True,
            timeout_seconds=600,
        )

    def test_run_grant_revoked_after_actual_sdk_preserves_receipt_without_core(self):
        run_cases(
            "source_saved_pipeline_cases.SourceSavedPipelineCases.test_run_grant_revoked_after_actual_sdk_preserves_receipt_without_core",
            self,
            complete_plugin=True,
            timeout_seconds=600,
        )

    def test_run_grant_revoked_after_core_preserves_source_without_final_success(self):
        run_cases(
            "source_saved_pipeline_cases.SourceSavedPipelineCases.test_run_grant_revoked_after_core_preserves_source_without_final_success",
            self,
            complete_plugin=True,
            timeout_seconds=600,
        )

    def test_run_grant_revoked_after_registry_preserves_prefix_without_final_success(
        self,
    ):
        run_cases(
            "source_saved_pipeline_cases.SourceSavedPipelineCases.test_run_grant_revoked_after_registry_preserves_prefix_without_final_success",
            self,
            complete_plugin=True,
            timeout_seconds=600,
        )


class SourceSavedPipelineDeadlineTests(unittest.TestCase):
    def test_worker_gate_refuses_expired_original_deadline_before_verifier(self):
        from datetime import datetime, timedelta, timezone
        from types import SimpleNamespace
        from unittest.mock import Mock, patch

        from research_workspace_native.project_source_saved_pipeline import (
            SourceJobDeadline,
            _OwnedPipelineGuard,
        )
        from research_workspace_native.session_api import SessionApiError

        now = datetime.now(timezone.utc)
        service = SimpleNamespace(
            clock=lambda: now.timestamp(),
            verify_configuration=Mock(),
            _runner_guard=Mock(),
        )
        job = {
            "binding": {"deadline_at": now.timestamp() + 60},
            "transport_request": {
                "deadline_utc": (now + timedelta(seconds=60)).isoformat(),
                "total_timeout_seconds": 60,
            },
        }
        with patch(
            "research_workspace_native.project_source_saved_pipeline.time.monotonic",
            return_value=100,
        ) as monotonic:
            deadline = SourceJobDeadline(service, job)
            original_end = deadline.end
            # Only pre-Core state is needed: expiration must precede any I/O.
            guard = _OwnedPipelineGuard.__new__(_OwnedPipelineGuard)
            guard.intent_key = guard.source_id = None
            guard.expected, guard.before = [], []
            guard.deadline, guard.deadline_end = deadline, original_end
            guard.service = service
            monotonic.return_value = original_end + 1
            with self.assertRaises(SessionApiError) as refused:
                guard(worker_gate=True)

        self.assertEqual(
            refused.exception.code, "source-pipeline-original-deadline-expired"
        )
        self.assertEqual(refused.exception.status, 408)
        self.assertIs(guard.deadline, deadline)
        self.assertEqual(deadline.end, original_end)
        service._runner_guard.assert_not_called()
        service.verify_configuration.assert_not_called()


if __name__ == "__main__":
    unittest.main()
