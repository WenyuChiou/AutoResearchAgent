"""Supported metadata observation is distinct from native tool attestation."""

import copy
import json
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))

from stage2_live.native import CaptureError  # noqa: E402
from stage2_live.native import sha256  # noqa: E402
from stage2_live.observation import (  # noqa: E402
    collect_runtime_observation,
    verify_runtime_observation,
    _rpc_exchange,
)


class RuntimeObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
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

    def transport(self, command, home, workspace, requests, timeout):
        self.requests = copy.deepcopy(requests)
        self.assertEqual(command[1:], ["app-server", "--stdio"])
        self.assertEqual(home, self.home)
        self.assertEqual(workspace, self.work)
        self.assertEqual(timeout, 30)
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
        process = MagicMock()
        process.stdin = io.StringIO()
        process.stdout = io.StringIO('{"id":0,"result":{}}\n')
        with (
            patch("stage2_live.observation.subprocess.Popen", return_value=process),
            patch("stage2_live.observation.time.monotonic", side_effect=[0, 100]),
        ):
            with self.assertRaisesRegex(CaptureError, "initialization failed"):
                _rpc_exchange(["synthetic"], self.home, self.work, [], 30)
        process.wait.assert_called_once_with(timeout=5)


if __name__ == "__main__":
    unittest.main()
