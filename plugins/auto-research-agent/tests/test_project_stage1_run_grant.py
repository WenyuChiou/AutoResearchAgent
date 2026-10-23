"""Real authenticated intake/run-grant persistence; no external execution."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage1_run_grant import (
    ProjectStage1RunGrantService,
    SCOPE,
    STORE,
)
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import sha
from stage1_ledger.journal import canonical
from test_workspace_project_intake import (
    authenticate,
    bound_body,
    compile_body,
    submit_body,
)


class RunGrantTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="stage1-run-grant-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.intake = ProjectIntakeService(self.root, authenticate=authenticate)
        self.addCleanup(lambda: self.intake.close())
        self.now = 1000.0
        self.service = ProjectStage1RunGrantService(
            self.intake, runtime_sha256="a" * 64, clock=lambda: self.now
        )
        receipt = self.intake.create(
            "alice-token", {"key": "create", "topic": "Urban flash flood forecasting"}
        )
        self.ref = receipt["project_ref"]
        view = self.intake.read("alice-token", self.ref)
        body = submit_body(view)
        body["budgets"].update(
            model_calls=3, search_calls=3, source_reads=4, seconds=120, rounds=2
        )
        body["consent"].update(external_search=True, public_source_read=True)
        self.intake.submit("alice-token", self.ref, body)
        self.intake.compile(
            "alice-token",
            self.ref,
            compile_body(self.intake.read("alice-token", self.ref)),
        )

    def body(self, key="consent", **changes):
        return {
            **bound_body(self.intake.read("alice-token", self.ref), key),
            "confirmed": True,
            "user_input": "Run Stage1 within these saved limits; stop at Core/Wiki gates.",
            "scope": SCOPE,
            "operations": [
                "query",
                "source",
                "analyze-full-paper",
                "agent-adoption",
                "records",
                "delivery",
            ],
            "max_seconds": 100,
            "max_actions": 4,
            **changes,
        }

    def authorize(self, **changes):
        return self.service.authorize("alice-token", self.ref, self.body(**changes))

    def inspect(self, grant):
        return self.service.inspect(
            "alice-token", self.ref, grant["grant_ref"], grant["grant_sha256"]
        )

    def derive(self, grant, operation="query", identity="b" * 64):
        return self.service.derive(
            "alice-token",
            self.ref,
            grant_ref=grant["grant_ref"],
            grant_sha256=grant["grant_sha256"],
            operation=operation,
            identity=identity,
        )

    def test_budget_alone_is_not_whole_run_authority(self):
        with self.assertRaises(SessionApiError):
            self.service.inspect("alice-token", self.ref, "missing", "b" * 64)
        for mutation in (
            {"confirmed": 1},
            {"confirmed": False},
            {"user_input": ""},
            {"scope": "stage2-research"},
            {"operations": ["stage2"]},
            {"operations": [["query"]]},
            {"max_actions": True},
            {"max_seconds": 1.0},
            {"max_seconds": 10801},
        ):
            with self.subTest(mutation=mutation), self.assertRaises(SessionApiError):
                self.service.authorize("alice-token", self.ref, self.body(**mutation))
        self.assertNotIn(STORE, self.intake._load("alice", self.ref))

    def test_saved_consent_and_derived_action_are_honest_agent_authority(self):
        grant = self.authorize()
        document = self.inspect(grant)
        self.assertEqual(
            document["budgets"],
            {
                "model_calls": 3,
                "search_calls": 3,
                "source_reads": 4,
                "seconds": 120,
                "rounds": 2,
            },
        )
        self.assertEqual(document["authority"], "user")
        self.assertEqual(document["automated_actor"], "agent")
        self.assertFalse(document["core_acceptance"])
        token = self.derive(grant)
        proof = token.check(self.intake, "alice", self.ref, "query", "b" * 64)
        self.assertEqual(proof["authority"], "user-run-grant")
        self.assertFalse(proof["human_per_action_confirmation"])
        state = self.intake._load("alice", self.ref)
        self.assertNotIn("stage1_query_authorization", state)
        self.assertNotIn("stage1_model_operations", state)
        self.assertNotIn("stage1_source_operations", state)
        self.assertFalse(grant["execution_observed"])
        self.assertFalse(grant["creates_lane_permits"])
        self.assertFalse(grant["resets_resources"])

    def test_actual_sqlite_reopen_and_same_keys_do_not_renew_or_derive_twice(self):
        body = self.body()
        grant = self.service.authorize("alice-token", self.ref, body)
        first = self.derive(grant)
        self.intake.close()
        self.intake = ProjectIntakeService(self.root, authenticate=authenticate)
        self.service = ProjectStage1RunGrantService(
            self.intake, runtime_sha256="a" * 64, clock=lambda: self.now
        )
        repeated = self.service.authorize(
            "alice-token", self.ref, {**body, "revision": 999}
        )
        second = self.derive(grant)
        self.assertTrue(repeated["replayed"])
        self.assertEqual(repeated["expires_at"], grant["expires_at"])
        self.assertEqual(first.key, second.key)
        self.assertEqual(first.request_sha256, second.request_sha256)
        self.assertEqual(
            len(self.intake.history("alice-token", self.ref)["actions"]), 5
        )
        self.assertEqual(
            second.check(self.intake, "alice", self.ref, "query", "b" * 64)[
                "automated_actor"
            ],
            "agent",
        )
        with self.assertRaises(SessionApiError):
            self.service.authorize("alice-token", self.ref, self.body(key="renew"))

    def test_token_cannot_cross_principal_project_operation_payload_or_runtime(self):
        grant = self.authorize()
        token = self.derive(grant)
        for principal, ref, operation, identity in (
            ("bob", self.ref, "query", "b" * 64),
            ("alice", "other", "query", "b" * 64),
            ("alice", self.ref, "source", "b" * 64),
            ("alice", self.ref, "query", "c" * 64),
        ):
            with (
                self.subTest(operation=operation, principal=principal),
                self.assertRaises(SessionApiError),
            ):
                token.check(self.intake, principal, ref, operation, identity)
        with self.assertRaises(SessionApiError):
            self.service.inspect(
                "bob-token", self.ref, grant["grant_ref"], grant["grant_sha256"]
            )
        other = ProjectStage1RunGrantService(
            self.intake, runtime_sha256="c" * 64, clock=lambda: self.now
        )
        with self.assertRaises(SessionApiError):
            other.inspect(
                "alice-token", self.ref, grant["grant_ref"], grant["grant_sha256"]
            )

    def test_expiry_revocation_and_changed_settings_block_existing_tokens(self):
        grant = self.authorize()
        token = self.derive(grant)
        self.now = 999
        with self.assertRaises(SessionApiError):
            token.check(self.intake, "alice", self.ref, "query", "b" * 64)
        self.now = grant["expires_at"]
        with self.assertRaises(SessionApiError):
            token.check(self.intake, "alice", self.ref, "query", "b" * 64)
        self.now = 1001
        view = self.intake.read("alice-token", self.ref)
        settings = deepcopy(view["settings"])
        settings["budgets"]["model_calls"] = 2
        body = {
            **bound_body(view, "config"),
            **{
                key: settings[key]
                for key in ("resource_envelope", "budgets", "consent", "user_input")
            },
            "confirmed": True,
        }
        self.intake.configure("alice-token", self.ref, body)
        with self.assertRaises(SessionApiError):
            token.check(self.intake, "alice", self.ref, "query", "b" * 64)
        receipt = self.service.revoke(
            "alice-token",
            self.ref,
            {
                **bound_body(self.intake.read("alice-token", self.ref), "revoke"),
                "grant_ref": grant["grant_ref"],
                "grant_sha256": grant["grant_sha256"],
            },
        )
        self.assertTrue(receipt["future_dispatch_revoked"])
        self.assertFalse(receipt["resources_refunded"])
        self.assertFalse(receipt["process_cleanup_attested"])
        with self.assertRaises(SessionApiError):
            self.inspect(grant)

    def test_derived_action_cap_never_refunds_or_recreates_failed_intents(self):
        grant = self.authorize(max_actions=1)
        self.derive(grant)
        with self.assertRaises(SessionApiError) as failed:
            self.derive(grant, identity="c" * 64)
        self.assertIn(
            "stage1-run-action-bound-exhausted", failed.exception.receipt["error"]
        )
        with self.assertRaises(SessionApiError):
            self.derive(grant, identity="c" * 64)
        rows = self.intake.history("alice-token", self.ref)["actions"]
        self.assertEqual(sum(row["kind"] == "stage1-run-derive" for row in rows), 2)

    def test_rehashed_modified_grant_cannot_replace_original_user_consent(self):
        grant = self.authorize()
        state = self.intake._load("alice", self.ref)
        row = state[STORE][grant["grant_ref"]]
        row["document"]["max_actions"] += 1
        new_pin = sha(canonical(row["document"]))
        row["sha256"] = new_pin
        self.intake.db.execute(
            "UPDATE intake_projects SET state=? WHERE ref=? AND principal=?",
            (canonical(state).decode(), self.ref, "alice"),
        )
        self.intake.db.commit()
        with self.assertRaises(SessionApiError):
            self.service.inspect("alice-token", self.ref, grant["grant_ref"], new_pin)


if __name__ == "__main__":
    unittest.main()
