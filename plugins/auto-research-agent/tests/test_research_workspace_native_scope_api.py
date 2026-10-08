"""Real SQLite scope transactions with synthetic briefs and injected channels."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
import test_research_workspace_native_session_api as fixtures
from research_workspace_native.scope_api import ScopeApi
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import sha
from stage1_brief.brief import validate_brief


class ScopeApiTests(unittest.TestCase):
    project = fixtures.SessionApiTests.project

    def setUp(self):
        fixtures.SessionApiTests.setUp(self)
        self.scope = ScopeApi(self.api)

    def brief(self, name="a", principal="principal-a"):
        p = self.project(name, principal)
        value = dict(
            kind="ResearchBrief",
            schema_version="1.0.0",
            original_description="Compare synthetic toy systems.",
            needs=[dict(need_id="n", question="Which constraints matter?")],
            scope_fields=[
                dict(field="geography", material=True, reason="Population differs."),
                dict(field="duration", material=False, reason="Exploratory example."),
            ],
            suggestions=[],
            previous_sha256=None,
            decisions=[
                dict(
                    event_id="original",
                    field="duration",
                    status="specified",
                    value="one interval",
                    actor="original-operator",
                    authority="user",
                    source_ref="private-source-marker",
                    recorded_at="2026-01-01T00:00:00Z",
                    user_input="Use one synthetic interval.",
                )
            ],
        )
        p.brief_path = p.root / "brief.json"
        p.brief_raw = (json.dumps(value, indent=2) + "\n").encode()
        p.brief_path.write_bytes(p.brief_raw)
        p.brief_hash = sha(p.brief_raw)
        self.scope.register(
            p.ref, brief_path="brief.json", expected_sha256=p.brief_hash
        )
        return p

    def body(self, p, key="scope-a", **changes):
        view = self.scope.history("token-a", p.ref)
        parent = view["versions"][-1]
        result = dict(
            key=key,
            revision=view["revision"],
            index_sha256=p.hash,
            input_version=p.version,
            confirmed=True,
            parent_ref=parent["version_ref"],
            parent_sha256=parent["sha256"],
            choices=[
                dict(
                    field="geography",
                    status="specified",
                    value="Region A",
                    reason="Explicit synthetic choice.",
                    user_input="Use Region A.",
                )
            ],
        )
        result.update(changes)
        return result

    def test_append_preserves_original_bytes_decisions_and_execution_binding(self):
        p = self.brief()
        before = p.store.snapshot(p.pid)
        original = self.scope.history("token-a", p.ref)["versions"][0]
        result = self.scope.append("token-a", p.ref, self.body(p))
        saved = p.store.snapshot(p.pid)
        overlay = saved["scope_overlay"]
        new = overlay["versions"][result["version_ref"]]
        value = json.loads(new["raw_utf8"])
        self.assertEqual(value["previous_sha256"], p.brief_hash)
        self.assertEqual(value["decisions"][:-1], json.loads(p.brief_raw)["decisions"])
        self.assertTrue(validate_brief(value, require_confirmed=True)["valid"])
        event = value["decisions"][-1]
        self.assertEqual(event["actor"], "principal-a")
        self.assertEqual(event["authority"], "user")
        self.assertTrue(event["source_ref"].startswith("scope-request:"))
        self.assertEqual(p.brief_path.read_bytes(), p.brief_raw)
        for key in ("session_api_binding", "index_sha256", "protocol", "intents"):
            self.assertEqual(saved[key], before[key])
        self.assertFalse(result["execution_authorized"])
        self.assertEqual(p.channel.calls, [])
        self.assertEqual(
            self.scope.read("token-a", p.ref, original["version_ref"])[
                "pending_fields"
            ],
            ["geography"],
        )
        public = self.scope.read("token-a", p.ref, result["version_ref"])
        self.assertEqual(public["scope"]["geography"]["value"], "Region A")
        self.assertNotIn("private-source-marker", json.dumps(public))

    def test_lost_response_concurrent_replay_and_fresh_facade_do_not_append_again(self):
        p = self.brief()
        body = self.body(p)
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(
                pool.map(lambda _: self.scope.append("token-a", p.ref, body), range(4))
            )
        self.assertEqual(sum(not row["replayed"] for row in rows), 1)
        self.assertEqual(len({row["version_ref"] for row in rows}), 1)
        revision = p.store.snapshot(p.pid)["revision"]
        reopened = ScopeApi(self.api)
        reopened.register(p.ref, brief_path="brief.json", expected_sha256=p.brief_hash)
        replay = reopened.append("token-a", p.ref, dict(body, revision=0))
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["client_key"], body["key"])
        self.assertEqual(p.store.snapshot(p.pid)["revision"], revision)
        self.assertEqual(len(reopened.history("token-a", p.ref)["versions"]), 2)
        changed = deepcopy(body)
        changed["choices"][0]["value"] = "Region B"
        with self.assertRaises(SessionApiError):
            reopened.append("token-a", p.ref, changed)
        self.assertEqual(p.channel.calls, [])

    def test_stale_parent_and_invalid_or_forged_confirmation_do_not_commit(self):
        p = self.brief()
        body = self.body(p)
        before = p.store.snapshot(p.pid)
        for change in (
            {"confirmed": 1},
            {"confirmed": False},
            {"actor": "human"},
            {"revision": True},
            {"input_version": "f" * 64},
            {"parent_sha256": "f" * 64},
            {"choices": []},
            {"choices": [dict(body["choices"][0], field="unknown")]},
            {
                "choices": [
                    dict(
                        body["choices"][0],
                        status="unrestricted",
                        value="hidden restriction",
                    )
                ]
            },
        ):
            with self.subTest(change=change), self.assertRaises(SessionApiError):
                self.scope.append("token-a", p.ref, dict(body, **change))
            self.assertEqual(p.store.snapshot(p.pid), before)
        self.scope.append("token-a", p.ref, body)
        with self.assertRaises(SessionApiError):
            self.scope.append("token-a", p.ref, dict(body, key="other"))
        newer_revision = p.store.snapshot(p.pid)["revision"]
        with self.assertRaises(SessionApiError):
            self.scope.append(
                "token-a", p.ref, dict(body, key="other", revision=newer_revision)
            )
        self.assertEqual(len(self.scope.history("token-a", p.ref)["versions"]), 2)
        self.assertEqual(p.channel.calls, [])

    def test_review_exact_old_version_is_distinct_from_scope_or_execution_approval(
        self,
    ):
        p = self.brief()
        original = self.scope.history("token-a", p.ref)["versions"][0]
        self.scope.append("token-a", p.ref, self.body(p))
        body = dict(
            key="review",
            revision=p.store.snapshot(p.pid)["revision"],
            index_sha256=p.hash,
            input_version=p.version,
            confirmed=True,
            version_ref=original["version_ref"],
            version_sha256=original["sha256"],
            decision="changes-requested",
            note="Geography is still pending here.",
        )
        receipt = self.scope.review("token-a", p.ref, body)
        self.assertEqual(receipt["status"], "review-recorded")
        self.assertEqual(receipt["note"], body["note"])
        self.assertTrue(receipt["recorded_at"])
        self.assertFalse(receipt["execution_authorized"])
        self.assertTrue(self.scope.review("token-a", p.ref, body)["replayed"])
        with self.assertRaises(SessionApiError):
            self.scope.review("token-a", p.ref, dict(body, decision="reviewed"))
        self.assertEqual(len(self.scope.history("token-a", p.ref)["versions"]), 2)
        self.assertEqual(p.channel.calls, [])

    def test_auth_cross_project_source_and_root_rebinding_fail_closed(self):
        a, b = self.brief(), self.brief("b", "principal-b")
        source_checks = len(b.source_checks)
        for call in (
            lambda: self.scope.history("token-a", b.ref),
            lambda: self.scope.append("token-a", b.ref, self.body(a)),
        ):
            with self.assertRaises(SessionApiError):
                call()
        self.assertEqual(len(b.source_checks), source_checks)
        body = self.body(a)
        a.brief_path.write_bytes(a.brief_raw + b" ")
        with self.assertRaises(SessionApiError):
            self.scope.append("token-a", a.ref, body)
        self.assertEqual(len(a.store.snapshot(a.pid)["scope_overlay"]["order"]), 1)
        a.brief_path.write_bytes(a.brief_raw)
        with self.assertRaises((SessionApiError, OSError)):
            self.scope.register(
                a.ref, brief_path="other.json", expected_sha256=a.brief_hash
            )
        other = a.root / "other.json"
        other.write_bytes(a.brief_raw)
        with self.assertRaises(SessionApiError):
            self.scope.register(
                a.ref, brief_path="other.json", expected_sha256=a.brief_hash
            )
        self.assertEqual(a.channel.calls + b.channel.calls, [])

    def test_atomic_sql_failure_leaves_no_orphan_version_and_saved_bytes_detect_drift(
        self,
    ):
        p = self.brief()
        body = self.body(p)
        before = p.store.snapshot(p.pid)
        p.store.db.execute("""CREATE TEMP TRIGGER fail_scope BEFORE INSERT ON events
          WHEN NEW.kind='scope-append' BEGIN SELECT RAISE(ABORT,'synthetic disk failure'); END""")
        with self.assertRaises(SessionApiError):
            self.scope.append("token-a", p.ref, body)
        self.assertEqual(p.store.snapshot(p.pid), before)
        p.store.db.execute("DROP TRIGGER fail_scope")
        result = self.scope.append("token-a", p.ref, body)
        state = p.store.snapshot(p.pid)
        state["scope_overlay"]["versions"][result["version_ref"]]["raw_utf8"] += " "
        p.store.db.execute(
            "UPDATE projects SET state=? WHERE id=?", (json.dumps(state), p.pid)
        )
        with self.assertRaises(SessionApiError):
            self.scope.history("token-a", p.ref)
        self.assertEqual(p.channel.calls, [])

    def test_sqlite_writer_wait_deadline_rolls_back_append_and_review(self):
        def expired():
            raise TimeoutError

        for kind in ("append", "review"):
            with self.subTest(kind=kind):
                p = self.brief(kind + "-deadline")
                if kind == "append":
                    body = self.body(p, key=kind + "-deadline")
                    operation = self.scope.append
                else:
                    original = self.scope.history("token-a", p.ref)["versions"][0]
                    body = dict(
                        key=kind + "-deadline",
                        revision=p.store.snapshot(p.pid)["revision"],
                        index_sha256=p.hash,
                        input_version=p.version,
                        confirmed=True,
                        version_ref=original["version_ref"],
                        version_sha256=original["sha256"],
                        decision="changes-requested",
                        note="Synthetic review remains unresolved.",
                    )
                    operation = self.scope.review
                before = p.store.snapshot(p.pid)
                events = p.store.events(p.pid)
                entered = threading.Event()
                writer = sqlite3.connect(p.store.path, timeout=1, isolation_level=None)
                pool = ThreadPoolExecutor(max_workers=1)
                try:
                    writer.execute("BEGIN IMMEDIATE")
                    p.store.db.set_trace_callback(
                        lambda statement: (
                            entered.set() if statement == "BEGIN IMMEDIATE" else None
                        )
                    )
                    future = pool.submit(
                        operation,
                        "token-a",
                        p.ref,
                        body,
                        check_deadline=expired,
                    )
                    self.assertTrue(
                        entered.wait(2), "target SQLite write did not start"
                    )
                    self.assertFalse(future.done())
                    writer.rollback()
                    with self.assertRaises(SessionApiError) as raised:
                        future.result(timeout=5)
                    self.assertEqual(
                        (raised.exception.status, raised.exception.code),
                        (408, "request-timeout"),
                    )
                finally:
                    p.store.db.set_trace_callback(None)
                    if writer.in_transaction:
                        writer.rollback()
                    writer.close()
                    pool.shutdown(wait=True, cancel_futures=True)
                self.assertEqual(p.store.snapshot(p.pid), before)
                self.assertEqual(p.store.events(p.pid), events)

                accepted = operation("token-a", p.ref, body)
                saved = p.store.snapshot(p.pid)
                saved_events = p.store.events(p.pid)
                replay = operation("token-a", p.ref, body, check_deadline=expired)
                self.assertEqual(dict(replay, replayed=False), accepted)
                self.assertTrue(replay["replayed"])
                self.assertEqual(p.store.snapshot(p.pid), saved)
                self.assertEqual(p.store.events(p.pid), saved_events)
                self.assertEqual(p.channel.calls, [])


if __name__ == "__main__":
    unittest.main()
