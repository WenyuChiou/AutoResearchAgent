"""Controller rejection and owner-loss regressions; injected channels only."""

import unittest
import json

from test_research_workspace_native_controller import (
    ANSWER,
    ERRORS,
    Channel,
    ControllerFixture,
)
from research_workspace_native.controller import InjectedSessionController
from research_workspace_native.frame_journal import FrameJournal
from research_workspace_native.recording import records


class ControllerSafetyTests(ControllerFixture):
    def test_invalid_actions_leave_inflight_start_and_channel_usable(self):
        controller = self.connect()
        result = controller.client_action(
            "active",
            "turn/start",
            {"threadId": "thread-a"},
            controller.view()["revision"],
        )
        self.assertEqual(result["status"], "write-observed")
        rpc_id = self.channel.messages()[0]["id"]
        resolved = self.pending(controller, 7)
        self.receive(
            controller,
            {
                "method": "serverRequest/resolved",
                "params": {"threadId": "thread-a", "requestId": 7},
            },
        )
        sent = self.pending(controller, 8)
        self.answer(controller, sent, key="already-sent", result=ANSWER)
        before, calls, closed = (
            self.state(),
            list(self.channel.calls),
            self.channel.closed,
        )
        attempts = (
            lambda: self.answer(controller, resolved, key="resolved-new"),
            lambda: self.answer(controller, sent, key="sent-new"),
            lambda: controller.client_action(
                "bad-interrupt",
                "turn/interrupt",
                {"threadId": "thread-a"},
                controller.view()["revision"],
            ),
        )
        for attempt in attempts:
            with self.subTest(attempt=attempts.index(attempt)):
                with self.assertRaises(ERRORS):
                    attempt()
                self.assertEqual(self.state(), before)
                self.assertEqual(self.channel.calls, calls)
                self.assertEqual(self.channel.closed, closed)
        self.assertEqual(before["intents"]["active"]["status"], "dispatching")
        self.assertEqual(
            before["controller_actions"]["active"]["status"], "write-observed"
        )
        self.receive(
            controller, {"id": rpc_id, "result": {"turn": {"id": "active-turn"}}}
        )
        self.assertEqual(controller.view()["actions"]["active"]["status"], "dispatched")
        self.assertIsNone(controller.view()["failure"])
        self.assertEqual(self.channel.closed, closed)

    def test_existing_journal_intent_cannot_be_adopted_by_controller(self):
        params = {"threadId": "thread-a", "turnId": "turn-a"}
        self.store.record_intent(
            "alpha",
            self.owner,
            "preexisting",
            "turn/interrupt",
            params,
            self.state()["revision"],
        )
        original = self.state()["intents"]["preexisting"]
        controller = self.connect()
        before = self.state()
        self.assertNotIn("preexisting", before.get("controller_actions", {}))
        with self.assertRaises(ERRORS):
            controller.client_action(
                "preexisting",
                "turn/interrupt",
                params,
                controller.view()["revision"],
            )
        self.assertEqual(self.state(), before)
        self.assertEqual(self.state()["intents"]["preexisting"], original)
        self.assertEqual(original["status"], "intent-recorded")
        self.assertEqual(self.channel.calls, [])
        self.assertEqual(self.channel.sent, [])
        self.assertEqual(self.channel.closed, 0)

    def test_owner_loss_durably_marks_local_action_unknown_without_resend(self):
        # No close cleanup: losing this fake channel models owner loss before close.
        lost = InjectedSessionController(
            store=self.store,
            project_id="alpha",
            owner=self.owner,
            connection_id="epoch-a",
            index_sha256="a" * 64,
            thread_id="thread-a",
            channel=self.channel,
            verify_binding=lambda: True,
            admit_action=lambda action: True,
        )
        params = {"threadId": "thread-a"}
        result = lost.client_action(
            "lost-action", "turn/start", params, lost.view()["revision"]
        )
        self.assertEqual(result["status"], "write-observed")
        original_channel, calls = self.channel, list(self.channel.calls)
        self.store.release_owner("alpha", self.owner)
        self.owner = self.store.acquire_owner("alpha", "recovery")
        self.assertEqual(
            self.state()["intents"]["lost-action"]["status"], "execution-unknown"
        )
        self.assertEqual(
            self.state()["controller_actions"]["lost-action"]["status"],
            "write-observed",
        )
        self.channel = Channel()
        recovered = self.connect(connection_id="epoch-b")
        reader = FrameJournal(self.store.path)
        self.addCleanup(reader.close)
        durable = reader.snapshot("alpha")
        self.assertEqual(
            durable["controller_actions"]["lost-action"]["status"], "execution-unknown"
        )
        self.assertEqual(
            durable["intents"]["lost-action"]["status"], "execution-unknown"
        )
        self.assertEqual(self.channel.calls, [])
        self.assertEqual(self.channel.sent, [])
        self.assertEqual(original_channel.closed, 0)
        with self.assertRaises(ERRORS):
            lost.pump()
        self.assertEqual(original_channel.calls, calls)
        with self.assertRaises(ERRORS):
            recovered.client_action(
                "lost-action", "turn/start", params, recovered.view()["revision"]
            )
        self.assertEqual(self.channel.calls, [])
        self.assertEqual(
            reader.snapshot("alpha")["intents"]["lost-action"]["status"],
            "execution-unknown",
        )

    def test_partial_write_failure_stays_unknown_without_resend(self):
        self.channel.writes.extend([5, OSError("synthetic write failure")])
        controller = self.connect()
        request = self.pending(controller)
        with self.assertRaises(ERRORS):
            self.answer(controller, request)
        self.assertEqual(
            controller.view()["actions"]["answer"]["status"], "execution-unknown"
        )
        self.assertEqual(
            next(iter(controller.view()["intents"].values()))["status"],
            "execution-unknown",
        )
        before = list(self.channel.calls)
        self.assertTrue(self.answer(controller, request)["replayed"])
        with self.assertRaises(ERRORS):
            controller.pump()
        self.assertEqual(self.channel.calls, before)
        rows = records(self.store, "alpha", "epoch-a")
        self.assertTrue(any(row.get("count") == 5 for row in rows))

    def test_malformed_and_eof_are_retained_and_fault_future_io(self):
        invalid_id = json.dumps(self.question(True)).encode() + b"\n"
        for epoch, raw in (("bad", b"\xff\n"), ("eof", b""), ("bool-id", invalid_id)):
            with self.subTest(epoch=epoch):
                self.channel = Channel()
                controller = self.connect(connection_id=epoch)
                self.channel.reads.append(raw)
                with self.assertRaises(ERRORS):
                    controller.pump()
                before = list(self.channel.calls)
                with self.assertRaises(ERRORS):
                    controller.pump()
                self.assertEqual(self.channel.calls, before)
                self.assertTrue(
                    any(
                        row["data"] == raw
                        for row in records(self.store, "alpha", epoch)
                    )
                )
                self.assertTrue(controller.view()["failure"])

    def test_binding_rejection_records_known_unsent_and_blocks_later_io(self):
        controller = self.connect(verify_binding=lambda: False)
        request = self.pending(controller)
        with self.assertRaises(ERRORS):
            self.answer(controller, request)
        self.assertEqual(
            controller.view()["actions"]["answer"]["status"], "failed-known-unsent"
        )
        self.assertEqual(self.channel.sent, [])
        before = list(self.channel.calls)
        with self.assertRaises(ERRORS):
            controller.pump()
        self.assertEqual(self.channel.calls, before)


if __name__ == "__main__":
    unittest.main()
