"""Exercise the common entry point with pinned saved views and existing objects."""

from pathlib import Path
import unittest
from unittest.mock import patch

from research_workspace_native.host_config import HostRegistry, create_host, load_config
from research_workspace_native.maintenance_inbox import MaintenanceInbox
from stage1_deliverable.common import canonical, sha
import test_research_workspace_atlas_host as host_fixtures

PLUGIN = Path(__file__).parents[1]


class HostConfigTests(unittest.TestCase):
    save_config = host_fixtures.AtlasHostTests.save_config
    setUp = host_fixtures.AtlasHostTests.setUp

    def semantic(self):
        contract = PLUGIN / "references/research-workspace/workspace-interface.v1.json"
        schema = PLUGIN / "cli/research_workspace/WorkspaceUiConfig.v1.schema.json"
        raw = canonical(
            dict(
                kind="WorkspaceUiConfig",
                schema_version="1.0.0",
                interface_sha256=sha(contract.read_bytes()),
                views=self.entries,
                presentation=dict(language="zh-Hant", density="compact"),
                native=dict(mode="server-registered", runtime_ref="absent"),
                maintenance=dict(mode="record-only", inbox_ref="feedback"),
            )
        )
        self.config.write_bytes(raw)
        return dict(
            expected_sha256=sha(raw),
            contract_path=contract,
            expected_contract_sha256=sha(contract.read_bytes()),
            schema_path=schema,
            expected_schema_sha256=sha(schema.read_bytes()),
        )

    def test_legacy_and_semantic_entry_preserve_source_inventory(self):
        legacy = load_config(self.config, self.pin)
        pins = self.semantic()
        semantic = load_config(self.config, **pins)
        self.assertEqual(semantic["files"], legacy["files"])
        self.assertEqual(semantic["views"], legacy["views"])
        self.assertEqual(
            load_config(str(self.config), **pins)["views"], legacy["views"]
        )
        self.assertEqual(
            semantic["presentation"], dict(language="zh-Hant", density="compact")
        )
        for field in (
            "expected_sha256",
            "expected_contract_sha256",
            "expected_schema_sha256",
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                load_config(self.config, **dict(pins, **{field: "0" * 64}))

    def test_absent_registry_objects_do_not_launch_or_enable_feedback(self):
        config = load_config(self.config, **self.semantic())
        with patch("subprocess.Popen", side_effect=AssertionError("implicit launch")):
            server = create_host(config)
            try:
                self.assertIsNone(server.maintenance)
                self.assertEqual(
                    server.capability_state,
                    dict(native="unavailable", maintenance="unavailable"),
                )
                bootstrap = server._assets["/views/stage1/atlas.html"].decode()
                self.assertIn('data-atlas-density="compact"', bootstrap)
                self.assertIn('lang="zh-Hant"', bootstrap)
            finally:
                server.server_close()

    def test_registered_inbox_has_exact_bindings_and_survives_host_close(self):
        config = load_config(self.config, **self.semantic())
        bindings = {
            row["ref"]: {
                name: row[name]
                for name in ("project_id", "index_sha256", "manifest_sha256")
            }
            for row in config["views"]
        }
        inbox = MaintenanceInbox(self.root / "feedback.sqlite", bindings)
        registry = HostRegistry(inboxes={"feedback": inbox})
        server = create_host(config, registry=registry)
        server.maintenance.submit(
            "stage1", 1, "Saved original feedback", "config-feedback"
        )
        server.server_close()
        self.assertEqual(
            inbox.get("stage1", "config-feedback")["message"], "Saved original feedback"
        )
        inbox.close()
        reopened = MaintenanceInbox(self.root / "feedback.sqlite", bindings)
        try:
            self.assertEqual(
                reopened.get("stage1", "config-feedback")["status"],
                "recorded-not-dispatched",
            )
        finally:
            reopened.close()
        with self.assertRaises(ValueError):
            HostRegistry(inboxes={"feedback": str(self.root / "feedback.sqlite")})
