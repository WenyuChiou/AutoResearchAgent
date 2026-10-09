"""Private, source-bound UI feedback storage; never dispatch a Codex task.

Trusted bootstrap registers opaque case/project and exact view identities. This
inbox has no controller, process launcher, credentials, native RPC or permission
callback. Its recorded-not-dispatched status is not an execution receipt.
"""

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import threading

from stage1_deliverable.common import (
    DeliverableError,
    canonical,
    reject_links,
    safe_path,
    sha,
)

STATUS = "recorded-not-dispatched"
MAX_MESSAGE_BYTES = 4000
MAX_CASES, MAX_CASE_RECORDS = 64, 1000
REF = re.compile(r"[A-Za-z0-9_-]{1,128}")
PROJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}")
KEY = re.compile(r"[A-Za-z0-9._:-]{1,128}")
HASH = re.compile(r"[0-9a-f]{64}")


class MaintenanceInboxError(DeliverableError):
    """Rejected feedback, changed binding or private storage boundary."""


def _require(condition, code):
    if not condition:
        raise MaintenanceInboxError(code)


def _match(pattern, value):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _private_path(value):
    """Check physical metadata only; unlike Git preflight, launch no process."""
    path = Path(value)
    _require(path.is_absolute(), "absolute-private-path-required")
    reject_links(path)
    path = path.resolve()
    _require(path.parent.is_dir(), "existing-private-parent-required")
    for directory in (path.parent, *path.parent.parents):
        _require(not (directory / ".git").exists(), "private-path-inside-git")
        bare = (directory / "HEAD").is_file() and all(
            (directory / name).is_dir() for name in ("objects", "refs")
        )
        _require(not bare, "private-path-inside-bare-git")
    _require(not path.exists() or path.is_file(), "regular-private-file-required")
    for suffix in ("", "-wal", "-shm", "-journal"):
        safe_path(path.parent, path.name + suffix)
    return path


class MaintenanceInbox:
    """Append-only SQLite inbox; server registration is distinct from authority.

    bindings maps case_ref to exactly project_id/index_sha256/manifest_sha256.
    The caller authenticates browser access separately. Project isolation here
    is a lookup boundary, not multi-tenant authentication or execution admission.
    """

    def __init__(self, path, bindings):
        _require(
            isinstance(bindings, dict) and 1 <= len(bindings) <= MAX_CASES,
            "bounded-case-bindings-required",
        )
        self._bindings = {}
        fields = {"project_id", "index_sha256", "manifest_sha256"}
        for case_ref, binding in bindings.items():
            _require(_match(REF, case_ref), "invalid-case-reference")
            _require(
                isinstance(binding, dict)
                and set(binding) == fields
                and _match(PROJECT, binding["project_id"])
                and all(
                    _match(HASH, binding[name]) for name in fields - {"project_id"}
                ),
                "invalid-trusted-binding",
            )
            self._bindings[case_ref] = deepcopy(binding)
        self.path = _private_path(path)
        self._pid, self._lock = os.getpid(), threading.RLock()
        self.db = sqlite3.connect(
            self.path, timeout=5, isolation_level=None, check_same_thread=False
        )
        self.db.row_factory = sqlite3.Row
        try:
            self.db.executescript("""
                PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
                CREATE TABLE IF NOT EXISTS maintenance_bindings (
                    case_ref TEXT PRIMARY KEY, binding TEXT NOT NULL,
                    binding_sha256 TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS maintenance_feedback (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_ref TEXT NOT NULL, client_key TEXT NOT NULL,
                    feedback_ref TEXT NOT NULL UNIQUE, request TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status='recorded-not-dispatched'),
                    UNIQUE(case_ref,client_key));
            """)
            for table in ("maintenance_bindings", "maintenance_feedback"):
                for action in ("UPDATE", "DELETE"):
                    self.db.execute(
                        f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action} "
                        f"BEFORE {action} ON {table} BEGIN "
                        "SELECT RAISE(ABORT, 'immutable maintenance record'); END"
                    )
            self.db.execute("BEGIN IMMEDIATE")
            for case_ref, binding in self._bindings.items():
                raw = canonical(binding)
                old = self.db.execute(
                    "SELECT binding,binding_sha256 FROM maintenance_bindings "
                    "WHERE case_ref=?",
                    (case_ref,),
                ).fetchone()
                if old is None:
                    self.db.execute(
                        "INSERT INTO maintenance_bindings VALUES(?,?,?)",
                        (case_ref, raw.decode(), sha(raw)),
                    )
                else:
                    _require(
                        old["binding"].encode() == raw
                        and old["binding_sha256"] == sha(raw),
                        "saved-case-binding-differs",
                    )
            _require(
                self.db.execute("SELECT COUNT(*) FROM maintenance_bindings").fetchone()[
                    0
                ]
                <= MAX_CASES,
                "case-history-bound-exceeded",
            )
            self.db.commit()
        except BaseException:
            self.db.rollback()
            self.db.close()
            raise

    def _binding(self, case_ref):
        _require(os.getpid() == self._pid, "inbox-cannot-cross-processes")
        _private_path(self.path)
        _require(
            _match(REF, case_ref) and case_ref in self._bindings,
            "case-not-registered",
        )
        binding = self._bindings[case_ref]
        row = self.db.execute(
            "SELECT binding,binding_sha256 FROM maintenance_bindings WHERE case_ref=?",
            (case_ref,),
        ).fetchone()
        raw = canonical(binding)
        _require(
            row is not None
            and row["binding"].encode() == raw
            and row["binding_sha256"] == sha(raw),
            "saved-case-binding-differs",
        )
        return deepcopy(binding)

    def _public(self, row, *, replayed=False):
        request = json.loads(row["request"])
        raw = canonical(request)
        _require(
            sha(raw) == row["request_sha256"]
            and row["status"] == STATUS
            and request["case_ref"] == row["case_ref"]
            and request["key"] == row["client_key"]
            and request["binding"] == self._bindings[row["case_ref"]],
            "saved-feedback-binding-differs",
        )
        return dict(
            request["binding"],
            feedback_ref=row["feedback_ref"],
            case_ref=row["case_ref"],
            sequence=row["seq"],
            stage=request["stage"],
            message=request["message"],
            key=row["client_key"],
            record_sha256=row["request_sha256"],
            created_at=row["created_at"],
            status=STATUS,
            replayed=replayed,
        )

    def submit(self, case_ref, stage, message, key, *, before_commit=None):
        """A trusted server deadline check runs within the insertion transaction.

        The callback is never saved, dispatched or interpreted as permission.
        Historical duplicate lookup does not insert or invoke this callback.
        """
        with self._lock:
            _require(
                before_commit is None or callable(before_commit),
                "invalid-deadline-check",
            )
            binding = self._binding(case_ref)
            _require(type(stage) is int and 1 <= stage <= 6, "invalid-stage")
            _require(_match(KEY, key), "invalid-idempotency-key")
            _require(isinstance(message, str) and message.strip(), "message-required")
            try:
                length = len(message.encode("utf-8"))
            except UnicodeError:
                raise MaintenanceInboxError("message-not-utf8") from None
            _require(length <= MAX_MESSAGE_BYTES, "message-byte-bound-exceeded")
            request = dict(
                case_ref=case_ref,
                binding=binding,
                stage=stage,
                message=message,
                key=key,
            )
            raw = canonical(request)
            digest = sha(raw)
            self.db.execute("BEGIN IMMEDIATE")
            try:
                old = self.db.execute(
                    "SELECT * FROM maintenance_feedback WHERE case_ref=? AND client_key=?",
                    (case_ref, key),
                ).fetchone()
                if old is not None:
                    _require(
                        old["request_sha256"] == digest
                        and old["request"].encode() == raw,
                        "idempotency-payload-differs",
                    )
                    result = self._public(old, replayed=True)
                else:
                    count = self.db.execute(
                        "SELECT COUNT(*) FROM maintenance_feedback WHERE case_ref=?",
                        (case_ref,),
                    ).fetchone()[0]
                    _require(count < MAX_CASE_RECORDS, "case-feedback-bound-exceeded")
                    if before_commit is not None:
                        before_commit()
                    self.db.execute(
                        "INSERT INTO maintenance_feedback "
                        "(case_ref,client_key,feedback_ref,request,request_sha256,created_at,status) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (
                            case_ref,
                            key,
                            sha(canonical([case_ref, key])),
                            raw.decode(),
                            digest,
                            datetime.now(timezone.utc).isoformat(),
                            STATUS,
                        ),
                    )
                    row = self.db.execute(
                        "SELECT * FROM maintenance_feedback WHERE case_ref=? AND client_key=?",
                        (case_ref, key),
                    ).fetchone()
                    result = self._public(row)
                    if before_commit is not None:
                        before_commit()
                self.db.commit()
                return result
            except BaseException:
                self.db.rollback()
                raise

    def get(self, case_ref, key):
        with self._lock:
            self._binding(case_ref)
            _require(_match(KEY, key), "invalid-idempotency-key")
            row = self.db.execute(
                "SELECT * FROM maintenance_feedback WHERE case_ref=? AND client_key=?",
                (case_ref, key),
            ).fetchone()
            _require(row is not None, "feedback-not-found")
            return self._public(row)

    def history(self, case_ref, *, after_seq=0, limit=100):
        with self._lock:
            self._binding(case_ref)
            _require(
                type(after_seq) is int and 0 <= after_seq < 2**63, "invalid-cursor"
            )
            _require(type(limit) is int and 1 <= limit <= 100, "invalid-history-limit")
            rows = self.db.execute(
                "SELECT * FROM maintenance_feedback WHERE case_ref=? AND seq>? "
                "ORDER BY seq LIMIT ?",
                (case_ref, after_seq, limit),
            ).fetchall()
            return [self._public(row) for row in rows]

    def close(self):
        with self._lock:
            self.db.close()
