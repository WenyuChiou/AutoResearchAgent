"""Offline accepted-frame atomicity; no channel-byte capture or native process."""

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from research_workspace_native.frame_journal import FrameJournal, JournalError
from research_workspace_native.transport import JsonRpcTransport, TransportError
from test_research_workspace_native_transport import FakeServer


class FrameJournalTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name).resolve() / "frames.sqlite3"
        self.j = FrameJournal(self.path)
        self.addCleanup(self.j.close)
        self.j.bind_project("alpha", "a" * 64)
        self.owner = self.j.acquire_owner("alpha", "test")
        self.call("bind_thread", "thread-a")
        self.call("bind_connection", "epoch-a")

    def state(self):
        return self.j.snapshot("alpha")

    def call(self, method, *args):
        return getattr(self.j, method)(
            "alpha", self.owner, *args, self.state()["revision"]
        )

    def frame(self, message, direction="incoming", connection="epoch-a"):
        kind = (
            "request"
            if "method" in message and "id" in message
            else "notification"
            if "method" in message
            else "response"
        )
        return dict(
            connection_id=connection,
            direction=direction,
            kind=kind,
            message=message,
            raw_utf8=json.dumps(message, ensure_ascii=False) + "\n",
        )

    def emit(self, message, direction="incoming", connection="epoch-a"):
        return self.j.ingest_frame(
            "alpha", self.owner, self.frame(message, direction, connection)
        )

    def prepare(self, key="start", rpc_id=1, method="turn/start"):
        params = {"threadId": "thread-a"}
        if method == "turn/interrupt":
            params["turnId"] = key
        self.call("record_intent", key, method, params)
        self.call("transition_intent", key, "dispatching", {"persisted": True})
        self.call("correlate", "epoch-a", rpc_id, key)
        return dict(id=rpc_id, method=method, params=params)

    def terminal(self, turn_id):
        return dict(
            method="turn/completed",
            params={
                "threadId": "thread-a",
                "turn": {"id": turn_id, "status": "completed"},
            },
        )

    def question(self, native_id):
        return dict(
            id=native_id,
            method="item/tool/requestUserInput",
            params={
                "threadId": "thread-a",
                "turnId": "turn-a",
                "itemId": "item-a",
                "questions": [{"id": "q", "question": "Neutral?"}],
            },
        )

    def test_raw_only_duplicate_observations_survive_a_fresh_connection(self):
        message = dict(
            method="thread/status/changed",
            params={"threadId": "thread-a", "status": "idle"},
        )
        frame = self.frame(message)
        for _ in range(2):
            self.j.ingest_frame("alpha", self.owner, frame)
        reader = FrameJournal(self.path)
        self.addCleanup(reader.close)
        self.assertEqual(reader.snapshot("alpha"), self.state())
        events = [
            e["payload"]
            for e in reader.events("alpha")
            if e["kind"] == "protocol-frame"
        ]
        self.assertEqual([e["frame_seq"] for e in events], [1, 2])
        self.assertEqual(
            [e["frame"]["raw_utf8"] for e in events], [frame["raw_utf8"]] * 2
        )
        self.assertEqual(self.state()["turns"], {})

    def test_terminal_and_response_orders_bind_only_the_exact_intent(self):
        for n, terminal_first in enumerate((True, False)):
            key = "turn-" + str(n)
            self.emit(self.prepare(key, n), "outgoing")
            ack = {"id": n, "result": {"turn": {"id": key}}}
            first, second = (
                (self.terminal(key), ack)
                if terminal_first
                else (ack, self.terminal(key))
            )
            self.emit(first)
            self.assertEqual(
                self.state()["intents"][key]["status"],
                "dispatching" if terminal_first else "dispatched",
            )
            self.emit(second)
            self.assertEqual(self.state()["intents"][key]["status"], "completed")
            self.assertEqual(self.state()["intents"][key]["native_turn_id"], key)
            self.emit(ack)
            self.emit(self.terminal(key))
            self.assertEqual(self.state()["intents"][key]["status"], "completed")
        conflict = self.terminal(key)
        conflict["params"]["turn"]["status"] = "failed"
        with self.assertRaisesRegex(JournalError, "terminal evidence differs"):
            self.emit(conflict)
        self.assertEqual(self.state()["turns"][key]["status"], "completed")

    def test_passive_notifications_have_no_business_authority(self):
        for message in (
            {"method": "turn/started", "params": {"threadId": "thread-a"}},
            {
                "method": "item/agentMessage/delta",
                "params": {"threadId": "thread-a", "delta": "neutral"},
            },
            {"method": "future/global"},
            {"method": "thread/observed", "params": {"thread": {"id": "thread-a"}}},
        ):
            self.emit(message)
        self.assertEqual(self.state()["protocol"]["frame_seq"], 4)
        self.assertEqual(
            [self.state()[name] for name in ("intents", "requests", "turns")],
            [{}, {}, {}],
        )
        for n, params in enumerate(
            (None, [], {"threadId": "other"}, {"thread": {"id": "other"}})
        ):
            connection = "invalid-" + str(n)
            self.call("bind_connection", connection)
            frame = self.frame(
                {"method": "future/global", "params": params}, connection=connection
            )
            with self.assertRaisesRegex(JournalError, "quarantine"):
                self.j.ingest_frame("alpha", self.owner, frame)
            self.assertEqual(self.j.events("alpha")[-1]["payload"]["frame"], frame)

    def test_native_request_resolution_is_not_send_or_turn_completion(self):
        self.emit(self.question(1))
        self.emit(self.question("1"))
        requests = sorted(
            self.state()["requests"].values(),
            key=lambda row: type(row["request_identity"]["native_id"]) is str,
        )
        answer = {"answers": {"q": {"answers": ["neutral"]}}}
        self.j.record_intent(
            "alpha",
            self.owner,
            "answer",
            requests[0]["method"],
            answer,
            self.state()["revision"],
            request_identity=requests[0]["request_identity"],
        )
        self.call("transition_intent", "answer", "dispatching", {"persisted": True})
        self.emit({"id": 1, "result": answer}, "outgoing")
        self.assertEqual(
            self.state()["requests"][requests[0]["key"]]["status"], "pending"
        )
        self.emit(
            {
                "method": "serverRequest/resolved",
                "params": {"threadId": "thread-a", "requestId": 1},
            }
        )
        self.assertEqual(
            [self.state()["requests"][r["key"]]["status"] for r in requests],
            ["request-resolved", "pending"],
        )
        self.assertEqual(self.state()["intents"]["answer"]["status"], "dispatching")
        self.assertEqual(self.state()["turns"], {})
        self.emit(self.question(1))
        self.assertEqual(
            self.state()["requests"][requests[0]["key"]]["status"], "request-resolved"
        )
        conflict = self.question(1)
        conflict["params"]["questions"][0]["question"] = "changed"
        with self.assertRaisesRegex(JournalError, "reused native request ID"):
            self.emit(conflict)
        self.assertEqual(
            self.state()["requests"][requests[0]["key"]]["status"], "request-resolved"
        )

    def test_valid_raw_mismatch_and_rpc_error_are_saved_in_quarantine(self):
        self.emit(self.prepare(), "outgoing")
        frame = self.frame(
            {"id": 1, "error": {"code": -1, "message": "neutral failure"}}
        )
        with self.assertRaisesRegex(JournalError, "quarantine"):
            self.j.ingest_frame("alpha", self.owner, frame)
        self.assertEqual(
            self.state()["intents"]["start"]["status"], "execution-unknown"
        )
        self.assertEqual(self.j.events("alpha")[-1]["payload"]["frame"], frame)
        self.call("bind_connection", "epoch-b")
        frame = self.frame(self.question(1), connection="epoch-b")
        frame["message"] = self.question("1")
        with self.assertRaisesRegex(JournalError, "raw/message mismatch"):
            self.j.ingest_frame("alpha", self.owner, frame)
        self.assertEqual(self.j.events("alpha")[-1]["payload"]["frame"], frame)
        self.assertEqual(self.state()["requests"], {})

    def test_typed_correlations_and_epoch_owner_project_isolation(self):
        for key, rpc_id in (
            ("int", 1),
            ("str", "1"),
            ("low", -(2**63)),
            ("high", 2**63 - 1),
        ):
            self.prepare(key, rpc_id)
        self.assertEqual(len(self.state()["protocol"]["correlations"]), 4)
        for value in (True, None, -(2**63) - 1, 2**63):
            with self.assertRaises(JournalError):
                self.call("correlate", "epoch-a", value, "int")
        self.j.bind_project("beta", "b" * 64)
        other = self.j.acquire_owner("beta", "test")
        self.j.bind_thread(
            "beta", other, "thread-b", self.j.snapshot("beta")["revision"]
        )
        with self.assertRaisesRegex(JournalError, "already bound"):
            self.j.bind_connection(
                "beta", other, "epoch-a", self.j.snapshot("beta")["revision"]
            )
        self.j.release_owner("alpha", self.owner)
        self.owner = self.j.acquire_owner("alpha", "replacement")
        with self.assertRaisesRegex(JournalError, "binding differs"):
            self.emit(self.question(1))
        self.call("bind_connection", "epoch-b")
        with self.assertRaisesRegex(JournalError, "binding differs"):
            self.emit(self.question(1))
        self.assertEqual(self.state()["requests"], {})

    def test_semantic_failure_discards_partial_projection_but_keeps_raw(self):
        original = self.j._apply

        def fail_after_apply(*args):
            original(*args)
            raise JournalError("injected failure after real reducer")

        with patch.object(self.j, "_apply", side_effect=fail_after_apply):
            with self.assertRaisesRegex(JournalError, "quarantine"):
                self.emit(self.question(1))
        self.assertEqual(self.state()["requests"], {})
        self.assertEqual(self.state()["protocol"]["frame_seq"], 1)
        self.assertEqual(self.j.events("alpha")[-1]["kind"], "protocol-frame")

    def test_sql_failure_rolls_back_both_frame_and_state(self):
        before, events = self.state(), self.j.events("alpha")
        self.j.db.execute(
            "CREATE TEMP TRIGGER reject_frame BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'fixture failure'); END"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.emit(self.question(1))
        self.assertEqual((self.state(), self.j.events("alpha")), (before, events))

    def test_outgoing_quarantine_stops_transport_before_any_write(self):
        class Channel:
            writes = 0

            def write(self, data, timeout):
                self.writes += 1
                return len(data)

            def close(self):
                pass

        channel = Channel()
        self.prepare()
        transport = JsonRpcTransport(
            channel,
            connection_id="epoch-a",
            on_event=lambda event: self.j.ingest_frame("alpha", self.owner, event),
            verify_binding=lambda: True,
        )
        self.addCleanup(transport.close)
        with self.assertRaises(TransportError):
            transport.send_request("turn/start", {"threadId": "other"}, request_id=1)
        self.assertEqual(channel.writes, 0)
        self.assertTrue(self.state()["protocol"]["quarantine"])
        self.assertFalse(
            next(iter(self.state()["protocol"]["correlations"].values()))["outgoing"]
        )

    def test_transport_callback_commits_interleaved_question_terminal_and_reply(self):
        outgoing = self.prepare("stream-turn", 1)

        def respond(row):
            self.assertEqual(row, outgoing)
            return [
                self.question(7),
                {
                    "method": "item/agentMessage/delta",
                    "params": {"threadId": "thread-a", "delta": "neutral"},
                },
                self.terminal("stream-turn"),
                {"id": 1, "result": {"turn": {"id": "stream-turn"}}},
            ]

        channel = FakeServer(respond)
        transport = JsonRpcTransport(
            channel,
            connection_id="epoch-a",
            on_event=lambda event: self.j.ingest_frame("alpha", self.owner, event),
            verify_binding=lambda: True,
        )
        self.addCleanup(transport.close)
        response = transport.request("turn/start", outgoing["params"], request_id=1)
        self.assertEqual(response["result"]["turn"]["id"], "stream-turn")
        self.assertEqual(self.state()["intents"]["stream-turn"]["status"], "completed")
        self.assertEqual(
            [row["status"] for row in self.state()["requests"].values()], ["pending"]
        )
        self.assertEqual(transport.pending_requests()[0]["request"]["id"], 7)
        frames = [
            event["payload"]
            for event in self.j.events("alpha")
            if event["kind"] == "protocol-frame"
        ]
        self.assertEqual([row["frame_seq"] for row in frames], [1, 2, 3, 4, 5])
        self.assertEqual(len(channel.messages), 1)


if __name__ == "__main__":
    unittest.main()
