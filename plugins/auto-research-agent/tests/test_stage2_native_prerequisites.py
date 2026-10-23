"""Synthetic transport tests; no native/model permission or research acceptance."""

# ruff: noqa: E402 -- use the repository's authored offline source fixture.
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "cli")]
import test_stage2_prior_work as prior_fixture
from stage2_common import Stage2Error, canonical_hash, source_set_hash
from stage2_live.native_prerequisites import (
    NativePrerequisiteHandler,
    load_native_prerequisites,
)
from stage2_workflow import initialize_workflow, inspect_workflow


class NativePrerequisiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prior = prior_fixture.Stage2PriorWorkTests()
        cls.prior.setUp()
        cls.addClassCleanup(cls.prior.doCleanups)

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="native-prerequisite-contract-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.packet = deepcopy(self.prior.packet)
        self.packet["prior_work_reviews"] = []
        source = self.root / "input.json"
        source.write_text(json.dumps(self.packet), encoding="utf-8")
        self.workflow = self.root / "workflow"
        initialize_workflow(
            source,
            self.prior.source_root,
            self.workflow,
            {"model": "synthetic-model", "reasoning": "medium"},
            {"path": "synthetic-only.json", "sha256": "a" * 64},
            canonical_hash(self.packet),
        )
        self.state = inspect_workflow(self.workflow)
        self.spec = {
            "native": {
                "codex": "synthetic-transport-not-an-executable",
                "model": "synthetic-model",
                "reasoning": "medium",
                "extraction_policy": {
                    "timeout_seconds": 600,
                    "evaluator_bundle_sha256": "d" * 64,
                },
            },
            "workspaces": {},
            "execution_policies": {},
            "execution_preflights": {},
            "execution_inventories": {},
        }
        self.config = {
            "kind": "Stage2NativePrerequisiteConfiguration",
            "schema_version": "1.0.0",
            "native_sha256": canonical_hash(self.spec["native"]),
            "output_root": str(self.root / "private-preparation"),
            "admission_context": {
                "status": "admitted",
                "mode": "explicit-synthetic-transport-only",
                "execution_policy_sha256": canonical_hash(self.spec["native"]),
                "runtime_sha256": "b" * 64,
                "deadline_unix": time.time() + 1200,
                "remaining_budget": {"native_captures": 1},
            },
            "workspace_templates": {},
            "prior_work": {
                "spec": deepcopy(self.spec),
                "paths": {
                    "home": str(self.root / "synthetic-home"),
                    "workspace": str(self.root / "synthetic-workspace"),
                },
            },
        }

    def handler(self):
        return NativePrerequisiteHandler(self.workflow, self.spec, self.config)

    def request(self, handler, *, gate="needs-prior-work"):
        return {
            "handler_identity": handler.identity,
            "spec": deepcopy(self.spec),
            "admission_context": deepcopy(handler.admission_context),
            "expected_head": self.state["head_sha256"],
            "snapshot_sha256": self.state["latest_snapshot"]["event"]["payload"][
                "snapshot_sha256"
            ],
            "gate": {
                "status": gate,
                "prior_work_completion": {"missing_candidate_ids": ["direction-1"]},
                "required_workspace_keys": ["review-slot:0:challenger"],
            },
        }

    def captured(
        self, *, executed=False, query="bounded precedent query", event_query=None
    ):
        packet = self.state["latest_snapshot"]["packet"]
        review = self.prior.review(status="partial")
        review["candidate_sha256"] = canonical_hash(packet["candidates"][-1])
        review["source_set_sha256"] = source_set_hash(packet)
        review["searches"] = [
            dict(
                search_id="search-1",
                need="Check nearest work.",
                query=query,
                status="executed" if executed else "planned",
                tool_ref=None,
                raw_path=None,
                raw_sha256=None,
                outcome="unknown",
                work_refs=[],
            )
        ]
        final = json.dumps([review])
        stdout = json.dumps(
            {"synthetic_test_only": True, "original_query": event_query or query}
        ).encode()

        def capture(task, source_root, paths, spec, output):
            output.mkdir()
            (output / "stdout.jsonl").write_bytes(stdout)
            (output / "final.txt").write_text(final, encoding="utf-8")
            return {
                "status": "complete",
                "record_sha256_receipt": "c" * 64,
                "archived_files": {
                    "stdout.jsonl": hashlib.sha256(stdout).hexdigest(),
                    "final.txt": hashlib.sha256(final.encode()).hexdigest(),
                },
                "event_summary": {
                    "final_output": final,
                    "tool_events": [{"query": event_query or query}],
                },
            }

        return capture

    def test_missing_admission_returns_readable_gate_without_dispatch(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from stage2_live.controller import _execute_unit
        from stage2_live.execution_admission import AdmittedAdapter
        from stage2_live.preparation import run_with_preparation

        self.spec["base_snapshot_sha256"] = self.state["latest_snapshot"]["event"][
            "payload"
        ]["snapshot_sha256"]
        for index, admission in enumerate((None, {})):
            with self.subTest(admission=admission):
                core = self.root / ("missing-admission-" + str(index))
                dispatch = Mock(side_effect=AssertionError("must not dispatch"))
                adapter = SimpleNamespace(synthetic=False, research=dispatch)
                handler = SimpleNamespace(
                    identity="synthetic-missing-admission",
                    admission_context=admission,
                    prepare=Mock(side_effect=AssertionError("must not prepare")),
                )

                def run(head, spec):
                    guard = AdmittedAdapter(adapter, handler, spec, core)
                    action = _execute_unit(
                        self.workflow,
                        core,
                        "missing-admission-action-" + str(index),
                        "stage2-ideation-native",
                        {"synthetic_test_only": True},
                        {"model": "synthetic-model", "reasoning": "medium"},
                        spec["base_snapshot_sha256"],
                        lambda: guard.research({"output": str(core / "native")}),
                    )
                    self.assertEqual(action["state"], "needs-recovery")
                    self.assertEqual(action["terminal_status"], "failed")
                    self.assertIn("original-admission-expired", action["error"])
                    return {
                        "status": "needs-prior-work",
                        "workflow_head_sha256": inspect_workflow(self.workflow)[
                            "head_sha256"
                        ],
                    }

                result = run_with_preparation(
                    run,
                    self.workflow,
                    core,
                    inspect_workflow(self.workflow)["head_sha256"],
                    self.spec,
                    handler,
                )
                self.assertEqual(
                    result["preparation"]["status"],
                    "unavailable-preparation-admission",
                )
                dispatch.assert_not_called()
                handler.prepare.assert_not_called()
                self.assertFalse(list(core.rglob("*.intent.json")))
                self.assertFalse((core / "execution_admission").exists())

    def test_replayed_core_before_first_preparation_intent_keeps_exhausted_budget(self):
        from types import SimpleNamespace
        from stage2_live.controller import _execute_unit
        from stage2_live.execution_admission import AdmittedAdapter
        import stage2_live.preparation as preparation_module

        self.spec["base_snapshot_sha256"] = self.state["latest_snapshot"]["event"][
            "payload"
        ]["snapshot_sha256"]
        self.config["admission_context"]["deadline_unix"] = time.time() + 10000
        self.config["admission_context"]["remaining_budget"] = {
            "native_captures": 1,
            "model_calls": 4,
        }
        core = self.root / "core-controller"
        calls = []
        adapter = SimpleNamespace(synthetic=False)
        for operation in ("research", "extract"):
            setattr(
                adapter,
                operation,
                lambda context, op=operation: (
                    calls.append(op) or {"synthetic_test_only": True, "operation": op}
                ),
            )

        def controller(handler):
            def run(head, spec):
                guard = AdmittedAdapter(adapter, handler, spec, core)
                for operation, kind in (
                    ("research", "stage2-ideation-native"),
                    ("extract", "stage2-ideation-extraction"),
                ):
                    result = _execute_unit(
                        self.workflow,
                        core,
                        "synthetic-core-" + operation,
                        kind,
                        {"synthetic_test_only": True},
                        {"model": "synthetic-model", "reasoning": "medium"},
                        self.spec["base_snapshot_sha256"],
                        lambda op=operation: getattr(guard, op)(
                            {"output": str(core / op)}
                        ),
                    )
                    self.assertEqual(result["state"], "complete")
                return {
                    "status": "needs-prior-work",
                    "workflow_head_sha256": inspect_workflow(self.workflow)[
                        "head_sha256"
                    ],
                    "prior_work_completion": {"missing_candidate_ids": ["direction-1"]},
                }

            return run

        original_write = preparation_module._write

        def interrupt_before_intent(path, value):
            if path.name == "00.intent.json":
                raise KeyboardInterrupt(
                    "synthetic interruption before prerequisite intent"
                )
            return original_write(path, value)

        handler = self.handler()
        with patch.object(
            preparation_module, "_write", side_effect=interrupt_before_intent
        ):
            with self.assertRaises(KeyboardInterrupt):
                preparation_module.run_with_preparation(
                    controller(handler),
                    self.workflow,
                    core,
                    self.state["head_sha256"],
                    self.spec,
                    handler,
                )
        self.assertEqual(calls, ["research", "extract"])
        self.assertFalse(list(core.rglob("*.intent.json")))
        self.assertFalse(Path(self.config["output_root"]).exists())
        reopened = self.handler()
        with patch(
            "stage2_live.native_prerequisites._ProductionAdapter._capture",
            side_effect=RuntimeError("synthetic transport must not be dispatched"),
        ) as capture:
            result = preparation_module.run_with_preparation(
                controller(reopened),
                self.workflow,
                core,
                inspect_workflow(self.workflow)["head_sha256"],
                self.spec,
                reopened,
            )
        capture.assert_not_called()
        self.assertEqual(calls, ["research", "extract"])
        self.assertEqual(
            reopened.admission_context["remaining_budget"],
            {"native_captures": 0, "model_calls": 0},
        )
        self.assertEqual(result["preparation"]["status"], "failed")
        self.assertIn("native-budget-unavailable", result["preparation"]["reason"])

    def test_each_guard_byte_change_invalidates_provider_reopening(self):
        import stage2_live.preparation as preparation_module
        from stage2_live.preparation import _write

        original = Path(preparation_module.__file__)
        for index, name in enumerate(("preparation.py", "execution_admission.py")):
            with self.subTest(helper=name):
                self.config["output_root"] = str(
                    self.root / ("provider-pins-" + str(index))
                )
                handler = self.handler()
                handler.output.mkdir()
                _write(handler.output / "provider-binding.json", handler.binding)
                copies = self.root / ("changed-helper-" + str(index))
                copies.mkdir()
                for file in ("preparation.py", "execution_admission.py"):
                    (copies / file).write_bytes(original.with_name(file).read_bytes())
                with (copies / name).open("ab") as stream:
                    stream.write(b"\n# synthetic byte-change probe; never executed\n")
                with patch.object(
                    preparation_module, "__file__", str(copies / "preparation.py")
                ):
                    with self.assertRaisesRegex(
                        Stage2Error, "provider-binding-differs"
                    ):
                        self.handler()

    def test_external_hash_refuses_before_any_provider_or_output(self):
        path = self.root / "configuration.json"
        path.write_text(json.dumps(self.config), encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "configuration-hash"):
            load_native_prerequisites(
                path, "0" * 64, workflow=self.workflow, spec=self.spec
            )
        self.assertFalse(Path(self.config["output_root"]).exists())

    def test_output_cannot_overlap_protected_workflow(self):
        self.config["output_root"] = str(self.workflow / "bad-output")
        with self.assertRaisesRegex(Stage2Error, "output-collision"):
            self.handler()

    def test_missing_proved_workspace_template_preserves_gate_without_native(self):
        handler = self.handler()
        with patch(
            "stage2_live.native_prerequisites._ProductionAdapter._capture"
        ) as capture:
            result = handler.prepare(self.request(handler, gate="needs-workspace"))
        capture.assert_not_called()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(
            inspect_workflow(self.workflow)["head_sha256"], self.state["head_sha256"]
        )

    def test_unknown_native_budget_or_insufficient_original_deadline_never_dispatches(
        self,
    ):
        for change in ("budget", "deadline"):
            with self.subTest(change=change):
                handler = self.handler()
                if change == "budget":
                    handler.admission_context["remaining_budget"]["native_captures"] = 0
                else:
                    handler.admission_context["deadline_unix"] = time.time() + 1
                with patch(
                    "stage2_live.native_prerequisites._ProductionAdapter._capture"
                ) as capture:
                    with self.assertRaises(Stage2Error):
                        handler.prepare(self.request(handler))
                capture.assert_not_called()
        self.assertFalse(Path(self.config["output_root"]).exists())

    def test_failed_transport_reservation_reopens_without_another_capture(self):
        handler = self.handler()
        with patch(
            "stage2_live.native_prerequisites._ProductionAdapter._capture",
            side_effect=OSError("explicit synthetic transport failure"),
        ) as capture:
            with self.assertRaises(OSError):
                handler.prepare(self.request(handler))
        self.assertEqual(capture.call_count, 1)
        reopened = self.handler()
        self.assertEqual(
            reopened.admission_context["remaining_budget"]["native_captures"], 0
        )
        with patch(
            "stage2_live.native_prerequisites._ProductionAdapter._capture"
        ) as execute:
            with self.assertRaisesRegex(Stage2Error, "native-budget"):
                reopened.prepare(self.request(reopened))
        execute.assert_not_called()

    def test_actual_snapshot_acceptance_of_partial_dossier_preserves_unknown_and_input(
        self,
    ):
        handler = self.handler()
        with (
            patch(
                "stage2_live.native_prerequisites._ProductionAdapter._capture",
                side_effect=self.captured(),
            ) as capture,
            patch("stage2_live.native_prerequisites.verify_capture") as authenticate,
        ):
            result = handler.prepare(self.request(handler))
        self.assertEqual(capture.call_count, 1)
        authenticate.assert_called_once()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["usage"]["native_captures"], 1)
        self.assertIsNone(result["usage"]["model_calls"])
        current = inspect_workflow(self.workflow)
        self.assertEqual(len(current["snapshots"]), 2)
        self.assertEqual(
            current["latest_snapshot"]["packet"]["prior_work_reviews"][0][
                "review_status"
            ],
            "partial",
        )
        self.assertEqual(
            self.prior.packet["prior_work_reviews"][0]["review_status"],
            "bounded-complete",
        )
        self.assertEqual(
            handler.admission_context["remaining_budget"]["native_captures"], 0
        )

    def test_query_prefix_cannot_authenticate_a_different_search(self):
        handler = self.handler()
        with (
            patch(
                "stage2_live.native_prerequisites._ProductionAdapter._capture",
                side_effect=self.captured(
                    executed=True,
                    query="bounded",
                    event_query="bounded precedent query",
                ),
            ),
            patch("stage2_live.native_prerequisites.verify_capture"),
        ):
            with self.assertRaisesRegex(Stage2Error, "search-not-in-original"):
                handler.prepare(self.request(handler))
        self.assertEqual(
            inspect_workflow(self.workflow)["head_sha256"], self.state["head_sha256"]
        )


if __name__ == "__main__":
    unittest.main()
