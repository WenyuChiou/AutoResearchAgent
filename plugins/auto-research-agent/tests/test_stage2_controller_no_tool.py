"""Synthetic controller composition tests; no native model is dispatched."""

from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))

from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_live import controller_no_tool as subject  # noqa: E402
from stage2_live.no_tool_call import NoToolCallResult  # noqa: E402


def _spec(model="model", reasoning="medium"):
    return {
        "schema_version": "1.2.0",
        "native": {
            "codex": "/synthetic/codex",
            "model": model,
            "reasoning": reasoning,
        },
    }


def _binding(home, telemetry):
    return {
        "path": str(home / "native-namespace.json"),
        "sha256": "a" * 64,
        "dispatcher_sha256": "b" * 64,
        "scope": {"telemetry": str(telemetry)},
    }


def _capture(execution_policy="no-offered-tools-v1"):
    capture = {
        "kind": "Stage2NoToolTraceCapture"
        if execution_policy == "no-offered-tools-v1"
        else "Stage2NoExecutionTraceCapture",
        "schema_version": "1.0.0",
        "units": {
            "extract": {
                "seal_path": "/synthetic/evidence/seal.json",
                "seal_sha256": "c" * 64,
                "trace_root": "/synthetic/trace",
                "proof": {"verification_status": "verified-no-tools"},
            }
        },
        "new_model_calls": 0,
        "new_tool_calls": 0,
        "resume_action": "capture-finished-no-execution",
    }
    if execution_policy == "no-executed-tools-v1":
        capture["units"]["extract"]["proof"] = {
            "verification_status": "verified",
            "offered_tool_inventory": [{"function": 1}],
        }
        unsigned = {
            "kind": "Stage2NoToolCallSealReceipt",
            "schema_version": "1.0.0",
            "execution_policy": execution_policy,
            "seal_sha256": {"extract": "c" * 64},
        }
        capture.update(
            execution_policy=execution_policy,
            seal_receipt={**unsigned, "receipt_sha256": canonical_hash(unsigned)},
        )
    return capture


class ControllerNoToolTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.home = self.root / "home"
        self.telemetry = self.root / "telemetry"
        self.output = self.root / "out"

    def _install_run(self):
        namespace = patch.object(
            subject,
            "bind_namespace",
            side_effect=lambda codex, home: _binding(self.home, self.telemetry),
        )
        namespace.start()
        self.addCleanup(namespace.stop)

        def fake_run(callback, **options):
            self.assertEqual(options["telemetry_root"], str(self.telemetry))
            policy = options["execution_policy"]
            result = callback(
                *options["callback_args"], **(options["callback_kwargs"] or {})
            )
            return NoToolCallResult(result, _capture(policy))

        runner = patch.object(subject, "run_no_tool_call", side_effect=fake_run)
        mocked = runner.start()
        self.addCleanup(runner.stop)
        return mocked

    def _result(self, callback=None, execution_policy="no-offered-tools-v1"):
        self._install_run()
        return subject.run_controller_no_tool(
            callback or (lambda: {"ok": True}),
            _spec(),
            self.home,
            self.output,
            execution_policy=execution_policy,
        )

    def _assert_history_rejected(
        self,
        result,
        spec=None,
        execution_policy="no-offered-tools-v1",
        error="history-binding-mismatch",
    ):
        with patch.object(subject, "resume_no_tool_call") as resume:
            with self.assertRaisesRegex(Stage2Error, error):
                subject.verify_controller_no_tool_history(
                    result,
                    spec or _spec(),
                    self.home,
                    self.output,
                    execution_policy=execution_policy,
                )
            resume.assert_not_called()

    def test_run_preserves_original_result_and_binds_receipts(self):
        callback = Mock(return_value={"canonical": [1, 2]})
        run = self._install_run()
        result = subject.run_controller_no_tool(
            callback,
            _spec(),
            self.home,
            self.output,
            args=(1,),
            kwargs={"named": 2},
        )
        metadata = result["no_tool_execution"]
        self.assertEqual(result["canonical"], [1, 2])
        self.assertEqual(
            metadata["original_call_result_sha256"],
            canonical_hash({"canonical": [1, 2]}),
        )
        self.assertEqual(metadata["seal_sha256"], {"extract": "c" * 64})
        self.assertEqual(metadata["schema_version"], "1.0.0")
        self.assertNotIn("execution_policy", metadata)
        self.assertNotIn("seal_receipt", metadata)
        self.assertNotIn("execution_policy", metadata["capture"])
        self.assertEqual(
            metadata["evidence_dir"], str(self.root / "out-trace-evidence")
        )
        callback.assert_called_once_with(1, named=2)
        self.assertEqual(run.call_count, 1)

    def test_explicit_no_execution_mode_uses_version_1_1_metadata(self):
        original = {"canonical": [1, 2]}
        callback = Mock(return_value=original)
        result = self._result(callback, "no-executed-tools-v1")
        metadata = result["no_tool_execution"]
        self.assertEqual(result["canonical"], [1, 2])
        self.assertEqual(metadata["schema_version"], "1.1.0")
        self.assertEqual(metadata["execution_policy"], "no-executed-tools-v1")
        self.assertEqual(metadata["capture"]["kind"], "Stage2NoExecutionTraceCapture")
        self.assertEqual(metadata["seal_receipt"], metadata["capture"]["seal_receipt"])
        self.assertEqual(
            metadata["capture"]["units"]["extract"]["proof"]["offered_tool_inventory"],
            [{"function": 1}],
        )
        callback.assert_called_once_with()

    def test_missing_namespace_rejects_before_callback(self):
        callback, run = Mock(), Mock()
        with (
            patch.object(subject, "bind_namespace", return_value=None),
            patch.object(subject, "run_no_tool_call", run),
            self.assertRaisesRegex(Stage2Error, "namespace-required"),
        ):
            subject.run_controller_no_tool(callback, _spec(), self.home, self.output)
        callback.assert_not_called()
        run.assert_not_called()

    def test_invalid_policy_rejects_before_namespace_and_callback(self):
        callback, namespace, run = Mock(), Mock(), Mock()
        with (
            patch.object(subject, "bind_namespace", namespace),
            patch.object(subject, "run_no_tool_call", run),
            self.assertRaisesRegex(Stage2Error, "execution-policy-invalid"),
        ):
            subject.run_controller_no_tool(
                callback,
                _spec(),
                self.home,
                self.output,
                execution_policy="invalid",
            )
        callback.assert_not_called()
        namespace.assert_not_called()
        run.assert_not_called()

    def test_history_rejects_telemetry_mismatch(self):
        result = self._result()
        result["no_tool_execution"]["namespace_binding"]["telemetry"] = "X"
        self._assert_history_rejected(result)

    def test_history_rejects_model_mismatch(self):
        self._assert_history_rejected(self._result(), _spec(model="changed"))

    def test_history_rejects_changed_seal(self):
        result = deepcopy(self._result())
        result["no_tool_execution"]["seal_sha256"]["extract"] = "d" * 64
        self._assert_history_rejected(result)

    def test_history_rejects_changed_path(self):
        result = deepcopy(self._result())
        result["no_tool_execution"]["output_dir"] = str(self.root / "other")
        self._assert_history_rejected(result)

    def test_history_resumes_without_reexecuting_callback(self):
        callback = Mock(return_value={"canonical": True})
        result = self._result(callback)
        resumed = {"resume_action": "verified-replay-no-execution", "proofs": {}}
        with patch.object(
            subject, "resume_no_tool_call", return_value=resumed
        ) as resume:
            verified = subject.verify_controller_no_tool_history(
                result, _spec(), self.home, self.output
            )
        self.assertEqual(verified, resumed)
        callback.assert_called_once_with()
        resume.assert_called_once_with(
            self.output,
            self.root / "out-trace-evidence",
            {"extract": "c" * 64},
            expected_config={
                "model": "model",
                "reasoning": "medium",
                "sandbox_mode": "read-only",
                "approval_policy": "never",
            },
            execution_policy="no-offered-tools-v1",
        )

    def test_no_execution_history_resumes_with_original_receipt(self):
        callback = Mock(return_value={"canonical": True})
        result = self._result(callback, "no-executed-tools-v1")
        receipt = result["no_tool_execution"]["seal_receipt"]
        resumed = {"execution_policy": "no-executed-tools-v1", "proofs": {}}
        with patch.object(
            subject, "resume_no_tool_call", return_value=resumed
        ) as resume:
            verified = subject.verify_controller_no_tool_history(
                result,
                _spec(),
                self.home,
                self.output,
                execution_policy="no-executed-tools-v1",
            )
        self.assertEqual(verified, resumed)
        callback.assert_called_once_with()
        resume.assert_called_once_with(
            self.output,
            self.root / "out-trace-evidence",
            receipt,
            expected_config={
                "model": "model",
                "reasoning": "medium",
                "sandbox_mode": "read-only",
                "approval_policy": "never",
            },
            execution_policy="no-executed-tools-v1",
        )

    def test_no_execution_history_rejects_switch_missing_or_tampered_receipt(self):
        result = self._result(execution_policy="no-executed-tools-v1")
        self._assert_history_rejected(result, error="history-policy-mismatch")

        missing = deepcopy(result)
        del missing["no_tool_execution"]["seal_receipt"]
        self._assert_history_rejected(
            missing,
            execution_policy="no-executed-tools-v1",
            error="metadata-invalid",
        )

        tampered = deepcopy(result)
        tampered["no_tool_execution"]["seal_receipt"]["receipt_sha256"] = "0" * 64
        self._assert_history_rejected(
            tampered,
            execution_policy="no-executed-tools-v1",
            error="seal-receipt-invalid",
        )


if __name__ == "__main__":
    unittest.main()


class ControllerPostCaptureFailureTests(unittest.TestCase):
    def test_invalid_result_retains_real_synthetic_seals_and_resumes_without_callback(
        self,
    ):
        from test_stage2_no_tool_call import NoToolCallTests
        from stage2_live.no_tool_call import NoToolCallFailure, resume_no_tool_call

        for policy in ("no-offered-tools-v1", "no-executed-tools-v1"):
            with self.subTest(policy=policy):
                case = NoToolCallTests(methodName="runTest")
                case.setUp()
                self.addCleanup(case.doCleanups)
                case.evidence = case.output.with_name(
                    case.output.name + "-trace-evidence"
                )
                tools = (
                    []
                    if policy == "no-offered-tools-v1"
                    else [
                        {
                            "type": "function",
                            "name": "unused",
                            "parameters": {"type": "object"},
                        }
                    ]
                )
                namespace = _binding(case.base / "home", case.telemetry)
                spec = _spec("synthetic-model")
                spec["native"]["reasoning"] = "medium"
                case.replay_calls = []

                def callback():
                    case.native_callback(tools)
                    return "invalid canonical result"

                with (
                    patch.object(subject, "bind_namespace", return_value=namespace),
                    patch(
                        "stage2_live.no_tool_call.replay_native_model_call_archive",
                        side_effect=case.replay,
                    ),
                    patch(
                        "stage2_live.no_tool_trace_capture.inspect_native_trace",
                        side_effect=case.observation,
                    ),
                    patch(
                        "stage2_live.no_tool_trace_evidence.inspect_native_trace",
                        side_effect=case.observation,
                    ),
                    self.assertRaises(NoToolCallFailure) as caught,
                ):
                    subject.run_controller_no_tool(
                        callback,
                        spec,
                        case.base / "home",
                        case.output,
                        execution_policy=policy,
                    )
                failure = caught.exception
                self.assertEqual(failure.phase, "controller-binding")
                self.assertIsInstance(failure.__cause__, Stage2Error)
                state = failure.state
                self.assertIs(state["completed_call"].evidence, state["evidence"])
                self.assertEqual(state["execution_policy"], policy)
                original = state["retained_seal_receipt"]
                self.assertEqual(
                    set(original["seal_sha256"]), {"initial", "correction"}
                )
                self.assertEqual(len(list(case.evidence.rglob("seal.json"))), 2)
                with (
                    patch(
                        "stage2_live.no_tool_call.replay_native_model_call_archive",
                        side_effect=case.replay,
                    ),
                    patch(
                        "stage2_live.no_tool_trace_evidence.inspect_native_trace",
                        side_effect=case.observation,
                    ),
                ):
                    resumed = resume_no_tool_call(
                        case.output,
                        case.evidence,
                        original,
                        expected_config=case.expected,
                        execution_policy=policy,
                    )
                self.assertEqual(case.callback_count, 1)
                self.assertEqual(resumed["new_model_calls"], 0)
                self.assertEqual(resumed["seal_receipt"], original)
