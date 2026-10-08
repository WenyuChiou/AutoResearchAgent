"""Synthetic observed-preflight receipt and binding tests."""

import copy
import hashlib
from pathlib import Path
import sys
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "cli"))

from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_live import preflight  # noqa: E402
from stage2_live import preflight_observed  # noqa: E402
from stage2_live.preflight import PreflightError  # noqa: E402
from stage2_live.trace_files import _load_inventory  # noqa: E402
from stage2_observed_preflight_fixtures import (  # noqa: E402
    ObservedPreflightFixture,
)


class ObservedReceiptTests(ObservedPreflightFixture):
    def test_wrong_contract_and_observation_bindings_are_rejected(self):
        changes = (
            (lambda spec: spec.update(schema_version="1.1.0"), "contract-invalid"),
            (
                lambda spec: spec.update(kind="Stage2RuntimeProbeSpec"),
                "contract-invalid",
            ),
            (
                lambda spec: spec["observation"].update(
                    telemetry_root=str(self.capture)
                ),
                "trace-root-mismatch",
            ),
            (
                lambda spec: spec["observation"]["capture_request"].update(
                    capture_dir=str(self.trace_root)
                ),
                "capture-mismatch",
            ),
        )
        for mutate, error in changes:
            spec = copy.deepcopy(self.spec)
            mutate(spec)
            with (
                self.subTest(error=error),
                self.assertRaisesRegex(PreflightError, error),
            ):
                preflight_observed.inspect_observed_preflight(
                    self.capture, "r" * 64, spec
                )

    def test_authentication_seams_and_receipts_are_bound(self):
        producer = {
            "native_capture_receipt": "r" * 64,
            "runtime_observation_receipt": "o" * 64,
            "trace": {
                "root": "trace",
                "inventory": {"trace.jsonl": "x" * 64},
                "receipt_sha256": "t" * 64,
            },
        }
        record = {
            "event_summary": {"thread_id": "root-thread"},
            "stable_request_binding": {
                "workspace": str(self.workspace),
                "config_bindings": {
                    "probe_shell": {"path": str(self.shell), "sha256": "a" * 64}
                },
            },
            "archived_files": [],
        }
        actual = {
            **self.spec["expected"],
            "permission_workspace_write": True,
            "approval_policy": "never",
        }
        context = {"synthetic": True}
        with (
            mock.patch.object(
                preflight_observed.trace_producer, "_verify", return_value=producer
            ) as authenticate,
            mock.patch.object(
                preflight_observed, "verify_capture", return_value=(record, {})
            ),
            mock.patch.object(
                preflight_observed,
                "_load_inventory",
                return_value={"trace.jsonl": b"{}\n"},
            ),
            mock.patch.object(
                preflight_observed.trace_observation,
                "inspect_native_trace",
                return_value={"blockers": [], "root_thread_id": "root-thread"},
            ),
            mock.patch.object(preflight_observed, "_load_jsonl", return_value=[{}]),
            mock.patch.object(
                preflight_observed, "_session_identity", return_value="root-thread"
            ),
            mock.patch.object(
                preflight_observed, "_turn_context", return_value=context
            ),
            mock.patch.object(preflight_observed, "verify_named_runtime"),
            mock.patch.object(
                preflight_observed, "_actual_runtime", return_value=actual
            ),
            mock.patch.object(
                preflight_observed,
                "_check_witnesses",
                return_value={
                    name: {"status": "passed"}
                    for name in ("read", "write", "search", "child")
                },
            ),
            mock.patch.object(
                preflight_observed, "_context_inventory", return_value={}
            ),
            mock.patch.object(
                preflight_observed,
                "_verify_child_session",
                return_value={**actual, "native_turn_ids": ["child-turn"]},
            ),
        ):
            report = preflight_observed.inspect_observed_preflight(
                self.capture, "r" * 64, self.spec
            )
            foreign = copy.deepcopy(self.spec)
            foreign["executor"]["working_directory"] = "/foreign-workspace"
            foreign["probes"]["read"]["command_path"] = (
                "/foreign-workspace/input/nonce.txt"
            )
            with self.assertRaisesRegex(PreflightError, "executor-workspace-mismatch"):
                preflight_observed.inspect_observed_preflight(
                    self.capture, "r" * 64, foreign
                )
        self.assertTrue(report["runtime_gate"])
        self.assertEqual(report["schema_version"], "1.2.0")
        self.assertEqual(authenticate.call_count, 2)
        authenticate.assert_any_call(
            self.request,
            self.trace_root,
            "p" * 64,
            allow_synthetic=False,
            workspace_mode="archived",
        )

        producer["native_capture_receipt"] = "z" * 64
        with (
            mock.patch.object(
                preflight_observed.trace_producer, "_verify", return_value=producer
            ),
            self.assertRaisesRegex(PreflightError, "receipt-mismatch"),
        ):
            preflight_observed.inspect_observed_preflight(
                self.capture, "r" * 64, self.spec
            )

    def test_inherited_and_genuine_child_contexts_are_both_verified(self):
        raw, _, sessions, stable, actual = self._native_child_case()
        with (
            mock.patch.object(
                preflight_observed, "_session_identity", return_value="child-thread"
            ),
            mock.patch.object(
                preflight_observed, "verify_named_runtime"
            ) as verify_policy,
            mock.patch.object(
                preflight_observed, "_actual_runtime", return_value=actual
            ),
        ):
            self.assertEqual(
                preflight_observed._verify_child_session(
                    sessions,
                    "child-thread",
                    stable,
                    self.spec["expected"],
                    raw,
                ),
                {**actual, "native_turn_ids": ["child-turn"]},
            )
        self.assertEqual(verify_policy.call_count, 2)
        self.assertEqual(
            [call.args[1]["marker"] for call in verify_policy.call_args_list],
            ["inherited", "child"],
        )

    def test_missing_duplicate_foreign_or_unsupported_child_context_rejects(self):
        cases = ("missing", "duplicate", "foreign", "no-child-turn")
        for case in cases:
            with self.subTest(case=case):
                raw, rows, sessions, stable, actual = self._native_child_case()
                expected_error = "context-missing"
                if case == "missing":
                    sessions[0].pop()
                elif case == "duplicate":
                    sessions[0].append(copy.deepcopy(sessions[0][-1]))
                    expected_error = "context-binding-mismatch"
                elif case == "foreign":
                    sessions[0][-1]["payload"]["turn_id"] = "foreign-turn"
                    expected_error = "context-binding-mismatch"
                else:
                    rows[:] = [
                        row
                        for row in rows
                        if not (
                            row["payload"]["type"] == "codex_turn_started"
                            and row["payload"].get("thread_id") == "child-thread"
                        )
                    ]
                    for number, row in enumerate(rows, 1):
                        row["seq"] = number
                    self._rewrite(raw, rows)
                    expected_error = "turn-missing"
                with (
                    mock.patch.object(
                        preflight_observed,
                        "_session_identity",
                        return_value="child-thread",
                    ),
                    mock.patch.object(preflight_observed, "verify_named_runtime"),
                    mock.patch.object(
                        preflight_observed, "_actual_runtime", return_value=actual
                    ),
                    self.assertRaisesRegex(PreflightError, expected_error),
                ):
                    preflight_observed._verify_child_session(
                        sessions,
                        "child-thread",
                        stable,
                        self.spec["expected"],
                        raw,
                    )

    def test_child_or_inherited_native_policy_drift_rejects(self):
        for marker, field, value in (
            ("child", "model", "foreign-model"),
            ("inherited", "approval_policy", "on-request"),
        ):
            with self.subTest(marker=marker, field=field):
                raw, _, sessions, stable, actual = self._native_child_case()

                def runtime(context, _workspace):
                    observed = dict(actual)
                    if context["marker"] == marker:
                        observed[field] = value
                    return observed

                with (
                    mock.patch.object(
                        preflight_observed,
                        "_session_identity",
                        return_value="child-thread",
                    ),
                    mock.patch.object(preflight_observed, "verify_named_runtime"),
                    mock.patch.object(
                        preflight_observed, "_actual_runtime", side_effect=runtime
                    ),
                    self.assertRaisesRegex(
                        PreflightError, "child-native-policy-mismatch"
                    ),
                ):
                    preflight_observed._verify_child_session(
                        sessions,
                        "child-thread",
                        stable,
                        self.spec["expected"],
                        raw,
                    )

    def test_rehashed_raw_payload_and_submitted_report_tamper_are_rejected(self):
        root = Path(self.temporary.name) / "raw-trace"
        (root / "payloads").mkdir(parents=True)
        files = {
            "manifest.json": b"{}\n",
            "trace.jsonl": b"{}\n",
            "payloads/value.json": b'{"value":"original"}\n',
        }
        for name, value in files.items():
            (root / name).write_bytes(value)
        receipt = {
            name: hashlib.sha256(value).hexdigest() for name, value in files.items()
        }
        receipt_hash = canonical_hash(receipt)
        changed = b'{"value":"changed"}\n'
        (root / "payloads/value.json").write_bytes(changed)
        rehashed = {
            **receipt,
            "payloads/value.json": hashlib.sha256(changed).hexdigest(),
        }
        with self.assertRaisesRegex(Stage2Error, "receipt-hash-mismatch"):
            _load_inventory(root, rehashed, receipt_hash)

        report = {
            "kind": "Stage2ProductionRuntimePreflight",
            "schema_version": "1.2.0",
            "validation_scope": "production-single",
            "filesystem_read_isolation": "not-assessed",
            "quality_improvement": "not-established",
            "formal_ready": False,
        }
        with mock.patch.object(preflight, "inspect_preflight", return_value=report):
            tampered = {**report, "runtime_gate": False}
            with self.assertRaisesRegex(PreflightError, "does not equal recomputed"):
                preflight.verify_preflight(tampered, self.capture, "r" * 64, self.spec)

    def test_legacy_v11_contract_remains_accepted(self):
        legacy = copy.deepcopy(self.spec)
        legacy.pop("observation")
        legacy["schema_version"] = "1.1.0"
        self.assertTrue(preflight._validate_probe_spec(legacy))


if __name__ == "__main__":
    unittest.main()
