# ruff: noqa: E402 -- reuse the repository's explicitly synthetic controller fixtures.
"""Trusted prerequisite preparation must not create a second execution engine."""

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "cli")]

from stage2_common import Stage2Error, canonical_hash, source_set_hash
from stage2_live.controller import run_controller
from stage2_live.environment import environment_key
from stage2_live.preparation import validate_spec_update
import stage2_live.preparation as preparation
from stage2_workflow.store import add_snapshot, initialize_workflow, inspect_workflow
import test_stage2_controller as fixtures
import test_stage2_prior_work as prior_fixtures


class DeterministicPreparation:
    identity = "synthetic-prerequisite-handler-v1"

    def __init__(self, case, callback=None):
        self.case, self.callback, self.calls = case, callback, []
        self.admission_context = {
            "status": "admitted",
            "mode": "deterministic-no-model",
            "execution_policy_sha256": canonical_hash(case.spec["native"]),
            "runtime_sha256": "a" * 64,
            "deadline_unix": time.time() + 600,
            "remaining_budget": {"model_calls": 0, "search_calls": 0},
        }

    def prepare(self, request):
        self.calls.append(copy.deepcopy(request))
        if self.callback:
            return self.callback(request)
        return self.case.complete_workspaces(request)


class ControllerPreparationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.Stage2ControllerTests(
            "test_complete_pipeline_replays_without_new_calls_and_awaits_human"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        for name in ("root", "run", "controller", "delivery", "initial"):
            setattr(self, name, getattr(self.fixture, name))
        self.spec = copy.deepcopy(self.fixture.spec)
        self.spec["workspaces"] = {
            key: value
            for key, value in self.spec["workspaces"].items()
            if key in {"research", "extractor"}
        }
        self.adapter = fixtures.SyntheticAdapter()

    def invoke(self, handler=None, *, head=None):
        with patch(
            "stage2_live.controller._ProductionAdapter", return_value=self.adapter
        ):
            return run_controller(
                self.run,
                self.controller,
                self.delivery,
                head or inspect_workflow(self.run)["head_sha256"],
                self.spec,
                prerequisite_handler=handler,
            )

    def receipt(self, label):
        path = self.root / f"synthetic-preparation-{label}.json"
        path.write_text(
            json.dumps({"synthetic_test_only": True, "label": label}), encoding="utf-8"
        )
        return {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    def complete_workspaces(self, request):
        spec = copy.deepcopy(request["spec"])
        for index, key in enumerate(request["gate"]["required_workspace_keys"]):
            spec["workspaces"][key] = {
                "workspace": str(self.root / f"prepared-workspace-{index}"),
                "home": str(self.root / f"prepared-home-{index}"),
            }
        return {
            "status": "complete",
            "spec": spec,
            "expected_head": request["expected_head"],
            "continuation_snapshot_sha256": spec.get("continuation_snapshot_sha256"),
            "receipts": [self.receipt("workspace")],
        }

    def test_real_workspace_gate_completes_and_reopens_without_callback_or_calls(self):
        handler = DeterministicPreparation(self)
        result = self.invoke(handler)
        self.assertEqual(result["status"], "awaiting-human")
        self.assertFalse(result["formal_ready"])
        self.assertEqual(len(handler.calls), 1)
        request = handler.calls[0]
        self.assertEqual(
            request["execution_policy_sha256"], canonical_hash(self.spec["native"])
        )
        self.assertEqual(request["admission_context"], handler.admission_context)
        calls = list(self.adapter.calls)
        reopened = self.invoke(handler)
        self.assertEqual(reopened["status"], "awaiting-human")
        self.assertEqual(self.adapter.calls, calls)
        self.assertEqual(len(handler.calls), 1)
        self.assertEqual(
            reopened["preparation"]["usage_observations"], [{"status": "unknown"}]
        )

    def test_absent_or_unknown_admission_keeps_readable_gate_without_callback(self):
        original = self.invoke()
        self.assertEqual(original["status"], "needs-workspace")
        handler = DeterministicPreparation(self)
        del handler.admission_context
        stopped = self.invoke(handler)
        self.assertEqual(stopped["status"], "needs-workspace")
        self.assertEqual(
            stopped["preparation"]["status"], "unavailable-preparation-admission"
        )
        self.assertEqual(handler.calls, [])
        self.assertEqual(
            stopped["required_workspace_keys"], original["required_workspace_keys"]
        )

    def test_runtime_model_budget_and_existing_workspace_changes_are_rejected(self):
        def changed(request):
            value = self.complete_workspaces(request)
            value["spec"]["native"]["model"] = "unauthorized-model"
            return value

        handler = DeterministicPreparation(self, changed)
        result = self.invoke(handler)
        self.assertEqual(result["preparation"]["status"], "failed")
        self.assertIn("immutable-spec", result["preparation"]["reason"])
        self.assertEqual(self.adapter.calls, ["research", "extract"])
        self.invoke(handler)
        self.assertEqual(len(handler.calls), 1)

    def test_existing_workspace_replacement_and_unrequested_slot_are_rejected(self):
        for change in ("replace", "extra"):
            with self.subTest(change=change):
                spec = copy.deepcopy(self.spec)
                value = {"workspaces": copy.deepcopy(spec["workspaces"])}
                if change == "replace":
                    value["workspaces"]["research"]["home"] += "-changed"
                else:
                    value["workspaces"]["unrequested"] = {
                        "home": "other",
                        "workspace": "other",
                    }
                with self.assertRaisesRegex(Stage2Error, "workspace"):
                    validate_spec_update(
                        spec,
                        {**spec, **value},
                        {"status": "needs-workspace", "required_workspace_keys": []},
                        {},
                    )

    def test_stale_callback_head_is_retained_as_failure_without_reviews(self):
        def stale(request):
            value = self.complete_workspaces(request)
            value["expected_head"] = "f" * 64
            return value

        result = self.invoke(DeterministicPreparation(self, stale))
        self.assertEqual(result["preparation"]["status"], "failed")
        self.assertIn("head", result["preparation"]["reason"])
        self.assertEqual(self.adapter.calls, ["research", "extract"])

    def test_exception_or_unavailable_result_never_retries_callback(self):
        def failed(_request):
            raise RuntimeError("preserved synthetic preparation failure")

        handler = DeterministicPreparation(self, failed)
        first = self.invoke(handler)
        self.assertEqual(first["preparation"]["status"], "failed")
        self.assertIn("preserved synthetic", first["preparation"]["reason"])
        self.invoke(handler)
        self.assertEqual(len(handler.calls), 1)

    def test_unknown_callback_outcome_holds_without_redispatch(self):
        def interrupted(_request):
            raise KeyboardInterrupt("synthetic interruption after durable intent")

        handler = DeterministicPreparation(self, interrupted)
        with self.assertRaises(KeyboardInterrupt):
            self.invoke(handler)
        result = self.invoke(handler)
        self.assertEqual(result["preparation"]["status"], "needs-recovery")
        self.assertEqual(len(handler.calls), 1)
        self.assertEqual(self.adapter.calls, ["research", "extract"])

    def test_changed_receipt_or_preparation_record_fails_before_engine_reentry(self):
        handler = DeterministicPreparation(self)
        self.invoke(handler)
        calls = list(self.adapter.calls)
        (self.root / "synthetic-preparation-workspace.json").write_text(
            "tamper", encoding="utf-8"
        )
        with self.assertRaisesRegex(Stage2Error, "receipt"):
            self.invoke(handler)
        self.assertEqual(self.adapter.calls, calls)

    def test_changed_handler_or_renewed_deadline_fails_before_callback(self):
        handler = DeterministicPreparation(self)
        self.invoke(handler)
        handler.admission_context["deadline_unix"] += 600
        with self.assertRaisesRegex(Stage2Error, "admission"):
            self.invoke(handler)
        self.assertEqual(len(handler.calls), 1)

    def test_record_tamper_and_stale_entry_head_fail_without_execution(self):
        handler = DeterministicPreparation(self)
        self.invoke(handler)
        calls = list(self.adapter.calls)
        record = next(self.controller.rglob("*.result.json"))
        value = json.loads(record.read_text(encoding="utf-8"))
        value["response"]["usage"] = {"model_calls": 0}
        record.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "record-hash"):
            self.invoke(handler)
        with self.assertRaises(Stage2Error):
            self.invoke(handler, head="f" * 64)
        self.assertEqual(self.adapter.calls, calls)

    def test_expired_admission_returns_original_gate_without_engine_reentry(self):
        handler = DeterministicPreparation(self)
        self.invoke(handler)
        calls = list(self.adapter.calls)
        handler.admission_context["deadline_unix"] = time.time() - 1
        result = self.invoke(handler)
        self.assertEqual(result["status"], "needs-workspace")
        self.assertEqual(
            result["preparation"]["status"], "unavailable-preparation-admission"
        )
        self.assertEqual(self.adapter.calls, calls)

    def test_callback_consuming_deadline_never_reenters_engine(self):
        now = [time.time()]

        def consumes_deadline(request):
            result = self.complete_workspaces(request)
            now[0] = request["admission_context"]["deadline_unix"] + 1
            return result

        handler = DeterministicPreparation(self, consumes_deadline)
        with patch("stage2_live.preparation.time.time", side_effect=lambda: now[0]):
            with patch(
                "stage2_live.controller._run_controller", wraps=fixtures._run_controller
            ) as engine:
                result = self.invoke(handler)
        self.assertEqual(engine.call_count, 1)
        self.assertEqual(self.adapter.calls, ["research", "extract"])
        self.assertEqual(result["status"], "needs-workspace")
        self.assertEqual(
            result["preparation"]["status"], "unavailable-preparation-admission"
        )
        self.assertEqual(len(handler.calls), 1)

    def test_callback_snapshot_then_failure_returns_current_head_without_retry(self):
        original_head = []

        def append_then_fail(request):
            original_head.append(request["gate"]["workflow_head_sha256"])
            state = inspect_workflow(self.run)
            snapshot = state["latest_snapshot"]
            packet = copy.deepcopy(snapshot["packet"])
            packet["packet_id"] = "preparation-snapshot-before-failure"
            path = self.root / "preparation-failure-packet.json"
            path.write_text(json.dumps(packet), encoding="utf-8")
            add_snapshot(
                self.run,
                path,
                snapshot["checker"]["root"] / "sources",
                "Retain a supported preparation snapshot before failure.",
                {
                    "candidate-1": {
                        "status": "affected",
                        "reason": "Preparation evidence retained.",
                    }
                },
                state["head_sha256"],
            )
            raise RuntimeError("synthetic failure after supported snapshot append")

        handler = DeterministicPreparation(self, append_then_fail)
        stopped = self.invoke(handler)
        current_head = inspect_workflow(self.run)["head_sha256"]
        self.assertNotEqual(current_head, original_head[0])
        self.assertEqual(stopped["workflow_head_sha256"], current_head)
        self.assertEqual(
            stopped["preparation"]["gate_workflow_head_sha256"], original_head[0]
        )
        intent = json.loads(
            next(self.controller.rglob("*.intent.json")).read_text(encoding="utf-8")
        )
        self.assertEqual(intent["gate"]["workflow_head_sha256"], original_head[0])
        reopened = self.invoke(handler)
        self.assertEqual(reopened["workflow_head_sha256"], current_head)
        self.assertEqual(reopened["preparation"]["status"], "failed")
        self.assertEqual(len(handler.calls), 1)
        self.assertEqual(self.adapter.calls, ["research", "extract"])

    def test_exact_thread_inventory_template_reaches_capture_lookup(self):
        old = copy.deepcopy(self.spec)
        old.setdefault("execution_policies", {})
        old["execution_inventories"] = {"retained-thread": {"receipt": "retained"}}
        new = copy.deepcopy(old)
        slot = "review-slot:0:challenger"
        new["workspaces"][slot] = {
            "home": str(self.root / "thread-home"),
            "workspace": str(self.root / "thread-workspace"),
        }
        key = environment_key(**new["workspaces"][slot])
        policy = {"synthetic_role_policy": True}
        new["execution_policies"][key] = policy
        thread_id = "019synthetic-thread-owner"
        inventory = {"synthetic_test_only": True, "receipt_sha256": "b" * 64}
        new["execution_inventories"][thread_id] = inventory
        templates = {
            slot: {
                "execution_policy": policy,
                "receipt": self.receipt("thread-template"),
                "inventories": {thread_id: inventory},
            }
        }
        gate = {"status": "needs-workspace", "required_workspace_keys": [slot]}
        validate_spec_update(old, new, gate, templates)
        self.assertEqual(new["execution_inventories"][thread_id], inventory)
        for change in ("unrelated", "changed", "retained"):
            altered = copy.deepcopy(new)
            if change == "unrelated":
                altered["execution_inventories"]["foreign-thread"] = inventory
            elif change == "changed":
                altered["execution_inventories"][thread_id] = {
                    "synthetic_test_only": "changed"
                }
            else:
                altered["execution_inventories"]["retained-thread"] = inventory
            with self.subTest(change=change), self.assertRaises(Stage2Error):
                validate_spec_update(old, altered, gate, templates)

    def test_each_guard_byte_change_invalidates_preparation_replay(self):
        handler = DeterministicPreparation(self)
        self.invoke(handler)
        calls = list(self.adapter.calls)
        original = Path(preparation.__file__)
        for index, name in enumerate(("preparation.py", "execution_admission.py")):
            with self.subTest(helper=name):
                copies = self.root / ("replay-guard-" + str(index))
                copies.mkdir()
                for file in ("preparation.py", "execution_admission.py"):
                    (copies / file).write_bytes(original.with_name(file).read_bytes())
                with (copies / name).open("ab") as stream:
                    stream.write(b"\n# synthetic byte-change probe; never executed\n")
                with patch.object(
                    preparation, "__file__", str(copies / "preparation.py")
                ):
                    with self.assertRaisesRegex(
                        Stage2Error, "preparation-binding-changed"
                    ):
                        self.invoke(handler)
        self.assertEqual(self.adapter.calls, calls)

    def test_environment_proofs_are_additive_and_exact_template_bound(self):
        old = copy.deepcopy(self.spec)
        for name in (
            "execution_policies",
            "execution_preflights",
            "execution_inventories",
        ):
            old[name] = {"existing": {"frozen": name}}
        new = copy.deepcopy(old)
        slot = "review-slot:0:challenger"
        new["workspaces"][slot] = {
            "home": str(self.root / "new-home"),
            "workspace": str(self.root / "new-workspace"),
        }
        key = environment_key(**new["workspaces"][slot])
        policy = {"frozen_role_policy": "synthetic-admitted-template"}
        new["execution_policies"][key] = policy
        new["execution_preflights"][key] = {"synthetic_test_only": True}
        thread_id = "synthetic-admitted-thread"
        inventory = {"synthetic_test_only": True}
        new["execution_inventories"][thread_id] = inventory
        gate = {"status": "needs-workspace", "required_workspace_keys": [slot]}
        templates = {
            slot: {
                "execution_policy": policy,
                "receipt": self.receipt("role-template"),
                "inventories": {thread_id: inventory},
            }
        }
        validate_spec_update(old, new, gate, templates)
        changed = copy.deepcopy(new)
        changed["execution_preflights"].pop("existing")
        with self.assertRaisesRegex(Stage2Error, "existing-environment"):
            validate_spec_update(old, changed, gate, templates)
        with self.assertRaisesRegex(Stage2Error, "role-template|unrequested-inventory"):
            validate_spec_update(old, new, gate, {})

    def test_preparation_cannot_write_inside_a_protected_workspace(self):
        self.controller = Path(self.spec["workspaces"]["research"]["workspace"])
        with self.assertRaisesRegex(Stage2Error, "input-output-collision"):
            self.invoke(DeterministicPreparation(self))
        self.assertFalse(self.controller.exists())

    def test_real_prior_work_then_workspace_gates_reuse_saved_ideation(self):
        prior = prior_fixtures.Stage2PriorWorkTests(
            "test_controller_persists_prior_work_gate_and_resumes_completed_snapshot"
        )
        prior.setUp()
        self.addCleanup(prior.doCleanups)
        self.root, self.run = prior.root, prior.root / "auto-preparation-workflow"
        self.controller, self.delivery = (
            prior.root / "auto-controller",
            prior.root / "auto-delivery",
        )
        packet = copy.deepcopy(prior.packet)
        packet["prior_work_reviews"] = []
        path = self.root / "auto-base.json"
        path.write_text(json.dumps(packet), encoding="utf-8")
        initialize_workflow(
            path,
            prior.source_root,
            self.run,
            {"model": "synthetic-model", "reasoning": "medium"},
            {"path": "policy.json", "sha256": "a" * 64},
            canonical_hash(packet),
        )
        state = inspect_workflow(self.run)
        self.spec["confirmed_brief_sha256"] = canonical_hash(packet["brief"])
        self.spec["base_snapshot_sha256"] = state["latest_snapshot"]["event"][
            "payload"
        ]["snapshot_sha256"]

        def prepare(request):
            if request["gate"]["status"] == "needs-workspace":
                return {
                    "status": "unavailable",
                    "reason": "No actual admitted role environments in this synthetic fixture.",
                }
            state = inspect_workflow(self.run)
            completed = copy.deepcopy(state["latest_snapshot"]["packet"])
            dossier = prior.review(status="partial")
            dossier["candidate_sha256"] = canonical_hash(completed["candidates"][-1])
            dossier["source_set_sha256"] = source_set_hash(completed)
            completed["prior_work_reviews"] = [dossier]
            completed_path = self.root / "auto-completed-prior-work.json"
            completed_path.write_text(json.dumps(completed), encoding="utf-8")
            event = add_snapshot(
                self.run,
                completed_path,
                prior.source_root,
                "Synthetic source-bound dossier preparation.",
                {"direction-1": {"status": "affected", "reason": "Dossier supplied."}},
                state["head_sha256"],
            )
            return {
                "status": "complete",
                "spec": copy.deepcopy(request["spec"]),
                "expected_head": event["event_sha256"],
                "continuation_snapshot_sha256": None,
                "receipts": [self.receipt("dossier")],
            }

        handler = DeterministicPreparation(self, prepare)
        result = self.invoke(handler)
        self.assertEqual(result["status"], "needs-workspace")
        self.assertEqual(
            [r["gate"]["status"] for r in handler.calls],
            ["needs-prior-work", "needs-workspace"],
        )
        self.assertEqual(self.adapter.calls, ["research", "extract"])
        self.invoke(handler)
        self.assertEqual(len(handler.calls), 2)
        self.assertEqual(self.adapter.calls, ["research", "extract"])


class PreparationFileBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="preparation-boundary-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def record(self, value):
        path = self.root / "record.json"
        path.write_text(
            json.dumps({**value, "record_sha256": canonical_hash(value)}),
            encoding="utf-8",
        )
        return path

    def test_bounded_regular_record_and_receipt_are_accepted(self):
        value = {"bounded": "ordinary metadata"}
        path = self.record(value)
        self.assertEqual(preparation._read(path), value)
        preparation._receipts(
            [
                {
                    "path": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            ]
        )

    def test_oversized_valid_record_is_rejected_before_json_decode(self):
        path = self.record({"padding": "x" * (4 * 1024 * 1024)})
        with patch.object(preparation.json, "loads", wraps=json.loads) as decode:
            with self.assertRaisesRegex(Stage2Error, "record-bound"):
                preparation._read(path)
        decode.assert_not_called()

    def test_oversized_correctly_hashed_receipt_is_rejected(self):
        path = self.root / "receipt.json"
        path.write_bytes(b"x" * (4 * 1024 * 1024 + 1))
        reference = {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        with self.assertRaisesRegex(Stage2Error, "record-bound"):
            preparation._receipts([reference])

    def test_ancestor_reparse_record_and_receipt_rejected_before_read(self):
        path = self.record({"ordinary": "metadata"})
        reference = {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        original = os.lstat

        def reparse_ancestor(candidate, *args, **kwargs):
            info = original(candidate, *args, **kwargs)
            if Path(candidate).absolute() == self.root:
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            return info

        with patch("stage1_deliverable.common.os.lstat", side_effect=reparse_ancestor):
            with self.assertRaisesRegex(Stage2Error, "linked"):
                preparation._read(path)
            with self.assertRaisesRegex(Stage2Error, "linked"):
                preparation._receipts([reference])

    def test_real_ancestor_link_or_windows_junction_is_rejected(self):
        from research_workspace_native.project_stage2_controller import (
            _guard as driver_guard,
        )

        target, linked = self.root / "physical", self.root / "linked"
        target.mkdir()
        preparation._write(target / "record.json", {"ordinary": "metadata"})
        if os.name == "nt":
            from _winapi import CreateJunction

            CreateJunction(str(target), str(linked))
            self.addCleanup(linked.rmdir)
            self.assertTrue(os.lstat(linked).st_file_attributes & 0x400)
        else:
            linked.symlink_to(target, target_is_directory=True)
            self.addCleanup(linked.unlink)
        alias = linked / "record.json"
        with self.assertRaisesRegex(Stage2Error, "linked"):
            preparation._read(alias)
        with self.assertRaisesRegex(Stage2Error, "linked"):
            preparation._receipts(
                [
                    {
                        "path": str(alias),
                        "sha256": hashlib.sha256(
                            (target / "record.json").read_bytes()
                        ).hexdigest(),
                    }
                ]
            )
        with self.assertRaisesRegex(Stage2Error, "linked"):
            driver_guard(alias)
        self.assertTrue((target / "record.json").is_file())

    def test_entry_reparse_ancestor_rejected_before_workflow_resolve(self):
        original = os.lstat

        def reparse_ancestor(candidate, *args, **kwargs):
            info = original(candidate, *args, **kwargs)
            if Path(candidate).absolute() == self.root:
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            return info

        with (
            patch("stage1_deliverable.common.os.lstat", side_effect=reparse_ancestor),
            patch.object(preparation, "inspect_workflow") as inspect,
        ):
            with self.assertRaisesRegex(Stage2Error, "linked"):
                preparation.run_with_preparation(
                    None,
                    self.root / "workflow",
                    self.root / "controller",
                    "a" * 64,
                    {"workspaces": {}},
                    None,
                )
        inspect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
