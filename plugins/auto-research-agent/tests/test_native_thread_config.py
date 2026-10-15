"""Deny-only thread config: injected fixtures, no Codex/model execution."""

import atlas_test_paths  # noqa: F401 -- standalone discovery needs the local CLI.
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from research_workspace_native.runtime_spec import DENIED_THREAD_CONFIG, _thread_config
from atlas_native_runtime_fixtures import CompositionCase
import test_atlas_runtime_spec as spec_case
import test_research_workspace_native_bootstrap_context as boot_case
from stage1_deliverable.common import canonical, sha


def denied():
    return {
        **DENIED_THREAD_CONFIG,
        "mcp_servers.node_repl.enabled": False,
        "mcp_servers.research-literature.enabled": False,
    }


class DenySpecTests(unittest.TestCase):
    setUp = spec_case.RuntimeSpecTests.setUp
    load = spec_case.RuntimeSpecTests.load

    def test_optional_config_is_exact_and_does_not_create_store(self):
        original = denied()
        self.spec["thread_config"] = original
        result = self.load()[2]
        self.assertEqual(result["thread_config"], original)
        detached = _thread_config(original)
        detached["mcp_servers.node_repl.enabled"] = True
        self.assertFalse(original["mcp_servers.node_repl.enabled"])
        self.assertFalse(Path(self.spec["store_path"]).exists())

    def test_enabled_omitted_or_arbitrary_overrides_refuse_before_spawn(self):
        configurations = [
            {},
            {**denied(), "features.shell_tool": True},
            {**denied(), "features.shell_tool": 0},
            {**denied(), "mcp_servers.node_repl.enabled": True},
            {**denied(), "mcp_servers..enabled": False},
            {**denied(), "mcp_servers.a.url": "https://example.invalid"},
            {**denied(), "model": "different"},
            {**denied(), "web_search": "cached"},
            {**denied(), "provider.api_key": "forbidden-test-only-field"},
        ]
        with patch(
            "research_workspace_native.runtime_factory.OwnedProcessChannel.__init__"
        ) as child:
            for config in configurations:
                with self.subTest(keys=sorted(config)), self.assertRaises(ValueError):
                    self.load({**self.spec, "thread_config": config})
            child.assert_not_called()
        self.assertFalse(Path(self.spec["store_path"]).exists())


class DenyBootstrapTests(unittest.TestCase):
    setUp = boot_case.BootstrapContextTests.setUp
    context = boot_case.BootstrapContextTests.context

    def test_untrusted_recorded_config_refuses_before_epoch_and_keeps_intent(self):
        payload = deepcopy(
            self.store.snapshot("alpha")["intents"]["new-session"]["payload"]
        )
        payload["config"] = {**denied(), "features.shell_tool": True}
        self.store.bind_project("beta", "a" * 64)
        owner = self.store.acquire_owner("beta", "config-fixture")
        self.store.record_intent(
            "beta",
            owner,
            "bad-config",
            "thread/start",
            payload,
            self.store.snapshot("beta")["revision"],
        )
        before = self.store.snapshot("beta")
        with self.assertRaisesRegex(ValueError, "required tool denials"):
            self.context(project_id="beta", owner=owner, intent_key="bad-config")
        self.assertEqual(self.store.snapshot("beta"), before)
        self.assertEqual(self.channel.calls, [])
        self.assertEqual(self.channel.closed, 0)


class DenyCompositionTests(CompositionCase):
    def test_same_config_is_in_saved_intent_lifecycle_hash_and_fake_wire(self):
        self.spec["thread_config"] = denied()
        self.pin = self.save()
        runtime = self.compose()
        received = [
            json.loads(line)
            for line in (self.source / "received.jsonl").read_bytes().splitlines()
        ]
        frame = next(row for row in received if row.get("method") == "thread/start")
        self.assertEqual(frame["params"]["config"], self.spec["thread_config"])
        store = runtime._entries[0]["store"]
        state = store.snapshot(self.spec["project_id"])
        self.assertEqual(state["intents"]["new-thread"]["payload"], frame["params"])
        expected = sha(canonical(frame["params"]))
        claims = [
            row["action"]
            for row in self.observed
            if row.get("action", {}).get("method")
            in {"new-session", "thread/start", "handoff"}
        ]
        self.assertGreaterEqual(len(claims), 3)
        self.assertTrue(all(row["params_sha256"] == expected for row in claims))
        self.assertEqual(
            [row["method"] for row in received if row.get("method") == "turn/start"], []
        )
        self.assertTrue(runtime.shutdown()["repo-case"]["leader_reaped"])


if __name__ == "__main__":
    unittest.main()
