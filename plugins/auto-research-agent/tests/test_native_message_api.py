"""Explicit message offers with real SQLite and injected bytes; no native/model."""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from research_workspace_native.controller import InjectedSessionController
from research_workspace_native.frame_journal import FrameJournal
from research_workspace_native.session_api import SessionApi, SessionApiError


class Crash(BaseException):
    """Bypass in-process handling at a durable boundary."""


class Channel:
    def __init__(self):
        self.calls, self.sent, self.closed = [], [], 0
        self.incoming = []

    def read(self, size, timeout):
        self.calls.append("read")
        if self.incoming:
            return self.incoming.pop(0)
        raise TimeoutError("synthetic idle")

    def write(self, data, timeout):
        self.calls.append(("write", timeout))
        self.sent.append(bytes(data))
        return len(data)

    def close(self):
        self.closed += 1

    def messages(self):
        return [json.loads(row) for row in b"".join(self.sent).splitlines()]


class MessageApiTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.authenticate = lambda token: {
            "token-a": "principal-a",
            "token-b": "principal-b",
        }.get(token)
        self.api = SessionApi(authenticate=self.authenticate)

    def project(self, name="a", enabled=True):
        root = self.root / name
        root.mkdir()
        index = root / "index.json"
        index.write_text(json.dumps({"case": name}), encoding="utf-8")
        p = SimpleNamespace(
            root=root,
            index=index,
            pid="internal-" + name,
            ref="project-" + name,
            epoch="epoch-" + name,
            thread="thread-" + name,
            channel=Channel(),
            source_ok=True,
            binding_ok=True,
            admission=True,
            offered=True,
            offer_changes={},
            offer_calls=0,
        )
        p.hash = hashlib.sha256(index.read_bytes()).hexdigest()
        p.version = hashlib.sha256(("input-" + name).encode()).hexdigest()
        p.store = FrameJournal(root / "session.sqlite3")
        self.addCleanup(p.store.close)
        p.store.bind_project(p.pid, p.hash)
        p.owner = p.store.acquire_owner(p.pid, "server")
        p.store.bind_thread(
            p.pid, p.owner, p.thread, p.store.snapshot(p.pid)["revision"]
        )

        def source(binding):
            return (
                p.source_ok
                and binding
                == dict(
                    project_ref=p.ref,
                    project_id=p.pid,
                    source_root=root.as_posix(),
                    index_sha256=p.hash,
                    input_version=p.version,
                    thread_id=p.thread,
                    connection_id=p.epoch,
                )
                and hashlib.sha256(index.read_bytes()).hexdigest() == p.hash
            )

        def offer(binding):
            p.offer_calls += 1
            if not p.offered:
                return None
            value = dict(
                project_id=p.pid,
                index_sha256=p.hash,
                input_version=p.version,
                source_root=root.as_posix(),
                model="synthetic-model",
                limits=dict(max_text_bytes=128, max_starts=2, timeout_seconds=3),
                permit_sha256="a" * 64,
            )
            value.update(deepcopy(p.offer_changes))
            return value

        p.source, p.offer = source, offer
        self.controller(p)
        p.registration = dict(
            controller=p.controller,
            principals={"principal-a"},
            source_root=root,
            index_sha256=p.hash,
            input_version=p.version,
            verify_source=source,
            start_offer=offer if enabled else None,
        )
        self.api.register(p.ref, **p.registration)
        return p

    def controller(self, p):
        p.controller = InjectedSessionController(
            store=p.store,
            project_id=p.pid,
            owner=p.owner,
            connection_id=p.epoch,
            index_sha256=p.hash,
            thread_id=p.thread,
            channel=p.channel,
            verify_binding=lambda: p.binding_ok,
            admit_action=lambda action: p.admission,
        )

    def body(self, p, **changes):
        body = dict(
            self.api.offer("token-a", p.ref),
            key="message-key",
            text="Read these recorded sources.",
        )
        body.pop("max_text_bytes", None)
        body.update(changes)
        return body

    def assert_zero(self, p, before):
        self.assertEqual(p.store.snapshot(p.pid), before)
        self.assertEqual(p.channel.calls, [])

    def reopen(self, p):
        old, owner = p.store, p.owner
        old.close()
        p.store = FrameJournal(p.root / "session.sqlite3")
        self.addCleanup(p.store.close)
        p.owner = p.store.acquire_owner(p.pid, "new-server")
        p.epoch += "-new"
        p.channel = Channel()
        self.controller(p)
        self.api = SessionApi(authenticate=self.authenticate)
        self.api.register(p.ref, **dict(p.registration, controller=p.controller))
        self.assertIsNot(p.store, old)
        self.assertNotEqual(p.owner, owner)

    def test_no_offer_or_caller_receipts_grant_message_authority(self):
        p = self.project(enabled=False)
        before = p.store.snapshot(p.pid)
        with self.assertRaises(SessionApiError):
            self.api.offer("token-a", p.ref)
        with self.assertRaises(SessionApiError):
            self.api.message(
                "token-a", p.ref, {"ready": True, "permit": "allowed", "text": "go"}
            )
        self.assert_zero(p, before)
        for value in (True, {"ready": True}, None):
            self.api._start_offers[p.ref] = lambda _: value
            with self.assertRaises(SessionApiError):
                self.api.offer("token-a", p.ref)
            self.assert_zero(p, before)

    def test_server_offer_is_durable_opaque_and_derives_exact_frame(self):
        p = self.project()
        body = self.body(p)
        self.assertEqual(
            set(body), {"key", "revision", "offer_ref", "offer_sha256", "text"}
        )
        self.assertEqual(p.channel.calls, [])
        offer_events = p.store.events(p.pid)
        self.assertEqual(
            self.api.offer("token-a", p.ref)["offer_ref"], body["offer_ref"]
        )
        self.assertEqual(p.store.events(p.pid), offer_events)
        result = self.api.message("token-a", p.ref, body)
        self.assertEqual(result["status"], "write-observed")
        self.assertFalse(result["replayed"])
        self.assertEqual(len(p.channel.calls), 1)
        self.assertEqual(p.channel.calls[0][0], "write")
        self.assertTrue(0 < p.channel.calls[0][1] <= 3)
        sent = p.channel.messages()[0]
        self.assertEqual(sent["method"], "turn/start")
        self.assertEqual(
            sent["params"],
            dict(
                threadId=p.thread,
                cwd=p.root.as_posix(),
                model="synthetic-model",
                input=[dict(type="text", text=body["text"], text_elements=[])],
            ),
        )
        serialized = json.dumps([body, result, self.api.view("token-a", p.ref)])
        for private in (
            p.thread,
            p.epoch,
            p.owner,
            p.pid,
            p.root.as_posix(),
            "synthetic-model",
            "permit_sha256",
        ):
            self.assertNotIn(private, serialized)

    def test_cross_project_and_caller_fields_are_rejected_before_intent(self):
        p, other = self.project(), self.project("b")
        body = self.body(p)
        before = p.store.snapshot(p.pid)
        for extra in (
            "threadId",
            "rpc_id",
            "connection_id",
            "owner",
            "source_root",
            "model",
            "permit_sha256",
            "ready",
            "receipts",
        ):
            with self.subTest(extra=extra), self.assertRaises(SessionApiError):
                self.api.message("token-a", p.ref, dict(body, **{extra: "caller"}))
            self.assert_zero(p, before)
        with self.assertRaises(SessionApiError):
            self.api.message("token-b", p.ref, body)
        self.assert_zero(p, before)
        before_other = other.store.snapshot(other.pid)
        body_other = dict(body, revision=before_other["revision"])
        with self.assertRaises(SessionApiError):
            self.api.message("token-a", other.ref, body_other)
        self.assert_zero(other, before_other)

    def test_offer_drift_text_bounds_and_revision_have_zero_write(self):
        p = self.project()
        body = self.body(p)
        before = p.store.snapshot(p.pid)
        for changes in (
            {"offer_sha256": "f" * 64},
            {"offer_ref": "unknown"},
            {"offer_ref": {}},
            {"offer_sha256": None},
            {"revision": 0},
            {"text": " "},
            {"text": "é" * 65},
            {"text": "\ud800"},
        ):
            with self.subTest(changes=changes), self.assertRaises(SessionApiError):
                self.api.message("token-a", p.ref, dict(body, **changes))
            self.assert_zero(p, before)
        for changes in (
            {"model": "different"},
            {"permit_sha256": "f" * 64},
            {"input_version": "f" * 64},
            {"source_root": self.root.as_posix()},
            {"limits": dict(max_text_bytes=128, max_starts=2, timeout_seconds=4)},
        ):
            p.offer_changes = changes
            with self.subTest(changes=changes), self.assertRaises(SessionApiError):
                self.api.message("token-a", p.ref, body)
            self.assert_zero(p, before)

    def test_concurrent_same_key_and_changed_payload_never_resend(self):
        p = self.project()
        body = self.body(p)
        barrier = threading.Barrier(2)

        def submit(_):
            barrier.wait(timeout=5)
            return self.api.message("token-a", p.ref, body)

        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(submit, range(2)))
        self.assertEqual(sorted(row["replayed"] for row in receipts), [False, True])
        before, calls = p.store.events(p.pid), list(p.channel.calls)
        p.offered = False
        self.assertTrue(
            self.api.message("token-a", p.ref, dict(body, revision=0))["replayed"]
        )
        self.api.action("token-a", p.ref, receipts[0]["action_ref"])
        self.api.view("token-a", p.ref)
        with self.assertRaises(SessionApiError):
            self.api.message("token-a", p.ref, dict(body, text="changed"))
        self.assertEqual(p.store.events(p.pid), before)
        self.assertEqual(p.channel.calls, calls)

    def test_revocation_after_api_intent_keeps_unknown_without_dispatch(self):
        p = self.project()
        body = self.body(p)
        original = p.offer
        self.api._start_offers[p.ref] = lambda context: (
            original(context) if p.offer_calls < 2 else None
        )
        with self.assertRaises(SessionApiError):
            self.api.message("token-a", p.ref, body)
        state = p.store.snapshot(p.pid)
        self.assertEqual(len(state["session_api_actions"]), 1)
        self.assertEqual(
            state["controller_actions"] if "controller_actions" in state else {}, {}
        )
        self.assertEqual(p.channel.calls, [])
        replay = self.api.message("token-a", p.ref, body)
        self.assertEqual(replay["status"], "dispatch-unobserved")
        self.assertTrue(replay["replayed"])
        self.assertEqual(p.channel.calls, [])

    def test_controller_refusal_and_start_budget_are_kept_separate(self):
        p = self.project()
        p.offer_changes = {
            "limits": dict(max_text_bytes=128, max_starts=1, timeout_seconds=3)
        }
        body = self.body(p)
        p.admission = False
        receipt = self.api.message("token-a", p.ref, body)
        self.assertEqual(receipt["status"], "refused")
        self.assertEqual(p.channel.calls, [])
        before = p.store.snapshot(p.pid)
        with self.assertRaises(SessionApiError):
            self.api.message(
                "token-a", p.ref, dict(body, key="new-key", revision=before["revision"])
            )
        self.assert_zero(p, before)

    def test_unsettled_start_and_native_question_do_not_start_another_turn(self):
        p = self.project()
        body = self.body(p)
        self.api.message("token-a", p.ref, body)
        before, calls = p.store.snapshot(p.pid), list(p.channel.calls)
        with self.assertRaises(SessionApiError):
            self.api.message(
                "token-a", p.ref, dict(body, key="second", revision=before["revision"])
            )
        self.assertEqual(p.store.snapshot(p.pid), before)
        self.assertEqual(p.channel.calls, calls)
        other = self.project("question")
        identity = dict(
            connection_id=other.epoch,
            native_id=4,
            thread_id=other.thread,
            turn_id="question-turn",
            item_id="question-item",
            approval_id=None,
        )
        other.store.record_request(
            other.pid,
            other.owner,
            identity,
            "item/tool/requestUserInput",
            {"questions": [{"id": "q", "question": "Choose?"}]},
            other.store.snapshot(other.pid)["revision"],
        )
        body = self.body(other)
        before = other.store.snapshot(other.pid)
        with self.assertRaises(SessionApiError):
            self.api.message("token-a", other.ref, body)
        self.assert_zero(other, before)

    def test_refusal_or_bound_terminal_allows_a_distinct_budgeted_start(self):
        for status in ("refused", "completed"):
            with self.subTest(status=status):
                p = self.project(status)
                p.admission = status != "refused"
                self.api.message("token-a", p.ref, self.body(p))
                if status == "completed":
                    request = p.channel.messages()[0]
                    frames = [
                        dict(id=request["id"], result=dict(turn=dict(id="turn-one"))),
                        dict(
                            method="turn/completed",
                            params=dict(
                                threadId=p.thread,
                                turn=dict(id="turn-one", status="completed"),
                            ),
                        ),
                    ]
                    p.channel.incoming = [
                        json.dumps(frame).encode() + b"\n" for frame in frames
                    ]
                    p.controller.pump(1)
                    p.controller.pump(1)
                p.admission = True
                result = self.api.message(
                    "token-a", p.ref, self.body(p, key="distinct-after-settled")
                )
                self.assertEqual(result["status"], "write-observed")
                self.assertEqual(
                    len(p.channel.messages()), 1 if status == "refused" else 2
                )

    def test_source_runtime_owner_and_input_drift_prevent_new_intent(self):
        for name in ("source", "runtime", "input", "owner"):
            with self.subTest(name=name):
                p = self.project(name)
                body = self.body(p)
                if name == "source":
                    p.source_ok = False
                elif name == "runtime":
                    p.binding_ok = False
                elif name == "input":
                    p.version = "f" * 64
                else:
                    p.store.release_owner(p.pid, p.owner)
                    p.store.acquire_owner(p.pid, "replacement")
                before = p.store.snapshot(p.pid)
                with self.assertRaises(SessionApiError):
                    self.api.message("token-a", p.ref, body)
                self.assert_zero(p, before)

    def test_real_sqlite_reopen_before_controller_intent_never_resends(self):
        p = self.project()
        body = self.body(p)
        original = p.channel
        with patch.object(p.controller, "client_action", side_effect=Crash):
            with self.assertRaises(Crash):
                self.api.message("token-a", p.ref, body)
        self.reopen(p)
        before = p.store.events(p.pid)
        replay = self.api.message("token-a", p.ref, body)
        self.assertEqual(replay["status"], "dispatch-unobserved")
        self.assertTrue(replay["replayed"])
        self.assertEqual(p.store.events(p.pid), before)
        self.assertEqual(original.calls + p.channel.calls, [])
        fresh = self.body(p, key="new-after-reopen")
        before = p.store.snapshot(p.pid)
        with self.assertRaises(SessionApiError) as rejected:
            self.api.message("token-a", p.ref, fresh)
        self.assertEqual(rejected.exception.code, "message-reconciliation-required")
        self.assert_zero(p, before)

    def test_real_sqlite_reopen_after_write_keeps_execution_unknown(self):
        p = self.project()
        body = self.body(p)
        original = p.channel
        with (
            patch.object(p.controller, "_save", side_effect=Crash),
            patch.object(p.controller, "_fault", side_effect=Crash),
        ):
            with self.assertRaises(Crash):
                self.api.message("token-a", p.ref, body)
        self.assertEqual(len(original.messages()), 1)
        self.reopen(p)
        before = p.store.events(p.pid)
        replay = self.api.message("token-a", p.ref, body)
        self.assertEqual(replay["status"], "execution-unknown")
        self.assertTrue(replay["replayed"])
        self.api.action("token-a", p.ref, replay["action_ref"])
        self.assertEqual(p.store.events(p.pid), before)
        self.assertEqual(p.channel.calls, [])
        self.assertEqual(len(original.messages()), 1)
        fresh = self.body(p, key="new-after-written-crash")
        before = p.store.snapshot(p.pid)
        with self.assertRaises(SessionApiError) as rejected:
            self.api.message("token-a", p.ref, fresh)
        self.assertEqual(rejected.exception.code, "message-reconciliation-required")
        self.assert_zero(p, before)


if __name__ == "__main__":
    unittest.main()
