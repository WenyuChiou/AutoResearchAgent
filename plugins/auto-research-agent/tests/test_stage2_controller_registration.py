# ruff: noqa: E402 -- exercise repository CLI without installation.
"""Synthetic interruption tests; no model or native research is executed."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "cli"))
sys.path.insert(0, str(HERE))

from stage2_common import Stage2Error
import test_stage2_controller as controller_fixtures
from test_stage2_failure_state import saved_failure
from stage2_fixture_helpers import write_stage2_fixture
from stage2_live.controller import _ProductionAdapter, _execute_unit
from stage2_workflow.store import initialize_workflow, inspect_workflow


class ControllerRegistrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        sources = self.root / "sources"
        packet = write_stage2_fixture(sources, candidate_count=1)
        packet_path = self.root / "packet.json"
        packet_path.write_text(json.dumps(packet), encoding="utf-8")
        self.run = self.root / "workflow"
        initialize_workflow(
            packet_path,
            sources,
            self.run,
            {"model": "synthetic", "reasoning": "medium"},
            {"path": "policy.json", "sha256": "a" * 64},
        )
        self.base = inspect_workflow(self.run)["latest_snapshot"]["event"]["payload"][
            "snapshot_sha256"
        ]
        self.output = self.root / "controller"
        self.value = {"synthetic": True, "saved_output": "accepted model bytes"}

    def unit(self, invoke):
        return _execute_unit(
            self.run,
            self.output,
            "saved-unit",
            "synthetic-interruption",
            {"input": "same"},
            {"mode": "synthetic-test-only"},
            self.base,
            invoke,
        )

    def test_completed_output_survives_registration_failure_without_dispatch_on_resume(
        self,
    ):
        invoke = Mock(return_value=self.value)
        with patch(
            "stage2_live.controller.finish_action",
            side_effect=Stage2Error("injected-registration-interruption"),
        ):
            result = self.unit(invoke)
        self.assertEqual(result["state"], "needs-recovery")
        self.assertEqual(result["recovery_boundary"], "registration")
        saved = self.output / "results" / "saved-unit.json"
        before = saved.read_bytes()
        self.assertEqual(json.loads(before), self.value)
        self.assertIsNone(inspect_workflow(self.run)["actions"]["saved-unit"]["result"])
        again = self.unit(invoke)
        self.assertEqual(again["state"], "needs-recovery")
        self.assertEqual(saved.read_bytes(), before)
        invoke.assert_called_once()
        failure = self.output / "results" / "saved-unit.registration-failure.json"
        self.assertIn(
            "injected-registration-interruption", failure.read_text(encoding="utf-8")
        )

    def test_failed_dispatch_remains_failed_and_cannot_reexecute(self):
        invoke = Mock(side_effect=RuntimeError("HTTP 429 Too Many Requests"))
        result = self.unit(invoke)
        self.assertEqual(result["terminal_status"], "failed")
        self.assertEqual(result["failure_class"], "rate-limit")
        state = inspect_workflow(self.run)
        self.assertEqual(state["actions"]["saved-unit"]["result"]["status"], "failed")
        self.assertEqual(self.unit(invoke)["state"], "needs-recovery")
        invoke.assert_called_once()

    def test_subprocess_deadline_is_retained_and_resume_does_not_dispatch(self):
        invoke = Mock(side_effect=subprocess.TimeoutExpired(["synthetic"], 1))
        result = self.unit(invoke)
        self.assertEqual(result["failure_class"], "timeout")
        original_head = inspect_workflow(self.run)["head_sha256"]
        again = self.unit(invoke)
        self.assertEqual(again["failure_class"], "timeout")
        self.assertEqual(inspect_workflow(self.run)["head_sha256"], original_head)
        invoke.assert_called_once()

    def test_failed_native_capture_preserves_deadline_witness_through_controller(self):
        workspace = self.root / "native-workspace"
        home = self.root / "native-home"
        workspace.mkdir()
        home.mkdir()
        native = {
            "codex": "synthetic-no-execution",
            "model": "synthetic",
            "reasoning": "medium",
            "config_bindings": {},
            "policy_bindings": {},
        }
        capture = {
            "status": "failed",
            "record_sha256_receipt": "b" * 64,
            "exception": {
                "type": "TimeoutExpired",
                "message": "real deadline",
                "cleanup_report": {"reap_status": "complete", "errors": []},
            },
        }
        captured = Mock(return_value=capture)
        verify_complete = Mock()
        with patch.multiple(
            "stage2_live.controller",
            preflight_for_environment=Mock(return_value={}),
            native_for_environment=Mock(return_value=native),
            verify_environment_start=Mock(return_value={}),
            admit_verified_preflight_workspace=Mock(),
            capture_native=captured,
            verify_environment_capture=verify_complete,
        ):
            result = self.unit(
                lambda: _ProductionAdapter._capture(
                    {"prompt": "synthetic"},
                    self.root / "sources",
                    {"workspace": workspace, "home": home},
                    {},
                    self.root / "fake-capture",
                )
            )
        self.assertEqual(result["failure_class"], "timeout")
        self.assertEqual(result["failure_observation"]["cleanup_status"], "complete")
        self.assertEqual(
            result["failure_observation"]["capture_record_sha256"], "b" * 64
        )
        captured.assert_called_once()
        verify_complete.assert_not_called()

    def test_native_401_and_429_survive_saved_capture_bridge_without_dispatch_again(
        self,
    ):
        for code, expected in [(401, "authentication"), (429, "rate-limit")]:
            root = self.root / str(code)
            workspace, home = root / "workspace", root / "home"
            workspace.mkdir(parents=True)
            home.mkdir()
            native = {
                "codex": "synthetic",
                "model": "synthetic",
                "reasoning": "medium",
                "config_bindings": {},
                "policy_bindings": {},
            }

            def capture(**arguments):
                return saved_failure(
                    Path(arguments["output_dir"]),
                    [
                        {
                            "type": "turn.failed",
                            "error": {"message": f"HTTP {code} rejected"},
                        }
                    ],
                )

            captured = Mock(side_effect=capture)
            with patch.multiple(
                "stage2_live.controller",
                preflight_for_environment=Mock(return_value={}),
                native_for_environment=Mock(return_value=native),
                verify_environment_start=Mock(return_value={}),
                admit_verified_preflight_workspace=Mock(),
                capture_native=captured,
                verify_environment_capture=Mock(),
            ):

                def invoke():
                    return _ProductionAdapter._capture(
                        {"prompt": "synthetic"},
                        self.root / "sources",
                        {"workspace": workspace, "home": home},
                        {},
                        root / "capture",
                    )

                arguments = (
                    self.run,
                    self.output,
                    f"native-{code}",
                    "native-failure-synthetic",
                    {"code": code},
                    {},
                    self.base,
                    invoke,
                )
                first = _execute_unit(*arguments)
                second = _execute_unit(*arguments)
            self.assertEqual(first["failure_class"], expected)
            self.assertEqual(second["failure_class"], expected)
            self.assertEqual(
                first["failure_observation"]["provider_observation"]["state"],
                "verified",
            )
            captured.assert_called_once()

    def test_public_controller_persists_current_failure_head_on_initial_dispatch(self):
        fixture = controller_fixtures.Stage2ControllerTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        research = Mock(side_effect=subprocess.TimeoutExpired(["synthetic"], 1))
        adapter = controller_fixtures.SyntheticAdapter()
        adapter.research = research
        first = fixture.run_controller(adapter)
        state = inspect_workflow(fixture.run)
        self.assertEqual(first["status"], "needs-recovery")
        self.assertEqual(first["workflow_head_sha256"], state["head_sha256"])
        self.assertEqual(first["units"][0]["failure_class"], "timeout")
        again = fixture.run_controller(adapter)
        self.assertEqual(again["workflow_head_sha256"], first["workflow_head_sha256"])
        self.assertEqual(
            again["controller_manifest_sha256"], first["controller_manifest_sha256"]
        )
        research.assert_called_once()


if __name__ == "__main__":
    unittest.main()
