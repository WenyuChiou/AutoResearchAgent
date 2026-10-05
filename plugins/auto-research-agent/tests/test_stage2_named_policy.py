"""Security boundaries for opt-in named native capture permissions."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))

from stage2_live import native, native_policy  # noqa: E402


NAME = "stage2_named"


def _scalar(value):
    return str(value).lower() if isinstance(value, bool) else json.dumps(value)


def _config(workspace, home, telemetry, output, **changes):
    values = {
        "model": "gpt-test",
        "reasoning": "high",
        "search": "live",
        "multi_agent": True,
        "proxy": True,
        "network": True,
        "local_binding": False,
    }
    values.update(changes)
    omit = set(values.get("omit", ()))
    filesystem = [
        ("root", "/", "read"),
        ("workspace", str(workspace.resolve()), "write"),
        ("home", str(home.resolve()), "deny"),
        ("telemetry", str(telemetry.resolve()), "deny"),
        ("output", str(output.resolve()), "deny"),
    ]
    domains = [
        ("wildcard", "*", "allow"),
        ("localhost", "localhost", "deny"),
        ("ipv4", "127.0.0.1", "deny"),
        ("ipv6", "::1", "deny"),
    ]
    lines = [
        f"model = {_scalar(values['model'])}",
        f"model_reasoning_effort = {_scalar(values['reasoning'])}",
        f"web_search = {_scalar(values['search'])}",
        'approval_policy = "never"',
        f"default_permissions = {json.dumps(NAME)}",
        "",
        "[features]",
        f"multi_agent_v2 = {_scalar(values['multi_agent'])}",
        f"network_proxy = {_scalar(values['proxy'])}",
        "",
        f"[permissions.{json.dumps(NAME)}.filesystem]",
    ]
    lines.extend(
        f"{json.dumps(path)} = {json.dumps(mode)}"
        for label, path, mode in filesystem
        if label not in omit
    )
    if values.get("extra_write"):
        lines.append(f'{json.dumps(str(values["extra_write"]))} = "write"')
    lines.extend(
        [
            "",
            f"[permissions.{json.dumps(NAME)}.network]",
            f"enabled = {_scalar(values['network'])}",
            'mode = "full"',
            f"allow_local_binding = {_scalar(values['local_binding'])}",
            "",
            f"[permissions.{json.dumps(NAME)}.network.domains]",
        ]
    )
    lines.extend(
        f"{json.dumps(domain)} = {json.dumps(mode)}"
        for label, domain, mode in domains
        if label not in omit
    )
    lines.extend(
        [
            "",
            f"[projects.{json.dumps(str(workspace.resolve()))}]",
            'trust_level = "untrusted"',
            "",
        ]
    )
    return "\n".join(lines).encode()


def _policy(config_bytes, telemetry):
    return {
        "kind": "Stage2NamedPermissionsPolicy",
        "schema_version": "1.0.0",
        "name": NAME,
        "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "telemetry_path": str(telemetry.resolve()),
    }


class NamedPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.workspace = self.root / "workspace"
        self.telemetry = self.root / "telemetry"
        for path in (self.home, self.workspace, self.telemetry):
            path.mkdir()
        (self.workspace / "source.txt").write_text("source", encoding="utf-8")
        self.codex = self.root / "codex.exe"
        self.codex.write_bytes(b"synthetic launcher")
        self.input = self.root / "brief.json"
        self.input.write_text('{"topic":"test"}\n', encoding="utf-8")
        self.budget = self.root / "budget.json"
        self.budget.write_text('{"limit":1}\n', encoding="utf-8")
        self.calls = []

    def _args(self, output, policy):
        return {
            "codex": self.codex,
            "codex_home": self.home,
            "workspace": self.workspace,
            "prompt": "Use native tools.",
            "model": "gpt-test",
            "reasoning": "high",
            "input_bindings": {"brief": self.input},
            "config_bindings": {"budget": self.budget},
            "policy_bindings": policy,
            "output_dir": output,
        }

    def _runner(self, command, **kwargs):
        self.calls.append(command)
        final = Path(command[command.index("-o") + 1])
        final.write_text("final answer\n", encoding="utf-8")
        events = (
            {"type": "thread.started", "thread_id": "thread-1"},
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "final answer"},
            },
            {"type": "turn.completed", "usage": {"output_tokens": 2}},
        )
        return SimpleNamespace(
            stdout=b"".join(json.dumps(row).encode() + b"\n" for row in events),
            stderr=b"",
            returncode=0,
        )

    def _install(self, output, **changes):
        raw = _config(self.workspace, self.home, self.telemetry, output, **changes)
        (self.home / "config.toml").write_bytes(raw)
        return raw, _policy(raw, self.telemetry)

    def _reject(self, label, **changes):
        output = self.root / f"rejected-{label}"
        _, policy = self._install(output, **changes)
        with self.assertRaises(native.CaptureError):
            native.capture_native(
                **self._args(output, policy), process_runner=self._runner
            )
        self.assertEqual(self.calls, [])
        self.assertFalse(output.exists())

    def test_named_capture_binds_config_command_and_resume_without_execution(self):
        output = self.root / "capture"
        raw, policy = self._install(output)
        captured = native.capture_native(
            **self._args(output, policy), process_runner=self._runner
        )
        self.assertEqual(captured["schema_version"], "2.0.0")
        self.assertEqual((output / "archive/profile-config.toml").read_bytes(), raw)
        command = captured["command"]
        self.assertIn(f"default_permissions={json.dumps(NAME)}", command)
        trust = f'projects.{json.dumps(str(self.workspace.resolve()))}.trust_level="untrusted"'
        self.assertIn(trust, command)
        self.assertIn("features.network_proxy=true", command)
        self.assertIn("features.multi_agent_v2=true", command)
        self.assertNotIn("--sandbox", command)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)
        replay = native.capture_native(
            **self._args(output, policy),
            resume=True,
            process_runner=lambda *args, **kwargs: self.fail("resume re-executed"),
            record_sha256_receipt=captured["record_sha256_receipt"],
        )
        self.assertEqual(replay["resume_action"], "verified-replay-no-execution")
        self.assertEqual(len(self.calls), 1)

    def test_altered_config_and_rehashed_restriction_changes_fail_preprocess(self):
        output = self.root / "altered"
        raw, policy = self._install(output)
        (self.home / "config.toml").write_bytes(raw + b"# changed\n")
        with self.assertRaisesRegex(native.CaptureError, "config bytes differ"):
            native.capture_native(
                **self._args(output, policy), process_runner=self._runner
            )
        cases = {
            "model": {"model": "other"},
            "reasoning": {"reasoning": "low"},
            "search": {"search": "cached"},
            "feature-int": {"multi_agent": 1},
            "proxy-int": {"proxy": 1},
            "network-int": {"network": 1},
            "binding-int": {"local_binding": 0},
            "missing-home-denial": {"omit": {"home"}},
            "missing-loopback-denial": {"omit": {"localhost"}},
            "extra-write": {"extra_write": self.root / "extra"},
        }
        for label, changes in cases.items():
            with self.subTest(label=label):
                self._reject(label, **changes)

    def test_overlapping_directories_and_missing_named_config_fail_preprocess(self):
        output = self.root / "overlap"
        telemetry = self.workspace / "telemetry"
        raw = _config(self.workspace, self.home, telemetry, output)
        (self.home / "config.toml").write_bytes(raw)
        with self.assertRaisesRegex(native.CaptureError, "directories overlap"):
            native.capture_native(
                **self._args(output, _policy(raw, telemetry)),
                process_runner=self._runner,
            )
        (self.home / "config.toml").unlink()
        with self.assertRaisesRegex(native.CaptureError, "config.toml"):
            native.capture_native(
                **self._args(self.root / "missing", _policy(raw, self.telemetry)),
                process_runner=self._runner,
            )
        self.assertEqual(self.calls, [])

    def test_project_and_ancestor_config_layers_block_before_dispatch(self):
        home_write = (
            f"[permissions.{json.dumps(NAME)}.filesystem]\n"
            f'{json.dumps(str(self.home.resolve()))} = "write"\n'
        )
        proxy_false = "[features]\nnetwork_proxy = false\n"
        attacks = (
            ("workspace", self.workspace / "config.toml", home_write),
            ("workspace-dot", self.workspace / ".codex/config.toml", proxy_false),
            ("parent-dot", self.root / ".codex/config.toml", home_write),
        )
        for label, path, content in attacks:
            with self.subTest(label=label):
                output = self.root / f"layer-{label}"
                _, policy = self._install(output)
                created_parent = not path.parent.exists()
                path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    path.write_text(content, encoding="utf-8")
                    with self.assertRaisesRegex(native.CaptureError, "config layers"):
                        native.capture_native(
                            **self._args(output, policy), process_runner=self._runner
                        )
                    self.assertEqual(self.calls, [])
                    self.assertFalse(output.exists())
                finally:
                    path.unlink(missing_ok=True)
                    if created_parent:
                        path.parent.rmdir()

    def test_dangling_config_detection_uses_lexists_before_dispatch(self):
        output = self.root / "dangling"
        _, policy = self._install(output)
        with patch.object(native_policy.os.path, "lexists", return_value=True):
            with self.assertRaisesRegex(native.CaptureError, "config layers"):
                native.capture_native(
                    **self._args(output, policy), process_runner=self._runner
                )
        self.assertEqual(self.calls, [])

    def test_legacy_capture_retains_schema_and_workspace_sandbox(self):
        output = self.root / "legacy"
        (self.home / "config.toml").write_text("model = 'frozen'\n", encoding="utf-8")
        captured = native.capture_native(
            **self._args(output, native.SUBJECT_EXECUTION_POLICY),
            process_runner=self._runner,
        )
        self.assertEqual(captured["schema_version"], "1.0.0")
        self.assertIn("--sandbox", captured["command"])
        self.assertIn("workspace-write", captured["command"])
