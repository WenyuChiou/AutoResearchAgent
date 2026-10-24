"""Offline Stage3 job tests; admission mocks do not authenticate a real choice."""

import copy
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]
from research_workspace_native.journal import Journal, JournalError  # noqa: E402
from stage3_plan.contracts import Stage3Error, canonical_bytes  # noqa: E402
from stage3_plan.jobs import PlanningJobs  # noqa: E402
from stage3_plan.storage import read_json  # noqa: E402
from stage3_plan.workflow import start_workflow  # noqa: E402
from stage3_plan_fixtures import make_intake, make_plan  # noqa: E402


class PlanningJobTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.journal = Journal(self.root / "host.sqlite3")
        self.addCleanup(self.journal.close)
        self.journal.bind_project("project-a", "a" * 64)
        self.owner = self.journal.acquire_owner("project-a", "offline-test")
        self.jobs = PlanningJobs(
            self.journal, "project-a", self.owner, self.root / "jobs"
        )
        self.plan = make_plan("theory", question_count=3, shared_path=True)
        self.intake = make_intake(self.plan)
        self.intake["selection_conditions"] = ["Keep the original limitation."]
        self.intake["brief"] = {"project_id": "original-brief"}
        for target in (
            "jobs.admit_intake",
            "workflow.admit_intake",
            "intake.admit_intake",
        ):
            mock = patch(
                "stage3_plan." + target,
                side_effect=lambda *a, **k: copy.deepcopy(self.intake),
            )
            mock.start()
            self.addCleanup(mock.stop)
        native = patch(
            "stage3_plan.native.NativePlanner.__call__",
            side_effect=AssertionError("native dispatch forbidden"),
        )
        self.native_guard = native.start()
        self.addCleanup(native.stop)
        process = patch(
            "subprocess.Popen", side_effect=AssertionError("process dispatch forbidden")
        )
        self.process_guard = process.start()
        self.addCleanup(process.stop)
        self.context = {"kind": "synthetic-job", "timeout_seconds": 5}
        self.config = {"model": "fixture-model", "reasoning": "medium"}
        self.checkpoint = self.workflow("initial")
        self.callback = Mock(
            side_effect=lambda **kw: {
                "raw_response": canonical_bytes(self.plan),
                "provenance": {"kind": "synthetic"},
            }
        )
        self.callback.request_context = self.context

    def tearDown(self):
        self.native_guard.assert_not_called()
        self.process_guard.assert_not_called()

    def workflow(self, name):
        path = self.root / (name + ".json")
        value = start_workflow(
            self.root / "source",
            self.root / "delivery",
            expected_source_manifest_sha256=self.plan["source_manifest_sha256"],
            output=path,
            workflow_id="workflow-" + name,
        )
        return {"path": str(path), "sha256": value["checkpoint_sha256"]}

    def prepare(self, key="one", **changes):
        kwargs = dict(
            checkpoint=self.checkpoint,
            configuration=self.config,
            adapter_context=self.context,
            plan_id=self.plan["plan_id"],
            expected_revision=self.journal.snapshot("project-a")["revision"],
        )
        kwargs.update(changes)
        return self.jobs.prepare(key, **kwargs)

    def execute(self, result, key="one"):
        return self.jobs.run(
            key,
            expected_request_sha256=result["request_sha256"],
            current_checkpoint=self.checkpoint,
            callback=self.callback,
        )

    def test_prepare_once_save_replay_and_inspect_have_no_new_calls(self):
        prepared = self.prepare()
        self.assertEqual(prepared["status"], "intent-recorded")
        prepared["policy"]["execution_authorized"] = True
        self.assertIs(self.prepare()["policy"]["execution_authorized"], False)
        self.callback.assert_not_called()

        saved = self.execute(prepared)
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(saved["result"]["outcome"], "saved")
        self.assertEqual(saved["result"]["planning_status"], "draft")
        self.assertTrue(all(v is False for v in saved["policy"].values()))
        revision = self.journal.snapshot("project-a")["revision"]
        self.assertEqual(self.execute(prepared), saved)
        self.assertEqual(self.prepare(), saved)
        self.assertEqual(self.journal.snapshot("project-a")["revision"], revision)
        self.assertEqual(self.callback.call_count, 1)
        revision = self.journal.snapshot("project-a")["revision"]
        self.assertEqual(
            self.jobs.inspect(
                "one",
                expected_request_sha256=prepared["request_sha256"],
                current_checkpoint=self.checkpoint,
            ),
            saved,
        )
        self.assertEqual(self.journal.snapshot("project-a")["revision"], revision)

    def test_generic_types_all_questions_and_reviewer_tasks_reach_existing_prompt(self):
        for topic in ("numeric", "observational", "qualitative", "theory"):
            with self.subTest(topic=topic):
                self.plan = make_plan(topic, question_count=3, shared_path=True)
                self.intake = make_intake(self.plan)
                self.intake["selection_conditions"] = ["Original human condition."]
                self.intake["reviewer_planning_context"] = {
                    "kind": "Stage2ReviewerPlanningContext",
                    "schema_version": "1.0.0",
                    "source_kind": "stage2-independent-review",
                    "review_view_version": "1.3.0",
                    "next_step": "Reviewer-only design task, not permission.",
                }
                self.checkpoint = self.workflow(topic)
                prepared = self.prepare(topic)
                saved = self.execute(prepared, topic)
                self.assertEqual(saved["result"]["outcome"], "saved")
                prompt = self.callback.call_args.kwargs["prompt"]
                for question in self.plan["questions"]:
                    self.assertIn(question["text"], prompt)
                self.assertIn("Reviewer-only design task", prompt)
                self.assertEqual(
                    self.intake["selection_conditions"], ["Original human condition."]
                )
        self.assertEqual(self.callback.call_count, 4)

    def test_changed_configuration_request_checkpoint_and_runtime_reject(self):
        prepared = self.prepare()
        with self.assertRaises(JournalError):
            self.prepare(configuration={"model": "changed", "reasoning": "medium"})
        with self.assertRaises(Stage3Error):
            self.jobs.run(
                "one",
                expected_request_sha256="0" * 64,
                current_checkpoint=self.checkpoint,
                callback=self.callback,
            )
        other = self.workflow("other")
        with self.assertRaises(Stage3Error):
            self.jobs.run(
                "one",
                expected_request_sha256=prepared["request_sha256"],
                current_checkpoint=other,
                callback=self.callback,
            )
        with patch("stage3_plan.jobs._runtime", return_value={"changed": True}):
            with self.assertRaises(Stage3Error):
                self.execute(prepared)
        self.callback.assert_not_called()

    def test_wrong_project_and_adapter_and_missing_choice_do_not_dispatch(self):
        self.intake["input_origin"] = {"project_ref": "another-project"}
        self.checkpoint = self.workflow("wrong-project")
        with self.assertRaises(Stage3Error):
            self.prepare()
        self.intake.pop("input_origin")
        self.checkpoint = self.workflow("correct-project")
        prepared = self.prepare()
        self.callback.request_context = {"kind": "changed", "timeout_seconds": 5}
        with self.assertRaises(Stage3Error):
            self.execute(prepared)
        with patch(
            "stage3_plan.workflow.admit_intake",
            side_effect=Stage3Error("no current human choice"),
        ):
            with self.assertRaises(Stage3Error):
                self.jobs.inspect(
                    "one",
                    expected_request_sha256=prepared["request_sha256"],
                    current_checkpoint=self.checkpoint,
                )
        self.callback.assert_not_called()

        self.intake["legacy_candidates"] = [{"reason": "unmapped fixture"}]
        self.checkpoint = self.workflow("unmapped")
        with self.assertRaisesRegex(Stage3Error, "existing Stage2 mapping"):
            self.prepare("unmapped")

    def failure(self, error, status):
        self.callback.side_effect = error
        prepared = self.prepare()
        self.last_prepared = prepared
        failed = self.execute(prepared)
        self.assertEqual(failed["status"], status)
        ref = failed["result"]["failure"]
        failure = read_json(ref["path"])
        self.assertEqual(failure["error_class"], type(error).__name__)
        self.assertEqual(self.execute(prepared), failed)
        self.assertEqual(self.callback.call_count, 1)

        return failure

    def test_timeout_keeps_exact_streams_unknown_outcome_and_never_retries(self):
        value = self.failure(
            subprocess.TimeoutExpired(
                "fixture", 5, output=b"partial out", stderr=b"timeout err"
            ),
            "execution-unknown",
        )
        self.assertEqual(Path(value["stdout"]["path"]).read_bytes(), b"partial out")
        self.assertEqual(Path(value["stderr"]["path"]).read_bytes(), b"timeout err")
        self.assertIsNone(value["returncode"])
        Path(value["stderr"]["path"]).write_bytes(b"changed failure stream")
        with self.assertRaises(Stage3Error):
            self.jobs.inspect(
                "one",
                expected_request_sha256=self.last_prepared["request_sha256"],
                current_checkpoint=self.checkpoint,
            )

    def test_429_and_cancellation_keep_original_error_without_live_retry(self):
        self.failure(
            RuntimeError("429 injected; no provider call"), "execution-unknown"
        )

    def test_keyboard_cancellation_is_retained_without_global_kill(self):
        self.failure(KeyboardInterrupt("injected cancellation"), "execution-unknown")

    def test_nonzero_exit_is_failed_and_keeps_actual_code_and_streams(self):
        value = self.failure(
            subprocess.CalledProcessError(
                7, "fixture", output=b"stdout", stderr=b"stderr"
            ),
            "completed",
        )
        self.assertEqual(value["returncode"], 7)

    def test_invalid_raw_is_retained_and_failed_is_not_successful(self):
        self.callback.side_effect = lambda **kw: {
            "raw_response": b"{bad",
            "provenance": {"kind": "synthetic"},
        }
        prepared = self.prepare()
        failed = self.execute(prepared)
        self.assertEqual(failed["status"], "completed")
        self.assertEqual(failed["result"]["outcome"], "failed")
        payload = self.journal.snapshot("project-a")["intents"][self.jobs._key("one")][
            "payload"
        ]
        self.assertEqual(
            (Path(payload["output"]) / "plan/raw-response.json").read_bytes(), b"{bad"
        )
        self.assertEqual(self.execute(prepared), failed)
        self.assertEqual(self.callback.call_count, 1)

        (Path(payload["output"]) / "plan/raw-response.json").write_bytes(b"changed")
        with self.assertRaisesRegex(Stage3Error, "failure artifact changed"):
            self.execute(prepared)

    def test_interrupted_after_saved_output_recovers_without_another_callback(self):
        prepared = self.prepare()
        transition = self.jobs._transition

        def cut(key, status, evidence):
            if status == "completed":
                raise OSError("injected final journal persistence failure")
            return transition(key, status, evidence)

        with patch.object(self.jobs, "_transition", side_effect=cut):
            with self.assertRaises(OSError):
                self.execute(prepared)
        self.assertEqual(self.execute(prepared)["status"], "dispatching")
        payload = self.journal.snapshot("project-a")["intents"][self.jobs._key("one")][
            "payload"
        ]
        pin = read_json(Path(payload["output"]) / "plan/manifest.json")[
            "manifest_sha256"
        ]
        recovered = self.jobs.recover(
            "one",
            expected_request_sha256=prepared["request_sha256"],
            current_checkpoint=self.checkpoint,
            expected_plan_manifest_sha256=pin,
        )
        self.assertEqual(recovered["result"]["outcome"], "saved")
        self.assertEqual(self.callback.call_count, 1)

    def test_partial_attempt_and_output_io_failure_never_trigger_new_work(self):
        prepared = self.prepare()
        payload = self.journal.snapshot("project-a")["intents"][self.jobs._key("one")][
            "payload"
        ]
        output = Path(payload["output"])
        output.parent.mkdir(parents=True)
        output.write_bytes(b"not a directory")
        with self.assertRaises(OSError):
            self.execute(prepared)
        self.assertEqual(self.execute(prepared)["status"], "dispatching")
        self.callback.assert_not_called()

    def test_saved_result_bytes_and_external_manifest_binding_are_verified(self):
        prepared = self.prepare()
        saved = self.execute(prepared)
        path = Path(saved["result"]["plan"]["package"]) / "plan.json"
        plan = read_json(path)
        plan["execution_authorized"] = True
        path.write_bytes(canonical_bytes(plan))
        with self.assertRaises(Stage3Error):
            self.execute(prepared)
        self.assertEqual(self.callback.call_count, 1)
