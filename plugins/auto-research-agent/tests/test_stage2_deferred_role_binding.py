"""Deferred Stage 2 role binding regressions with synthetic execution only."""

# ruff: noqa: E402 -- load repository CLI and existing controlled fixtures.

import copy
import hashlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "cli"))

from stage2_common import Stage2Error
from stage2_live import environment
from stage2_live.controller import _action_settings, _settings_binding
from stage2_workflow.store import inspect_workflow
import test_stage2_controller as controller_fixtures
from test_stage2_controller import SyntheticAdapter
from test_stage2_named_policy import _config
from test_stage2_role_policy_controller import _root_policy


class DeferredRoleBindingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = controller_fixtures.Stage2ControllerTests(
            methodName="test_complete_pipeline_replays_without_new_calls_and_awaits_human"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        environment_root = tempfile.TemporaryDirectory()
        self.addCleanup(environment_root.cleanup)
        self.environment_root = Path(environment_root.name).resolve()
        self.spec = copy.deepcopy(self.fixture.spec)
        self.spec.update(
            schema_version="1.2.0",
            execution_policies={},
            execution_preflights={},
            execution_inventories={},
        )
        codex = self.fixture.root / "synthetic-codex.exe"
        codex.write_bytes(b"synthetic runtime fixture; never executed")
        self.spec["native"]["codex"] = str(codex)
        shared_config = self.environment_root / "shared-config.json"
        shared_config.write_bytes(b'{"controlled":true}\n')
        self.spec["native"]["config_bindings"] = {"shared": str(shared_config)}
        self.spec["preflight"] = {"synthetic": True}
        original_keys = tuple(self.spec["workspaces"])
        self.spec["workspaces"] = {}
        for key in ("research", "extractor"):
            self._add_environment(key)
        self.deferred = tuple(
            key for key in original_keys if key not in self.spec["workspaces"]
        )

    def _add_environment(self, key, row=None):
        index = len(self.spec["workspaces"])
        safe = key.replace(":", "-")
        row = row or {
            "home": str(self.environment_root / f"{safe}-home-{index}"),
            "workspace": str(self.environment_root / f"{safe}-workspace-{index}"),
        }
        home, workspace = Path(row["home"]), Path(row["workspace"])
        home.mkdir(parents=True, exist_ok=True)
        workspace.mkdir(parents=True, exist_ok=True)
        telemetry = self.environment_root / f"{safe}-telemetry-{index}"
        capture_root = self.environment_root / f"{safe}-captures-{index}"
        raw = _config(
            workspace,
            home,
            telemetry,
            capture_root,
            model="synthetic-model",
            reasoning="medium",
        )
        (home / "config.toml").write_bytes(raw)
        env_key = environment.environment_key(home, workspace)
        self.spec["workspaces"][key] = {
            "home": str(home),
            "workspace": str(workspace),
        }
        self.spec["execution_policies"][env_key] = _root_policy(
            raw, telemetry, capture_root
        )
        self.spec["execution_preflights"][env_key] = {
            "synthetic": True,
            "inventory_receipt": {"environment": key},
        }

    def _add_deferred(self):
        for key in self.deferred:
            self._add_environment(key)

    def test_added_roles_resume_without_reexecuting_completed_units(self):
        adapter = SyntheticAdapter()
        first = self.fixture.run_controller(adapter, spec=self.spec)
        self.assertEqual(first["status"], "needs-workspace")
        self.assertEqual(adapter.calls, ["research", "extract"])
        self._add_deferred()
        resumed = self.fixture.run_controller(adapter, spec=self.spec)
        self.assertEqual(resumed["status"], "awaiting-human")
        self.assertTrue(all(row["replayed"] for row in resumed["units"][:2]))
        completed_calls = list(adapter.calls)
        self._add_environment("future:unused")
        replayed = self.fixture.run_controller(adapter, spec=self.spec)
        self.assertTrue(all(row["replayed"] for row in replayed["units"]))
        self.assertEqual(adapter.calls, completed_calls)

    def test_used_environment_tamper_rejects_replay_without_new_calls(self):
        adapter = SyntheticAdapter()
        self.fixture.run_controller(adapter, spec=self.spec)
        calls = list(adapter.calls)
        research = self.spec["workspaces"]["research"]
        profile = Path(research["home"]) / "config.toml"
        raw = profile.read_bytes() + b"# changed used environment\n"
        profile.write_bytes(raw)
        key = environment.environment_key(research["home"], research["workspace"])
        self.spec["execution_policies"][key]["config_sha256"] = hashlib.sha256(
            raw
        ).hexdigest()
        with self.assertRaisesRegex(Stage2Error, "action-binding-changed"):
            self.fixture.run_controller(adapter, spec=self.spec)
        self.assertEqual(adapter.calls, calls)

    def test_missing_added_role_proof_and_cross_role_alias_fail_before_calls(self):
        self._add_deferred()
        missing = copy.deepcopy(self.spec)
        missing["execution_preflights"].pop(
            next(reversed(missing["execution_preflights"]))
        )
        with self.assertRaisesRegex(Stage2Error, "policy-environments-mismatch"):
            self.fixture.run_controller(SyntheticAdapter(), spec=missing)
        self.assertEqual(inspect_workflow(self.fixture.run)["actions"], {})

        aliased = copy.deepcopy(self.spec)
        aliased["workspaces"]["future:alias"] = {
            "home": str(Path(aliased["workspaces"]["research"]["home"]) / "nested"),
            "workspace": str(self.fixture.root / "future-alias-workspace"),
        }
        with self.assertRaisesRegex(Stage2Error, "workspace-not-isolated"):
            self.fixture.run_controller(SyntheticAdapter(), spec=aliased)

    def test_v12_policy_selected_and_review_resolution_bind_actual_roles(self):
        self._add_deferred()
        research = self.spec["workspaces"]["research"]
        selected = environment.native_for_environment(
            self.spec, research["home"], research["workspace"]
        )
        key = environment.environment_key(research["home"], research["workspace"])
        self.assertEqual(
            selected["policy_bindings"], self.spec["execution_policies"][key]
        )

        result = self.fixture.run_controller(SyntheticAdapter(), spec=self.spec)
        state = inspect_workflow(
            self.fixture.run, expected_head=result["workflow_head_sha256"]
        )
        review = next(
            row
            for row in state["actions"].values()
            if row["request"]["action_kind"] == "stage2-independent-review"
        )
        resolution = next(
            row
            for row in state["actions"].values()
            if row["request"]["action_kind"] == "stage2-review-reconciliation"
        )
        self.assertEqual(
            set(review["request"]["settings"]["environment_bindings"]),
            {"extractor", "review:candidate-1:challenger"},
        )
        self.assertEqual(
            set(resolution["request"]["settings"]["environment_bindings"]),
            {"extractor", "resolution:candidate-1"},
        )

    def test_v11_remains_global_and_rejects_map_change(self):
        self._add_deferred()
        self.spec["schema_version"] = "1.1.0"
        adapter = SyntheticAdapter()
        self.fixture.run_controller(adapter, spec=self.spec)
        calls = list(adapter.calls)
        self._add_environment("future:unused")
        with self.assertRaisesRegex(Stage2Error, "action-binding-changed"):
            self.fixture.run_controller(adapter, spec=self.spec)
        self.assertEqual(adapter.calls, calls)

    def test_native_action_settings_ignore_unused_roles_and_bind_used_inputs(self):
        self.spec["preflight"] = {
            "report": {"status": "controlled-fixture"},
            "capture_dir": str(self.environment_root / "primary-preflight"),
            "receipt": "a" * 64,
            "probe_spec": {"schema_version": "1.2.0"},
            "inventory_receipt": {"primary": "controlled-fixture"},
        }
        adapter = SimpleNamespace(synthetic=False)

        def action_settings(spec, role):
            return _action_settings(spec, _settings_binding(spec, adapter), [role])

        research_before = action_settings(self.spec, "research")
        extractor_before = action_settings(self.spec, "extractor")
        self._add_environment("future:unused")
        self.spec["execution_inventories"]["future-thread"] = {
            "entries": {"unused": True}
        }
        self.assertEqual(action_settings(self.spec, "research"), research_before)
        self.assertEqual(action_settings(self.spec, "extractor"), extractor_before)

        research = self.spec["workspaces"]["research"]
        env_key = environment.environment_key(research["home"], research["workspace"])
        changed = copy.deepcopy(self.spec)
        changed["execution_preflights"][env_key]["inventory_receipt"] = {
            "environment": "changed-used-proof"
        }
        self.assertNotEqual(action_settings(changed, "research"), research_before)

        runtime = Path(self.spec["native"]["codex"])
        runtime_before = runtime.read_bytes()
        runtime.write_bytes(runtime_before + b" changed-runtime")
        try:
            self.assertNotEqual(action_settings(self.spec, "research"), research_before)
        finally:
            runtime.write_bytes(runtime_before)

        shared = Path(self.spec["native"]["config_bindings"]["shared"])
        shared_before = shared.read_bytes()
        shared.write_bytes(shared_before + b" ")
        try:
            self.assertNotEqual(action_settings(self.spec, "research"), research_before)
        finally:
            shared.write_bytes(shared_before)

        profile = Path(research["home"]) / "config.toml"
        profile_before = profile.read_bytes()
        policy_before = copy.deepcopy(self.spec["execution_policies"][env_key])
        for label, model, telemetry, capture_root in (
            (
                "model",
                "changed-model",
                Path(policy_before["telemetry_path"]),
                Path(policy_before["capture_root"]),
            ),
            (
                "policy",
                "synthetic-model",
                self.environment_root / "changed-telemetry",
                self.environment_root / "changed-capture-root",
            ),
        ):
            with self.subTest(label=label):
                changed = copy.deepcopy(self.spec)
                changed["native"]["model"] = model
                raw = _config(
                    Path(research["workspace"]),
                    Path(research["home"]),
                    telemetry,
                    capture_root,
                    model=model,
                    reasoning="medium",
                )
                profile.write_bytes(raw)
                changed["execution_policies"][env_key] = _root_policy(
                    raw, telemetry, capture_root
                )
                try:
                    self.assertNotEqual(
                        action_settings(changed, "research"), research_before
                    )
                finally:
                    profile.write_bytes(profile_before)


if __name__ == "__main__":
    unittest.main()
