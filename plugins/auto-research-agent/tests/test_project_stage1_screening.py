"""Explicit screening writes with real ledger/history; no search or model."""

from copy import deepcopy
import unittest
from research_workspace_native.session_api import SessionApiError
from stage1_ledger.validation import validate_run
from test_project_stage1_library import Stage1LibraryFixture


class ScreeningTests(Stage1LibraryFixture, unittest.TestCase):
    def body(self, key="screen", decision="pending"):
        project = self.intake.read(self.token, self.ref)
        return dict(
            key=key,
            revision=project["revision"],
            input_version=project["input_version"],
            brief_sha256=project["brief_sha256"],
            ledger_state_sha256=self.ledger.state_hash(),
            work_ref=self.work_by_name["unscreened"],
            decision=decision,
            rationale="Synthetic user: retain for source review, no verified scientific support.",
            confirmed=True,
        )

    def test_saved_selection_replay_reversal_and_history(self):
        body = self.body()
        before = len(self.ledger.events())
        first = self.stage1.screen(self.token, self.ref, body)
        self.assertEqual(len(self.ledger.events()), before + 1)
        repeated = self.stage1.screen(self.token, self.ref, body)
        self.assertEqual(first["decision_event_id"], repeated["decision_event_id"])
        self.assertEqual(len(self.ledger.events()), before + 1)
        second = self.stage1.screen(
            self.token, self.ref, self.body("reverse", "exclude")
        )
        row = self.ledger.event(second["decision_event_id"])
        self.assertEqual(row["reverses_event_id"], first["decision_event_id"])
        self.assertEqual(row["actor_type"], "human")
        self.assertFalse(second["scientific_acceptance"])
        self.assertTrue(validate_run(self.ledger.root)["valid"])
        self.runner.assert_not_called()

    def test_changed_key_payload_and_stale_ledger_refuse(self):
        body = self.body()
        self.stage1.screen(self.token, self.ref, body)
        before = self.ledger.state_hash()
        changed = deepcopy(body)
        changed["decision"] = "include"
        with self.assertRaises(SessionApiError):
            self.stage1.screen(self.token, self.ref, changed)
        stale = self.body("stale")
        stale["ledger_state_sha256"] = body["ledger_state_sha256"]
        with self.assertRaises(SessionApiError):
            self.stage1.screen(self.token, self.ref, stale)
        self.assertEqual(self.ledger.state_hash(), before)

    def test_invalid_choice_and_foreign_work_refuse_before_append(self):
        before = self.ledger.state_hash()
        for changes in (
            {"decision": "passed"},
            {"work_ref": "work-other"},
            {"rationale": ""},
            {"owner": "caller-owner"},
        ):
            body = self.body("refuse-" + next(iter(changes)))
            body.update(changes)
            with self.assertRaises((SessionApiError, ValueError)):
                self.stage1.screen(self.token, self.ref, body)
        self.assertEqual(self.ledger.state_hash(), before)
        self.runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
