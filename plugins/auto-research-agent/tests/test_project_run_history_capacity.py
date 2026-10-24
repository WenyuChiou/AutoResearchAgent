"""Explicit audit capacity with real saved consent and unchanged resource limits."""

from copy import deepcopy
import unittest

from research_workspace_native.project_intake import ProjectIntakeService, MAX_ACTIONS
from research_workspace_native.project_stage1_run_grant import (
    ProjectStage1RunGrantService,
    STORE,
)
from research_workspace_native.session_api import SessionApiError
from stage1_ledger.journal import canonical
from stage1_deliverable.common import sha
import test_project_stage1_run_grant as fixture
from test_workspace_project_intake import bound_body, authenticate


class RunHistoryCapacityTests(unittest.TestCase):
    setUp = fixture.RunGrantTests.setUp
    body = fixture.RunGrantTests.body
    authorize = fixture.RunGrantTests.authorize
    inspect = fixture.RunGrantTests.inspect
    derive = fixture.RunGrantTests.derive

    def count(self):
        return self.intake.db.execute(
            "SELECT COUNT(*) FROM intake_actions WHERE principal=? AND project=?",
            ("alice", self.ref),
        ).fetchone()[0]

    def seed_history(self, total):
        # Seed only completed no-op historical receipts, never resource reservations.
        before = self.count()
        body = bound_body(self.intake.read("alice-token", self.ref), "fixture")
        values = []
        for n in range(before, total):
            request = {
                k: v
                for k, v in {**body, "key": f"fixture-{n}"}.items()
                if k != "revision"
            }
            pin = sha(canonical({"kind": "test-no-work", "body": request}))
            receipt = dict(
                project_ref=self.ref,
                key=request["key"],
                kind="test-no-work",
                request_sha256=pin,
                request=request,
                status="saved",
            )
            values.append(
                ("alice", self.ref, request["key"], pin, canonical(receipt).decode())
            )
        self.intake.db.executemany(
            "INSERT INTO intake_actions VALUES(?,?,?,?,?)", values
        )
        self.intake.db.commit()
        return before

    def noop(self, key):
        return self.intake._perform(
            "alice",
            self.ref,
            "test-no-work",
            bound_body(self.intake.read("alice-token", self.ref), key),
            lambda *_: {},
        )

    def test_explicit_versioned_capacity_passes_256_without_reset_after_reopen(self):
        original = deepcopy(self.intake.binding(self.ref)["settings"])
        grant = self.authorize(max_history_actions=1024)
        document = self.inspect(grant)
        self.assertEqual(document["schema_version"], "1.1.0")
        self.assertEqual(document["max_history_actions"], 1024)
        self.seed_history(MAX_ACTIONS)
        old_rows = [
            tuple(r)
            for r in self.intake.db.execute(
                "SELECT key,request_hash,receipt FROM intake_actions ORDER BY key"
            )
        ]
        self.intake.close()
        self.intake = ProjectIntakeService(self.root, authenticate=authenticate)
        self.service = ProjectStage1RunGrantService(
            self.intake, runtime_sha256="a" * 64, clock=lambda: self.now
        )
        self.assertEqual(self.noop("after-256")["status"], "saved")
        self.assertEqual(self.count(), MAX_ACTIONS + 1)
        current = {
            r[0]: tuple(r)
            for r in self.intake.db.execute(
                "SELECT key,request_hash,receipt FROM intake_actions"
            )
        }
        self.assertTrue(all(current[r[0]] == r for r in old_rows))
        self.assertEqual(self.intake.binding(self.ref)["settings"], original)
        self.assertTrue(self.noop("after-256")["replayed"])
        self.assertEqual(self.count(), MAX_ACTIONS + 1)

    def test_legacy_consent_keeps_original_cap(self):
        grant = self.authorize()
        self.assertEqual(self.inspect(grant)["schema_version"], "1.0.0")
        self.seed_history(MAX_ACTIONS)
        with self.assertRaises(SessionApiError):
            self.noop("legacy-overflow")
        self.assertEqual(self.count(), MAX_ACTIONS)

    def test_invalid_capacity_and_nonconsent_do_not_expand_history(self):
        for value in (True, 256.0, 255, 2049, "1024", None):
            with self.subTest(value=value), self.assertRaises(SessionApiError):
                self.authorize(max_history_actions=value)
        self.assertNotIn(STORE, self.intake._load("alice", self.ref))
        self.seed_history(MAX_ACTIONS)
        with self.assertRaises(SessionApiError):
            self.noop("not-opted-in")

    def test_rehashed_capacity_cannot_replace_original_consent(self):
        grant = self.authorize(max_history_actions=512)
        state = self.intake._load("alice", self.ref)
        row = state[STORE][grant["grant_ref"]]
        row["document"]["max_history_actions"] = 2048
        row["sha256"] = sha(canonical(row["document"]))
        self.intake.db.execute(
            "UPDATE intake_projects SET state=? WHERE ref=?",
            (canonical(state).decode(), self.ref),
        )
        self.intake.db.commit()
        self.seed_history(MAX_ACTIONS)
        with self.assertRaises(SessionApiError):
            self.noop("tamper-overflow")
        self.assertEqual(self.count(), MAX_ACTIONS)

    def test_expiry_and_revocation_never_clear_audit_capacity_or_restore_execution(
        self,
    ):
        grant = self.authorize(max_history_actions=512)
        token = self.derive(grant)
        self.now = grant["expires_at"]
        with self.assertRaises(SessionApiError):
            self.inspect(grant)
        self.service.revoke(
            "alice-token",
            self.ref,
            {
                **bound_body(self.intake.read("alice-token", self.ref), "cancel"),
                "grant_ref": grant["grant_ref"],
                "grant_sha256": grant["grant_sha256"],
            },
        )
        self.seed_history(MAX_ACTIONS)
        self.assertEqual(self.noop("retain-cancellation-audit")["status"], "saved")
        with self.assertRaises(SessionApiError):
            token.check(self.intake, "alice", self.ref, "query", "b" * 64)
        self.assertEqual(self.count(), MAX_ACTIONS + 1)

    def test_opted_in_capacity_is_still_bounded_and_old_key_is_readable(self):
        self.authorize(max_history_actions=512)
        self.noop("saved-noop")
        self.seed_history(512)
        with self.assertRaises(SessionApiError):
            self.noop("overflow")
        self.assertTrue(self.noop("saved-noop")["replayed"])
        self.assertEqual(self.count(), 512)


if __name__ == "__main__":
    unittest.main()
