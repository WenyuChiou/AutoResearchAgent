"""Contract tests for the Stage 2 functional runtime preflight."""

import copy
from contextlib import redirect_stdout
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage2_live import preflight


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Stage2PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.capture = Path(self.temporary.name) / "capture"
        self.start = self.capture / "archive/workspace-start"
        self.end = self.capture / "archive/workspace-end"
        self.sessions = self.capture / "archive/native-sessions"
        self.start.mkdir(parents=True)
        self.end.mkdir(parents=True)
        self.sessions.mkdir(parents=True)
        self.bootstrap = self.capture / "bootstrap"
        self.bootstrap.mkdir()
        shell_bytes = b"synthetic host shell fixture"
        self.executor = {
            "shell_path": "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
            "shell_sha256": digest(shell_bytes),
            "working_directory": str(self.capture.parent),
            "family": "windows",
        }
        shell_archive = self.capture / "archive/config_bindings/probe_shell"
        shell_archive.parent.mkdir(parents=True)
        shell_archive.write_bytes(shell_bytes)
        self.nonce = "nonce-4c712fed"
        (self.start / "source.txt").write_text(
            f"source-only {self.nonce}\n", encoding="utf-8"
        )
        self.created = b"functional-write\n"
        (self.end / "created.txt").write_bytes(self.created)
        self.record = {
            "kind": "Stage2NativeCapture",
            "schema_version": "1.0.0",
            "stable_request_binding": {
                "workspace": str(self.capture.parent),
                "model": "gpt-test",
                "reasoning": "high",
                "policy_bindings": {
                    "sandbox": "workspace-write",
                    "network_access": True,
                },
                "config_bindings": {
                    "probe_shell": {
                        "kind": "file",
                        "path": self.executor["shell_path"],
                        "sha256": self.executor["shell_sha256"],
                    }
                },
            },
            "event_summary": {"thread_id": "thread-primary"},
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        self.spec = {
            "kind": "Stage2RuntimeProbeSpec",
            "schema_version": "1.0.0",
            "executor": self.executor,
            "expected": {
                "model": "gpt-test",
                "reasoning": "high",
                "sandbox": "workspace-write",
                "network_access": True,
            },
            "probes": {
                "read": {
                    "event_id": "call-read",
                    "source_path": "source.txt",
                    "nonce": self.nonce,
                },
                "write": {
                    "event_id": "call-write",
                    "output_path": "created.txt",
                    "sha256": digest(self.created),
                },
                "search": {"event_id": "search-1"},
                "child": {
                    "event_id": "child-1",
                    "child_thread_id": "thread-child",
                },
                "isolation": {
                    "sentinels": {
                        "judge": self.sentinel_spec(
                            "deny-judge", "C:/sealed/judge.txt", "judge-nonce"
                        ),
                        "peer": self.sentinel_spec(
                            "deny-peer", "C:/sealed/peer.txt", "peer-nonce"
                        ),
                        "expected-outcomes": self.sentinel_spec(
                            "deny-expected",
                            "C:/sealed/expected.json",
                            "expected-nonce",
                        ),
                    }
                },
            },
        }
        self.context = {
            "model": "gpt-test",
            "effort": "high",
            "approval_policy": "never",
            "sandbox_policy": {
                "type": "workspaceWrite",
                "network_access": True,
            },
            "permission_profile": {
                "type": "managed",
                "file_system": {
                    "type": "restricted",
                    "entries": [
                        {
                            "path": {
                                "type": "special",
                                "value": {"kind": "project_roots"},
                            },
                            "access": "write",
                        }
                    ],
                },
                "network": "enabled",
            },
            "capability_inventory": {
                "instructions": ["AGENTS.md"],
                "skills": ["stage2"],
                "plugins": ["auto-research-agent"],
                "mcp": ["web"],
                "tools": ["exec_command", "web_search", "subagent"],
                "settings": {"profile": "isolated"},
            },
        }
        self.inventory_receipt = self.write_inventory_receipt()
        self.write_sessions()

    def tearDown(self):
        self.temporary.cleanup()

    def write_jsonl(self, name, events):
        path = self.sessions / name
        path.write_text(
            "".join(json.dumps(event) + "\n" for event in events),
            encoding="utf-8",
        )

    def write_stdout(self, events):
        (self.capture / "stdout.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in events),
            encoding="utf-8",
        )

    def mutate_stdout_item(self, event_id, **updates):
        path = self.capture / "stdout.jsonl"
        events = [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        ]
        for event in events:
            if event.get("item", {}).get("id") == event_id:
                event["item"].update(updates)
                break
        else:
            self.fail(f"missing stdout item {event_id}")
        self.write_stdout(events)

    def write_raw(self, name, value):
        path = self.bootstrap / name
        raw = (json.dumps(value, sort_keys=True) + "\n").encode()
        path.write_bytes(raw)
        return {
            "path": path.relative_to(self.capture).as_posix(),
            "sha256": digest(raw),
        }

    def sentinel_spec(self, event_id, path, nonce):
        command = self.read_request(path)
        sentinel_sha256 = digest((nonce + "-bytes").encode())
        receipt = self.write_raw(
            f"{event_id}-sentinel.json",
            {
                "exists": True,
                "path": path,
                "sha256": sentinel_sha256,
                "nonce": nonce,
                "phase": "before-run",
            },
        )
        return {
            "event_id": event_id,
            "path": path,
            "request_sha256": digest(command.encode()),
            "receipt_path": receipt["path"],
            "receipt_sha256": receipt["sha256"],
            "sentinel_sha256": sentinel_sha256,
            "nonce": nonce,
        }

    def read_request(self, path):
        return json.dumps(
            {
                "cmd": preflight.read_probe_command(path),
                "shell": self.executor["shell_path"],
                "workdir": self.executor["working_directory"],
                "login": False,
            }
        )

    def write_inventory_receipt(self):
        sources = {
            "settings": (
                "config/read",
                {
                    "config": {"model": "gpt-test"},
                    "origins": {},
                    "layers": [
                        {
                            "name": {"type": "user"},
                            "version": "1",
                            "config": {"model": "gpt-test"},
                        },
                        {
                            "name": {"type": "project"},
                            "version": "2",
                            "config": {},
                            "disabledReason": "outside project root",
                        },
                    ],
                },
            ),
            "instructions": (
                "thread/start",
                {"instructionSources": ["C:/workspace/AGENTS.md"]},
            ),
            "skills": (
                "skills/list",
                {"data": [{"cwd": "C:/workspace", "skills": [], "errors": []}]},
            ),
            "plugins": (
                "plugin/list",
                {
                    "marketplaces": [],
                    "marketplaceLoadErrors": [],
                    "featuredPluginIds": [],
                },
            ),
            "mcp": (
                "mcpServerStatus/list",
                {"data": [], "nextCursor": None},
            ),
            "tools": ("tools/list", {"tools": [{"name": "exec_command"}]}),
        }
        entries = {}
        for name, (source, value) in sources.items():
            entries[name] = {
                "source": source,
                **self.write_raw(f"{name}.json", {"result": value}),
            }
        return {
            "kind": "Stage2RuntimeInventoryReceipt",
            "schema_version": "1.0.0",
            "entries": entries,
        }

    def write_sessions(self, *, context=None, include_child=True, read_output=None):
        context = self.context if context is None else context
        read_output = self.nonce if read_output is None else read_output
        events = [
            {"type": "session_meta", "payload": {"id": "thread-primary"}},
            {"type": "turn_context", "payload": context},
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "call-read",
                    "arguments": self.read_request("source.txt"),
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "call-read",
                    "output": read_output,
                },
            },
        ]
        self.write_jsonl("primary.jsonl", events)
        self.write_stdout(
            [
                {
                    "type": "item.completed",
                    "item": {
                        "id": "call-write",
                        "type": "command_execution",
                        "status": "completed",
                        "command": "write created.txt",
                        "exit_code": 0,
                        "aggregated_output": "created",
                    },
                },
                {
                    "type": "item.completed",
                    "item": {
                        "id": "search-1",
                        "type": "web_search",
                        "status": "completed",
                        "query": "bounded query",
                        "results": [{"url": "https://example.test/result"}],
                    },
                },
                {
                    "type": "item.completed",
                    "item": {
                        "id": "child-1",
                        "type": "subagent_call",
                        "status": "completed",
                        "thread_id": "thread-child",
                        "result": "bounded child result",
                    },
                },
                *[
                    {
                        "type": "item.completed",
                        "item": {
                            "id": event_id,
                            "type": "command_execution",
                            "status": "failed",
                            "command": self.read_request(path),
                            "exit_code": 1,
                            "aggregated_output": "Permission denied by sandbox policy",
                        },
                    }
                    for event_id, path in (
                        ("deny-judge", "C:/sealed/judge.txt"),
                        ("deny-peer", "C:/sealed/peer.txt"),
                        ("deny-expected", "C:/sealed/expected.json"),
                    )
                ],
            ]
        )
        child = self.sessions / "child.jsonl"
        if include_child:
            self.write_jsonl(
                "child.jsonl",
                [
                    {"type": "session_meta", "payload": {"id": "thread-child"}},
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {"type": "output_text", "text": "child result"}
                            ],
                        },
                    },
                ],
            )
        elif child.exists():
            child.unlink()

    def inspect(self, spec=None, inventory_receipt="default"):
        if inventory_receipt == "default":
            inventory_receipt = self.inventory_receipt
        with patch.object(
            preflight, "verify_capture", return_value=(self.record, "ok")
        ):
            return preflight.inspect_preflight(
                self.capture,
                "a" * 64,
                self.spec if spec is None else spec,
                inventory_receipt=inventory_receipt,
            )

    def test_positive_fixture_binds_real_events_contexts_and_bytes(self):
        report = self.inspect()
        self.assertEqual(report["kind"], "Stage2RuntimePreflight")
        self.assertEqual(report["schema_version"], "1.0.0")
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["runtime_gate"])
        self.assertFalse(report["formal_ready"])
        self.assertFalse(report["scientific_improvement"])
        self.assertEqual(report["primary_thread_id"], "thread-primary")
        self.assertEqual(
            set(report["capabilities"]),
            {"read", "write", "search", "child", "isolation"},
        )
        self.assertTrue(
            all(
                value["status"] == "passed" for value in report["capabilities"].values()
            )
        )
        self.assertGreaterEqual(len(report["archive_files"]), 4)
        self.assertEqual(
            [
                row["state"]
                for row in report["inventory"]["settings"]["value"]["layers"]
            ],
            ["active", "disabled"],
        )

    def test_verify_recomputes_exact_report_and_rejects_tampering(self):
        report = self.inspect()
        with patch.object(
            preflight, "verify_capture", return_value=(self.record, "ok")
        ):
            self.assertEqual(
                preflight.verify_preflight(
                    report,
                    self.capture,
                    "a" * 64,
                    self.spec,
                    inventory_receipt=self.inventory_receipt,
                ),
                report,
            )
            changed = copy.deepcopy(report)
            changed["runtime_gate"] = False
            with self.assertRaisesRegex(preflight.PreflightError, "does not equal"):
                preflight.verify_preflight(
                    changed,
                    self.capture,
                    "a" * 64,
                    self.spec,
                    inventory_receipt=self.inventory_receipt,
                )
        (self.end / "created.txt").write_bytes(b"tampered")
        with patch.object(
            preflight, "verify_capture", return_value=(self.record, "ok")
        ):
            with self.assertRaisesRegex(preflight.PreflightError, "does not equal"):
                preflight.verify_preflight(
                    report,
                    self.capture,
                    "a" * 64,
                    self.spec,
                    inventory_receipt=self.inventory_receipt,
                )

    def test_wrong_thread_policy_and_model_are_not_accepted(self):
        for mutation, reason in (
            (("thread", "wrong-thread"), "primary-session-missing"),
            (("sandbox", {"type": "read-only"}), "sandbox-not-workspace-write"),
            (
                (
                    "permission",
                    {
                        "type": "managed",
                        "file_system": {
                            "type": "restricted",
                            "entries": [
                                {
                                    "path": {
                                        "type": "special",
                                        "value": {"kind": "project_roots"},
                                    },
                                    "access": "read",
                                }
                            ],
                        },
                        "network": "restricted",
                    },
                ),
                "permission-profile-readonly",
            ),
            (
                (
                    "permission",
                    {
                        "type": "managed",
                        "file_system": {"type": "unrestricted"},
                        "network": "enabled",
                    },
                ),
                "permission-profile-danger-unrestricted",
            ),
            (("model", "wrong-model"), "model-mismatch"),
        ):
            with self.subTest(reason=reason):
                if mutation[0] == "thread":
                    self.record["event_summary"]["thread_id"] = mutation[1]
                else:
                    changed = copy.deepcopy(self.context)
                    if mutation[0] == "sandbox":
                        changed["sandbox_policy"] = mutation[1]
                    elif mutation[0] == "permission":
                        changed["permission_profile"] = mutation[1]
                    else:
                        changed["model"] = mutation[1]
                    self.write_sessions(context=changed)
                report = self.inspect()
                self.assertEqual(report["status"], "blocked")
                self.assertIn(reason, report["blockers"])
                self.record["event_summary"]["thread_id"] = "thread-primary"
                self.write_sessions()

    def test_complete_process_with_denied_required_tool_is_blocked(self):
        self.write_sessions(read_output="Permission denied")
        report = self.inspect()
        self.assertEqual(report["capabilities"]["read"]["status"], "failed")
        self.assertFalse(report["runtime_gate"])

    def test_declaration_without_action_and_unrelated_event_do_not_pass(self):
        spec = copy.deepcopy(self.spec)
        spec["probes"]["search"]["event_id"] = "declared-only"
        report = self.inspect(spec)
        self.assertEqual(report["capabilities"]["search"]["status"], "unknown")
        spec = copy.deepcopy(self.spec)
        spec["probes"]["read"]["event_id"] = "search-1"
        spec["probes"]["search"]["event_id"] = "declared-only"
        with self.assertRaisesRegex(preflight.PreflightError, "exposed"):
            self.inspect(spec)

    def test_probe_must_match_source_and_each_sentinel(self):
        spec = copy.deepcopy(self.spec)
        spec["probes"]["read"]["source_path"] = "missing.txt"
        self.assertEqual(
            self.inspect(spec)["capabilities"]["read"]["status"], "unknown"
        )
        spec = copy.deepcopy(self.spec)
        spec["probes"]["isolation"]["sentinels"]["judge"]["path"] = "C:/other.txt"
        report = self.inspect(spec)
        self.assertEqual(report["capabilities"]["isolation"]["status"], "failed")

    def test_missing_child_result_is_blocked(self):
        self.write_sessions(include_child=False)
        report = self.inspect()
        self.assertEqual(report["capabilities"]["child"]["status"], "unknown")
        self.assertIn("child-session-result-missing", report["blockers"])

    def test_unknown_inventory_is_blocked_without_inventing_empty_lists(self):
        changed = copy.deepcopy(self.context)
        del changed["capability_inventory"]["plugins"]
        self.write_sessions(context=changed)
        report = self.inspect(inventory_receipt=None)
        self.assertEqual(report["inventory"]["plugins"]["status"], "unknown")
        self.assertIsNone(report["inventory"]["plugins"]["value"])
        self.assertIn("inventory-plugins-unknown", report["blockers"])
        self.assertEqual(report["inventory"]["skills"]["status"], "unknown")
        self.assertEqual(
            report["inventory"]["skills"]["synthetic_context_value"], ["stage2"]
        )
        self.assertIn("inventory-skills-unknown", report["blockers"])

    def test_inventory_raw_response_tamper_is_rejected(self):
        settings = self.inventory_receipt["entries"]["settings"]
        (self.capture / settings["path"]).write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(preflight.PreflightError, "raw-response hash"):
            self.inspect()

    def test_isolation_rejects_spoof_unrelated_missing_and_absent_sentinel(self):
        cases = (
            {
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": "Permission denied by sandbox policy",
            },
            {"command": json.dumps({"cmd": "echo unrelated"})},
            {
                "status": "failed",
                "exit_code": 1,
                "aggregated_output": "No such file",
            },
        )
        for updates in cases:
            with self.subTest(updates=updates):
                self.write_sessions()
                self.mutate_stdout_item("deny-judge", **updates)
                report = self.inspect()
                self.assertEqual(
                    report["capabilities"]["isolation"]["status"], "failed"
                )

        spec = copy.deepcopy(self.spec)
        judge = spec["probes"]["isolation"]["sentinels"]["judge"]
        path = self.capture / judge["receipt_path"]
        absent = {
            "exists": False,
            "path": judge["path"],
            "sha256": judge["sentinel_sha256"],
            "nonce": judge["nonce"],
            "phase": "before-run",
        }
        raw = (json.dumps(absent, sort_keys=True) + "\n").encode()
        path.write_bytes(raw)
        judge["receipt_sha256"] = digest(raw)
        report = self.inspect(spec)
        self.assertEqual(report["capabilities"]["isolation"]["status"], "failed")

    def test_ambiguous_primary_and_malformed_spec_raise(self):
        original = (self.sessions / "primary.jsonl").read_text(encoding="utf-8")
        (self.sessions / "duplicate.jsonl").write_text(original, encoding="utf-8")
        with self.assertRaisesRegex(preflight.PreflightError, "ambiguous primary"):
            self.inspect()
        (self.sessions / "duplicate.jsonl").unlink()
        malformed = copy.deepcopy(self.spec)
        del malformed["probes"]["write"]["sha256"]
        with self.assertRaisesRegex(preflight.PreflightError, "write probe fields"):
            self.inspect(malformed)

    def test_forged_denial_with_rehashed_request_cannot_pass(self):
        spec = copy.deepcopy(self.spec)
        for sentinel in spec["probes"]["isolation"]["sentinels"].values():
            command = json.dumps(
                {
                    "cmd": "echo 'Permission denied by sandbox policy'; exit 1 # "
                    + sentinel["path"]
                }
            )
            sentinel["request_sha256"] = digest(command.encode())
            self.mutate_stdout_item(sentinel["event_id"], command=command)
        self.assertFalse(self.inspect(spec)["runtime_gate"])

    def test_inventory_errors_and_incomplete_pages_block(self):
        for name, value in (
            ("skills", {"data": [{"skills": [], "errors": ["load failed"]}]}),
            ("plugins", {"marketplaces": [], "marketplaceLoadErrors": ["failed"]}),
            ("mcp", {"data": [], "nextCursor": "more-pages"}),
            ("tools", {"tools": [], "nextCursor": "more-pages"}),
        ):
            with self.subTest(name=name):
                receipt = copy.deepcopy(self.inventory_receipt)
                receipt["entries"][name].update(
                    self.write_raw(name + "-bad.json", {"result": value})
                )
                report = self.inspect(inventory_receipt=receipt)
                self.assertEqual(report["inventory"][name]["status"], "unknown")
                self.assertFalse(report["runtime_gate"])

    def test_foreign_tool_or_changed_shell_and_workdir_cannot_prove_isolation(self):
        self.mutate_stdout_item(
            "deny-judge", type="mcp_tool_call", server="foreign", tool="pretend"
        )
        self.assertFalse(self.inspect()["runtime_gate"])
        for key, value in (
            ("shell", "C:/workspace/fake-denial-shell.exe"),
            ("workdir", "C:/unrelated"),
            ("login", True),
        ):
            with self.subTest(key=key):
                self.write_sessions()
                spec = copy.deepcopy(self.spec)
                sentinel = spec["probes"]["isolation"]["sentinels"]["judge"]
                request = json.loads(self.read_request(sentinel["path"]))
                request[key] = value
                command = json.dumps(request)
                sentinel["request_sha256"] = digest(command.encode())
                self.mutate_stdout_item("deny-judge", command=command)
                self.assertFalse(self.inspect(spec)["runtime_gate"])

    def test_shell_bytes_and_working_directory_are_bound_to_host_archive(self):
        spec = copy.deepcopy(self.spec)
        spec["executor"]["working_directory"] = "C:/unrelated"
        with self.assertRaisesRegex(preflight.PreflightError, "working directory"):
            self.inspect(spec)
        (self.capture / "archive/config_bindings/probe_shell").write_bytes(
            b"changed shell"
        )
        with self.assertRaisesRegex(preflight.PreflightError, "shell bytes"):
            self.inspect()

    def test_read_nonce_in_prompt_config_or_context_is_rejected(self):
        for relative in (
            "archive/prompt.bin",
            "archive/profile-config.toml",
            "archive/input_bindings/injected.txt",
        ):
            with self.subTest(relative=relative):
                path = self.capture / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(self.nonce, encoding="utf-8")
                with self.assertRaisesRegex(preflight.PreflightError, "exposed"):
                    self.inspect()
                path.unlink()
        changed = copy.deepcopy(self.context)
        changed["instructions"] = "read answer: " + self.nonce
        self.write_sessions(context=changed)
        with self.assertRaisesRegex(preflight.PreflightError, "exposed"):
            self.inspect()

    def test_echoed_read_answer_is_rejected(self):
        path = self.sessions / "primary.jsonl"
        events = [json.loads(line) for line in path.read_text().splitlines()]
        events[2]["payload"]["arguments"] = json.dumps(
            {"cmd": "echo " + self.nonce + " # source.txt"}
        )
        self.write_jsonl("primary.jsonl", events)
        with self.assertRaisesRegex(preflight.PreflightError, "exposed"):
            self.inspect()

    def test_windows_rooted_drive_and_parent_paths_are_rejected_on_all_hosts(self):
        for value in (
            r"\Windows\win.ini",
            "C:relative.txt",
            r"C:\absolute.txt",
            r"..\escape.txt",
            r"\\server\share",
            "/etc/passwd",
        ):
            for probe, field in (("read", "source_path"), ("write", "output_path")):
                with self.subTest(value=value, probe=probe):
                    spec = copy.deepcopy(self.spec)
                    spec["probes"][probe][field] = value
                    with self.assertRaisesRegex(preflight.PreflightError, "contained"):
                        self.inspect(spec)

    def test_blocked_cli_returns_nonzero(self):
        from stage2_live import __main__ as cli

        probe = self.capture / "probe.json"
        probe.write_text(json.dumps(self.spec), encoding="utf-8")
        with (
            patch.object(cli, "inspect_preflight", return_value={"status": "blocked"}),
            redirect_stdout(io.StringIO()),
        ):
            code = cli.main(
                [
                    "preflight",
                    "--capture",
                    str(self.capture),
                    "--receipt",
                    "a" * 64,
                    "--probe",
                    str(probe),
                    "--output",
                    str(self.capture / "cli-result.json"),
                ]
            )
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
