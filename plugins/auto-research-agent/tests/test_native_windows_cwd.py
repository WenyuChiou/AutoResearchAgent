"""Exact cwd separator compatibility; synthetic transport, no native process."""

import atlas_test_paths  # noqa: F401
import json
import unittest
from unittest.mock import patch

import test_research_workspace_native_bootstrap as fixture
from research_workspace_native.bootstrap import _cwd_matches


class WindowsCwdTests(unittest.TestCase):
    setUp = fixture.BootstrapTests.setUp
    state = fixture.BootstrapTests.state
    bootstrap = fixture.BootstrapTests.bootstrap
    responses = fixture.BootstrapTests.responses

    def test_only_windows_separators_are_equivalent(self):
        requested = "D:/private/project"
        self.assertTrue(_cwd_matches("D:\\private\\project", requested, windows=True))
        self.assertFalse(_cwd_matches("D:\\private\\project", requested, windows=False))
        self.assertTrue(_cwd_matches(requested, requested, windows=False))
        for wrong in (
            "d:/private/project",
            "D:/private/./project",
            "D:/private/other",
            "private/project",
            "D:/private/../project",
            None,
            {},
        ):
            self.assertFalse(_cwd_matches(wrong, requested, windows=True))

    def test_changed_separators_bind_same_thread_without_model_turn(self):
        boot = self.bootstrap()
        self.responses()
        reply = json.loads(self.channel.reads[-1])
        requested = self.params["cwd"]
        reply["result"]["cwd"] = (
            requested.replace("\\", "/")
            if "\\" in requested
            else requested.replace("/", "\\")
        )
        self.channel.reads[-1] = json.dumps(reply).encode() + b"\n"
        with patch(
            "research_workspace_native.bootstrap._cwd_matches",
            side_effect=lambda a, b: _cwd_matches(a, b, windows=True),
        ):
            boot.open_thread(dict(name="synthetic-client", version="1"))
        self.assertEqual(self.state()["bootstrap"]["phase"], "ready")
        self.assertFalse(
            any(row.get("method") == "turn/start" for row in self.channel.messages())
        )

    def test_different_root_retains_unknown_failure_and_never_retries(self):
        boot = self.bootstrap()
        self.responses()
        reply = json.loads(self.channel.reads[-1])
        reply["result"]["cwd"] = self.params["cwd"] + "/different"
        self.channel.reads[-1] = json.dumps(reply).encode() + b"\n"
        with self.assertRaises(ValueError):
            boot.open_thread(dict(name="synthetic-client", version="1"))
        self.assertEqual(
            self.state()["intents"]["new-session"]["status"], "execution-unknown"
        )
        calls = list(self.channel.calls)
        with self.assertRaises(ValueError):
            boot.open_thread(dict(name="synthetic-client", version="1"))
        self.assertEqual(self.channel.calls, calls)


if __name__ == "__main__":
    unittest.main()
