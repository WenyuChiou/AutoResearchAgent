"""Real offline workflow events and durable project frontier acknowledgments.

Canonical import, workflow producers and SQLite run normally. No native process,
model, search, scoring, or implicit workflow action is executed by the adapter.
"""

# ruff: noqa: E402 -- reuse the repository's authored canonical Stage1 fixture.
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / "cli"),
    str(Path(__file__).resolve().parent),
]

import test_project_stage2 as fixture
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage2 import ProjectStage2Service
from research_workspace_native.session_api import SessionApiError
from stage1_ledger.journal import LedgerError, canonical
from stage2_common import Stage2Error
from stage2_workflow import finish_action, inspect_workflow, start_action


class ProjectStage2FrontierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.ProjectStage2Tests.setUpClass.__func__(cls)

    setUp = fixture.ProjectStage2Tests.setUp
    body = fixture.ProjectStage2Tests.body

    def activate(self):
        self.activation = self.service.activate("own", self.ref, self.body())
        self.initial = self.service.binding(self.ref)
        self.workflow = self.initial["workflow_root"]
        return self.initial

    def append_start(self, action_id="offline-check"):
        state = inspect_workflow(self.workflow)
        return start_action(
            self.workflow,
            action_id,
            "offline-record-only",
            {"purpose": "Retain an offline observation without execution"},
            {"execution_authorized": False},
            state["head_sha256"],
        )["event"]["event_sha256"]

    def advance(
        self,
        head,
        *,
        previous=None,
        key="frontier-1",
        activation=None,
        check_deadline=None,
    ):
        return self.service.advance_frontier(
            self.ref,
            key=key,
            expected_activation_sha256=activation or self.initial["activation_sha256"],
            expected_previous_head_sha256=previous
            or self.initial["workflow_head_sha256"],
            new_workflow_head_sha256=head,
            check_deadline=check_deadline,
        )

    def reopen(self):
        self.intake.close()
        self.intake = ProjectIntakeService(
            self.store_root, authenticate=self.authenticate
        )
        self.service = ProjectStage2Service(self.intake)

    def edit_state(self, change):
        state = self.intake._load("researcher", self.ref)
        change(state)
        with self.intake.db:
            self.intake.db.execute(
                "UPDATE intake_projects SET state=? WHERE ref=?",
                (canonical(state).decode(), self.ref),
            )

    def test_real_events_advance_cas_frontier_and_survive_sqlite_reopen(self):
        self.activate()
        original = self.service.read("own", self.ref)["activation"]
        self.assertEqual(self.initial["frontier_sequence"], 0)
        started = self.append_start()
        with self.assertRaisesRegex(Stage2Error, "workflow-head-receipt-mismatch"):
            self.service.binding(self.ref)
        workflow_before = inspect_workflow(self.workflow)
        popen = subprocess.Popen

        def validation_probe_only(command, *args, **kwargs):
            # The real canonical checker checks its private directory with this
            # read-only Git probe. No model/native process is permitted.
            self.assertEqual(command[:2], ["git", "-C"])
            self.assertEqual(command[3:], ["rev-parse", "--show-toplevel"])
            return popen(command, *args, **kwargs)

        with patch("subprocess.Popen", side_effect=validation_probe_only):
            first = self.advance(started)
        self.assertEqual(inspect_workflow(self.workflow), workflow_before)
        self.assertEqual(first["frontier"]["sequence"], 1)
        self.assertEqual(
            self.service.binding(self.ref)["workflow_head_sha256"], started
        )
        finished = finish_action(
            self.workflow,
            "offline-check",
            "failed",
            {},
            None,
            "Offline observation intentionally has no execution result.",
            started,
        )["event_sha256"]
        self.advance(finished, previous=started, key="frontier-2")
        self.reopen()
        binding = self.service.binding(self.ref)
        self.assertEqual(binding["workflow_head_sha256"], finished)
        self.assertEqual(
            binding["initial_workflow_head_sha256"], original["workflow_head_sha256"]
        )
        self.assertEqual(binding["frontier_sequence"], 2)
        public = self.service.read("own", self.ref)
        self.assertEqual(public["activation"], original)
        self.assertEqual(public["frontier"]["workflow_head_sha256"], finished)
        self.assertFalse(public["execution_authorized"])
        self.assertFalse(public["stage2_complete"])
        self.assertEqual(public["daily_v3"], "not-started")
        history = self.service.history("own", self.ref)["actions"]
        self.assertEqual([row["kind"] for row in history[-2:]], ["stage2-frontier"] * 2)

    def test_same_key_replay_never_inspects_or_advances_workflow_again(self):
        self.activate()
        head = self.append_start()
        saved = self.advance(head)
        self.reopen()
        before = self.service.history("own", self.ref)
        workflow_before = inspect_workflow(self.workflow)
        with patch(
            "research_workspace_native.project_stage2.inspect_workflow"
        ) as inspect:
            replay = self.advance(head)
        inspect.assert_not_called()
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["frontier"], saved["frontier"])
        self.assertEqual(self.service.history("own", self.ref), before)
        self.assertEqual(inspect_workflow(self.workflow), workflow_before)
        with self.assertRaisesRegex(SessionApiError, "idempotency-payload-differs"):
            self.advance("f" * 64)

    def interrupted_completed_frontier(self):
        self.activate()
        head = self.append_start()
        original = self.intake._save

        def fail_commit(state, kind, payload):
            original(state, kind, payload)
            if kind == "stage2-frontier-saved":
                raise OSError("synthetic completed frontier commit failure")

        with patch.object(self.intake, "_save", side_effect=fail_commit):
            with self.assertRaisesRegex(SessionApiError, "intake-operation-failed"):
                self.advance(head)
        self.assertEqual(self.advance(head)["status"], "execution-unknown")
        return head

    def recover(self, head):
        return self.service.recover_frontier(
            self.ref,
            key="frontier-1",
            expected_activation_sha256=self.initial["activation_sha256"],
            expected_previous_head_sha256=self.initial["workflow_head_sha256"],
            new_workflow_head_sha256=head,
        )

    def test_completed_frontier_recovery_is_metadata_only_durable_and_idempotent(self):
        head = self.interrupted_completed_frontier()
        before = inspect_workflow(self.workflow)
        result = self.recover(head)
        self.assertEqual(result["status"], "saved")
        self.assertFalse(result["execution_authorized"])
        self.assertIn("recovered_from_receipt_sha256", result)
        self.assertEqual(inspect_workflow(self.workflow), before)
        self.reopen()
        self.assertEqual(self.service.binding(self.ref)["workflow_head_sha256"], head)
        self.assertEqual(self.recover(head)["frontier"], result["frontier"])
        failures = self.service._journal(self.ref, "stage2-frontier-failed")
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["status"], "execution-unknown")

    def test_completed_frontier_recovery_rejects_changed_request_and_observation(self):
        head = self.interrupted_completed_frontier()
        with self.assertRaisesRegex(SessionApiError, "recovery-request-differs"):
            self.recover("f" * 64)
        row = self.intake.db.execute(
            "SELECT receipt FROM intake_actions WHERE project=? AND key='frontier-1'",
            (self.ref,),
        ).fetchone()
        value = json.loads(row[0])
        value["output_observation"]["frontier"]["sequence"] += 1
        with self.intake.db:
            self.intake.db.execute(
                "UPDATE intake_actions SET receipt=? WHERE project=? AND key='frontier-1'",
                (canonical(value).decode(), self.ref),
            )
        with self.assertRaisesRegex(
            SessionApiError, "recovery-failure-receipt-differs"
        ):
            self.recover(head)
        self.assertEqual(
            self.intake._load("researcher", self.ref)["stage2_frontier"]["sequence"], 0
        )

    def assert_failure_receipt_edit_is_rejected(self, field, altered):
        head = self.interrupted_completed_frontier()
        before = inspect_workflow(self.workflow)
        failures = self.service._journal(self.ref, "stage2-frontier-failed")
        row = self.intake.db.execute(
            "SELECT receipt FROM intake_actions WHERE project=? AND key='frontier-1'",
            (self.ref,),
        ).fetchone()
        value = json.loads(row[0])
        value[field] = altered
        with self.intake.db:
            self.intake.db.execute(
                "UPDATE intake_actions SET receipt=? WHERE project=? AND key='frontier-1'",
                (canonical(value).decode(), self.ref),
            )
        with self.assertRaises(SessionApiError):
            self.recover(head)
        self.assertEqual(inspect_workflow(self.workflow), before)
        self.assertEqual(
            self.service._journal(self.ref, "stage2-frontier-failed"), failures
        )
        self.assertEqual(self.service._journal(self.ref, "stage2-frontier-saved"), [])
        self.assertEqual(
            self.intake._load("researcher", self.ref)["stage2_frontier"]["sequence"], 0
        )

    def test_completed_recovery_rejects_action_row_only_project_tampering(self):
        self.assert_failure_receipt_edit_is_rejected("project_ref", "project-foreign")

    def test_completed_recovery_rejects_action_row_only_key_tampering(self):
        self.assert_failure_receipt_edit_is_rejected("key", "frontier-forged")

    def test_completed_recovery_rejects_action_row_only_digest_tampering(self):
        self.assert_failure_receipt_edit_is_rejected("request_sha256", "f" * 64)

    def test_completed_recovery_deadline_after_sql_writes_rolls_back(self):
        head = self.interrupted_completed_frontier()
        before = inspect_workflow(self.workflow)
        row = self.intake.db.execute(
            "SELECT receipt FROM intake_actions WHERE project=? AND key='frontier-1'",
            (self.ref,),
        ).fetchone()
        original = row[0]
        checks = 0

        def deadline():
            nonlocal checks
            checks += 1
            if checks == 3:
                raise TimeoutError("synthetic deadline after SQL writes")

        with self.assertRaisesRegex(TimeoutError, "after SQL writes"):
            self.service.recover_frontier(
                self.ref,
                key="frontier-1",
                expected_activation_sha256=self.initial["activation_sha256"],
                expected_previous_head_sha256=self.initial["workflow_head_sha256"],
                new_workflow_head_sha256=head,
                check_deadline=deadline,
            )
        self.assertEqual(checks, 3)
        self.assertEqual(
            self.intake.db.execute(
                "SELECT receipt FROM intake_actions WHERE project=? AND key='frontier-1'",
                (self.ref,),
            ).fetchone()[0],
            original,
        )
        self.assertEqual(self.service._journal(self.ref, "stage2-frontier-saved"), [])
        self.assertEqual(inspect_workflow(self.workflow), before)
        self.assertEqual(self.recover(head)["status"], "saved")

    def test_frontier_validation_failure_is_not_promoted_to_completed_recovery(self):
        self.activate()
        with self.assertRaises(SessionApiError):
            self.advance("f" * 64)
        with self.assertRaisesRegex(SessionApiError, "recovery-outcome-unverified"):
            self.recover("f" * 64)

    def test_stale_cas_wrong_activation_and_noop_preserve_failed_history(self):
        self.activate()
        first = self.append_start()
        self.advance(first)
        second = self.append_start("another-offline-check")
        for key, previous, activation, new_head in (
            ("stale-frontier", self.initial["workflow_head_sha256"], None, second),
            ("wrong-activation", first, "f" * 64, second),
            ("no-op", first, None, first),
        ):
            with self.subTest(key=key), self.assertRaises(SessionApiError):
                self.advance(
                    new_head, previous=previous, key=key, activation=activation
                )
        history = self.service.history("own", self.ref)["actions"]
        self.assertEqual([row["status"] for row in history[-3:]], ["failed"] * 3)
        self.assertEqual(
            self.service.read("own", self.ref)["frontier"]["workflow_head_sha256"],
            first,
        )

    def test_unjournaled_head_and_forged_state_frontier_are_rejected(self):
        self.activate()
        head = self.append_start()
        with self.assertRaisesRegex(Stage2Error, "workflow-head-receipt-mismatch"):
            self.service.binding(self.ref)
        self.edit_state(
            lambda state: state["stage2_frontier"].update(
                workflow_head_sha256=head, sequence=1
            )
        )
        self.reopen()
        with self.assertRaisesRegex(SessionApiError, "frontier-state-journal-differs"):
            self.service.binding(self.ref)
        with self.assertRaisesRegex(
            SessionApiError, "intake-operation-failed"
        ) as failure:
            self.advance(head)
        self.assertIn(
            "frontier-state-journal-differs", failure.exception.receipt["error"]
        )

    def test_saved_frontier_removal_and_source_binding_edit_cannot_bypass_journal(self):
        self.activate()
        head = self.append_start()
        self.advance(head)
        saved = self.intake._load("researcher", self.ref)
        self.edit_state(lambda state: state.pop("stage2_frontier"))
        with self.assertRaisesRegex(SessionApiError, "frontier-state-journal-differs"):
            self.service.binding(self.ref)
        self.edit_state(
            lambda state: state.update(stage2_frontier=saved["stage2_frontier"])
        )
        self.edit_state(
            lambda state: state["stage2_offers"][self.offer["offer_ref"]].update(
                stage1_handoff_sha256="f" * 64
            )
        )
        with self.assertRaisesRegex(SessionApiError, "offer-journal-differs"):
            self.service.binding(self.ref)

    def test_activation_receipt_cannot_be_replaced_by_current_head(self):
        self.activate()
        head = self.append_start()
        self.edit_state(
            lambda state: state["stage2_activation"].update(workflow_head_sha256=head)
        )
        with self.assertRaisesRegex(SessionApiError, "activation-journal-differs"):
            self.service.binding(self.ref)

    def test_tampered_workflow_and_wrong_new_head_do_not_advance(self):
        self.activate()
        head = self.append_start()
        with self.assertRaisesRegex(
            SessionApiError, "intake-operation-failed"
        ) as failure:
            self.advance("f" * 64, key="wrong-head")
        self.assertEqual(
            failure.exception.receipt["error"], "stage2-frontier-validation-failed"
        )
        events = sorted((self.workflow / "events").glob("*.json"))[-1]
        event = json.loads(events.read_bytes())
        event["payload"]["request"]["action_kind"] = "tampered-offline-action"
        events.write_bytes(canonical(event) + b"\n")
        with self.assertRaisesRegex(
            SessionApiError, "intake-operation-failed"
        ) as failure:
            self.advance(head, key="tampered-event")
        self.assertEqual(
            failure.exception.receipt["error"], "stage2-frontier-validation-failed"
        )
        self.assertEqual(self.service.read("own", self.ref)["frontier"]["sequence"], 0)

    def test_changed_source_and_project_version_reject_advancement(self):
        self.activate()
        head = self.append_start()
        raw = self.handoff_path.read_bytes()
        self.handoff_path.write_bytes(raw + b" ")
        with self.assertRaisesRegex(
            SessionApiError, "intake-operation-failed"
        ) as failure:
            self.advance(head, key="changed-handoff")
        self.assertIn("input-bytes-differ", failure.exception.receipt["error"])
        self.handoff_path.write_bytes(raw)
        state = self.intake.read("own", self.ref)
        self.intake.revise(
            "own",
            self.ref,
            dict(
                key="change-topic",
                revision=state["revision"],
                input_version=state["input_version"],
                brief_sha256=state["brief_sha256"],
                topic="A revised synthetic topic",
            ),
        )
        with self.assertRaises(LedgerError):
            self.advance(head, key="changed-project")

    def test_interrupted_intent_replays_unknown_without_reconciliation(self):
        self.activate()
        head = self.append_start()
        calls = 0

        def expired_after_validation():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise TimeoutError("Offline frontier commit interrupted")

        with self.assertRaises(SessionApiError) as failure:
            self.advance(head, check_deadline=expired_after_validation)
        self.assertEqual(failure.exception.receipt["status"], "execution-unknown")
        self.reopen()
        with patch(
            "research_workspace_native.project_stage2.inspect_workflow"
        ) as inspect:
            replay = self.advance(head)
        inspect.assert_not_called()
        self.assertEqual(replay["status"], "execution-unknown")
        self.assertTrue(replay["replayed"])
        self.assertEqual(self.service.read("own", self.ref)["frontier"]["sequence"], 0)
        with self.assertRaisesRegex(Stage2Error, "workflow-head-receipt-mismatch"):
            self.service.binding(self.ref)

    def test_opaque_browser_shapes_and_public_history_have_no_physical_paths(self):
        self.activate()
        head = self.append_start()
        self.advance(head)
        with self.assertRaises(SessionApiError):
            self.service.activate(
                "own",
                self.ref,
                dict(
                    self.body("browser-frontier"),
                    new_workflow_head_sha256=head,
                    workflow_root=str(self.workflow),
                ),
            )
        with self.assertRaises(TypeError):
            self.service.advance_frontier(
                self.ref,
                key="path-injection",
                source_root=self.workflow,
                expected_activation_sha256=self.initial["activation_sha256"],
                expected_previous_head_sha256=head,
                new_workflow_head_sha256=head,
            )
        with self.assertRaises(SessionApiError):
            self.service.read("other", self.ref)
        manifest = self.workflow / "workflow_manifest.json"
        raw = manifest.read_bytes()
        manifest.unlink()
        try:
            with self.assertRaisesRegex(
                SessionApiError, "intake-operation-failed"
            ) as failure:
                self.advance("f" * 64, previous=head, key="missing-workflow")
            self.assertEqual(
                failure.exception.receipt["error"], "stage2-frontier-validation-failed"
            )
        finally:
            manifest.write_bytes(raw)
        self.assertNotIn(str(self.root), json.dumps(self.service.read("own", self.ref)))
        self.assertNotIn(
            str(self.root), json.dumps(self.service.history("own", self.ref))
        )


if __name__ == "__main__":
    unittest.main()
