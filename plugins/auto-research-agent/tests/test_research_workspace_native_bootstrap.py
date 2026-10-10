"""Synthetic channels and real SQLite; no native process, model or network."""

import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from research_workspace_native.bootstrap import BootstrapSession
from research_workspace_native.controller import InjectedSessionController
from research_workspace_native.frame_journal import FrameJournal
from research_workspace_native.construction import BoundControllerContext
from research_workspace_native.recording import records
from native_session_fixtures import Channel


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name).resolve() / "synthetic-bootstrap.sqlite"
        self.store = FrameJournal(self.path)
        self.addCleanup(self.store.close)
        self.store.bind_project("alpha", "a" * 64)
        self.owner = self.store.acquire_owner("alpha", "synthetic")
        self.params = dict(
            cwd=directory.name,
            model="synthetic-model",
            approvalPolicy="on-request",
            sandbox="read-only",
        )
        self.store.record_intent(
            "alpha",
            self.owner,
            "new-session",
            "thread/start",
            self.params,
            self.state()["revision"],
        )
        self.channel = Channel()

    def state(self):
        return self.store.snapshot("alpha")

    def bootstrap(self, **changes):
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
        return BootstrapSession(**options)

    def responses(self, *, account=None, tail=b"", thread_id="synthetic-thread"):
        self.channel.queue(dict(id=1, result=dict(userAgent="synthetic-server")))
        self.channel.queue(
            dict(
                id="1",
                result=account
                or dict(requiresOpenaiAuth=True, account={"type": "apiKey"}),
            )
        )
        self.channel.reads.append(
            json.dumps(
                dict(
                    id=2,
                    result=dict(
                        thread={"id": thread_id},
                        cwd=self.params["cwd"],
                        model=self.params["model"],
                        approvalPolicy="on-request",
                        sandbox={"type": "readOnly", "networkAccess": False},
                    ),
                )
            ).encode()
            + b"\n"
            + tail
        )

    def ready(self, **options):
        boot = self.bootstrap(**options)
        self.responses()
        return boot.open_thread(dict(name="synthetic-client", version="1"))

    def test_explicit_handshake_total_preserves_each_step_limit(self):
        boot = self.bootstrap()
        self.responses()
        allowed = boot._allowed

        def delayed(method):
            time.sleep(0.12)
            return allowed(method)

        with patch.object(boot, "_allowed", side_effect=delayed):
            boot.open_thread(
                dict(name="synthetic-client", version="1"),
                timeout=0.3,
                total_timeout=1.2,
            )
        self.assertEqual(self.state()["bootstrap"]["phase"], "ready")
        self.assertEqual(len(self.channel.sent), 4)
        self.assertNotIn(
            "turn/start", [json.loads(raw).get("method") for raw in self.channel.sent]
        )

    def test_legacy_total_deadline_still_stops_without_resend(self):
        boot = self.bootstrap()
        self.responses()
        allowed = boot._allowed

        def delayed(method):
            time.sleep(0.12)
            return allowed(method)

        with patch.object(boot, "_allowed", side_effect=delayed):
            with self.assertRaises(ValueError):
                boot.open_thread(
                    dict(name="synthetic-client", version="1"), timeout=0.3
                )
        before = len(self.channel.sent)
        with self.assertRaises(ValueError):
            boot.open_thread(
                dict(name="synthetic-client", version="1"), total_timeout=120
            )
        self.assertEqual(len(self.channel.sent), before)
        self.assertEqual(self.state()["bootstrap"]["phase"], "failed")

    def test_invalid_budget_and_late_cached_response_cannot_bind_thread(self):
        boot = self.bootstrap()
        self.responses()
        for budget in (True, -1, 121, float("inf"), float("nan")):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                boot.open_thread(
                    dict(name="synthetic-client", version="1"), total_timeout=budget
                )
        self.assertEqual(len(self.channel.sent), 0)
        response = boot.transport.wait_response

        def late(*args, **kwargs):
            reply = response(*args, **kwargs)
            time.sleep(0.15)
            return reply

        with patch.object(boot.transport, "wait_response", side_effect=late):
            with self.assertRaises(ValueError):
                boot.open_thread(
                    dict(name="synthetic-client", version="1"),
                    timeout=0.1,
                    total_timeout=0.5,
                )
        self.assertIsNone(self.state()["thread_id"])
        self.assertEqual(self.state()["bootstrap"]["phase"], "failed")
        self.assertEqual(len(self.channel.sent), 1)

    def test_same_transport_preserves_typed_ids_partial_buffer_and_raw_frames(self):
        boot = self.bootstrap()
        notice = b'{"method":"synthetic/notice","params":{}}\n'
        self.responses(tail=notice + b'{"method":"synthetic/partial"')
        boot.open_thread(dict(name="synthetic-client", version="1"))
        transport, wrapped, used, buffer = (
            boot.transport,
            boot.channel,
            set(boot.transport.used),
            boot.transport.buffer,
        )
        controller = InjectedSessionController.adopt_ready(
            boot, admit_action=lambda action: True
        )
        self.addCleanup(controller.close)
        self.assertIs(controller.transport, transport)
        self.assertIs(controller.channel, wrapped)
        self.assertEqual(controller.transport.used, used)
        self.assertIn(("int", 1), used)
        self.assertIn(("str", "1"), used)
        self.assertEqual(controller.transport.buffer, buffer)
        self.assertTrue(controller.transport.initialized)
        controller.pump()
        self.channel.reads.append(b',"params":{}}\n')
        controller.pump()
        frames = self.state()["bootstrap"]["frames"]
        self.assertEqual(len(frames), 7)
        self.assertTrue(all(row["raw_utf8"].endswith("\n") for row in frames))
        self.assertTrue(records(self.store, "alpha", "synthetic-epoch"))

    def test_nonliteral_gates_and_missing_intent_cause_zero_io(self):
        before = self.state()
        for changes in (
            {"admit_lifecycle": lambda offer: 1},
            {"verify_binding": lambda: None},
            {"intent_key": "absent"},
        ):
            with self.assertRaises(ValueError):
                self.bootstrap(**changes)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.channel.calls, [])

    def test_login_and_revoked_thread_permission_do_not_send_thread_start(self):
        boot = self.bootstrap(
            admit_lifecycle=lambda offer: offer["method"] != "thread/start"
        )
        self.responses()
        with self.assertRaises(ValueError):
            boot.open_thread(dict(name="synthetic-client", version="1"))
        self.assertNotIn(
            "thread/start", [m.get("method") for m in self.channel.messages()]
        )
        self.assertEqual(
            self.state()["intents"]["new-session"]["status"], "intent-recorded"
        )
        self.assertEqual(self.channel.closed, 1)

    def test_missing_login_is_preserved_and_thread_start_is_not_sent(self):
        boot = self.bootstrap()
        self.responses(account=dict(requiresOpenaiAuth=True, account=None))
        with self.assertRaises(ValueError):
            boot.open_thread(dict(name="synthetic-client", version="1"))
        self.assertEqual(self.channel.messages()[-1]["method"], "account/read")
        self.assertEqual(self.state()["bootstrap"]["phase"], "failed")

    def test_thread_partial_write_failure_reopen_is_unknown_and_never_resends(self):
        boot = self.bootstrap()
        self.responses()
        original = self.channel.write

        def fail(data, timeout):
            if b'"thread/start"' in data:
                self.channel.write = lambda data, timeout: (_ for _ in ()).throw(
                    OSError("synthetic partial failure")
                )
                self.channel.sent.append(data[:3])
                return 3
            return original(data, timeout)

        self.channel.write = fail
        with self.assertRaises(ValueError):
            boot.open_thread(dict(name="synthetic-client", version="1"))
        count = len(self.channel.calls)
        self.store.close()
        self.store = FrameJournal(self.path)
        self.addCleanup(self.store.close)
        self.owner = self.store.acquire_owner("alpha", "recovered")
        self.assertEqual(
            self.state()["intents"]["new-session"]["status"], "execution-unknown"
        )
        with self.assertRaises(ValueError):
            self.bootstrap(connection_id="new-epoch")
        self.assertEqual(len(self.channel.calls), count)

    def test_completed_reply_crash_before_bind_recovers_locally_without_io(self):
        boot = self.bootstrap()
        self.responses()
        with patch.object(
            self.store, "bind_thread", side_effect=OSError("synthetic crash window")
        ):
            with self.assertRaises(ValueError):
                boot.open_thread(dict(name="synthetic-client", version="1"))
        self.assertIsNone(self.state()["thread_id"])
        self.assertEqual(self.state()["intents"]["new-session"]["status"], "completed")
        calls = list(self.channel.calls)
        self.store.close()
        self.store = FrameJournal(self.path)
        self.addCleanup(self.store.close)
        self.owner = self.store.acquire_owner("alpha", "recovered")
        for _ in range(2):
            state = BootstrapSession.recover_thread(
                self.store,
                "alpha",
                self.owner,
                index_sha256="a" * 64,
                input_version="b" * 64,
                verify_binding=lambda: True,
            )
            self.assertEqual(state["thread_id"], "synthetic-thread")
        self.assertEqual(self.channel.calls, calls)

    def test_double_adopt_and_ordinary_constructor_keep_existing_guards(self):
        boot = self.ready()
        controller = InjectedSessionController.adopt_ready(
            boot, admit_action=lambda action: True
        )
        self.addCleanup(controller.close)
        with self.assertRaises(ValueError):
            InjectedSessionController.adopt_ready(
                boot, admit_action=lambda action: True
            )
        with self.assertRaisesRegex(ValueError, "healthy channel"):
            BoundControllerContext(
                store=self.store,
                project_id="alpha",
                owner=self.owner,
                connection_id="other",
                index_sha256="a" * 64,
                thread_id="synthetic-thread",
                channel=Channel(),
                verify_binding=lambda: True,
                admit_action=lambda action: True,
                on_event=lambda event: None,
            )

    def test_handoff_failure_retains_frames_closes_once_and_prevents_reuse(self):
        boot = self.ready()
        with patch.object(
            self.store, "bind_connection", side_effect=OSError("synthetic bind failure")
        ):
            with self.assertRaises(ValueError):
                InjectedSessionController.adopt_ready(
                    boot, admit_action=lambda action: True
                )
        self.assertEqual(self.channel.closed, 1)
        self.assertEqual(len(self.state()["bootstrap"]["frames"]), 7)
        with self.assertRaises(ValueError):
            InjectedSessionController.adopt_ready(
                boot, admit_action=lambda action: True
            )

    def test_post_ready_admission_refusal_consumes_and_closes(self):
        boot = self.ready()
        boot.admit_lifecycle = lambda offer: False
        with self.assertRaises(ValueError):
            InjectedSessionController.adopt_ready(
                boot, admit_action=lambda action: True
            )
        self.assertEqual(self.state()["bootstrap"]["phase"], "failed")
        self.assertEqual(self.channel.closed, 1)
        boot.admit_lifecycle = lambda offer: True
        with self.assertRaises(ValueError):
            InjectedSessionController.adopt_ready(
                boot, admit_action=lambda action: True
            )
        self.assertEqual(self.channel.closed, 1)

    def test_post_ready_source_exception_closes_and_preserves_failure(self):
        boot = self.ready()
        boot.verify_binding = lambda: (_ for _ in ()).throw(
            OSError("synthetic source drift")
        )
        with self.assertRaises(ValueError) as raised:
            InjectedSessionController.adopt_ready(
                boot, admit_action=lambda action: True
            )
        self.assertIsInstance(raised.exception.__cause__, OSError)
        self.assertEqual(self.channel.closed, 1)
        self.assertEqual(self.state()["bootstrap"]["phase"], "failed")

    def test_post_ready_owner_loss_still_closes_underlying_channel(self):
        boot = self.ready()
        self.store.release_owner("alpha", self.owner)
        with self.assertRaisesRegex(ValueError, "persistence unobserved"):
            InjectedSessionController.adopt_ready(
                boot, admit_action=lambda action: True
            )
        self.assertEqual(self.channel.closed, 1)

    def test_malformed_account_never_dispatches_thread_start(self):
        boot = self.bootstrap()
        self.responses(account=dict(requiresOpenaiAuth=True, account={"type": "bogus"}))
        with self.assertRaisesRegex(ValueError, "bootstrap failed"):
            boot.open_thread(dict(name="synthetic-client", version="1"))
        self.assertEqual(self.channel.messages()[-1]["method"], "account/read")
        self.assertEqual(
            self.state()["intents"]["new-session"]["status"], "intent-recorded"
        )

    def test_elevated_effective_sandbox_fails_and_retains_attempt(self):
        boot = self.bootstrap()
        self.responses()
        reply = json.loads(self.channel.reads[-1])
        reply["result"]["sandbox"]["networkAccess"] = True
        self.channel.reads[-1] = json.dumps(reply).encode() + b"\n"
        with self.assertRaises(ValueError):
            boot.open_thread(dict(name="synthetic-client", version="1"))
        self.assertEqual(
            self.state()["intents"]["new-session"]["status"], "execution-unknown"
        )
        self.assertEqual(self.channel.closed, 1)

    def test_numeric_network_policy_is_rejected(self):
        boot = self.bootstrap()
        self.responses()
        reply = json.loads(self.channel.reads[-1])
        reply["result"]["sandbox"]["networkAccess"] = 0
        self.channel.reads[-1] = json.dumps(reply).encode() + b"\n"
        with self.assertRaises(ValueError):
            boot.open_thread(dict(name="synthetic-client", version="1"))
        self.assertEqual(self.state()["bootstrap"]["phase"], "failed")
        self.assertEqual(self.channel.closed, 1)

    def test_direct_transport_dispatch_has_no_saved_claim_and_zero_writes(self):
        boot = self.bootstrap()
        for method, params, rpc_id in (
            ("thread/start", self.params, 3),
            ("initialize", {"wrong": True}, "1"),
        ):
            with self.assertRaises(ValueError):
                boot.transport.send_request(method, params, request_id=rpc_id)
        with self.assertRaises(ValueError):
            boot.transport.notify("initialized")
        self.assertEqual(self.channel.calls, [])
        self.assertEqual(
            self.state()["intents"]["new-session"]["status"], "intent-recorded"
        )

    def test_owner_loss_before_open_closes_without_protocol_write(self):
        boot = self.bootstrap()
        self.store.release_owner("alpha", self.owner)
        with self.assertRaisesRegex(ValueError, "persistence unobserved"):
            boot.open_thread(dict(name="synthetic-client", version="1"))
        self.assertEqual(self.channel.closed, 1)
        self.assertEqual(self.channel.calls, [])

    def test_local_recovery_rejects_tampered_typed_request(self):
        boot = self.bootstrap()
        self.responses()
        with patch.object(
            self.store, "bind_thread", side_effect=OSError("synthetic crash")
        ):
            with self.assertRaises(ValueError):
                boot.open_thread(dict(name="synthetic-client", version="1"))
        with self.store._edit(
            "alpha", self.owner, None, "synthetic-tampering", {}
        ) as state:
            state["bootstrap"]["correlations"]['["int",2]']["request"]["id"] = "2"
        before = list(self.channel.calls)
        with self.assertRaises(ValueError):
            BootstrapSession.recover_thread(
                self.store,
                "alpha",
                self.owner,
                index_sha256="a" * 64,
                input_version="b" * 64,
                verify_binding=lambda: True,
            )
        self.assertEqual(self.channel.calls, before)


if __name__ == "__main__":
    unittest.main()
