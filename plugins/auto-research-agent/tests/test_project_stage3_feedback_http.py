"""Real owned journal behind the transport handler; no network/model dispatch."""

from copy import deepcopy
import io
import json
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from test_project_stage3_feedback import Stage3FeedbackFixture
from test_project_stage3_planning_http import Handler
from research_workspace_native.project_stage3_http import (
    ProjectStage3Http,
    handle_planning,
)
from research_workspace_native.session_api import SessionApiError
from research_workspace_native.http import MAX_RESPONSE, SessionHandler


class Stage3FeedbackHttpTests(Stage3FeedbackFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()

        def read(credential, ref, **kwargs):
            if ref != "authored-ref":
                raise SessionApiError("project-not-found", 404)
            return dict(deepcopy(self.view), planning_mode="direction-intent")

        self.service = SimpleNamespace(
            intake=SimpleNamespace(_lock=threading.RLock()),
            bindings={"authored-ref": {"jobs": self.jobs}},
            read=read,
        )
        self.closed = []
        self.transport = ProjectStage3Http(
            self.service, close_owner=lambda: self.closed.append(1)
        )
        self.addCleanup(self.transport.close)

    def handler(self, action=None, body=None, **kwargs):
        handler = Handler(self.transport, action, body, **kwargs)
        handler.path = "/api/projects/authored-ref/stage3/planning" + (
            "/" + action if action else ""
        )
        return handler

    def comment_body(self):
        return dict(
            self.request("http-comment"),
            text="Keep the limitations.",
            question_ref="q1",
        )

    def assert_actual_reply_readable(self, view):
        handler = Mock(wfile=io.BytesIO())
        SessionHandler._reply(handler, 200, view)
        handler.send_response.assert_called_once_with(200)
        self.assertLessEqual(len(handler.wfile.getvalue()), MAX_RESPONSE)

    def test_aggregate_drafts_cannot_hide_original_or_lose_receipt_readback(self):
        self.view["plan"]["markdown"] = "資料😀" * 15000
        from research_workspace_native.project_stage3_feedback import read_feedback

        self.binding = read_feedback(self.jobs, "authored-ref", self.view)["binding"]
        comment = self.comment()
        rejected = False
        for index in range(8):
            before = read_records(self)
            try:
                self.revision(comment, key="wire-" + str(index))
            except SessionApiError as error:
                self.assertEqual(error.status, 413)
                self.assertEqual(read_records(self), before)
                rejected = True
            self.assert_actual_reply_readable(
                self.transport.view("own", "authored-ref")
            )
            if rejected:
                break
        self.assertTrue(rejected)

    def test_near_limit_original_remains_readable_without_feedback_envelope(self):
        bare = self.transport._view("own", "authored-ref")
        size = len(json.dumps(bare, ensure_ascii=True, allow_nan=False).encode("utf8"))
        self.view["plan"]["markdown"] += "x" * (MAX_RESPONSE - size - 32)
        view = self.transport.view("own", "authored-ref")
        self.assert_actual_reply_readable(view)
        self.assertEqual(view["plan"], self.view["plan"])
        self.assertNotIn("feedback", view)

    def test_comment_revision_and_read_use_original_receipts_without_dispatch(self):
        comment = self.handler("comment", self.comment_body())
        handle_planning(comment, "POST")
        self.assertEqual(comment.replies[0][0], 200)
        receipt = comment.replies[0][1]
        body = dict(
            self.request("http-revision"),
            comments=[{"key": "http-comment", "sha256": receipt["receipt_sha256"]}],
            parent_revision=None,
            changes=[
                {
                    "question_ref": "q1",
                    "field": "design",
                    "value": "A manual alternative",
                }
            ],
        )
        revision = self.handler("revise", body)
        handle_planning(revision, "POST")
        self.assertEqual(revision.replies[0][0], 200)
        replay = self.handler("revise", body)
        handle_planning(replay, "POST")
        self.assertTrue(replay.replies[0][1]["replayed"])
        self.assertEqual(
            replay.replies[0][1]["receipt_sha256"],
            revision.replies[0][1]["receipt_sha256"],
        )
        read = self.handler()
        handle_planning(read, "GET")
        self.assertEqual(read.replies[0][0], 200)
        self.assertEqual(len(read.replies[0][1]["feedback"]["records"]), 2)
        self.assertFalse(revision.replies[0][1]["execution_authorized"])
        self.assertEqual(
            self.view["plan"]["question_plans"][0]["design"], "Original design"
        )

    def test_auth_cross_site_unknown_project_and_limits_do_not_write(self):
        cases = [
            (self.handler("comment", self.comment_body(), credential="wrong"), 401),
            (
                self.handler("comment", dict(self.comment_body(), input_version="1")),
                409,
            ),
            (
                self.handler(
                    "comment", dict(self.comment_body(), parent_plan_sha256="0" * 64)
                ),
                409,
            ),
            (self.handler("comment", dict(self.comment_body(), text="x" * 4096)), 413),
        ]
        crossed = self.handler("comment", self.comment_body())
        crossed.headers["Sec-Fetch-Site"] = "cross-site"
        cases.append((crossed, 403))
        missing = self.handler("comment", self.comment_body())
        missing.path = missing.path.replace("authored-ref", "missing-ref")
        cases.append((missing, 404))
        for handler, status in cases:
            with self.subTest(status=status):
                handle_planning(handler, "POST")
                self.assertEqual(handler.replies[0][0], status)
        self.assertEqual(read_records(self), [])

    def test_lost_reply_is_readable_and_same_key_replay_does_not_append(self):
        handler = self.handler("comment", self.comment_body())

        def lost(*args):
            raise ConnectionResetError("Authored loss after local commit")

        handler._reply = lost
        handle_planning(handler, "POST")
        self.assertTrue(handler.close_connection)
        original = read_records(self)
        self.assertEqual(len(original), 1)
        retry = self.handler("comment", self.comment_body())
        handle_planning(retry, "POST")
        self.assertTrue(retry.replies[0][1]["replayed"])
        self.assertEqual(read_records(self), original)

    def test_active_project_rejects_another_write(self):
        self.transport.admit_feedback("authored-ref", self.comment_body(), "comment")
        handler = self.handler("comment", self.comment_body())
        handle_planning(handler, "POST")
        self.assertEqual(handler.replies[0][0], 409)
        self.transport.finish("authored-ref")
        self.assertEqual(read_records(self), [])

    def test_expired_handler_deadline_releases_admission_without_write(self):
        handler = self.handler("comment", self.comment_body())
        calls = []

        def remaining():
            calls.append(1)
            if len(calls) >= 3:
                raise TimeoutError("Authored real admission deadline")
            return 10

        handler._remaining = remaining
        handle_planning(handler, "POST")
        self.assertTrue(handler.close_connection)
        self.assertEqual(read_records(self), [])
        self.assertTrue(self.transport.close()["threads_joined"])

    def test_shutdown_drains_existing_local_write_before_releasing_owner(self):
        entered, release = threading.Event(), threading.Event()
        original = self.service.read

        def held(*args, **kwargs):
            entered.set()
            if not release.wait(4):
                raise AssertionError("Authored local write was not released")
            return original(*args, **kwargs)

        self.service.read = held
        handler = self.handler("comment", self.comment_body())
        thread = threading.Thread(target=handle_planning, args=(handler, "POST"))
        self.addCleanup(thread.join, 5)
        self.addCleanup(release.set)
        thread.start()
        self.assertTrue(entered.wait(2))
        self.assertFalse(self.transport.close()["threads_joined"])
        self.assertEqual(self.closed, [])
        release.set()
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(handler.replies[0][0], 200)
        self.assertEqual(self.closed, [1])
        self.assertTrue(self.transport.close()["threads_joined"])


def read_records(case):
    from research_workspace_native.project_stage3_feedback import read_feedback

    return read_feedback(case.jobs, "authored-ref", case.view)["records"]
