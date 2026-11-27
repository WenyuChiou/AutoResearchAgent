"""Re-registering an existing connection with a NEW key is idempotent.

This is the call the page's "reconnect" action makes after a Host restart: the
saved connection record is returned unchanged and nothing new is written.
"""

# ruff: noqa: E402 -- exercise repository package and authored fixtures.
from pathlib import Path
import sys
import unittest

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / "cli"),
    str(Path(__file__).resolve().parent),
]
from project_stage2_selection_fixture import Stage2SelectionFixture
from research_workspace_native.project_stage_connections import ConnectionStore
from research_workspace_native.session_api import SessionApiError

ROW = {"authored_storage_probe": 1}


def counts(intake):
    return tuple(
        intake.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("intake_actions", "intake_events")
    )


class ReconnectWithNewKeyTests(Stage2SelectionFixture):
    def test_new_key_returns_the_saved_connection_and_writes_nothing(self):
        store = ConnectionStore(self.intake, "own")
        first = store.record(self.ref, "stage2-input", ROW, derived_from={})
        before = counts(self.intake)
        revision = self.intake.read("own", self.ref)["revision"]
        again = store.record(
            self.ref,
            "stage2-input",
            ROW,
            derived_from={},
            expected_revision=revision,
            request_key="reconnect-with-a-new-key",
        )
        self.assertEqual(again["connection_id"], first["connection_id"])
        self.assertEqual(again["receipt_id"], first["receipt_id"])
        self.assertEqual(counts(self.intake), before)
        self.assertEqual(self.intake.read("own", self.ref)["revision"], revision)

    def test_a_key_already_used_by_another_action_is_refused(self):
        store = ConnectionStore(self.intake, "own")
        store.record(self.ref, "stage2-input", ROW, derived_from={})
        used = self.intake.db.execute(
            "SELECT key FROM intake_actions WHERE project=? LIMIT 1", (self.ref,)
        ).fetchone()[0]
        before = counts(self.intake)
        with self.assertRaisesRegex(SessionApiError, "idempotency-payload-differs"):
            store.record(
                self.ref,
                "stage2-input",
                ROW,
                derived_from={},
                request_key=used,
            )
        self.assertEqual(counts(self.intake), before)


if __name__ == "__main__":
    unittest.main()
