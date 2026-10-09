"""Source/storage rejection preserves existing projects and unobserved intents."""

from copy import deepcopy
import json
import sqlite3
import unittest
from unittest.mock import patch

import test_workspace_stage_actions as fixture_module
from research_workspace_native import stage_actions as mod
from research_workspace_native.session_api import SessionApiError


class StageStorageTests(unittest.TestCase):
    setUp = fixture_module.StageActionTests.setUp
    stage1 = fixture_module.StageActionTests.stage1
    registrations = fixture_module.StageActionTests.registrations
    start = fixture_module.StageActionTests.start
    body = fixture_module.StageActionTests.body
    execute = fixture_module.StageActionTests.execute

    def test_db_and_other_project_output_never_enter_source_root(self):
        ledger = self.stage1()
        before = mod.source_digest(mod.snapshot_inputs(self.inputs))
        with self.assertRaises(SessionApiError):
            mod.StageActions(
                ledger.root / "forbidden.sqlite3",
                registrations=self.registrations(),
                authenticate=lambda _: "principal-a",
            )
        registrations = self.registrations(extra=True)
        registrations["case"]["inputs"] = {1: None, 2: None}
        registrations["case"]["source_sha256"] = mod.source_digest({})
        registrations["case"]["output_root"] = str(ledger.root / "cross-project-output")
        with self.assertRaises(SessionApiError):
            self.start(registrations)
        self.assertFalse(self.db.exists())
        self.assertEqual(mod.source_digest(mod.snapshot_inputs(self.inputs)), before)

    def test_all_prior_bindings_are_checked_before_any_owner_or_intent_change(self):
        registrations = self.registrations(extra=True)
        self.start(registrations)
        body = self.body(1, "checkpoint-stage1", "pending-start")
        with patch.object(mod.StageActions, "_produce", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.execute(body)
        before = list(
            self.service.store.db.execute("SELECT id,state FROM projects ORDER BY id")
        )
        events = list(
            self.service.store.db.execute(
                "SELECT * FROM events ORDER BY project,revision"
            )
        )
        self.service.close()
        changed = deepcopy(registrations)
        changed["other"]["output_root"] = str(self.root / "different")
        with self.assertRaises(SessionApiError):
            self.start(changed)
        connection = sqlite3.connect(self.db)
        try:
            self.assertEqual(
                [tuple(row) for row in before],
                connection.execute(
                    "SELECT id,state FROM projects ORDER BY id"
                ).fetchall(),
            )
            self.assertEqual(
                [tuple(row) for row in events],
                connection.execute(
                    "SELECT * FROM events ORDER BY project,revision"
                ).fetchall(),
            )
            row = json.loads(
                connection.execute(
                    "SELECT state FROM projects WHERE id=?",
                    ("stage-actions-" + mod.sha(b"case")[:32],),
                ).fetchone()[0]
            )
            self.assertEqual(next(iter(row["intents"].values()))["status"], "running")
        finally:
            connection.close()
        self.assertFalse((self.root / "different").exists())


if __name__ == "__main__":
    unittest.main()
