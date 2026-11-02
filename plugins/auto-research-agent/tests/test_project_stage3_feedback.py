"""Deterministic local-record tests; no research or model evaluation."""

from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace_native.journal import Journal
from research_workspace_native.project_stage3_feedback import (
    read_feedback,
    record_feedback,
)
from research_workspace_native.session_api import SessionApiError
from stage3_plan.jobs import PlanningJobs


class Stage3FeedbackFixture:
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.journal = Journal(self.root / "authored-feedback.sqlite3")
        self.addCleanup(self.journal.close)
        self.journal.bind_project("authored-project", "a" * 64)
        self.owner = self.journal.acquire_owner("authored-project", "fixture-owner")
        self.jobs = PlanningJobs(
            self.journal, "authored-project", self.owner, self.root / "jobs"
        )
        self.view = {
            "project_ref": "authored-ref",
            "input_version": 1,
            "revision": 2,
            "brief_sha256": "b" * 64,
            "job": {
                "outcome": "saved",
                "request_sha256": "c" * 64,
                "plan_manifest_sha256": "d" * 64,
            },
            "plan": {
                "kind": "Stage3DirectionPlanningResult",
                "execution_authorized": False,
                "markdown": "Authored original, including all limitations.",
                "question_plans": [
                    {
                        "question_ref": "q1",
                        "method": "Original method",
                        "materials": "Data availability unknown",
                        "design": "Original design",
                        "analysis": "Original analysis",
                        "interpretation": "Conditional",
                        "validation": "Not run",
                        "minimum_deliverable": "A draft",
                        "unknowns": ["Rights remain unknown"],
                    }
                ],
            },
        }
        self.binding = read_feedback(self.jobs, "authored-ref", self.view)["binding"]
        for target in ("stage3_plan.native.NativePlanner.__call__", "subprocess.Popen"):
            guard = patch(
                target, side_effect=AssertionError("model/process dispatch forbidden")
            )
            guard.start()
            self.addCleanup(guard.stop)

    def request(self, key):
        return {
            "key": key,
            **{k: v for k, v in self.binding.items() if k != "project_ref"},
        }

    def comment(
        self, key="comment-1", text="Keep the uncertainty visible.", question="q1"
    ):
        body = dict(self.request(key), text=text, question_ref=question)
        return record_feedback(self.jobs, "authored-ref", self.view, body, "comment")

    def revision(self, comment, *, parent=None, changes=None, key="revision-1"):
        body = dict(
            self.request(key),
            comments=[
                {
                    "key": comment["record"]["request"]["key"],
                    "sha256": comment["receipt_sha256"],
                }
            ],
            parent_revision=parent,
            changes=changes
            or [
                {
                    "question_ref": "q1",
                    "field": "method",
                    "value": "A user-authored alternative",
                }
            ],
        )
        return record_feedback(self.jobs, "authored-ref", self.view, body, "revise")


class Stage3FeedbackTests(Stage3FeedbackFixture, unittest.TestCase):
    def test_large_original_remains_readable_and_commentable_without_plan_copy(self):
        self.view["plan"]["markdown"] = "Original text " * 22000
        self.binding = read_feedback(self.jobs, "authored-ref", self.view)["binding"]
        original = deepcopy(self.view)
        comment = self.comment()
        self.assertNotIn("plan", comment["record"])
        self.assertEqual(self.view, original)
        self.assertEqual(
            read_feedback(self.jobs, "authored-ref", self.view)["records"],
            [{name: comment[name] for name in ("receipt_sha256", "record")}],
        )

    def test_comment_is_honestly_attributed_and_replays_without_another_write(self):
        text = "原文保留\nInclude the limitation."
        result = self.comment(text=text)
        self.assertEqual(result["record"]["text"], text)
        self.assertEqual(result["record"]["request"]["text"], text)
        self.assertEqual(result["record"]["binding"], self.binding)
        self.assertFalse(result["record"]["execution_authorized"])
        self.assertFalse(result["record"]["native_message"])
        self.assertFalse(result["record"]["model_generated"])
        self.assertEqual(
            result["record"]["input_source"], "project-host-user-submission"
        )
        before = self.journal.snapshot(self.jobs.project_id)
        replay = self.comment(text="原文保留\nInclude the limitation.")
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["receipt_sha256"], result["receipt_sha256"])
        self.assertEqual(self.journal.snapshot(self.jobs.project_id), before)

    def test_same_key_with_other_text_is_rejected(self):
        self.comment()
        with self.assertRaises(SessionApiError) as error:
            self.comment(text="A changed request cannot replace the first comment.")
        self.assertEqual(error.exception.status, 409)

    def test_changed_project_or_plan_pin_does_not_carry_records_forward(self):
        self.comment()
        other = deepcopy(self.view)
        other["job"]["plan_manifest_sha256"] = "e" * 64
        self.assertEqual(read_feedback(self.jobs, "authored-ref", other)["records"], [])
        self.assertEqual(
            read_feedback(self.jobs, "other-ref", self.view)["records"], []
        )

    def test_typed_version_and_each_hash_are_checked_before_write(self):
        for field, value in [
            ("input_version", "1"),
            ("revision", True),
            ("brief_sha256", "e" * 64),
            ("parent_plan_sha256", "e" * 64),
            ("parent_plan_manifest_sha256", "e" * 64),
            ("plan_request_sha256", "e" * 64),
        ]:
            with self.subTest(field=field):
                body = dict(
                    self.request("bad-" + field), text="Text", question_ref=None
                )
                body[field] = value
                with self.assertRaises(SessionApiError):
                    record_feedback(
                        self.jobs, "authored-ref", self.view, body, "comment"
                    )
        self.assertEqual(
            read_feedback(self.jobs, "authored-ref", self.view)["records"], []
        )

    def test_nonexistent_question_is_rejected_without_write(self):
        before = self.journal.snapshot(self.jobs.project_id)
        with self.assertRaises(SessionApiError):
            self.comment(question="other-question")
        self.assertEqual(self.journal.snapshot(self.jobs.project_id), before)

    def test_comment_action_and_payload_cannot_request_revision(self):
        body = dict(self.request("invalid"), text="Text", question_ref=None)
        cases = [("revise", body), ("unknown", body)] + [
            ("comment", dict(body, **{field: value}))
            for field, value in (
                ("comments", []),
                ("parent_revision", None),
                ("changes", []),
                ("execution_authorized", True),
            )
        ]
        before = self.journal.snapshot(self.jobs.project_id)
        for action, payload in cases:
            with self.subTest(action=action, payload=payload):
                with self.assertRaises(SessionApiError) as error:
                    record_feedback(
                        self.jobs, "authored-ref", self.view, payload, action
                    )
                self.assertEqual(error.exception.status, 400)
        self.assertEqual(self.journal.snapshot(self.jobs.project_id), before)

    def test_record_limit_rejects_new_comment_but_allows_existing_replay(self):
        first = self.comment(key="bounded-0")
        for index in range(1, 32):
            self.comment(key="bounded-" + str(index))
        before = self.journal.snapshot(self.jobs.project_id)
        replay = self.comment(key="bounded-0")
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["receipt_sha256"], first["receipt_sha256"])
        with self.assertRaises(SessionApiError) as error:
            self.comment(key="bounded-32")
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(
            len(read_feedback(self.jobs, "authored-ref", self.view)["records"]), 32
        )
        self.assertEqual(self.journal.snapshot(self.jobs.project_id), before)

    def test_no_saved_plan_has_no_feedback_mutation(self):
        view = dict(self.view, plan=None)
        with self.assertRaises(SessionApiError):
            read_feedback(self.jobs, "authored-ref", view)

    def test_lost_reply_can_be_reconciled_by_read_and_same_key(self):
        first = self.comment()
        rows = read_feedback(self.jobs, "authored-ref", self.view)["records"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["receipt_sha256"], first["receipt_sha256"])
        self.assertEqual(self.comment()["receipt_sha256"], first["receipt_sha256"])

    def test_deadline_expiry_prevents_publication(self):
        def expired():
            raise TimeoutError("authored deadline")

        body = dict(self.request("deadline"), text="Text", question_ref=None)
        with self.assertRaises(TimeoutError):
            record_feedback(
                self.jobs, "authored-ref", self.view, body, "comment", expired
            )
        self.assertEqual(
            read_feedback(self.jobs, "authored-ref", self.view)["records"], []
        )

    def test_changed_record_cannot_keep_its_original_receipt(self):
        self.comment()
        state = deepcopy(self.journal.snapshot(self.jobs.project_id))
        item = next(iter(state["intents"].values()))
        item["payload"]["text"] = "An altered record with the original receipt"
        with patch.object(self.journal, "snapshot", return_value=state):
            with self.assertRaises(SessionApiError):
                read_feedback(self.jobs, "authored-ref", self.view)

    def test_generic_saved_plan_allows_only_whole_plan_comment(self):
        self.view["plan"] = {
            "kind": "Stage3ResearchPlan",
            "execution_authorized": False,
        }
        self.binding = read_feedback(self.jobs, "authored-ref", self.view)["binding"]
        original = deepcopy(self.view)
        comment = self.comment(question=None)
        self.assertIsNone(comment["record"]["question_ref"])
        self.assertEqual(self.view, original)
        before = self.journal.snapshot(self.jobs.project_id)
        with self.assertRaises(SessionApiError):
            self.comment(key="unknown-question", question="q1")
        self.assertEqual(self.journal.snapshot(self.jobs.project_id), before)

    def test_manual_revision_preserves_parent_unknowns_and_original_plan(self):
        original = deepcopy(self.view)
        result = self.revision(self.comment())
        record = result["record"]
        self.assertEqual(record["revision_number"], 2)
        self.assertEqual(record["authoring_mode"], "manual-planning-draft")
        self.assertEqual(
            record["plan"]["question_plans"][0]["method"], "A user-authored alternative"
        )
        self.assertEqual(
            record["plan"]["question_plans"][0]["unknowns"], ["Rights remain unknown"]
        )
        self.assertEqual(record["plan"]["markdown"], self.view["plan"]["markdown"])
        self.assertFalse(record["execution_authorized"])
        self.assertEqual(self.view, original)

    def test_revision_chain_binds_exact_parent_receipt(self):
        comment = self.comment()
        first = self.revision(comment)
        second = self.revision(
            comment,
            key="revision-2",
            parent={"key": "revision-1", "sha256": first["receipt_sha256"]},
            changes=[
                {"question_ref": "q1", "field": "validation", "value": "Proposed check"}
            ],
        )
        self.assertEqual(second["record"]["revision_number"], 3)
        self.assertEqual(
            second["record"]["plan"]["question_plans"][0]["method"],
            "A user-authored alternative",
        )
        with self.assertRaises(SessionApiError):
            self.revision(
                comment,
                key="bad-parent",
                parent={"key": "revision-1", "sha256": "f" * 64},
            )

    def test_unrecognized_or_policy_fields_cannot_be_edited(self):
        comment = self.comment()
        for field in ("execution_authorized", "unknowns", "question_ref", "kind"):
            with self.subTest(field=field), self.assertRaises(SessionApiError):
                self.revision(
                    comment,
                    key="invalid-" + field,
                    changes=[
                        {"question_ref": "q1", "field": field, "value": "replace"}
                    ],
                )

    def test_nonexistent_question_and_wrong_comment_receipt_are_rejected(self):
        with self.assertRaises(SessionApiError):
            self.comment(question="other-question")
        comment = self.comment()
        comment["receipt_sha256"] = "e" * 64
        with self.assertRaises(SessionApiError):
            self.revision(comment)

    def test_generic_saved_plan_allows_comment_but_not_unknown_question_edit(self):
        self.view["plan"] = {
            "kind": "Stage3ResearchPlan",
            "execution_authorized": False,
        }
        self.binding = read_feedback(self.jobs, "authored-ref", self.view)["binding"]
        comment = self.comment(question=None)
        with self.assertRaises(SessionApiError):
            self.revision(comment)

    def test_lost_revision_reply_recovers_exact_receipt_without_another_write(self):
        comment = self.comment()
        original = self.journal.record_intent

        def commit_then_disconnect(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("reply lost after durable local record")

        with patch.object(self.journal, "record_intent", commit_then_disconnect):
            with self.assertRaises(OSError):
                self.revision(comment)
        revisions = [
            row
            for row in read_feedback(self.jobs, "authored-ref", self.view)["records"]
            if row["record"]["kind"] == "revision"
        ]
        self.assertEqual(len(revisions), 1)
        saved = revisions[0]
        before = self.journal.snapshot(self.jobs.project_id)
        replay = self.revision(comment)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["receipt_sha256"], saved["receipt_sha256"])
        self.assertEqual(replay["record"], saved["record"])
        self.assertEqual(self.journal.snapshot(self.jobs.project_id), before)

    def test_revision_copy_bound_preserves_original_and_comment(self):
        self.view["plan"]["markdown"] = "Original text " * 22000
        self.binding = read_feedback(self.jobs, "authored-ref", self.view)["binding"]
        comment = self.comment()
        before = self.journal.snapshot(self.jobs.project_id)
        with self.assertRaises(SessionApiError) as error:
            self.revision(comment)
        self.assertEqual(error.exception.status, 413)
        self.assertEqual(self.journal.snapshot(self.jobs.project_id), before)

    def test_revision_replay_at_record_cap_but_new_revision_is_rejected(self):
        comment = self.comment()
        first = self.revision(comment)
        for index in range(30):
            self.comment(key="filler-" + str(index))
        before = self.journal.snapshot(self.jobs.project_id)
        self.assertEqual(
            self.revision(comment)["receipt_sha256"], first["receipt_sha256"]
        )
        with self.assertRaises(SessionApiError) as error:
            self.revision(comment, key="new-at-cap")
        self.assertEqual(error.exception.code, "stage3-feedback-record-bound")
        self.assertEqual(self.journal.snapshot(self.jobs.project_id), before)


if __name__ == "__main__":
    unittest.main()
