"""Plan decisions are local, bound, idempotent records; they never dispatch or authorize."""

from copy import deepcopy
import threading
from types import SimpleNamespace
import unittest

from test_project_stage3_feedback import Stage3FeedbackFixture
from test_project_stage3_planning_http import Handler
from research_workspace_native.project_stage3_feedback import read_feedback
from research_workspace_native.project_stage3_http import (
    ProjectStage3Http,
    handle_planning,
)
from research_workspace_native.session_api import SessionApiError


class Stage3DecisionTests(Stage3FeedbackFixture, unittest.TestCase):
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
        self.transport = ProjectStage3Http(self.service, close_owner=lambda: None)
        self.addCleanup(self.transport.close)

    def rebind(self):
        self.binding = read_feedback(self.jobs, "authored-ref", self.view)["binding"]

    def decision(self, key="decision-1", decision="accept", text="I accept this plan."):
        return dict(self.request(key), decision=decision, text=text, confirmed=True)

    def post(self, body, **kwargs):
        handler = Handler(self.transport, "decide", body, **kwargs)
        handler.path = "/api/projects/authored-ref/stage3/planning/decide"
        handle_planning(handler, "POST")
        return handler.replies[0]

    def journal_state(self):
        return self.journal.snapshot(self.jobs.project_id)

    def test_accept_records_an_honest_local_decision_and_reads_back(self):
        status, reply = self.post(self.decision())
        self.assertEqual(status, 200, reply)
        record = reply["record"]
        self.assertEqual(record["decision"], "accept")
        self.assertEqual(record["decision_status"], "recorded-by-local-host-ui")
        self.assertIs(record["identity_authenticated"], False)
        self.assertIs(record["native_message"], False)
        self.assertIs(record["model_generated"], False)
        self.assertIs(record["execution_authorized"], False)
        self.assertIs(record["stage2_selection_change_required"], False)
        self.assertEqual(
            record["accept_condition"], "every-question-plan-has-all-content-fields"
        )
        self.assertFalse(reply["replayed"])
        before = self.journal_state()
        view = self.transport.view("own", "authored-ref")
        self.assertEqual(
            view["decision"]["latest"]["receipt_sha256"], reply["receipt_sha256"]
        )
        self.assertEqual(view["plan"], self.view["plan"])
        self.assertEqual(self.journal_state(), before)  # reading writes nothing

    def test_replay_returns_the_stored_record_and_changes_nothing(self):
        first = self.post(self.decision())[1]
        before = self.journal_state()
        status, replay = self.post(self.decision())
        self.assertEqual(status, 200)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["receipt_sha256"], first["receipt_sha256"])
        self.assertEqual(self.journal_state(), before)
        # the fixture forbids any planner or process dispatch (AssertionError)

    def test_same_key_with_another_body_is_refused(self):
        self.post(self.decision())
        before = self.journal_state()
        status, reply = self.post(self.decision(text="Different words."))
        self.assertEqual(
            (status, reply["error"]), (409, "stage3-decision-key-payload-differs")
        )
        self.assertEqual(self.journal_state(), before)

    def test_a_changed_plan_version_is_refused_and_leaves_nothing(self):
        body = self.decision()
        self.view["plan"]["markdown"] += " changed after display"
        before = self.journal_state()
        status, reply = self.post(body)
        self.assertEqual(
            (status, reply["error"]), (409, "stage3-decision-version-differs")
        )
        self.assertEqual(self.journal_state(), before)

    def test_no_saved_plan_or_no_connection_is_refused(self):
        saved_job = self.view["job"]
        self.view["job"] = {}
        before = self.journal_state()
        status, reply = self.post(self.decision())
        self.assertEqual(
            (status, reply["error"]), (409, "stage3-decision-saved-plan-required")
        )
        self.assertEqual(self.journal_state(), before)
        self.view["job"] = saved_job
        self.service.bindings.clear()
        status, reply = self.post(self.decision())
        self.assertEqual((status, reply["error"]), (409, "stage3-planning-unconnected"))

    def test_accept_needs_a_complete_plan_but_the_other_two_do_not(self):
        self.view["plan"]["question_plans"][0]["validation"] = ""
        self.rebind()
        before = self.journal_state()
        status, reply = self.post(self.decision())
        self.assertEqual(
            (status, reply["error"]), (409, "stage3-decision-plan-not-ready")
        )
        self.assertEqual(self.journal_state(), before)  # refused before any write
        status, reply = self.post(
            self.decision("d-2", "revise-then-review", "Fix it first.")
        )
        self.assertEqual(status, 200, reply)
        self.assertIs(reply["record"]["stage2_selection_change_required"], False)
        status, reply = self.post(
            self.decision("d-3", "return-to-stage2", "Wrong direction.")
        )
        self.assertEqual(status, 200, reply)
        self.assertIs(reply["record"]["stage2_selection_change_required"], True)
        self.assertNotIn("accept_condition", reply["record"])

    def test_bad_shapes_are_refused_before_any_write(self):
        before = self.journal_state()
        good = self.decision()
        for label, body, code in (
            ("extra field", dict(good, extra=1), None),
            (
                "not confirmed",
                dict(good, confirmed=False),
                "explicit-stage3-decision-required",
            ),
            (
                "unknown decision",
                dict(good, decision="approve"),
                "stage3-decision-invalid",
            ),
            ("empty text", dict(good, text="  "), "stage3-decision-text-required"),
            (
                "text too long",
                dict(good, text="x" * 2100),
                "stage3-decision-text-too-long",
            ),
            ("missing key", {k: v for k, v in good.items() if k != "key"}, None),
        ):
            with self.subTest(label):
                status, reply = self.post(body)
                self.assertEqual(status, 400, reply)
                if code:
                    self.assertEqual(reply["error"], code)
        self.assertEqual(self.journal_state(), before)

    def test_credentials_and_origin_are_checked(self):
        before = self.journal_state()
        status, _ = self.post(self.decision(), credential="wrong")
        self.assertEqual(status, 401)
        handler = Handler(self.transport, "decide", self.decision())
        handler.path = "/api/projects/authored-ref/stage3/planning/decide"
        handler.headers["Sec-Fetch-Site"] = "cross-site"
        handle_planning(handler, "POST")
        self.assertEqual(handler.replies[0][0], 403)
        self.assertEqual(self.journal_state(), before)

    def test_a_get_to_the_decide_route_is_not_a_decision(self):
        handler = Handler(self.transport, "decide", None)
        handler.path = "/api/projects/authored-ref/stage3/planning/decide"
        handler.length = 0
        handle_planning(handler, "GET")
        self.assertEqual(handler.replies[0][0], 400)
        self.assertEqual(self.journal_state()["intents"], {})


if __name__ == "__main__":
    unittest.main()
