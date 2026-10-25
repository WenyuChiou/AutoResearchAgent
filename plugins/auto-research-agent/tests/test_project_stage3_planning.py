"""Fixed-callback integration; no research, scoring or native model calls."""

# ruff: noqa: E402 -- exercise the CLI and existing authored package fixtures.
from copy import deepcopy
import json
from pathlib import Path
import sys
from threading import Thread
import unittest
from unittest.mock import Mock, patch

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / "cli"),
    str(Path(__file__).resolve().parent),
]
import test_project_stage123_controller_e2e as current
from research_workspace_native.journal import Journal
from research_workspace_native.project_stage2_controller import (
    ProjectStage2ControllerDriver,
)
from research_workspace_native.project_stage2_selection import (
    ProjectStage2SelectionService,
)
from research_workspace_native.project_stage2 import ProjectStage2Service
from research_workspace_native.project_stage3_planning import (
    ProjectStage3PlanningService,
)
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable import sources
from stage3_plan.contracts import Stage3Error, canonical_bytes, digest
from stage3_plan.jobs import POLICY, PlanningJobs
from stage3_plan.planning_conditions import condition_sources
from stage3_plan.storage import read_json
from stage3_plan_fixtures import make_plan


def authored_plan(intake, pin, plan_id):
    """Adapt the existing generic theory fixture to the actually admitted SQs."""
    plan = make_plan(
        "theory", question_count=len(intake["questions"]), shared_path=True
    )
    refs = [q["question_ref"] for q in intake["questions"]]
    mapping = dict(zip([q["question_ref"] for q in plan["questions"]], refs))
    plan.update(
        schema_version="1.1.0",
        plan_id=plan_id,
        source_manifest_sha256=pin,
        condition_dispositions=[],
    )
    plan["selected_candidates"] = deepcopy(intake["selected_candidates"])
    plan["questions"] = deepcopy(intake["questions"])
    for row in plan["question_plans"]:
        row["question_ref"] = mapping[row["question_ref"]]
        row["resource_uses"][0]["status"] = "unknown"
        row["blockers"] = ["Fixture material availability remains unknown."]
    for group in ("designs", "analyses", "results"):
        for row in plan[group]:
            row["question_refs"] = [mapping[ref] for ref in row["question_refs"]]
    for resource in plan["resources"]:
        resource.update(
            origin="proposed",
            availability="unknown",
            uncertainties=["Synthetic fixture supplies no access evidence."],
        )
    for i, source in enumerate(condition_sources(intake)):
        uid = "source-unknown-" + str(i)
        plan["unknowns"].append(
            dict(
                description=json.dumps(source["value"], ensure_ascii=False),
                question_refs=refs,
                resolution="Record source-linked resolution evidence.",
                blocking=True,
                unknown_id=uid,
                kind="other",
                resolve_before="plan-review",
                resource_ids=[],
                owner=None,
                resolution_evidence_needed="A versioned receipt.",
                recheck_trigger="Source or selected scope changes.",
                fallback="Retain the question as unanswered.",
                scope_change_required=False,
                disposition="unresolved",
            )
        )
        plan["condition_dispositions"].append(
            dict(
                condition_ref=source["condition_ref"],
                source_sha256=source["source_sha256"],
                question_refs=refs,
                interpretation="Preserve the original condition.",
                disposition="blocked",
                response="Resolve the linked unknown before review.",
                unknown_ids=[uid],
            )
        )
    plan["unknowns"].append(
        dict(
            description="The proposed material remains unverified.",
            question_refs=refs,
            resolution="Verify documentation, access and question-specific material fit.",
            blocking=True,
            unknown_id="material",
            kind="material-fit",
            resolve_before="material-design",
            resource_ids=["resource-1"],
            owner=None,
            resolution_evidence_needed="Versioned material-fit evidence.",
            recheck_trigger="The material or design changes.",
            fallback="Narrow the design.",
            scope_change_required=False,
            disposition="unresolved",
        )
    )
    return plan


class ProjectStage3PlanningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Compute the real exporter environment attestation once for these fixed
        # fixtures. Repeated installed-distribution hashing belongs to upstream
        # runtime tests, not each Stage3 bridge assertion. Admission stays real.
        runtime = sources.runtime_binding()
        cls.enterClassContext(
            patch.object(sources, "runtime_binding", return_value=runtime)
        )
        # Reuse package construction, never invoke the previous test as a nested
        # test or count its assertions as new samples.
        cls.fixture_type = current.ImportedRichControllerChoiceE2ETests
        cls.fixture_type.setUpClass()
        cls.addClassCleanup(cls.fixture_type.doClassCleanups)
        f = cls.fixture_type()
        f.setUp()
        cls.addClassCleanup(f.doCleanups)
        driver = ProjectStage2ControllerDriver(
            f.service,
            spec=f.spec,
            controller_dir=f.output,
            delivery_dir=f.delivery,
            prerequisite_handler=f.handler,
        )
        with patch(
            "stage2_live.controller._ProductionAdapter",
            return_value=current.RichSyntheticAdapter(),
        ):
            saved = driver.run("own", f.ref, key="synthetic-controller-once")
        f.assertEqual(saved["status"], "saved", saved)
        project = f.intake.read("own", f.ref)
        manifest = read_json(f.delivery / "delivery_manifest.json")
        choice = ProjectStage2SelectionService(
            f.intake,
            {
                f.ref: dict(
                    input_version=project["input_version"],
                    brief_sha256=project["brief_sha256"],
                    workflow_root=str(f.workflow),
                    delivery_root=str(f.delivery),
                    delivery_manifest_sha256=manifest["manifest_sha256"],
                ),
            },
        )
        view = choice.read("own", f.ref)
        fields = (
            "revision",
            "input_version",
            "brief_sha256",
            "delivery_manifest_sha256",
            "workflow_head_sha256",
            "snapshot_sha256",
        )
        selection = choice.select(
            "own",
            f.ref,
            dict(
                key="synthetic-bridge-choice",
                confirmed=True,
                **{key: view[key] for key in fields},
                decision=dict(
                    actor="synthetic-user",
                    kind="select",
                    selected=view["eligible"],
                    user_text="Fixture choice for engineering planning only.",
                    conditions=["Keep limitations"],
                    unresolved=["Access unknown"],
                    rationale="Fixed bridge fixture",
                    scope_or_resource_change=False,
                ),
            ),
        )
        f.assertFalse(f.intake.db.in_transaction)
        verified, _ = choice._current_context("own", f.ref)
        cls.f, cls.choice, cls.selection, cls.admitted = (
            f,
            choice,
            selection,
            verified[-1],
        )
        state = f.intake._load(f.intake._principal("own"), f.ref)
        cls.activation_context = f.service._activation_context(f.ref, state)

    def setUp(self):
        f = self.f
        # The immutable upstream activation was verified while building the one
        # shared source fixture. These focused cases substitute that result only;
        # current project/receipt/frontier and strict Stage3 admission stay real.
        # Upstream exporter/environment drift is covered by its registered tests.
        self.enterContext(
            patch.object(
                ProjectStage2Service,
                "_activation_context",
                return_value=deepcopy(self.activation_context),
            )
        )
        project = f.intake.read("own", f.ref)
        root = f.root / self._testMethodName
        self.journal = Journal(root / "host-jobs.sqlite")
        self.addCleanup(self.journal.close)
        self.journal.bind_project(project["project_id"], digest({"fixture": f.ref}))
        owner = self.journal.acquire_owner(project["project_id"], "synthetic-host")
        self.jobs = PlanningJobs(
            self.journal,
            project["project_id"],
            owner,
            root / "stage3-jobs",
            project_ref=f.ref,
        )
        self.key = "synthetic-stage3-plan"
        self.plan = authored_plan(
            self.admitted,
            self.selection["planning_manifest_sha256"],
            "host-plan-" + digest(self.key),
        )
        self.callback = Mock(
            return_value=dict(
                raw_response=canonical_bytes(self.plan),
                provenance={"kind": "authored-test"},
            )
        )
        self.callback.request_context = {"kind": "fixed-callback", "timeout_seconds": 5}
        self.binding = dict(
            jobs=self.jobs,
            configuration={"model": "fixture-model", "reasoning": "medium"},
            callback=self.callback,
        )
        self.bridge = self.service()
        self.native = self.enterContext(
            patch(
                "stage3_plan.native.NativePlanner.__call__",
                side_effect=AssertionError("native call forbidden"),
            )
        )
        self.process = self.enterContext(
            patch(
                "subprocess.Popen", side_effect=AssertionError("process call forbidden")
            )
        )
        self.addCleanup(self.process.assert_not_called)
        self.addCleanup(self.native.assert_not_called)

    def service(self, binding=None):
        return ProjectStage3PlanningService(
            self.f.intake, self.choice, bindings={self.f.ref: binding or self.binding}
        )

    def body(self, **changes):
        project = self.f.intake.read("own", self.f.ref)
        return dict(
            key=self.key,
            revision=project["revision"],
            input_version=project["input_version"],
            brief_sha256=project["brief_sha256"],
            selection_request_sha256=self.selection["request_sha256"],
            **changes,
        )

    def prepared(self):
        result = self.bridge.prepare("own", self.f.ref, self.body())
        return self.body(request_sha256=result["request_sha256"])

    def item(self):
        return self.journal.snapshot(self.jobs.project_id)["intents"][
            self.jobs._key(self.key)
        ]

    def test_save_only_prepares_real_checkpoint_without_dispatch(self):
        before = self.f.intake.read("own", self.f.ref)
        self.assertEqual(
            self.bridge.read("own", self.f.ref)["selection_status"], "recorded"
        )
        body = self.prepared()
        replay = self.bridge.prepare("own", self.f.ref, self.body())
        self.assertEqual(replay["status"], "intent-recorded")
        self.assertEqual(self.bridge.inspect("own", self.f.ref, body), replay)
        payload = self.item()["payload"]
        checkpoint = read_json(payload["checkpoint"]["path"])
        self.assertEqual(checkpoint["kind"], "Stage3WorkflowCheckpoint")
        self.assertEqual(payload["plan"]["schema_version"], "1.1.0")
        self.assertEqual(payload["project_ref"], self.f.ref)
        self.assertEqual(payload["project_id"], before["project_id"])
        self.assertNotEqual(payload["project_ref"], payload["project_id"])
        self.assertEqual(self.f.intake.read("own", self.f.ref), before)
        self.callback.assert_not_called()

    def test_explicit_run_preserves_sq_conditions_and_replays_without_dispatch(self):
        body = self.prepared()
        result = self.bridge.run("own", self.f.ref, dict(body, confirmed=True))
        self.assertEqual(result["outcome"], "saved", result)
        self.assertEqual(result["planning_status"], "needs-information")
        self.assertEqual(self.callback.call_count, 1)
        output = Path(self.item()["payload"]["output"]) / "plan"
        plan, request = (
            read_json(output / "plan.json"),
            read_json(output / "request.json"),
        )
        self.assertEqual(plan["questions"], self.admitted["questions"])
        self.assertEqual(request["intake"], self.admitted)
        self.assertTrue(plan["condition_dispositions"])
        prompt = self.callback.call_args.kwargs["prompt"]
        self.assertIn("STAGE3_REVIEWER_ONLY", prompt)
        self.assertIn("STAGE3_AXIS_ONLY", prompt)
        for flag in POLICY:
            self.assertIs(result[flag], False)
        self.assertNotIn(str(self.f.root), json.dumps(result))
        self.assertEqual(
            self.bridge.run("own", self.f.ref, dict(body, confirmed=True)), result
        )
        self.assertEqual(self.bridge.inspect("own", self.f.ref, body), result)
        self.assertEqual(
            self.bridge.recover(
                "own",
                self.f.ref,
                body,
                expected_plan_manifest_sha256=result["plan_manifest_sha256"],
            ),
            result,
        )
        self.assertEqual(self.callback.call_count, 1)

    def test_unconfigured_retains_selection_and_refuses_dispatch(self):
        service = ProjectStage3PlanningService(self.f.intake, self.choice)
        view = service.read("own", self.f.ref)
        self.assertEqual(view["selection_status"], "recorded")
        self.assertFalse(view["planning_configured"])
        with self.assertRaisesRegex(SessionApiError, "unconfigured"):
            service.prepare("own", self.f.ref, self.body())
        self.assertEqual(self.journal.snapshot(self.jobs.project_id)["intents"], {})
        self.callback.assert_not_called()

    def test_explicit_confirmation_and_server_owned_fields_are_required(self):
        body = self.prepared()
        for field, value in [
            ("configuration", {}),
            ("timeout_seconds", 9),
            ("checkpoint", "C:/foreign"),
            ("callback", "native"),
        ]:
            with self.subTest(field=field), self.assertRaises(SessionApiError):
                self.bridge.run(
                    "own", self.f.ref, dict(body, confirmed=True, **{field: value})
                )
        for value in [False, 1, "true", None]:
            with self.subTest(value=value), self.assertRaises(SessionApiError):
                self.bridge.run("own", self.f.ref, dict(body, confirmed=value))
        self.callback.assert_not_called()
        self.assertEqual(self.item()["status"], "intent-recorded")

    def test_versions_request_and_principal_mismatch_preserve_job(self):
        body = self.prepared()
        before = self.item()
        for field, value in [
            ("revision", True),
            ("revision", body["revision"] + 1),
            ("input_version", 1),
            ("selection_request_sha256", "a" * 64),
            ("brief_sha256", "a" * 64),
            ("request_sha256", "b" * 64),
        ]:
            with self.subTest(field=field), self.assertRaises(SessionApiError):
                self.bridge.run(
                    "own", self.f.ref, dict(body, confirmed=True, **{field: value})
                )
        with self.assertRaises(SessionApiError):
            self.bridge.run("foreign", self.f.ref, dict(body, confirmed=True))
        self.assertEqual(self.item(), before)
        self.callback.assert_not_called()

    def test_changed_adapter_and_configuration_cannot_rebind_prepared_job(self):
        body = self.prepared()
        before = self.item()
        changed = self.service(
            dict(
                self.binding, configuration={"model": "changed", "reasoning": "medium"}
            )
        )
        with self.assertRaisesRegex(SessionApiError, "binding-differs"):
            changed.run("own", self.f.ref, dict(body, confirmed=True))
        self.callback.request_context["timeout_seconds"] = 6
        with self.assertRaisesRegex(SessionApiError, "adapter-context-differs"):
            self.bridge.run("own", self.f.ref, dict(body, confirmed=True))
        self.assertEqual(self.item(), before)
        self.callback.assert_not_called()

    def test_cross_project_jobs_and_invalid_deadlines_are_rejected(self):
        self.jobs.project_id = "foreign"
        with self.assertRaisesRegex(SessionApiError, "project-differs"):
            self.bridge.prepare("own", self.f.ref, self.body())
        self.jobs.project_id = self.f.intake.read("own", self.f.ref)["project_id"]
        for timeout in [None, True, 0, -1, float("inf"), float("nan")]:
            self.callback.request_context = {"timeout_seconds": timeout}
            with self.subTest(timeout=timeout), self.assertRaises(SessionApiError):
                self.service()
        self.callback.assert_not_called()

    def test_failed_callback_is_retained_and_same_key_does_not_retry(self):
        body = self.prepared()
        self.callback.side_effect = RuntimeError("authored adapter failure")
        result = self.bridge.run("own", self.f.ref, dict(body, confirmed=True))
        self.assertEqual(result["status"], "execution-unknown", result)
        before = deepcopy(self.item())
        self.assertEqual(
            self.bridge.run("own", self.f.ref, dict(body, confirmed=True)), result
        )
        self.assertEqual(self.bridge.inspect("own", self.f.ref, body), result)
        next_body = self.body()
        next_body["key"] = "different-key"
        with self.assertRaises((Stage3Error, ValueError)):
            self.bridge.prepare("own", self.f.ref, next_body)
        self.assertEqual(self.callback.call_count, 1)
        self.assertEqual(self.item(), before)

    def test_saved_artifact_recovery_never_redispatches(self):
        body = self.prepared()
        original = self.jobs._transition

        def cut(key, status, evidence):
            if status == "completed":
                raise OSError("authored interruption before completion receipt")
            return original(key, status, evidence)

        with patch.object(self.jobs, "_transition", side_effect=cut):
            with self.assertRaises(OSError):
                self.bridge.run("own", self.f.ref, dict(body, confirmed=True))
        self.assertEqual(self.item()["status"], "dispatching")
        self.bridge.inspect("own", self.f.ref, body)
        path = Path(self.item()["payload"]["output"]) / "plan/manifest.json"
        pin = read_json(path)["manifest_sha256"]
        recovered = self.bridge.recover(
            "own", self.f.ref, body, expected_plan_manifest_sha256=pin
        )
        self.assertEqual(recovered["outcome"], "saved")
        self.assertEqual(self.callback.call_count, 1)

    def test_expired_host_request_does_not_dispatch(self):
        body = self.prepared()
        before = self.item()
        with self.assertRaises(TimeoutError):
            self.bridge.run(
                "own",
                self.f.ref,
                dict(body, confirmed=True),
                check_deadline=Mock(side_effect=TimeoutError("expired")),
            )
        self.assertEqual(self.item(), before)
        self.callback.assert_not_called()

    def test_selection_source_drift_rejects_before_dispatch(self):
        body = self.prepared()
        before = self.item()
        output = self.f.intake._path(self.f.ref, self.selection["artifact_ref"])
        path = output / "interaction/interaction.json"
        original = path.read_bytes()
        self.addCleanup(path.write_bytes, original)
        path.write_bytes(original + b"\n")
        with self.assertRaises(SessionApiError):
            self.bridge.run("own", self.f.ref, dict(body, confirmed=True))
        self.assertEqual(self.item(), before)
        self.callback.assert_not_called()

    def test_callback_time_project_drift_cannot_publish_a_plan(self):
        body, changed = self.prepared(), [False]
        original = self.f.intake.read

        def read(*args):
            project = original(*args)
            if changed[0]:
                project["revision"] += 1
            return project

        def response(**request):
            changed[0] = True
            return self.callback.return_value

        self.callback.side_effect = response
        with patch.object(self.f.intake, "read", side_effect=read):
            with self.assertRaises(SessionApiError):
                self.bridge.run("own", self.f.ref, dict(body, confirmed=True))
        root = Path(self.item()["payload"]["output"]) / "plan"
        self.assertFalse((root / "plan.json").exists())
        self.assertTrue((root / "failure.json").exists())
        self.assertEqual(self.item()["status"], "execution-unknown")
        self.assertEqual(self.callback.call_count, 1)

    def test_callback_time_expiry_cannot_publish_a_plan(self):
        body, expired = self.prepared(), [False]

        def deadline():
            if expired[0]:
                raise TimeoutError("expired during callback")

        def response(**request):
            expired[0] = True
            return self.callback.return_value

        self.callback.side_effect = response
        with self.assertRaises(TimeoutError):
            self.bridge.run(
                "own", self.f.ref, dict(body, confirmed=True), check_deadline=deadline
            )
        root = Path(self.item()["payload"]["output"]) / "plan"
        self.assertFalse((root / "plan.json").exists())
        self.assertTrue((root / "failure.json").exists())
        self.assertEqual(self.item()["status"], "execution-unknown")
        self.assertEqual(self.callback.call_count, 1)

    def test_publication_holds_intake_lock_but_adapter_does_not(self):
        body, original = self.prepared(), self.jobs._transition

        def lock_available():
            observed = []

            def probe():
                acquired = self.f.intake._lock.acquire(blocking=False)
                observed.append(acquired)
                if acquired:
                    self.f.intake._lock.release()

            thread = Thread(target=probe)
            thread.start()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            return observed == [True]

        def response(**request):
            self.assertTrue(lock_available())
            return self.callback.return_value

        def transition(key, status, evidence):
            if status == "completed":
                self.assertFalse(lock_available())
            return original(key, status, evidence)

        self.callback.side_effect = response
        with patch.object(self.jobs, "_transition", side_effect=transition):
            result = self.bridge.run("own", self.f.ref, dict(body, confirmed=True))
        self.assertEqual(result["outcome"], "saved", result)
        self.assertTrue(lock_available())

    def test_shared_root_and_key_keep_internal_projects_separate(self):
        self.prepared()
        second_id = "second-host-internal-project"
        self.journal.bind_project(second_id, digest({"second-fixture": self.f.ref}))
        owner = self.journal.acquire_owner(second_id, "synthetic-second-host")
        second = PlanningJobs(
            self.journal, second_id, owner, self.jobs.root, project_ref=self.f.ref
        )
        bridge = self.service(dict(self.binding, jobs=second))
        verified, context = self.choice._current_context("own", self.f.ref)
        # Isolate output allocation for two trusted Host internal identities.
        # The original selected source, strict admission and job writes stay real;
        # this case does not attest a second real user/project import.
        project = dict(verified[0], project_id=second_id)
        with patch.object(
            self.choice,
            "_current_context",
            return_value=((project, *verified[1:]), context),
        ):
            result = bridge.prepare("own", self.f.ref, self.body())
        item = self.journal.snapshot(second_id)["intents"][second._key(self.key)]
        first_path = self.item()["payload"]["checkpoint"]["path"]
        second_path = item["payload"]["checkpoint"]["path"]
        self.assertEqual(result["status"], "intent-recorded")
        self.assertNotEqual(first_path, second_path)
        self.assertTrue(all(Path(path).is_file() for path in [first_path, second_path]))
        self.callback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
