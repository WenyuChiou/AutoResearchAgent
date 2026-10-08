"""Synthetic native-witness tests using the shared observed fixture."""

import json
from pathlib import Path
import shlex
import sys
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from stage2_common import Stage2Error  # noqa: E402
from stage2_live import preflight_native_witnesses as preflight_observed
from stage2_live import preflight  # noqa: E402
from stage2_live.preflight import PreflightError  # noqa: E402

from stage2_observed_preflight_fixtures import ObservedPreflightFixture, _bytes


class NativeWitnessTests(ObservedPreflightFixture):
    def test_search_error_is_not_success(self):
        for text in (
            "Error: web search failed: network access denied",
            "Error: https://example.org/ \ue200cite\ue202turn0search0\ue201",
            "No results found",
        ):
            raw, _ = self._fixture()
            raw["payloads/search-call-result.json"] = _bytes(
                {"type": "code_mode_response", "value": text}
            )
            with self.assertRaisesRegex(PreflightError, "search-result"):
                preflight_observed._check_witnesses(
                    raw, "root-thread", self.spec, self.capture
                )

    def test_config_before_spawn_and_malformed_config_are_rejected(self):
        raw, rows = self._fixture()
        configured = next(
            row
            for row in rows
            if row["payload"].get("event_type") == "session_configured"
        )
        rows.remove(configured)
        rows.insert(0, configured)
        for number, row in enumerate(rows, 1):
            row["seq"] = number
        self._rewrite(raw, rows)
        with self.assertRaisesRegex(PreflightError, "child-config-mismatch"):
            preflight_observed._check_witnesses(
                raw, "root-thread", self.spec, self.capture
            )
        raw, _ = self._fixture()
        raw["payloads/child-configured.json"] = _bytes([])
        with self.assertRaisesRegex(PreflightError, "child-config-invalid"):
            preflight_observed._check_witnesses(
                raw, "root-thread", self.spec, self.capture
            )

    def test_matching_foreign_runtime_turns_are_rejected(self):
        raw, _ = self._fixture()
        for suffix in ("start", "end"):
            path = f"payloads/read-call-runtime-{suffix}.json"
            value = json.loads(raw[path])
            value["turn_id"] = "foreign-turn"
            raw[path] = _bytes(value)
        with self.assertRaisesRegex(PreflightError, "runtime-turn-mismatch"):
            preflight_observed._check_witnesses(
                raw, "root-thread", self.spec, self.capture
            )

    def test_alias_requires_execution_host_and_pinned_bytes(self):
        executor = {
            "shell_path": "/usr/bin/bash",
            "shell_sha256": "a" * 64,
            "family": "posix",
        }
        with mock.patch.object(preflight_observed.os, "name", "nt"):
            self.assertFalse(preflight_observed._same_shell("/bin/bash", executor))
        with (
            mock.patch.object(preflight_observed.os, "name", "posix"),
            mock.patch.object(
                preflight_observed.os.path, "samefile", return_value=True
            ),
            mock.patch.object(
                preflight_observed,
                "Path",
                return_value=mock.Mock(read_bytes=lambda: b"shell"),
            ),
        ):
            self.assertFalse(preflight_observed._same_shell("/bin/bash", executor))
            import hashlib

            executor["shell_sha256"] = hashlib.sha256(b"shell").hexdigest()
            self.assertTrue(preflight_observed._same_shell("/bin/bash", executor))

    def test_genuine_typed_witnesses_pass_with_immutable_refs(self):
        capabilities = preflight_observed._check_witnesses(
            self._fixture()[0], "root-thread", self.spec, self.capture
        )
        self.assertEqual(set(capabilities), {"read", "write", "search", "child"})
        self.assertTrue(
            all(item["status"] == "passed" for item in capabilities.values())
        )
        self.assertTrue(
            all(
                item["evidence_refs"] and item["event_id"].endswith("-call")
                for item in capabilities.values()
            )
        )

    def test_read_echo_or_arbitrary_code_is_rejected(self):
        for command in (
            f"echo {self.nonce}",
            f"{preflight.read_probe_command(self.spec['probes']['read']['command_path'], 'posix')}; id",
        ):
            with self.subTest(command=command):
                raw, _ = self._fixture()
                path = "payloads/read-call-invocation.json"
                invocation = json.loads(raw[path])
                arguments = json.loads(invocation["payload"]["arguments"])
                arguments["cmd"] = command
                invocation["payload"]["arguments"] = json.dumps(arguments)
                raw[path] = _bytes(invocation)
                with self.assertRaisesRegex(
                    PreflightError, "read-not-exact|runtime-binding"
                ):
                    preflight_observed._check_witnesses(
                        raw, "root-thread", self.spec, self.capture
                    )

    def test_early_nonce_disclosure_is_rejected(self):
        raw, _ = self._fixture()
        raw["payloads/initial-request.json"] = _bytes({"input": [self.nonce]})
        with self.assertRaisesRegex(PreflightError, "nonce-disclosed"):
            preflight_observed._check_witnesses(
                raw, "root-thread", self.spec, self.capture
            )

    def test_missing_or_failed_write_runtime_is_rejected(self):
        raw, rows = self._fixture()
        rows[:] = [
            row
            for row in rows
            if not (
                row["payload"].get("tool_call_id") == "write-call"
                and row["payload"]["type"] == "tool_call_runtime_ended"
            )
        ]
        for number, row in enumerate(rows, 1):
            row["seq"] = number
        self._rewrite(raw, rows)
        with self.assertRaisesRegex(Stage2Error, "runtime-end-missing"):
            preflight_observed._check_witnesses(
                raw, "root-thread", self.spec, self.capture
            )

        raw, _ = self._fixture()
        path = "payloads/write-call-runtime-end.json"
        runtime = json.loads(raw[path])
        runtime["exit_code"] = 1
        raw[path] = _bytes(runtime)
        with self.assertRaisesRegex(PreflightError, "runtime-failed"):
            preflight_observed._check_witnesses(
                raw, "root-thread", self.spec, self.capture
            )

    def test_write_must_attribute_the_exact_archived_bytes(self):
        target = str(Path(str(self.workspace)) / "output/result.txt")
        commands = (
            f"echo {shlex.quote(target)}",
            f"printf %s wrong-bytes > {shlex.quote(target)}",
            f"printf %s {shlex.quote(self.written.decode('utf-8'))} > {shlex.quote(target)}; id",
        )
        for command in commands:
            with self.subTest(command=command):
                raw, _ = self._fixture()
                self._change_tool_command(raw, "write-call", command)
                with self.assertRaisesRegex(PreflightError, "write-not-exact"):
                    preflight_observed._check_witnesses(
                        raw, "root-thread", self.spec, self.capture
                    )

    def test_empty_or_forged_search_is_rejected(self):
        for mutate, error in (
            (lambda invocation, result: result.update(value="  "), "result-empty"),
            (
                lambda invocation, result: invocation.update(
                    tool_namespace="synthetic"
                ),
                "tool-mismatch",
            ),
        ):
            raw, _ = self._fixture()
            invocation_path = "payloads/search-call-invocation.json"
            result_path = "payloads/search-call-result.json"
            invocation, result = (
                json.loads(raw[invocation_path]),
                json.loads(raw[result_path]),
            )
            mutate(invocation, result)
            raw[invocation_path], raw[result_path] = _bytes(invocation), _bytes(result)
            with self.assertRaisesRegex(PreflightError, error):
                preflight_observed._check_witnesses(
                    raw, "root-thread", self.spec, self.capture
                )

    def test_foreign_missing_or_changed_child_is_rejected(self):
        for mutation, error in (
            ("parent", "parent-mismatch"),
            ("missing", "lifecycle-incomplete"),
            ("model", "config-mismatch"),
        ):
            with self.subTest(mutation=mutation):
                raw, rows = self._fixture()
                if mutation == "parent":
                    result = next(
                        row
                        for row in rows
                        if row["payload"]["type"] == "agent_result_observed"
                    )
                    result["payload"]["parent_thread_id"] = "foreign-thread"
                    self._rewrite(raw, rows)
                elif mutation == "missing":
                    rows[:] = [
                        row for row in rows if row["payload"]["type"] != "thread_ended"
                    ]
                    self._rewrite(raw, rows)
                else:
                    path = "payloads/child-configured.json"
                    configured = json.loads(raw[path])
                    configured["model"] = "changed-model"
                    raw[path] = _bytes(configured)
                with self.assertRaisesRegex(PreflightError, error):
                    preflight_observed._check_witnesses(
                        raw, "root-thread", self.spec, self.capture
                    )

    def test_direct_child_completion_sequence_and_config_are_checked(self):
        raw, _ = self._fixture()
        witness = preflight_observed.project_tool_witness(
            raw, "root-thread", "child-call"
        )
        self.assertIsNone(
            preflight_observed._check_child(raw, "root-thread", witness, self.spec)
        )

        changed_sequence = {**witness, "start_seq": witness["end_seq"] + 100}
        with self.assertRaisesRegex(PreflightError, "child-config-mismatch"):
            preflight_observed._check_child(
                raw, "root-thread", changed_sequence, self.spec
            )

        configured_path = "payloads/child-configured.json"
        configured = json.loads(raw[configured_path])
        configured["reasoning_effort"] = "changed-effort"
        raw[configured_path] = _bytes(configured)
        with self.assertRaisesRegex(PreflightError, "child-config-mismatch"):
            preflight_observed._check_child(raw, "root-thread", witness, self.spec)
