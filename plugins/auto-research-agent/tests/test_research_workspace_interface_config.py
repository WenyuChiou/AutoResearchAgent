"""Synthetic config safety; no file inventories, processes or model calls."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from research_workspace.interface_config import compile_config

PLUGIN = Path(__file__).resolve().parents[1]


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")


class InterfaceConfigTests(unittest.TestCase):
    def setUp(self):
        self.contract = (
            PLUGIN / "references/research-workspace/workspace-interface.v1.json"
        ).read_bytes()
        self.schema = (
            PLUGIN / "cli/research_workspace/WorkspaceUiConfig.v1.schema.json"
        ).read_bytes()
        self.config = {
            "kind": "WorkspaceUiConfig",
            "schema_version": "1.0.0",
            "interface_sha256": sha256(self.contract).hexdigest(),
            "views": [
                {
                    "ref": "synthetic-case",
                    "label": "Unverified inventory",
                    "manifest": "C:/not-a-view/manifest.json",
                    "sha256": "a" * 64,
                    "fixture": True,
                }
            ],
            "presentation": {"language": "en", "density": "comfortable"},
            "native": {"mode": "disabled"},
            "maintenance": {"mode": "disabled"},
        }

    def compile(self, value=None, raw=None, **overrides):
        raw = encoded(value or self.config) if raw is None else raw
        options = {
            "expected_sha256": sha256(raw).hexdigest(),
            "contract_raw": self.contract,
            "expected_contract_sha256": sha256(self.contract).hexdigest(),
            "schema_raw": self.schema,
            "expected_schema_sha256": sha256(self.schema).hexdigest(),
        }
        options.update(overrides)
        return compile_config(raw, **options)

    def test_renderer_changes_do_not_change_sources_or_mutate_input(self):
        before = deepcopy(self.config)
        expected = {"views": before["views"]}
        for language in ("en", "zh-Hans", "zh-Hant"):
            changed = deepcopy(before)
            changed["presentation"]["language"] = language
            result = self.compile(changed)
            self.assertEqual(result["host_config"], expected)
            result["host_config"]["views"][0]["ref"] = "changed"
            self.assertEqual(changed["views"], expected["views"])
        self.assertEqual(before, self.config)

    def test_registered_mode_declaration_never_creates_authority(self):
        value = deepcopy(self.config)
        value["native"] = {"mode": "server-registered", "runtime_ref": "owner"}
        value["maintenance"] = {"mode": "record-only", "inbox_ref": "inbox"}
        state = self.compile(value)["capability_state"]
        self.assertEqual(state["native"], "declared-not-activated")
        self.assertEqual(state["maintenance"], "declared-not-activated")
        self.assertEqual(state["source_inventory"], "requires-load-views")
        self.assertIs(state["execution_authority"], False)

    def test_pins_and_interface_cannot_be_substituted(self):
        for field in (
            "expected_sha256",
            "expected_contract_sha256",
            "expected_schema_sha256",
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.compile(**{field: "0" * 64})
        value = deepcopy(self.config)
        value["interface_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            self.compile(value)

    def test_duplicate_keys_refs_authority_and_unknown_version_reject(self):
        values = []
        for field, value in (("schema_version", "2.0.0"), ("owner", "caller")):
            changed = deepcopy(self.config)
            changed[field] = value
            values.append(changed)
        changed = deepcopy(self.config)
        changed["views"].append(deepcopy(changed["views"][0]))
        values.append(changed)
        changed = deepcopy(self.config)
        changed["native"] = {"mode": "launch", "command": "codex"}
        values.append(changed)
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.compile(value)
        for raw in (b'{"a":1,"a":2}', b'{"x":NaN}', b"\xff"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.compile(raw=raw)

    def test_external_schema_resolution_never_occurs(self):
        schema = json.loads(self.schema)
        schema["properties"]["views"] = {"$ref": "https://example.invalid/schema"}
        raw = encoded(schema)
        with self.assertRaises(ValueError):
            self.compile(schema_raw=raw, expected_schema_sha256=sha256(raw).hexdigest())


if __name__ == "__main__":
    unittest.main()
