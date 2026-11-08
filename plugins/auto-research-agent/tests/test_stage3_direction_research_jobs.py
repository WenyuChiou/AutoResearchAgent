"""Authored direction-job research/review integration; no live models."""

# ruff: noqa: E402 -- repository fixture imports.

from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

from research_workspace_native.journal import Journal
from stage3_plan.contracts import Stage3Error, canonical_bytes
from stage3_plan.direction_intent import build_direction_prompt
from stage3_plan.direction_jobs import DirectionPlanningJobs
from stage3_plan.jobs import _ref
from stage3_plan.storage import inspect_package, read_json, write_new
from test_stage3_direction_research import _DirectionResearchFixture


class Stage3DirectionResearchJobsTests(_DirectionResearchFixture):
    def prepare_job(self, callback):
        self.journal = Journal(self.root / "journal.sqlite")
        self.addCleanup(self.journal.close)
        self.journal.bind_project("project-direction-id", "a" * 64)
        owner = self.journal.acquire_owner("project-direction-id", "test-owner")
        self.jobs = DirectionPlanningJobs(
            self.journal,
            "project-direction-id",
            owner,
            self.root / "jobs",
            project_ref="project-direction",
        )
        path = self.root / "input.json"
        write_new(
            path,
            {
                "kind": "Stage3DirectionPlanningJobInput",
                "source": self.direction.source(),
            },
        )
        self.checkpoint = _ref(path)
        return self.jobs.prepare(
            "original-research-job",
            checkpoint=self.checkpoint,
            configuration={"model": "authored-stub", "reasoning": "medium"},
            adapter_context=callback.request_context,
            plan_id="conditional-test",
            expected_revision=self.journal.snapshot(self.jobs.project_id)["revision"],
        )

    def run_job(self, prepared, callback):
        return self.jobs.run(
            "original-research-job",
            expected_request_sha256=prepared["request_sha256"],
            current_checkpoint=self.checkpoint,
            callback=callback,
        )

    def saved_root(self):
        intent = self.journal.snapshot(self.jobs.project_id)["intents"][
            self.jobs._key("original-research-job")
        ]
        return Path(intent["payload"]["output"]) / "plan"

    def test_default_job_keeps_original_prompt_without_research_or_review(self):
        from stage3_plan.direction_research import research_context

        self.plan["planning_status"] = "conditional-draft"
        before = deepcopy(self.context)
        prompt = build_direction_prompt(self.context)
        self.assertIs(research_context(self.context, {}), self.context)
        planner, _ = self.callbacks()
        prepared = self.prepare_job(planner)
        saved = self.run_job(prepared, planner)
        self.assertEqual(saved["result"]["outcome"], "saved")
        self.assertEqual(
            saved["result"]["planning_status"], self.plan["planning_status"]
        )
        self.assertEqual(self.planner_calls[0]["prompt"], prompt)
        self.assertEqual(len(self.planner_calls), 1)
        self.assertEqual(self.reviewer_calls, [])
        self.assertEqual(self.context, before)

    def test_legacy_completed_no_review_job_keeps_exact_completion_evidence(self):
        self.plan["planning_status"] = "conditional-draft"
        planner, _ = self.callbacks()
        prepared = self.prepare_job(planner)
        current_saved = self.jobs._saved

        def historical_completion(*args, **kwargs):
            result = current_saved(*args, **kwargs)
            result["planning_status"] = self.plan["planning_status"]
            return result

        # Authored legacy journal evidence uses the original public result field.
        with patch.object(self.jobs, "_saved", side_effect=historical_completion):
            saved = self.run_job(prepared, planner)
        reread = self.jobs.inspect_saved(
            "original-research-job",
            expected_request_sha256=prepared["request_sha256"],
            current_checkpoint=self.checkpoint,
            expected_plan_manifest_sha256=saved["result"]["plan"]["manifest_sha256"],
        )
        self.assertEqual(reread["result"], saved["result"])
        self.assertEqual((len(self.planner_calls), len(self.reviewer_calls)), (1, 0))

    def test_same_saved_job_replays_plan_and_review_without_dispatch(self):
        adapter = self.adapter()
        prepared = self.prepare_job(adapter)
        saved = self.run_job(prepared, adapter)
        self.assertEqual(saved["result"]["outcome"], "saved")
        self.assertEqual(saved["result"]["planning_status"], "needs-information")
        manifest_sha = saved["result"]["plan"]["manifest_sha256"]
        package = inspect_package(self.saved_root(), manifest_sha)
        self.assertEqual(package["artifacts"]["plan.json"], self.plan)
        self.assertEqual(package["artifacts"]["design-review.json"], self.review())
        self.assertEqual(
            (self.saved_root() / "raw-design-review.txt").read_bytes(),
            canonical_bytes(self.review()),
        )
        self.assertEqual(self.run_job(prepared, adapter), saved)
        reread = self.jobs.inspect_saved(
            "original-research-job",
            expected_request_sha256=prepared["request_sha256"],
            current_checkpoint=self.checkpoint,
            expected_plan_manifest_sha256=manifest_sha,
        )
        self.assertEqual(reread["result"], saved["result"])
        self.assertEqual((len(self.planner_calls), len(self.reviewer_calls)), (1, 1))
        review_prompt = self.reviewer_calls[0]["prompt"]
        self.assertIn(self.plan["markdown"], review_prompt)
        self.assertIn(self.context["source_unresolved"][0], review_prompt)

    def test_missing_reviewer_is_rejected_before_planner_dispatch(self):
        from stage3_plan.direction_research import DirectionResearchAdapter

        planner, reviewer = self.callbacks()
        binding = self.binding()
        with self.assertRaises(Stage3Error):
            DirectionResearchAdapter(planner, None, evidence=binding)
        adapter = DirectionResearchAdapter(planner, reviewer, evidence=binding)
        planner.request_context = adapter.request_context
        prepared = self.prepare_job(planner)
        before = self.journal.snapshot(self.jobs.project_id)
        with self.assertRaisesRegex(Stage3Error, "before dispatch"):
            self.run_job(prepared, planner)
        self.assertEqual(self.journal.snapshot(self.jobs.project_id), before)
        self.assertEqual(
            self.jobs.inspect(
                "original-research-job",
                expected_request_sha256=prepared["request_sha256"],
                current_checkpoint=self.checkpoint,
            )["resume_action"],
            "prepared",
        )
        self.assertEqual(self.planner_calls, [])
        self.assertEqual(self.reviewer_calls, [])

    def test_reviewer_failure_retains_original_plan_and_never_auto_retries(self):
        adapter = self.adapter(
            reviewer_error=RuntimeError("Authored reviewer failure.")
        )
        prepared = self.prepare_job(adapter)
        failed = self.run_job(prepared, adapter)
        self.assertEqual(failed["result"]["outcome"], "failed")
        output = self.saved_root()
        self.assertEqual(read_json(output / "plan.json"), self.plan)
        self.assertEqual(
            (output / "raw-response.json").read_bytes(), canonical_bytes(self.plan)
        )
        self.assertTrue((output / "failure.json").is_file())
        self.assertEqual(self.run_job(prepared, adapter), failed)
        self.assertEqual((len(self.planner_calls), len(self.reviewer_calls)), (1, 1))

    def test_failed_review_raw_bytes_remain_bound_on_replay(self):
        adapter = self.adapter()

        def invalid_review(**request):
            self.reviewer_calls.append(request)
            return {
                "raw_response": b"invalid authored review",
                "provenance": {"kind": "authored-reviewer-offline-stub"},
            }

        invalid_review.request_context = adapter.reviewer.request_context
        adapter.reviewer = invalid_review
        prepared = self.prepare_job(adapter)
        failed = self.run_job(prepared, adapter)
        self.assertEqual(failed["result"]["outcome"], "failed")
        raw = self.saved_root() / "raw-design-review.txt"
        self.assertEqual(raw.read_bytes(), b"invalid authored review")
        self.assertEqual(self.run_job(prepared, adapter), failed)
        raw.write_bytes(b"changed original review")
        with self.assertRaisesRegex(Stage3Error, "failure artifact changed"):
            self.run_job(prepared, adapter)
        self.assertEqual((len(self.planner_calls), len(self.reviewer_calls)), (1, 1))

    def assert_review_planning_status(self, answerability, planning_status):
        self.plan["planning_status"] = "conditional-draft"
        adapter = self.adapter()
        review = self.review()
        for row in review["question_reviews"]:
            row["answerability"] = answerability

        def authored_review(**request):
            self.reviewer_calls.append(request)
            return {
                "raw_response": canonical_bytes(review),
                "provenance": {"kind": "authored-reviewer-offline-stub"},
            }

        authored_review.request_context = adapter.reviewer.request_context
        adapter.reviewer = authored_review
        prepared = self.prepare_job(adapter)
        saved = self.run_job(prepared, adapter)
        self.assertEqual(saved["result"]["outcome"], "saved")
        self.assertEqual(saved["result"]["planning_status"], planning_status)
        output = self.saved_root()
        self.assertEqual(read_json(output / "design-review.json"), review)
        self.assertEqual(
            (output / "raw-design-review.txt").read_bytes(), canonical_bytes(review)
        )
        self.assertEqual(self.run_job(prepared, adapter), saved)
        self.assertEqual((len(self.planner_calls), len(self.reviewer_calls)), (1, 1))

    def test_adequate_review_preserves_draft_status_and_original_raw_review(self):
        self.assert_review_planning_status("adequate", "draft")

    def test_needs_revision_review_keeps_information_pending_and_original_raw_review(
        self,
    ):
        self.assert_review_planning_status("needs-revision", "needs-information")


if __name__ == "__main__":
    unittest.main()
