"""Role policy regressions using explicit synthetic captures and adapters only."""

# ruff: noqa: E402 -- load the repository CLI and existing synthetic test fixtures.

import copy
import hashlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "cli"))

from stage2_common import Stage2Error, canonical_hash
from stage2_live import environment, native, native_policy
from stage2_live.controller import (
    _settings_binding,
    _validate_spec,
    _verify_action_environments,
    verify_controller,
)
import test_stage2_controller as controller_fixtures
from test_stage2_controller import SyntheticAdapter
from test_stage2_named_policy import NAME, _config, _policy


def _root_policy(raw, telemetry, capture_root):
    policy = _policy(raw, telemetry)
    policy.update(schema_version="1.1.0", capture_root=str(capture_root.resolve()))
    return policy


def _runtime(binding):
    policy = binding["policy_bindings"]
    modes = {
        "/": "read",
        binding["workspace"]: "write",
        binding["codex_home"]: "deny",
        policy["telemetry_path"]: "deny",
        policy["capture_root"]: "deny",
    }
    entries = [
        {"path": {"type": "path", "path": path}, "access": mode}
        for path, mode in modes.items()
    ]
    return {
        "active_permission_profile": {"id": policy["name"]},
        "permission_profile": {
            "type": "managed",
            "network": "enabled",
            "file_system": {"type": "restricted", "entries": entries},
        },
        "file_system_sandbox_policy": {
            "kind": "restricted",
            "entries": copy.deepcopy(entries),
        },
        "sandbox_policy": {"type": "workspace-write", "network_access": True},
        "approval_policy": "never",
    }


class CaptureRootPolicyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.home = self.root / "home"
        self.workspace = self.root / "workspace"
        self.telemetry = self.root / "telemetry"
        self.capture_root = self.root / "captures"
        for path in (self.home, self.workspace, self.telemetry):
            path.mkdir()
        self.codex = self.root / "synthetic-codex.exe"
        self.codex.write_bytes(b"explicit synthetic launcher; never executed")
        self.input = self.root / "input.json"
        self.input.write_text("{}\n", encoding="utf-8")
        self.raw = _config(self.workspace, self.home, self.telemetry, self.capture_root)
        (self.home / "config.toml").write_bytes(self.raw)
        self.policy = _root_policy(self.raw, self.telemetry, self.capture_root)
        self.calls = []

    def _binding(self, policy=None):
        return {
            "workspace": str(self.workspace),
            "codex_home": str(self.home),
            "model": "gpt-test",
            "reasoning": "high",
            "policy_bindings": policy or self.policy,
            "codex_profile_config": native._path_binding(self.home / "config.toml"),
        }

    def _args(self, output, policy=None):
        return {
            "codex": self.codex,
            "codex_home": self.home,
            "workspace": self.workspace,
            "prompt": "Explicit synthetic capture fixture.",
            "model": "gpt-test",
            "reasoning": "high",
            "input_bindings": {"brief": self.input},
            "config_bindings": {},
            "policy_bindings": policy or self.policy,
            "output_dir": output,
        }

    def _synthetic_runner(self, command, **kwargs):
        self.calls.append(command)
        Path(command[command.index("-o") + 1]).write_text(
            "Explicit synthetic answer.\n", encoding="utf-8"
        )
        return SimpleNamespace(
            stdout=b'{"type":"thread.started","thread_id":"synthetic-only"}\n'
            b'{"type":"item.completed","item":{"type":"agent_message","text":"Explicit synthetic answer."}}\n'
            b'{"type":"turn.completed","usage":{"output_tokens":2}}\n',
            stderr=b"",
            returncode=0,
        )

    def test_two_fresh_captures_share_frozen_profile_and_resume_without_execution(self):
        captures = []
        for name in ("first", "second"):
            output = self.capture_root / name
            captured = native.capture_native(
                **self._args(output), process_runner=self._synthetic_runner
            )
            captures.append((output, captured))
            self.assertEqual(
                captured["stable_request_binding"]["policy_bindings"], self.policy
            )
            self.assertEqual(
                (output / "archive/profile-config.toml").read_bytes(), self.raw
            )
        self.assertEqual((self.home / "config.toml").read_bytes(), self.raw)
        self.assertEqual(len(self.calls), 2)
        for output, captured in captures:
            replay = native.capture_native(
                **self._args(output),
                resume=True,
                process_runner=lambda *args, **kwargs: self.fail("resume re-executed"),
                record_sha256_receipt=captured["record_sha256_receipt"],
            )
            self.assertEqual(replay["resume_action"], "verified-replay-no-execution")

    def test_capture_root_equal_escape_and_prefix_sibling_fail_before_dispatch(self):
        for output in (
            self.capture_root,
            self.root / "outside",
            self.root / "captures-other" / "run",
            self.capture_root / ".." / "escaped",
        ):
            with self.subTest(output=output):
                with self.assertRaisesRegex(
                    native.CaptureError, "inside frozen capture_root"
                ):
                    native.capture_native(
                        **self._args(output), process_runner=self._synthetic_runner
                    )
                self.assertFalse(output.exists())
        self.assertEqual(self.calls, [])

    def test_widened_root_wrong_config_and_cross_role_policy_are_rejected(self):
        mutations = []
        widened = copy.deepcopy(self.policy)
        widened["capture_root"] = str(self.root.parent)
        mutations.append(widened)
        wrong_hash = copy.deepcopy(self.policy)
        wrong_hash["config_sha256"] = "0" * 64
        mutations.append(wrong_hash)
        cross_role = copy.deepcopy(self.policy)
        cross_role["name"] = "other_role"
        mutations.append(cross_role)
        for policy in mutations:
            with self.subTest(policy=policy):
                with self.assertRaises(native_policy.NamedPolicyError):
                    native_policy.named_policy_args(
                        self._binding(policy), self.raw, self.capture_root / "attempt"
                    )

    def test_legacy_policy_keeps_exact_output_and_rejects_capture_root_field(self):
        legacy = _policy(self.raw, self.telemetry)
        native_policy.named_policy_args(
            self._binding(legacy), self.raw, self.capture_root
        )
        with self.assertRaisesRegex(
            native_policy.NamedPolicyError, "restrictions differ"
        ):
            native_policy.named_policy_args(
                self._binding(legacy), self.raw, self.capture_root / "new-output"
            )
        legacy["capture_root"] = str(self.capture_root)
        with self.assertRaisesRegex(native_policy.NamedPolicyError, "fields differ"):
            native_policy.named_policy_args(
                self._binding(legacy), self.raw, self.capture_root
            )

    def test_named_runtime_requires_both_exact_observed_filesystems(self):
        binding = self._binding()
        context = _runtime(binding)
        native_policy.verify_named_runtime(binding, context)
        mutations = {
            "missing-active": lambda row: row.pop("active_permission_profile"),
            "wrong-active": lambda row: row["active_permission_profile"].update(
                id="other_role"
            ),
            "missing-profile-filesystem": lambda row: row["permission_profile"].pop(
                "file_system"
            ),
            "missing-sandbox-filesystem": lambda row: row.pop(
                "file_system_sandbox_policy"
            ),
            "split-filesystem-drift": lambda row: row["file_system_sandbox_policy"][
                "entries"
            ][1].update(access="read"),
            "extra-writable-root": lambda row: row["permission_profile"]["file_system"][
                "entries"
            ].append(
                {
                    "path": {"type": "path", "path": str(self.root / "extra")},
                    "access": "write",
                }
            ),
            "duplicate-path": lambda row: row["file_system_sandbox_policy"][
                "entries"
            ].append(copy.deepcopy(row["file_system_sandbox_policy"]["entries"][0])),
            "network-disabled": lambda row: row["permission_profile"].update(
                network="disabled"
            ),
            "unmanaged-profile": lambda row: row["permission_profile"].update(
                type="custom"
            ),
            "missing-root-read": lambda row: row["file_system_sandbox_policy"][
                "entries"
            ].pop(0),
            "home-write": lambda row: row["permission_profile"]["file_system"][
                "entries"
            ][2].update(access="write"),
        }
        for label, change in mutations.items():
            with self.subTest(label=label):
                altered = copy.deepcopy(context)
                change(altered)
                with self.assertRaises(native_policy.NamedPolicyError):
                    native_policy.verify_named_runtime(binding, altered)

    def test_environment_selection_uses_canonical_pair_and_fails_for_absent_or_foreign_map(
        self,
    ):
        key = environment.environment_key(self.home, self.workspace)
        spec = {
            "schema_version": "1.1.0",
            "native": {
                "model": "gpt-test",
                "reasoning": "high",
                "policy_bindings": native.SUBJECT_EXECUTION_POLICY,
            },
            "execution_policies": {key: self.policy},
        }
        resolved = environment.native_for_environment(
            spec, self.home / ".." / "home", self.workspace / ".." / "workspace"
        )
        self.assertEqual(resolved["policy_bindings"], self.policy)
        resolved["policy_bindings"]["name"] = "mutated-return-only"
        self.assertEqual(spec["execution_policies"][key]["name"], NAME)
        for mapping in ({}, {"foreign-pair": self.policy}):
            changed = copy.deepcopy(spec)
            changed["execution_policies"] = mapping
            with self.assertRaisesRegex(
                Stage2Error, "execution-specific-named-policy-required"
            ):
                environment.native_for_environment(changed, self.home, self.workspace)
        (self.home / "config.toml").write_bytes(self.raw + b"# modified\n")
        with self.assertRaisesRegex(Stage2Error, "config bytes differ"):
            environment.native_for_environment(spec, self.home, self.workspace)


class RolePolicyControllerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = controller_fixtures.Stage2ControllerTests(
            methodName="test_complete_pipeline_replays_without_new_calls_and_awaits_human"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.spec = copy.deepcopy(self.fixture.spec)
        self.spec.update(
            schema_version="1.1.0",
            execution_policies={},
            execution_preflights={},
            execution_inventories={},
        )
        codex = self.fixture.root / "synthetic-codex.exe"
        codex.write_bytes(b"synthetic runtime fixture; never executed")
        self.spec["native"]["codex"] = str(codex)
        self.spec["preflight"] = {
            "report": {"synthetic": True},
            "capture_dir": str(self.fixture.root / "synthetic-preflight"),
            "receipt": "9" * 64,
            "probe_spec": {
                "kind": "Stage2ProductionRuntimeProbeSpec",
                "schema_version": "1.1.0",
            },
            "inventory_receipt": {},
        }
        for index, row in enumerate(self.spec["workspaces"].values()):
            home, workspace = Path(row["home"]), Path(row["workspace"])
            home.mkdir()
            workspace.mkdir()
            telemetry = self.fixture.root / f"telemetry-{index}"
            capture_root = self.fixture.root / f"capture-{index}"
            raw = _config(
                workspace,
                home,
                telemetry,
                capture_root,
                model="synthetic-model",
                reasoning="medium",
            )
            (home / "config.toml").write_bytes(raw)
            key = environment.environment_key(home, workspace)
            self.spec["execution_policies"][key] = _root_policy(
                raw, telemetry, capture_root
            )
            self.spec["execution_preflights"][key] = {"synthetic": True}

    def test_opt_in_spec_accepts_exact_role_map_and_rejects_incomplete_or_foreign_map(
        self,
    ):
        _validate_spec(
            self.spec, self.fixture.packet, self.fixture.base, synthetic=True
        )
        for field in ("execution_policies", "execution_preflights"):
            for alteration in ("missing", "foreign"):
                with self.subTest(field=field, alteration=alteration):
                    changed = copy.deepcopy(self.spec)
                    value = changed[field].pop(next(iter(changed[field])))
                    if alteration == "foreign":
                        changed[field]["foreign-pair"] = value
                    with self.assertRaisesRegex(
                        Stage2Error, "policy-environments-mismatch"
                    ):
                        _validate_spec(
                            changed,
                            self.fixture.packet,
                            self.fixture.base,
                            synthetic=True,
                        )

    def test_cross_role_policy_and_wrong_config_fail_during_spec_validation(self):
        changed = copy.deepcopy(self.spec)
        keys = list(changed["execution_policies"])
        changed["execution_policies"][keys[0]] = changed["execution_policies"][keys[1]]
        with self.assertRaisesRegex(Stage2Error, "execution-named-policy-invalid"):
            _validate_spec(
                changed, self.fixture.packet, self.fixture.base, synthetic=True
            )
        home = Path(self.spec["workspaces"]["research"]["home"])
        with (home / "config.toml").open("ab") as stream:
            stream.write(b"# changed profile bytes\n")
        with self.assertRaisesRegex(Stage2Error, "config bytes differ"):
            _validate_spec(
                self.spec, self.fixture.packet, self.fixture.base, synthetic=True
            )

    def test_legacy_controller_rejects_new_policy_map_without_explicit_opt_in(self):
        legacy = copy.deepcopy(self.fixture.spec)
        legacy["execution_policies"] = self.spec["execution_policies"]
        with self.assertRaisesRegex(Stage2Error, "controller-spec-shape"):
            _validate_spec(
                legacy, self.fixture.packet, self.fixture.base, synthetic=True
            )

    def test_production_settings_bind_named_policy_map(self):
        settings = _settings_binding(self.spec, SimpleNamespace(synthetic=False))
        self.assertEqual(
            settings["bindings"]["execution_policies_sha256"],
            canonical_hash(self.spec["execution_policies"]),
        )
        self.assertEqual(
            settings["bindings"]["workspaces_sha256"],
            canonical_hash(self.spec["workspaces"]),
        )

    def test_synthetic_controller_is_explicit_and_replays_without_execution(self):
        adapter = SyntheticAdapter()
        result = self.fixture.run_controller(adapter, spec=self.spec)
        self.assertEqual(result["status"], "awaiting-human")
        verified = verify_controller(
            self.fixture.controller, result["controller_manifest_sha256"]
        )
        self.assertTrue(verified["synthetic_test_only"])
        self.assertFalse(verified["authentic_native_execution"])
        self.assertFalse(verified["pilot_executable"])
        calls = list(adapter.calls)
        replay = self.fixture.run_controller(adapter, spec=self.spec)
        self.assertTrue(all(unit["replayed"] for unit in replay["units"]))
        self.assertEqual(adapter.calls, calls)

    def test_changed_valid_named_mapping_invalidates_resume_without_execution(self):
        adapter = SyntheticAdapter()
        self.fixture.run_controller(adapter, spec=self.spec)
        calls = list(adapter.calls)
        changed = copy.deepcopy(self.spec)
        research = changed["workspaces"]["research"]
        profile = Path(research["home"]) / "config.toml"
        raw = profile.read_bytes() + b"# new frozen profile identity\n"
        profile.write_bytes(raw)
        key = environment.environment_key(research["home"], research["workspace"])
        changed["execution_policies"][key]["config_sha256"] = hashlib.sha256(
            raw
        ).hexdigest()
        with self.assertRaisesRegex(Stage2Error, "action-binding-changed"):
            self.fixture.run_controller(adapter, spec=changed)
        self.assertEqual(adapter.calls, calls)

    def test_swapped_valid_role_assignments_invalidate_resume_without_execution(self):
        adapter = SyntheticAdapter()
        self.fixture.run_controller(adapter, spec=self.spec)
        calls = list(adapter.calls)
        changed = copy.deepcopy(self.spec)
        challenger = "review:candidate-1:challenger"
        changed["workspaces"]["research"], changed["workspaces"][challenger] = (
            changed["workspaces"][challenger],
            changed["workspaces"]["research"],
        )
        self.assertEqual(changed["execution_policies"], self.spec["execution_policies"])
        _validate_spec(changed, self.fixture.packet, self.fixture.base, synthetic=True)
        with self.assertRaisesRegex(Stage2Error, "action-binding-changed"):
            self.fixture.run_controller(adapter, spec=changed)
        self.assertEqual(adapter.calls, calls)

    def test_saved_capture_cannot_be_reassigned_by_valid_rehashed_role_spec(self):
        changed = copy.deepcopy(self.spec)
        challenger = "review:candidate-1:challenger"
        changed["workspaces"]["research"], changed["workspaces"][challenger] = (
            changed["workspaces"][challenger],
            changed["workspaces"]["research"],
        )
        _validate_spec(changed, self.fixture.packet, self.fixture.base, synthetic=True)
        self.assertNotEqual(canonical_hash(changed), canonical_hash(self.spec))
        state = self.fixture.initial
        capture_dir = self.fixture.root / "synthetic-saved-capture"
        receipt = "a" * 64
        cases = (
            (
                "stage2-ideation-native",
                "research",
                {},
                {"capture_dir": str(capture_dir), "record_sha256_receipt": receipt},
            ),
            (
                "stage2-independent-review",
                challenger,
                {"role": "challenger"},
                {
                    "review": {
                        "candidate_id": "candidate-1",
                        "role": "challenger",
                        "native_artifact": {"path": str(capture_dir / "run.json")},
                    },
                    "native_receipt": receipt,
                },
            ),
        )
        for kind, original_role, inputs, value in cases:
            with self.subTest(kind=kind):
                saved_paths = self.spec["workspaces"][original_role]
                key = environment.environment_key(
                    saved_paths["home"], saved_paths["workspace"]
                )
                record = {
                    "stable_request_binding": {
                        "codex_home": saved_paths["home"],
                        "workspace": saved_paths["workspace"],
                        "policy_bindings": self.spec["execution_policies"][key],
                    },
                    "event_summary": {"thread_id": "synthetic-only"},
                }
                synthetic_state = {
                    "snapshots": state["snapshots"],
                    "actions": {
                        "saved": {
                            "request": {
                                "action_kind": kind,
                                "inputs": inputs,
                                "snapshot_sha256": self.fixture.base,
                            }
                        }
                    },
                }
                with (
                    patch(
                        "stage2_live.controller.verify_capture",
                        return_value=(record, ""),
                    ) as capture_verifier,
                    patch(
                        "stage2_live.controller.verify_environment_capture"
                    ) as environment_verifier,
                ):
                    _verify_action_environments(
                        self.spec, synthetic_state, {"saved": value}
                    )
                    environment_verifier.assert_called_once()
                    environment_verifier.reset_mock()
                    with self.assertRaisesRegex(
                        Stage2Error, "capture-role-allocation-mismatch"
                    ):
                        _verify_action_environments(
                            changed, synthetic_state, {"saved": value}
                        )
                    environment_verifier.assert_not_called()
                    self.assertEqual(
                        [call.args[1] for call in capture_verifier.call_args_list],
                        [receipt, receipt],
                    )


if __name__ == "__main__":
    unittest.main()
