"""Private SQLite project/owner checks, without the native action journal."""

import multiprocessing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from research_workspace_native.store import JournalError, ProjectStore
from stage1_deliverable.common import canonical, sha


def child_store(path, crash, queue):
    store = ProjectStore(path)
    try:
        token = store.acquire_owner("alpha", "child")
    except JournalError:
        queue.put("blocked")
        store.close()
        return
    store.bind_thread("alpha", token, "thread-a", store.snapshot("alpha")["revision"])
    if crash:
        os._exit(0)
    store.close()


class ProjectStoreTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name).resolve() / "projects.sqlite3"
        self.store = ProjectStore(self.path)
        self.addCleanup(self.store.close)
        self.store.bind_project("alpha", "a" * 64)
        self.owner = self.store.acquire_owner("alpha", "test")

    def state(self):
        return self.store.snapshot("alpha")

    def test_bound_project_thread_and_revision_are_durable(self):
        before = self.state()
        self.assertEqual(self.store.bind_project("alpha", "a" * 64), before)
        for digest in ("b" * 64, "malformed"):
            with self.assertRaises(JournalError):
                self.store.bind_project("alpha", digest)
        with self.assertRaisesRegex(JournalError, "stale revision"):
            self.store.bind_thread("alpha", self.owner, "thread-a", 0)
        self.assertEqual(self.state(), before)
        self.store.bind_thread("alpha", self.owner, "thread-a", before["revision"])
        with self.assertRaisesRegex(JournalError, "already bound"):
            self.store.bind_thread(
                "alpha", self.owner, "thread-b", self.state()["revision"]
            )
        self.store.bind_project("beta", "b" * 64)
        other = self.store.acquire_owner("beta", "test")
        with self.assertRaisesRegex(JournalError, "another project"):
            self.store.bind_thread(
                "beta", other, "thread-a", self.store.snapshot("beta")["revision"]
            )
        reader = ProjectStore(self.path)
        self.addCleanup(reader.close)
        self.assertEqual(reader.snapshot("alpha"), self.state())
        with self.assertRaisesRegex(JournalError, "exclusive owner"):
            reader.bind_thread(
                "alpha", self.owner, "thread-a", self.state()["revision"]
            )

    def test_atomic_events_and_recovery_preserve_completed_records(self):
        before, events = self.state(), self.store.events("alpha")
        with self.assertRaisesRegex(RuntimeError, "abort"):
            with self.store._edit(
                "alpha", self.owner, before["revision"], "fixture", {}
            ) as state:
                state["thread_id"] = "rolled-back"
                raise RuntimeError("abort")
        self.assertEqual((self.state(), self.store.events("alpha")), (before, events))
        with self.store._edit(
            "alpha", self.owner, before["revision"], "fixture", {}
        ) as state:
            state["intents"] = {
                "pending": {"status": "dispatching"},
                "done": {"status": "completed"},
            }
            state["requests"] = {
                "pending": {"status": "answer-sent"},
                "done": {"status": "request-resolved"},
            }
        self.store.release_owner("alpha", self.owner)
        old_owner, self.owner = (
            self.owner,
            self.store.acquire_owner("alpha", "recovery"),
        )
        state = self.state()
        self.assertEqual(
            state["intents"],
            {
                "pending": {"status": "execution-unknown"},
                "done": {"status": "completed"},
            },
        )
        self.assertEqual(
            state["requests"],
            {
                "pending": {"status": "execution-unknown"},
                "done": {"status": "request-resolved"},
            },
        )
        event = self.store.events("alpha")[-1]
        self.assertEqual(event["state_sha256"], sha(canonical(state)))
        self.assertEqual(
            event["payload"]["execution_unknown"],
            [["intents", "pending"], ["requests", "pending"]],
        )
        with self.assertRaisesRegex(JournalError, "exclusive owner"):
            self.store.release_owner("alpha", old_owner)
        for sql in ("DELETE FROM events", "UPDATE events SET kind='changed'"):
            with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable event"):
                self.store.db.execute(sql)

    def test_process_owner_exclusion_and_crash_preserve_project(self):
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        self.addCleanup(queue.close)
        for crash in (False, True):
            if crash:
                self.store.release_owner("alpha", self.owner)
            child = context.Process(
                target=child_store, args=(str(self.path), crash, queue)
            )
            child.start()
            child.join(10)
            self.assertFalse(child.is_alive())
            self.assertEqual(child.exitcode, 0)
            if not crash:
                self.assertEqual(queue.get(timeout=2), "blocked")
        self.owner = self.store.acquire_owner("alpha", "after-crash")
        self.assertEqual(self.state()["thread_id"], "thread-a")
        self.assertEqual(self.state()["owner"]["index_sha256"], "a" * 64)


if __name__ == "__main__":
    unittest.main()
