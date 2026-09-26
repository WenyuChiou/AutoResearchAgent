import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))

from stage1_ab import runner, sequence  # noqa: E402


def native_events():
    events = [
        {"type": "thread.started", "thread_id": "thread-native"},
        {"type": "turn.started"},
        {
            "type": "item.started",
            "item": {"id": "web-1", "type": "web_search"},
        },
        {
            "type": "item.completed",
            "item": {
                "id": "web-1",
                "type": "web_search",
                "action": {
                    "type": "search",
                    "queries": ["generic evidence", "generic recent comparison"],
                },
            },
        },
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 3,
                "cached_input_tokens": 0,
                "output_tokens": 2,
            },
        },
    ]
    return b"".join(json.dumps(event).encode() + b"\n" for event in events)


class NativeSearchRunnerV31Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "capture"
        self.output.mkdir()
        self.snapshot = self.output / "workspace" / "01"
        self.snapshot.mkdir(parents=True)
        self.pin = self.root / "runtime-pin.json"
        self.pin.write_text(
            json.dumps({"revision": runner.RESEARCH_HUB_SHA, "status": "merged"}),
            encoding="utf-8",
        )
        self.pin_bytes = self.pin.read_bytes()
        self.pin_sha = runner.sha(self.pin_bytes)
        self.lock = {
            "kind": "Stage1ABPublicLockV3",
            "schema_version": "3.1.0",
            "search_observation_policy": "native-or-cli",
            "plugin_tree_sha256": "a" * 64,
            "paired_repeats": [],
        }

    def attempt(self):
        raw = native_events()
        (self.output / "attempt-01.jsonl").write_bytes(raw)
        return {
            "started_at": "2026-09-26T00:00:00+00:00",
            "ended_at": "2026-09-26T00:01:00+00:00",
            "exit_code": 0,
            "files": {"attempt-01.jsonl": runner.sha(raw)},
            "summary": runner._event_summary(raw),
        }

    def record(self):
        return {
            "run_id": "run-native",
            "condition": "treatment",
            "repeat": 1,
            "execution_policy": runner.SUBJECT_EXECUTION_POLICY,
            "status": "complete",
            "attempts": [self.attempt()],
            "treatment_runtime_pin_path": str(self.pin),
        }

    def receipt(self, record=None, lock=None):
        record = record or self.record()
        return runner._treatment_execution_receipt(
            self.output,
            self.snapshot,
            record,
            lock or self.lock,
            {"path": str(self.pin), "sha256": self.pin_sha},
            pin_bytes=self.pin_bytes,
            verify_runtime=False,
        )

    def test_native_only_opt_in_builds_observational_receipt(self):
        record = self.record()
        receipt = self.receipt(record)
        self.assertEqual(receipt["kind"], "NativeSearchReceipt")
        self.assertEqual(receipt["counts"]["completed_search_actions"], 1)
        self.assertEqual(receipt["counts"]["completed_search_queries"], 2)
        self.assertIsNone(receipt["limitations"]["result_count"])
        self.assertFalse(receipt["limitations"]["full_text_verified"])
        self.assertFalse(receipt["limitations"]["search_success_inferred"])

    def test_present_invalid_cli_ledger_fails_without_native_fallback(self):
        ledger = self.snapshot / "stage1" / "run"
        ledger.mkdir(parents=True)
        (ledger / "run_manifest.json").write_text("{}", encoding="utf-8")
        with (
            patch.object(runner, "check_pin"),
            self.assertRaisesRegex(
                runner.ExecutionBlocked, "invalid Stage 1 ledger manifest"
            ),
        ):
            self.receipt()

    def _write_verifiable_capture(self, *, opt_in=True, tamper=False):
        record = self.record()
        lock = dict(self.lock)
        if not opt_in:
            lock["schema_version"] = "3.0.0"
            lock.pop("search_observation_policy")
        lock_raw = json.dumps(lock, sort_keys=True).encode()
        preflight = {
            "valid": True,
            "lock_sha256": runner.sha(lock_raw),
            "plugin_tree_sha256": lock["plugin_tree_sha256"],
        }
        preflight_raw = json.dumps(preflight, sort_keys=True).encode()
        files = record["attempts"][0]["files"]
        for name, raw in (
            ("attempt-01.lock.json", lock_raw),
            ("attempt-01.preflight.json", preflight_raw),
            ("attempt-01.runtime-pin.json", self.pin_bytes),
        ):
            (self.output / name).write_bytes(raw)
            files[name] = runner.sha(raw)
        record.update(
            {
                "lock_kind": "Stage1ABPublicLockV3",
                "lock_sha256": runner.sha(lock_raw),
                "preflight_sha256": runner.sha(preflight_raw),
                "profile_probe": {
                    "installed_plugin_sha256": lock["plugin_tree_sha256"]
                },
            }
        )
        # A legacy lock cannot generate this receipt; inject it to verify rejection.
        record["stage1_receipt"] = runner._native_receipt_from_capture(
            self.output, record["attempts"]
        )
        if tamper:
            record["stage1_receipt"]["counts"]["completed_search_queries"] = 99
        (self.output / "run.json").write_text(json.dumps(record), encoding="utf-8")
        binding = {
            "probes": {"treatment": record["profile_probe"]},
            "treatment_runtime_pin": {"sha256": self.pin_sha},
        }
        return record, lock, binding

    def test_verify_capture_replays_native_receipt_and_rejects_tamper(self):
        record, _lock, binding = self._write_verifiable_capture()
        with (
            patch.object(
                sequence, "expected_runs", return_value=[{"run_id": record["run_id"]}]
            ),
            patch.object(runner, "_preflight_binding", return_value=binding),
            patch.object(runner, "_repeat_pin_sha", return_value=self.pin_sha),
        ):
            self.assertEqual(
                runner.verify_capture(self.output, verify_runtime=False)["status"],
                "complete",
            )

        self.output = self.root / "tampered"
        self.output.mkdir()
        self.snapshot = self.output / "workspace" / "01"
        self.snapshot.mkdir(parents=True)
        record, _lock, binding = self._write_verifiable_capture(tamper=True)
        with (
            patch.object(
                sequence, "expected_runs", return_value=[{"run_id": record["run_id"]}]
            ),
            patch.object(runner, "_preflight_binding", return_value=binding),
            patch.object(runner, "_repeat_pin_sha", return_value=self.pin_sha),
            self.assertRaisesRegex(
                runner.ExecutionBlocked, "receipt differs from replay"
            ),
        ):
            runner.verify_capture(self.output, verify_runtime=False)

    def test_legacy_v3_lock_rejects_native_receipt(self):
        record, _lock, binding = self._write_verifiable_capture(opt_in=False)
        with (
            patch.object(
                sequence, "expected_runs", return_value=[{"run_id": record["run_id"]}]
            ),
            patch.object(runner, "_preflight_binding", return_value=binding),
            patch.object(runner, "_repeat_pin_sha", return_value=self.pin_sha),
            self.assertRaisesRegex(runner.ExecutionBlocked, "not enabled"),
        ):
            runner.verify_capture(self.output, verify_runtime=False)


if __name__ == "__main__":
    unittest.main()
