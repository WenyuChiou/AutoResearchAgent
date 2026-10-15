"""Durable scope refusal/recovery with real SQLite and injected native events."""

from copy import deepcopy
import unittest

import atlas_test_paths  # noqa: F401
import test_research_workspace_native_scope_api as fixtures
import test_research_workspace_native_session_api as session_fixture
from research_workspace_native.controller import InjectedSessionController
from research_workspace_native.frame_journal import FrameJournal
from research_workspace_native.scope_api import ScopeApi
from research_workspace_native.session_api import SessionApi, SessionApiError
from stage1_ledger.journal import canonical
from stage1_deliverable.common import sha
from native_session_fixtures import Channel


class ScopeStaleRecoveryTests(unittest.TestCase):
    setUp = fixtures.ScopeApiTests.setUp
    project = fixtures.ScopeApiTests.project
    brief = fixtures.ScopeApiTests.brief
    body = fixtures.ScopeApiTests.body
    push = session_fixture.SessionApiTests.push

    def advance(self, p):
        # A real controller/FrameJournal receives a synthetic protocol request.
        return session_fixture.SessionApiTests.request(self, p)

    def rejected(self, operation, p, body):
        with self.assertRaises(SessionApiError) as raised:
            operation("token-a", p.ref, body)
        error = raised.exception
        self.assertEqual(error.code, "stale-revision")
        self.assertIsNotNone(error.receipt)
        receipt = error.receipt
        self.assertEqual(receipt["status"], "rejected-known-unsent")
        self.assertFalse(receipt["execution_authorized"])
        self.assertEqual(receipt["submitted_request"], body)
        self.assertEqual(receipt["submitted_request_sha256"], sha(canonical(body)))
        self.assertEqual(receipt["submitted_revision"], body["revision"])
        self.assertGreater(receipt["observed_revision"], body["revision"])
        return receipt

    def test_native_event_stales_scope_and_explicit_fresh_action_saves_once(self):
        p = self.brief()
        body = self.body(p)
        self.advance(p)
        before = p.store.snapshot(p.pid)
        io = list(p.channel.calls)
        rejected = self.rejected(self.scope.append, p, body)
        state = p.store.snapshot(p.pid)
        self.assertEqual(
            state["scope_overlay"]["versions"], before["scope_overlay"]["versions"]
        )
        self.assertEqual(state["intents"], before["intents"])
        self.assertEqual(state["requests"], before["requests"])
        self.assertEqual(p.channel.calls, io)
        self.assertEqual(p.store.events(p.pid)[-1]["kind"], "scope-rejected")
        history = self.scope.history("token-a", p.ref)
        self.assertEqual(history["actions"], [rejected])
        self.assertEqual(rejected["version_ref"], body["parent_ref"])
        self.assertEqual(rejected["version_sha256"], body["parent_sha256"])
        events = p.store.events(p.pid)
        replay = self.rejected(self.scope.append, p, body)
        self.assertTrue(replay["replayed"])
        # A changed revision cannot turn this exact retained key into an append.
        with self.assertRaises(SessionApiError) as raised:
            self.scope.append(
                "token-a", p.ref, dict(body, revision=history["revision"])
            )
        self.assertTrue(raised.exception.receipt["replayed"])
        changed = deepcopy(body)
        changed["choices"][0]["value"] = "different"
        with self.assertRaisesRegex(SessionApiError, "idempotency-payload-differs"):
            self.scope.append("token-a", p.ref, changed)
        self.assertEqual(p.store.events(p.pid), events)
        accepted = self.scope.append(
            "token-a", p.ref, self.body(p, key="explicit-fresh")
        )
        self.assertEqual(accepted["status"], "version-saved")
        self.assertEqual(len(self.scope.history("token-a", p.ref)["versions"]), 2)
        self.assertEqual(p.brief_path.read_bytes(), p.brief_raw)
        self.assertEqual(p.channel.calls, io)

    def test_real_reopen_new_owner_recovers_exact_refusal_without_native_io(self):
        p = self.brief()
        body = self.body(p)
        self.advance(p)
        first = self.rejected(self.scope.append, p, body)
        original_store, original_owner, original_channel = p.store, p.owner, p.channel
        original_store.close()
        p.store = FrameJournal(p.root / "session.sqlite3")
        self.addCleanup(p.store.close)
        p.owner = p.store.acquire_owner(p.pid, "fresh-scope-owner")
        p.epoch += "-reopened"
        p.channel = Channel()
        p.controller = InjectedSessionController(
            store=p.store,
            project_id=p.pid,
            owner=p.owner,
            connection_id=p.epoch,
            index_sha256=p.hash,
            thread_id=p.thread,
            channel=p.channel,
            verify_binding=lambda: True,
            admit_action=lambda _action: False,
        )
        self.api = SessionApi(authenticate=self.authenticate)
        self.api.register(p.ref, **dict(p.registration, controller=p.controller))
        self.scope = ScopeApi(self.api)
        self.scope.register(
            p.ref, brief_path="brief.json", expected_sha256=p.brief_hash
        )
        self.assertIsNot(p.store, original_store)
        self.assertNotEqual(p.owner, original_owner)
        before = p.store.events(p.pid)
        self.assertEqual(self.scope.history("token-a", p.ref)["actions"], [first])
        replay = self.rejected(self.scope.append, p, body)
        self.assertTrue(replay["replayed"])
        self.assertEqual(p.store.events(p.pid), before)
        self.assertEqual(p.channel.calls, [])
        self.assertEqual(original_channel.messages(), [])

    def test_commit_or_deadline_failure_never_creates_known_unsent_receipt(self):
        def expired():
            raise TimeoutError

        p = self.brief()
        body = self.body(p)
        self.advance(p)
        before = p.store.snapshot(p.pid)
        p.store.db.execute("""CREATE TEMP TRIGGER fail_refusal BEFORE INSERT ON events
          WHEN NEW.kind='scope-rejected' BEGIN SELECT RAISE(ABORT,'disk refusal'); END""")
        with self.assertRaises(SessionApiError) as raised:
            self.scope.append("token-a", p.ref, body)
        self.assertIsNone(raised.exception.receipt)
        self.assertEqual(p.store.snapshot(p.pid), before)
        p.store.db.execute("DROP TRIGGER fail_refusal")
        with self.assertRaises(SessionApiError) as raised:
            self.scope.append("token-a", p.ref, body, check_deadline=expired)
        self.assertEqual(raised.exception.code, "request-timeout")
        self.assertIsNone(raised.exception.receipt)
        self.assertEqual(p.store.snapshot(p.pid), before)

    def test_invalid_choice_parent_source_or_principal_still_fail_closed(self):
        p = self.brief()
        body = self.body(p)
        self.advance(p)
        before = p.store.snapshot(p.pid)
        for changes in (
            {"choices": []},
            {"parent_sha256": "f" * 64},
            {"confirmed": 1},
            {"input_version": "f" * 64},
        ):
            with (
                self.subTest(changes=changes),
                self.assertRaises(SessionApiError) as raised,
            ):
                self.scope.append("token-a", p.ref, dict(body, **changes))
            self.assertIsNone(raised.exception.receipt)
            self.assertEqual(p.store.snapshot(p.pid), before)
        with self.assertRaises(SessionApiError):
            self.scope.append("token-b", p.ref, body)
        p.brief_path.write_bytes(p.brief_raw + b" ")
        with self.assertRaises(SessionApiError):
            self.scope.append("token-a", p.ref, body)
        self.assertEqual(p.store.snapshot(p.pid), before)

    def test_review_refusal_keeps_target_and_requires_explicit_new_decision(self):
        p = self.brief()
        old = self.scope.history("token-a", p.ref)
        target = old["versions"][0]
        body = dict(
            key="old-review",
            revision=old["revision"],
            index_sha256=p.hash,
            input_version=p.version,
            confirmed=True,
            version_ref=target["version_ref"],
            version_sha256=target["sha256"],
            decision="reviewed",
            note="Explicit review.",
        )
        self.advance(p)
        refusal = self.rejected(self.scope.review, p, body)
        self.assertEqual(refusal["version_ref"], target["version_ref"])
        fresh = dict(
            body,
            key="new-review",
            revision=self.scope.history("token-a", p.ref)["revision"],
        )
        receipt = self.scope.review("token-a", p.ref, fresh)
        self.assertEqual(receipt["status"], "review-recorded")
        self.assertFalse(receipt["execution_authorized"])
        self.assertEqual(len(self.scope.history("token-a", p.ref)["versions"]), 1)


if __name__ == "__main__":
    unittest.main()
