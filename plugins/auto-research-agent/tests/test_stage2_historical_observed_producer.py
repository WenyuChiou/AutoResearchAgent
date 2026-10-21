# ruff: noqa: E402 -- exercise the repository CLI without installation.
"""Synthetic historical observed-producer checks; no live model or old-code execution."""

import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage2_common import Stage2Error, canonical_hash
from stage2_live import historical_verifier as host, trace_producer
import test_stage2_controller_host_verification as host_cases
import test_stage2_trace_producer as trace_cases


class HistoricalObservedProducerTests(unittest.TestCase):
    def setUp(self):
        f = host_cases.HistoricalHostVerificationTests(methodName="runTest")
        f.setUp()
        self.addCleanup(f.doCleanups)
        self.fixture = f
        self.old = f.producer / "stage2_live/trace_producer.py"
        self.old.write_bytes(b'raise AssertionError("old code must never execute")\n')
        rows = host._source_inventory(f.producer)
        producer_sha = canonical_hash(rows)
        registry = json.loads(f.registry.read_bytes())
        registry["supported_producers"][producer_sha] = dict(
            registry["supported_producers"][f.producer_sha]
        )
        f.registry.write_text(json.dumps(registry), encoding="utf8")
        self.pin = hashlib.sha256(self.old.read_bytes()).hexdigest()
        self.binding = {
            **f.binding,
            "schema_version": "1.1.0",
            "producer_cli_sha256": producer_sha,
            "observed_producer_source_sha256": self.pin,
            **host.inspect_verifier_build(),
        }

    def test_explicit_registered_trace_pin_is_readonly_and_never_executes_old_source(
        self,
    ):
        before = self.old.read_bytes()
        with patch(
            "builtins.exec", side_effect=AssertionError("old code must never execute")
        ):
            build = host.resolve_historical_binding(self.binding)
        self.assertEqual(build.observed_producer_source_sha256, self.pin)
        self.assertEqual(build.receipt["schema_version"], "1.1.0")
        self.assertTrue(build.receipt["read_only"])
        self.assertFalse(build.receipt["formal_ready"])
        self.assertEqual(self.old.read_bytes(), before)

    def test_bad_trace_pin_or_wrong_schema_and_rehashed_source_refuse(self):
        for change in (
            {"observed_producer_source_sha256": "0" * 64},
            {"schema_version": "1.0.0"},
            {"schema_version": "1.9.0"},
        ):
            with self.subTest(change=change), self.assertRaises(Stage2Error):
                host.resolve_historical_binding({**self.binding, **change})
        self.old.write_bytes(b"new source")
        with self.assertRaises(Stage2Error):
            host.resolve_historical_binding(self.binding)
        rehashed = {
            **self.binding,
            "producer_cli_sha256": canonical_hash(
                host._source_inventory(self.fixture.producer)
            ),
            "observed_producer_source_sha256": hashlib.sha256(
                self.old.read_bytes()
            ).hexdigest(),
        }
        with self.assertRaisesRegex(Stage2Error, "unsupported-producer"):
            host.resolve_historical_binding(rehashed)

    def test_only_new_version_passes_binding_to_readonly_environment(self):
        with patch(
            "stage2_live.environment.verify_environment_capture",
            return_value={"status": "verified", "inventory_status": "not-captured"},
        ) as verify:
            r = host.verify_historical_environment_capture(
                "capture",
                "r",
                {"receipt": "p", "probe_spec": {"schema_version": "1.2.0"}},
                None,
                historical_binding=self.binding,
            )
        verify.assert_called_once_with(
            "capture",
            "r",
            {"receipt": "p", "probe_spec": {"schema_version": "1.2.0"}},
            None,
            historical_binding=self.binding,
        )
        self.assertFalse(r["historical_verification"]["formal_ready"])
        self.assertEqual(r["environment"]["inventory_status"], "not-captured")

    def test_new_binding_refuses_nonobserved_or_malformed_preflight_before_environment(
        self,
    ):
        for pre in (
            None,
            [],
            {"receipt": "p"},
            {"receipt": "p", "probe_spec": None},
            {"receipt": "p", "probe_spec": {"schema_version": "1.1.0"}},
        ):
            with (
                self.subTest(pre=pre),
                patch("stage2_live.environment.verify_environment_capture") as verify,
            ):
                with self.assertRaisesRegex(Stage2Error, "observed-preflight-required"):
                    host.verify_historical_environment_capture(
                        "capture", "r", pre, None, historical_binding=self.binding
                    )
                verify.assert_not_called()

    def _old_capture(self):
        case = trace_cases.TraceProducerTests(methodName="runTest")
        case.setUp()
        self.addCleanup(case.doCleanups)
        with patch.object(trace_producer, "_source_sha", return_value=self.pin):
            produced = case._produce()
        return case, produced

    def test_authentic_synthetic_trace_replay_uses_registered_old_source_and_resume_stays_strict(
        self,
    ):
        case, produced = self._old_capture()
        receipt = produced["producer_receipt"]
        with self.assertRaisesRegex(Stage2Error, "source-changed"):
            trace_producer._verify(
                case._args(),
                case.telemetry,
                receipt,
                allow_synthetic=True,
                workspace_mode="archived",
            )
        r = trace_producer._verify(
            case._args(),
            case.telemetry,
            receipt,
            allow_synthetic=True,
            workspace_mode="archived",
            historical_binding=self.binding,
        )
        self.assertEqual(r["resume_action"], "verified-replay-no-execution")
        self.assertEqual(case.calls, 1)
        self.assertEqual(r["evidence_class"], "synthetic-test-only")
        with self.assertRaisesRegex(Stage2Error, "source-changed"):
            case._produce(resume=True, producer_receipt=receipt)
        self.assertEqual(case.calls, 1)

    def test_current_mode_and_arbitrary_binding_reject_without_capture_or_execution(
        self,
    ):
        for binding, mode in (
            (self.binding, "current"),
            ({**self.binding, "observed_producer_source_sha256": "0" * 64}, "archived"),
        ):
            with self.subTest(mode=mode), self.assertRaises(Stage2Error):
                trace_producer._verify(
                    {},
                    Path("does-not-exist"),
                    "r",
                    allow_synthetic=False,
                    workspace_mode=mode,
                    historical_binding=binding,
                )

    def test_rehashed_capture_source_cannot_replace_the_registered_producer(self):
        case, produced = self._old_capture()
        control = case.telemetry / "bundle/producer.json"
        row = json.loads(control.read_bytes())
        row["producer_source_sha256"] = "0" * 64
        control.write_text(json.dumps(row), encoding="utf8")
        receipt = hashlib.sha256(control.read_bytes()).hexdigest()
        with self.assertRaisesRegex(Stage2Error, "source-changed"):
            trace_producer._verify(
                case._args(),
                case.telemetry,
                receipt,
                allow_synthetic=True,
                workspace_mode="archived",
                historical_binding=self.binding,
            )


if __name__ == "__main__":
    unittest.main()
