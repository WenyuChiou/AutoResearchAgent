"""Diagnostic lifecycle admission is offline-testable without any model or VM."""

import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage1_ab import (
    runner,
    vm_guest,
    vm_lifecycle as lifecycle,
    vm_subject,
)  # noqa: E402


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.subject = self.root / "subject"
        self.diag = self.root / "diagnostic"
        for home in (self.subject, self.diag):
            home.mkdir()
            for name in ("profile", "workspace", "tmp"):
                (home / name).mkdir()
            (home / "profile/config.toml").write_text('web_search="live"\n')
        self.state = self.root / "state"
        self.state.mkdir()
        self.key = self.root / "key"
        self.key.write_bytes(b"private-operator-key-32-bytes-long")
        self.key.chmod(0o600)
        self.config = {
            "native_user": "subject",
            "profile": str(self.subject / "profile"),
            "workspace": str(self.subject / "workspace"),
            "native_tmp": str(self.subject / "tmp"),
            "diagnostic": {
                "native_user": "diagnostic",
                "profile": str(self.diag / "profile"),
                "workspace": str(self.diag / "workspace"),
                "native_tmp": str(self.diag / "tmp"),
            },
            "condition": "treatment",
            "codex": "synthetic",
            "private_root": str(self.root / "absent"),
            "state_root": str(self.state),
            "secret_file": str(self.key),
        }
        self.identity = {
            "condition": "treatment",
            "config_sha256": "actual-config",
            "guest_id": "actual-guest",
            "protected_runtime": {"kind": "synthetic-test-runtime"},
        }
        self.lock = {"codex_runtime_sha256": "binary", "plugin_tree_sha256": "plugin"}
        self.probe = {key: key + "-value" for key in lifecycle.MATCH_FIELDS}
        self.probe.update(
            functional_skill_sha256="skill", installed_skill_sha256="skill"
        )
        self.groups = [(101, self.subject, []), (102, self.diag, [])]
        self.calls = []

    def native(self, name):
        home = self.subject if name == "subject" else self.diag
        return {"user": 101 if name == "subject" else 102}, {"HOME": str(home)}

    def helper(self, name, operation, **args):
        return vm_subject.dispatch({"operation": operation, **args})

    def fake_probe(self, codex, profile, workspace, *args, **kwargs):
        self.calls.append((profile, kwargs))
        self.assertEqual(profile, str(self.diag / "profile"))
        (self.diag / "profile/history.jsonl").write_text("diagnostic only")
        (self.diag / ".cache").mkdir()
        (self.diag / ".cache/native-cache").write_text("diagnostic cache")
        return self.probe.copy()

    def context(self):
        from contextlib import ExitStack

        stack = ExitStack()
        stack.enter_context(
            patch.object(
                vm_guest,
                "configuration",
                return_value=(
                    self.config,
                    self.lock,
                    self.identity,
                    self.key.read_bytes(),
                ),
            )
        )
        stack.enter_context(
            patch.object(vm_guest, "native_options", side_effect=self.native)
        )
        stack.enter_context(
            patch.object(lifecycle, "account_paths", return_value=self.groups)
        )
        stack.enter_context(patch.object(lifecycle, "process_ids", return_value=[]))
        stack.enter_context(patch.object(lifecycle, "retire"))
        stack.enter_context(patch.object(vm_subject, "call", side_effect=self.helper))
        stack.enter_context(
            patch.object(runner, "codex_runtime_sha", return_value="binary")
        )
        stack.enter_context(
            patch.object(runner, "probe_profile", side_effect=self.fake_probe)
        )
        return stack

    def test_diagnostic_mutation_never_reaches_subject_and_admission_is_zero_call(self):
        with self.context():
            before = lifecycle.initial_setup(self.config)
            envelope = lifecycle.run_diagnostic("config.json")
            proof = lifecycle.admit(self.config, self.lock, self.identity)
            self.assertEqual(before, lifecycle.initial_setup(self.config))
            self.assertFalse((self.subject / "profile/history.jsonl").exists())
            self.assertFalse((self.subject / ".cache").exists())
            self.assertEqual(len(self.calls), 1)
            self.assertEqual(envelope["body"]["model_calls"], 1)
            self.assertEqual(proof["diagnostic"], envelope)
            actual = {**self.probe, "functional_skill_sha256": None}
            lifecycle.match_probe(proof, actual, self.lock, self.identity)
            for key in (
                "native_config_sha256",
                "installed_plugin_sha256",
                "codex_version",
            ):
                with self.subTest(key=key), self.assertRaises(runner.ExecutionBlocked):
                    lifecycle.match_probe(
                        proof, {**actual, key: "substituted"}, self.lock, self.identity
                    )
            with self.assertRaises(runner.ExecutionBlocked):
                lifecycle.admit(
                    self.config,
                    self.lock,
                    {**self.identity, "config_sha256": "another-profile"},
                )
            with self.assertRaises(runner.ExecutionBlocked):
                lifecycle.match_probe(
                    proof,
                    actual,
                    {**self.lock, "codex_runtime_sha256": "different"},
                    self.identity,
                )
            self.assertEqual(len(self.calls), 1)

    def test_freshness_and_signature_fail_closed(self):
        with self.context():
            lifecycle.run_diagnostic("config.json")
            (self.subject / "profile/history.jsonl").write_text("old run")
            with self.assertRaisesRegex(ValueError, "non-setup"):
                lifecycle.admit(self.config, self.lock, self.identity)
            receipt = self.state / "diagnostic-receipt.json"
            value = runner.read_json(receipt)
            value["body"]["matching_probe"]["native_config_sha256"] = "tamper"
            receipt.write_text(json.dumps(value))
            with self.assertRaisesRegex(runner.ExecutionBlocked, "authentication"):
                lifecycle.admit(self.config, self.lock, self.identity)

    def test_duplicate_diagnostic_never_reexecutes(self):
        with self.context():
            lifecycle.run_diagnostic("config.json")
            with self.assertRaises((ValueError, OSError)):
                lifecycle.run_diagnostic("config.json")
            self.assertEqual(len(self.calls), 1)

    def test_stop_receipt_write_failure_still_retires_diagnostic(self):
        original = runner.write_json

        def fail_stop(path, value):
            if Path(path).name == "diagnostic-stop.json":
                raise OSError("synthetic disk full")
            return original(path, value)

        with (
            self.context(),
            patch.object(runner, "write_json", side_effect=fail_stop),
            patch.object(lifecycle, "retire") as retire,
        ):
            with self.assertRaisesRegex(OSError, "disk full"):
                lifecycle.run_diagnostic("config.json")
            retire.assert_called_once_with(102)
            self.assertTrue((self.state / "diagnostic-start.json").exists())
            self.assertFalse((self.state / "diagnostic-receipt.json").exists())

    def test_plugin_cache_history_is_not_setup(self):
        with self.context():
            folder = (
                self.subject / "profile/plugins/cache/market/auto-research-agent/0.1.0"
            )
            folder.mkdir(parents=True)
            (folder / "history.jsonl").write_text("copied diagnostic data")
            with self.assertRaisesRegex(ValueError, "non-setup"):
                lifecycle.initial_setup(self.config)

    def test_permission_helper_reports_actual_access(self):
        result = vm_subject.dispatch(
            {"operation": "access", "paths": [str(self.subject)]}
        )
        self.assertEqual(
            result,
            {
                str(self.subject): (
                    os.access(self.subject, os.R_OK) or os.access(self.subject, os.X_OK)
                )
            },
        )

    def test_shared_or_accessible_storage_rejected(self):

        def fake_stat(path, *args, **kwargs):
            uid = (
                101
                if path == self.subject or path.is_relative_to(self.subject)
                else 102
            )
            return type("Stat", (), {"st_uid": uid, "st_mode": 0o40700})()

        def text(path, *args, **kwargs):
            if str(path).replace("\\", "/") == "/proc/mounts":
                return "none / ext4 rw 0 0\n"
            raise AssertionError(path)

        # Platform filesystem identities are replaced, but production path-overlap
        # and helper read/traverse rejection are exercised directly.
        with (
            patch.object(vm_guest, "native_options", side_effect=self.native),
            patch.object(Path, "stat", fake_stat),
            patch.object(Path, "is_dir", return_value=True),
            patch.object(Path, "is_symlink", return_value=False),
            patch.object(Path, "read_text", text),
            patch.object(
                vm_subject,
                "call",
                side_effect=lambda user, op, **kw: {p: True for p in kw["paths"]},
            ),
        ):
            with self.assertRaisesRegex(runner.ExecutionBlocked, "accessible"):
                lifecycle.account_paths(self.config)
            other = copy.deepcopy(self.config)
            other["diagnostic"]["profile"] = self.config["profile"]
            with self.assertRaises(runner.ExecutionBlocked):
                lifecycle.account_paths(other)

    def test_actual_probe_mode_skips_smoke_but_local_default_keeps_it(self):
        skill = (
            self.subject
            / "profile/plugins/cache/local/auto-research-agent/0.1.0/skills/stage1-literature/SKILL.md"
        )
        skill.parent.mkdir(parents=True)
        skill.write_text("synthetic skill")
        responses = [
            {},
            {
                "marketplaces": [
                    {
                        "name": "local",
                        "path": "market",
                        "plugins": [
                            {
                                "name": "auto-research-agent",
                                "installed": True,
                                "enabled": True,
                                "localVersion": "0.1.0",
                            }
                        ],
                    }
                ]
            },
            {
                "data": [
                    {
                        "model": "gpt-5.6-sol",
                        "supportedReasoningEfforts": [{"reasoningEffort": "high"}],
                    }
                ]
            },
            {"webSearch": True},
            {
                "plugin": {
                    "skills": [
                        {"name": "auto-research-agent:" + name, "enabled": True}
                        for name in ("stage1-literature", "stage2-directions")
                    ]
                }
            },
        ]
        for mode in (lifecycle.MODE, "functional"):
            process = MagicMock()
            process.stdin = io.StringIO()
            process.stdout = io.StringIO(
                "".join(
                    json.dumps({"id": n, "result": value}) + "\n"
                    for n, value in enumerate(responses, 1)
                )
            )
            process.wait.return_value = 0
            with (
                patch.object(runner.subprocess, "Popen", return_value=process),
                patch.object(
                    runner.subprocess,
                    "run",
                    side_effect=[
                        type(
                            "Result",
                            (),
                            {"returncode": 0, "stdout": value, "stderr": ""},
                        )()
                        for value in ("codex", "Logged in")
                    ],
                ),
                patch.object(runner, "tree_sha", return_value="plugin"),
                patch.object(
                    runner, "_functional_skill_smoke", return_value="skill"
                ) as smoke,
            ):
                options = {} if mode == "functional" else {"probe_mode": mode}
                proof = runner.probe_profile(
                    "codex",
                    self.subject / "profile",
                    self.subject / "workspace",
                    True,
                    self.root / "absent",
                    **options,
                )
                self.assertEqual(smoke.call_count, int(mode == "functional"))
                self.assertEqual(
                    proof["functional_skill_sha256"],
                    "skill" if mode == "functional" else None,
                )
        with self.assertRaisesRegex(
            runner.ExecutionBlocked, "unknown profile probe mode"
        ):
            runner.probe_profile("codex", None, None, True, None, probe_mode="typo")


if __name__ == "__main__":
    unittest.main()
