"""Supported metadata observation is distinct from native tool attestation."""

import copy
import json
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))

from stage2_live.native import CaptureError  # noqa: E402
from stage2_live.native import sha256  # noqa: E402
from stage2_live import observation  # noqa: E402
from stage2_live.observation import (  # noqa: E402
    collect_runtime_observation,
    verify_runtime_observation,
    _rpc_exchange,
)


class TrackingBytesIO(io.BytesIO):
    def __init__(self, value):
        super().__init__(value)
        self.readline_sizes = []

    def readline(self, size=-1):
        self.readline_sizes.append(size)
        return super().readline(size)


def mock_process(stdout):
    process = MagicMock()
    process.stdin = io.BytesIO()
    process.stdout = stdout
    return process


def rpc_wire(trailing=b""):
    responses = (
        {"id": 0, "result": {}},
        {"id": 1, "result": {"config": {}}},
        {"id": 2, "result": {"data": []}},
        {"id": 3, "result": {"marketplaces": [], "marketplaceLoadErrors": []}},
        {"id": 4, "result": {"data": [], "nextCursor": None}},
    )
    return b"".join((json.dumps(row) + "\n").encode() for row in responses) + trailing


class RuntimeObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.home = self.root / "profile"
        self.work = self.root / "workspace"
        self.home.mkdir()
        self.work.mkdir()
        self.binary = self.root / "codex.exe"
        self.binary.write_bytes(b"synthetic executable")
        self.args = dict(
            codex=self.binary,
            codex_home=self.home,
            workspace=self.work,
            output_dir=self.root / "observed",
        )
        self.requests = []
        self.expected_timeout = 120

    def transport(self, command, home, workspace, requests, timeout):
        self.requests = copy.deepcopy(requests)
        self.assertEqual(command[1:], ["app-server", "--stdio"])
        self.assertEqual(home, self.home)
        self.assertEqual(workspace, self.work)
        self.assertEqual(timeout, self.expected_timeout)
        result_by_method = {
            "config/read": {"config": {}},
            "skills/list": {"data": []},
            "plugin/list": {"marketplaces": [], "marketplaceLoadErrors": []},
            "mcpServerStatus/list": {"data": [], "nextCursor": None},
            "thread/read": {"thread": {"id": "existing"}},
        }
        responses = [
            {"id": item["id"], "result": result_by_method[item["method"]]}
            for item in requests
        ]
        events = [
            {"direction": "request", "payload": {"id": 0, "method": "initialize"}},
            {"direction": "response", "payload": {"id": 0, "result": {}}},
            {"direction": "request", "payload": {"method": "initialized"}},
        ]
        for request, response in zip(requests, responses):
            events.extend(
                [
                    {"direction": "request", "payload": request},
                    {"direction": "response", "payload": response},
                ]
            )
        return responses, events, b""

    def test_supported_observation_never_dispatches_model_or_claims_isolation(self):
        result = collect_runtime_observation(**self.args, rpc_transport=self.transport)
        self.assertEqual(
            [r["method"] for r in self.requests],
            [
                "config/read",
                "skills/list",
                "plugin/list",
                "mcpServerStatus/list",
            ],
        )
        self.assertEqual(result["model_turns_dispatched"], 0)
        self.assertFalse(result["formal_ready"])
        self.assertEqual(result["offered_tool_inventory"], "unknown")
        self.assertEqual(result["filesystem_read_isolation"], "not-assessed")
        with self.assertRaisesRegex(CaptureError, "synthetic"):
            verify_runtime_observation(
                self.args["output_dir"], result["record_sha256_receipt"]
            )
        self.assertEqual(
            verify_runtime_observation(
                self.args["output_dir"],
                result["record_sha256_receipt"],
                allow_synthetic=True,
            )["status"],
            "observed",
        )

    def test_nondefault_rpc_deadline_reaches_transport_record_and_replay(self):
        self.expected_timeout = 245.5
        result = collect_runtime_observation(
            **self.args,
            rpc_transport=self.transport,
            rpc_timeout_seconds=self.expected_timeout,
        )
        self.assertEqual(result["schema_version"], "2.0.0")
        self.assertEqual(result["rpc_timeout_seconds"], self.expected_timeout)
        verified = verify_runtime_observation(
            self.args["output_dir"],
            result["record_sha256_receipt"],
            allow_synthetic=True,
        )
        self.assertEqual(verified["rpc_timeout_seconds"], self.expected_timeout)

    def test_invalid_rpc_deadlines_reject_before_transport_or_output(self):
        calls = []

        def forbidden(*args):
            calls.append(args)
            raise AssertionError("invalid deadline must not reach transport")

        for value in (
            True,
            False,
            None,
            "120",
            0,
            -1,
            601,
            10**1000,
            float("inf"),
            float("nan"),
        ):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(CaptureError, "rpc_timeout_seconds"),
            ):
                collect_runtime_observation(
                    **self.args,
                    rpc_transport=forbidden,
                    rpc_timeout_seconds=value,
                )
            self.assertFalse(self.args["output_dir"].exists())
        self.assertEqual(calls, [])

    def test_legacy_and_versioned_deadline_contracts_fail_closed(self):
        collect_runtime_observation(**self.args, rpc_transport=self.transport)
        path = self.args["output_dir"] / "observation.json"
        current = json.loads(path.read_bytes())

        legacy = dict(current)
        legacy["schema_version"] = "1.0.0"
        legacy.pop("rpc_timeout_seconds")
        raw = json.dumps(legacy).encode()
        path.write_bytes(raw)
        self.assertEqual(
            verify_runtime_observation(path.parent, sha256(raw), allow_synthetic=True)[
                "schema_version"
            ],
            "1.0.0",
        )

        invalid = (
            ("legacy-field", {**current, "schema_version": "1.0.0"}),
            (
                "missing",
                {k: v for k, v in current.items() if k != "rpc_timeout_seconds"},
            ),
            ("boolean", {**current, "rpc_timeout_seconds": True}),
            ("too-large", {**current, "rpc_timeout_seconds": 601}),
        )
        for label, value in invalid:
            with self.subTest(label=label):
                raw = json.dumps(value).encode()
                path.write_bytes(raw)
                with self.assertRaisesRegex(CaptureError, "contract differs"):
                    verify_runtime_observation(
                        path.parent, sha256(raw), allow_synthetic=True
                    )

    def test_optional_thread_reads_actual_thread_without_starting_one(self):
        collect_runtime_observation(
            **self.args, thread_id="existing", rpc_transport=self.transport
        )
        self.assertEqual(self.requests[-1]["method"], "thread/read")
        self.assertEqual(
            self.requests[-1]["params"], {"threadId": "existing", "includeTurns": False}
        )

    def test_unsupported_api_and_unfinished_pagination_remain_partial(self):
        def incomplete(*args):
            replies, events, stderr = self.transport(*args)
            replies[1].clear()
            replies[1].update({"id": 2, "error": {"message": "unsupported"}})
            replies[3]["result"]["nextCursor"] = "more"
            return replies, events, stderr

        result = collect_runtime_observation(**self.args, rpc_transport=incomplete)
        self.assertEqual(result["status"], "partial")
        rows = json.loads((self.args["output_dir"] / "rpc.json").read_text())
        self.assertEqual(
            [r["status"] for r in rows],
            ["observed", "incomplete", "observed", "incomplete"],
        )

    def test_artifact_tampering_and_wrong_receipts_are_rejected(self):
        result = collect_runtime_observation(**self.args, rpc_transport=self.transport)
        with self.assertRaisesRegex(CaptureError, "receipt"):
            verify_runtime_observation(
                self.args["output_dir"], "0" * 64, allow_synthetic=True
            )
        (self.args["output_dir"] / "rpc.json").write_text("[]")
        with self.assertRaisesRegex(CaptureError, "artifact"):
            verify_runtime_observation(
                self.args["output_dir"],
                result["record_sha256_receipt"],
                allow_synthetic=True,
            )

    def test_runtime_changes_and_profile_changes_are_rejected(self):
        def change(*args):
            replies = self.transport(*args)
            self.binary.write_bytes(b"changed executable")
            return replies

        with self.assertRaisesRegex(CaptureError, "changed during"):
            collect_runtime_observation(**self.args, rpc_transport=change)
        self.assertTrue((self.args["output_dir"] / "rpc-responses.json").is_file())
        self.assertTrue((self.args["output_dir"] / "transport.json").is_file())

    def test_nested_skill_errors_and_empty_metadata_are_incomplete(self):
        def bad(*args):
            replies, events, stderr = self.transport(*args)
            replies[0]["result"] = {}
            replies[1]["result"] = {
                "data": [{"skills": [], "errors": ["could not load skill"]}]
            }
            return replies, events, stderr

        result = collect_runtime_observation(**self.args, rpc_transport=bad)
        self.assertEqual(result["status"], "partial")

    def test_wrong_response_identity_preserves_transport(self):
        def bad(*args):
            replies, events, stderr = self.transport(*args)
            replies[0]["id"] = 99
            return replies, events, stderr

        with self.assertRaisesRegex(CaptureError, "identity"):
            collect_runtime_observation(**self.args, rpc_transport=bad)
        self.assertTrue((self.args["output_dir"] / "rpc-responses.json").is_file())

    def test_rehash_tamper_rejected_when_rpc_status_is_invented(self):
        collect_runtime_observation(**self.args, rpc_transport=self.transport)
        root = self.args["output_dir"]
        rows = json.loads((root / "rpc.json").read_text())
        rows[0]["response"] = {"id": 1, "error": {"message": "unavailable"}}
        raw = json.dumps(rows).encode()
        (root / "rpc.json").write_bytes(raw)
        record = json.loads((root / "observation.json").read_text())
        record["artifacts"]["rpc.json"] = sha256(raw)
        rewritten = json.dumps(record).encode()
        (root / "observation.json").write_bytes(rewritten)
        with self.assertRaisesRegex(CaptureError, "response differs"):
            verify_runtime_observation(root, sha256(rewritten), allow_synthetic=True)

    def test_output_collision_and_git_containment_are_rejected(self):
        collect_runtime_observation(**self.args, rpc_transport=self.transport)
        with self.assertRaises(FileExistsError):
            collect_runtime_observation(**self.args, rpc_transport=self.transport)
        (self.work / ".git").mkdir()
        with self.assertRaisesRegex(CaptureError, "Git"):
            collect_runtime_observation(
                **{**self.args, "output_dir": self.work / "private"},
                rpc_transport=self.transport,
            )

    def test_transport_failure_retains_failed_record(self):
        def failure(*_):
            raise CaptureError("interrupted transport")

        with self.assertRaisesRegex(CaptureError, "interrupted"):
            collect_runtime_observation(**self.args, rpc_transport=failure)
        self.assertEqual(
            json.loads((self.args["output_dir"] / "failure.json").read_text())[
                "status"
            ],
            "failed",
        )

    def test_rehash_tamper_rejected_for_model_dispatch_transport(self):
        collect_runtime_observation(**self.args, rpc_transport=self.transport)
        root = self.args["output_dir"]
        events = json.loads((root / "transport.json").read_text())
        events.append({"direction": "request", "payload": {"method": "turn/start"}})
        raw = json.dumps(events).encode()
        (root / "transport.json").write_bytes(raw)
        record = json.loads((root / "observation.json").read_text())
        record["artifacts"]["transport.json"] = sha256(raw)
        rewritten = json.dumps(record).encode()
        (root / "observation.json").write_bytes(rewritten)
        with self.assertRaisesRegex(CaptureError, "unexpected requests"):
            verify_runtime_observation(root, sha256(rewritten), allow_synthetic=True)

    def test_malformed_record_is_typed_and_receipt_cannot_change_profile(self):
        from stage2_live.__main__ import main

        root = self.args["output_dir"]
        root.mkdir()
        (root / "observation.json").write_bytes(b"[]")
        with self.assertRaises(CaptureError):
            verify_runtime_observation(root, sha256(b"[]"), allow_synthetic=True)
        with patch("stage2_live.observation.collect_runtime_observation") as collect:
            with patch("sys.stderr", io.StringIO()):
                status = main(
                    [
                        "observe-runtime",
                        "--codex",
                        str(self.binary),
                        "--codex-home",
                        str(self.home),
                        "--workspace",
                        str(self.work),
                        "--output",
                        str(self.root / "other"),
                        "--receipt-output",
                        str(self.home / "config.toml"),
                    ]
                )
            self.assertEqual(status, 2)
            collect.assert_not_called()
            self.assertFalse((self.home / "config.toml").exists())

    def test_rpc_deadline_is_checked_even_with_queued_replies(self):
        process = mock_process(io.BytesIO(b'{"id":0,"result":{}}\n'))
        with (
            patch("stage2_live.observation.subprocess.Popen", return_value=process),
            patch("stage2_live.observation.time.monotonic", side_effect=[0, 121]),
        ):
            with self.assertRaisesRegex(CaptureError, "initialization failed"):
                _rpc_exchange(["synthetic"], self.home, self.work, [], 120)
        process.wait.assert_called_once_with(timeout=5)

    def test_rpc_accepts_five_megabyte_json_with_bounded_readline(self):
        raw = (
            json.dumps({"id": 0, "result": {"payload": "x" * (5 * 1024 * 1024)}}) + "\n"
        ).encode()
        stdout = TrackingBytesIO(raw)
        process = mock_process(stdout)
        with patch("stage2_live.observation.subprocess.Popen", return_value=process):
            responses, events, stderr = _rpc_exchange(
                ["synthetic"], self.home, self.work, [], 120
            )
        self.assertEqual(responses, [])
        self.assertEqual(
            len(events[1]["payload"]["result"]["payload"]), 5 * 1024 * 1024
        )
        self.assertEqual(stderr, b"")
        self.assertTrue(stdout.readline_sizes)
        self.assertEqual(
            set(stdout.readline_sizes), {observation.MAX_RPC_FRAME_BYTES + 2}
        )

    def test_five_megabyte_response_is_persisted_and_replayed(self):
        def large(*args):
            responses, events, stderr = self.transport(*args)
            result = {
                "marketplaces": [{"description": "x" * (5 * 1024 * 1024)}],
                "marketplaceLoadErrors": [],
            }
            responses[2]["result"] = result
            events[-3]["payload"]["result"] = copy.deepcopy(result)
            return responses, events, stderr

        result = collect_runtime_observation(**self.args, rpc_transport=large)
        verified = verify_runtime_observation(
            self.args["output_dir"],
            result["record_sha256_receipt"],
            allow_synthetic=True,
        )
        self.assertEqual(verified["status"], "observed")
        self.assertGreater(
            (self.args["output_dir"] / "transport.json").stat().st_size,
            5 * 1024 * 1024,
        )

    def test_rpc_reader_failures_are_distinct_finite_and_terminate(self):
        cases = (
            ("utf8", b"\xff\n", {}, "invalid UTF-8", "invalid-utf8"),
            ("json", b"{nope}\n", {}, "malformed JSON", "malformed-json"),
            (
                "frame",
                b"x" * 18,
                {"MAX_RPC_FRAME_BYTES": 16, "MAX_RPC_STREAM_BYTES": 64},
                "frame exceeded 16 bytes.*18-byte prefix",
                "frame-limit",
            ),
        )
        for label, raw, limits, message, kind in cases:
            with self.subTest(label=label):
                process = mock_process(TrackingBytesIO(raw))
                patches = [
                    patch.object(observation, name, value)
                    for name, value in limits.items()
                ]
                with patch.object(
                    observation.subprocess, "Popen", return_value=process
                ):
                    for active in patches:
                        active.start()
                    try:
                        with self.assertRaisesRegex(CaptureError, message) as caught:
                            _rpc_exchange(["synthetic"], self.home, self.work, [], 120)
                    finally:
                        for active in reversed(patches):
                            active.stop()
                detail = caught.exception.observation_events[1]["payload"][
                    "reader_error"
                ]
                self.assertEqual(detail["kind"], kind)
                self.assertLessEqual(
                    detail["observed_prefix_bytes"],
                    limits.get("MAX_RPC_FRAME_BYTES", len(raw)) + 2,
                )
                process.wait.assert_called_once_with(timeout=5)

    def test_rpc_cumulative_stream_limit_is_distinct(self):
        hello = b'{"id":0,"result":{}}\n'
        notice = b'{"method":"notice","params":{"value":"abcdefgh"}}\n'
        reply = b'{"id":1,"result":{}}\n'
        process = mock_process(TrackingBytesIO(hello + notice + reply))
        request = {"id": 1, "method": "config/read", "params": {}}
        limit = len(hello) + len(notice) - 1
        with (
            patch.object(observation.subprocess, "Popen", return_value=process),
            patch.object(observation, "MAX_RPC_FRAME_BYTES", 64),
            patch.object(observation, "MAX_RPC_STREAM_BYTES", limit),
        ):
            with self.assertRaisesRegex(
                CaptureError,
                rf"stream exceeded {limit} bytes.*{len(hello) + len(notice)}-byte prefix",
            ) as caught:
                _rpc_exchange(["synthetic"], self.home, self.work, [request], 120)
        detail = caught.exception.observation_events[-1]["payload"]["reader_error"]
        self.assertEqual(
            detail,
            {
                "kind": "stream-limit",
                "limit_bytes": limit,
                "observed_prefix_bytes": len(hello) + len(notice),
            },
        )

    def test_rpc_reader_exception_is_preserved_and_process_is_cleaned_up(self):
        class BrokenReader:
            def readline(self, _size):
                raise OSError("sensitive source content")

            def close(self):
                pass

        process = mock_process(BrokenReader())
        process.wait.side_effect = [
            subprocess.TimeoutExpired("synthetic", 5),
            None,
        ]
        with patch.object(observation.subprocess, "Popen", return_value=process):
            with self.assertRaisesRegex(
                CaptureError, "response reader failed: OSError"
            ) as caught:
                _rpc_exchange(["synthetic"], self.home, self.work, [], 120)
        detail = caught.exception.observation_events[1]["payload"]["reader_error"]
        self.assertEqual(detail, {"kind": "reader-exception", "error_type": "OSError"})
        self.assertEqual(process.wait.call_count, 2)
        process.terminate.assert_called_once_with()

    def test_late_invalid_utf8_fails_collection_and_is_saved_once(self):
        process = mock_process(TrackingBytesIO(rpc_wire(b"\xff\n")))

        def late_transport(*args):
            with patch.object(observation.subprocess, "Popen", return_value=process):
                return _rpc_exchange(*args)

        with self.assertRaisesRegex(CaptureError, "invalid UTF-8"):
            collect_runtime_observation(**self.args, rpc_transport=late_transport)
        events = json.loads(
            (self.args["output_dir"] / "failed-transport.json").read_bytes()
        )
        failures = [
            event["payload"]["reader_error"]
            for event in events
            if isinstance(event.get("payload"), dict)
            and "reader_error" in event["payload"]
        ]
        self.assertEqual(
            failures,
            [{"kind": "invalid-utf8", "observed_prefix_bytes": 2, "byte_offset": 0}],
        )
        self.assertFalse((self.args["output_dir"] / "observation.json").exists())

    def test_late_oversized_frame_fails_collection_and_is_saved_once(self):
        process = mock_process(TrackingBytesIO(rpc_wire(b"x" * 130)))

        def late_transport(*args):
            with patch.object(observation.subprocess, "Popen", return_value=process):
                return _rpc_exchange(*args)

        with (
            patch.object(observation, "MAX_RPC_FRAME_BYTES", 128),
            patch.object(observation, "MAX_RPC_STREAM_BYTES", 4096),
            self.assertRaisesRegex(
                CaptureError, "frame exceeded 128 bytes.*130-byte prefix"
            ),
        ):
            collect_runtime_observation(**self.args, rpc_transport=late_transport)
        events = json.loads(
            (self.args["output_dir"] / "failed-transport.json").read_bytes()
        )
        failures = [
            event["payload"]["reader_error"]
            for event in events
            if isinstance(event.get("payload"), dict)
            and "reader_error" in event["payload"]
        ]
        self.assertEqual(
            failures,
            [
                {
                    "kind": "frame-limit",
                    "limit_bytes": 128,
                    "observed_prefix_bytes": 130,
                }
            ],
        )
        self.assertFalse((self.args["output_dir"] / "observation.json").exists())


if __name__ == "__main__":
    unittest.main()
