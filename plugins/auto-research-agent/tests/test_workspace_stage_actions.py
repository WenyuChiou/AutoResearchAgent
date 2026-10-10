"""Existing repository producers over saved cases, never model/native calls."""

import atlas_test_paths  # noqa: F401 -- standalone discovery needs the local CLI.

from copy import deepcopy
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from research_workspace_native import stage_actions as mod
from research_workspace_native import stage_inputs as inputs_mod
from research_workspace_native.session_api import SessionApiError
from stage1_ledger.store import Ledger
from test_stage1_ledger import fixture
import test_stage2_completion as completion_fixture


class StageActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.db = self.root / "stage-actions.sqlite3"
        self.inputs = {1: None, 2: None}
        self.service = None

    def stage1(self):
        ledger, _, _, _ = fixture(self.root / "ledger")
        self.inputs[1] = dict(ledger_root=str(ledger.root))
        return ledger

    def stage2(self, *, evaluated=False):
        case = completion_fixture.Stage2CompletionTests("runTest")
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.deliver()
        evaluation = case.evaluated() if evaluated else None
        self.inputs[2] = dict(
            delivery_root=str(case.delivery),
            delivery_manifest_sha256=case.manifest["manifest_sha256"],
            evaluation_root=str(case.root / "completion-evaluation")
            if evaluation
            else None,
            evaluation_manifest_sha256=evaluation["manifest_sha256"]
            if evaluation
            else None,
        )
        return case

    def registrations(self, *, extra=False):
        item = dict(
            project_id="case-a",
            index_sha256="a" * 64,
            input_version="b" * 64,
            source_sha256=mod.source_digest(mod.snapshot_inputs(self.inputs)),
            inputs=self.inputs,
            output_root=str(self.root / "outputs"),
            principals={"principal-a"},
        )
        items = {"case": item}
        if extra:
            other = deepcopy(item)
            other.update(
                project_id="case-b",
                output_root=str(self.root / "other"),
                principals={"principal-b"},
            )
            items["other"] = other
        return items

    def start(self, registrations=None):
        self.service = mod.StageActions(
            self.db,
            registrations=registrations or self.registrations(),
            authenticate=lambda token: {"a": "principal-a", "b": "principal-b"}.get(
                token
            ),
        )
        self.addCleanup(self.service.close)
        return self.service

    def body(self, stage, action, key, *, decision=None, note="", confirmed=False):
        offer = self.service.offer("a", "case", stage, action)
        return dict(
            stage=stage,
            action=action,
            key=key,
            revision=offer["revision"],
            index_sha256="a" * 64,
            input_version="b" * 64,
            offer_ref=offer["offer_ref"],
            offer_sha256=offer["offer_sha256"],
            decision=decision,
            note=note,
            confirmed=confirmed,
        )

    def execute(self, body):
        return self.service.execute("a", "case", body, deadline=time.monotonic() + 30)

    def test_stage1_real_checkpoint_validates_copy_and_retains_original(self):
        ledger = self.stage1()
        original = mod.source_digest(mod.snapshot_inputs(self.inputs))
        self.start()
        body = self.body(1, "checkpoint-stage1", "stage1-check")
        checkpoint = Ledger.checkpoint

        def checked(instance):
            self.assertEqual(
                self.service.view("a", "case")["history"][0]["status"], "running"
            )
            self.assertNotEqual(instance.root, ledger.root)
            return checkpoint(instance)

        with patch.object(
            Ledger, "checkpoint", autospec=True, side_effect=checked
        ) as calls:
            result = self.execute(body)
            replay = self.execute(dict(body, revision=999))
            self.assertEqual(result, replay)
            self.assertEqual(calls.call_count, 1)
        self.assertEqual(result["outcome"], "succeeded")
        self.assertTrue(result["result"]["ledger_valid"])
        self.assertEqual(
            result["result"]["handoff"]["stage2"],
            dict(status="not-started", execution_authorized=False),
        )
        self.assertFalse(result["result"]["handoff"]["eligible_for_stage2"])
        self.assertEqual(mod.source_digest(mod.snapshot_inputs(self.inputs)), original)
        self.assertIn(
            "closest-work-unverified", result["result"]["readiness"]["blockers"]
        )

    def test_stage2_real_completion_missing_assessment_and_completed_retained(self):
        case = self.stage2()
        self.start()
        with patch.object(
            inputs_mod, "inspect_completion", wraps=inputs_mod.inspect_completion
        ) as inspect:
            row = self.execute(self.body(2, "inspect-stage2", "stage2-check"))
            self.assertEqual(inspect.call_count, 1)
        self.assertEqual(row["outcome"], "succeeded")
        result = row["result"]["completion"]
        self.assertTrue(result["research_delivery_ready"])
        self.assertEqual(result["assessment_status"], "missing")
        self.assertIsNone(result["assessment_dimensions"])
        self.assertFalse(result["stage2_complete"])
        self.assertFalse(result["stage3_execution_authorized"])
        self.assertEqual(case.inspect(), result)

    def test_stage2_assessed_case_readiness_stays_separate_from_ui_request(self):
        self.stage2(evaluated=True)
        self.start()
        check = self.execute(self.body(2, "inspect-stage2", "check"))
        self.assertEqual(check["outcome"], "succeeded")
        self.assertTrue(check["result"]["completion"]["stage2_complete"])
        review = self.execute(
            self.body(
                2,
                "review-stage",
                "choice",
                decision="request-next",
                note="Review this retained candidate package.",
                confirmed=True,
            )
        )["result"]
        self.assertEqual(review["kind"], "WorkspaceStageReviewRecord")
        self.assertEqual(
            review["next_stage_request"], "recorded-awaiting-execution-authority"
        )
        self.assertFalse(review["native_user_message_attested"])
        self.assertFalse(review["execution_authorized"])
        self.assertEqual(review["check_action_ref"], check["key"])

    def test_missing_inputs_and_explicit_hold_persist_without_claiming_success(self):
        self.start()
        row = self.execute(self.body(1, "checkpoint-stage1", "missing"))
        self.assertEqual(row["result"]["readiness"]["status"], "missing")
        review = self.execute(
            self.body(
                1,
                "review-stage",
                "hold",
                decision="hold",
                note="Need the actual ledger.",
                confirmed=True,
            )
        )
        self.assertEqual(review["result"]["next_stage_request"], "not-requested")
        self.assertFalse(review["execution_authorized"])
        body = self.body(
            1,
            "review-stage",
            "not-confirmed",
            decision="request-next",
            note="Next",
            confirmed=False,
        )
        count = self.service.view("a", "case")["history_count"]
        with self.assertRaises(SessionApiError):
            self.execute(body)
        self.assertEqual(self.service.view("a", "case")["history_count"], count)

    def test_failure_history_no_reexecution_reopen_and_latest_failure_blocks(self):
        self.stage2(evaluated=True)
        registrations = self.registrations()
        self.start(registrations)
        success = self.execute(self.body(2, "inspect-stage2", "first"))
        self.assertEqual(success["outcome"], "succeeded")
        body = self.body(2, "inspect-stage2", "later-failure")
        with patch.object(
            inputs_mod,
            "inspect_completion",
            side_effect=ValueError("synthetic failure"),
        ) as calls:
            failed = self.execute(body)
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(self.execute(body), failed)
            self.assertEqual(calls.call_count, 1)
        review = self.execute(
            self.body(
                2,
                "review-stage",
                "next",
                decision="request-next",
                note="Keep failed check visible.",
                confirmed=True,
            )
        )["result"]
        self.assertEqual(review["readiness"]["status"], "unavailable")
        self.assertEqual(review["next_stage_request"], "blocked")
        self.service.close()
        self.start(registrations)
        with patch.object(
            inputs_mod,
            "inspect_completion",
            side_effect=AssertionError("must not execute"),
        ):
            self.assertEqual(self.execute(body), failed)
            self.assertEqual(self.service.get_action("a", "case", body["key"]), failed)
        self.assertEqual(self.service.view("a", "case")["history_count"], 3)
        history = self.service.view("a", "case")["history"]
        self.assertNotIn("result", history[0])
        self.assertEqual(history[0]["result_summary"]["readiness_status"], "ready")

    def test_owner_loss_unknown_intent_replay_never_calls_checkpoint(self):
        self.stage1()
        registrations = self.registrations()
        self.start(registrations)
        body = self.body(1, "checkpoint-stage1", "uncertain")
        with patch.object(mod.StageActions, "_produce", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.execute(body)
        self.service.close()
        self.start(registrations)
        with patch.object(
            Ledger, "checkpoint", side_effect=AssertionError("must not retry")
        ):
            row = self.execute(body)
            self.assertEqual(row["status"], "execution-unknown")
            self.assertEqual(self.service.get_action("a", "case", body["key"]), row)

    def test_project_version_revision_offer_and_source_reject_before_work(self):
        ledger = self.stage1()
        self.start(self.registrations(extra=True))
        body = self.body(1, "checkpoint-stage1", "protected")
        for wrong in (
            dict(body, revision=0),
            dict(body, input_version="c" * 64),
            dict(body, offer_ref="d" * 64),
            dict(body, action="run-model"),
            dict(body, root=str(self.root)),
        ):
            with self.assertRaises(SessionApiError):
                self.execute(wrong)
        with self.assertRaises(SessionApiError):
            self.service.view("a", "other")
        self.assertEqual(self.service.view("b", "other")["history_count"], 0)
        (ledger.root / "run_manifest.json").write_bytes(b"{}")
        with self.assertRaises(SessionApiError):
            self.execute(body)
        self.assertEqual(self.service.view("a", "case")["history_count"], 0)

    def test_deadline_rejection_and_passive_history_leave_intent_count_zero(self):
        self.stage1()
        self.start()
        body = self.body(1, "checkpoint-stage1", "expired")
        with self.assertRaises(SessionApiError):
            self.service.execute("a", "case", body, deadline=time.monotonic() - 1)
        with patch.object(
            mod, "time", SimpleNamespace(monotonic=iter((10, 20)).__next__)
        ):
            with self.assertRaises(SessionApiError):
                self.service.execute("a", "case", body, deadline=15)
        with patch.object(
            Ledger, "checkpoint", side_effect=AssertionError("GET is passive")
        ):
            self.assertEqual(self.service.view("a", "case")["history_count"], 0)
            with self.assertRaises(SessionApiError):
                self.service.get_action("a", "case", "missing")


if __name__ == "__main__":
    unittest.main()
