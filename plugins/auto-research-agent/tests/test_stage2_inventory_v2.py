"""Contract tests for the supported Stage 2 runtime inventory v2 receipt."""

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from stage2_live import preflight


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Stage2InventoryV2Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.capture = Path(self.temporary.name) / "capture"
        self.bootstrap = self.capture / "bootstrap"
        self.transport = self.capture / "archive/transport"
        self.bootstrap.mkdir(parents=True)
        self.transport.mkdir(parents=True)
        sources = {
            "settings": (
                "config/read",
                {"config": {}, "origins": {}, "layers": []},
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
                {"marketplaces": [], "marketplaceLoadErrors": []},
            ),
            "mcp": (
                "mcpServerStatus/list",
                {"data": [], "nextCursor": None},
            ),
        }
        entries = {}
        for name, (source, value) in sources.items():
            entries[name] = {
                "source": source,
                **self.write_json(self.bootstrap / f"{name}.json", {"result": value}),
            }
        self.receipt = {
            "kind": "Stage2RuntimeInventoryReceipt",
            "schema_version": "2.0.0",
            "entries": entries,
        }

    def tearDown(self):
        self.temporary.cleanup()

    def write_json(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = (json.dumps(value, sort_keys=True) + "\n").encode()
        path.write_bytes(raw)
        return {
            "path": path.relative_to(self.capture).as_posix(),
            "sha256": digest(raw),
        }

    def captured_tools(self, value=None):
        request = (
            value
            if value is not None
            else {
                "tools": [
                    {
                        "type": "function",
                        "name": "exec_command",
                        "parameters": {"type": "object"},
                    },
                    {"type": "web_search"},
                ]
            }
        )
        value = {
            "kind": "Stage2NativeModelRequest",
            "schema_version": "1.0.0",
            "backend": "responses",
            "thread_id": "thread-primary",
            "request_id": "request-native-01",
            "request": {
                "model": "gpt-test",
                "input": [{"role": "user", "content": "probe"}],
                **request,
            },
        }
        binding = self.write_json(self.transport / "model-request.json", value)
        return {
            "status": "captured",
            "source": "native-model-request",
            **binding,
        }

    def inspect(self, receipt=None):
        archive_files = []
        inventory, receipt_sha = preflight._inventory(
            {"model": "gpt-test"},
            self.capture.resolve(),
            receipt or self.receipt,
            archive_files,
            "thread-primary",
        )
        return inventory, receipt_sha, archive_files

    def test_supported_responses_and_transport_tools_are_present(self):
        self.receipt["tools"] = self.captured_tools()

        inventory, receipt_sha, archive_files = self.inspect()

        self.assertEqual(set(inventory), set(preflight._INVENTORY_KEYS))
        self.assertTrue(all(item["status"] == "present" for item in inventory.values()))
        self.assertEqual(
            inventory["tools"]["value"]["tool_identities"],
            ["exec_command", "web_search"],
        )
        self.assertEqual(receipt_sha, preflight._canonical_hash(self.receipt))
        self.assertEqual(len(archive_files), 6)

    def test_missing_or_explicit_unknown_tools_remain_unknown(self):
        for tools in (
            None,
            {
                "status": "unknown",
                "source": "native-model-request",
                "path": None,
                "sha256": None,
            },
        ):
            with self.subTest(tools=tools):
                receipt = copy.deepcopy(self.receipt)
                if tools is not None:
                    receipt["tools"] = tools
                inventory, _, _ = self.inspect(receipt)
                self.assertEqual(inventory["tools"]["status"], "unknown")
                self.assertIsNone(inventory["tools"]["value"])

    def test_unknown_tools_block_the_existing_complete_inventory_gate(self):
        import test_stage2_preflight as fixture_module

        fixture = fixture_module.Stage2PreflightTests(
            "test_positive_fixture_binds_real_events_contexts_and_bytes"
        )
        fixture.setUp()
        try:
            receipt = copy.deepcopy(fixture.inventory_receipt)
            receipt["schema_version"] = "2.0.0"
            del receipt["entries"]["tools"]
            receipt["tools"] = {
                "status": "unknown",
                "source": "native-model-request",
                "path": None,
                "sha256": None,
            }

            report = fixture.inspect(inventory_receipt=receipt)

            self.assertFalse(report["runtime_gate"])
            self.assertFalse(report["formal_ready"])
            self.assertIn("inventory-tools-unknown", report["blockers"])
        finally:
            fixture.tearDown()

    def test_model_self_report_and_workspace_files_are_rejected(self):
        for relative in (
            "archive/workspace-start/model-request.json",
            "archive/workspace-end/model-request.json",
            "response/model-request.json",
        ):
            with self.subTest(relative=relative):
                receipt = copy.deepcopy(self.receipt)
                binding = self.write_json(
                    self.capture / relative,
                    {"tools": [{"name": "subject_claimed_tool"}]},
                )
                receipt["tools"] = {
                    "status": "captured",
                    "source": "native-model-request",
                    **binding,
                }
                with self.assertRaisesRegex(preflight.PreflightError, "transport"):
                    self.inspect(receipt)

    def test_tool_hash_tamper_is_rejected(self):
        self.receipt["tools"] = self.captured_tools()
        (self.transport / "model-request.json").write_text("{}\n", encoding="utf-8")

        with self.assertRaisesRegex(preflight.PreflightError, "hash differs"):
            self.inspect()

    def test_duplicate_or_malformed_tool_identities_are_rejected(self):
        bad_lists = (
            [
                {
                    "type": "function",
                    "name": "exec_command",
                    "parameters": {"type": "object"},
                },
                {
                    "type": "function",
                    "name": "exec_command",
                    "parameters": {"type": "object"},
                },
            ],
            [{"name": "exec_command"}],
            [{"name": "   "}],
            [{}],
            [],
        )
        for tools in bad_lists:
            with self.subTest(tools=tools):
                receipt = copy.deepcopy(self.receipt)
                receipt["tools"] = self.captured_tools({"tools": tools})
                with self.assertRaisesRegex(
                    preflight.PreflightError, "tool identities"
                ):
                    self.inspect(receipt)

    def test_request_catalog_wrong_runtime_and_malformed_status_fail_closed(self):
        self.receipt["tools"] = self.captured_tools()
        path = self.transport / "model-request.json"
        valid = json.loads(path.read_text(encoding="utf-8"))
        for change in ("catalog", "model", "thread", "backend", "input"):
            with self.subTest(change=change):
                value = copy.deepcopy(valid)
                if change == "catalog":
                    value = {
                        "kind": "ModelProviderCapabilities",
                        "tools": valid["request"]["tools"],
                    }
                elif change == "model":
                    value["request"]["model"] = "wrong-model"
                elif change == "thread":
                    value["thread_id"] = "other-thread"
                elif change == "backend":
                    value["backend"] = "capability-catalog"
                else:
                    value["request"]["input"] = []
                self.receipt["tools"].update(self.write_json(path, value))
                with self.assertRaises(preflight.PreflightError):
                    self.inspect()
        receipt = copy.deepcopy(self.receipt)
        receipt["tools"]["status"] = []
        with self.assertRaises(preflight.PreflightError):
            self.inspect(receipt)

    def test_transport_junction_to_workspace_cannot_establish_inventory(self):
        workspace = self.capture / "archive/workspace-end"
        workspace.mkdir()
        self.receipt["tools"] = self.captured_tools()
        raw = (self.transport / "model-request.json").read_bytes()
        (workspace / "model-request.json").write_bytes(raw)
        (self.transport / "model-request.json").unlink()
        self.transport.rmdir()
        if os.name == "nt":
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(self.transport), str(workspace)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        else:
            self.transport.symlink_to(workspace, target_is_directory=True)
        try:
            with self.assertRaisesRegex(preflight.PreflightError, "symlink|reparse"):
                self.inspect()
        finally:
            if os.name == "nt":
                self.transport.rmdir()
            else:
                self.transport.unlink()

    def test_unsupported_rpc_and_malformed_v2_receipts_are_rejected(self):
        mutations = []
        unsupported = copy.deepcopy(self.receipt)
        unsupported["entries"]["skills"]["source"] = "tools/list"
        mutations.append(unsupported)
        extra = copy.deepcopy(self.receipt)
        extra["entries"]["tools"] = {
            "source": "tools/list",
            "path": "bootstrap/tools.json",
            "sha256": "0" * 64,
        }
        mutations.append(extra)
        malformed = copy.deepcopy(self.receipt)
        malformed["entries"]["mcp"]["sha256"] = "not-a-hash"
        mutations.append(malformed)
        substituted = copy.deepcopy(self.receipt)
        substituted["tools"] = self.captured_tools()
        substituted["tools"]["source"] = "modelProvider/capabilities/read"
        mutations.append(substituted)

        for receipt in mutations:
            with self.subTest(receipt=receipt):
                with self.assertRaises(preflight.PreflightError):
                    self.inspect(receipt)


if __name__ == "__main__":
    unittest.main()
