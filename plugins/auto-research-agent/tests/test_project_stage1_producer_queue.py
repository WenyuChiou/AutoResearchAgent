"""Actual saved-state tests for the read-only Stage 1 producer inspector."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from analysis_run_fixture import analysis_proposal, analysis_run_fixture
from research_workspace_native.project_agent_coverage import (
    ProjectAgentCoverageService,
)
from research_workspace_native.project_agent_analysis import (
    ProjectStage1AnalysisService,
)
from research_workspace_native.project_model import _output_ref
from research_workspace_native.project_stage1_producer_queue import (
    ProjectStage1ProducerQueue,
)
from test_project_agent_coverage import coverage_proposal


def legacy_include_proposal(context):
    proposal = analysis_proposal(context)
    proposal["screening"].update(
        decision="include",
        reason_code="authored-fixture-legacy-include",
        rationale="Include the authored fixture while coverage evidence remains unavailable in legacy schema 1.0.",
    )
    return proposal


class ProducerQueueTests(unittest.TestCase):
    def test_legacy_included_adoption_holds_unsupported_coverage_review(self):
        with analysis_run_fixture(proposal_builder=legacy_include_proposal) as run:
            queue = ProjectStage1ProducerQueue(
                run.case.delivery.stage1, run.model, run.case.producer
            )
            analysis = ProjectStage1AnalysisService(
                run.case.delivery.stage1, run.model, run.case.producer
            )
            selection = queue.inspect("alice-token", run.ref)["selection"]
            body, token = run.derived(
                "stage1-agent-analysis", "agent-adoption", selection["body"]
            )
            analysis.adopt("alice-token", run.ref, body, run_authorization=token)
            calls = len(run.calls)
            observed = queue.inspect("alice-token", run.ref)
            self.assertEqual(observed["view"]["status"], "held")
            self.assertEqual(
                observed["view"]["next_action"]["reason"],
                "producer-coverage-analysis-version-unsupported",
            )
            self.assertIsNone(observed["selection"])
            self.assertFalse(observed["view"]["research_complete"])
            self.assertEqual(len(run.calls), calls)

    def test_completed_job_with_missing_owner_registration_holds(self):
        with analysis_run_fixture() as run:
            queue = ProjectStage1ProducerQueue(
                run.case.delivery.stage1, run.model, run.case.producer
            )
            registration = run.model._registrations.pop(run.job["offer_ref"])
            calls = len(run.calls)
            try:
                observed = queue.inspect("alice-token", run.ref)
            finally:
                run.model._registrations[run.job["offer_ref"]] = registration
            self.assertEqual(observed["view"]["status"], "held")
            self.assertEqual(
                observed["view"]["next_action"]["reason"],
                "producer-analysis-adoption-unavailable",
            )
            self.assertIsNone(observed["selection"])
            self.assertEqual(len(run.calls), calls)

    def test_actual_coverage_review_then_registration_is_not_duplicated(self):
        with analysis_run_fixture(
            proposal_builder=coverage_proposal, analysis_coverage=True
        ) as run:
            queue = ProjectStage1ProducerQueue(
                run.case.delivery.stage1, run.model, run.case.producer
            )
            analysis = ProjectStage1AnalysisService(
                run.case.delivery.stage1, run.model, run.case.producer
            )
            coverage = ProjectAgentCoverageService(analysis)
            calls = len(run.calls)
            adoption_selection = queue.inspect("alice-token", run.ref)["selection"]
            self.assertEqual(adoption_selection["operation"], "analysis-adopt")
            adoption_body, adoption_token = run.derived(
                "stage1-agent-analysis",
                "agent-adoption",
                adoption_selection["body"],
            )
            adoption = analysis.adopt(
                "alice-token",
                run.ref,
                adoption_body,
                run_authorization=adoption_token,
            )

            review_selection = queue.inspect("alice-token", run.ref)["selection"]
            self.assertEqual(review_selection["operation"], "coverage-review")
            self.assertEqual(
                review_selection["body"],
                dict(
                    adoption_key=adoption_body["key"],
                    adoption_request_sha256=adoption["request_sha256"],
                ),
            )
            review_body, review_token = run.derived(
                "stage1-agent-coverage",
                "agent-adoption",
                review_selection["body"],
            )
            review = coverage.review(
                "alice-token", run.ref, review_body, run_authorization=review_token
            )

            register_selection = queue.inspect("alice-token", run.ref)["selection"]
            self.assertEqual(register_selection["operation"], "register-coverage")
            self.assertEqual(
                register_selection["body"],
                dict(
                    adoption_key=review_body["key"],
                    adoption_request_sha256=review["request_sha256"],
                    reading_sha256=review["reading_sha256"],
                ),
            )
            register_body, register_token = run.derived(
                "stage1-agent-reading", "records", register_selection["body"]
            )
            coverage.register(
                "alice-token", run.ref, register_body, run_authorization=register_token
            )
            completed = queue.inspect("alice-token", run.ref)
            self.assertFalse(completed["view"]["research_complete"])
            self.assertTrue(
                completed["selection"] is None
                or completed["selection"]["operation"] != "register-coverage"
            )
            self.assertEqual(len(run.calls), calls)

    def test_uncapped_saved_job_adoption_then_registration_without_resend(self):
        with analysis_run_fixture() as run:
            queue = ProjectStage1ProducerQueue(
                run.case.delivery.stage1, run.model, run.case.producer
            )
            calls = len(run.calls)
            observed = queue.inspect("alice-token", run.ref)
            self.assertEqual(observed["view"]["kind"], "ProjectStage1ProducerQueue")
            self.assertEqual(observed["view"]["schema_version"], "1.0.0")
            self.assertEqual(
                observed["view"]["ledger_state_sha256"], run.ledger.state_hash()
            )
            self.assertEqual(observed["view"]["status"], "ready")
            self.assertEqual(observed["selection"]["operation"], "analysis-adopt")
            self.assertEqual(
                observed["selection"]["body"],
                dict(
                    output_ref=_output_ref(run.job),
                    draft_sha256=run.job["analysis_draft"]["sha256"],
                ),
            )
            project = run.case.intake.read("alice-token", run.ref)
            self.assertEqual(
                observed["view"]["binding"],
                {
                    key: project[key]
                    for key in (
                        "project_ref",
                        "revision",
                        "input_version",
                        "brief_sha256",
                    )
                },
            )
            self.assertEqual(len(run.calls), calls)

            analysis = ProjectStage1AnalysisService(
                run.case.delivery.stage1, run.model, run.case.producer
            )
            body, token = run.derived(
                "stage1-agent-analysis",
                "agent-adoption",
                observed["selection"]["body"],
            )
            adoption = analysis.adopt(
                "alice-token", run.ref, body, run_authorization=token
            )
            followup = queue.inspect("alice-token", run.ref)
            self.assertEqual(followup["selection"]["operation"], "register-analysis")
            self.assertEqual(
                followup["selection"]["body"],
                dict(
                    adoption_key=body["key"],
                    adoption_request_sha256=adoption["request_sha256"],
                    reading_sha256=adoption["reading_sha256"],
                ),
            )
            self.assertEqual(len(run.calls), calls)

    def test_current_unknown_job_holds_without_provider_resend(self):
        with analysis_run_fixture() as run:
            queue = ProjectStage1ProducerQueue(
                run.case.delivery.stage1, run.model, run.case.producer
            )
            state = run.case.intake._load("alice", run.ref)
            changed = deepcopy(state)
            changed["model_operations"]["jobs"][run.job["key"]]["status"] = (
                "execution-unknown"
            )
            calls = len(run.calls)
            with patch.object(run.case.intake, "_load", return_value=changed):
                observed = queue.inspect("alice-token", run.ref)
            self.assertEqual(observed["view"]["status"], "held")
            self.assertEqual(observed["view"]["blocked_work_count"], 1)
            self.assertEqual(
                observed["view"]["next_action"]["reason"],
                "producer-model-job-terminal",
            )
            self.assertIsNone(observed["selection"])
            self.assertEqual(len(run.calls), calls)


if __name__ == "__main__":
    unittest.main()
