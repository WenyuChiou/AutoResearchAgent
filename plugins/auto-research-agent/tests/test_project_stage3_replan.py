"""Replan from a manual revision on the real selected source; stub planner only.

Reuses the authored Stage 2 selection fixture of ``test_project_stage3_planning``
(without re-running its tests). The planning adapter is a fixed Mock; native
planner and process calls are forbidden.
"""

# ruff: noqa: E402 -- exercise the CLI and existing authored package fixtures.
from pathlib import Path
import sys
import unittest

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / "cli"),
    str(Path(__file__).resolve().parent),
]
import test_project_stage3_planning as base
from research_workspace_native.project_stage3_http import ProjectStage3Http
from research_workspace_native.project_stage3_replan import MODE, replan_key
from research_workspace_native.session_api import SessionApiError
from stage3_plan.contracts import canonical_bytes, digest
from stage3_plan.prompts import REVISION_INSTRUCTION


class ReplanFixture:
    setUpClass = classmethod(base.ProjectStage3PlanningTests.setUpClass.__func__)
    service = base.ProjectStage3PlanningTests.service
    body = base.ProjectStage3PlanningTests.body
    prepared = base.ProjectStage3PlanningTests.prepared

    def setUp(self):
        base.ProjectStage3PlanningTests.setUp(self)
        self.ref = self.f.ref
        self.http = ProjectStage3Http(self.bridge)
        self.addCleanup(self.http.close)
        self.key = self.http.view("own", self.ref)["default_request"]["key"]
        self.original = self.respond(self.key)
        self.default_body = self.prepared()
        saved = self.bridge.run(
            "own", self.ref, dict(self.default_body, confirmed=True)
        )
        self.assertEqual(saved["outcome"], "saved", saved)
        self.assertEqual(self.callback.call_count, 1)
        self.question = self.original["question_plans"][0]["question_ref"]

    # -- helpers -------------------------------------------------------------
    def respond(self, key, marker=None):
        plan = base.authored_plan(
            self.admitted,
            self.selection["planning_manifest_sha256"],
            "host-plan-" + digest(key),
        )
        if marker:
            plan["question_plans"][0]["minimum_deliverable"] = marker
        self.callback.return_value = dict(
            raw_response=canonical_bytes(plan), provenance={"kind": "authored-test"}
        )
        return plan

    def view(self):
        return self.http.view("own", self.ref)

    def feedback_binding(self):
        return {
            k: v
            for k, v in self.view()["feedback"]["binding"].items()
            if k != "project_ref"
        }

    def comment(self, key="c1", text="COMMENT-MARKER keep access unknown."):
        body = dict(
            self.feedback_binding(), key=key, text=text, question_ref=self.question
        )
        return self.http.feedback("own", self.ref, body, "comment")

    def revise(
        self, comment, key="r1", value="REVISED-MARKER bounded deliverable", parent=None
    ):
        body = dict(
            self.feedback_binding(),
            key=key,
            comments=[
                {
                    "key": comment["record"]["request"]["key"],
                    "sha256": comment["receipt_sha256"],
                }
            ],
            parent_revision=parent
            and {
                "key": parent["record"]["request"]["key"],
                "sha256": parent["receipt_sha256"],
            },
            changes=[
                {
                    "question_ref": self.question,
                    "field": "minimum_deliverable",
                    "value": value,
                }
            ],
        )
        return self.http.feedback("own", self.ref, body, "revise")

    def decide(self, key="d1", decision="revise-then-review"):
        view = self.view()
        body = dict(
            {
                k: v
                for k, v in view["host_decision"]["binding"].items()
                if k != "project_ref"
            },
            key=key,
            decision=decision,
            text="Please replan from my revision.",
            confirmed=True,
        )
        return self.http.decide("own", self.ref, body)

    def replan_body(self, decision, revision, **changes):
        project = self.body()
        project.pop("key")
        decision_sha = (
            decision if isinstance(decision, str) else decision["receipt_sha256"]
        )
        revision_sha = (
            revision if isinstance(revision, str) else revision["receipt_sha256"]
        )
        return dict(
            project,
            mode=MODE,
            key=replan_key(self.key, decision_sha, revision_sha),
            decision_receipt_sha256=decision_sha,
            plan_revision_receipt_sha256=revision_sha,
            **changes,
        )

    def revised_and_decided(self):
        comment = self.comment()
        revision = self.revise(comment)
        decision = self.decide()
        return comment, revision, decision

    def state(self):
        return (
            self.journal.snapshot(self.jobs.project_id),
            sorted(p.name for p in self.jobs.root.iterdir()),
        )

    def item_for(self, key):
        return self.journal.snapshot(self.jobs.project_id)["intents"].get(
            self.jobs._key(key)
        )

    def assert_refused(self, call, code, status=None):
        before = self.state()
        calls = self.callback.call_count
        with self.assertRaises(SessionApiError) as error:
            call()
        self.assertEqual(error.exception.code, code)
        if status is not None:
            self.assertEqual(error.exception.status, status)
        self.assertEqual(self.state(), before)  # nothing was written
        self.assertEqual(self.callback.call_count, calls)


class ReplanHostTests(ReplanFixture, unittest.TestCase):
    def test_prepare_and_run_plan_once_from_the_revision(self):
        _, revision, decision = self.revised_and_decided()
        body = self.replan_body(decision, revision)
        prepared = self.http.replan.prepare("own", self.ref, body)
        self.assertEqual(prepared["status"], "intent-recorded")
        self.assertEqual(self.callback.call_count, 1)  # prepare makes no call
        payload = self.item_for(body["key"])["payload"]
        self.assertEqual(payload["schema_version"], "1.1.0")
        self.assertEqual(self.item_for(self.key)["payload"]["schema_version"], "1.0.0")
        frozen = payload["revision_input"]
        self.assertEqual(
            frozen["plan_revision_receipt_sha256"], revision["receipt_sha256"]
        )
        self.assertEqual(frozen["decision_receipt_sha256"], decision["receipt_sha256"])
        self.assertEqual(frozen["plan"], revision["record"]["plan"])
        self.assertEqual(
            frozen["comments"],
            [
                {
                    "question_ref": self.question,
                    "text": "COMMENT-MARKER keep access unknown.",
                }
            ],
        )
        self.assertEqual(
            frozen["parent_request_sha256"], self.default_body["request_sha256"]
        )
        model_text = self.original["question_plans"][0]["minimum_deliverable"]
        self.assertEqual(
            frozen["changes"],
            [
                {
                    "question_ref": self.question,
                    "field": "minimum_deliverable",
                    "model_value": model_text,
                    "researcher_value": "REVISED-MARKER bounded deliverable",
                }
            ],
        )
        # same key replays the same job
        self.assertEqual(self.http.replan.prepare("own", self.ref, body), prepared)

        new_plan = self.respond(body["key"], marker="NEW-PLAN-MARKER")
        run_body = dict(body, request_sha256=prepared["request_sha256"], confirmed=True)
        result = self.http.replan.run("own", self.ref, run_body)
        self.assertEqual(result["outcome"], "saved", result)
        self.assertEqual(self.callback.call_count, 2)
        prompt = self.callback.call_args.kwargs["prompt"]
        self.assertIn(REVISION_INSTRUCTION, prompt)
        self.assertIn("REVISED-MARKER bounded deliverable", prompt)
        self.assertIn("COMMENT-MARKER keep access unknown.", prompt)
        self.assertIn('"researcher_value":"REVISED-MARKER bounded deliverable"', prompt)
        self.assertIn('"model_value":' + base.json.dumps(model_text), prompt)
        self.assertNotIn("NEW-PLAN-MARKER", prompt)
        # replays never call again
        self.assertEqual(self.http.replan.run("own", self.ref, run_body), result)
        inspect_body = dict(body, request_sha256=prepared["request_sha256"])
        self.assertEqual(
            self.http.replan.inspect("own", self.ref, inspect_body), result
        )
        self.assertEqual(self.http.replan.prepare("own", self.ref, body), result)
        self.assertEqual(self.callback.call_count, 2)
        output = Path(self.item_for(body["key"])["payload"]["output"]) / "plan"
        self.assertEqual(
            base.read_json(output / "request.json")["revision_input"], frozen
        )
        self.assertEqual(base.read_json(output / "plan.json"), new_plan)

    def test_prepare_refusals_happen_before_any_write(self):
        prepare = self.http.replan.prepare
        fake = "e" * 64
        self.assert_refused(
            lambda: prepare("own", self.ref, self.replan_body(fake, fake)),
            "stage3-replan-revision-required",
            409,
        )
        comment = self.comment()
        first = self.revise(comment)
        self.assert_refused(
            lambda: prepare("own", self.ref, self.replan_body(fake, first)),
            "stage3-replan-decision-required",
            409,
        )
        other = self.decide("d-return", "return-to-stage2")
        self.assert_refused(
            lambda: prepare("own", self.ref, self.replan_body(other, first)),
            "stage3-replan-decision-required",
            409,
        )
        old_decision = self.decide("d-first")
        second = self.revise(comment, key="r2", value="SECOND revision", parent=first)
        self.assert_refused(
            lambda: prepare("own", self.ref, self.replan_body(old_decision, first)),
            "stage3-replan-revision-changed",
            409,
        )
        self.assert_refused(
            lambda: prepare("own", self.ref, self.replan_body(old_decision, second)),
            "stage3-replan-decision-differs",
            409,
        )
        good = self.replan_body(self.decide("d-second"), second)
        for bad, code in (
            (dict(good, key="stage3-replan-forged"), "stage3-replan-key-differs"),
            (dict(good, mode="direction-intent-ish"), "stage3-replan-mode-invalid"),
            (
                dict(good, decision_receipt_sha256="nope"),
                "stage3-replan-receipt-invalid",
            ),
        ):
            with self.subTest(code=code):
                self.assert_refused(lambda: prepare("own", self.ref, bad), code, 400)
        for field, value in (("revision", True), ("selection_request_sha256", fake)):
            with self.subTest(field=field), self.assertRaises(SessionApiError):
                prepare("own", self.ref, dict(good, **{field: value}))
        with self.assertRaises(SessionApiError):
            prepare("own", self.ref, dict(good, execution_authorized=True))
        big = self.revise(comment, key="r3", value="x" * 60000, parent=second)
        too_large = self.replan_body(self.decide("d-big"), big)
        self.assert_refused(
            lambda: prepare("own", self.ref, too_large),
            "stage3-replan-input-too-large",
            413,
        )
        self.revise(comment, key="r3-tie", value="A tie with r3", parent=second)
        self.assert_refused(
            lambda: prepare("own", self.ref, self.replan_body(fake, big)),
            "stage3-decision-revision-ambiguous",
            409,
        )
        self.assertIsNone(self.item_for(good["key"]))
        self.assertEqual(self.callback.call_count, 1)

    def test_revision_changed_after_prepare_blocks_run_without_a_call(self):
        comment, revision, decision = self.revised_and_decided()
        body = self.replan_body(decision, revision)
        prepared = self.http.replan.prepare("own", self.ref, body)
        self.revise(
            comment, key="r-later", value="Changed after prepare", parent=revision
        )
        self.respond(body["key"])
        run_body = dict(body, request_sha256=prepared["request_sha256"], confirmed=True)
        self.assert_refused(
            lambda: self.http.replan.run("own", self.ref, run_body),
            "stage3-replan-revision-changed",
            409,
        )
        self.assertEqual(self.item_for(body["key"])["status"], "intent-recorded")
        self.assertEqual(self.callback.call_count, 1)

    def test_replan_job_cannot_be_dispatched_without_the_replan_check(self):
        _, revision, decision = self.revised_and_decided()
        body = self.replan_body(decision, revision)
        prepared = self.http.replan.prepare("own", self.ref, body)
        plain = {
            name: body[name]
            for name in (
                "key",
                "revision",
                "input_version",
                "brief_sha256",
                "selection_request_sha256",
            )
        }
        self.assert_refused(
            lambda: self.bridge.run(
                "own",
                self.ref,
                dict(plain, request_sha256=prepared["request_sha256"], confirmed=True),
            ),
            "stage3-replan-mode-required",
            409,
        )
        # read-only inspection without the mode is still allowed
        read = self.bridge.inspect(
            "own", self.ref, dict(plain, request_sha256=prepared["request_sha256"])
        )
        self.assertEqual(read["status"], "intent-recorded")


class ReplanLatestDecisionTests(ReplanFixture, unittest.TestCase):
    """Only the latest decision (by server sequence) on the displayed revision counts."""

    def accept(self, key):
        from unittest.mock import patch

        # The authored fixture plan is needs-information, so the real accept gate
        # would refuse; only that readiness gate is substituted, the record is real.
        with patch(
            "research_workspace_native.project_stage3_decision.accept_condition",
            return_value=(True, "fixture-accept", None),
        ):
            return self.decide(key, "accept")

    def test_later_accept_or_return_supersedes_revise_before_prepare(self):
        _, revision, decision = self.revised_and_decided()
        body = self.replan_body(decision, revision)
        for key, later in (("d-accept", self.accept), ("d-return", None)):
            with self.subTest(later=key):
                if later is None:
                    self.decide(key, "return-to-stage2")
                else:
                    later(key)
                self.assert_refused(
                    lambda: self.http.replan.prepare("own", self.ref, body),
                    "stage3-replan-decision-superseded",
                    409,
                )
                replan = self.view()["replan"]
                self.assertEqual(
                    (replan["available"], replan["reason"]),
                    (False, "stage3-replan-decision-superseded"),
                )
                self.assertIsNone(replan["from_decision_receipt_sha256"])
        # choosing revise-then-review again makes it possible, with the new receipt
        again = self.decide("d-again")
        replan = self.view()["replan"]
        self.assertTrue(replan["available"])
        self.assertEqual(replan["request"], self.replan_body(again, revision))
        prepared = self.http.replan.prepare("own", self.ref, replan["request"])
        self.assertEqual(prepared["status"], "intent-recorded")
        self.assertEqual(self.callback.call_count, 1)

    def test_accept_after_prepare_blocks_run_without_a_call_until_revise_again(self):
        _, revision, decision = self.revised_and_decided()
        body = self.replan_body(decision, revision)
        prepared = self.http.replan.prepare("own", self.ref, body)
        self.accept("d-accept")
        self.respond(body["key"])
        run_body = dict(body, request_sha256=prepared["request_sha256"], confirmed=True)
        self.assert_refused(
            lambda: self.http.replan.run("own", self.ref, run_body),
            "stage3-replan-decision-superseded",
            409,
        )
        self.assert_refused(
            lambda: self.http.admit_run("own", self.ref, run_body, None),
            "stage3-replan-decision-superseded",
            409,
        )
        self.assertEqual(self.item_for(body["key"])["status"], "intent-recorded")
        self.assertEqual(self.callback.call_count, 1)
        # A later revise-then-review is a new decision: the old job stays refused
        # and the page's template moves to a new key that needs its own prepare.
        again = self.decide("d-again")
        self.assert_refused(
            lambda: self.http.replan.run("own", self.ref, run_body),
            "stage3-replan-decision-superseded",
            409,
        )
        request = self.view()["replan"]["request"]
        self.assertEqual(request, self.replan_body(again, revision))
        self.assertNotEqual(request["key"], body["key"])
        fresh = self.http.replan.prepare("own", self.ref, request)
        self.respond(request["key"])
        result = self.http.replan.run(
            "own",
            self.ref,
            dict(request, request_sha256=fresh["request_sha256"], confirmed=True),
        )
        self.assertEqual(result["outcome"], "saved", result)
        self.assertEqual(self.callback.call_count, 2)


class ReplanReviewFixTests(ReplanFixture, unittest.TestCase):
    """Fixes from the 2026-11-27 independent review."""

    def test_chained_revision_sends_net_edits_relative_to_the_model_plan(self):
        comment = self.comment()
        first = self.revise(comment, value="FIRST edit")
        second = self.revise(comment, key="r2", value="SECOND edit", parent=first)
        decision = self.decide()
        body = self.replan_body(decision, second)
        self.http.replan.prepare("own", self.ref, body)
        frozen = self.item_for(body["key"])["payload"]["revision_input"]
        self.assertEqual(
            frozen["changes"],
            [
                {
                    "question_ref": self.question,
                    "field": "minimum_deliverable",
                    "model_value": self.original["question_plans"][0][
                        "minimum_deliverable"
                    ],
                    "researcher_value": "SECOND edit",
                }
            ],
        )

    def test_plain_prepare_cannot_occupy_a_replan_key(self):
        body = dict(self.body(), key="stage3-replan-" + "0" * 64)
        self.assert_refused(
            lambda: self.bridge.prepare("own", self.ref, body),
            "stage3-replan-key-reserved",
            400,
        )

    def test_direct_service_run_rechecks_inside_the_callback_before_the_model(self):
        from unittest.mock import patch
        from research_workspace_native.project_stage3_replan import (
            ProjectStage3Replan,
        )

        _, revision, decision = self.revised_and_decided()
        body = self.replan_body(decision, revision)
        prepared = self.http.replan.prepare("own", self.ref, body)
        self.respond(body["key"])
        original = ProjectStage3Replan.check_current
        calls = []

        def second_fails(replan, *args, **kwargs):
            calls.append(1)
            if len(calls) == 2:  # a change slipped in after the first check
                raise SessionApiError("stage3-replan-revision-changed", 409)
            return original(replan, *args, **kwargs)

        with patch.object(ProjectStage3Replan, "check_current", second_fails):
            result = self.http.replan.run(
                "own",
                self.ref,
                dict(body, request_sha256=prepared["request_sha256"], confirmed=True),
            )
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.callback.call_count, 1)  # the adapter was never called
        self.assertNotEqual(result["outcome"], "saved")

    def test_unreadable_new_plan_is_marked_and_writes_keep_working(self):
        from unittest.mock import patch
        from stage3_plan.jobs import _runtime

        _, revision, decision = self.revised_and_decided()
        body = self.replan_body(decision, revision)
        prepared = self.http.replan.prepare("own", self.ref, body)
        self.respond(body["key"], marker="NEW-PLAN")
        self.http.replan.run(
            "own",
            self.ref,
            dict(body, request_sha256=prepared["request_sha256"], confirmed=True),
        )
        # After a Core upgrade only the first job has a trusted pin.
        identity = (self.ref, self.key, self.default_body["request_sha256"])
        pin = self.item_for(self.key)["evidence"]["plan"]["manifest_sha256"]
        self.http.recovery_pins[identity] = self.bridge.saved_read_pins[identity] = pin
        upgraded = _runtime()
        upgraded["stage3_sources"]["jobs.py"] = "b" * 64
        with (
            patch("stage3_plan.jobs._runtime", return_value=upgraded),
            patch("stage3_plan.planner._producer_sha256", return_value="c" * 64),
        ):
            view = self.view()
            self.assertEqual(view["plan"], self.original)
            self.assertEqual(
                view["unreadable_plans"],
                [
                    {
                        "key": body["key"],
                        "request_sha256": prepared["request_sha256"],
                        "error": "stage3-replan-plan-unreadable",
                        "parent_request_sha256": self.default_body["request_sha256"],
                        "from_revision_receipt_sha256": revision["receipt_sha256"],
                        "from_decision_receipt_sha256": decision["receipt_sha256"],
                    }
                ],
            )
            self.assertEqual(
                (view["replan"]["available"], view["replan"]["reason"]),
                (False, "stage3-replan-plan-unreadable"),
            )
            self.assertEqual(len(view["feedback"]["records"]), 2)
            comment = self.comment(key="c-after", text="Still writable.")
            self.revise(
                comment, key="r-after", value="Still revisable", parent=revision
            )
            decided = self.decide(key="d-after")
            self.assertEqual(decided["record"]["decision"], "revise-then-review")
            self.assertRaises(
                SessionApiError,
                self.http.replan.prepare,
                "own",
                self.ref,
                self.replan_body(
                    decided,
                    self.view()["host_decision"]["binding"][
                        "plan_revision_receipt_sha256"
                    ],
                ),
            )
        self.assertEqual(self.callback.call_count, 2)


class ReplanViewTests(ReplanFixture, unittest.TestCase):
    def run_replan(self):
        comment, revision, decision = self.revised_and_decided()
        template = self.view()["replan"]
        body = self.replan_body(decision, revision)
        self.assertEqual(template["request"], body)
        prepared = self.http.replan.prepare("own", self.ref, body)
        new_plan = self.respond(body["key"], marker="NEW-PLAN-MARKER")
        result = self.http.replan.run(
            "own",
            self.ref,
            dict(body, request_sha256=prepared["request_sha256"], confirmed=True),
        )
        self.assertEqual(result["outcome"], "saved", result)
        return comment, revision, decision, body, prepared, new_plan

    def test_view_without_revision_has_no_replan_fields(self):
        view = self.view()
        self.assertNotIn("replan", view)
        self.assertNotIn("previous_plans", view)
        self.assertEqual(view["plan"], self.original)

    def test_template_follows_revision_decision_and_job_state(self):
        comment = self.comment()
        revision = self.revise(comment)
        replan = self.view()["replan"]
        self.assertEqual(
            (replan["available"], replan["reason"]),
            (False, "stage3-replan-decision-required"),
        )
        self.assertEqual(
            replan["from_revision_receipt_sha256"], revision["receipt_sha256"]
        )
        self.assertEqual(
            replan["parent_plan_manifest_sha256"],
            self.view()["job"]["plan_manifest_sha256"],
        )
        decision = self.decide()
        view = self.view()
        replan = view["replan"]
        self.assertTrue(replan["available"])
        self.assertIsNone(replan["reason"])
        self.assertIsNone(replan["job"])
        self.assertEqual(
            replan["from_decision_receipt_sha256"], decision["receipt_sha256"]
        )
        prepared = self.http.replan.prepare("own", self.ref, replan["request"])
        view = self.view()
        self.assertEqual(view["replan"]["job"], prepared)
        self.assertEqual(
            view["replan"]["request"]["request_sha256"], prepared["request_sha256"]
        )
        self.assertEqual(view["plan"], self.original)  # in progress: still the parent
        self.assertNotIn("previous_plans", view)

    def test_failed_replan_keeps_the_parent_displayed_and_is_not_resent(self):
        _, revision, decision = self.revised_and_decided()
        body = self.replan_body(decision, revision)
        prepared = self.http.replan.prepare("own", self.ref, body)
        self.callback.side_effect = RuntimeError("authored adapter failure")
        run_body = dict(body, request_sha256=prepared["request_sha256"], confirmed=True)
        failed = self.http.replan.run("own", self.ref, run_body)
        self.assertEqual(failed["status"], "execution-unknown", failed)
        self.assertEqual(self.http.replan.run("own", self.ref, run_body), failed)
        self.assertEqual(self.callback.call_count, 2)
        view = self.view()
        self.assertEqual(view["plan"], self.original)
        self.assertEqual(view["replan"]["job"]["status"], "execution-unknown")
        self.assertNotIn("previous_plans", view)

    def test_saved_replan_becomes_current_and_parent_is_history(self):
        comment, revision, decision, body, prepared, new_plan = self.run_replan()
        before = self.journal.snapshot(self.jobs.project_id)
        view = self.view()
        self.assertEqual(self.journal.snapshot(self.jobs.project_id), before)
        self.assertEqual(view["plan"], new_plan)
        self.assertEqual(view["job"]["request_sha256"], prepared["request_sha256"])
        self.assertEqual(view["default_request"]["key"], self.key)
        [old] = view["previous_plans"]
        self.assertEqual(old["plan"], self.original)
        self.assertEqual(
            old["job"]["request_sha256"], self.default_body["request_sha256"]
        )
        self.assertEqual(
            old["replanned_by"],
            {
                "key": body["key"],
                "request_sha256": prepared["request_sha256"],
                "from_revision_receipt_sha256": revision["receipt_sha256"],
                "from_decision_receipt_sha256": decision["receipt_sha256"],
            },
        )
        self.assertEqual(
            {r["receipt_sha256"] for r in old["feedback"]["records"]},
            {comment["receipt_sha256"], revision["receipt_sha256"]},
        )
        self.assertEqual(
            old["host_decision"]["latest"]["receipt_sha256"], decision["receipt_sha256"]
        )
        # the new plan starts clean; comments now bind to it
        self.assertEqual(view["feedback"]["records"], [])
        self.assertIsNone(view["host_decision"]["latest"])
        self.assertEqual(
            (view["replan"]["available"], view["replan"]["reason"]),
            (False, "stage3-replan-revision-required"),
        )
        self.assertEqual(
            view["replan"]["parent_plan_manifest_sha256"],
            view["job"]["plan_manifest_sha256"],
        )
        fresh = self.comment(key="c-new", text="On the new plan.")
        self.assertEqual(
            fresh["record"]["binding"]["plan_request_sha256"],
            prepared["request_sha256"],
        )
        # a second replan chains from the new plan
        revision2 = self.revise(fresh, key="r-new", value="SECOND-ROUND")
        decision2 = self.decide(key="d-new")
        body2 = dict(
            self.replan_body(decision2, revision2),
            key=replan_key(
                self.key, decision2["receipt_sha256"], revision2["receipt_sha256"]
            ),
        )
        prepared2 = self.http.replan.prepare("own", self.ref, body2)
        payload = self.item_for(body2["key"])["payload"]
        self.assertEqual(
            payload["revision_input"]["parent_request_sha256"],
            prepared["request_sha256"],
        )
        third = self.respond(body2["key"], marker="THIRD-PLAN")
        self.http.replan.run(
            "own",
            self.ref,
            dict(body2, request_sha256=prepared2["request_sha256"], confirmed=True),
        )
        view = self.view()
        self.assertEqual(view["plan"], third)
        self.assertEqual(
            [entry["plan"] for entry in view["previous_plans"]],
            [self.original, new_plan],
        )
        self.assertEqual(self.callback.call_count, 3)


class ReplanHttpTests(ReplanFixture, unittest.TestCase):
    def post(self, action, body):
        from test_project_stage3_planning_http import Handler
        from research_workspace_native.project_stage3_http import handle_planning

        handler = Handler(self.http, action, body)
        handler.path = "/api/projects/" + self.ref + "/stage3/planning/" + action
        handle_planning(handler, "POST")
        return handler.replies

    def test_http_prepare_and_confirmed_run_dispatch_once(self):
        _, revision, decision = self.revised_and_decided()
        body = self.view()["replan"]["request"]
        [(status, prepared)] = self.post("prepare", body)
        self.assertEqual((status, prepared["status"]), (200, "intent-recorded"))
        self.assertEqual(self.callback.call_count, 1)
        self.respond(body["key"], marker="HTTP-PLAN")
        run_body = dict(body, request_sha256=prepared["request_sha256"], confirmed=True)
        [(status, accepted)] = self.post("run", run_body)
        self.assertEqual(status, 202)
        self.assertFalse(accepted["dispatch_observed"])
        self.assertEqual(self.callback.call_count, 2)
        [(status, replay)] = self.post("run", run_body)
        self.assertEqual((status, replay["outcome"]), (200, "saved"))
        [(status, read)] = self.post(
            "inspect", dict(body, request_sha256=prepared["request_sha256"])
        )
        self.assertEqual((status, read), (200, replay))
        self.assertEqual(self.callback.call_count, 2)
        self.assertIsNone(self.view()["submission_error"])

    def test_http_run_refuses_changed_revision_before_ack(self):
        comment, revision, decision = self.revised_and_decided()
        body = self.view()["replan"]["request"]
        [(_, prepared)] = self.post("prepare", body)
        self.revise(
            comment, key="r-after", value="Edited after prepare", parent=revision
        )
        before = self.state()
        run_body = dict(body, request_sha256=prepared["request_sha256"], confirmed=True)
        self.assertEqual(
            self.post("run", run_body),
            [(409, {"error": "stage3-replan-revision-changed"})],
        )
        self.assertEqual(self.state(), before)
        self.assertEqual(self.callback.call_count, 1)
        self.assertEqual(self.post("run", dict(run_body, confirmed=False))[0][0], 400)

    def test_http_prepare_without_decision_is_refused_without_record(self):
        comment = self.comment()
        revision = self.revise(comment)
        before = self.state()
        self.assertEqual(
            self.post("prepare", self.replan_body("f" * 64, revision)),
            [(409, {"error": "stage3-replan-decision-required"})],
        )
        self.assertEqual(self.state(), before)
        self.assertEqual(self.callback.call_count, 1)


class ReplanDirectionModeTests(unittest.TestCase):
    def test_direction_mode_is_refused_before_any_job_lookup(self):
        import threading
        from types import SimpleNamespace

        service = SimpleNamespace(
            intake=SimpleNamespace(_lock=threading.RLock()),
            bindings={},
            _current=lambda *args, **kwargs: (None, None, None, None, None),
        )
        transport = ProjectStage3Http(service, close_owner=lambda: None)
        self.addCleanup(transport.close)
        body = dict(
            key="stage3-replan-x",
            revision=1,
            input_version=1,
            brief_sha256="a" * 64,
            selection_request_sha256="b" * 64,
            mode=MODE,
            decision_receipt_sha256="c" * 64,
            plan_revision_receipt_sha256="d" * 64,
        )
        for call in (transport.replan.prepare, transport.replan.inspect):
            extra = (
                {} if call == transport.replan.prepare else {"request_sha256": "e" * 64}
            )
            with (
                self.subTest(call=call.__name__),
                self.assertRaises(SessionApiError) as error,
            ):
                call("own", "direction-ref", dict(body, **extra))
            self.assertEqual(
                (error.exception.code, error.exception.status),
                ("stage3-replan-direction-mode-unsupported", 409),
            )


if __name__ == "__main__":
    unittest.main()
