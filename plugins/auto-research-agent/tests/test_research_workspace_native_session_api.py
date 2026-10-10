"""Server-owned API checks using real SQLite and injected channels; no HTTP/model."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from test_research_workspace_native_controller import ANSWER, Channel, ERRORS
from research_workspace_native.controller import InjectedSessionController
from research_workspace_native.frame_journal import FrameJournal
from research_workspace_native.session_api import SessionApi, SessionApiError


class SessionApiTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root, self.auth = Path(folder.name).resolve(), []

        def authenticate(credential):
            self.auth.append(credential)
            return {"token-a": "principal-a", "token-b": "principal-b"}.get(credential)

        self.authenticate = authenticate
        self.api = SessionApi(authenticate=authenticate)

    def project(self, name="a", principal="principal-a"):
        root = self.root / name
        root.mkdir()
        index = root / "index.json"
        index.write_text(
            json.dumps({"title": "Same title", "input": name}), encoding="utf-8"
        )
        p = SimpleNamespace(
            root=root,
            index=index,
            pid="internal-" + name,
            ref="project-" + name,
            principal=principal,
            channel=Channel(),
            thread="private-thread-" + name,
            epoch="private-epoch-" + name,
            source_ok=True,
            binding_ok=True,
            source_checks=[],
            binding_checks=[],
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
            p.source_checks.append(binding)
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

        def binding():
            p.binding_checks.append(True)
            return p.binding_ok

        p.controller = InjectedSessionController(
            store=p.store,
            project_id=p.pid,
            owner=p.owner,
            connection_id=p.epoch,
            index_sha256=p.hash,
            thread_id=p.thread,
            channel=p.channel,
            verify_binding=binding,
            admit_action=lambda action: True,
        )
        p.registration = dict(
            controller=p.controller,
            principals={principal},
            source_root=root,
            index_sha256=p.hash,
            input_version=p.version,
            verify_source=source,
        )
        self.api.register(p.ref, **p.registration)
        return p

    def push(self, p, message):
        p.channel.queue(message)
        p.controller.pump()

    def test_view_exposes_trusted_project_identity_without_io(self):
        p = self.project()
        before = p.store.snapshot(p.pid)
        view = self.api.view("token-a", p.ref)
        self.assertEqual(view["project_id"], p.pid)
        self.assertEqual(view["project_ref"], p.ref)
        self.assertEqual(view["index_sha256"], p.hash)
        self.assertEqual(p.store.snapshot(p.pid), before)
        self.assertEqual(p.channel.messages(), [])

    def request(self, p, native_id=83, method="item/tool/requestUserInput"):
        self.push(
            p,
            {
                "id": native_id,
                "method": method,
                "params": {
                    "threadId": p.thread,
                    "turnId": "private-turn",
                    "itemId": "private-item",
                    "approvalId": "private-approval",
                    "questions": [{"id": "q", "question": "Choose?"}],
                },
            },
        )
        return self.api.view("token-a", p.ref)["requests"][-1]

    def body(self, p, request, **changes):
        body = dict(
            key="answer",
            revision=self.api.view("token-a", p.ref)["revision"],
            index_sha256=p.hash,
            input_version=p.version,
            request_ref=request["request_ref"],
            request_sha256=request["request_sha256"],
            result=ANSWER,
        )
        body.update(changes)
        return body

    def test_same_title_projects_and_principals_do_not_share_authority(self):
        a, b, c = self.project(), self.project("b", "principal-b"), self.project("c")
        request = self.request(a)
        before = b.store.snapshot(b.pid)
        counters = (len(b.source_checks), len(b.binding_checks), list(b.channel.calls))
        for action in (
            lambda: self.api.view("token-a", b.ref),
            lambda: self.api.answer("token-a", b.ref, {}),
            lambda: self.api.action("token-a", b.ref, "unknown"),
        ):
            with self.assertRaises(SessionApiError):
                action()
        self.assertEqual(b.store.snapshot(b.pid), before)
        self.assertEqual(
            (len(b.source_checks), len(b.binding_checks), b.channel.calls), counters
        )
        self.assertEqual(self.api.view("token-b", b.ref)["requests"], [])
        with self.assertRaises(SessionApiError):
            self.api.answer("token-a", c.ref, self.body(c, request))
        self.assertEqual(c.channel.calls, [])
        self.assertEqual(len({a.hash, b.hash, c.hash}), 3)
        self.assertEqual(len({a.version, b.version, c.version}), 3)

    def test_public_views_and_action_receipts_hide_native_identity(self):
        p = self.project()
        request = self.request(p, "private-native-request")
        result = self.api.answer("token-a", p.ref, self.body(p, request))
        public = [
            self.api.view("token-a", p.ref),
            result,
            self.api.action("token-a", p.ref, result["action_ref"]),
        ]
        self.assertEqual(public[0]["project_id"], p.pid)
        self.assertTrue(all("project_id" not in row for row in public[1:]))
        # Only the explicit project binding is public; native target identities stay private.
        public[0] = {
            key: value for key, value in public[0].items() if key != "project_id"
        }
        text = json.dumps(public)
        for secret in (
            p.owner,
            p.epoch,
            p.thread,
            p.pid,
            p.root.as_posix(),
            str(p.root),
            "private-native-request",
            "private-turn",
            "private-item",
            "private-approval",
        ):
            self.assertNotIn(secret, text)
        self.assertEqual(
            p.channel.messages(), [{"id": "private-native-request", "result": ANSWER}]
        )

    def test_concurrent_replay_and_lost_response_reads_never_write_twice(self):
        p = self.project()
        body = self.body(p, self.request(p))
        barrier = threading.Barrier(2)

        def submit():
            barrier.wait(timeout=5)
            return self.api.answer("token-a", p.ref, body)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: submit(), range(2)))
        self.assertEqual(sorted(r["replayed"] for r in results), [False, True])
        self.assertEqual(len(p.channel.messages()), 1)
        calls = list(p.channel.calls)
        self.api = SessionApi(authenticate=self.authenticate)
        self.api.register(p.ref, **p.registration)
        restored = self.api.action("token-a", p.ref, results[0]["action_ref"])
        self.assertEqual(restored["action_sha256"], results[0]["action_sha256"])
        self.assertEqual(restored["status"], "dispatched")
        for _ in range(2):
            self.api.view("token-a", p.ref)
            self.api.action("token-a", p.ref, results[0]["action_ref"])
        self.assertTrue(
            self.api.answer("token-a", p.ref, dict(body, revision=0))["replayed"]
        )
        with self.assertRaises(SessionApiError):
            self.api.answer(
                "token-a",
                p.ref,
                dict(body, result={"answers": {"q": {"answers": ["changed"]}}}),
            )
        self.assertEqual(p.channel.calls, calls)

    def test_stale_versions_hash_revision_and_unknown_fields_have_zero_io(self):
        p = self.project()
        body = self.body(p, self.request(p))
        before, calls = p.store.snapshot(p.pid), list(p.channel.calls)
        for changes in (
            {"revision": body["revision"] - 1},
            {"index_sha256": "f" * 64},
            {"input_version": "f" * 64},
            {"request_sha256": "f" * 64},
            {"request_ref": "unknown"},
            {"threadId": p.thread},
            {"owner": p.owner},
            {"command": "unrequested"},
        ):
            with self.subTest(changes=changes), self.assertRaises(SessionApiError):
                self.api.answer("token-a", p.ref, dict(body, **changes))
            self.assertEqual(p.channel.calls, calls)
            self.assertEqual(p.store.snapshot(p.pid), before)

    def test_decline_and_interrupt_derive_exact_native_targets_on_server(self):
        p = self.project()
        request = self.request(p, 91, "item/commandExecution/requestApproval")
        self.api.answer(
            "token-a", p.ref, self.body(p, request, result={"decision": "decline"})
        )
        self.assertEqual(
            p.channel.messages()[0], {"id": 91, "result": {"decision": "decline"}}
        )
        p.controller.client_action(
            "server-start",
            "turn/start",
            {"threadId": p.thread},
            p.controller.view()["revision"],
        )
        wire = p.channel.messages()[-1]
        self.push(p, {"id": wire["id"], "result": {"turn": {"id": "saved-turn"}}})
        view = self.api.view("token-a", p.ref)
        operation = view["operations"][0]
        body = dict(
            key="interrupt",
            revision=view["revision"],
            index_sha256=p.hash,
            input_version=p.version,
            action_ref=operation["action_ref"],
            action_sha256=operation["action_sha256"],
        )
        self.api.interrupt("token-a", p.ref, body)
        sent = p.channel.messages()[-1]
        self.assertEqual(sent["method"], "turn/interrupt")
        self.assertEqual(sent["params"], {"threadId": p.thread, "turnId": "saved-turn"})
        self.assertNotIn("rpc_id", body)

    def test_source_callback_and_index_byte_drift_fail_closed(self):
        for name in ("callback", "bytes", "binding", "index"):
            with self.subTest(name=name):
                p = self.project(name)
                body = self.body(p, self.request(p))
                if name == "callback":
                    p.source_ok = False
                elif name == "bytes":
                    p.index.write_bytes(b"changed")
                elif name == "index":
                    p.controller.index_sha256 = "f" * 64
                else:
                    p.binding_ok = False
                calls = list(p.channel.calls)
                with self.assertRaises(SessionApiError):
                    self.api.answer("token-a", p.ref, body)
                self.assertEqual(p.channel.calls, calls)
                self.assertEqual(p.channel.sent, [])

    def test_partial_write_unknown_is_durable_and_never_retried(self):
        p = self.project()
        body = self.body(p, self.request(p))
        p.channel.writes.extend((4, OSError("synthetic write failure")))
        with self.assertRaises(SessionApiError):
            self.api.answer("token-a", p.ref, body)
        calls = list(p.channel.calls)
        self.assertTrue(
            any(
                r["status"] == "execution-unknown"
                for r in p.store.snapshot(p.pid)["intents"].values()
            )
        )
        replay = self.api.answer("token-a", p.ref, body)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["status"], "execution-unknown")
        self.api.action("token-a", p.ref, replay["action_ref"])
        self.assertEqual(p.channel.calls, calls)

    def test_malformed_channel_and_owner_loss_preserve_unknown_without_retry(self):
        for name in ("malformed", "owner-loss"):
            with self.subTest(name=name):
                p = self.project(name)
                body = self.body(p, self.request(p))
                result = self.api.answer("token-a", p.ref, body)
                if name == "malformed":
                    p.channel.reads.append(b"\xff\n")
                    with self.assertRaises(ERRORS):
                        p.controller.pump()
                else:
                    p.store.release_owner(p.pid, p.owner)
                    p.store.acquire_owner(p.pid, "replacement")
                calls = list(p.channel.calls)
                self.assertTrue(
                    any(
                        r["status"] == "execution-unknown"
                        for r in p.store.snapshot(p.pid)["intents"].values()
                    )
                )
                if name == "malformed":
                    receipt = self.api.action("token-a", p.ref, result["action_ref"])
                    self.assertEqual(receipt["status"], "execution-unknown")
                    replay = self.api.answer("token-a", p.ref, body)
                    self.assertEqual(replay["status"], "execution-unknown")
                else:
                    with self.assertRaises(SessionApiError):
                        self.api.action("token-a", p.ref, result["action_ref"])
                    with self.assertRaises(SessionApiError):
                        self.api.answer("token-a", p.ref, body)
                self.assertEqual(p.channel.calls, calls)


if __name__ == "__main__":
    unittest.main()
