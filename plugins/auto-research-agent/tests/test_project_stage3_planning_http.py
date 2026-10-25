"""Transport-only fixtures; real source/journal/selection are covered in E2E."""

import io
import json
from pathlib import Path
import sys
import threading
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace_native.project_stage3_http import (  # noqa: E402
    ProjectStage3Http,
    handle_planning,
)
from research_workspace_native.session_api import SessionApiError  # noqa: E402
from stage3_plan.jobs import POLICY  # noqa: E402


BODY = dict(
    key="plan-once",
    revision=1,
    input_version="v1",
    brief_sha256="a" * 64,
    selection_request_sha256="b" * 64,
    request_sha256="c" * 64,
    confirmed=True,
)


class Service:
    def __init__(self):
        self.bindings = {}
        self.status = "intent-recorded"
        self.calls = 0
        self.failure = None
        self.entered = threading.Event()
        self.release = threading.Event()

    def read(self, *args, **kwargs):
        return dict(selection_request_sha256=None, **POLICY)

    def inspect(self, *args, **kwargs):
        return dict(status=self.status, outcome=None, **POLICY)

    def prepare(self, *args, **kwargs):
        return self.inspect()

    def run(self, *args, check_deadline, **kwargs):
        check_deadline()
        self.calls += 1
        self.entered.set()
        if not self.release.wait(3):
            raise AssertionError("test callback was not released")
        check_deadline()
        if self.failure:
            raise self.failure
        self.status = "completed"
        return self.inspect()


class Handler:
    def __init__(self, transport, action="run", body=None, *, credential="own"):
        raw = json.dumps(BODY if body is None else body).encode()
        self.rfile, self.wfile = io.BytesIO(raw), io.BytesIO()
        self.headers = {"Content-Type": "application/json"}
        self.path = "/api/projects/project-1/stage3/planning"
        if action:
            self.path += "/" + action
        self.server = SimpleNamespace(
            project_stage3_http=transport,
            authenticate=lambda token: "local-viewer" if token == "own" else None,
        )
        self.credential, self.length = credential, len(raw)
        self.replies = []
        self.replied = threading.Event()
        self.close_connection = False

    def _headers(self, method):
        return self.credential, 0 if method == "GET" else self.length

    def _remaining(self):
        return 10

    def _reply(self, status, body):
        self.replies.append((status, body))
        self.replied.set()


class PlanningHttpTests(unittest.TestCase):
    def setUp(self):
        self.service = Service()
        self.transport = ProjectStage3Http(self.service)

    def test_read_and_prepare_do_not_dispatch(self):
        read = Handler(self.transport, action=None)
        handle_planning(read, "GET")
        prepare = Handler(self.transport, action="prepare")
        handle_planning(prepare, "POST")
        self.assertEqual([read.replies[0][0], prepare.replies[0][0]], [200, 200])
        self.assertEqual(self.service.calls, 0)

    def test_run_ack_precedes_callback_and_duplicate_has_no_second_dispatch(self):
        handler = Handler(self.transport)
        thread = threading.Thread(target=handle_planning, args=(handler, "POST"))
        thread.start()
        self.addCleanup(thread.join, 4)
        self.addCleanup(self.service.release.set)
        self.assertTrue(handler.replied.wait(2))
        self.assertEqual(handler.replies[0][0], 202)
        self.assertIs(handler.replies[0][1]["dispatch_observed"], False)
        self.assertTrue(self.service.entered.wait(2))
        replay = Handler(self.transport)
        handle_planning(replay, "POST")
        self.assertEqual(replay.replies[0][0], 200)
        self.assertTrue(replay.replies[0][1]["submission_in_progress"])
        self.assertEqual(self.service.calls, 1)
        self.service.release.set()
        thread.join(3)
        self.assertFalse(thread.is_alive())

    def test_after_ack_error_is_visible_without_retry(self):
        self.service.failure = SessionApiError("saved-source-changed", 409)
        self.service.release.set()
        handler = Handler(self.transport)
        handle_planning(handler, "POST")
        state = self.transport.view("own", "project-1")
        self.assertEqual(handler.replies[0][0], 202)
        self.assertEqual(state["submission_error"]["code"], "saved-source-changed")
        self.assertFalse(state["submission_error"]["automatic_retry"])
        self.assertFalse(state["submission_in_progress"])
        self.assertEqual(self.service.calls, 1)

    def test_untrusted_fields_and_missing_recovery_pin_are_rejected(self):
        for action, body, status in (
            ("run", dict(BODY, confirmed=False), 400),
            ("run", dict(BODY, model="browser-model"), 400),
            ("recover", dict(BODY, expected_plan_manifest_sha256="d" * 64), 409),
        ):
            with self.subTest(action=action, body=body):
                handler = Handler(self.transport, action, body)
                handle_planning(handler, "POST")
                self.assertEqual(handler.replies[0][0], status)
        self.assertEqual(self.service.calls, 0)

    def test_auth_and_origin_rejection_do_not_dispatch(self):
        unauthorized = Handler(self.transport, credential="wrong")
        handle_planning(unauthorized, "POST")
        crossed = Handler(self.transport)
        crossed.headers["Sec-Fetch-Site"] = "cross-site"
        handle_planning(crossed, "POST")
        self.assertEqual(
            [unauthorized.replies[0][0], crossed.replies[0][0]], [401, 403]
        )
        self.assertEqual(self.service.calls, 0)

    def test_nonobject_write_envelopes_are_rejected_without_dispatch(self):
        for action in ("prepare", "run", "inspect", "recover"):
            with self.subTest(action=action):
                handler = Handler(self.transport, action, [])
                handle_planning(handler, "POST")
                self.assertEqual(
                    handler.replies,
                    [(400, {"error": "stage3-planning-object-required"})],
                )
        self.assertEqual(self.service.calls, 0)

    def test_shutdown_rejects_future_admission_and_closes_owner_once(self):
        closed = []
        transport = ProjectStage3Http(
            self.service, close_owner=lambda: closed.append(1)
        )
        self.assertTrue(transport.close()["threads_joined"])
        transport.close()
        handler = Handler(transport)
        handle_planning(handler, "POST")
        self.assertEqual(closed, [1])
        self.assertTrue(handler.close_connection)
        self.assertEqual(self.service.calls, 0)


if __name__ == "__main__":
    unittest.main()
