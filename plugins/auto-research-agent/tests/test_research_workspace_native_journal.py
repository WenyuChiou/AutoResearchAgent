"""Synthetic SQLite checks without native/model/network execution."""

import multiprocessing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from research_workspace_native.journal import Journal, JournalError


def child_owner(path, crash, queue):
    journal = Journal(path)
    try:
        owner = journal.acquire_owner("alpha", "child")
    except JournalError:
        queue.put("blocked")
        journal.close()
        return
    journal.bind_thread(
        "alpha", owner, "thread-a", journal.snapshot("alpha")["revision"]
    )
    journal.record_intent(
        "alpha",
        owner,
        "crashed",
        "turn/start",
        {"threadId": "thread-a"},
        journal.snapshot("alpha")["revision"],
    )
    journal.bind_rpc(
        "alpha",
        owner,
        "connection-a",
        1,
        "crashed",
        journal.snapshot("alpha")["revision"],
    )
    journal.transition_intent(
        "alpha",
        owner,
        "crashed",
        "dispatching",
        {"before_send": True},
        journal.snapshot("alpha")["revision"],
    )
    if crash:
        os._exit(0)
    journal.release_owner("alpha", owner)
    journal.close()


class NativeJournalTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name).resolve() / "journal.sqlite3"
        self.journal = Journal(self.path)
        self.addCleanup(self.journal.close)
        self.journal.bind_project("alpha", "a" * 64)
        self.owner = self.journal.acquire_owner("alpha", "test")

    def state(self):
        return self.journal.snapshot("alpha")

    def call(self, method, *args):
        return getattr(self.journal, method)(
            "alpha", self.owner, *args, self.state()["revision"]
        )

    def identity(self, native_id=1):
        return dict(
            connection_id="connection-a",
            native_id=native_id,
            thread_id="thread-a",
            turn_id="turn-a",
            item_id="item-a",
            approval_id=None,
        )

    def recover(self):
        self.journal.release_owner("alpha", self.owner)
        self.owner = self.journal.acquire_owner("alpha", "recovery")

    def queued(self, key, rpc_id=1, method="turn/start", **payload):
        self.call("record_intent", key, method, dict(threadId="thread-a", **payload))
        self.call("bind_rpc", "connection-a", rpc_id, key)

    def test_binding_revision_and_cross_connection_owner(self):
        second = Journal(self.path)
        self.addCleanup(second.close)
        with self.assertRaisesRegex(JournalError, "execution owner"):
            second.acquire_owner("alpha", "other")
        for journal, owner in ((second, self.owner), (self.journal, None)):
            with self.assertRaisesRegex(JournalError, "exclusive owner"):
                journal.record_intent(
                    "alpha", owner, "x", "turn/start", {}, self.state()["revision"]
                )
        with self.assertRaisesRegex(JournalError, "binding differs"):
            self.journal.bind_project("alpha", "b" * 64)
        with self.assertRaisesRegex(JournalError, "stale revision"):
            self.journal.bind_thread("alpha", self.owner, "thread-a", 0)
        self.call("bind_thread", "thread-a")
        self.journal.bind_project("beta", "b" * 64)
        other = self.journal.acquire_owner("beta", "test")
        with self.assertRaisesRegex(JournalError, "another project"):
            self.journal.bind_thread(
                "beta", other, "thread-a", self.journal.snapshot("beta")["revision"]
            )

    def test_durable_intent_idempotency_and_immutable_history(self):
        self.call("bind_thread", "thread-a")
        revision = self.state()["revision"]
        self.assertFalse(
            self.call("record_intent", "once", "turn/start", {"threadId": "thread-a"})[
                "replayed"
            ]
        )
        second = Journal(self.path)
        self.addCleanup(second.close)
        self.assertEqual(
            second.snapshot("alpha")["intents"]["once"]["status"], "intent-recorded"
        )
        events = self.journal.events("alpha")
        replay = self.journal.record_intent(
            "alpha",
            self.owner,
            "once",
            "turn/start",
            {"threadId": "thread-a"},
            revision,
        )
        self.assertTrue(replay["replayed"])
        self.assertEqual(events, self.journal.events("alpha"))
        with self.assertRaisesRegex(JournalError, "payload differs"):
            self.call("record_intent", "once", "turn/start", {"text": "different"})
        for statement in ("DELETE FROM events", "UPDATE events SET kind='rewritten'"):
            with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable event"):
                self.journal.db.execute(statement)

    def test_typed_requests_answer_resolution_and_terminal_are_distinct(self):
        self.call("bind_thread", "thread-a")
        rows = [
            self.call(
                "record_request",
                self.identity(value),
                "item/tool/requestUserInput",
                {"question": "Neutral?"},
            )
            for value in (1, "1", -(2**63), 2**63 - 1)
        ]
        self.assertEqual(len({row["key"] for row in rows}), 4)
        before = self.state()
        for invalid in (True, None, 2**63, -(2**63) - 1):
            with self.assertRaises(JournalError):
                self.call("record_request", self.identity(invalid), "question", {})
            self.assertEqual(self.state(), before)
        self.call(
            "update_request", self.identity(), "answer-sent", {"response": "observed"}
        )
        self.call("record_terminal", "turn-a", "completed", {"event": "turn/completed"})
        self.assertEqual(
            self.state()["requests"][rows[0]["key"]]["status"], "answer-sent"
        )
        self.assertEqual(self.state()["turns"]["turn-a"]["status"], "completed")
        self.call(
            "update_request",
            self.identity(),
            "request-resolved",
            {"event": "serverRequest/resolved"},
        )
        self.assertEqual(self.state()["requests"][rows[1]["key"]]["status"], "pending")
        self.assertEqual(
            self.journal.events("alpha")[-1]["payload"]["collection"], "requests"
        )

    def test_unknown_intent_requires_explicit_terminal_reconciliation(self):
        self.call("bind_thread", "thread-a")
        self.queued("once")
        self.call("transition_intent", "once", "dispatching", {"before_send": True})
        self.recover()
        self.assertEqual(self.state()["intents"]["once"]["status"], "execution-unknown")
        with self.assertRaisesRegex(JournalError, "forbidden"):
            self.call("transition_intent", "once", "dispatching", {"retry": True})
        with self.assertRaisesRegex(JournalError, "execution-unknown"):
            self.call("record_intent", "retry", "turn/start", {"threadId": "thread-a"})
        with self.assertRaisesRegex(JournalError, "reconciliation"):
            self.call(
                "transition_intent", "once", "completed", {"native_turn_id": "turn-a"}
            )
        reconciliation = dict(
            connection_id="connection-a",
            rpc_id=1,
            native_turn_id="turn-a",
            thread_id="thread-a",
            intent_record_sha256=self.state()["intents"]["once"]["record_sha256"],
        )
        with self.assertRaisesRegex(JournalError, "terminal required"):
            self.call(
                "transition_intent",
                "once",
                "completed",
                {"reconciliation": reconciliation},
            )
        self.call(
            "record_terminal", "turn-a", "interrupted", {"event": "turn/completed"}
        )
        self.call(
            "transition_intent", "once", "completed", {"reconciliation": reconciliation}
        )
        self.assertEqual(self.state()["intents"]["once"]["native_turn_id"], "turn-a")
        self.assertEqual(
            self.journal.events("alpha")[-1]["payload"]["collection"], "intents"
        )

    def test_process_owner_exclusion_and_crash_recovery(self):
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        self.addCleanup(queue.close)
        for crash in (False, True):
            if crash:
                self.journal.release_owner("alpha", self.owner)
            process = context.Process(
                target=child_owner, args=(str(self.path), crash, queue)
            )
            process.start()
            process.join(10)
            self.assertFalse(process.is_alive())
            self.assertEqual(process.exitcode, 0)
            if not crash:
                self.assertEqual(queue.get(timeout=2), "blocked")
        self.journal.acquire_owner("alpha", "after-crash")
        self.assertEqual(
            self.state()["intents"]["crashed"]["status"], "execution-unknown"
        )

    def test_unknown_thread_start_cannot_create_or_bind_a_replacement(self):
        self.call("record_intent", "start", "thread/start", {})
        self.call("transition_intent", "start", "dispatching", {"before_send": True})
        self.recover()
        with self.assertRaisesRegex(JournalError, "needs reconciliation"):
            self.call("bind_thread", "guessed-thread")
        with self.assertRaisesRegex(JournalError, "thread/start intent"):
            self.call("record_intent", "retry", "thread/start", {})
        with self.assertRaisesRegex(JournalError, "native thread ID"):
            self.call("transition_intent", "start", "completed", {"guess": True})
        self.call(
            "transition_intent", "start", "completed", {"thread_id": "observed-thread"}
        )
        self.call("bind_thread", "observed-thread")
        with self.assertRaisesRegex(JournalError, "unknown request"):
            self.call(
                "update_request",
                self.identity(),
                "request-resolved",
                {"event": "serverRequest/resolved"},
            )

    def test_unknown_native_request_blocks_new_intents_without_unknown_intents(self):
        self.call("bind_thread", "thread-a")
        self.call("record_request", self.identity(), "item/tool/requestUserInput", {})
        self.recover()
        self.assertEqual(self.state()["intents"], {})
        with self.assertRaisesRegex(JournalError, "execution-unknown"):
            self.call("record_intent", "new", "turn/start", {"threadId": "thread-a"})
        self.call(
            "update_request",
            self.identity(),
            "request-resolved",
            {"event": "serverRequest/resolved"},
        )
        self.assertEqual(self.state()["turns"], {})

    def test_rpc_ack_is_not_turn_terminal_and_ids_cannot_switch(self):
        self.call("bind_thread", "thread-a")
        for method in ("turn/start", "turn/interrupt"):
            turn = method.replace("/", "-")
            rpc_id = -(2**63) if method == "turn/start" else 2**63 - 1
            self.queued(method, rpc_id, method, turnId=turn)
            self.call("transition_intent", method, "dispatching", {"before_send": True})
            ack = dict(
                connection_id="connection-a",
                native_turn_id=turn,
                rpc_receipt={
                    "id": rpc_id,
                    "result": {"turn": {"id": turn}},
                },
            )
            with self.assertRaisesRegex(JournalError, "terminal required"):
                self.call("transition_intent", method, "completed", ack)
            if method == "turn/start":
                malformed = {
                    **ack,
                    "rpc_receipt": {"id": rpc_id, "result": {"turn": None}},
                }
                with self.assertRaisesRegex(JournalError, "turn must be an object"):
                    self.call("transition_intent", method, "dispatched", malformed)
            before = self.state()
            for invalid in (True, None, 2**63, -(2**63) - 1):
                bad = {**ack, "rpc_receipt": {**ack["rpc_receipt"], "id": invalid}}
                with self.assertRaises(JournalError):
                    self.call("transition_intent", method, "dispatched", bad)
                self.assertEqual(self.state(), before)
            self.call("transition_intent", method, "dispatched", ack)
            with self.assertRaisesRegex(JournalError, "terminal required"):
                self.call("transition_intent", method, "completed", ack)
            self.call("record_terminal", turn, "failed", {"event": "turn/completed"})
            with self.assertRaisesRegex(JournalError, "identity differs"):
                self.call(
                    "transition_intent",
                    method,
                    "completed",
                    {"native_turn_id": "wrong-turn"},
                )
            self.call(
                "transition_intent", method, "completed", {"native_turn_id": turn}
            )

    def test_answer_intent_completion_requires_native_request_resolution(self):
        self.call("bind_thread", "thread-a")
        method = "item/tool/requestUserInput"
        self.call("record_request", self.identity(), method, {})
        self.journal.record_intent(
            "alpha",
            self.owner,
            "answer",
            method,
            {"answer": "neutral"},
            self.state()["revision"],
            request_identity=self.identity(),
        )
        self.call("transition_intent", "answer", "dispatching", {"before_send": True})
        self.call("update_request", self.identity(), "answer-sent", {"sent": True})
        with self.assertRaisesRegex(JournalError, "requires request-resolved"):
            self.call("transition_intent", "answer", "completed", {"sent": True})
        self.call(
            "update_request",
            self.identity(),
            "request-resolved",
            {"event": "serverRequest/resolved"},
        )
        self.call("transition_intent", "answer", "completed", {"resolved": True})
        self.assertEqual(self.state()["turns"], {})

    def test_queued_intent_cannot_dispatch_during_unknown_request_or_intent(self):
        self.call("bind_thread", "thread-a")
        self.queued("queued")
        self.call("record_request", self.identity(), "item/tool/requestUserInput", {})
        self.call(
            "update_request", self.identity(), "execution-unknown", {"lost": True}
        )
        before = self.state()
        with self.assertRaisesRegex(JournalError, "execution-unknown before dispatch"):
            self.call("transition_intent", "queued", "dispatching", {"send": True})
        self.assertEqual(self.state(), before)
        self.call(
            "update_request", self.identity(), "request-resolved", {"resolved": True}
        )
        self.queued("displaced", 2)
        self.call("transition_intent", "displaced", "dispatching", {"send": True})
        self.call("transition_intent", "displaced", "execution-unknown", {"lost": True})
        before = self.state()
        with self.assertRaisesRegex(JournalError, "execution-unknown before dispatch"):
            self.call("transition_intent", "queued", "dispatching", {"send": True})
        self.assertEqual(self.state(), before)


if __name__ == "__main__":
    unittest.main()
