"""A real sealed advice input with mocked Host authority and an authored callback."""

# ruff: noqa: E402 -- repository fixture imports.

from pathlib import Path
import sys
from threading import RLock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

from research_workspace_native.journal import Journal  # noqa: E402
from research_workspace_native.project_stage3_direction_planning import (
    ProjectStage3DirectionPlanning,
)  # noqa: E402
from research_workspace_native.project_stage3_http import ProjectStage3Http  # noqa: E402
from research_workspace_native.session_api import SessionApiError  # noqa: E402
from stage3_plan.contracts import Stage3Error, canonical_bytes, digest  # noqa: E402
from stage3_plan.jobs import POLICY, PlanningJobs  # noqa: E402
from stage3_plan.native import NativePlanner  # noqa: E402
from stage3_plan.prompts import MAX_CONTEXT_BYTES  # noqa: E402
from stage3_plan.storage import write_new  # noqa: E402
from stage3_direction_fixtures import DirectionFixture  # noqa: E402


class ProjectDirectionPlanningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.direction = DirectionFixture(cls.addClassCleanup)

    def setUp(self):
        self.fixture = self.direction
        self.source = self.fixture.source()
        root = self.fixture.fixture.root / self._testMethodName
        root.mkdir()
        self.journal = Journal(root / "host.sqlite")
        self.addCleanup(self.journal.close)
        self.journal.bind_project("project-direction-id", "a" * 64)
        owner = self.journal.acquire_owner("project-direction-id", "fixture-owner")
        self.project = dict(
            project_id="project-direction-id",
            project_ref="project-direction",
            input_version=1,
            revision=1,
            brief_sha256="b" * 64,
        )
        context = self.fixture.admit(self.source)
        result = {
            "kind": "Stage3DirectionPlanningResult",
            "schema_version": "1.0.0",
            "intent_sha256": self.source["intent_sha256"],
            "planning_status": "needs-information",
            "question_plans": [
                {
                    "question_ref": q["question_ref"],
                    **{
                        k: "A conditional unrun procedure with an explicit evidence boundary."
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
                    "unknowns": ["Resolve material access before collection."],
                }
                for q in context["questions"]
            ],
            "markdown": "Authored test output, not an accepted scientific plan.",
            "execution_authorized": False,
        }
        self.callback = Mock(
            return_value={
                "raw_response": canonical_bytes(result),
                "provenance": {"kind": "offline-authored-output"},
            }
        )
        self.callback.request_context = {
            "kind": "offline-callback",
            "timeout_seconds": 1,
        }
        jobs = PlanningJobs(
            self.journal,
            "project-direction-id",
            owner,
            root / "jobs",
            project_ref="project-direction",
        )
        binding = {
            "input_version": 1,
            "brief_sha256": "b" * 64,
            "workflow_root": "unused-fixture-root",
            "delivery_root": self.source["delivery_dir"],
            "delivery_manifest_sha256": self.source["delivery_manifest_sha256"],
        }

        def current(credential, ref, **kwargs):
            if credential != "own" or ref != "project-direction":
                raise SessionApiError("fixture-authority-rejected", 403)
            return self.project, binding, None, None, None

        parent = SimpleNamespace(
            intake=SimpleNamespace(_lock=RLock()),
            _current=current,
            selection_view=SimpleNamespace(bindings={"project-direction": binding}),
            bindings={
                "project-direction": {
                    "jobs": jobs,
                    "callback": self.callback,
                    "configuration": {"model": "stub", "reasoning": "medium"},
                }
            },
        )
        self.service = ProjectStage3DirectionPlanning(parent)
        self.service.selection.read = Mock(
            return_value={
                "direction_intent": {"intent_sha256": self.source["intent_sha256"]}
            }
        )
        self.service.selection.direction_intent_context = Mock(
            return_value={
                **self.source,
                "advisory_dir": Path(self.source["advisory_dir"]),
                "delivery_dir": Path(self.source["delivery_dir"]),
            }
        )
        self.body = {
            k: self.project[k] for k in ("revision", "input_version", "brief_sha256")
        }
        self.body.update(
            key="stage3-direction-" + self.source["intent_sha256"],
            mode="direction-intent",
            direction_intent_sha256=self.source["intent_sha256"],
        )
        self.addCleanup(patch.stopall)
        self.native_forbidden = patch(
            "stage3_plan.native.NativePlanner.__call__",
            side_effect=AssertionError("native forbidden"),
        )
        self.native_forbidden.start()

    def test_replacing_intent_uses_distinct_native_capture_and_keeps_old_attempt(self):
        parent = self.service.planning
        root = self.fixture.fixture.root / self._testMethodName
        original = NativePlanner(
            codex=sys.executable,
            codex_home=root,
            capture_dir=root / "native-capture",
            timeout_seconds=1,
        )
        parent.bindings["project-direction"]["callback"] = original
        selection = self.service.selection
        service = ProjectStage3DirectionPlanning(parent)
        service.selection = selection
        first = service._current("own", "project-direction")[3]["callback"]
        same = service._current("own", "project-direction")[3]["callback"]
        self.assertEqual(first.request_context, same.request_context)
        source = self.fixture.source(
            dict(self.fixture.intent, user_input="Authored second preference.")
        )
        selection.read.return_value = {
            "direction_intent": {"intent_sha256": source["intent_sha256"]}
        }
        selection.direction_intent_context.return_value = source
        second = service._current("own", "project-direction")[3]["callback"]
        self.assertNotEqual(first.capture, second.capture)
        namespace = original.capture.with_name(original.capture.name + "-direction")
        self.assertEqual(first.capture.parent, namespace)
        self.assertEqual(second.capture.parent, namespace)
        first.capture.mkdir(parents=True)
        marker = first.capture / "authored-attempt.txt"
        marker.write_bytes(b"Preserve this authored prior attempt.")
        self.native_forbidden.stop()
        with patch("stage1_eval.model_calls.call_model_v31") as primitive:
            with self.assertRaisesRegex(Stage3Error, "capture already attempted"):
                first(
                    prompt="Authored guard test.",
                    schema_path=PLUGIN / "schemas/stage3-direction-plan.v1.schema.json",
                    output_dir=root / "unused-plan",
                    configuration={"model": "stub", "reasoning": "medium"},
                )
            primitive.assert_not_called()
        self.assertEqual(marker.read_bytes(), b"Preserve this authored prior attempt.")

    def test_current_preference_prepare_run_and_read_result_use_original_job(self):
        before = self.service.read(
            "own", "project-direction", {"selection_status": "pending", **POLICY}
        )
        self.assertFalse(before["agent_conversation_connected"])
        self.assertEqual(before["planning_target"], "stage3-planning-job")
        prepared = self.service.prepare("own", "project-direction", self.body)
        self.callback.assert_not_called()
        body = dict(self.body, request_sha256=prepared["request_sha256"])
        saved = self.service.run("own", "project-direction", dict(body, confirmed=True))
        self.assertEqual(saved["outcome"], "saved")
        replay = self.service.run(
            "own", "project-direction", dict(body, confirmed=True)
        )
        self.assertEqual(replay, saved)
        self.assertEqual(self.callback.call_count, 1)
        jobs = self.service.bindings["project-direction"]["jobs"]
        with patch.object(jobs, "inspect", wraps=jobs.inspect) as inspected:
            view = self.service.read(
                "own", "project-direction", {"selection_status": "pending", **POLICY}
            )
            self.assertEqual(inspected.call_count, 1)
        self.assertEqual(self.callback.call_count, 1)
        self.assertEqual(view["selection_status"], "pending")
        self.assertEqual(view["plan"]["kind"], "Stage3DirectionPlanningResult")
        self.assertFalse(view["formal_selected_receiver"])

    def test_http_view_and_admission_retain_conditional_pins_without_dispatch(self):
        facade = SimpleNamespace(
            read=lambda credential, ref, **kwargs: self.service.read(
                credential, ref, {"selection_status": "pending", **POLICY}, **kwargs
            ),
            inspect=self.service.inspect,
        )
        http = ProjectStage3Http(facade)
        self.addCleanup(http.close)
        view = http.view("own", "project-direction")
        self.assertEqual(view["default_request"], self.body)
        self.assertEqual(view["direction_intent_sha256"], self.source["intent_sha256"])
        with self.assertRaises(TimeoutError):
            http.view(
                "own",
                "project-direction",
                check_deadline=Mock(side_effect=TimeoutError),
            )
        prepared = self.service.prepare("own", "project-direction", self.body)
        body = dict(
            self.body, request_sha256=prepared["request_sha256"], confirmed=True
        )
        for invalid in (dict(body, confirmed=False), dict(body, target_thread="other")):
            with self.assertRaises(SessionApiError):
                http.admit_run("own", "project-direction", invalid, None)
        self.assertTrue(http.admit_run("own", "project-direction", body, None)[0])
        self.assertFalse(http.admit_run("own", "project-direction", body, None)[0])
        self.callback.assert_not_called()
        self.service.run("own", "project-direction", body)
        http.finish("project-direction")
        saved = http.view("own", "project-direction")
        self.assertEqual(saved["job"]["outcome"], "saved")
        self.assertEqual(saved["plan"]["intent_sha256"], self.source["intent_sha256"])
        self.assertEqual(self.callback.call_count, 1)

    def test_changed_host_configuration_rejects_reuse_and_run_without_dispatch(self):
        prepared = self.service.prepare("own", "project-direction", self.body)
        body = dict(self.body, request_sha256=prepared["request_sha256"])
        configuration = self.service.bindings["project-direction"]["configuration"]
        for field in ("model", "reasoning"):
            previous = configuration[field]
            configuration[field] = "changed-" + previous
            for action in (
                lambda: self.service.prepare("own", "project-direction", self.body),
                lambda: self.service.inspect("own", "project-direction", body),
                lambda: self.service.run(
                    "own", "project-direction", dict(body, confirmed=True)
                ),
            ):
                with self.subTest(field=field), self.assertRaises(SessionApiError):
                    action()
            configuration[field] = previous
        self.callback.assert_not_called()

    def test_http_uncertain_view_offers_only_matching_trusted_recovery(self):
        prepared = self.service.prepare("own", "project-direction", self.body)
        view = self.service.read(
            "own", "project-direction", {"selection_status": "pending", **POLICY}
        )
        view["job"] = dict(
            view["job"], status="execution-unknown", outcome="execution-unknown"
        )
        facade = SimpleNamespace(read=Mock(return_value=view))
        identity = ("project-direction", self.body["key"], prepared["request_sha256"])
        trusted = ProjectStage3Http(facade, recovery_pins={identity: "f" * 64})
        untrusted = ProjectStage3Http(facade)
        self.addCleanup(trusted.close)
        self.addCleanup(untrusted.close)
        self.assertIs(
            trusted.view("own", "project-direction")["recovery_pin_available"], True
        )
        self.assertIs(
            untrusted.view("own", "project-direction")["recovery_pin_available"], False
        )
        self.callback.assert_not_called()

    def test_foreign_or_stale_request_does_not_prepare_or_call(self):
        for body in (
            dict(self.body, revision=0),
            dict(self.body, input_version="1"),
            dict(self.body, key="different-key"),
            dict(self.body, direction_intent_sha256="0" * 64),
        ):
            with self.subTest(body=body), self.assertRaises(SessionApiError):
                self.service.prepare("own", "project-direction", body)
        with self.assertRaises(SessionApiError):
            self.service.prepare("foreign", "project-direction", self.body)
        self.callback.assert_not_called()

    def test_extra_target_or_missing_confirmation_cannot_start(self):
        prepared = self.service.prepare("own", "project-direction", self.body)
        body = dict(
            self.body, request_sha256=prepared["request_sha256"], confirmed=True
        )
        with self.assertRaises(SessionApiError):
            self.service.run(
                "own", "project-direction", dict(body, target_thread="arbitrary")
            )
        with self.assertRaises(SessionApiError):
            self.service.run("own", "project-direction", dict(body, confirmed=False))
        self.callback.assert_not_called()

    def test_oversize_intent_is_visible_before_any_job_artifact(self):
        changed = dict(self.fixture.intent, user_input="x" * MAX_CONTEXT_BYTES)
        self.source = self.fixture.source(changed)
        self.service.selection.read.return_value = {
            "direction_intent": {"intent_sha256": self.source["intent_sha256"]}
        }
        self.service.selection.direction_intent_context.return_value = self.source
        self.body.update(
            key="stage3-direction-" + self.source["intent_sha256"],
            direction_intent_sha256=self.source["intent_sha256"],
        )
        view = self.service.read(
            "own", "project-direction", {"selection_status": "pending", **POLICY}
        )
        self.assertEqual(view["planning_status"], "needs-information")
        self.assertTrue(view["planning_blockers"])
        self.assertIsNone(view["default_request"])
        with self.assertRaises(SessionApiError):
            self.service.prepare("own", "project-direction", self.body)
        self.assertFalse(
            self.service.bindings["project-direction"]["jobs"].root.exists()
        )
        self.callback.assert_not_called()

    def test_complete_input_before_job_intent_reuses_only_matching_bytes(self):
        source = self.service._current("own", "project-direction", self.body)[1]
        jobs = self.service.bindings["project-direction"]["jobs"]
        jobs.root.mkdir()
        path = jobs.root / (
            "host-direction-"
            + digest(["project-direction", self.body["key"]])
            + ".json"
        )
        write_new(path, {"unrelated": "preserve original mismatch"})
        before = path.read_bytes()
        with self.assertRaises(SessionApiError):
            self.service.prepare("own", "project-direction", self.body)
        self.assertEqual(path.read_bytes(), before)
        path.unlink()
        write_new(path, {"kind": "Stage3DirectionPlanningJobInput", "source": source})
        before = path.read_bytes()
        self.service.prepare("own", "project-direction", self.body)
        self.assertEqual(path.read_bytes(), before)
        self.callback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
