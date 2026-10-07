"""API crash gaps and fault/close evidence on fresh SQLite writers; synthetic I/O."""

from contextlib import contextmanager
from unittest.mock import patch
import unittest

import test_research_workspace_native_session_api as api_fixture
from research_workspace_native.controller import InjectedSessionController
from research_workspace_native.frame_journal import FrameJournal
from research_workspace_native.recording import records
from research_workspace_native.session_api import SessionApi, SessionApiError
from native_session_fixtures import Channel


class SimulatedCrash(BaseException):
    """Bypass in-process fault handling at the specified durable boundary."""


class ApiRecoveryTests(unittest.TestCase):
    setUp = api_fixture.SessionApiTests.setUp
    project = api_fixture.SessionApiTests.project
    push = api_fixture.SessionApiTests.push
    request = api_fixture.SessionApiTests.request
    body = api_fixture.SessionApiTests.body

    def reopen(self, p):
        original_store, original_owner = p.store, p.owner
        original_store.close()
        p.store = FrameJournal(p.root / "session.sqlite3")
        self.addCleanup(p.store.close)
        p.owner = p.store.acquire_owner(p.pid, "fresh-server")
        p.epoch += "-new"
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
            admit_action=lambda action: True,
        )
        self.api = SessionApi(authenticate=self.authenticate)
        self.api.register(p.ref, **dict(p.registration, controller=p.controller))
        self.assertIsNot(p.store, original_store)
        self.assertNotEqual(p.owner, original_owner)

    def test_crash_before_controller_dispatch_reopens_without_resend(self):
        p = self.project()
        body = self.body(p, self.request(p))
        original = p.channel
        with patch.object(p.controller, "answer", side_effect=SimulatedCrash):
            with self.assertRaises(SimulatedCrash):
                self.api.answer("token-a", p.ref, body)
        self.assertEqual(original.sent, [])
        self.reopen(p)
        self.assert_replay(p, body, "dispatch-unobserved")
        self.assertEqual(original.sent, [])

    def test_crash_after_recorded_write_reopens_unknown_without_resend(self):
        p = self.project()
        body = self.body(p, self.request(p))
        original, epoch = p.channel, p.epoch
        with (
            patch.object(p.controller, "_save", side_effect=SimulatedCrash),
            patch.object(p.controller, "_fault", side_effect=SimulatedCrash),
        ):
            with self.assertRaises(SimulatedCrash):
                self.api.answer("token-a", p.ref, body)
        self.assertEqual(len(original.messages()), 1)
        self.assertTrue(
            any(
                r["operation"] == "write" and r["phase"] == "result"
                for r in records(p.store, p.pid, epoch)
            )
        )
        self.reopen(p)
        self.assert_replay(p, body, "execution-unknown")
        self.assertEqual(len(original.messages()), 1)

    def assert_replay(self, p, body, status):
        before = p.store.events(p.pid)
        receipt = self.api.answer("token-a", p.ref, body)
        self.assertTrue(receipt["replayed"])
        self.assertEqual(receipt["status"], status)
        self.assertEqual(
            self.api.action("token-a", p.ref, receipt["action_ref"])["status"], status
        )
        self.api.view("token-a", p.ref)
        with self.assertRaises(SessionApiError):
            self.api.answer(
                "token-a",
                p.ref,
                dict(body, result={"answers": {"q": {"answers": ["changed"]}}}),
            )
        self.assertEqual(p.store.events(p.pid), before)
        self.assertEqual(p.channel.calls, [])

    def test_post_recording_fault_persistence_failure_keeps_close_and_history(self):
        p = self.project()
        body = self.body(p, self.request(p))
        original_edit, channel, epoch = p.store._edit, p.channel, p.epoch

        @contextmanager
        def fail_status_and_fault(project, owner, revision, kind, payload=None, **kw):
            if kind in {"controller-action-status", "controller-fault"}:
                raise OSError("synthetic status/fault persistence failure")
            with original_edit(
                project, owner, revision, kind, payload, **kw
            ) as current:
                yield current

        with patch.object(p.store, "_edit", fail_status_and_fault):
            with self.assertRaises(SessionApiError):
                self.api.answer("token-a", p.ref, body)
        self.assertEqual(len(channel.messages()), 1)
        self.assertEqual(channel.closed, 1)
        self.assertIn("fault persistence unobserved", p.controller.failure)
        rows = records(p.store, p.pid, epoch)
        self.assertTrue(
            any(r["operation"] == "close" and r["phase"] == "result" for r in rows)
        )
        self.assertFalse(
            any(e["kind"] == "controller-fault" for e in p.store.events(p.pid))
        )
        self.reopen(p)
        self.assert_replay(p, body, "execution-unknown")
        self.assertEqual(records(p.store, p.pid, epoch), rows)
        self.assertEqual(channel.closed, 1)
