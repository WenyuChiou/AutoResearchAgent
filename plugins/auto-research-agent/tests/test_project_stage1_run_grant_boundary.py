"""Durable expiry/cancellation with real intake SQLite and no external work."""

from contextlib import closing
import sqlite3
import unittest

from research_workspace_native.project_intake import MAX_ACTIONS, ProjectIntakeService
from research_workspace_native.project_stage1_run_grant import (
    ProjectStage1RunGrantService,
)
from research_workspace_native.project_stage1_run_lease import RunLease
from research_workspace_native.session_api import SessionApiError
import test_project_stage1_run_grant as grant_fixture
from test_workspace_project_intake import authenticate, bound_body


class RunGrantBoundaryTests(unittest.TestCase):
    setUp = grant_fixture.RunGrantTests.setUp
    body = grant_fixture.RunGrantTests.body
    authorize = grant_fixture.RunGrantTests.authorize
    inspect = grant_fixture.RunGrantTests.inspect
    derive = grant_fixture.RunGrantTests.derive

    def reopen(self):
        self.intake.close()
        self.intake = ProjectIntakeService(self.root, authenticate=authenticate)
        self.service = ProjectStage1RunGrantService(
            self.intake, runtime_sha256="a" * 64, clock=lambda: self.now
        )

    def test_in_interval_clock_regression_is_terminal_after_true_reopen(self):
        grant = self.authorize()
        self.now = 1050
        self.inspect(grant)
        self.reopen()
        self.now = 1001
        with self.assertRaises(SessionApiError):
            self.inspect(grant)
        self.reopen()
        self.now = 1051
        with self.assertRaises(SessionApiError):
            self.derive(grant)

    def test_expiry_is_terminal_after_rollback_and_true_reopen(self):
        grant = self.authorize()
        self.now = 1100
        self.intake.db.execute("BEGIN IMMEDIATE")
        try:
            with self.assertRaises(SessionApiError):
                self.inspect(grant)
        finally:
            self.intake.db.rollback()
        self.reopen()
        for now in (1001, 1099):
            self.now = now
            with self.subTest(now=now), self.assertRaises(SessionApiError):
                self.derive(grant)

    def test_high_water_survives_enclosing_intake_rollback(self):
        grant = self.authorize()
        self.now = 1050
        self.intake.db.execute("BEGIN IMMEDIATE")
        self.inspect(grant)
        self.intake.db.rollback()
        self.reopen()
        self.now = 1001
        with self.assertRaises(SessionApiError):
            self.inspect(grant)

    def test_authenticated_revoke_at_full_action_cap_survives_reopen(self):
        grant = self.authorize()
        token = self.derive(grant)
        count = self.intake.db.execute(
            "SELECT COUNT(*) FROM intake_actions"
        ).fetchone()[0]
        for index in range(MAX_ACTIONS - count):
            body = bound_body(
                self.intake.read("alice-token", self.ref), f"fill-{index}"
            )
            self.intake._perform("alice", self.ref, "test-no-work", body, lambda *_: {})
        token.check(self.intake, "alice", self.ref, "query", "b" * 64)
        request = {
            **bound_body(self.intake.read("alice-token", self.ref), "cancel-full"),
            "grant_ref": grant["grant_ref"],
            "grant_sha256": grant["grant_sha256"],
        }
        with self.assertRaises(SessionApiError):
            self.service.revoke("bob-token", self.ref, request)
        token.check(self.intake, "alice", self.ref, "query", "b" * 64)
        result = self.service.revoke("alice-token", self.ref, request)
        self.assertTrue(result["future_dispatch_revoked"])
        self.assertFalse(result["resources_refunded"])
        self.assertFalse(result["process_cleanup_attested"])
        self.assertEqual(
            self.intake.db.execute("SELECT COUNT(*) FROM intake_actions").fetchone()[0],
            MAX_ACTIONS,
        )
        with self.assertRaises(SessionApiError):
            token.check(self.intake, "alice", self.ref, "query", "b" * 64)
        self.reopen()
        with self.assertRaises(SessionApiError):
            self.inspect(grant)
        repeated = self.service.revoke("alice-token", self.ref, request)
        self.assertTrue(repeated["replayed"])
        self.assertEqual(repeated["request_sha256"], result["request_sha256"])
        with self.assertRaises(SessionApiError):
            self.service.revoke(
                "alice-token", self.ref, {**request, "brief_sha256": "f" * 64}
            )

    def test_missing_protection_is_not_recreated(self):
        grant = self.authorize()
        document = self.inspect(grant)
        path = RunLease(self.intake, self.ref, document, grant["grant_sha256"]).path
        path.unlink()
        self.reopen()
        with self.assertRaises(SessionApiError):
            self.derive(grant)
        self.assertFalse(path.exists())

    def test_corrupt_and_rebound_protection_fail_closed(self):
        grant = self.authorize()
        document = self.inspect(grant)
        path = RunLease(self.intake, self.ref, document, grant["grant_sha256"]).path
        with closing(sqlite3.connect(path)) as db:
            db.execute("UPDATE lease SET body='{}'")
            db.commit()
        with self.assertRaises(SessionApiError):
            self.inspect(grant)
        path.write_bytes(b"corrupt protection")
        self.reopen()
        with self.assertRaises(SessionApiError):
            self.derive(grant)
        self.assertEqual(path.read_bytes(), b"corrupt protection")


if __name__ == "__main__":
    unittest.main()
