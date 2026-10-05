"""Synthetic constructor failures; no process, model or research execution."""

from pathlib import Path
from contextlib import contextmanager
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from research_workspace_native import construction as module
from research_workspace_native.frame_journal import FrameJournal
from research_workspace_native.recording import records
from native_session_fixtures import Channel, NativeSessionFixture


class ConstructionTests(NativeSessionFixture, unittest.TestCase):
    @staticmethod
    def connection_factory(**options):
        options.setdefault(
            "on_event",
            lambda event: options["store"].ingest_frame(
                options["project_id"], options["owner"], event
            ),
        )
        return module.BoundControllerContext(**options)

    def receive(self, context, message):
        self.channel.queue(message)
        return context.transport.poll(0)

    def test_invalid_channel_does_not_bind_and_valid_retry_is_possible(self):
        before = self.state()
        with self.assertRaisesRegex(Exception, "binary channel"):
            self.connect(channel=object())
        self.assertEqual(self.state(), before)
        self.assertEqual(self.channel.calls, [])
        self.connect(connection_id="valid-after-invalid")
        self.assertEqual(self.channel.calls, [])

    def test_overlong_id_does_not_bind_or_poison_owner(self):
        before = self.state()
        with self.assertRaisesRegex(Exception, "connection ID"):
            self.connect(connection_id="x" * 129)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.channel.calls, [])
        self.connect(connection_id="valid-after-long")
        self.assertEqual(self.channel.calls, [])

    def test_failure_after_protocol_bind_is_durable_without_fake_byte_channel(self):
        with patch.object(module, "RecordingChannel", side_effect=OSError("setup")):
            with self.assertRaises(Exception):
                self.connect(connection_id="failed-before-recording")
        state = self.state()
        failure = state.get("controller_initialization_failures", {}).get(
            "failed-before-recording"
        )
        self.assertIsNotNone(failure)
        self.assertEqual(failure["owner"], self.owner)
        self.assertEqual(failure["exception_type"], "OSError")
        self.assertNotIn("failed-before-recording", state.get("byte_channels", {}))
        self.assertEqual(self.channel.calls, [])
        self.assertEqual(self.channel.closed, 0)
        with self.assertRaises(module.ControllerError) as rejected:
            self.connect(connection_id="failed-before-recording")
        self.assertRegex(
            str(rejected.exception.__cause__), "connection ID already bound"
        )
        self.assertEqual(
            self.state()["controller_initialization_failures"][
                "failed-before-recording"
            ],
            failure,
        )
        self.connect(connection_id="valid-after-setup")
        self.assertIn(
            "failed-before-recording", self.state()["protocol"]["connections"]
        )
        self.assertEqual(self.channel.calls, [])

    def test_failure_after_recording_closes_once_and_preserves_history(self):
        with patch.object(module, "JsonRpcTransport", side_effect=ValueError("setup")):
            with self.assertRaises(Exception):
                self.connect(connection_id="failed-after-recording")
        state = self.state()
        failure = state.get("controller_initialization_failures", {}).get(
            "failed-after-recording"
        )
        self.assertIsNotNone(failure)
        self.assertTrue(state["byte_channels"]["failed-after-recording"]["fault"])
        self.assertEqual(self.channel.calls, [])
        self.assertEqual(self.channel.closed, 1)
        self.connect(connection_id="valid-after-transport", channel=Channel())
        self.assertEqual(self.channel.closed, 1)
        self.assertEqual(self.channel.calls, [])
        events = self.store.db.execute(
            "SELECT kind FROM events WHERE project='alpha'"
        ).fetchall()
        self.assertIn(
            "controller-initialization-failed", [row["kind"] for row in events]
        )
        self.assertIn("failed-after-recording", self.state()["protocol"]["connections"])

    def test_unobserved_fault_persistence_stays_closed_without_io(self):
        edit = self.store._edit

        @contextmanager
        def failing_edit(*args, **kwargs):
            if args[3] == "controller-initialization-failed":
                raise OSError("journal write unavailable")
            with edit(*args, **kwargs) as state:
                yield state

        with (
            patch.object(module, "RecordingChannel", side_effect=OSError("setup")),
            patch.object(self.store, "_edit", failing_edit),
        ):
            with self.assertRaisesRegex(Exception, "fault persistence unobserved"):
                self.connect(connection_id="failed-unobserved")
        state = self.state()
        self.assertEqual(
            state["protocol"]["binding"]["connection_id"], "failed-unobserved"
        )
        self.assertFalse(state.get("controller_initialization_failures"))
        self.assertFalse(state.get("byte_channels"))
        with self.assertRaisesRegex(
            Exception, "existing protocol epoch must be closed"
        ):
            self.connect(connection_id="new-unobserved")
        self.assertEqual(self.state(), state)
        self.assertEqual(self.channel.calls, [])
        self.assertEqual(self.channel.closed, 0)

    def test_missing_event_sink_cannot_bind_or_discard_frame_evidence(self):
        before = self.state()
        with self.assertRaisesRegex(Exception, "event sink"):
            self.connect(on_event=None)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.channel.calls, [])
        self.connect(connection_id="valid-with-sink")

    def test_same_owner_second_epoch_cannot_displace_healthy_context(self):
        first = self.connect()
        self.receive(first, self.question())
        before, calls = self.state(), list(self.channel.calls)
        second_channel = Channel()
        with self.assertRaises(Exception):
            self.connect(connection_id="epoch-b", channel=second_channel)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.channel.calls, calls)
        self.assertEqual(self.channel.closed, 0)
        self.assertEqual(second_channel.calls, [])
        self.assertEqual(second_channel.closed, 0)
        self.receive(
            first,
            {
                "method": "thread/status/changed",
                "params": {"threadId": "thread-a", "status": "idle"},
            },
        )
        self.assertEqual(first.view()["connection_id"], "epoch-a")
        self.assertIsNone(first.view()["failure"])

    def test_close_reopen_keeps_old_request_unknown_and_never_reattaches(self):
        context = self.connect()
        self.receive(context, self.question())
        request = next(iter(context.view()["requests"].values()))
        context.close()
        context.close()
        self.assertEqual(self.channel.closed, 1)
        self.store.close()
        self.store = FrameJournal(self.store.path)
        self.addCleanup(self.store.close)
        self.owner = self.store.acquire_owner("alpha", "recovery")
        self.assertEqual(
            self.state()["requests"][request["key"]]["status"],
            "execution-unknown",
        )
        with self.assertRaises(Exception):
            self.connect()
        self.channel = Channel()
        recovered = self.connect(connection_id="epoch-b")
        self.assertEqual(self.channel.calls, [])
        self.assertEqual(self.channel.sent, [])
        self.assertEqual(
            recovered.view()["requests"][request["key"]]["status"],
            "execution-unknown",
        )
        with self.assertRaises(Exception):
            context._context()

    def test_failed_fault_event_with_recorded_close_recovers_only_new_epoch(self):
        edit = self.store._edit

        @contextmanager
        def failing_edit(*args, **kwargs):
            if args[3] == "controller-initialization-failed":
                raise OSError("fault event persistence unavailable")
            with edit(*args, **kwargs) as state:
                yield state

        with (
            patch.object(module, "JsonRpcTransport", side_effect=ValueError("setup")),
            patch.object(self.store, "_edit", failing_edit),
        ):
            with self.assertRaisesRegex(
                module.ControllerError, "fault persistence unobserved"
            ):
                self.connect(connection_id="failed-with-close")
        failed_channel = self.channel
        self.assertEqual(failed_channel.closed, 1)
        self.assertEqual(failed_channel.calls, [])
        state = self.state()
        self.assertFalse(state.get("controller_initialization_failures"))
        self.assertTrue(state["byte_channels"]["failed-with-close"]["fault"])
        evidence = records(self.store, "alpha", "failed-with-close")
        closes = [row for row in evidence if row["operation"] == "close"]
        self.assertEqual([row["phase"] for row in closes], ["intent", "result"])
        self.assertEqual(closes[1]["intent_seq"], closes[0]["seq"])
        self.assertEqual(closes[1]["outcome"], "closed")
        self.assertEqual(closes[1]["exception_types"], [])
        self.assertFalse(any(row["operation"] in {"read", "write"} for row in evidence))
        self.store.close()
        self.store = FrameJournal(self.store.path)
        self.addCleanup(self.store.close)
        self.owner = self.store.acquire_owner("alpha", "recovery")
        self.assertEqual(records(self.store, "alpha", "failed-with-close"), evidence)
        with self.assertRaisesRegex(module.ControllerError, "initialization failed"):
            self.connect(connection_id="failed-with-close", channel=Channel())
        self.assertEqual(records(self.store, "alpha", "failed-with-close"), evidence)
        self.channel = Channel()
        recovered = self.connect(connection_id="explicit-new-epoch")
        self.assertIsNone(recovered.view()["failure"])
        self.assertEqual(self.channel.calls, [])
        self.assertEqual(failed_channel.closed, 1)


if __name__ == "__main__":
    unittest.main()
