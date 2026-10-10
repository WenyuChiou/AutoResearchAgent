"""Extraction-only recovery preserves the failed action and immutable capture."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "cli"))
sys.path.insert(0, str(HERE))

from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage1_eval import model_calls  # noqa: E402
from stage2_fixture_helpers import write_stage2_fixture  # noqa: E402
from stage2_live.native import _path_binding  # noqa: E402
from stage2_live.review_models import review_task  # noqa: E402
from stage2_live.review_recovery import recover_failed_review  # noqa: E402
from stage2_workflow import (  # noqa: E402
    finish_action,
    initialize_workflow,
    inspect_workflow,
    start_action,
)
from test_stage2_checker import assessment  # noqa: E402
import test_stage2_native_namespace_integration as namespace_fixtures  # noqa: E402
from stage2_live import review_models, review_recovery  # noqa: E402


class Stage2ReviewRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.sources = self.root / "sources"
        self.packet = write_stage2_fixture(self.sources, candidate_count=2)
        packet_path = self.root / "packet.json"
        packet_path.write_text(json.dumps(self.packet), encoding="utf-8")
        self.run = self.root / "run"
        initialize_workflow(packet_path, self.sources, self.run, {}, {})
        state = inspect_workflow(self.run)
        self.snapshot = state["latest_snapshot"]["event"]["payload"]["snapshot_sha256"]
        self.view = review_task(self.packet, "candidate-1", self.snapshot, "challenger")
        self.old_preflight = {"receipt": "a" * 64}
        self.environment = {
            "home": str(self.root / "old-home"),
            "workspace": str(self.root / "old-workspace"),
            "preflight_sha256": canonical_hash(self.old_preflight),
            "preflight_inventory_receipt_sha256": canonical_hash(None),
            "policy_sha256": canonical_hash({"old": "policy"}),
            "profile_config": {"kind": "file", "sha256": "p" * 64},
        }
        self.action_id = f"review-{self.snapshot[:12]}-candidate-1-challenger"
        started = start_action(
            self.run,
            self.action_id,
            "stage2-independent-review",
            {"role": "challenger", "view_sha256": canonical_hash(self.view)},
            {
                "mode": "native",
                "formal_ready": False,
                "bindings": {"model": "test-model", "reasoning": "high"},
                "environment_bindings": {"review-slot:0:challenger": self.environment},
            },
            state["head_sha256"],
        )
        failure = self.root / "old-failure.json"
        failure.write_text('{"error":"retained-parser-failure"}', encoding="utf-8")
        finish_action(
            self.run,
            self.action_id,
            "failed",
            {
                "summary.json": {
                    "path": str(failure),
                    "sha256": hashlib.sha256(failure.read_bytes()).hexdigest(),
                }
            },
            None,
            "retained-parser-failure",
            started["event"]["event_sha256"],
        )
        self.original = copy.deepcopy(
            inspect_workflow(self.run)["actions"][self.action_id]
        )
        self.capture = self.root / "capture"
        self.capture.mkdir()
        (self.capture / "run.json").write_text(
            '{"fixture":"authentic verifier is mocked"}', encoding="utf-8"
        )
        (self.capture / "stdout.jsonl").write_bytes(b"original saved transcript\n")
        (self.capture / "archive").mkdir()
        (self.capture / "archive" / "evidence.txt").write_bytes(b"original evidence")
        self.receipt = hashlib.sha256(
            (self.capture / "run.json").read_bytes()
        ).hexdigest()
        self.record = {
            "evidence_class": "host-native-capture",
            "event_summary": {"thread_id": "saved-session"},
            "stable_request_binding": {
                "codex_home": self.environment["home"],
                "workspace": self.environment["workspace"],
                "policy_bindings": {"old": "policy"},
                "codex_profile_config": {
                    "path": "old-profile",
                    **self.environment["profile_config"],
                },
                "model": "test-model",
                "reasoning": "high",
                "input_bindings": {"sources": _path_binding(self.sources)},
            },
        }
        self.native = {
            "codex": "fixture-codex",
            "model": "test-model",
            "reasoning": "high",
            "extraction_policy": {"timeout_seconds": 600},
            "config_bindings": {"capture_cli": str(HERE.parent)},
            "policy_bindings": {},
        }
        review = {
            "candidate_id": "candidate-1",
            "candidate_version": 1,
            "role": "challenger",
            "snapshot_sha256": self.snapshot,
            "view_sha256": canonical_hash(self.view),
            "assessment": assessment(self.packet),
            "session_id": "saved-session",
            "native_artifact": {
                "path": str(self.capture / "stdout.jsonl"),
                "sha256": "d" * 64,
            },
            "initial": True,
            "assumptions": ["Original assumption"],
            "strongest_alternative": "Original alternative",
            "change_conditions": ["Original condition"],
        }
        self.value = {
            "review": review,
            "native_receipt": self.receipt,
            "adapter_mode": "native",
            "native_capture_verified": True,
            "capture_evidence_class": "host-native-capture",
            "scientific_truth_attested": False,
            "replay_receipt": {"unit_receipts": {"initial-review": {"fixture": True}}},
        }
        self.args = dict(
            run_dir=self.run,
            failed_action_id=self.action_id,
            candidate_id="candidate-1",
            role="challenger",
            source_root=self.sources,
            expected_snapshot_sha256=self.snapshot,
            expected_head=inspect_workflow(self.run)["head_sha256"],
            capture_dir=self.capture,
            capture_receipt=self.receipt,
            original_preflight=self.old_preflight,
            original_inventory_receipt=None,
            execution_preflight={"new": "genuinely current proof"},
            native=self.native,
            evaluator_home=self.root / "new-home",
            extractor_workspace=self.root / "new-workspace",
            output_dir=self.root / "recovery",
        )
        self.model = self.enterContext(
            patch("stage2_live.review_recovery.extract_review", return_value=self.value)
        )
        self.config = {
            "native_namespace": {"synthetic": True},
            "effective_cwd": str(self.args["extractor_workspace"].resolve()),
        }
        self.request_config = self.enterContext(
            patch(
                "stage2_live.review_recovery._request_config", return_value=self.config
            )
        )

        def synthetic_extraction(*_args, **kwargs):
            request = (
                Path(kwargs["output_dir"]) / "initial-review.model-call/request.json"
            )
            request.parent.mkdir(parents=True, exist_ok=True)
            request.write_text(json.dumps({"config": self.config}), encoding="utf-8")
            return self.value

        self.model.side_effect = synthetic_extraction
        self.enterContext(
            patch(
                "stage2_live.review_recovery._captured_input",
                return_value=(self.record, "saved native output"),
            )
        )
        self.enterContext(
            patch(
                "stage2_live.review_recovery.verify_environment_capture",
                return_value={"status": "verified", "inventory_status": "not-captured"},
            )
        )
        self.proof = self.enterContext(
            patch(
                "stage2_live.review_recovery.verify_environment_start",
                return_value=(
                    {},
                    {
                        "status": "passed",
                        "runtime_gate": True,
                        "validation_scope": "production-single",
                    },
                ),
            )
        )
        self.enterContext(
            patch(
                "stage2_live.review_recovery._adapter_binding",
                return_value={"current": "code and runtime"},
            )
        )

    def test_recovery_appends_distinct_action_without_repeating_native(self):
        result = recover_failed_review(**self.args)
        state = inspect_workflow(self.run)
        self.assertEqual(state["actions"][self.action_id], self.original)
        self.assertEqual(
            state["actions"][result["action_id"]]["result"]["status"], "complete"
        )
        self.assertEqual(result["review_result"], self.value)
        self.assertEqual(result["requested_native_calls"], 0)
        self.assertFalse(result["scientific_truth_attested"])
        self.assertEqual(self.proof.call_count, 3)
        self.assertFalse(self.model.call_args.kwargs["resume"])

    def test_completed_recovery_reuses_receipted_extraction(self):
        result = recover_failed_review(**self.args)
        head = inspect_workflow(self.run)["head_sha256"]
        again = recover_failed_review(**{**self.args, "expected_head": head})
        self.assertTrue(again["replayed"])
        self.assertEqual(again["action_id"], result["action_id"])
        self.assertTrue(self.model.call_args.kwargs["resume"])
        self.assertEqual(
            self.model.call_args.kwargs["resume_receipt"], self.value["replay_receipt"]
        )
        self.assertEqual(inspect_workflow(self.run)["head_sha256"], head)

    def test_changed_snapshot_candidate_role_or_receipt_rejected_before_model(self):
        for change in (
            {"expected_snapshot_sha256": "f" * 64},
            {"candidate_id": "candidate-2"},
            {"role": "feasibility"},
            {"capture_receipt": "f" * 64},
        ):
            with self.subTest(change=change), self.assertRaises(Stage2Error):
                recover_failed_review(**{**self.args, **change})
        self.model.assert_not_called()
        self.assertEqual(len(inspect_workflow(self.run)["actions"]), 1)

    def test_current_proof_failure_never_uses_old_proof_as_execution_authority(self):
        self.proof.side_effect = Stage2Error("execution-preflight-code-changed")
        with self.assertRaisesRegex(Stage2Error, "execution-preflight-code-changed"):
            recover_failed_review(**self.args)
        self.model.assert_not_called()
        self.assertEqual(len(inspect_workflow(self.run)["actions"]), 1)

    def test_other_original_environment_or_source_rejected(self):
        for field, value in (
            ("workspace", "different-workspace"),
            ("model", "different-model"),
            ("policy_bindings", {"changed": True}),
            ("input_bindings", {}),
        ):
            prior = copy.deepcopy(self.record)
            self.record["stable_request_binding"][field] = value
            with self.subTest(field=field), self.assertRaises(Stage2Error):
                recover_failed_review(**self.args)
            self.record.clear()
            self.record.update(prior)
        self.model.assert_not_called()

    def test_old_source_pin_cannot_authorize_current_executor(self):
        self.native["config_bindings"]["capture_cli"] = str(
            self.root / "frozen-old-library"
        )
        with self.assertRaisesRegex(Stage2Error, "current-executor-source-required"):
            recover_failed_review(**self.args)
        self.model.assert_not_called()
        self.proof.assert_not_called()

    def test_nonproduction_or_failed_current_proof_rejected(self):
        for report in (
            {"status": "passed", "runtime_gate": True, "validation_scope": "formal"},
            {
                "status": "passed",
                "runtime_gate": False,
                "validation_scope": "production-single",
            },
        ):
            self.proof.return_value = ({}, report)
            with (
                self.subTest(report=report),
                self.assertRaisesRegex(
                    Stage2Error, "current-production-proof-required"
                ),
            ):
                recover_failed_review(**self.args)
        self.model.assert_not_called()

    def test_completed_recovery_rejects_changed_policy_without_another_call(self):
        recover_failed_review(**self.args)
        head = inspect_workflow(self.run)["head_sha256"]
        self.model.reset_mock()
        self.native["extraction_policy"]["timeout_seconds"] = 601
        with self.assertRaisesRegex(Stage2Error, "workflow-action-id-input-conflict"):
            recover_failed_review(**{**self.args, "expected_head": head})
        self.model.assert_not_called()
        self.assertEqual(inspect_workflow(self.run)["head_sha256"], head)

    def test_model_failure_preserved_and_not_blindly_retried(self):
        self.model.side_effect = RuntimeError("actual extraction failed")
        with self.assertRaisesRegex(RuntimeError, "actual extraction failed"):
            recover_failed_review(**self.args)
        state = inspect_workflow(self.run)
        recovery = next(
            row for key, row in state["actions"].items() if key != self.action_id
        )
        self.assertEqual(recovery["result"]["status"], "failed")
        self.assertEqual(state["actions"][self.action_id], self.original)
        self.model.reset_mock()
        with self.assertRaisesRegex(
            Stage2Error, "workflow-action-replay-not-authorized"
        ):
            recover_failed_review(
                **{**self.args, "expected_head": state["head_sha256"]}
            )
        self.model.assert_not_called()

    def test_injected_extraction_cannot_complete_recovery(self):
        self.value["adapter_mode"] = "injected-test"
        with self.assertRaisesRegex(Stage2Error, "authentic-extraction-required"):
            recover_failed_review(**self.args)
        self.assertEqual(
            inspect_workflow(self.run)["actions"][self.action_id], self.original
        )

    def test_wrong_capture_extraction_cannot_complete_recovery(self):
        self.value["native_receipt"] = "f" * 64
        with self.assertRaisesRegex(Stage2Error, "extraction-capture-mismatch"):
            recover_failed_review(**self.args)
        self.assertEqual(
            inspect_workflow(self.run)["actions"][self.action_id], self.original
        )

    def test_changed_candidate_version_in_extraction_cannot_complete_recovery(self):
        self.value["review"]["candidate_version"] = 2
        with self.assertRaises(Stage2Error):
            recover_failed_review(**self.args)
        self.assertEqual(
            inspect_workflow(self.run)["actions"][self.action_id], self.original
        )

    def test_output_collision_rejected_before_model(self):
        with self.assertRaisesRegex(Stage2Error, "output-collision"):
            recover_failed_review(
                **{**self.args, "output_dir": self.capture / "output"}
            )
        self.model.assert_not_called()
        self.assertEqual(
            inspect_workflow(self.run)["actions"][self.action_id], self.original
        )

    def test_stale_snapshot_action_unchanged_on_rejection(self):
        with self.assertRaises(Stage2Error):
            recover_failed_review(**{**self.args, "expected_head": "e" * 64})
        self.model.assert_not_called()
        self.assertEqual(
            inspect_workflow(self.run)["actions"][self.action_id], self.original
        )

    def test_capture_change_during_model_call_cannot_complete_recovery(self):
        def changed(*_args, **_kwargs):
            (self.capture / "run.json").write_text("changed", encoding="utf-8")
            return self.value

        self.model.side_effect = changed
        with self.assertRaisesRegex(Stage2Error, "original-changed-during-extraction"):
            recover_failed_review(**self.args)
        self.assertEqual(
            inspect_workflow(self.run)["actions"][self.action_id], self.original
        )

    def test_transcript_change_with_unchanged_receipt_cannot_complete_recovery(self):
        def changed(*_args, **_kwargs):
            (self.capture / "stdout.jsonl").write_bytes(b"changed transcript")
            return self.value

        self.model.side_effect = changed
        with self.assertRaisesRegex(Stage2Error, "capture-changed"):
            recover_failed_review(**self.args)
        self.assertEqual(
            hashlib.sha256((self.capture / "run.json").read_bytes()).hexdigest(),
            self.receipt,
        )
        self.assertEqual(
            inspect_workflow(self.run)["actions"][self.action_id], self.original
        )

    def test_archive_change_with_unchanged_receipt_cannot_complete_recovery(self):
        def changed(*_args, **_kwargs):
            (self.capture / "archive" / "evidence.txt").write_bytes(b"changed evidence")
            return self.value

        self.model.side_effect = changed
        with self.assertRaisesRegex(Stage2Error, "capture-changed"):
            recover_failed_review(**self.args)
        self.assertEqual(
            hashlib.sha256((self.capture / "run.json").read_bytes()).hexdigest(),
            self.receipt,
        )
        self.assertEqual(
            inspect_workflow(self.run)["actions"][self.action_id], self.original
        )

    def test_missing_namespace_or_other_cwd_rejected_before_model(self):
        for config in ({}, {**self.config, "effective_cwd": "wrong-workspace"}):
            self.request_config.return_value = config
            with (
                self.subTest(config=config),
                self.assertRaisesRegex(
                    Stage2Error, "proven-extraction-workspace-required"
                ),
            ):
                recover_failed_review(**self.args)
        self.model.assert_not_called()

    def test_execution_policy_change_at_handoff_rejected_before_model(self):
        original_start = start_action

        def changed(*args, **kwargs):
            result = original_start(*args, **kwargs)
            self.native["extraction_policy"]["timeout_seconds"] = 601
            return result

        with patch.object(review_recovery, "start_action", side_effect=changed):
            with self.assertRaisesRegex(
                Stage2Error, "execution-changed-before-handoff"
            ):
                recover_failed_review(**self.args)
        self.model.assert_not_called()
        self.assertEqual(
            inspect_workflow(self.run)["actions"][self.action_id], self.original
        )

    def test_execution_config_bytes_change_during_extraction_rejected(self):
        config = self.root / "current-executor-config.json"
        config.write_bytes(b"original current config")
        self.native["config_bindings"]["current_config"] = str(config)

        def changed(*_args, **_kwargs):
            config.write_bytes(b"changed current config")
            return self.value

        self.model.side_effect = changed
        with self.assertRaisesRegex(Stage2Error, "execution-changed-during-extraction"):
            recover_failed_review(**self.args)
        self.assertEqual(
            inspect_workflow(self.run)["actions"][self.action_id], self.original
        )

    def test_adapter_bytes_change_during_extraction_rejected(self):
        adapter = self.enterContext(patch.object(review_recovery, "_adapter_binding"))
        adapter.side_effect = [
            {"runtime": "original"},
            {"runtime": "original"},
            {"runtime": "changed"},
        ]
        with self.assertRaisesRegex(Stage2Error, "execution-changed-during-extraction"):
            recover_failed_review(**self.args)

    def test_extracted_archive_records_exact_proven_handoff(self):
        original = self.model.side_effect

        def wrong(*args, **kwargs):
            value = original(*args, **kwargs)
            request = (
                Path(kwargs["output_dir"]) / "initial-review.model-call/request.json"
            )
            request.write_text('{"config":{"effective_cwd":"wrong"}}', encoding="utf-8")
            return value

        self.model.side_effect = wrong
        with self.assertRaisesRegex(Stage2Error, "extraction-handoff-mismatch"):
            recover_failed_review(**self.args)

    def _real_adapter_fixture(self, *, change_runtime=False):
        """Real extraction/unit/archive pipeline, synthetic process boundary only."""
        fixture = namespace_fixtures.NamespaceIntegrationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        policy = {
            "schema_version": model_calls.MODEL_CALL_ARCHIVE_VERSION,
            "timeout_seconds": 600,
            "max_transient_transport_retries": 0,
            "evaluator_bundle_sha256": "a" * 64,
        }
        args = {
            **self.args,
            "evaluator_home": fixture.home,
            "extractor_workspace": fixture.work,
            "output_dir": fixture.capture_root / "recovery",
            "native": {
                **self.native,
                "codex": fixture.codex,
                "extraction_policy": policy,
            },
        }
        payload = {
            "assessment": {
                k: v
                for k, v in self.value["review"]["assessment"].items()
                if k
                not in {
                    "kind",
                    "schema_version",
                    "event_id",
                    "candidate_id",
                    "candidate_version",
                    "packet_sha256",
                }
            },
            "assumptions": ["synthetic integration assumption"],
            "strongest_alternative": "synthetic integration alternative",
            "change_conditions": ["synthetic integration condition"],
        }

        def boundary(command, **kwargs):
            self.assertEqual(kwargs["cwd"], str(fixture.work))
            self.assertEqual(kwargs["env"]["CODEX_HOME"], str(fixture.home))
            output = Path(command[command.index("-o") + 1])
            output.write_text(json.dumps(payload), encoding="utf-8")
            rows = [
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": json.dumps(payload)},
                },
                {"type": "turn.completed"},
            ]
            if change_runtime:
                fixture.codex.write_bytes(b"runtime changed during call")
            return SimpleNamespace(
                returncode=0,
                stderr=b"",
                stdout=("\n".join(map(json.dumps, rows)) + "\n").encode(),
            )

        with (
            patch.object(
                review_recovery, "extract_review", review_models.extract_review
            ),
            patch.object(
                review_recovery, "_request_config", model_calls._request_config
            ),
            patch.object(
                review_models,
                "_captured_input",
                return_value=(self.record, "saved output"),
            ),
            patch.object(model_calls, "bind_namespace", return_value=fixture.binding),
            patch.object(model_calls, "wrap_namespace", side_effect=fixture.wrap),
            patch.object(
                model_calls, "_execute_bound_process", side_effect=boundary
            ) as transport,
        ):
            result = recover_failed_review(**args)
            self.assertEqual(transport.call_count, 1)
            again = recover_failed_review(
                **{**args, "expected_head": result["head_sha256"]}
            )
            self.assertTrue(again["replayed"])
            self.assertEqual(transport.call_count, 1)
        return result

    def test_real_extraction_adapter_keeps_proven_cwd_and_receipt_only_resume(self):
        result = self._real_adapter_fixture()
        self.assertEqual(result["review_result"]["adapter_mode"], "native")
        self.assertFalse(result["scientific_truth_attested"])
        self.assertEqual(
            inspect_workflow(self.run)["actions"][self.action_id], self.original
        )

    def test_real_extraction_adapter_rejects_runtime_replacement(self):
        # The adapter itself stays real; only native transport is synthetic.
        with patch.object(
            review_recovery, "_adapter_binding", review_models._adapter_binding
        ):
            with self.assertRaises(Stage2Error):
                self._real_adapter_fixture(change_runtime=True)
        self.assertEqual(
            inspect_workflow(self.run)["actions"][self.action_id], self.original
        )


if __name__ == "__main__":
    unittest.main()
