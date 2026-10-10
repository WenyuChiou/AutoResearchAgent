"""Pre-dispatch rejection must preserve failed actions and prevent native replay."""

import copy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "cli"))
sys.path.insert(0, str(HERE))

from stage1_eval import model_calls  # noqa: E402
from stage1_eval.common import EvaluationError  # noqa: E402
from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_live import review_models, review_recovery  # noqa: E402
from stage2_live.native import _path_binding  # noqa: E402
from stage2_workflow import finish_action, inspect_workflow, start_action  # noqa: E402
import test_stage2_native_namespace_integration as namespace_fixture  # noqa: E402
import test_stage2_review_recovery as recovery_fixture  # noqa: E402


class ReviewPreDispatchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = recovery_fixture.Stage2ReviewRecoveryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_namespace_output_rejected_before_action_or_extraction(self):
        fixture = self.fixture
        fixture.config["native_namespace"] = {
            "scope": {
                "capture_root": str(fixture.root / "allowed-capture-root"),
                "workspace": str(fixture.args["extractor_workspace"]),
            },
        }
        head = inspect_workflow(fixture.run)["head_sha256"]
        with self.assertRaisesRegex(Stage2Error, "namespace-output-scope"):
            review_recovery.recover_failed_review(**fixture.args)
        fixture.model.assert_not_called()
        self.assertEqual(inspect_workflow(fixture.run)["head_sha256"], head)

    def test_missing_predecessor_cannot_select_legacy_recovery(self):
        fixture = self.fixture
        head = inspect_workflow(fixture.run)["head_sha256"]
        with self.assertRaisesRegex(Stage2Error, "predecessor-required"):
            review_recovery.continue_pre_dispatch_review_recovery(None, **fixture.args)
        fixture.model.assert_not_called()
        self.assertEqual(inspect_workflow(fixture.run)["head_sha256"], head)

    def prepare_predecessor(self):
        """Use the real preparation/namespace guard; no process is dispatched."""
        f = self.fixture
        # The producer reads the persisted snapshot, including its JSON field
        # order, before constructing the exact model prompt.
        f.packet = inspect_workflow(f.run)["latest_snapshot"]["packet"]
        f.view = review_models.review_task(
            f.packet, "candidate-1", f.snapshot, "challenger"
        )
        ns = namespace_fixture.NamespaceIntegrationTests()
        ns.setUp()
        self.addCleanup(ns.doCleanups)
        policy = {
            "schema_version": model_calls.MODEL_CALL_ARCHIVE_VERSION,
            "timeout_seconds": 600,
            "max_transient_transport_retries": 0,
            "evaluator_bundle_sha256": "a" * 64,
        }
        self.args = {
            **f.args,
            "evaluator_home": ns.home,
            "extractor_workspace": ns.work,
            "native": {**f.native, "codex": ns.codex, "extraction_policy": policy},
        }
        self.enterContext(
            patch.object(model_calls, "bind_namespace", return_value=ns.binding)
        )
        self.enterContext(
            patch.object(model_calls, "wrap_namespace", side_effect=ns.wrap)
        )
        self.enterContext(
            patch.object(
                review_recovery, "_request_config", model_calls._request_config
            )
        )
        self.enterContext(
            patch.object(
                review_recovery, "_adapter_binding", review_models._adapter_binding
            )
        )
        self.enterContext(
            patch.object(
                review_models,
                "_captured_input",
                return_value=(f.record, "saved native output"),
            )
        )
        self.transport = self.enterContext(
            patch.object(model_calls, "_execute_bound_process")
        )
        current = review_recovery._current_execution_binding(
            self.args["execution_preflight"], self.args["native"], ns.home, ns.work
        )
        self.inputs = {
            "schema_version": "1.0.0",
            "failed_action_id": f.action_id,
            "failed_request_sha256": f.original["request"]["request_sha256"],
            "failed_result_sha256": f.original["result"]["result_sha256"],
            "candidate_id": "candidate-1",
            "role": "challenger",
            "view_sha256": canonical_hash(f.view),
            "capture_dir": str(f.capture.resolve()),
            "capture_receipt": f.receipt,
            "capture_tree_sha256": _path_binding(f.capture)["sha256"],
            "original_environment": {
                "status": "verified",
                "inventory_status": "not-captured",
            },
        }
        self.previous_id = (
            "review-recovery-"
            + canonical_hash(["1.0.0", f.action_id, f.snapshot, f.receipt])[:24]
        )
        self.old_output = f.args["output_dir"].resolve()
        started = start_action(
            f.run,
            self.previous_id,
            "stage2-independent-review-recovery",
            self.inputs,
            {
                "execution": current,
                "output_dir": str(self.old_output),
                "formal_ready": False,
            },
            inspect_workflow(f.run)["head_sha256"],
        )
        with self.assertRaisesRegex(
            EvaluationError, "archive violates frozen attempt limit"
        ):
            review_models.extract_review(
                f.packet,
                f.sources,
                "candidate-1",
                f.snapshot,
                "challenger",
                f.capture,
                f.receipt,
                codex=ns.codex,
                evaluator_home=ns.home,
                model=f.native["model"],
                reasoning="high",
                execution_policy=policy,
                output_dir=self.old_output / "extraction",
            )
        self.transport.assert_not_called()
        failure = self.old_output / "recovery-failure.json"
        review_recovery._write_new(
            failure,
            {
                "error_type": "EvaluationError",
                "error": "model-call archive violates frozen attempt limit",
            },
        )
        finish_action(
            f.run,
            self.previous_id,
            "failed",
            {
                "failure.json": {
                    "path": str(failure),
                    "sha256": hashlib.sha256(failure.read_bytes()).hexdigest(),
                }
            },
            None,
            "model-call archive violates frozen attempt limit",
            started["event"]["event_sha256"],
        )
        self.previous = copy.deepcopy(
            inspect_workflow(f.run)["actions"][self.previous_id]
        )
        self.binding = {
            "schema_version": "1.1.0",
            "action_id": self.previous_id,
            "action_sha256": canonical_hash(self.previous),
            "output_tree_sha256": _path_binding(self.old_output)["sha256"],
        }
        self.args.update(
            output_dir=ns.capture_root / "continuation",
            expected_head=inspect_workflow(f.run)["head_sha256"],
        )
        self.ns = ns

    def continue_recovery(self):
        return review_recovery.continue_pre_dispatch_review_recovery(
            self.binding, **self.args
        )

    def assert_pre_dispatch_rejected(self, error="pre-dispatch"):
        before = inspect_workflow(self.fixture.run)["head_sha256"]
        calls = self.fixture.model.call_count
        with self.assertRaisesRegex(Stage2Error, error):
            self.continue_recovery()
        self.transport.assert_not_called()
        self.assertEqual(self.fixture.model.call_count, calls)
        self.assertEqual(inspect_workflow(self.fixture.run)["head_sha256"], before)

    def test_real_preparation_continues_once_and_replays_without_dispatch(self):
        self.prepare_predecessor()
        f = self.fixture
        payload = {
            "assessment": {
                k: v
                for k, v in f.value["review"]["assessment"].items()
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
            "assumptions": ["retained assumption"],
            "strongest_alternative": "retained alternative",
            "change_conditions": ["retained condition"],
        }

        def process(command, **kwargs):
            self.assertEqual(kwargs["cwd"], str(self.ns.work))
            self.assertEqual(kwargs["env"]["CODEX_HOME"], str(self.ns.home))
            Path(command[command.index("-o") + 1]).write_text(
                json.dumps(payload), encoding="utf-8"
            )
            return SimpleNamespace(
                returncode=0,
                stderr=b"",
                stdout=(
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {
                                "type": "agent_message",
                                "text": json.dumps(payload),
                            },
                        }
                    )
                    + '\n{"type":"turn.completed"}\n'
                ).encode(),
            )

        self.transport.side_effect = process
        with patch.object(
            review_recovery, "extract_review", review_models.extract_review
        ):
            result = self.continue_recovery()
            self.assertEqual(self.transport.call_count, 1)
            self.args["expected_head"] = result["head_sha256"]
            again = self.continue_recovery()
            self.assertTrue(again["replayed"])
            self.assertEqual(self.transport.call_count, 1)
        self.assertEqual(result["schema_version"], "1.1.0")
        self.assertEqual(result["requested_native_calls"], 0)
        self.assertFalse(result["scientific_truth_attested"])
        state = inspect_workflow(f.run)
        self.assertEqual(state["actions"][self.previous_id], self.previous)
        self.assertEqual(state["actions"][f.action_id], f.original)
        self.assertEqual(
            _path_binding(self.old_output)["sha256"], self.binding["output_tree_sha256"]
        )

    def test_valid_path_with_missing_attempts_is_ambiguous_and_rejected(self):
        self.prepare_predecessor()
        # Even a fully rehashed request/journal cannot turn absence into proof.
        previous = copy.deepcopy(self.previous)
        config = previous["request"]["settings"]["execution"]["model_call_config"]
        config["native_namespace"]["scope"]["capture_root"] = str(self.fixture.root)
        self.binding["action_sha256"] = canonical_hash(previous)
        with patch.object(review_recovery, "inspect_workflow") as inspect:
            state = inspect_workflow(self.fixture.run)
            state["actions"][self.previous_id] = previous
            inspect.return_value = state
            self.assert_pre_dispatch_rejected("rejection-not-established")

    def test_preparation_tampering_rejected_even_with_updated_tree_digest(self):
        for name in (
            "prompt.txt",
            "schema.json",
            "generation-schema.json",
            "native-namespace.json",
            "request.json",
        ):
            with self.subTest(name=name):
                if not hasattr(self, "binding"):
                    self.prepare_predecessor()
                path = self.old_output / "extraction/initial-review.model-call" / name
                original = path.read_bytes()
                path.write_bytes(original + b" ")
                self.binding["output_tree_sha256"] = _path_binding(self.old_output)[
                    "sha256"
                ]
                # JSON whitespace alone need not change semantic request; byte
                # equality is required for every independently retained file.
                if name == "request.json":
                    value = json.loads(original)
                    value["request_fingerprint_sha256"] = "f" * 64
                    path.write_text(json.dumps(value), encoding="utf-8")
                    self.binding["output_tree_sha256"] = _path_binding(self.old_output)[
                        "sha256"
                    ]
                self.assert_pre_dispatch_rejected()
                path.write_bytes(original)

    def test_attempt_or_result_file_rejected_even_with_updated_tree_digest(self):
        self.prepare_predecessor()
        extra = self.old_output / "extraction/initial-review.model-call/attempt-1.json"
        extra.write_text("{}", encoding="utf-8")
        self.binding["output_tree_sha256"] = _path_binding(self.old_output)["sha256"]
        self.assert_pre_dispatch_rejected("attempt-or-extra-evidence")

    def test_capture_binding_tamper_rejected_even_with_updated_tree_digest(self):
        self.prepare_predecessor()
        path = self.old_output / "extraction/capture-binding.json"
        value = json.loads(path.read_bytes())
        value["raw_sha256"] = "f" * 64
        path.write_text(json.dumps(value), encoding="utf-8")
        self.binding["output_tree_sha256"] = _path_binding(self.old_output)["sha256"]
        self.assert_pre_dispatch_rejected("capture-binding-mismatch")

    def test_stale_predecessor_receipt_rejected(self):
        self.prepare_predecessor()
        self.binding["action_sha256"] = "f" * 64
        self.assert_pre_dispatch_rejected("predecessor-mismatch")

    def test_predecessor_change_during_extraction_cannot_complete(self):
        self.prepare_predecessor()
        f = self.fixture
        original = f.model.side_effect

        def changed(*args, **kwargs):
            value = original(*args, **kwargs)
            (
                self.old_output / "extraction/initial-review.model-call/prompt.txt"
            ).write_bytes(b"changed")
            return value

        f.model.side_effect = changed
        with self.assertRaisesRegex(Stage2Error, "tree-mismatch"):
            self.continue_recovery()
        state = inspect_workflow(f.run)
        self.assertEqual(state["actions"][self.previous_id], self.previous)
        self.assertEqual(state["actions"][f.action_id], f.original)
        new = next(
            k for k in state["actions"] if k.startswith("review-recovery-pre-dispatch-")
        )
        self.assertEqual(state["actions"][new]["result"]["status"], "failed")

    def test_predecessor_output_collision_rejected_before_dispatch(self):
        self.prepare_predecessor()
        # Use a namespace with both roots so the early guard permits the old
        # path but the independently recorded predecessor guard still rejects.
        f = self.fixture
        f.config["native_namespace"]["scope"]["capture_root"] = str(f.root)
        self.args["output_dir"] = self.old_output
        with patch.object(review_recovery, "_request_config", return_value=f.config):
            # The supplied current config still needs the proven workspace.
            f.config["effective_cwd"] = str(self.ns.work)
            self.assert_pre_dispatch_rejected("output-collision")

    def test_failed_continuation_cannot_retry_or_chain(self):
        self.prepare_predecessor()
        self.fixture.model.side_effect = RuntimeError("retained extraction failure")
        with self.assertRaisesRegex(RuntimeError, "retained extraction failure"):
            self.continue_recovery()
        self.args["expected_head"] = inspect_workflow(self.fixture.run)["head_sha256"]
        with self.assertRaises(Stage2Error):
            self.continue_recovery()
        self.assertEqual(self.fixture.model.call_count, 1)
        state = inspect_workflow(self.fixture.run)
        new = next(
            k for k in state["actions"] if k.startswith("review-recovery-pre-dispatch-")
        )
        self.binding.update(
            action_id=new, action_sha256=canonical_hash(state["actions"][new])
        )
        self.assert_pre_dispatch_rejected("predecessor-mismatch")


if __name__ == "__main__":
    unittest.main()
