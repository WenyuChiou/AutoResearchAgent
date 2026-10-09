"""Real SQLite feedback persistence; no native/model/task dispatch."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from research_workspace_native.maintenance_inbox import (
    MaintenanceInbox,
    MaintenanceInboxError,
)


class MaintenanceInboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "feedback.sqlite3"
        self.bindings = {
            "same-title-a": dict(
                project_id="project-a",
                index_sha256="a" * 64,
                manifest_sha256="b" * 64,
            ),
            "same-title-b": dict(
                project_id="project-b",
                index_sha256="a" * 64,
                manifest_sha256="c" * 64,
            ),
        }
        self.inbox = MaintenanceInbox(self.path, self.bindings)

    def tearDown(self):
        self.inbox.close()
        self.temp.cleanup()

    def test_reopen_preserves_original_binding_text_and_record(self):
        text = "请放大图中的字体。\n保留原版色彩。"
        result = self.inbox.submit("same-title-a", 1, text, "feedback-1")
        self.assertEqual(result["status"], "recorded-not-dispatched")
        self.assertEqual(result["message"], text)
        self.assertEqual(result["manifest_sha256"], "b" * 64)
        self.assertFalse(result["replayed"])
        self.inbox.close()
        self.inbox = MaintenanceInbox(self.path, deepcopy(self.bindings))
        self.assertEqual(self.inbox.get("same-title-a", "feedback-1"), result)
        self.assertEqual(self.inbox.history("same-title-a"), [result])
        replay = self.inbox.submit("same-title-a", 1, text, "feedback-1")
        self.assertEqual(replay, dict(result, replayed=True))

    def test_parallel_duplicate_and_changed_payload_never_add_another_record(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(
                pool.map(
                    lambda _: self.inbox.submit(
                        "same-title-a", 2, "Fix labels.", "same-key"
                    ),
                    range(4),
                )
            )
        self.assertEqual(sum(not item["replayed"] for item in results), 1)
        self.assertEqual(len({item["feedback_ref"] for item in results}), 1)
        before = self.inbox.history("same-title-a")
        for stage, text in ((2, "Fix labels!"), (1, "Fix labels.")):
            with (
                self.subTest(stage=stage, text=text),
                self.assertRaisesRegex(
                    MaintenanceInboxError, "idempotency-payload-differs"
                ),
            ):
                self.inbox.submit("same-title-a", stage, text, "same-key")
        self.assertEqual(self.inbox.history("same-title-a"), before)

    def test_case_identity_prevents_same_title_index_and_key_conflation(self):
        a = self.inbox.submit("same-title-a", 1, "Font size.", "shared-key")
        b = self.inbox.submit("same-title-b", 1, "Font size.", "shared-key")
        self.assertNotEqual(a["feedback_ref"], b["feedback_ref"])
        self.assertNotEqual(a["manifest_sha256"], b["manifest_sha256"])
        self.assertEqual(self.inbox.history("same-title-a"), [a])
        self.assertEqual(self.inbox.history("same-title-b"), [b])
        self.assertEqual(self.inbox.get("same-title-b", "shared-key"), b)
        changed = deepcopy(self.bindings)
        changed["same-title-a"]["manifest_sha256"] = "d" * 64
        with self.assertRaisesRegex(
            MaintenanceInboxError, "saved-case-binding-differs"
        ):
            MaintenanceInbox(self.path, changed)
        self.assertEqual(self.inbox.get("same-title-a", "shared-key"), a)

    def test_invalid_feedback_leaves_history_empty(self):
        bad = (
            ("unknown", 1, "message", "key"),
            ("same-title-a", True, "message", "key"),
            ("same-title-a", 0, "message", "key"),
            ("same-title-a", 7, "message", "key"),
            ("same-title-a", "1", "message", "key"),
            ("same-title-a", 1, "", "key"),
            ("same-title-a", 1, " \n", "key"),
            ("same-title-a", 1, None, "key"),
            ("same-title-a", 1, "中" * 1334, "key"),
            ("same-title-a", 1, "\ud800", "key"),
            ("same-title-a", 1, "message", ""),
            ("same-title-a", 1, "message", " key"),
            ("same-title-a", 1, "message", "key\n"),
        )
        for args in bad:
            with (
                self.subTest(args=repr(args)),
                self.assertRaises(MaintenanceInboxError),
            ):
                self.inbox.submit(*args)
        self.assertEqual(self.inbox.history("same-title-a"), [])
        limit = self.inbox.submit("same-title-a", 6, "中" * 1333 + "a", "max")
        self.assertEqual(len(limit["message"].encode("utf-8")), 4000)

    def test_history_is_passive_paginated_and_exposes_no_private_authority(self):
        with (
            patch("subprocess.Popen", side_effect=AssertionError("no process")),
            patch("subprocess.run", side_effect=AssertionError("no process")),
        ):
            self.inbox.close()
            self.inbox = MaintenanceInbox(self.path, self.bindings)
            first = self.inbox.submit("same-title-a", 1, "First", "key-1")
            second = self.inbox.submit("same-title-a", 2, "Second", "key-2")
            total = self.inbox.db.total_changes
            self.assertEqual(self.inbox.history("same-title-a", limit=1), [first])
            self.assertEqual(
                self.inbox.history("same-title-a", after_seq=first["sequence"]),
                [second],
            )
            self.assertEqual(self.inbox.get("same-title-a", "key-1"), first)
            self.assertEqual(self.inbox.db.total_changes, total)
        text = json.dumps(first)
        for secret in (
            self.root.as_posix(),
            "owner",
            "permission",
            "RPC",
            "credential",
        ):
            self.assertNotIn(secret, text)
        with self.assertRaises(TypeError):
            self.inbox.submit("same-title-a", 1, "Bad", "key", owner="caller")
        for change in ({"limit": True}, {"limit": 101}, {"after_seq": -1}):
            with self.assertRaises(MaintenanceInboxError):
                self.inbox.history("same-title-a", **change)
        with self.assertRaises(MaintenanceInboxError):
            self.inbox.get("same-title-a", "missing-key")

    def test_records_are_append_only_and_registration_requires_private_storage(self):
        self.inbox.submit("same-title-a", 1, "Keep evidence.", "key")
        for table in ("maintenance_feedback", "maintenance_bindings"):
            for statement in (
                f"DELETE FROM {table}",
                f"UPDATE {table} SET case_ref='x'",
            ):
                with (
                    self.subTest(statement=statement),
                    self.assertRaises(sqlite3.IntegrityError),
                ):
                    self.inbox.db.execute(statement)
        with self.assertRaises(MaintenanceInboxError):
            MaintenanceInbox(Path("relative.sqlite3"), self.bindings)
        git_root = self.root / "git-checkout"
        git_root.mkdir()
        (git_root / ".git").write_text("gitdir: irrelevant\n")
        with self.assertRaises(MaintenanceInboxError):
            MaintenanceInbox(git_root / "inbox.sqlite3", self.bindings)
        bad = deepcopy(self.bindings)
        bad["same-title-a"]["root"] = "caller-path"
        with self.assertRaises(MaintenanceInboxError):
            MaintenanceInbox(self.root / "invalid.sqlite3", bad)

    def test_server_deadline_failure_rolls_back_before_persisting_feedback(self):
        observed = []

        def expired():
            observed.append(self.inbox.db.in_transaction)
            raise TimeoutError("server deadline expired after lock wait")

        with self.assertRaises(TimeoutError):
            self.inbox.submit(
                "same-title-a", 1, "Save later.", "expired", before_commit=expired
            )
        self.assertEqual(observed, [True])
        self.assertFalse(self.inbox.db.in_transaction)
        self.assertEqual(self.inbox.history("same-title-a"), [])
        self.inbox.close()
        self.inbox = MaintenanceInbox(self.path, self.bindings)
        self.assertEqual(self.inbox.history("same-title-a"), [])
        calls = []
        saved = self.inbox.submit(
            "same-title-a",
            1,
            "Save later.",
            "expired",
            before_commit=lambda: calls.append(self.inbox.db.in_transaction),
        )
        self.assertEqual(calls, [True, True])
        replay = self.inbox.submit(
            "same-title-a", 1, "Save later.", "expired", before_commit=expired
        )
        self.assertEqual(replay, dict(saved, replayed=True))
        self.assertEqual(observed, [True])

    def test_deadline_expiring_after_insertion_rolls_back_before_commit(self):
        expired = False
        original = self.inbox._public

        def public(row, **kwargs):
            nonlocal expired
            result = original(row, **kwargs)
            expired = True
            return result

        def deadline():
            if expired:
                raise TimeoutError("expired during insertion")

        with patch.object(self.inbox, "_public", side_effect=public):
            with self.assertRaises(TimeoutError):
                self.inbox.submit(
                    "same-title-a", 1, "Late save", "late", before_commit=deadline
                )
        self.assertFalse(self.inbox.db.in_transaction)
        self.assertEqual(self.inbox.history("same-title-a"), [])
        self.inbox.close()
        self.inbox = MaintenanceInbox(self.path, self.bindings)
        self.assertEqual(self.inbox.history("same-title-a"), [])

    def test_two_sqlite_handles_deduplicate_without_task_dispatch(self):
        other = MaintenanceInbox(self.path, self.bindings)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(
                    pool.map(
                        lambda inbox: inbox.submit("same-title-a", 2, "Shared.", "one"),
                        (self.inbox, other),
                    )
                )
            self.assertEqual(sum(not row["replayed"] for row in results), 1)
            self.assertEqual(len(self.inbox.history("same-title-a")), 1)
            self.assertEqual(
                other.history("same-title-a"), self.inbox.history("same-title-a")
            )
        finally:
            other.close()


if __name__ == "__main__":
    unittest.main()
