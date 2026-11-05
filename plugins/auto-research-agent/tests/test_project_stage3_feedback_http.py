"""Real owned journal behind the transport handler; no network/model dispatch."""

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
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
from research_workspace_native.http import MAX_BODY, MAX_RESPONSE, SessionHandler

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "harness-ui"))
from test_stage3_material_capacity import MaterialsHttpHarness, synthetic_payload


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

    def test_comment_revision_and_read_use_original_receipts_without_dispatch(self):
        original = deepcopy(self.view)
        text = "界" * 3200 + "x" * 41
        self.assertEqual(len(text.encode("utf8")), 9641)
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
                    "field": "materials",
                    "value": text,
                }
            ],
        )
        revision = self.handler("revise", body)
        self.assertGreater(revision.length, 4096)
        handle_planning(revision, "POST")
        self.assertEqual(revision.replies[0][0], 200)
        saved = revision.replies[0][1]
        self.assertEqual(saved["record"]["request"], body)
        self.assertEqual(
            saved["record"]["plan"]["question_plans"][0]["materials"], text
        )
        before = self.journal.snapshot(self.jobs.project_id)
        replay = self.handler("revise", body)
        handle_planning(replay, "POST")
        self.assertTrue(replay.replies[0][1]["replayed"])
        self.assertEqual(
            replay.replies[0][1]["receipt_sha256"],
            revision.replies[0][1]["receipt_sha256"],
        )
        self.assertEqual(self.journal.snapshot(self.jobs.project_id), before)
        read = self.handler()
        handle_planning(read, "GET")
        self.assertEqual(read.replies[0][0], 200)
        self.assertEqual(len(read.replies[0][1]["feedback"]["records"]), 2)
        self.assertIn(
            {name: saved[name] for name in ("receipt_sha256", "record")},
            read.replies[0][1]["feedback"]["records"],
        )
        self.assertFalse(revision.replies[0][1]["execution_authorized"])
        self.assertEqual(self.view, original)

    def test_revision_whole_wire_request_bound_rejects_without_write(self):
        comment = self.comment()
        body = dict(
            self.request("http-too-large"),
            comments=[{"key": "comment-1", "sha256": comment["receipt_sha256"]}],
            parent_revision=None,
            changes=[
                {"question_ref": "q1", "field": "materials", "value": "界" * 87381}
            ],
        )
        handler = self.handler("revise", body)
        self.assertGreater(handler.length, MAX_BODY)
        before = self.journal.snapshot(self.jobs.project_id)
        handle_planning(handler, "POST")
        self.assertEqual(handler.replies[0][0], 413)
        self.assertEqual(self.journal.snapshot(self.jobs.project_id), before)

    def test_real_25mib_http_material_reference_replay_inheritance_and_replacement(
        self,
    ):
        original = deepcopy(self.view)
        http = MaterialsHttpHarness(self.root / "materials", transport=self.transport)
        self.addCleanup(http.close)
        data = synthetic_payload(25 * 1024 * 1024)
        self.assertEqual(len(data), 26214400)
        self.assertIn('界😀"\\\n', data.decode("utf8"))
        material = http.upload(data)
        self.assertEqual(http.request("files/" + material["id"]), (200, data))
        self.assertEqual(material["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(
            self.transport.material_resolver("authored-ref", material["id"]), material
        )
        route = "/api/projects/authored-ref/stage3/planning"
        status, raw = http.request(route + "/comment", self.comment_body())
        self.assertEqual(status, 200)
        receipt = json.loads(raw)
        reference = dict(
            question_ref="q1",
            file_id=material["id"],
            sha256=material["sha256"],
            bytes=len(data),
        )
        text = "Complete authored file attached; access and rights remain unverified."
        body = dict(
            self.request("material-reference"),
            comments=[{"key": "http-comment", "sha256": receipt["receipt_sha256"]}],
            parent_revision=None,
            changes=[{"question_ref": "q1", "field": "materials", "value": text}],
            material_refs=[reference],
        )
        status, raw = http.request(route + "/revise", body)
        self.assertEqual(status, 200)
        saved = json.loads(raw)
        record = saved["record"]
        self.assertEqual(record["schema_version"], 2)
        self.assertEqual(
            record["material_refs"], [{**reference, "name": material["name"]}]
        )
        expected = deepcopy(original["plan"])
        expected["question_plans"][0]["materials"] = text
        self.assertEqual(record["plan"], expected)
        self.assertEqual(record["request"], body)
        for flag in (
            "execution_authorized",
            "evaluation_calls_authorized",
            "formal_execution_enabled",
            "external_claim_ready",
            "usable_for_formal_pairing",
        ):
            self.assertIs(record[flag], False)
            self.assertIs(saved[flag], False)
        self.assertLess(len(json.dumps(saved, ensure_ascii=True).encode("utf8")), 16384)
        self.assert_actual_reply_readable(saved)
        before = self.journal.snapshot(self.jobs.project_id)
        status, raw = http.request(route + "/revise", body)
        self.assertEqual(status, 200)
        replay = json.loads(raw)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["record"], record)
        self.assertEqual(replay["receipt_sha256"], saved["receipt_sha256"])
        self.assertEqual(self.journal.snapshot(self.jobs.project_id), before)
        status, raw = http.request(route)
        self.assertEqual(status, 200)
        self.assertIn(
            {name: saved[name] for name in ("receipt_sha256", "record")},
            json.loads(raw)["feedback"]["records"],
        )
        for key, field, value, expected_refs in (
            ("inherited", "method", "A separate method edit", record["material_refs"]),
            ("replaced", "materials", "A replacement without the prior attachment", []),
        ):
            body = dict(
                self.request(key),
                comments=body["comments"],
                parent_revision={
                    "key": saved["record"]["request"]["key"],
                    "sha256": saved["receipt_sha256"],
                },
                changes=[{"question_ref": "q1", "field": field, "value": value}],
            )
            status, raw = http.request(route + "/revise", body)
            self.assertEqual(status, 200)
            saved = json.loads(raw)
            self.assertEqual(saved["record"]["material_refs"], expected_refs)
            self.assertEqual(
                saved["record"]["plan"]["question_plans"][0]["unknowns"],
                ["Rights remain unknown"],
            )
        self.assertEqual(self.view, original)

    def test_material_reference_mismatches_incomplete_and_stale_requests_do_not_write(
        self,
    ):
        http = MaterialsHttpHarness(self.root / "materials", transport=self.transport)
        self.addCleanup(http.close)
        data = synthetic_payload(4000)
        complete = http.upload(data)
        foreign = http.upload(data, project_ref="foreign-ref")
        incomplete = http.upload(data, name="incomplete.txt", finish=False)
        corrupted = http.upload(data, name="corrupted.txt")
        (http.root / "files" / (corrupted["id"] + ".bin")).write_bytes(
            b"Changed saved bytes"
        )
        comment = self.comment()
        reference = dict(
            question_ref="q1",
            file_id=complete["id"],
            sha256=complete["sha256"],
            bytes=len(data),
        )
        body = dict(
            self.request("bad-reference"),
            comments=[{"key": "comment-1", "sha256": comment["receipt_sha256"]}],
            parent_revision=None,
            changes=[
                {
                    "question_ref": "q1",
                    "field": "materials",
                    "value": "Retain all unknowns.",
                }
            ],
            material_refs=[reference],
        )
        cases = [
            dict(body, material_refs=[dict(reference, sha256="0" * 64)]),
            dict(body, material_refs=[dict(reference, bytes=len(data) + 1)]),
            dict(body, material_refs=[dict(reference, file_id=foreign["id"])]),
            dict(body, material_refs=[dict(reference, file_id=incomplete["id"])]),
            dict(body, material_refs=[dict(reference, file_id=corrupted["id"])]),
            dict(body, input_version="1"),
            dict(
                body,
                changes=[
                    {
                        "question_ref": "q1",
                        "field": "method",
                        "value": "An unrelated edit",
                    }
                ],
            ),
        ]
        before = self.journal.snapshot(self.jobs.project_id)
        for payload in cases:
            with self.subTest(payload=payload):
                handler = self.handler("revise", payload)
                handle_planning(handler, "POST")
                self.assertEqual(handler.replies[0][0], 409)
                self.assertEqual(self.journal.snapshot(self.jobs.project_id), before)
        handler = self.handler(
            "comment", dict(self.comment_body(), material_refs=[reference])
        )
        handle_planning(handler, "POST")
        self.assertEqual(handler.replies[0][0], 400)
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

    def test_aggregate_drafts_cannot_hide_original_or_lose_receipt_readback(self):
        self.view["plan"]["markdown"] = "資料😀" * 15000
        from research_workspace_native.project_stage3_feedback import read_feedback

        self.binding = read_feedback(self.jobs, "authored-ref", self.view)["binding"]
        comment = self.comment()
        rejected = False
        for index in range(8):
            before = read_records(self)
            before_state = self.journal.snapshot(self.jobs.project_id)
            body = dict(
                self.request("wire-" + str(index)),
                comments=[{"key": "comment-1", "sha256": comment["receipt_sha256"]}],
                parent_revision=None,
                changes=[
                    {
                        "question_ref": "q1",
                        "field": "materials",
                        "value": "界" * 3200 + "x" * 41,
                    }
                ],
            )
            handler = self.handler("revise", body)
            self.assertGreater(handler.length, 4096)
            handle_planning(handler, "POST")
            status, reply = handler.replies[0]
            if status == 413:
                self.assertEqual(reply["error"], "stage3-feedback-response-bound")
                self.assertEqual(read_records(self), before)
                self.assertEqual(
                    self.journal.snapshot(self.jobs.project_id), before_state
                )
                rejected = True
            else:
                self.assertEqual(status, 200)
                self.assertEqual(len(read_records(self)), len(before) + 1)
            self.assert_actual_reply_readable(
                self.transport.view("own", "authored-ref")
            )
            if rejected:
                break
        self.assertTrue(rejected)


def read_records(case):
    from research_workspace_native.project_stage3_feedback import read_feedback

    return read_feedback(case.jobs, "authored-ref", case.view)["records"]
