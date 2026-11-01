"""Real owned journal behind the transport handler; no network/model dispatch."""

from copy import deepcopy
import io
import json
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

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

    def test_aggregate_comments_preserve_original_and_wire_bounded_readback(self):
        self.view["plan"]["markdown"] = "資料😀" * 40000
        from research_workspace_native.project_stage3_feedback import read_feedback

        self.binding = read_feedback(self.jobs, "authored-ref", self.view)["binding"]
        rejected = False
        for index in range(32):
            before = self.journal.snapshot(self.jobs.project_id)
            before_rows = read_records(self)
            body = dict(
                self.request("wire-" + str(index)),
                text="資料😀" * 100,
                question_ref="q1",
            )
            handler = self.handler("comment", body)
            handle_planning(handler, "POST")
            status, reply = handler.replies[0]
            if status == 413:
                self.assertEqual(self.journal.snapshot(self.jobs.project_id), before)
                self.assertEqual(read_records(self), before_rows)
                rejected = True
            else:
                self.assertEqual(status, 200)
                self.assertEqual(len(read_records(self)), len(before_rows) + 1)
                self.assertIn(
                    {name: reply[name] for name in ("receipt_sha256", "record")},
                    read_records(self),
                )
            self.assert_actual_reply_readable(reply)
            view = self.transport.view("own", "authored-ref")
            self.assert_actual_reply_readable(view)
            self.assertEqual(view["plan"], self.view["plan"])
            self.assertEqual(view["feedback"]["records"], read_records(self))
            if rejected:
                break
        self.assertTrue(rejected)
        self.assertGreater(len(read_records(self)), 0)

    def test_near_limit_original_remains_readable_without_feedback_envelope(self):
        bare = self.transport._view("own", "authored-ref")
        size = len(json.dumps(bare, ensure_ascii=True, allow_nan=False).encode("utf8"))
        self.view["plan"]["markdown"] += "x" * (MAX_RESPONSE - size - 32)
        view = self.transport.view("own", "authored-ref")
        self.assert_actual_reply_readable(view)
        self.assertEqual(view["plan"], self.view["plan"])
        self.assertNotIn("feedback", view)

    def test_comment_replay_and_read_preserve_receipt_without_dispatch(self):
        original = deepcopy(self.view)
        comment = self.handler("comment", self.comment_body())
        handle_planning(comment, "POST")
        self.assertEqual(comment.replies[0][0], 200)
        receipt = comment.replies[0][1]
        before = self.journal.snapshot(self.jobs.project_id)
        replay = self.handler("comment", self.comment_body())
        handle_planning(replay, "POST")
        self.assertEqual(replay.replies[0][0], 200)
        self.assertTrue(replay.replies[0][1]["replayed"])
        self.assertEqual(
            replay.replies[0][1]["receipt_sha256"], receipt["receipt_sha256"]
        )
        self.assertEqual(self.journal.snapshot(self.jobs.project_id), before)
        read = self.handler()
        handle_planning(read, "GET")
        self.assertEqual(read.replies[0][0], 200)
        self.assertEqual(
            read.replies[0][1]["feedback"]["records"],
            [{name: receipt[name] for name in ("receipt_sha256", "record")}],
        )
        self.assertFalse(receipt["execution_authorized"])
        self.assertEqual(self.view, original)

    def test_deferred_revision_route_is_not_handled_or_admitted(self):
        handler = self.handler("revise", self.comment_body())
        before = self.journal.snapshot(self.jobs.project_id)
        with patch.object(self.transport, "admit_feedback") as admitted:
            self.assertIs(handle_planning(handler, "POST"), False)
            admitted.assert_not_called()
        self.assertEqual(handler.replies, [])
        self.assertEqual(self.journal.snapshot(self.jobs.project_id), before)

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
            (
                self.handler("comment", dict(self.comment_body(), changes=[])),
                400,
            ),
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
