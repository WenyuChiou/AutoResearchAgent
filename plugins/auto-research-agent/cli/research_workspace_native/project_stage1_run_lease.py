"""Durable attenuation only; this journal cannot establish consent or authority."""

from contextlib import closing
import math
import os
import sqlite3
import stat

from stage1_deliverable.common import sha
from stage1_ledger.journal import canonical, decode

from .session_api import SessionApiError, _check


class RunLease:
    def __init__(self, intake, ref, document, pin):
        self.path = intake._path(ref, "stage1-run-lease-" + pin + ".sqlite")
        for suffix in ("-journal", "-wal", "-shm"):
            intake._path(ref, self.path.name + suffix)
        self.pin, self.document = pin, document

    def create(self):
        """Exclusive creation at consent time; checks never recreate a missing file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
            with closing(sqlite3.connect(self.path, timeout=1)) as db:
                db.execute("PRAGMA synchronous=FULL")
                db.execute("CREATE TABLE lease (id INTEGER PRIMARY KEY, body TEXT)")
                body = dict(
                    grant_sha256=self.pin,
                    issued_at=self.document["issued_at"],
                    expires_at=self.document["expires_at"],
                    highest_observed_time=self.document["issued_at"],
                    blocked=None,
                    cancellation=None,
                )
                db.execute(
                    "INSERT INTO lease VALUES (1,?)", (canonical(body).decode(),)
                )
                db.commit()
        except (OSError, sqlite3.Error) as exc:
            raise SessionApiError("stage1-run-lease-create-failed") from exc

    def _transaction(self, change):
        db = None
        try:
            info = self.path.lstat()
            _check(
                stat.S_ISREG(info.st_mode)
                and info.st_nlink == 1
                and 0 < info.st_size <= 131072,
                "stage1-run-lease-invalid",
            )
            db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=1)
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("BEGIN IMMEDIATE")
            _check(
                db.execute("PRAGMA quick_check").fetchall() == [("ok",)],
                "stage1-run-lease-invalid",
            )
            rows = db.execute("SELECT id,body FROM lease").fetchall()
            _check(
                len(rows) == 1 and rows[0][0] == 1 and len(rows[0][1]) <= 16384,
                "stage1-run-lease-invalid",
            )
            body = decode(rows[0][1].encode(), "Stage1 run lease")
            _check(
                type(body) is dict
                and set(body)
                == {
                    "grant_sha256",
                    "issued_at",
                    "expires_at",
                    "highest_observed_time",
                    "blocked",
                    "cancellation",
                }
                and body["grant_sha256"] == self.pin
                and body["issued_at"] == self.document["issued_at"]
                and body["expires_at"] == self.document["expires_at"]
                and type(body["highest_observed_time"]) in (int, float)
                and math.isfinite(body["highest_observed_time"])
                and body["highest_observed_time"] >= body["issued_at"]
                and body["blocked"] in (None, "expired", "clock-regressed", "revoked")
                and (
                    body["cancellation"] is None or type(body["cancellation"]) is dict
                ),
                "stage1-run-lease-invalid",
            )
            _check(
                (body["blocked"] == "revoked") == (body["cancellation"] is not None),
                "stage1-run-lease-invalid",
            )
            result = change(body)
            db.execute(
                "UPDATE lease SET body=? WHERE id=1", (canonical(body).decode(),)
            )
            db.commit()
            return result
        except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
            raise SessionApiError("stage1-run-lease-unavailable") from exc
        finally:
            if db is not None:
                db.close()

    def check(self, now):
        def observe(body):
            if body["blocked"] is None:
                if now < body["highest_observed_time"]:
                    body["blocked"] = "clock-regressed"
                elif now >= body["expires_at"]:
                    body["blocked"] = "expired"
            body["highest_observed_time"] = max(body["highest_observed_time"], now)
            return body["blocked"]

        # Commit before refusal, independently of any enclosing intake rollback.
        blocked = self._transaction(observe)
        _check(blocked is None, "stage1-run-grant-" + str(blocked))

    def revoke(self, body):
        semantic = {key: value for key, value in body.items() if key != "revision"}
        digest = sha(canonical({"kind": "stage1-run-revoke", "body": semantic}))

        def cancel(lease):
            existing = lease["cancellation"]
            if existing is not None:
                _check(
                    existing.get("request_sha256") == digest,
                    "stage1-run-cancellation-intent-differs",
                )
                return dict(existing, replayed=True)
            receipt = dict(
                kind="stage1-run-revoke",
                status="saved",
                request=semantic,
                request_sha256=digest,
                grant_ref=body["grant_ref"],
                future_dispatch_revoked=True,
                resources_refunded=False,
                process_cleanup_attested=False,
                replayed=False,
            )
            lease["blocked"] = "revoked"
            lease["cancellation"] = receipt
            return receipt

        return self._transaction(cancel)
