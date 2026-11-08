"""Authored complete-study jobs and original Host forwarding; no native calls."""

# ruff: noqa: E402
from copy import deepcopy
from pathlib import Path
import sys
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]
from stage3_plan.contracts import Stage3Error, canonical_bytes, digest
from stage3_plan.context_projection import expand_context
from stage3_plan.storage import decode_json
from stage3_plan.direction_research import (
    DirectionResearchAdapter,
    prepare_direction_evidence,
    research_context,
)
from stage3_plan.direction_study_route import PROFILE, project_study_route
from stage3_plan.storage import read_json
from stage3_direction_fixtures import DirectionFixture
from test_stage3_direction_research import _DirectionResearchFixture
from test_stage3_study_route import structured_result
import test_stage3_direction_research_jobs as job_fixture
import test_project_stage3_direction_planning as host_fixture


class _StudySetup:
    def setup_study(self, context, root):
        self.study_calls = []
        self.study_reviews = []
        raw = structured_result()
        raw["intent_sha256"] = context["intent_sha256"]
        template = deepcopy(raw["question_plans"][0])
        raw["question_plans"] = [
            dict(deepcopy(template), question_ref=q["question_ref"])
            for q in context["questions"]
        ]
        self.study_raw = raw
        self.study_plan = project_study_route(raw)

        def planner(**request):
            self.study_calls.append(request)
            return {
                "raw_response": canonical_bytes(raw),
                "provenance": {"kind": "authored-study-planner"},
            }

        def reviewer(**request):
            self.study_reviews.append(request)
            if getattr(self, "review_hook", None):
                self.review_hook()
            value = {
                "kind": "Stage3DirectionDesignReview",
                "intent_sha256": context["intent_sha256"],
                "plan_sha256": digest(self.study_plan),
                "question_reviews": [
                    {
                        "question_ref": q["question_ref"],
                        "answerability": "unknown",
                        "reason": "Keep the original source limit.",
                        "supported_scope": "Only a proposed study.",
                        "revision": "Resolve the stated access condition.",
                    }
                    for q in context["questions"]
                ],
            }
            return {
                "raw_response": canonical_bytes(value),
                "provenance": {"kind": "authored-study-reviewer"},
            }

        planner.request_context = {"kind": "authored-study-plan", "timeout_seconds": 1}
        reviewer.request_context = {
            "kind": "authored-independent-study-review",
            "timeout_seconds": 1,
        }
        evidence = prepare_direction_evidence(
            context,
            [
                {
                    "id": "material-access",
                    "question_ref": context["questions"][0]["question_ref"],
                    "requirement": "Verify lawful access.",
                    "design_decision": "Retain an unknown until checked.",
                }
            ],
            root / "study-evidence.json",
        )
        self.study_adapter = DirectionResearchAdapter(
            planner, reviewer, evidence=evidence, prompt_profile=PROFILE
        )


class Stage3StudyJobsTests(_DirectionResearchFixture, _StudySetup):
    prepare_job = job_fixture.Stage3DirectionResearchJobsTests.prepare_job
    run_job = job_fixture.Stage3DirectionResearchJobsTests.run_job
    saved_root = job_fixture.Stage3DirectionResearchJobsTests.saved_root

    def test_structured_raw_public_projection_and_review_replay_are_bound(self):
        self.setup_study(self.context, self.root)
        prepared = self.prepare_job(self.study_adapter)
        saved = self.run_job(prepared, self.study_adapter)
        self.assertEqual(saved["result"]["outcome"], "saved")
        root = self.saved_root()
        self.assertEqual(read_json(root / "raw-response.json"), self.study_raw)
        self.assertEqual(read_json(root / "plan.json"), self.study_plan)
        self.assertEqual(
            self.study_calls[0]["schema_path"].name,
            "stage3-structured-direction-plan.v1.schema.json",
        )
        review_input = decode_json(
            self.study_reviews[0]["prompt"].split("UNTRUSTED_RESEARCH_DESIGN\n", 1)[1]
        )
        if review_input.get("kind") == "Stage3SharedPlanningContext":
            review_input = expand_context(review_input)
        self.assertEqual(review_input["delivered_plan"], self.study_plan)
        self.assertEqual(self.run_job(prepared, self.study_adapter), saved)
        reread = self.jobs.inspect_saved(
            "original-research-job",
            expected_request_sha256=prepared["request_sha256"],
            current_checkpoint=self.checkpoint,
            expected_plan_manifest_sha256=saved["result"]["plan"]["manifest_sha256"],
        )
        self.assertEqual(reread["result"], saved["result"])
        self.assertEqual((len(self.study_calls), len(self.study_reviews)), (1, 1))

    def test_non_mapping_research_context_rejects_before_dispatch(self):
        for value in ("bad", [], 7):
            with self.subTest(value=value), self.assertRaises(Stage3Error):
                research_context({}, {"direction_research": value})

    def test_wrong_structured_schema_binding_rejects_before_callbacks(self):
        self.setup_study(self.context, self.root)
        changed = deepcopy(self.study_adapter.request_context)
        changed["direction_research"]["plan_schema_sha256"] = "a" * 64
        with self.assertRaisesRegex(Stage3Error, "schema differs"):
            research_context(self.context, changed)
        self.assertEqual((self.study_calls, self.study_reviews), ([], []))


class ProjectStudyForwardingTests(unittest.TestCase, _StudySetup):
    @classmethod
    def setUpClass(cls):
        cls.direction = DirectionFixture(cls.addClassCleanup)

    def setUp(self):
        host_fixture.ProjectDirectionPlanningTests.setUp(self)
        context = self.direction.admit(self.source)
        root = self.fixture.fixture.root / self._testMethodName
        self.setup_study(context, root)
        configured = self.service.bindings[self.project["project_ref"]]
        configured.update(
            callback=self.study_adapter,
            adapter_context=deepcopy(self.study_adapter.request_context),
        )

    def test_original_host_prepare_run_read_forwards_independent_review_once(self):
        ref = self.project["project_ref"]
        prepared = self.service.prepare("own", ref, self.body)
        body = dict(
            self.body, request_sha256=prepared["request_sha256"], confirmed=True
        )
        saved = self.service.run("own", ref, body)
        self.assertEqual(saved["outcome"], "saved")
        self.assertEqual(self.service.run("own", ref, body), saved)
        view = self.service.read("own", ref, self.project)
        self.assertEqual(view["plan"], self.study_plan)
        self.assertFalse(view["formal_selected_receiver"])
        self.assertFalse(view["plan"]["execution_authorized"])
        self.assertEqual((len(self.study_calls), len(self.study_reviews)), (1, 1))

    def test_review_time_source_drift_prevents_publication_without_retry(self):
        ref = self.project["project_ref"]
        prepared = self.service.prepare("own", ref, self.body)
        body = dict(
            self.body, request_sha256=prepared["request_sha256"], confirmed=True
        )
        self.review_hook = lambda: self.project.update(
            revision=self.project["revision"] + 1
        )
        result = self.service.run("own", ref, body)
        # A completed planner plus a rejected review is a known failed package.
        self.assertEqual((result["status"], result["outcome"]), ("completed", "failed"))
        jobs = self.service.bindings[ref]["jobs"]
        item = self.journal.snapshot(self.project["project_id"])["intents"][
            jobs._key(body["key"])
        ]
        root = Path(item["payload"]["output"])
        failure = read_json(root / "job-failure.json")
        self.assertEqual(failure["message"], "stage3-direction-project-version-differs")
        self.assertEqual(read_json(root / "plan/plan.json"), self.study_plan)
        self.assertEqual(read_json(root / "plan/manifest.json")["state"], "failed")
        self.assertFalse((root / "plan/design-review.json").exists())
        self.assertFalse(result["execution_authorized"])
        self.assertEqual((len(self.study_calls), len(self.study_reviews)), (1, 1))


if __name__ == "__main__":
    unittest.main()
