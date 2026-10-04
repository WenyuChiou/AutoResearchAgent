"""Durable project bindings, exclusive owners and immutable state events."""

from contextlib import contextmanager
import json
import os
import re
import sqlite3
import threading
import uuid

from stage1_deliverable.common import (
    DeliverableError,
    canonical,
    identifier,
    private_output,
    safe_path,
    sha,
)


class JournalError(DeliverableError):
    """An identity, revision, ownership or transition conflicts with saved history."""


def _require(condition, message):
    if not condition:
        raise JournalError(message)


class ProjectStore:
    def __init__(self, path):
        self.path = private_output(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for suffix in ("", "-wal", "-shm", "-journal"):
            safe_path(self.path.parent, self.path.name + suffix)
        self._lock, self._owners = threading.RLock(), {}
        self._pid = os.getpid()
        self.db = sqlite3.connect(
            self.path, timeout=5, isolation_level=None, check_same_thread=False
        )
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (project TEXT NOT NULL, revision INTEGER NOT NULL,
                kind TEXT NOT NULL, payload TEXT NOT NULL, state_sha256 TEXT NOT NULL,
                PRIMARY KEY(project, revision));
            CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
                BEGIN SELECT RAISE(ABORT, 'immutable event'); END;
            CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
                BEGIN SELECT RAISE(ABORT, 'immutable event'); END;
        """)

    def _read(self, project_id):
        _require(os.getpid() == self._pid, "journal cannot be shared across processes")
        row = self.db.execute(
            "SELECT state FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        _require(row is not None, "unknown project")
        return json.loads(row[0])

    @contextmanager
    def _edit(self, project_id, owner, revision, kind, payload, *, acquiring=False):
        with self._lock:
            _require(
                os.getpid() == self._pid, "journal cannot be shared across processes"
            )
            self.db.execute("BEGIN IMMEDIATE")
            try:
                state = self._read(project_id)
                if not acquiring:
                    _require(
                        owner is not None
                        and project_id in self._owners
                        and self._owners[project_id][0] == owner
                        and state["owner"] is not None
                        and state["owner"]["token"] == owner,
                        "exclusive owner required",
                    )
                if revision is not None:
                    _require(
                        type(revision) is int and revision == state["revision"],
                        "stale revision",
                    )
                before = canonical(state)
                yield state
                if canonical(state) != before:
                    state["revision"] += 1
                    raw = canonical(state)
                    self.db.execute(
                        "UPDATE projects SET state=? WHERE id=?",
                        (raw.decode(), project_id),
                    )
                    self.db.execute(
                        "INSERT INTO events VALUES(?,?,?,?,?)",
                        (
                            project_id,
                            state["revision"],
                            kind,
                            canonical(payload).decode(),
                            sha(raw),
                        ),
                    )
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise

    def bind_project(self, project_id, index_sha256):
        _require(os.getpid() == self._pid, "journal cannot be shared across processes")
        identifier(project_id)
        _require(
            isinstance(index_sha256, str)
            and re.fullmatch(r"[0-9a-f]{64}", index_sha256),
            "invalid index hash",
        )
        with self._lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute(
                "SELECT state FROM projects WHERE id=?", (project_id,)
            ).fetchone()
            if row:
                _require(
                    json.loads(row[0])["index_sha256"] == index_sha256,
                    "project index binding differs",
                )
            else:
                state = {
                    "project_id": project_id,
                    "index_sha256": index_sha256,
                    "thread_id": None,
                    "revision": 0,
                    "owner": None,
                    "intents": {},
                    "requests": {},
                    "turns": {},
                }
                raw = canonical(state)
                self.db.execute(
                    "INSERT INTO projects VALUES(?,?)", (project_id, raw.decode())
                )
                self.db.execute(
                    "INSERT INTO events VALUES(?,?,?,?,?)",
                    (
                        project_id,
                        0,
                        "project-bound",
                        canonical({"index_sha256": index_sha256}).decode(),
                        sha(raw),
                    ),
                )
        return self.snapshot(project_id)

    def acquire_owner(self, project_id, owner_id):
        identifier(owner_id)
        with self._lock:
            _require(project_id not in self._owners, "owner already acquired")
            self._read(project_id)
            path = safe_path(
                self.path.parent,
                self.path.name + ".owner-" + sha(project_id.encode()) + ".sqlite3",
            )
            lock = sqlite3.connect(
                path, timeout=0, isolation_level=None, check_same_thread=False
            )
            try:
                lock.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as error:
                lock.close()
                raise JournalError("project already has an execution owner") from error
            token = uuid.uuid4().hex
            recovered = {"owner_id": owner_id, "token": token, "execution_unknown": []}
            try:
                with self._edit(
                    project_id,
                    None,
                    None,
                    "owner-acquired",
                    recovered,
                    acquiring=True,
                ) as state:
                    for collection, terminal in (
                        ("intents", "completed"),
                        ("requests", "request-resolved"),
                    ):
                        for key, item in state[collection].items():
                            if item["status"] != terminal:
                                item["status"] = "execution-unknown"
                                recovered["execution_unknown"].append([collection, key])
                    state["owner"] = {
                        "owner_id": owner_id,
                        "token": token,
                        "index_sha256": state["index_sha256"],
                    }
                self._owners[project_id] = (token, lock)
            except BaseException:
                lock.close()
                raise
            return token

    def release_owner(self, project_id, owner):
        with self._lock:
            with self._edit(
                project_id, owner, None, "owner-released", {"token": owner}
            ) as state:
                state["owner"] = None
            self._owners.pop(project_id)[1].close()

    def bind_thread(self, project_id, owner, thread_id, expected_revision):
        _require(isinstance(thread_id, str) and thread_id, "thread ID required")
        with self._edit(
            project_id,
            owner,
            expected_revision,
            "thread-bound",
            {"thread_id": thread_id},
        ) as state:
            _require(
                state["thread_id"] in (None, thread_id), "project thread already bound"
            )
            for intent in state["intents"].values():
                if intent["method"] == "thread/start":
                    _require(
                        intent["status"] == "completed"
                        and intent["evidence"].get("thread_id") == thread_id,
                        "thread/start needs reconciliation with its native thread ID",
                    )
            others = self.db.execute(
                "SELECT state FROM projects WHERE id!=?", (project_id,)
            ).fetchall()
            _require(
                all(json.loads(row[0])["thread_id"] != thread_id for row in others),
                "thread already belongs to another project",
            )
            state["thread_id"] = thread_id
        return self.snapshot(project_id)

    def snapshot(self, project_id):
        with self._lock:
            return self._read(project_id)

    def events(self, project_id):
        with self._lock:
            return [
                dict(row, payload=json.loads(row["payload"]))
                for row in self.db.execute(
                    "SELECT * FROM events WHERE project=? ORDER BY revision",
                    (project_id,),
                )
            ]

    def close(self):
        """Drop process locks; a later owner reconciles unfinished records, never resends."""
        with self._lock:
            for _, connection in self._owners.values():
                connection.close()
            self._owners.clear()
            self.db.close()
