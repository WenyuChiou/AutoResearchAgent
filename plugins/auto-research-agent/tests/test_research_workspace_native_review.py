"""Core review regressions; synthetic SQLite records never execute native work."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from research_workspace_native.journal import Journal, JournalError


class NativeReviewTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.j = Journal(Path(folder.name).resolve() / "review.sqlite3")
        self.addCleanup(self.j.close)
        self.j.bind_project("alpha", "a" * 64)
        self.owner = self.j.acquire_owner("alpha", "test")
        self.call("bind_thread", "thread-a")

    def state(self):
        return self.j.snapshot("alpha")

    def call(self, method, *args):
        return getattr(self.j, method)(
            "alpha", self.owner, *args, self.state()["revision"]
        )

    def start(self, key):
        self.call(
            "record_intent", key, "turn/start", {"threadId": "thread-a", "text": key}
        )

    def dispatch(self, key, rpc_id):
        self.call("bind_rpc", "epoch-a", rpc_id, key)
        self.call("transition_intent", key, "dispatching", {"pre_send": True})

    def ack(self, rpc_id, turn):
        return dict(
            connection_id="epoch-a",
            native_turn_id=turn,
            rpc_receipt={"id": rpc_id, "result": {"turn": {"id": turn}}},
        )

    def reconciliation(self, key, rpc_id, turn):
        return {
            "reconciliation": dict(
                connection_id="epoch-a",
                rpc_id=rpc_id,
                thread_id="thread-a",
                native_turn_id=turn,
                intent_record_sha256=self.state()["intents"][key]["record_sha256"],
            )
        }

    def recover(self):
        self.j.release_owner("alpha", self.owner)
        self.owner = self.j.acquire_owner("alpha", "recovery")

    def test_thread_payload_and_explicit_terminal_conflicts_are_rejected(self):
        before = self.state()
        for method in ("turn/start", "turn/interrupt"):
            with self.subTest(method=method), self.assertRaises(JournalError):
                self.call(
                    "record_intent",
                    "cross",
                    method,
                    {"threadId": "thread-b", "turnId": "turn-a"},
                )
            self.assertEqual(self.state(), before)
        for field in ("threadId", "thread_id"):
            with self.subTest(field=field), self.assertRaises(JournalError):
                self.call("record_terminal", "turn-a", "completed", {field: "thread-b"})
            self.assertEqual(self.state(), before)
        self.j.bind_project("beta", "b" * 64)
        owner = self.j.acquire_owner("beta", "test")
        with self.assertRaises(JournalError):
            self.j.record_intent(
                "beta",
                owner,
                "unbound",
                "turn/start",
                {"threadId": "thread-b"},
                self.j.snapshot("beta")["revision"],
            )

    def test_exact_typed_rpc_correlation_is_required_and_not_reused(self):
        self.start("first")
        with self.assertRaises(JournalError):
            self.call("transition_intent", "first", "dispatching", {"pre_send": True})
        self.dispatch("first", 7)
        before = self.state()
        for rpc_id, epoch in (("7", "epoch-a"), (7, "other-epoch")):
            ack = self.ack(rpc_id, "turn-a")
            ack["connection_id"] = epoch
            with self.subTest(id=rpc_id, epoch=epoch), self.assertRaises(JournalError):
                self.call("transition_intent", "first", "dispatched", ack)
            self.assertEqual(self.state(), before)
        self.start("second")
        with self.assertRaises(JournalError):
            self.call("bind_rpc", "epoch-a", 7, "second")
        self.call("bind_rpc", "epoch-a", "7", "second")

    def test_native_turn_has_one_start_owner_but_allows_an_interrupt(self):
        for key, rpc_id in (("first", 1), ("second", 2)):
            self.start(key)
            self.dispatch(key, rpc_id)
        self.call("transition_intent", "first", "dispatched", self.ack(1, "shared"))
        before = self.state()
        with self.assertRaises(JournalError):
            self.call(
                "transition_intent", "second", "dispatched", self.ack(2, "shared")
            )
        self.assertEqual(self.state(), before)
        self.call("record_terminal", "shared", "completed", {"threadId": "thread-a"})
        self.call(
            "transition_intent", "first", "completed", {"native_turn_id": "shared"}
        )
        self.call(
            "record_intent",
            "stop",
            "turn/interrupt",
            {"threadId": "thread-a", "turnId": "shared"},
        )
        self.dispatch("stop", 3)
        self.call("transition_intent", "stop", "dispatched", self.ack(3, "shared"))
        self.call(
            "transition_intent", "stop", "completed", {"native_turn_id": "shared"}
        )
        self.assertEqual(self.state()["intents"]["stop"]["status"], "completed")

    def test_unknown_reconciliation_cannot_reuse_another_start_turn(self):
        for key, rpc_id in (("first", 1), ("second", 2)):
            self.start(key)
            self.dispatch(key, rpc_id)
        self.recover()
        self.call("record_terminal", "shared", "completed", {"threadId": "thread-a"})
        self.call(
            "transition_intent",
            "first",
            "completed",
            self.reconciliation("first", 1, "shared"),
        )
        before = self.state()
        with self.assertRaises(JournalError):
            self.call(
                "transition_intent",
                "second",
                "completed",
                self.reconciliation("second", 2, "shared"),
            )
        self.assertEqual(self.state(), before)
        wrong = self.reconciliation("second", 1, "other")
        with self.assertRaises(JournalError):
            self.call("transition_intent", "second", "completed", wrong)

    def test_queued_recovery_preserves_unsent_and_does_not_block_new_intake(self):
        self.start("active")
        self.dispatch("active", 1)
        self.start("queued")
        self.call("bind_rpc", "epoch-a", 2, "queued")
        self.recover()
        self.assertEqual(self.state()["intents"]["queued"]["status"], "intent-recorded")
        self.assertEqual(
            self.state()["intents"]["active"]["status"], "execution-unknown"
        )
        with self.assertRaises(JournalError):
            self.call("transition_intent", "active", "dispatching", {"retry": True})
        self.call(
            "record_terminal", "active-turn", "completed", {"threadId": "thread-a"}
        )
        self.call(
            "transition_intent",
            "active",
            "completed",
            self.reconciliation("active", 1, "active-turn"),
        )
        self.start("new")
        with self.assertRaises(JournalError):
            self.call("transition_intent", "queued", "dispatching", {"old_owner": True})
        self.assertEqual(self.state()["intents"]["queued"]["status"], "intent-recorded")

    def test_superseded_answer_is_atomically_retired_without_dispatch(self):
        identity = dict(
            connection_id="epoch-a",
            native_id=1,
            thread_id="thread-a",
            turn_id="turn-a",
            item_id="item-a",
            approval_id=None,
        )
        method = "item/tool/requestUserInput"
        self.call("record_request", identity, method, {})
        self.j.record_intent(
            "alpha",
            self.owner,
            "answer",
            method,
            {"answer": "neutral"},
            self.state()["revision"],
            request_identity=identity,
        )
        self.call(
            "update_request",
            identity,
            "request-resolved",
            {"event": "serverRequest/resolved"},
        )
        result = self.call(
            "transition_intent", "answer", "dispatching", {"pre_send": True}
        )
        self.assertEqual(result["status"], "retired")
        reader = Journal(self.j.path)
        self.addCleanup(reader.close)
        self.assertEqual(
            reader.snapshot("alpha")["intents"]["answer"]["status"], "retired"
        )
        self.assertTrue(result["evidence"])
        self.recover()
        self.assertEqual(self.state()["intents"]["answer"]["status"], "retired")
        with self.assertRaises(JournalError):
            self.call("transition_intent", "answer", "dispatching", {"retry": True})


if __name__ == "__main__":
    unittest.main()
