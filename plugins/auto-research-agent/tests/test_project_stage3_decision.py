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

        self.view["job"]["planning_status"] = "draft"
        self.view["plan"]["planning_status"] = "draft"
        self.rebind()
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
        body = dict(self.request(key), decision=decision, text=text, confirmed=True)
        body["plan_revision_receipt_sha256"] = self.revision_receipt()
        return body

    def revision_receipt(self):
        from research_workspace_native.project_stage3_decision import _binding

        try:
            return _binding(self.jobs, "authored-ref", self.view)[1][
                "plan_revision_receipt_sha256"
            ]
        except SessionApiError:  # no saved plan: the host refuses before binding
            return None

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
            record["accept_condition"],
            "job-planning-status-draft-or-ready+plan-planning-status-present-and-not-needs-information+every-question-plan-has-all-content-fields",
        )
        self.assertFalse(reply["replayed"])
        before = self.journal_state()
        view = self.transport.view("own", "authored-ref")
        self.assertEqual(
            view["host_decision"]["latest"]["receipt_sha256"], reply["receipt_sha256"]
        )
        self.assertEqual(view["plan"], self.view["plan"])
        self.assertEqual(self.journal_state(), before)  # reading writes nothing

    def test_latest_is_the_last_written_not_the_last_by_hash_order(self):
        sent = []
        for index, kind in enumerate(
            (
                "accept",
                "return-to-stage2",
                "revise-then-review",
                "accept",
                "return-to-stage2",
                "accept",
            )
        ):
            key = "k-" + str(index)
            status, reply = self.post(self.decision(key, kind, "text " + key))
            self.assertEqual(status, 200, reply)
            self.assertEqual(reply["record"]["sequence"], index + 1)
            sent.append(key)
        view = self.transport.view("own", "authored-ref")["host_decision"]
        self.assertEqual([r["record"]["request"]["key"] for r in view["records"]], sent)
        self.assertEqual(view["latest"]["record"]["request"]["key"], sent[-1])
        self.assertEqual(view["latest"]["record"]["decision"], "accept")

    def test_manual_revision_moves_old_decisions_to_history_and_binds_new_ones(self):
        status, first = self.post(self.decision("before-revision"))
        self.assertEqual(status, 200, first)
        comment = self.comment()
        revision = self.revision(comment)
        view = self.transport.view("own", "authored-ref")["host_decision"]
        self.assertTrue(view["has_manual_revision"])
        self.assertEqual(view["records"], [])
        self.assertIsNone(view["latest"])
        self.assertEqual(len(view["history"]), 1)
        self.assertTrue(view["history"][0]["superseded_by_manual_revision"])
        # the old decision body no longer matches the displayed version
        before = self.journal_state()
        status, reply = self.post(
            dict(self.decision("before-revision"), plan_revision_receipt_sha256=None)
        )
        self.assertEqual(
            (status, reply["error"]), (409, "stage3-decision-version-differs")
        )
        self.assertEqual(self.journal_state(), before)
        # a decision on the revised draft is possible and becomes the current one
        status, second = self.post(self.decision("after-revision"))
        self.assertEqual(status, 200, second)
        self.assertEqual(
            second["record"]["binding"]["plan_revision_receipt_sha256"],
            revision["receipt_sha256"],
        )
        view = self.transport.view("own", "authored-ref")["host_decision"]
        self.assertEqual(view["latest"]["receipt_sha256"], second["receipt_sha256"])
        self.assertEqual(
            [r["receipt_sha256"] for r in view["history"]], [first["receipt_sha256"]]
        )

    def test_two_parallel_revisions_make_the_binding_ambiguous_and_refuse(self):
        first = self.comment("c1", "one")
        self.revision(first, key="rev-a")
        second = self.comment("c2", "two")
        self.revision(second, key="rev-b")  # also v2: both written from the original
        view = self.transport.view("own", "authored-ref")["host_decision"]
        self.assertTrue(view["revision_ambiguous"])
        self.assertTrue(view["has_manual_revision"])
        self.assertEqual((view["records"], view["latest"]), ([], None))
        before = self.journal_state()
        status, reply = self.post(self.decision("amb"))
        self.assertEqual(
            (status, reply["error"]), (409, "stage3-decision-revision-ambiguous")
        )
        self.assertEqual(self.journal_state(), before)

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

    def test_accept_refuses_a_plan_the_saved_review_says_needs_information(self):
        self.view["job"]["planning_status"] = "needs-information"
        before = self.journal_state()
        status, reply = self.post(self.decision())
        self.assertEqual(
            (status, reply["error"]), (409, "stage3-decision-plan-not-ready")
        )
        self.assertEqual(self.journal_state(), before)
        self.view["job"]["planning_status"] = "draft"
        status, reply = self.post(self.decision())
        self.assertEqual(status, 200, reply)
        self.assertEqual(
            reply["record"]["accept_condition"],
            "job-planning-status-draft-or-ready+plan-planning-status-present-and-not-needs-information+every-question-plan-has-all-content-fields",
        )
        # intent-only decisions are never gated by the review status
        self.view["job"]["planning_status"] = "needs-information"
        status, reply = self.post(self.decision("d-2", "revise-then-review", "More."))
        self.assertEqual(status, 200, reply)

    def test_plan_that_says_it_needs_information_cannot_be_accepted(self):
        self.view["plan"]["planning_status"] = "needs-information"
        self.rebind()
        status, reply = self.post(self.decision())
        self.assertEqual(
            (status, reply["error"]), (409, "stage3-decision-plan-not-ready")
        )

    def test_full_plan_accept_branch_uses_check_plan(self):
        from unittest.mock import patch

        self.view["plan"] = dict(self.view["plan"], kind="Stage3PlanningResult")
        self.rebind()
        for check, expected in (
            ({"structural_valid": True, "blocked_questions": []}, 200),
            ({"structural_valid": True, "blocked_questions": ["q1"]}, 409),
            ({"structural_valid": False, "blocked_questions": []}, 409),
        ):
            with self.subTest(check=check):
                with patch(
                    "research_workspace_native.project_stage3_decision.check_plan",
                    return_value=check,
                ):
                    status, reply = self.post(
                        self.decision(
                            "full-"
                            + str(expected)
                            + str(len(check["blocked_questions"]))
                            + str(check["structural_valid"])
                        )
                    )
                self.assertEqual(status, expected, reply)
                if expected == 200:
                    self.assertEqual(
                        reply["record"]["accept_condition"],
                        "job-planning-status-draft-or-ready+structurally-valid-with-no-blocked-question",
                    )

    def test_accept_is_refused_when_the_saved_status_is_missing(self):
        before = self.journal_state()
        for label, mutate in (
            ("job status", lambda: self.view["job"].pop("planning_status")),
            ("plan status", lambda: self.view["plan"].pop("planning_status")),
        ):
            with self.subTest(label):
                mutate()
                self.rebind()
                status, reply = self.post(
                    self.decision("missing-" + label.replace(" ", "-"))
                )
                self.assertEqual(
                    (status, reply["error"]),
                    (409, "stage3-decision-planning-status-missing"),
                )
                self.assertEqual(self.journal_state(), before)
                self.view["job"]["planning_status"] = "draft"
                self.view["plan"]["planning_status"] = "draft"
                self.rebind()
        # intent-only decisions do not need it
        self.view["job"].pop("planning_status")
        status, reply = self.post(self.decision("intent", "revise-then-review", "x"))
        self.assertEqual(status, 200, reply)

    def test_ready_for_plan_review_and_unknown_job_statuses(self):
        for key, value, expected in (
            ("ready", "ready-for-plan-review", 200),
            ("failed", "failed", 409),
            ("odd", "something-new", 409),
        ):
            with self.subTest(value):
                self.view["job"]["planning_status"] = value
                status, reply = self.post(self.decision(key))
                self.assertEqual(status, expected, reply)

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
            ("text not a string", dict(good, text=5), "stage3-decision-text-invalid"),
            ("missing key", {k: v for k, v in good.items() if k != "key"}, None),
        ):
            with self.subTest(label):
                status, reply = self.post(body)
                self.assertEqual(status, 400, reply)
                if code:
                    self.assertEqual(reply["error"], code)
        self.assertEqual(self.journal_state(), before)

    def test_reason_is_optional_and_limited_to_4096_utf8_bytes(self):
        status, reply = self.post(self.decision("empty", "accept", ""))
        self.assertEqual(status, 200, reply)
        self.assertEqual(reply["record"]["text"], "")
        edge = "資" * 1365  # 4095 bytes
        status, reply = self.post(self.decision("edge", "revise-then-review", edge))
        self.assertEqual(status, 200, reply)
        before = self.journal_state()
        for key, text in (("long-ascii", "x" * 4097), ("long-cjk", "資" * 1366)):
            status, reply = self.post(self.decision(key, "revise-then-review", text))
            self.assertEqual(
                (status, reply["error"]), (413, "stage3-decision-text-too-long")
            )
        self.assertEqual(self.journal_state(), before)
        # confirmed:true stays mandatory even with an empty reason
        status, reply = self.post(
            dict(self.decision("c", "accept", ""), confirmed=False)
        )
        self.assertEqual(
            (status, reply["error"]), (400, "explicit-stage3-decision-required")
        )

    def test_malformed_requests_are_refused_before_the_lease_is_taken(self):
        calls = []

        class Bindings(dict):
            def for_write(self, ref):
                calls.append(ref)
                return self.get(ref)

        self.service.bindings = Bindings({"authored-ref": {"jobs": self.jobs}})
        good = self.decision()
        for body in (
            dict(good, extra=1),
            dict(good, confirmed=False),
            dict(good, decision="approve"),
            dict(good, text="x" * 5000),
            {k: v for k, v in good.items() if k != "key"},
        ):
            status, _ = self.post(body)
            self.assertGreaterEqual(status, 400)
        self.assertEqual(calls, [])
        self.assertEqual(self.post(good)[0], 200)
        self.assertEqual(calls, ["authored-ref"])

    def concurrent(self, bodies):
        results = []
        threads = [
            threading.Thread(target=lambda b=b: results.append(self.post(b)))
            for b in bodies
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(len(results), len(bodies))
        for status, reply in results:
            self.assertIn(status, (200, 409), reply)
            if status == 409:
                self.assertEqual(reply["error"], "stage3-planning-project-busy")
        view = self.transport.view("own", "authored-ref")["host_decision"]
        return results, view

    def test_concurrent_decisions_with_different_keys_never_share_a_sequence(self):
        results, view = self.concurrent(
            [
                self.decision("a", "accept", "A"),
                self.decision("b", "return-to-stage2", "B"),
            ]
        )
        successes = sum(1 for status, _ in results if status == 200)
        self.assertGreaterEqual(successes, 1)
        sequences = [r["record"]["sequence"] for r in view["records"]]
        self.assertEqual(sequences, list(range(1, successes + 1)))

    def test_concurrent_decisions_with_the_same_key_record_once(self):
        results, view = self.concurrent(
            [
                self.decision("same", "accept", "S"),
                self.decision("same", "accept", "S"),
            ]
        )
        self.assertGreaterEqual(sum(1 for status, _ in results if status == 200), 1)
        self.assertEqual(len(view["records"]), 1)

    def test_view_says_so_when_the_decision_does_not_fit_the_response(self):
        from unittest.mock import patch

        real = __import__(
            "research_workspace_native.project_stage3_http", fromlist=["fits_response"]
        ).fits_response
        self.post(self.decision())
        with patch(
            "research_workspace_native.project_stage3_http.fits_response",
            side_effect=lambda value: (
                (
                    "host_decision" not in value
                    or value["host_decision"].get("omitted") == "response-bound"
                )
                and real(value)
            ),
        ):
            view = self.transport.view("own", "authored-ref")
        self.assertEqual(
            view["host_decision"],
            {
                "omitted": "response-bound",
                "count": 1,
                "latest_decision": "accept",
                "latest_sequence": 1,
            },
        )

    def test_a_stale_snapshot_cannot_reuse_a_sequence(self):
        from unittest.mock import patch

        from research_workspace_native import project_stage3_decision as module

        self.post(self.decision("one"))
        journal = self.jobs.journal
        real = journal.record_intent
        state = {"done": False}

        def racing(*args, **kwargs):
            if not state["done"]:
                state["done"] = True
                # another writer appends between our snapshot and our append
                real(
                    self.jobs.project_id,
                    self.jobs.owner,
                    "intruder",
                    "stage3/other",
                    {"x": 1},
                    expected_revision=journal.snapshot(self.jobs.project_id)[
                        "revision"
                    ],
                )
            return real(*args, **kwargs)

        with patch.object(journal, "record_intent", racing):
            with self.assertRaises(Exception):
                module.record_decision(
                    self.jobs,
                    "authored-ref",
                    self.view,
                    self.decision("two", "return-to-stage2", "late"),
                )
        view = self.transport.view("own", "authored-ref")["host_decision"]
        self.assertEqual([r["record"]["sequence"] for r in view["records"]], [1])

    def test_a_damaged_decision_log_does_not_take_the_plan_view_down(self):
        from unittest.mock import patch

        with patch(
            "research_workspace_native.project_stage3_http.read_decisions",
            side_effect=SessionApiError("stage3-decision-record-differs", 409),
        ):
            view = self.transport.view("own", "authored-ref")
        self.assertEqual(
            view["host_decision"], {"error": "stage3-decision-record-differs"}
        )
        self.assertEqual(view["plan"], self.view["plan"])

    def test_body_limit_is_32768_bytes_and_fits_the_worst_escaped_reason(self):
        worst = "" * 4096  # JSON-escapes to six bytes each: 24576 bytes
        status, reply = self.post(self.decision("worst", "revise-then-review", worst))
        self.assertEqual(status, 200, reply)
        before = self.journal_state()
        body = dict(
            self.decision("huge", "revise-then-review", ""), padding="x" * 33000
        )
        status, reply = self.post(body)
        self.assertEqual(
            (status, reply["error"]), (413, "stage3-planning-body-bound-exceeded")
        )
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
