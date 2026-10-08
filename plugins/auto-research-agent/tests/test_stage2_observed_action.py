import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys

CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))

from stage2_live.native import CaptureError  # noqa: E402
from stage2_live import observed_action  # noqa: E402


class ObservedActionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.telemetry = self.root / "telemetry"
        self.telemetry.mkdir()
        self.trace_root = self.telemetry / "action-one"
        self.request = {
            "codex": self.root / "codex",
            "codex_home": self.root / "home",
            "workspace": self.root / "workspace",
            "prompt": "perform one action",
            "model": "gpt-test",
            "reasoning": "high",
            "input_bindings": {},
            "config_bindings": {},
            "policy_bindings": {
                "kind": "Stage2NamedPermissionsPolicy",
                "schema_version": "1.1.0",
                "name": "subject",
                "config_sha256": "a" * 64,
                "telemetry_path": str(self.telemetry),
                "capture_root": str(self.root / "captures"),
            },
            "capture_dir": self.root / "captures/action-one",
            "timeout_seconds": 45,
            "trace_root": str(self.trace_root),
        }
        self.producer = {
            "producer_receipt": "p" * 64,
            "native_capture_receipt": "n" * 64,
            "runtime_observation_receipt": "r" * 64,
            "capture": {"status": "complete", "cost": {"amount": None}},
            "formal_ready": False,
        }
        self.inventory = {
            "kind": "Stage2ExecutionInventory",
            "formal_ready": False,
            "cost": {"amount": None, "currency": None, "state": "unknown"},
            "threads": [{"thread_id": "discovered-from-trace"}],
        }
        self.native_record = {
            "kind": "Stage2NativeCapture",
            "status": "complete",
            "record_sha256_receipt": "n" * 64,
        }

    def test_fresh_action_scopes_environment_and_inspects_without_thread_id(self):
        observed = {}

        def capture(**kwargs):
            observed["capture"] = kwargs
            observed["capture_env"] = os.environ["CODEX_ROLLOUT_TRACE_ROOT"]
            self.assertTrue(self.trace_root.is_dir())
            return self.producer

        def inspect(root, receipt, *, capture_request):
            observed["inspect"] = (root, receipt, capture_request)
            observed["inspect_env"] = os.environ["CODEX_ROLLOUT_TRACE_ROOT"]
            return self.inventory

        with (
            patch.object(
                observed_action.trace_producer,
                "capture_observed_native",
                side_effect=capture,
            ),
            patch.object(
                observed_action.execution_inventory,
                "inspect_execution_inventory",
                side_effect=inspect,
            ),
            patch.object(
                observed_action.native,
                "verify_capture",
                return_value=(self.native_record, "final"),
            ) as verify_native,
            patch.dict(os.environ, {"CODEX_ROLLOUT_TRACE_ROOT": "prior-root"}),
        ):
            result = observed_action.capture_observed_action(self.request)
            self.assertEqual(os.environ["CODEX_ROLLOUT_TRACE_ROOT"], "prior-root")

        self.assertEqual(observed["capture_env"], str(self.trace_root))
        self.assertEqual(observed["inspect_env"], str(self.trace_root))
        capture = observed["capture"]
        self.assertEqual({key: capture[key] for key in self.request}, self.request)
        self.assertEqual(
            (capture["producer_receipt"], capture["resume"]), (None, False)
        )
        self.assertNotIn("thread_id", capture)
        self.assertEqual(
            observed["inspect"],
            (self.trace_root, "p" * 64, self.request),
        )
        self.assertIs(result["producer"], self.producer)
        self.assertIs(result["inventory"], self.inventory)
        verify_native.assert_called_once_with(self.request["capture_dir"], "n" * 64)
        self.assertIs(result["native_capture"], self.native_record)
        self.assertEqual(
            result["receipts"],
            {
                "producer": "p" * 64,
                "native_capture": "n" * 64,
                "runtime_observation": "r" * 64,
            },
        )
        self.assertFalse(result["formal_ready"])
        self.assertIsNone(result["inventory"]["cost"]["amount"])

    def test_resume_uses_retained_receipt_and_never_creates_or_dispatches_itself(self):
        self.trace_root.mkdir()
        (self.trace_root / "producer-archive").write_bytes(b"retained")
        receipt = "p" * 64
        with (
            patch.object(
                observed_action.trace_producer,
                "capture_observed_native",
                return_value=self.producer,
            ) as producer,
            patch.object(
                observed_action.execution_inventory,
                "inspect_execution_inventory",
                return_value=self.inventory,
            ) as inspect,
            patch.object(
                observed_action.native,
                "verify_capture",
                return_value=(self.native_record, "final"),
            ) as verify_native,
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("CODEX_ROLLOUT_TRACE_ROOT", None)
            result = observed_action.capture_observed_action(
                self.request, producer_receipt=receipt, resume=True
            )
            self.assertNotIn("CODEX_ROLLOUT_TRACE_ROOT", os.environ)
        producer.assert_called_once_with(
            **self.request, producer_receipt=receipt, resume=True
        )
        inspect.assert_called_once_with(
            self.trace_root, receipt, capture_request=self.request
        )
        verify_native.assert_called_once_with(self.request["capture_dir"], "n" * 64)
        self.assertEqual(result["resume_action"], "verified-replay-no-execution")
        self.assertEqual(
            (self.trace_root / "producer-archive").read_bytes(), b"retained"
        )

    def test_inventory_failure_restores_environment_and_preserves_archives(self):
        previous = os.environ.get("CODEX_ROLLOUT_TRACE_ROOT")
        self.trace_root.mkdir()
        native_archive = self.root / "captures/action-one/run.json"
        native_archive.parent.mkdir(parents=True)
        native_archive.write_bytes(b"original-native")
        producer_archive = self.trace_root / "producer.json"
        producer_archive.write_bytes(b"original-producer")
        with (
            patch.object(
                observed_action.trace_producer,
                "capture_observed_native",
                return_value=self.producer,
            ),
            patch.object(
                observed_action.execution_inventory,
                "inspect_execution_inventory",
                side_effect=CaptureError("inventory verification failed"),
            ),
            patch.object(
                observed_action.native,
                "verify_capture",
                return_value=(self.native_record, "final"),
            ),
            patch.dict(os.environ, {"CODEX_ROLLOUT_TRACE_ROOT": "prior"}),
            self.assertRaisesRegex(
                observed_action.ObservedActionVerificationError,
                "inventory verification failed",
            ) as raised,
        ):
            observed_action.capture_observed_action(
                self.request, producer_receipt="p" * 64, resume=True
            )
        self.assertEqual(os.environ.get("CODEX_ROLLOUT_TRACE_ROOT"), previous)
        self.assertEqual(
            raised.exception.receipts,
            {
                "producer": "p" * 64,
                "native_capture": "n" * 64,
                "runtime_observation": "r" * 64,
            },
        )
        self.assertEqual(native_archive.read_bytes(), b"original-native")
        self.assertEqual(producer_archive.read_bytes(), b"original-producer")

    def test_native_verification_failure_retains_original_receipts_and_failure(self):
        self.trace_root.mkdir()
        archive = self.trace_root / "original-capture"
        archive.write_bytes(b"original-native-bytes")
        for producer_status in ("failed", "complete"):
            with self.subTest(producer_status=producer_status):
                producer = {
                    **self.producer,
                    "capture": {"status": producer_status},
                }
                failure = CaptureError("native original capture is not verifiable")
                with (
                    patch.object(
                        observed_action.trace_producer,
                        "capture_observed_native",
                        return_value=producer,
                    ),
                    patch.object(
                        observed_action.native, "verify_capture", side_effect=failure
                    ),
                    patch.object(
                        observed_action.execution_inventory,
                        "inspect_execution_inventory",
                    ) as inspect,
                    patch.dict(os.environ, {"CODEX_ROLLOUT_TRACE_ROOT": "prior-root"}),
                ):
                    with self.assertRaises(
                        observed_action.ObservedActionVerificationError
                    ) as raised:
                        observed_action.capture_observed_action(
                            self.request, producer_receipt="p" * 64, resume=True
                        )
                    self.assertEqual(
                        os.environ["CODEX_ROLLOUT_TRACE_ROOT"], "prior-root"
                    )
                self.assertEqual(
                    raised.exception.receipts,
                    {
                        "producer": "p" * 64,
                        "native_capture": "n" * 64,
                        "runtime_observation": "r" * 64,
                    },
                )
                self.assertEqual(raised.exception.failure_class, "CaptureError")
                self.assertIs(raised.exception.__cause__, failure)
                self.assertEqual(archive.read_bytes(), b"original-native-bytes")
                inspect.assert_not_called()

    def test_invalid_request_fails_before_trace_or_calls(self):
        for request in (
            {key: value for key, value in self.request.items() if key != "trace_root"},
            {**self.request, "foreign": True},
        ):
            with self.subTest(fields=set(request)), self.assertRaises(CaptureError):
                observed_action.capture_observed_action(request)
        self.assertFalse(self.trace_root.exists())


if __name__ == "__main__":
    unittest.main()
