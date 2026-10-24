"""Real project activation/frontier with an explicitly synthetic controller only."""

# ruff: noqa: E402 -- import the repository CLI and authored offline fixtures.
from copy import deepcopy
import json
import hashlib
import os
import tempfile
from types import SimpleNamespace
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / "cli"),
    str(Path(__file__).parent),
]

import test_project_stage2 as fixture
from research_workspace_native.project_stage2_controller import (
    ProjectStage2ControllerDriver,
)
import research_workspace_native.project_stage2_controller as driver_module
from research_workspace_native.session_api import SessionApiError
from stage1_ledger.journal import canonical
from stage2_common import Stage2Error, canonical_hash, source_set_hash
from stage2_live import controller
from stage2_workflow import (
    add_snapshot,
    initialize_workflow,
    inspect_workflow,
    start_action,
)
import test_stage2_controller as controller_fixture
import test_stage2_prior_work as prior_fixture


class Handler:
    identity = "explicit-no-model-fixture"

    def __init__(self, spec):
        self.admission_context = dict(
            status="admitted",
            mode="deterministic-no-model",
            execution_policy_sha256=canonical_hash(spec["native"]),
            runtime_sha256="d" * 64,
            deadline_unix=time.time() + 600,
            remaining_budget=dict(model_calls=0, search_calls=0),
        )

    def prepare(self, request):
        raise AssertionError("No prerequisite is executed by this failure fixture")


class ProjectStage2ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.ProjectStage2Tests.setUpClass.__func__(cls)

    body = fixture.ProjectStage2Tests.body

    def setUp(self):
        fixture.ProjectStage2Tests.setUp(self)
        self.service.activate("own", self.ref, self.body())
        self.binding = self.service.binding(self.ref)
        self.workflow = self.binding["workflow_root"]
        state = inspect_workflow(self.workflow)
        self.packet = state["latest_snapshot"]["packet"]
        self.base = state["latest_snapshot"]["event"]["payload"]["snapshot_sha256"]
        self.spec = controller_fixture.Stage2ControllerTests._spec(self)
        self.spec["confirmed_brief_sha256"] = canonical_hash(self.packet["brief"])
        self.output = self.root / "trusted-controller"
        self.delivery = self.root / "trusted-delivery"
        self.handler = Handler(self.spec)
        self.calls = 0

    def driver(self, **changes):
        options = dict(
            spec=self.spec,
            controller_dir=self.output,
            delivery_dir=self.delivery,
            prerequisite_handler=self.handler,
        )
        options.update(changes)
        return ProjectStage2ControllerDriver(self.service, **options)

    def core(self, run, output, delivery, head, spec, *, prerequisite_handler):
        self.calls += 1
        self.assertIs(prerequisite_handler, self.handler)
        # The real controller/store/manifest/verifier run; the adapter refuses
        # deterministically before any model, native process or source search.
        adapter = controller_fixture.SyntheticAdapter()

        def refuse(_):
            adapter.calls.append("synthetic-refusal")
            raise RuntimeError("explicit synthetic producer refusal")

        adapter.research = refuse
        return controller._run_controller(run, output, delivery, head, spec, adapter)

    def run_driver(self, **changes):
        with patch(
            "research_workspace_native.project_stage2_controller.run_controller",
            side_effect=self.core,
        ):
            return self.driver(**changes).run("own", self.ref, key="controller-1")

    def test_sealed_core_result_restores_after_host_result_write_interruption(self):
        original = driver_module._write

        def interrupted(path, value):
            if Path(path).name == "result.json":
                raise OSError("synthetic interruption before Host result persistence")
            return original(path, value)

        with patch.object(driver_module, "_write", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "Host result persistence"):
                self.run_driver()
        self.assertEqual(self.calls, 1)
        self.assertFalse((self.output / "project_stage2_driver/result.json").exists())
        self.assertEqual(
            len(list((self.output / "controller_results").glob("*.json"))), 1
        )
        with patch.object(driver_module, "run_controller") as execute:
            reopened = self.driver().run("own", self.ref, key="controller-1")
        execute.assert_not_called()
        self.assertTrue(reopened["replayed"])
        self.assertEqual(reopened["controller"]["status"], "needs-recovery")
        self.assertFalse(reopened["research_delivery_ready"])
        self.assertFalse(reopened["execution_authorized"])

    def test_real_activation_refuses_version_rewrite_and_same_key_never_redispatches(
        self,
    ):
        _exercise_public_preparation(self, activation_refusal=True)

    def test_real_activation_controller_receipt_and_frontier_are_reopened(self):
        result = self.run_driver()
        self.assertEqual(self.calls, 1)
        self.assertEqual(result["status"], "saved")
        self.assertEqual(result["controller"]["status"], "needs-recovery")
        self.assertTrue(result["controller"]["synthetic_test_only"])
        self.assertFalse(result["research_delivery_ready"])
        self.assertEqual(result["human_selection"], "pending")
        self.assertEqual(result["stage3_receiver"], "not-started")
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["formal_ready"])
        self.assertEqual(self.service.binding(self.ref)["frontier_sequence"], 1)
        intent = json.loads(
            (self.output / "project_stage2_driver" / "intent.json").read_bytes()
        )
        self.assertEqual(
            intent["binding"]["activation_sha256"], self.binding["activation_sha256"]
        )
        self.assertEqual(intent["spec"], self.spec)
        self.assertEqual(intent["admission_context"], self.handler.admission_context)

    def test_same_key_reopen_never_dispatches_and_reverifies_manifest(self):
        first = self.run_driver()
        with patch(
            "research_workspace_native.project_stage2_controller.run_controller"
        ) as execute:
            again = self.driver().run("own", self.ref, key="controller-1")
        execute.assert_not_called()
        self.assertEqual(again["controller"], first["controller"])
        self.assertTrue(again["replayed"])
        self.assertEqual(self.service.binding(self.ref)["frontier_sequence"], 1)
        receipt = first["controller"]["controller_manifest_sha256"]
        manifest = self.output / "controller_manifests" / (receipt + ".json")
        manifest.write_text("{}", encoding="utf-8")
        with patch(
            "research_workspace_native.project_stage2_controller.run_controller"
        ) as execute:
            with self.assertRaises((SessionApiError, Stage2Error)):
                self.driver().run("own", self.ref, key="controller-1")
        execute.assert_not_called()

    def test_original_execution_expiry_prevents_dispatch_without_intent(self):
        self.handler.admission_context["deadline_unix"] = time.time() - 1
        result = self.run_driver()
        self.assertEqual(result["status"], "unavailable-preparation-admission")
        self.assertEqual(self.calls, 0)
        self.assertFalse(
            (self.output / "project_stage2_driver" / "intent.json").exists()
        )

    def test_completed_result_after_execution_expiry_only_recovers_metadata(self):
        first = self.run_driver()
        original = self.handler.admission_context["deadline_unix"]
        with (
            patch("time.time", return_value=original + 1),
            patch(
                "research_workspace_native.project_stage2_controller.run_controller"
            ) as execute,
        ):
            replay = self.driver().run("own", self.ref, key="controller-1")
        self.assertEqual(replay["controller"], first["controller"])
        execute.assert_not_called()

    def test_foreign_credential_refused_before_execution_or_record(self):
        with patch(
            "research_workspace_native.project_stage2_controller.run_controller"
        ) as execute:
            with self.assertRaises(SessionApiError):
                self.driver().run("foreign", self.ref, key="controller-1")
        execute.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_missing_handler_admission_is_readable_unavailable(self):
        del self.handler.admission_context
        result = self.run_driver()
        self.assertEqual(result["status"], "unavailable-preparation-admission")
        self.assertEqual(self.calls, 0)

    def test_interrupted_controller_intent_never_redispatches(self):
        with patch(
            "research_workspace_native.project_stage2_controller.run_controller",
            side_effect=OSError("synthetic unknown outcome"),
        ) as execute:
            first = self.driver().run("own", self.ref, key="controller-1")
            second = self.driver().run("own", self.ref, key="controller-1")
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(first["status"], "execution-unknown")
        self.assertEqual(second["status"], "execution-unknown")

    def test_controller_exception_retains_classification_and_original_message(self):
        error = RuntimeError("HTTP status 429: explicit synthetic refusal")
        with patch(
            "research_workspace_native.project_stage2_controller.run_controller",
            side_effect=error,
        ) as execute:
            first = self.driver().run("own", self.ref, key="controller-1")
            self.driver().run("own", self.ref, key="controller-1")
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(first["status"], "execution-unknown")
        saved = driver_module._read(
            self.output / "project_stage2_driver" / "failure.json"
        )
        self.assertEqual(saved["error_message"], str(error))
        self.assertEqual(
            saved["failure_observation"]["primary_failure_class"], "rate-limit"
        )
        self.assertFalse(saved["failure_observation"]["retry_authorized"])
        self.assertEqual(self.service.binding(self.ref)["frontier_sequence"], 0)

    def test_same_namespace_rejects_key_spec_admission_and_path_replacement(self):
        self.run_driver()
        with patch(
            "research_workspace_native.project_stage2_controller.run_controller"
        ) as execute:
            with self.assertRaisesRegex(SessionApiError, "binding-differs"):
                self.driver().run("own", self.ref, key="different-key")
            changed = deepcopy(self.spec)
            changed["native"]["model"] = "replacement"
            with self.assertRaisesRegex(SessionApiError, "binding-differs"):
                self.driver(spec=changed).run("own", self.ref, key="controller-1")
            with self.assertRaisesRegex(SessionApiError, "binding-differs"):
                self.driver(delivery_dir=self.root / "different-delivery").run(
                    "own", self.ref, key="controller-1"
                )
            self.handler.admission_context["deadline_unix"] += 600
            with self.assertRaisesRegex(SessionApiError, "binding-differs"):
                self.driver().run("own", self.ref, key="controller-1")
        execute.assert_not_called()

    def test_typed_version_drift_is_refused_without_execution(self):
        self.run_driver()
        original = self.intake.read

        def changed(*args, **kwargs):
            value = original(*args, **kwargs)
            value["input_version"] = str(value["input_version"])
            return value

        with (
            patch.object(self.intake, "read", side_effect=changed),
            patch(
                "research_workspace_native.project_stage2_controller.run_controller"
            ) as execute,
        ):
            with self.assertRaisesRegex(SessionApiError, "binding-differs"):
                self.driver().run("own", self.ref, key="controller-1")
        execute.assert_not_called()

    def test_changed_source_is_refused_without_dispatch(self):
        self.run_driver()
        packet = json.loads(self.binding["packet_path"].read_bytes())
        source = self.binding["source_root"] / packet["sources"][0]["path"]
        source.write_bytes(source.read_bytes() + b"\nchanged")
        with patch(
            "research_workspace_native.project_stage2_controller.run_controller"
        ) as execute:
            with self.assertRaises((SessionApiError, Stage2Error)):
                self.driver().run("own", self.ref, key="controller-1")
        execute.assert_not_called()

    def test_changed_current_head_is_refused_without_dispatch(self):
        self.run_driver()
        state = inspect_workflow(self.workflow)
        start_action(
            self.workflow,
            "other-offline-observation",
            "offline-record-only",
            {"purpose": "Synthetic head drift"},
            {"execution_authorized": False},
            state["head_sha256"],
        )
        with patch(
            "research_workspace_native.project_stage2_controller.run_controller"
        ) as execute:
            with self.assertRaises((SessionApiError, Stage2Error)):
                self.driver().run("own", self.ref, key="controller-1")
        execute.assert_not_called()

    def test_unchanged_controller_head_never_fabricates_frontier_progress(self):
        self.run_driver()
        self.output = self.root / "second-trusted-controller"
        with patch.object(self.service, "advance_frontier") as advance:
            result = self.run_driver()
        advance.assert_not_called()
        self.assertEqual(result["status"], "saved")
        self.assertFalse(result["frontier_advanced"])
        self.assertEqual(self.service.binding(self.ref)["frontier_sequence"], 1)

    def test_completed_result_recovers_failed_frontier_registration_without_core(self):
        original = self.intake._save

        def fail_commit(state, kind, payload):
            original(state, kind, payload)
            if kind == "stage2-frontier-saved":
                raise OSError("synthetic frontier commit interruption")

        with patch.object(self.intake, "_save", side_effect=fail_commit):
            first = self.run_driver()
        self.assertEqual(first["status"], "frontier-registration-pending")
        self.assertTrue(
            (self.output / "project_stage2_driver" / "result.json").is_file()
        )
        deadline_checks = []
        with patch(
            "research_workspace_native.project_stage2_controller.run_controller"
        ) as execute:
            recovered = self.driver(
                check_registration_deadline=lambda: deadline_checks.append(True)
            ).run("own", self.ref, key="controller-1")
        execute.assert_not_called()
        self.assertEqual(recovered["status"], "saved")
        self.assertTrue(
            recovered["frontier_registration"]["recovered_from_receipt_sha256"]
        )
        self.assertTrue(deadline_checks)
        self.assertEqual(self.service.binding(self.ref)["frontier_sequence"], 1)

    def test_durable_result_tamper_is_refused_even_after_rehash(self):
        self.run_driver()
        path = self.output / "project_stage2_driver" / "result.json"
        value = json.loads(path.read_bytes())
        value["controller"]["workflow_head_sha256"] = "f" * 64
        value.pop("record_sha256")
        value["record_sha256"] = canonical_hash(value)
        path.write_bytes(canonical(value))
        with self.assertRaises((SessionApiError, Stage2Error)):
            self.driver().run("own", self.ref, key="controller-1")


def _exercise_public_preparation(self, *, activation_refusal=False):
    self.spec["workspaces"] = {
        k: v
        for k, v in self.spec["workspaces"].items()
        if k in {"research", "extractor"}
    }
    self.handler = Handler(self.spec)
    gates = []
    case = self

    class GeneratedCandidate(controller_fixture.SyntheticAdapter):
        def extract(self, context):
            result = super().extract(context)
            packet = result["next_packet"]["packet"]
            packet.update(
                schema_version="2.4.0", supplemental_literature=[], research_tables=None
            )
            packet["candidates"].append(
                dict(
                    candidate_id="candidate-1",
                    version=1,
                    parent_version=None,
                    question="Does the synthetic bounded method answer the saved question?",
                    research_mode="method-development",
                    opportunity="A synthetic bounded comparison remains open.",
                    value="The comparison could inform a synthetic decision.",
                    approach="Compare against the saved precedent.",
                    requirements=["Use the retained source."],
                    limitations=["Synthetic evidence only."],
                    evidence_ids=[packet["evidence"][0]["evidence_id"]],
                )
            )
            packet["prior_work_reviews"] = []
            return result

        def review(self, context):
            result = super().review(context)
            for finding in result["review"]["assessment"]["checks"].values():
                finding["evidence_ids"] = [
                    context["packet"]["evidence"][0]["evidence_id"]
                ]
            return result

        def resolve(self, context):
            result = super().resolve(context)
            result["resolution"]["evidence_ids"] = [
                context["packet"]["evidence"][0]["evidence_id"]
            ]
            return result

    def receipt(label):
        path = self.root / ("synthetic-driver-" + label + ".json")
        path.write_text(
            json.dumps({"synthetic_test_only": True, "label": label}), encoding="utf-8"
        )
        return dict(
            path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest()
        )

    def prepare(request):
        gates.append(request["gate"]["status"])
        spec = deepcopy(request["spec"])
        head = request["expected_head"]
        if request["gate"]["status"] == "needs-prior-work":
            state = inspect_workflow(self.workflow)
            packet = deepcopy(state["latest_snapshot"]["packet"])
            candidate, work = packet["candidates"][-1], packet["literature"][0]
            packet["prior_work_reviews"] = [
                dict(
                    kind="Stage2PriorWorkReview",
                    schema_version="1.0.0",
                    candidate_id=candidate["candidate_id"],
                    candidate_version=candidate["version"],
                    candidate_sha256=canonical_hash(candidate),
                    source_set_sha256=source_set_hash(packet),
                    positioning="Synthetic comparison against a retained work; global novelty unknown.",
                    review_status="partial",
                    stop_reason="Deterministic fixture has no search executor.",
                    search_limits=["No actual search is authorized."],
                    unresolved=["Actual search remains unavailable."],
                    searches=[
                        dict(
                            search_id="planned-only",
                            need="Inspect the closest precedent.",
                            query="synthetic planned query",
                            status="planned",
                            tool_ref=None,
                            raw_path=None,
                            raw_sha256=None,
                            outcome="unknown",
                            work_refs=[],
                        )
                    ],
                    comparisons=[
                        dict(
                            work_id=work["work_id"],
                            version_id=work["version_id"],
                            role="closest",
                            established="A saved synthetic baseline.",
                            overlap="A bounded comparison.",
                            difference="A synthetic method component.",
                            evidence_ids=[packet["evidence"][0]["evidence_id"]],
                            limitations=["No claim of scientific novelty."],
                        )
                    ],
                )
            ]
            path = self.root / "synthetic-driver-prior-packet.json"
            path.write_text(json.dumps(packet), encoding="utf-8")
            head = add_snapshot(
                self.workflow,
                path,
                state["latest_snapshot"]["checker"]["root"] / "sources",
                "Retain a synthetic partial dossier with planned searches only.",
                {
                    "candidate-1": dict(
                        status="affected", reason="Synthetic dossier supplied."
                    )
                },
                state["head_sha256"],
            )["event_sha256"]
        else:
            for index, key in enumerate(request["gate"]["required_workspace_keys"]):
                spec["workspaces"][key] = dict(
                    home=str(case.root / ("prepared-home-" + str(index))),
                    workspace=str(case.root / ("prepared-workspace-" + str(index))),
                )
        return dict(
            status="complete",
            spec=spec,
            expected_head=head,
            continuation_snapshot_sha256=None,
            receipts=[receipt(str(len(gates)))],
        )

    self.handler.prepare = prepare
    adapter = GeneratedCandidate()
    errors = []

    def checked_entry(*args, **kwargs):
        try:
            return controller.run_controller(*args, **kwargs)
        except Exception as error:
            errors.append(type(error).__name__ + ": " + str(error))
            raise

    with (
        patch("stage2_live.controller._ProductionAdapter", return_value=adapter),
        patch.object(
            driver_module, "run_controller", side_effect=checked_entry
        ) as entry,
    ):
        first = self.driver().run("own", self.ref, key="combined-prerequisites")
        if activation_refusal:
            self.assertEqual(first["status"], "execution-unknown")
            self.assertTrue(
                any(
                    "workflow-packet-version-change-requires-new-run" in error
                    for error in errors
                )
            )
            calls = list(adapter.calls)
            replay = self.driver().run("own", self.ref, key="combined-prerequisites")
            self.assertEqual(entry.call_count, 1)
            self.assertEqual(adapter.calls, calls)
            self.assertEqual(replay["status"], "execution-unknown")
            return
        self.assertEqual(first["status"], "saved", errors)
        self.assertEqual(first["controller"]["preparation"]["status"], "complete")
        self.assertEqual(gates, ["needs-prior-work", "needs-workspace"])
        self.assertEqual(adapter.calls.count("research"), 1)
        self.assertEqual(adapter.calls.count("extract"), 1)
        self.assertIn("review:challenger", adapter.calls)
        self.assertFalse(first["formal_ready"])
        calls = list(adapter.calls)
        replay = self.driver().run("own", self.ref, key="combined-prerequisites")
        self.assertEqual(entry.call_count, 1)
        self.assertEqual(adapter.calls, calls)
        self.assertEqual(gates, ["needs-prior-work", "needs-workspace"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["controller"], first["controller"])


class SyntheticPublicPreparationTests(unittest.TestCase):
    """Composition only: v2.4 fixture bindings provide no activation/admission proof."""

    driver = ProjectStage2ControllerTests.driver

    def setUp(self):
        prior = prior_fixture.Stage2PriorWorkTests("runTest")
        prior.setUp()
        self.addCleanup(prior.doCleanups)
        self.root, self.ref = prior.root, "explicit-synthetic-project"
        self.packet = deepcopy(prior.packet)
        self.packet.update(candidates=[], prior_work_reviews=[])
        packet_path = self.root / "synthetic-public-base.json"
        packet_path.write_text(json.dumps(self.packet), encoding="utf-8")
        self.workflow = self.root / "synthetic-public-workflow"
        initialize_workflow(
            packet_path,
            prior.source_root,
            self.workflow,
            {"model": "synthetic-model", "reasoning": "medium"},
            {"path": "policy.json", "sha256": "a" * 64},
            canonical_hash(self.packet),
        )
        state = inspect_workflow(self.workflow)
        self.base = state["latest_snapshot"]["event"]["payload"]["snapshot_sha256"]
        self.spec = controller_fixture.Stage2ControllerTests._spec(self)
        self.output, self.delivery = (
            self.root / "synthetic-public-controller",
            self.root / "synthetic-public-delivery",
        )
        activation = dict(synthetic_test_only=True, fixture="existing-prior-work-v2.4")
        identity = dict(
            project_id=self.ref,
            input_version="synthetic-v2.4",
            brief_sha256=canonical_hash(self.packet["brief"]),
            origin_identity="fixture-only",
        )
        binding = dict(
            identity,
            source_root=str(prior.source_root),
            packet_path=str(packet_path),
            workflow_root=str(self.workflow),
            workflow_head_sha256=state["head_sha256"],
            initial_workflow_head_sha256=state["head_sha256"],
            activation_sha256=canonical_hash(activation),
            packet_sha256=canonical_hash(self.packet),
            frontier_sequence=0,
            execution_authorized=False,
        )
        saved = []

        def read(credential, project_ref):
            self.assertEqual((credential, project_ref), ("own", self.ref))
            return deepcopy(identity)

        def current(project_ref):
            self.assertEqual(project_ref, self.ref)
            inspect_workflow(
                self.workflow, expected_head=binding["workflow_head_sha256"]
            )
            return deepcopy(binding)

        def action(credential, project_ref, key):
            read(credential, project_ref)
            if not saved:
                raise SessionApiError("intake-action-unavailable", 404)
            self.assertEqual(key, saved[0][0]["key"])
            return deepcopy(saved[0][1])

        def advance(project_ref, **arguments):
            self.assertEqual(project_ref, self.ref)
            self.assertEqual(
                arguments["expected_previous_head_sha256"],
                binding["workflow_head_sha256"],
            )
            self.assertEqual(
                arguments["expected_activation_sha256"], binding["activation_sha256"]
            )
            inspect_workflow(
                self.workflow, expected_head=arguments["new_workflow_head_sha256"]
            )
            binding.update(
                workflow_head_sha256=arguments["new_workflow_head_sha256"],
                frontier_sequence=1,
            )
            result = dict(
                status="saved", execution_authorized=False, synthetic_test_only=True
            )
            saved.append((arguments, result))
            return deepcopy(result)

        def recover(project_ref, **arguments):
            self.assertEqual(project_ref, self.ref)
            self.assertEqual(arguments, saved[0][0])
            return deepcopy(saved[0][1])

        self.service = SimpleNamespace(
            intake=SimpleNamespace(read=read, binding=lambda _: deepcopy(identity)),
            read=lambda *_: dict(activation=deepcopy(activation)),
            binding=current,
            action=action,
            advance_frontier=advance,
            recover_frontier=recover,
        )

    def test_public_driver_prepares_both_gates_and_same_key_never_redispatches(self):
        _exercise_public_preparation(self)


class DriverFileBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="driver-boundary-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def test_regular_bounded_record_read_and_oversize_refusal(self):
        path = self.root / "record.json"
        driver_module._write(path, {"ordinary": "metadata"})
        self.assertEqual(driver_module._read(path), {"ordinary": "metadata"})
        path.write_bytes(b"x" * (4 * 1024 * 1024 + 1))
        with self.assertRaisesRegex(SessionApiError, "record-bound"):
            driver_module._raw(path)

    def test_ancestor_reparse_rejected_before_resolve(self):
        original = os.lstat

        def reparse_ancestor(candidate, *args, **kwargs):
            info = original(candidate, *args, **kwargs)
            if Path(candidate).absolute() == self.root:
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            return info

        with patch("stage1_deliverable.common.os.lstat", side_effect=reparse_ancestor):
            with self.assertRaisesRegex(Stage2Error, "linked"):
                driver_module._guard(self.root / "not-created-yet")


if __name__ == "__main__":
    unittest.main()
