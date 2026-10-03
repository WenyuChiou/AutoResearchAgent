"""Synthetic conversation and owner-decision boundaries; no model calls."""

import json
import sys
import unittest
from unittest.mock import patch
import uuid

import test_research_studio as fixtures
from research_studio.interaction import decide, dialogue_context, reply
from research_studio.runtime import validate_request
from research_studio.store import StudioError, canonical, sha


class StudioInteractionTests(unittest.TestCase):
    setUp = fixtures.StudioTests.setUp
    tearDown = fixtures.StudioTests.tearDown
    git = fixtures.StudioTests.git
    request = fixtures.StudioTests.request
    run_fixture = fixtures.StudioTests.run_fixture

    def dialogue(self, **updates):
        value = {
            "kind": "dialogue",
            "request_id": str(uuid.uuid4()),
            "thread_id": str(uuid.uuid4()),
            "parent_turn_id": None,
            "context_run_id": None,
            "artifact_ids": [],
            "stage": 1,
            "topic": "Synthetic fixture",
            "message": "What scope should I confirm?",
            "timeout_seconds": 60,
        }
        return value | updates

    def decision(self, **updates):
        return {
            "request_id": str(uuid.uuid4()),
            "stage": 1,
            "topic": "Synthetic fixture",
            "action": "confirm_scope",
            "scope": "No geographic restriction",
            "run_id": None,
            "manifest_sha256": None,
            "note": "",
        } | updates

    def execute_dialogue(self, request, output=None):
        output = output or {
            "message": "Please choose the scope.",
            "question": "Which years?",
            "suggested_scope": "2020 through 2025",
        }
        code = (
            "import pathlib,sys; sys.stdin.read(); pathlib.Path('final.md').write_text("
            + repr(json.dumps(output))
            + ", encoding='utf-8')"
        )
        with patch.object(
            self.engine, "dialogue_command", return_value=[sys.executable, "-c", code]
        ):
            self.engine.submit(request)
            self.engine.thread.join(15)
            self.assertFalse(self.engine.thread.is_alive())
        return self.store.get(request["request_id"])

    def test_question_answer_history_and_stage_isolation(self):
        request = self.dialogue(stage=3)
        run = self.execute_dialogue(request)
        self.assertEqual(run["status"], "human-review")
        self.assertEqual(reply(self.engine, run)["question"], "Which years?")
        self.assertEqual(self.store.list(), [])
        self.assertEqual(len(self.store.threads(3)), 1)
        self.assertEqual(self.store.threads(1), [])
        second = self.dialogue(
            stage=3,
            thread_id=request["thread_id"],
            parent_turn_id=run["id"],
            message="2022 onward",
        )
        context = dialogue_context(self.engine, second)
        self.assertEqual(context["history"][0]["assistant"]["question"], "Which years?")
        with self.assertRaises(StudioError):
            self.engine.submit(second | {"stage": 2})
        with self.assertRaises(StudioError):
            self.engine.submit(second | {"parent_turn_id": None})
        self.execute_dialogue(second)
        self.assertEqual(len(self.store.turns(request["thread_id"])), 2)
        self.assertEqual(self.store.decisions(3, request["topic"]), [])
        with self.assertRaises(StudioError):
            self.engine.submit(self.request() | {"request_id": run["id"]})

    def test_scope_is_explicit_idempotent_and_bound_to_run_input(self):
        decision = self.decision()
        saved = decide(self.engine, decision)
        self.assertEqual(decide(self.engine, decision), saved)
        self.assertEqual(self.store.list(), [])
        with self.assertRaises(StudioError):
            decide(self.engine, decision | {"scope": "Changed"})
        request = self.request() | {"scope_confirmation_id": saved["id"]}
        with self.assertRaises(StudioError):
            self.engine.submit(request | {"scope": "Different"})
        run = self.run_fixture(request)
        self.assertEqual(
            self.store.get(run["id"])["scope_confirmation_id"], saved["id"]
        )

        unlinked = dict(request)
        del unlinked["scope_confirmation_id"]
        with self.assertRaises(StudioError):
            self.engine.submit(unlinked)

    def test_review_binds_manifest_and_preserves_research_status(self):
        run = self.run_fixture()
        run = self.store.get(run["id"])
        request = self.decision(
            action="accept_review",
            scope=None,
            run_id=run["id"],
            manifest_sha256=sha(canonical(run["manifest"]).encode()),
        )
        with self.assertRaises(StudioError):
            decide(self.engine, request | {"manifest_sha256": "0" * 64})
        saved = decide(self.engine, request)
        self.assertEqual(saved["request"]["run_id"], run["id"])
        self.assertEqual(self.store.get(run["id"])["status"], "human-review")
        changes = request | {
            "request_id": str(uuid.uuid4()),
            "action": "request_changes",
        }
        with self.assertRaises(StudioError):
            decide(self.engine, changes)
        decide(self.engine, changes | {"note": "Add missing evidence"})
        self.assertEqual(len(self.store.decisions(1, request["topic"])), 2)

    def test_malformed_reply_fails_and_command_is_read_only(self):
        run = self.execute_dialogue(self.dialogue(), {"message": "missing fields"})
        self.assertEqual(run["status"], "failed")
        self.assertIsNone(reply(self.engine, run))
        command = self.engine.dialogue_command(self.root)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        self.assertIn("--output-schema", command)
        self.assertIn('web_search="disabled"', command)
        self.assertNotIn("sandbox_workspace_write.network_access=true", command)

    def test_attachments_reject_cross_stage_and_changed_bytes(self):
        run = self.run_fixture()
        run = self.store.get(run["id"])
        file = next(f for f in run["manifest"]["artifacts"] if f["path"] == "final.md")
        request = self.dialogue(context_run_id=run["id"], artifact_ids=[file["id"]])
        self.assertEqual(
            dialogue_context(self.engine, request)["source_run"]["files"][0]["text"],
            "synthetic only",
        )
        with self.assertRaises(StudioError):
            dialogue_context(self.engine, request | {"stage": 2})
        with self.assertRaises(StudioError):
            validate_request(request | {"artifact_ids": [file["id"], file["id"]]})
        # Actual artifact integrity is checked by the existing download boundary.
        with patch.object(
            self.engine, "artifact", side_effect=StudioError("hash changed")
        ):
            with self.assertRaises(StudioError):
                dialogue_context(self.engine, request)


if __name__ == "__main__":
    unittest.main()
