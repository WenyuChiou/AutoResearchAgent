"""Private persistent execution index, not a scientific stage ledger."""

import hashlib
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import stat
import time


class StudioError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(root, relative="."):
    root = Path(root).absolute()
    path = root / relative
    try:
        path.relative_to(root)
        path.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise StudioError("path outside private root") from error
    for part in [path, *path.parents]:
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if (
                stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 1024
            ):
                raise StudioError("links are not allowed")
    return path


def private_root(value):
    root = safe_path(value)
    if any((p / ".git").exists() for p in [root, *root.parents]):
        raise StudioError("data root must be outside every Git checkout")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


class Store:
    def __init__(self, root):
        self.root = private_root(root)
        self.path = safe_path(self.root, "studio.sqlite3")
        self.lease = safe_path(self.root, "server.lock").open("a+b")
        self.lease.write(b"0")
        self.lease.flush()
        self.lease.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.lease.close()
            raise StudioError("another server owns this data root") from error
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, request TEXT, status TEXT, created_at REAL,
                    updated_at REAL, exit_code INTEGER, error TEXT, manifest TEXT);
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT,
                    type TEXT, text TEXT, created_at REAL);
            """)
            changed = db.execute(
                "UPDATE runs SET status='interrupted', error=?, updated_at=? "
                "WHERE status IN ('queued','running')",
                (
                    "server restarted; inspect partial output; never automatically resumed",
                    time.time(),
                ),
            )
            if changed.rowcount:
                safe_path(self.root, "reconciliation-required").write_text(
                    "inspect surviving processes before new execution", encoding="utf-8"
                )

    @contextmanager
    def connect(self):
        safe_path(self.root, "studio.sqlite3")
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise StudioError("run not found", 404)
        result = dict(row)
        request = json.loads(result.pop("request"))
        result.update(request)
        result["manifest"] = json.loads(result["manifest"] or "{}")
        return result

    def list(self):
        with self.connect() as db:
            ids = db.execute(
                "SELECT id FROM runs ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        return [self.get(row["id"]) for row in ids]

    def create(self, request):
        now = time.time()
        with self.connect() as db:
            db.execute(
                "INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)",
                (
                    request["request_id"],
                    canonical(request),
                    "queued",
                    now,
                    now,
                    None,
                    None,
                    "{}",
                ),
            )

    def update(self, run_id, status, *, error=None, exit_code=None, manifest=None):
        with self.connect() as db:
            db.execute(
                "UPDATE runs SET status=?,updated_at=?,error=?,exit_code=?,"
                "manifest=COALESCE(?,manifest) WHERE id=?",
                (
                    status,
                    time.time(),
                    error,
                    exit_code,
                    canonical(manifest) if manifest is not None else None,
                    run_id,
                ),
            )
        self.event(run_id, "status", status if error is None else f"{status}: {error}")

    def event(self, run_id, kind, text):
        with self.connect() as db:
            db.execute(
                "INSERT INTO events(run_id,type,text,created_at) VALUES(?,?,?,?)",
                (run_id, kind, text, time.time()),
            )

    def detail(self, run_id, after):
        run = self.get(run_id)
        with self.connect() as db:
            events = [
                dict(r)
                for r in db.execute(
                    "SELECT seq,type,text,created_at FROM events WHERE run_id=? AND seq>? "
                    "ORDER BY seq LIMIT 200",
                    (run_id, after),
                )
            ]
        return {
            "run": run,
            "manifest": run["manifest"],
            "events": events,
            "cursor": events[-1]["seq"] if events else after,
            "artifacts": run["manifest"].get("artifacts", []),
        }

    def close(self):
        self.lease.close()
