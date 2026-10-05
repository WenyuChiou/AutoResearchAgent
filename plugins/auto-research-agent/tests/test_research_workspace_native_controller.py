"""Injected channel integration only; no native process, model or network."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from research_workspace_native.controller import (
    ControllerError,
    InjectedSessionController,
)
from research_workspace_native.frame_journal import FrameJournal
from research_workspace_native.recording import records
from research_workspace_native.store import JournalError
from research_workspace_native.transport import TransportError
from native_session_fixtures import Channel as Channel, NativeSessionFixture

ERRORS = (ControllerError, JournalError, TransportError)
ANSWER = {"answers": {"q": {"answers": ["neutral"]}}}


class ControllerFixture(NativeSessionFixture, unittest.TestCase):
    connection_factory = InjectedSessionController

    def receive(self, controller, message):
        self.channel.queue(message)
        controller.pump()

    def pending(self, controller, native_id=7):
        self.receive(controller, self.question(native_id))
        return next(
            row
            for row in controller.view()["requests"].values()
            if type(row["request_identity"]["native_id"]) is type(native_id)
            and row["request_identity"]["native_id"] == native_id
        )

    def answer(self, controller, request, key="answer", result=None, **changes):
        arguments = dict(
            key=key,
            request_key=request["key"],
            request_sha256=request["record_sha256"],
            result=ANSWER if result is None else result,
            expected_revision=controller.view()["revision"],
        )
        arguments.update(changes)
        return controller.answer(**arguments)

    def terminal(self, controller):
        self.receive(
            controller,
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "thread-a",
                    "turn": {"id": "turn-a", "status": "completed"},
                },
            },
        )


class InjectedControllerTests(ControllerFixture):
    def test_answer_partial_writes_resolution_and_terminal_are_separate(self):
        self.channel.limit = 7
        controller = self.connect()
        request = self.pending(controller)
        result = self.answer(controller, request)
        self.assertEqual(result["status"], "dispatched")
        self.assertGreater(self.channel.calls.count("write"), 1)
        self.assertEqual(self.channel.messages(), [{"id": 7, "result": ANSWER}])
        self.assertEqual(
            controller.view()["requests"][request["key"]]["status"], "answer-sent"
        )
        self.assertEqual(controller.view()["turns"], {})
        self.receive(
            controller,
            {
                "method": "serverRequest/resolved",
                "params": {"threadId": "thread-a", "requestId": 7},
            },
        )
        view = controller.view()
        self.assertEqual(view["actions"]["answer"]["status"], "completed")
        self.assertEqual(next(iter(view["intents"].values()))["status"], "completed")
        self.assertEqual(view["turns"], {})
        self.terminal(controller)
        self.assertEqual(controller.view()["turns"]["turn-a"]["status"], "completed")
        rows = records(self.store, "alpha", "epoch-a")
        self.assertTrue(any(row["operation"] == "read" and row["data"] for row in rows))
        self.assertTrue(
            any(
                row["operation"] == "write" and row["phase"] == "result" for row in rows
            )
        )
        self.assertTrue(
            any(row["kind"] == "protocol-frame" for row in self.store.events("alpha"))
        )
        view["actions"].clear()
        self.assertIn("answer", controller.view()["actions"])
        self.assertNotIn(self.owner, json.dumps(controller.view()))
        self.assertNotIn("protocol", controller.view())

    def test_approval_decline_and_cancel_keep_integer_and_string_ids_distinct(self):
        controller = self.connect()
        for native_id, method, decision in (
            (7, "item/commandExecution/requestApproval", "decline"),
            ("7", "item/fileChange/requestApproval", "cancel"),
        ):
            self.receive(controller, self.question(native_id, method))
            request = next(
                row
                for row in controller.view()["requests"].values()
                if type(row["request_identity"]["native_id"]) is type(native_id)
            )
            self.answer(
                controller, request, key=decision, result={"decision": decision}
            )
        self.assertEqual(
            self.channel.messages(),
            [
                {"id": 7, "result": {"decision": "decline"}},
                {"id": "7", "result": {"decision": "cancel"}},
            ],
        )
        self.assertEqual(controller.view()["turns"], {})

    def test_interrupt_ack_is_not_terminal_and_backend_owns_rpc_id(self):
        controller = self.connect()
        result = controller.client_action(
            "interrupt",
            "turn/interrupt",
            {"threadId": "thread-a", "turnId": "turn-a"},
            controller.view()["revision"],
        )
        self.assertEqual(result["status"], "write-observed")
        wire = self.channel.messages()[0]
        self.assertEqual(wire["method"], "turn/interrupt")
        self.assertIn(type(wire["id"]), (int, str))
        self.receive(controller, {"id": wire["id"], "result": {}})
        self.assertEqual(
            controller.view()["actions"]["interrupt"]["status"], "dispatched"
        )
        self.assertEqual(controller.view()["turns"], {})
        self.terminal(controller)
        self.assertEqual(
            controller.view()["actions"]["interrupt"]["status"], "completed"
        )

    def test_duplicate_tabs_share_one_write_and_changed_payload_is_rejected(self):
        controller = self.connect()
        request = self.pending(controller)
        revision, gate = controller.view()["revision"], threading.Barrier(2)

        def submit():
            gate.wait(timeout=5)
            return self.answer(controller, request, expected_revision=revision)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: submit(), range(2)))
        self.assertEqual(sorted(row["replayed"] for row in results), [False, True])
        self.assertEqual(len(self.channel.messages()), 1)
        before = list(self.channel.calls)
        with self.assertRaises(ERRORS):
            self.answer(
                controller, request, result={"answers": {"q": {"answers": ["changed"]}}}
            )
        self.assertEqual(self.channel.calls, before)

    def test_wrong_scope_hash_stale_revision_and_invalid_answer_do_not_write(self):
        controller = self.connect()
        request = self.pending(controller)
        for changes in (
            {"request_key": "missing"},
            {"request_sha256": "b" * 64},
            {"expected_revision": 0},
            {"result": {"answers": {"other": {"answers": []}}}},
        ):
            with self.subTest(changes=changes), self.assertRaises(ERRORS):
                self.answer(controller, request, **changes)
            self.assertEqual(controller.view()["intents"], {})
        for method, params in (
            ("thread/start", {}),
            ("turn/start", {"threadId": "other"}),
        ):
            with self.subTest(method=method), self.assertRaises(ERRORS):
                controller.client_action(
                    "invalid", method, params, controller.view()["revision"]
                )
        for changes in (
            {"index_sha256": "b" * 64},
            {"thread_id": "other"},
            {"project_id": "missing"},
        ):
            with self.subTest(scope=changes), self.assertRaises(ERRORS):
                self.connect(connection_id="invalid-scope", **changes)
        self.assertEqual(self.channel.sent, [])

    def test_admission_requires_literal_true_and_refusal_is_durable_idempotent(self):
        controller = self.connect(admit_action=lambda action: 1)
        request = self.pending(controller)
        first = self.answer(controller, request)
        self.assertEqual(first["status"], "refused")
        self.assertTrue(self.answer(controller, request)["replayed"])
        self.assertEqual(self.channel.sent, [])
        self.assertEqual(controller.view()["intents"], {})
        reader = FrameJournal(self.store.path)
        self.addCleanup(reader.close)
        self.assertEqual(
            reader.snapshot("alpha")["controller_actions"]["answer"]["status"],
            "refused",
        )


if __name__ == "__main__":
    unittest.main()
