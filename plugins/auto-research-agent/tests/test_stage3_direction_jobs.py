"""Deterministic direction job replay and question closure; callbacks are authored."""

# ruff: noqa: E402 -- repository fixture imports.

from copy import deepcopy
from pathlib import Path
import sys
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

from research_workspace_native.journal import Journal
from stage3_direction_fixtures import DirectionFixture
from stage3_plan.contracts import Stage3Error, canonical_bytes
from stage3_plan.direction_jobs import DirectionPlanningJobs, validate_direction_result
from stage3_plan.jobs import _ref
from stage3_plan.storage import MAX_ARTIFACT_BYTES, write_new


def authored_result(context):
    return {
        "kind": "Stage3DirectionPlanningResult",
        "schema_version": "1.0.0",
        "intent_sha256": context["intent_sha256"],
        "planning_status": "needs-information",
        "question_plans": [
            {
                "question_ref": q["question_ref"],
                **{
                    k: "An authored unrun procedure requiring material verification."
                    for k in (
                        "materials",
                        "method",
                        "design",
                        "validation",
                        "analysis",
                        "interpretation",
                        "minimum_deliverable",
                    )
                },
                "unknowns": ["Resolve access before collecting evidence."],
            }
            for q in context["questions"]
        ],
        "markdown": "Authored engineering output; no scientific result.",
        "execution_authorized": False,
    }


class Stage3DirectionJobsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.direction = DirectionFixture(cls.addClassCleanup)

    def setUp(self):
        root = self.direction.fixture.root / self._testMethodName
        root.mkdir()
        self.journal = Journal(root / "journal.sqlite")
        self.addCleanup(self.journal.close)
        self.journal.bind_project("project-direction-id", "a" * 64)
        owner = self.journal.acquire_owner("project-direction-id", "test-owner")
        self.jobs = DirectionPlanningJobs(
            self.journal,
            "project-direction-id",
            owner,
            root / "jobs",
            project_ref="project-direction",
        )
        path = root / "input.json"
        write_new(
            path,
            {
                "kind": "Stage3DirectionPlanningJobInput",
                "source": self.direction.source(),
            },
        )
        self.checkpoint = _ref(path)
        self.context = self.direction.admit(self.direction.source())
        self.calls = []

    def callback(self, raw=None, *, context=None):
        def capture(**request):
            self.calls.append(request)
            return {
                "raw_response": canonical_bytes(
                    authored_result(self.context if context is None else context)
                )
                if raw is None
                else raw,
                "provenance": {"kind": "authored-offline-stub"},
            }

        capture.request_context = {"kind": "offline-stub", "timeout_seconds": 1}
        return capture

    def prepare(self, key, callback):
        return self.jobs.prepare(
            key,
            checkpoint=self.checkpoint,
            configuration={"model": "stub", "reasoning": "medium"},
            adapter_context=callback.request_context,
            plan_id="conditional-test",
            expected_revision=self.journal.snapshot(self.jobs.project_id)["revision"],
        )

    def run_job(self, key, prepared, callback):
        return self.jobs.run(
            key,
            expected_request_sha256=prepared["request_sha256"],
            current_checkpoint=self.checkpoint,
            callback=callback,
        )

    def test_conditional_job_reuses_journal_and_dispatches_once(self):
        callback = self.callback()
        prepared = self.prepare("original-plan-key", callback)
        self.assertEqual(self.calls, [])
        result = self.run_job("original-plan-key", prepared, callback)
        self.assertEqual(result["result"]["outcome"], "saved")
        self.assertIs(result["result"]["formal_selected_receiver"], False)
        self.assertEqual(self.run_job("original-plan-key", prepared, callback), result)
        self.assertEqual(len(self.calls), 1)
        self.assertIs(result["policy"]["execution_authorized"], False)

    def test_invalid_response_is_retained_and_replay_never_retries(self):
        raw = b'{"invalid":"Keep this original failure."}'
        callback = self.callback(raw)
        prepared = self.prepare("invalid-result", callback)
        result = self.run_job("invalid-result", prepared, callback)
        self.assertEqual(result["result"]["outcome"], "failed")
        output = self.journal.snapshot(self.jobs.project_id)["intents"][
            self.jobs._key("invalid-result")
        ]["payload"]["output"]
        saved = Path(output) / "plan"
        self.assertEqual((saved / "raw-response.json").read_bytes(), raw)
        self.assertTrue((saved / "failure.json").is_file())
        self.assertEqual(self.run_job("invalid-result", prepared, callback), result)
        self.assertEqual(len(self.calls), 1)

    def test_three_question_result_requires_exact_source_closure(self):
        context = deepcopy(self.context)
        context["questions"] = [
            dict(
                context["questions"][0], question_ref="synthetic-direction@1/q" + str(i)
            )
            for i in range(3)
        ]
        result = authored_result(context)
        validate_direction_result(result, context)
        variants = []
        for rows in (
            result["question_plans"][:-1],
            result["question_plans"] + result["question_plans"][:1],
        ):
            variants.append(dict(result, question_plans=rows))
        foreign = deepcopy(result)
        foreign["question_plans"][0]["question_ref"] = "foreign-direction@1/q0"
        variants.extend(
            [
                foreign,
                dict(result, execution_authorized=True),
                dict(result, intent_sha256="0" * 64),
            ]
        )
        for value in variants:
            with self.subTest(value=value), self.assertRaises(Stage3Error):
                validate_direction_result(value, context)

    def test_invalid_adapter_preflight_records_no_intent_or_dispatch(self):
        bad = [
            None,
            {},
            {"timeout_seconds": False},
            {"timeout_seconds": 0},
            {"timeout_seconds": -1},
            {"timeout_seconds": float("inf")},
            {"timeout_seconds": float("nan")},
            {"timeout_seconds": 1, "oversized": "x" * MAX_ARTIFACT_BYTES},
        ]
        before = self.journal.snapshot(self.jobs.project_id)
        for i, adapter in enumerate(bad):
            with self.subTest(case=i), self.assertRaises(Stage3Error):
                self.jobs.prepare(
                    "invalid-preflight",
                    checkpoint=self.checkpoint,
                    configuration={"model": "stub", "reasoning": "medium"},
                    adapter_context=adapter,
                    plan_id="conditional-test",
                    expected_revision=before["revision"],
                )
            after = self.journal.snapshot(self.jobs.project_id)
            self.assertEqual(after["revision"], before["revision"])
            self.assertEqual(list(after["intents"]), list(before["intents"]))
        self.assertFalse(self.jobs.root.exists())
        self.assertEqual(self.calls, [])

    def test_two_projects_with_the_same_root_and_key_have_separate_outputs(self):
        self.journal.bind_project("other-project-id", "f" * 64)
        owner = self.journal.acquire_owner("other-project-id", "other-owner")
        other = DirectionPlanningJobs(
            self.journal,
            "other-project-id",
            owner,
            self.jobs.root,
            project_ref="other-project",
        )
        intent = dict(
            self.direction.intent,
            project_ref="other-project",
            project_id="other-project-id",
        )
        source = self.direction.source(intent)
        path = self.checkpoint["path"] + ".other.json"
        write_new(path, {"kind": "Stage3DirectionPlanningJobInput", "source": source})
        checkpoint = _ref(path)
        context = self.direction.admit(source)
        callback = self.callback(context=context)
        first_callback = self.callback()
        first = self.prepare("shared-key", first_callback)
        second = other.prepare(
            "shared-key",
            checkpoint=checkpoint,
            configuration={"model": "stub", "reasoning": "medium"},
            adapter_context=callback.request_context,
            plan_id="conditional-test",
            expected_revision=self.journal.snapshot(other.project_id)["revision"],
        )
        paths = [
            self.journal.snapshot(j.project_id)["intents"][j._key("shared-key")][
                "payload"
            ]["output"]
            for j in (self.jobs, other)
        ]
        self.assertNotEqual(*paths)
        self.assertEqual(
            self.run_job("shared-key", first, first_callback)["result"]["outcome"],
            "saved",
        )
        result = other.run(
            "shared-key",
            expected_request_sha256=second["request_sha256"],
            current_checkpoint=checkpoint,
            callback=callback,
        )
        self.assertEqual(result["result"]["outcome"], "saved")
        self.assertEqual(len(self.calls), 2)


if __name__ == "__main__":
    unittest.main()
