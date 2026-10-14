"""Opt-in pure native profiles retain capture and effective-permission guards."""

import copy
import hashlib
import os
import unittest
from unittest.mock import patch

import test_stage2_named_policy as legacy_fixture
from stage2_live import (
    environment,
    native,
    native_policy,
    observed_action,
    trace_producer,
)


class PlainNativePolicyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = legacy_fixture.NamedPolicyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.capture_root = self.fixture.root / "capture-root"
        self.capture_root.mkdir()
        self.output = self.capture_root / "run-1"

    def install(self, *, version="1.2.0", raw=None, limit=3):
        f = self.fixture
        if raw is None:
            raw = legacy_fixture._config(
                f.workspace, f.home, f.telemetry, self.capture_root
            )
            raw = raw.replace(
                b"network_proxy = true\n",
                b"network_proxy = true\napps = false\nplugins = false\n"
                b"remote_plugin = false\nmemories = false\n",
            )
            raw += b"\n[mcp_servers]\n\n[agents]\nmax_threads = 3\n"
        (f.home / "config.toml").write_bytes(raw)
        policy = {
            "kind": "Stage2NamedPermissionsPolicy",
            "schema_version": version,
            "name": legacy_fixture.NAME,
            "config_sha256": hashlib.sha256(raw).hexdigest(),
            "telemetry_path": str(f.telemetry.resolve()),
            "capture_root": str(self.capture_root.resolve()),
        }
        if version == "1.2.0":
            policy["max_child_threads"] = limit
        return raw, f._args(self.output, policy)

    def test_pure_profile_capture_and_completed_resume_keep_exact_arguments(self):
        raw, args = self.install()
        result = native.capture_native(**args, process_runner=self.fixture._runner)
        self.assertEqual(
            (self.output / "archive/profile-config.toml").read_bytes(), raw
        )
        for option in (
            "features.apps=false",
            "features.plugins=false",
            "features.remote_plugin=false",
            "features.memories=false",
            "agents.max_threads=3",
            "mcp_servers={}",
        ):
            self.assertIn(option, result["command"])
        self.assertNotIn(
            "--dangerously-bypass-approvals-and-sandbox", result["command"]
        )
        replay = native.capture_native(
            **args,
            resume=True,
            record_sha256_receipt=result["record_sha256_receipt"],
            process_runner=lambda *a, **k: self.fail("completed capture re-executed"),
        )
        self.assertEqual(replay["resume_action"], "verified-replay-no-execution")
        self.assertEqual(len(self.fixture.calls), 1)

    def test_legacy_root_policy_still_rejects_added_baseline_configuration(self):
        _, args = self.install(version="1.1.0")
        with self.assertRaisesRegex(native.CaptureError, "unsupported configuration"):
            native.capture_native(**args, process_runner=self.fixture._runner)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.fixture.calls, [])

    def test_malformed_feature_tables_are_rejected_before_dispatch(self):
        original, _ = self.install()
        prefix, remaining = original.split(b"[features]\n", 1)
        _, permissions = remaining.split(b"\n[permissions.", 1)
        for value in (b"0", b"[]", b"true"):
            with self.subTest(value=value):
                raw = (
                    prefix + b"features = " + value + b"\n\n[permissions." + permissions
                )
                _, args = self.install(raw=raw)
                with self.assertRaisesRegex(
                    native.CaptureError, "features must be a table"
                ):
                    native.capture_native(**args, process_runner=self.fixture._runner)
                self.assertFalse(self.output.exists())
                self.assertEqual(self.fixture.calls, [])

    def test_malformed_version_is_a_controlled_rejection_in_every_caller(self):
        _, args = self.install()
        for version in (["1.2.0"], {"version": "1.2.0"}):
            with self.subTest(version=version):
                request = {k: v for k, v in args.items() if k != "output_dir"}
                request["policy_bindings"] = dict(
                    args["policy_bindings"], schema_version=version
                )
                request["capture_dir"] = self.output
                request["trace_root"] = self.fixture.telemetry / "malformed"
                self.assertFalse(
                    native_policy.capture_root_policy(request["policy_bindings"])
                )
                with self.assertRaises(native.CaptureError):
                    native.capture_native(
                        **dict(args, policy_bindings=request["policy_bindings"]),
                        process_runner=self.fixture._runner,
                    )
                with self.assertRaises(native.CaptureError):
                    observed_action._action_root(request, resume=False)
                self.assertFalse(request["trace_root"].exists())
                self.assertEqual(self.fixture.calls, [])

    def test_enabled_extensions_extra_mcp_and_limit_drift_fail_before_dispatch(self):
        original, _ = self.install()
        cases = [
            original.replace(f"{key} = false".encode(), f"{key} = true".encode())
            for key in ("apps", "plugins", "remote_plugin", "memories")
        ]
        cases += [
            original.replace(b"apps = false", b"apps = 0"),
            original.replace(b"[mcp_servers]", b'[mcp_servers.extra]\ncommand = "bad"'),
            original.replace(b"max_threads = 3", b"max_threads = 4"),
            original.replace(b"max_threads = 3", b"max_threads = true"),
            original.replace(b"max_threads = 3", b"max_threads = 0"),
            original.replace(b"max_threads = 3", b"max_threads = 3\nmax_depth = 9"),
        ]
        for index, raw in enumerate(cases):
            with self.subTest(index=index):
                _, args = self.install(raw=raw)
                with self.assertRaises(native.CaptureError):
                    native.capture_native(**args, process_runner=self.fixture._runner)
                self.assertFalse(self.output.exists())
                self.assertEqual(self.fixture.calls, [])

    def test_rehashed_permission_changes_and_ancestor_layers_still_reject(self):
        raw, _ = self.install()
        changes = [
            raw.replace(b'"/" = "read"', b'"/" = "write"'),
            raw.replace(b'"localhost" = "deny"', b'"localhost" = "allow"'),
            raw.replace(b"allow_local_binding = false", b"allow_local_binding = true"),
            raw.replace(b'trust_level = "untrusted"', b'trust_level = "trusted"'),
        ]
        for index, altered in enumerate(changes):
            with self.subTest(index=index):
                _, args = self.install(raw=altered)
                with self.assertRaises(native.CaptureError):
                    native.capture_native(**args, process_runner=self.fixture._runner)
                self.assertEqual(self.fixture.calls, [])
        _, args = self.install()
        with patch.object(native_policy.os.path, "lexists", return_value=True):
            with self.assertRaisesRegex(native.CaptureError, "config layers"):
                native.capture_native(**args, process_runner=self.fixture._runner)

    def test_action_trace_and_role_resolution_accept_only_bound_child_paths(self):
        _, args = self.install()
        action_trace = (self.fixture.telemetry / "action-1").resolve()
        request = {k: v for k, v in args.items() if k != "output_dir"}
        request["capture_dir"] = args["output_dir"]
        request["trace_root"] = action_trace
        self.assertEqual(
            observed_action._action_root(request, resume=False), action_trace
        )
        with patch.dict(os.environ, {"CODEX_ROLLOUT_TRACE_ROOT": str(action_trace)}):
            self.assertEqual(
                trace_producer._telemetry(args["policy_bindings"], action_trace),
                action_trace,
            )
        invalid = dict(request, trace_root=self.fixture.telemetry)
        with self.assertRaises(native.CaptureError):
            observed_action._action_root(invalid, resume=False)
        spec = {
            "schema_version": "1.2.0",
            "native": {"model": "gpt-test", "reasoning": "high"},
            "execution_policies": {
                environment.environment_key(
                    self.fixture.home, self.fixture.workspace
                ): args["policy_bindings"]
            },
        }
        resolved = environment.native_for_environment(
            spec, self.fixture.home, self.fixture.workspace
        )
        self.assertEqual(resolved["policy_bindings"], args["policy_bindings"])

    def test_effective_permission_checks_are_not_skipped_for_new_version(self):
        _, args = self.install()
        binding = dict(
            args,
            workspace=str(self.fixture.workspace.resolve()),
            codex_home=str(self.fixture.home.resolve()),
        )
        entries = [
            {"path": {"type": "path", "path": path}, "access": access}
            for path, access in {
                "/": "read",
                binding["workspace"]: "write",
                binding["codex_home"]: "deny",
                args["policy_bindings"]["telemetry_path"]: "deny",
                args["policy_bindings"]["capture_root"]: "deny",
            }.items()
        ]
        context = {
            "active_permission_profile": {"id": legacy_fixture.NAME},
            "permission_profile": {
                "type": "managed",
                "network": "enabled",
                "file_system": {"type": "restricted", "entries": entries},
            },
            "file_system_sandbox_policy": {"kind": "restricted", "entries": entries},
            "sandbox_policy": {"type": "workspace-write", "network_access": True},
            "approval_policy": "never",
        }
        native_policy.verify_named_runtime(binding, context)
        tampered = copy.deepcopy(context)
        tampered["permission_profile"]["file_system"]["entries"][0]["access"] = "write"
        with self.assertRaises(native_policy.NamedPolicyError):
            native_policy.verify_named_runtime(binding, tampered)
        with self.assertRaises(native_policy.NamedPolicyError):
            native_policy.verify_named_runtime(binding, {})


if __name__ == "__main__":
    unittest.main()
