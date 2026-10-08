import copy
import hashlib
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

TESTS = Path(__file__).resolve().parent
CLI = TESTS.parent / "cli"
sys.path[:0] = [str(CLI), str(TESTS)]

from stage2_common import Stage2Error  # noqa: E402
from stage2_live import native, observation, trace_producer  # noqa: E402
import test_stage2_trace_producer as fixture  # noqa: E402
from test_stage2_named_policy import _config, _policy  # noqa: E402


class ActionTraceRootTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.TraceProducerTests(methodName="runTest")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.telemetry = self.case.telemetry
        self.capture_root = self.case.root / "captures"
        self.capture_root.mkdir()
        config = _config(
            self.case.workspace,
            self.case.home,
            self.telemetry,
            self.capture_root,
        )
        (self.case.home / "config.toml").write_bytes(config)
        self.case.policy = {
            **_policy(config, self.telemetry),
            "schema_version": "1.1.0",
            "capture_root": str(self.capture_root),
        }
        self.scope_file = self.case.home / "native-namespace.json"
        self.scope_file.write_bytes(b'{"synthetic":true}\n')
        self.scope = {
            "codex": str(self.case.codex),
            "home": str(self.case.home),
            "workspace": str(self.case.workspace),
            "telemetry": str(self.telemetry),
            "capture_root": str(self.capture_root),
        }

    def binding(self, trace_root=None):
        value = {
            "path": str(self.scope_file),
            "sha256": hashlib.sha256(self.scope_file.read_bytes()).hexdigest(),
            "scope": copy.deepcopy(self.scope),
            "dispatcher_sha256": "d" * 64,
        }
        if trace_root is not None:
            value["trace_root"] = str(Path(trace_root).resolve())
        return value

    def bind(self, codex, home, workspace=None, *, trace_root=None):
        self.assertEqual(str(Path(codex).resolve()), self.scope["codex"])
        self.assertEqual(str(Path(home).resolve()), self.scope["home"])
        if workspace is not None:
            self.assertEqual(str(Path(workspace).resolve()), self.scope["workspace"])
        return self.binding(trace_root)

    def wrap(self, command, binding, *, output_sink=None):
        if binding and "trace_root" in binding and "-o" in command:
            self.assertIsNotNone(output_sink)
            self.assertTrue(output_sink.is_file())
            self.assertEqual(command[command.index("-o") + 1], str(output_sink))
        return command if binding is None else ["bwrap", "--"] + command

    def produce(self, action, *, resume=False, receipt=None, include_trace=True):
        trace_root = self.telemetry / action
        capture = self.capture_root / action
        if not trace_root.exists():
            trace_root.mkdir()
        self.case.telemetry = trace_root
        self.case.capture = capture
        updates = {"resume": resume, "producer_receipt": receipt}
        if include_trace:
            updates["trace_root"] = str(trace_root)
        with patch.dict(os.environ, {"CODEX_ROLLOUT_TRACE_ROOT": str(trace_root)}):
            return self.case._produce(**updates)

    def test_two_action_children_capture_and_replay_without_reexecution(self):
        with (
            patch.object(native, "bind_namespace", side_effect=self.bind),
            patch.object(native, "wrap_namespace", side_effect=self.wrap),
            patch.object(observation, "bind_namespace", side_effect=self.bind),
            patch.object(observation, "wrap_namespace", side_effect=self.wrap),
        ):
            first = self.produce("action-one")
            first_replay = self.produce(
                "action-one", resume=True, receipt=first["producer_receipt"]
            )
            second = self.produce("action-two")
            second_replay = self.produce(
                "action-two", resume=True, receipt=second["producer_receipt"]
            )

        self.assertEqual(first_replay["resume_action"], "verified-replay-no-execution")
        self.assertEqual(second_replay["resume_action"], "verified-replay-no-execution")
        self.assertEqual((self.case.calls, self.case.rpc_calls), (2, 2))
        self.assertNotEqual(first["producer_receipt"], second["producer_receipt"])
        for action, produced in (("action-one", first), ("action-two", second)):
            selected = str(self.telemetry / action)
            namespace = produced["capture"]["stable_request_binding"][
                "native_namespace"
            ]
            self.assertEqual(namespace["trace_root"], selected)
            observed = trace_producer._json(
                (
                    self.telemetry / action / "bundle/inventory/observation.json"
                ).read_bytes(),
                "observation.json",
            )
            self.assertEqual(observed["binding"]["native_namespace"], namespace)
            self.assertTrue((self.capture_root / action / "run.json").is_file())

    def test_changed_or_dropped_child_rejects_without_reexecution(self):
        with (
            patch.object(native, "bind_namespace", side_effect=self.bind),
            patch.object(native, "wrap_namespace", side_effect=self.wrap),
            patch.object(observation, "bind_namespace", side_effect=self.bind),
            patch.object(observation, "wrap_namespace", side_effect=self.wrap),
        ):
            first = self.produce("action-one")
            with self.assertRaisesRegex(Stage2Error, "telemetry-binding-mismatch"):
                self.produce(
                    "action-one",
                    resume=True,
                    receipt=first["producer_receipt"],
                    include_trace=False,
                )
            self.produce("action-two")
            with self.assertRaisesRegex(Stage2Error, "receipt-mismatch"):
                self.produce(
                    "action-two",
                    resume=True,
                    receipt=first["producer_receipt"],
                )
        self.assertEqual((self.case.calls, self.case.rpc_calls), (2, 2))

    def test_legacy_and_invalid_action_roots(self):
        with patch.dict(os.environ, {"CODEX_ROLLOUT_TRACE_ROOT": str(self.telemetry)}):
            self.assertEqual(
                trace_producer._telemetry(_policy(b"x", self.telemetry)),
                self.telemetry,
            )
        with patch.object(native, "bind_namespace", return_value=None):
            request = trace_producer._request(self.case._args())
        self.assertNotIn("native_namespace", request)

        outside = self.case.root / "outside"
        outside.mkdir()
        child = self.telemetry / "child"
        child.mkdir()
        link = self.telemetry / "linked"
        try:
            link.symlink_to(child, target_is_directory=True)
        except OSError:
            link = None
        for label, selected in (
            ("root", self.telemetry),
            ("outside", outside),
            ("symlink", link),
        ):
            if selected is None:
                continue
            with (
                self.subTest(label=label),
                patch.dict(os.environ, {"CODEX_ROLLOUT_TRACE_ROOT": str(selected)}),
                self.assertRaisesRegex(Stage2Error, "action-trace-root"),
            ):
                trace_producer._telemetry(self.case.policy, str(selected))

        legacy = {**self.case.policy, "schema_version": "1.0.0"}
        legacy.pop("capture_root")
        with (
            patch.dict(os.environ, {"CODEX_ROLLOUT_TRACE_ROOT": str(child)}),
            self.assertRaisesRegex(Stage2Error, "requires-policy-1.1"),
        ):
            trace_producer._telemetry(legacy, str(child))


if __name__ == "__main__":
    unittest.main()
