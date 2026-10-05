"""Synthetic constructor failures; no process, model or research execution."""

from pathlib import Path
from contextlib import contextmanager
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from research_workspace_native import controller as module
from test_research_workspace_native_controller import Channel, ControllerFixture


class ConstructionTests(ControllerFixture):
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


if __name__ == "__main__":
    unittest.main()
