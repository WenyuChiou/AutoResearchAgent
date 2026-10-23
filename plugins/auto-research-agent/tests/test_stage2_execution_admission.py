"""Offline guards: capacity reservations are not real model usage evidence."""

from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage2_common import Stage2Error, canonical_hash
from stage2_live.execution_admission import AdmittedAdapter


class ExecutionAdmissionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="stage2-original-budget-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.spec = {
            "native": {
                "extraction_policy": {
                    "timeout_seconds": 600,
                    "evaluator_bundle_sha256": "a" * 64,
                }
            }
        }
        self.context = dict(
            status="admitted",
            mode="offline-guard-only",
            runtime_sha256="b" * 64,
            execution_policy_sha256=canonical_hash(self.spec["native"]),
            deadline_unix=time.time() + 10000,
            remaining_budget=dict(native_captures=2, model_calls=4),
        )
        self.calls = []
        self.adapter = SimpleNamespace(
            synthetic=False,
            research=lambda c: self.calls.append(c),
            extract=lambda c: self.calls.append(c),
        )
        self.handler = SimpleNamespace(admission_context=deepcopy(self.context))

    def guard(self, handler=None):
        return AdmittedAdapter(
            self.adapter, handler or self.handler, self.spec, self.root
        )

    def test_each_guard_byte_change_invalidates_project_driver_identity(self):
        from unittest.mock import patch
        import stage2_live.preparation as preparation_module
        from research_workspace_native.project_stage2_controller import (
            ProjectStage2ControllerDriver,
        )

        driver = ProjectStage2ControllerDriver(
            None,
            spec=self.spec,
            controller_dir=self.root / "driver",
            delivery_dir=self.root / "delivery",
        )
        original = Path(preparation_module.__file__)
        before = driver._configuration()
        for index, name in enumerate(("preparation.py", "execution_admission.py")):
            with self.subTest(helper=name):
                copies = self.root / ("guard-" + str(index))
                copies.mkdir()
                for file in ("preparation.py", "execution_admission.py"):
                    (copies / file).write_bytes(original.with_name(file).read_bytes())
                with (copies / name).open("ab") as stream:
                    stream.write(b"\n# synthetic byte-change probe; never executed\n")
                with patch.object(
                    preparation_module, "__file__", str(copies / "preparation.py")
                ):
                    self.assertNotEqual(driver._configuration(), before)

    def test_changed_guard_bytes_reject_saved_core_budget_before_replay(self):
        from unittest.mock import patch
        import stage2_live.preparation as preparation_module

        self.guard().research({"output": str(self.root / "reserved-core")})
        original = Path(preparation_module.__file__)
        for index, name in enumerate(("preparation.py", "execution_admission.py")):
            with self.subTest(helper=name):
                copies = self.root / ("ledger-guard-" + str(index))
                copies.mkdir()
                for file in ("preparation.py", "execution_admission.py"):
                    (copies / file).write_bytes(original.with_name(file).read_bytes())
                with (copies / name).open("ab") as stream:
                    stream.write(b"\n# synthetic byte-change probe; never executed\n")
                with patch.object(
                    preparation_module, "__file__", str(copies / "preparation.py")
                ):
                    with self.assertRaisesRegex(Stage2Error, "guard-runtime-differs"):
                        self.guard()
        self.assertEqual(len(self.calls), 1)

    def test_capacity_is_reserved_before_new_call_and_not_actual_usage(self):
        self.guard().extract({"output": str(self.root / "unit-1")})
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(
            self.handler.admission_context["remaining_budget"]["model_calls"], 0
        )
        import json

        record = json.loads(
            next((self.root / "execution_admission").glob("*.json")).read_bytes()
        )
        self.assertIsNone(record["actual_model_calls"])
        self.assertEqual(
            record["capacity_reserved"], {"native_captures": 0, "model_calls": 4}
        )

    def test_expired_whole_deadline_and_missing_capacity_refuse_before_call(self):
        self.handler.admission_context["deadline_unix"] = time.time() + 1
        with self.assertRaisesRegex(Stage2Error, "original-deadline"):
            self.guard().research({"output": str(self.root / "unit-1")})
        self.assertEqual(self.calls, [])
        self.handler.admission_context = deepcopy(self.context)
        del self.handler.admission_context["remaining_budget"]["model_calls"]
        with self.assertRaisesRegex(Stage2Error, "run-budget-exhausted"):
            self.guard().extract({"output": str(self.root / "unit-2")})
        self.assertEqual(self.calls, [])

    def test_reopening_original_budget_does_not_renew_reserved_capacity(self):
        self.guard().extract({"output": str(self.root / "unit-1")})
        original = SimpleNamespace(admission_context=deepcopy(self.context))
        with self.assertRaisesRegex(Stage2Error, "run-budget-exhausted"):
            self.guard(original).extract({"output": str(self.root / "unit-2")})
        self.assertEqual(len(self.calls), 1)

    def test_same_unit_cannot_be_redispatched_after_unknown_outcome(self):
        self.guard().research({"output": str(self.root / "unit-1")})
        with self.assertRaisesRegex(Stage2Error, "outcome-unknown"):
            self.guard().research({"output": str(self.root / "unit-1")})
        self.assertEqual(len(self.calls), 1)
