"""Synthetic helper failures with real SQLite; no process or model execution."""

from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from research_workspace_native.bootstrap_context import BootstrapContext
from research_workspace_native.frame_journal import FrameJournal
from native_session_fixtures import Channel


class BootstrapContextTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = FrameJournal(Path(folder.name).resolve() / "synthetic.sqlite")
        self.addCleanup(self.store.close)
        self.store.bind_project("alpha", "a" * 64)
        self.owner = self.store.acquire_owner("alpha", "synthetic")
        self.store.record_intent(
            "alpha",
            self.owner,
            "new-session",
            "thread/start",
            dict(
                cwd=folder.name,
                model="synthetic",
                approvalPolicy="on-request",
                sandbox="read-only",
            ),
            self.store.snapshot("alpha")["revision"],
        )
        self.channel = Channel()

    def context(self, **changes):
        options = dict(
            store=self.store,
            project_id="alpha",
            owner=self.owner,
            connection_id="synthetic-epoch",
            index_sha256="a" * 64,
            input_version="b" * 64,
            intent_key="new-session",
            channel=self.channel,
            verify_binding=lambda: True,
            admit_lifecycle=lambda offer: True,
        )
        options.update(changes)
        return BootstrapContext(**options)

    def test_invalid_channel_owner_and_nonliteral_gates_do_not_poison_state(self):
        before = self.store.snapshot("alpha")
        for changes in (
            {"channel": object()},
            {"owner": "wrong"},
            {"verify_binding": lambda: None},
            {"admit_lifecycle": lambda offer: 1},
        ):
            with self.assertRaises(ValueError):
                self.context(**changes)
        self.assertEqual(self.store.snapshot("alpha"), before)
        self.assertEqual(self.channel.calls, [])

    def test_payload_mutation_rejects_without_io(self):
        context = self.context()
        self.addCleanup(context.channel.close)
        context.params["model"] = "different"
        with self.assertRaisesRegex(ValueError, "payload differs"):
            context._context()
        self.assertEqual(self.channel.calls, [])

    def incoming_frame(self, context):
        frames = []
        self.channel.queue(dict(method="synthetic/notice", params={}))
        with patch.object(context.transport, "on_event", side_effect=frames.append):
            context.transport.poll(0)
        self.assertEqual(len(frames), 1)
        return frames[0]

    def test_frame_validation_uses_transaction_state_without_snapshot(self):
        context = self.context()
        self.addCleanup(context.channel.close)
        frame = self.incoming_frame(context)
        with patch.object(
            self.store, "snapshot", wraps=self.store.snapshot
        ) as snapshot:
            context._event(frame)
        snapshot.assert_not_called()
        self.assertEqual(len(self.store.snapshot("alpha")["bootstrap"]["frames"]), 1)

    def test_frame_rejects_version_changed_during_binding_verification(self):
        context = self.context()
        self.addCleanup(context.channel.close)
        frame = self.incoming_frame(context)

        def changed_binding():
            with self.store._edit(
                "alpha", self.owner, None, "synthetic-version-change", {}
            ) as state:
                state["bootstrap"]["input_version"] = "c" * 64
            return True

        context.verify_binding = changed_binding
        with self.assertRaisesRegex(ValueError, "bootstrap owner/version expired"):
            context._event(frame)
        state = self.store.snapshot("alpha")
        self.assertEqual(state["bootstrap"]["input_version"], "c" * 64)
        self.assertEqual(state["bootstrap"]["frames"], [])

    def test_post_recording_failure_and_unobserved_failure_save_close_once(self):
        edit = self.store._edit

        @contextmanager
        def failing(*args, **kwargs):
            if args[3] == "bootstrap-failed":
                raise OSError("synthetic journal failure")
            with edit(*args, **kwargs) as state:
                yield state

        with (
            patch.object(self.store, "_edit", side_effect=failing),
            patch(
                "research_workspace_native.bootstrap_context.JsonRpcTransport",
                side_effect=ValueError("synthetic late failure"),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "failure persistence unobserved"):
                self.context()
        self.assertEqual(self.channel.closed, 1)
        self.assertEqual(self.channel.calls, [])
        with self.assertRaises(ValueError):
            self.context(connection_id="other")

    def test_recording_constructor_failure_closes_owned_raw_channel(self):
        with patch(
            "research_workspace_native.bootstrap_context.RecordingChannel",
            side_effect=OSError("synthetic constructor failure"),
        ):
            with self.assertRaises(ValueError) as raised:
                self.context()
        self.assertIsInstance(raised.exception.__cause__, OSError)
        self.assertEqual(self.channel.closed, 1)
        boot = self.store.snapshot("alpha")["bootstrap"]
        self.assertEqual(boot["phase"], "failed")
        self.assertEqual(
            boot["cleanup"], dict(attempted=True, route="raw", returned=True)
        )

    def test_raw_close_failure_retains_uncertainty_and_original_failure(self):
        def close():
            self.channel.closed += 1
            raise TimeoutError("synthetic cleanup failure")

        self.channel.close = close
        with patch(
            "research_workspace_native.bootstrap_context.RecordingChannel",
            side_effect=OSError("synthetic constructor failure"),
        ):
            with self.assertRaisesRegex(
                ValueError, "cleanup persistence unobserved"
            ) as raised:
                self.context()
        self.assertIsInstance(raised.exception.__cause__, OSError)
        self.assertEqual(self.channel.closed, 1)
        self.assertEqual(
            self.store.snapshot("alpha")["bootstrap"]["cleanup"]["exception_type"],
            "TimeoutError",
        )


if __name__ == "__main__":
    unittest.main()
