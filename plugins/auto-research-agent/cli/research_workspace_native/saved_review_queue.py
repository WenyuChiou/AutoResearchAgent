"""Explicit local maintenance admission for saved requests; never a task runner.

The trusted embedding server owns routing, principals and private paths. Queue
acceptance, an owner's claim and an owner's result report are separate records.
None authenticate scientific review, grant research or accept/import Stage 2.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from stage1_deliverable.common import canonical, safe_path, sha

from .maintenance_inbox import (
    KEY,
    REF,
    HASH,
    MaintenanceInbox,
    _match,
    _private_path,
    _require,
)
from .atlas_local_source import decode
from .saved_review import MAX_FILE, OPERATIONS, SavedReviewService, load_registration
from .saved_source_parser_runtime import read

SCHEMA = "SavedReviewQueuePolicy.v1"
STATUSES = {"admit": "queued-for-owner", "claim": "owner-claimed"}
TABLES = ("maintenance_queue_bindings", "maintenance_queue_events")
SOURCE_FIELDS = {
    "key",
    "feedback_ref",
    "record_sha256",
    "review_revision",
    "principal_ref",
    "operation",
    "context",
    "target",
}


def _fields(value, fields):
    _require(type(value) is dict and set(value) == set(fields), "queue-fields-rejected")


def _result_shape(ref):
    """Validate saved reference data without opening its current filesystem path."""
    _fields(ref, {"path", "bytes", "sha256"})
    name = ref["path"]
    _require(
        type(ref["bytes"]) is int
        and 0 < ref["bytes"] <= MAX_FILE
        and _match(HASH, ref["sha256"])
        and type(name) is str
        and name
        and "\\" not in name
        and ":" not in name
        and not PurePosixPath(name).is_absolute()
        and all(
            part not in {"", ".", ".."}
            and not part.endswith((".", " "))
            and part.split(".")[0].upper()
            not in {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                *(f"COM{i}" for i in range(10)),
                *(f"LPT{i}" for i in range(10)),
            }
            and not any(ord(c) < 32 or c in '<>"|?*' for c in part)
            for part in name.split("/")
        ),
        "queue-result-binding-invalid",
    )


def _body(action, body):
    fields = {
        "admit": {
            "key",
            "source_key",
            "source_record_sha256",
            "source_review_revision",
            "confirmed",
        },
        "claim": {"key", "revision", "confirmed"},
        "finish": {
            "key",
            "revision",
            "outcome",
            "reason",
            "new_delivery_ref",
            "confirmed",
        },
    }
    _require(type(action) is str and action in fields, "queue-action-invalid")
    _fields(body, fields[action])
    _require(
        _match(KEY, body["key"]) and body["confirmed"] is True,
        "queue-confirmation-required",
    )
    if action == "admit":
        _require(
            _match(KEY, body["source_key"])
            and _match(HASH, body["source_record_sha256"])
            and type(body["source_review_revision"]) is int
            and body["source_review_revision"] > 0,
            "queue-original-request-differs",
        )
    else:
        _require(
            type(body["revision"]) is int and body["revision"] >= 1,
            "stale-queue-revision",
        )
    if action == "finish":
        _require(
            type(body["outcome"]) is str and body["outcome"] in {"completed", "failed"},
            "queue-outcome-invalid",
        )
        _require(
            type(body["reason"]) is str
            and body["reason"].strip()
            and len(body["reason"].encode("utf8")) <= 4000,
            "queue-reason-required",
        )
        _require(
            body["outcome"] != "completed" or body["new_delivery_ref"] is not None,
            "queue-result-required",
        )
        if body["new_delivery_ref"] is not None:
            _result_shape(body["new_delivery_ref"])


class SavedReviewQueueService:
    """Borrow one inbox; callers authenticate before supplying principal labels.

    Policy is trusted local configuration, not browser input or proof of human
    identity. The service writes no result file and invokes no worker/callback
    except an optional trusted deadline check within the transaction.
    """

    def __init__(
        self, review, *, registration_path, policy, result_root, allow_register=True
    ):
        _require(
            isinstance(review, SavedReviewService), "saved-review-service-required"
        )
        _fields(policy, {"schema_version", "routes"})
        _require(policy["schema_version"] == SCHEMA, "queue-policy-version")
        _require(
            type(policy["routes"]) is dict and set(policy["routes"]) == OPERATIONS,
            "queue-policy-routes",
        )
        for route in policy["routes"].values():
            _fields(route, {"owner_ref", "admit_principals", "owner_principals"})
            _require(_match(REF, route["owner_ref"]), "queue-owner-invalid")
            for name in ("admit_principals", "owner_principals"):
                values = route[name]
                _require(
                    type(values) is list
                    and 1 <= len(values) <= 32
                    and all(_match(KEY, p) for p in values)
                    and len(set(values)) == len(values),
                    "queue-principals-invalid",
                )
        self.review, self.inbox = review, review.inbox
        self.registration_path = _private_path(registration_path)
        self.result_root = Path(result_root)
        _require(
            self.result_root.is_absolute() and self.result_root.is_dir(),
            "queue-result-root-required",
        )
        _private_path(self.result_root / "queue-private-boundary")
        self.result_root = self.result_root.resolve()
        _require(
            not self.result_root.is_relative_to(review.root.resolve())
            and not review.root.resolve().is_relative_to(self.result_root),
            "queue-result-source-overlap",
        )
        self.policy = deepcopy(policy)
        self._raw = canonical(
            dict(
                policy=self.policy,
                result_root=str(self.result_root),
                registration_sha256=review.registration_sha256,
                saved_review_ref=review.ref,
            )
        )
        with self.inbox._lock:
            self.inbox.db.executescript("""
                CREATE TABLE IF NOT EXISTS maintenance_queue_bindings (
                    case_ref TEXT PRIMARY KEY, payload TEXT NOT NULL, digest TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS maintenance_queue_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, case_ref TEXT NOT NULL,
                    queue_ref TEXT NOT NULL, revision INTEGER NOT NULL,
                    event_key TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL,
                    created_at TEXT NOT NULL, UNIQUE(case_ref,event_key),
                    UNIQUE(queue_ref,revision));
            """)
            for table in TABLES:
                for action in ("UPDATE", "DELETE"):
                    self.inbox.db.execute(
                        f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'immutable maintenance queue'); END"
                    )
            self.inbox.db.execute("BEGIN IMMEDIATE")
            try:
                row = self.inbox.db.execute(
                    "SELECT * FROM maintenance_queue_bindings WHERE case_ref=?",
                    (review.case_ref,),
                ).fetchone()
                if row is None:
                    _require(allow_register is True, "queue-registration-required")
                    self._guard()
                    self.inbox.db.execute(
                        "INSERT INTO maintenance_queue_bindings VALUES(?,?,?)",
                        (review.case_ref, self._raw.decode(), sha(self._raw)),
                    )
                else:
                    _require(
                        row["payload"].encode() == self._raw
                        and row["digest"] == sha(self._raw),
                        "queue-policy-binding-differs",
                    )
                self.inbox.db.commit()
            except BaseException:
                self.inbox.db.rollback()
                raise

    def _bound(self):
        self.review._bound(self.review.ref)
        _require(
            canonical(
                dict(
                    policy=self.policy,
                    result_root=str(self.result_root),
                    registration_sha256=self.review.registration_sha256,
                    saved_review_ref=self.review.ref,
                )
            )
            == self._raw,
            "queue-policy-binding-differs",
        )
        row = self.inbox.db.execute(
            "SELECT * FROM maintenance_queue_bindings WHERE case_ref=?",
            (self.review.case_ref,),
        ).fetchone()
        _require(
            row is not None
            and row["payload"].encode() == self._raw
            and row["digest"] == sha(self._raw),
            "queue-policy-binding-differs",
        )

    def _guard(self):
        value = load_registration(
            self.registration_path, self.review.registration_sha256
        )
        _require(
            canonical(value) == canonical(self.review.registration),
            "queue-registration-differs",
        )
        self.review._verify_files()
        _private_path(self.result_root / "queue-private-boundary")

    def _source(self, key):
        action = self.review.action(self.review.ref, key)
        return {
            name: deepcopy(action[name])
            for name in (
                "key",
                "feedback_ref",
                "record_sha256",
                "review_revision",
                "principal_ref",
                "operation",
                "context",
                "target",
            )
        }

    def _route(self, source):
        return self.policy["routes"][source["operation"]]

    def _access(self, principal, source, *, owner=False):
        route = self._route(source)
        allowed = route["owner_principals"] if owner else route["admit_principals"]
        _require(
            _match(KEY, principal)
            and principal in allowed
            and (owner or principal == source["principal_ref"]),
            "queue-principal-denied",
        )
        return route

    def _queue_ref(self, source):
        return (
            "saved-queue-"
            + sha(
                canonical(
                    [self.review.case_ref, source["feedback_ref"], sha(self._raw)]
                )
            )[:40]
        )

    def _decode(self, row, *, replayed=False):
        value = decode(row["payload"].encode())
        _fields(
            value,
            {
                "key",
                "principal_ref",
                "queue_ref",
                "action",
                "body",
                "source",
                "owner_ref",
                "policy_sha256",
                "queue_revision",
                "status",
                "new_delivery_ref",
                "owner_report_only",
                "execution_authorized",
                "research_execution_authorized",
                "Core_acceptance",
                "formal_Stage2_import",
            },
        )
        _require(
            canonical(value).decode() == row["payload"]
            and sha(canonical(value)) == row["digest"]
            and row["case_ref"] == self.review.case_ref
            and type(row["revision"]) is int
            and value["queue_ref"] == row["queue_ref"]
            and value["key"] == row["event_key"]
            and type(value["queue_revision"]) is int
            and value["queue_revision"] == row["revision"]
            and value["owner_report_only"] is True
            and all(
                value[name] is False
                for name in (
                    "execution_authorized",
                    "research_execution_authorized",
                    "Core_acceptance",
                    "formal_Stage2_import",
                )
            ),
            "queue-history-differs",
        )
        _fields(value["source"], SOURCE_FIELDS)
        source = self._source(value["source"]["key"])
        action, body = value["action"], value["body"]
        _body(action, body)
        route = self._access(value["principal_ref"], source, owner=action != "admit")
        revision = {"admit": 1, "claim": 2, "finish": 3}[action]
        if action == "admit":
            _require(
                body["source_key"] == source["key"]
                and body["source_record_sha256"] == source["record_sha256"]
                and body["source_review_revision"] == source["review_revision"],
                "queue-original-request-differs",
            )
        else:
            _require(body["revision"] == revision - 1, "queue-history-differs")
        expected = dict(
            key=body["key"],
            principal_ref=value["principal_ref"],
            queue_ref=self._queue_ref(source),
            action=action,
            body=body,
            source=source,
            owner_ref=route["owner_ref"],
            policy_sha256=sha(self._raw),
            queue_revision=revision,
            status=STATUSES[action]
            if action != "finish"
            else "owner-reported-" + body["outcome"],
            new_delivery_ref=body.get("new_delivery_ref"),
            owner_report_only=True,
            execution_authorized=False,
            research_execution_authorized=False,
            Core_acceptance=False,
            formal_Stage2_import=False,
        )
        _require(
            canonical(value) == canonical(expected),
            "queue-source-binding-differs",
        )
        return dict(
            value,
            record_sha256=row["digest"],
            recorded_at=row["created_at"],
            replayed=replayed,
        )

    def _rows(self, queue_ref):
        _require(_match(REF, queue_ref), "queue-reference-invalid")
        rows = self.inbox.db.execute(
            "SELECT * FROM maintenance_queue_events WHERE case_ref=? AND queue_ref=? ORDER BY revision",
            (self.review.case_ref, queue_ref),
        ).fetchall()
        _require(rows and len(rows) <= 3, "queue-action-unavailable")
        values = [self._decode(row) for row in rows]
        _require(
            [v["queue_revision"] for v in values] == list(range(1, len(values) + 1))
            and [v["action"] for v in values]
            == ["admit", "claim", "finish"][: len(values)]
            and [row["seq"] for row in rows] == sorted(row["seq"] for row in rows)
            and all(
                canonical(v["source"]) == canonical(values[0]["source"]) for v in values
            )
            and (
                len(values) < 3
                or values[2]["principal_ref"] == values[1]["principal_ref"]
            ),
            "queue-history-differs",
        )
        return values

    def _result(self, ref):
        _result_shape(ref)
        raw = read(safe_path(self.result_root, ref["path"]), ref["bytes"])
        _require(
            len(raw) == ref["bytes"] and sha(raw) == ref["sha256"],
            "queue-result-bytes-differ",
        )

    def _append(
        self, principal, queue_ref, source, action, body, *, before_commit=None
    ):
        _require(
            _match(KEY, body["key"]) and body["confirmed"] is True,
            "queue-confirmation-required",
        )
        _require(
            before_commit is None or callable(before_commit), "invalid-deadline-check"
        )
        route = self._access(principal, source, owner=action != "admit")
        semantic = dict(
            key=body["key"],
            principal_ref=principal,
            queue_ref=queue_ref,
            action=action,
            body=deepcopy(body),
            source=source,
            owner_ref=route["owner_ref"],
            policy_sha256=sha(self._raw),
        )
        self.inbox.db.execute("BEGIN IMMEDIATE")
        try:
            old = self.inbox.db.execute(
                "SELECT * FROM maintenance_queue_events WHERE case_ref=? AND event_key=?",
                (self.review.case_ref, body["key"]),
            ).fetchone()
            if old is not None:
                value = next(
                    v for v in self._rows(old["queue_ref"]) if v["key"] == body["key"]
                )
                value["replayed"] = True
                _require(
                    all(value[k] == v for k, v in semantic.items()),
                    "queue-idempotency-payload-differs",
                )
                self.inbox.db.commit()
                return value
            if action == "admit":
                _require(
                    self.inbox.db.execute(
                        "SELECT COUNT(*) FROM maintenance_queue_events WHERE case_ref=? AND revision=1",
                        (self.review.case_ref,),
                    ).fetchone()[0]
                    < 1000,
                    "queue-bound-exceeded",
                )
                _require(
                    self.inbox.db.execute(
                        "SELECT 1 FROM maintenance_queue_events WHERE queue_ref=?",
                        (queue_ref,),
                    ).fetchone()
                    is None,
                    "queue-request-already-admitted",
                )
                revision, status = 1, STATUSES[action]
            else:
                rows = self._rows(queue_ref)
                current = rows[-1]
                _require(
                    type(body["revision"]) is int
                    and body["revision"] == current["queue_revision"],
                    "stale-queue-revision",
                )
                _require(
                    current["status"]
                    == ("queued-for-owner" if action == "claim" else "owner-claimed"),
                    "queue-transition-refused",
                )
                if action == "finish":
                    _require(
                        current["principal_ref"] == principal,
                        "queue-claim-owner-differs",
                    )
                revision = current["queue_revision"] + 1
                status = (
                    STATUSES[action]
                    if action == "claim"
                    else "owner-reported-" + body["outcome"]
                )
            result = body.get("new_delivery_ref")

            def guard():
                if before_commit is not None:
                    before_commit()
                self._bound()
                self._guard()
                if result is not None:
                    self._result(result)

            guard()
            value = dict(
                semantic,
                queue_revision=revision,
                status=status,
                new_delivery_ref=deepcopy(result),
                owner_report_only=True,
                execution_authorized=False,
                research_execution_authorized=False,
                Core_acceptance=False,
                formal_Stage2_import=False,
            )
            raw = canonical(value)
            self.inbox.db.execute(
                "INSERT INTO maintenance_queue_events(case_ref,queue_ref,revision,event_key,payload,digest,created_at) VALUES(?,?,?,?,?,?,?)",
                (
                    self.review.case_ref,
                    queue_ref,
                    revision,
                    body["key"],
                    raw.decode(),
                    sha(raw),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            guard()
            row = self.inbox.db.execute(
                "SELECT * FROM maintenance_queue_events WHERE case_ref=? AND event_key=?",
                (self.review.case_ref, body["key"]),
            ).fetchone()
            output = self._decode(row)
            self.inbox.db.commit()
            return output
        except BaseException:
            self.inbox.db.rollback()
            raise

    def admit(self, principal, saved_review_ref, body, *, before_commit=None):
        body = deepcopy(body)
        _body("admit", body)
        with self.inbox._lock:
            self._bound()
            _require(
                saved_review_ref == self.review.ref, "queue-review-reference-differs"
            )
            source = self._source(body["source_key"])
            _require(
                type(body["source_review_revision"]) is int
                and source["review_revision"] == body["source_review_revision"]
                and source["record_sha256"] == body["source_record_sha256"],
                "queue-original-request-differs",
            )
            queue_ref = self._queue_ref(source)
            return self._append(
                principal, queue_ref, source, "admit", body, before_commit=before_commit
            )

    def claim(self, principal, queue_ref, body, *, before_commit=None):
        body = deepcopy(body)
        _body("claim", body)
        with self.inbox._lock:
            self._bound()
            return self._append(
                principal,
                queue_ref,
                self._rows(queue_ref)[0]["source"],
                "claim",
                body,
                before_commit=before_commit,
            )

    def finish(self, principal, queue_ref, body, *, before_commit=None):
        body = deepcopy(body)
        _body("finish", body)
        with self.inbox._lock:
            self._bound()
            return self._append(
                principal,
                queue_ref,
                self._rows(queue_ref)[0]["source"],
                "finish",
                body,
                before_commit=before_commit,
            )

    def history(self, principal, queue_ref, *, after_revision=0, limit=100):
        with self.inbox._lock:
            self._bound()
            _require(
                type(after_revision) is int
                and 0 <= after_revision <= 3
                and type(limit) is int
                and 1 <= limit <= 100,
                "queue-history-bound",
            )
            rows = self._rows(queue_ref)
            source = rows[0]["source"]
            _require(
                principal == source["principal_ref"]
                or principal in self._route(source)["owner_principals"],
                "queue-principal-denied",
            )
            return rows[after_revision : after_revision + limit]

    def action(self, principal, queue_ref, key=None):
        rows = self.history(principal, queue_ref)
        if key is None:
            return rows[-1]
        value = next((row for row in rows if row["key"] == key), None)
        _require(value is not None, "queue-key-unavailable")
        return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "database",
        "package-root",
        "registration",
        "expected-registration-sha256",
        "policy",
        "expected-policy-sha256",
        "result-root",
    ):
        parser.add_argument("--" + name, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("admit", "claim", "finish", "action", "history"):
        command = commands.add_parser(name)
        command.add_argument("--principal", required=True)
        if name != "admit":
            command.add_argument("--queue-ref", required=True)
        if name in {"admit", "claim", "finish"}:
            command.add_argument("--request", required=True)
        if name == "action":
            command.add_argument("--key")
        if name == "history":
            command.add_argument("--after-revision", type=int, default=0)
            command.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)
    _require(Path(args.database).is_file(), "saved-review-registration-required")
    registration = load_registration(
        args.registration, args.expected_registration_sha256
    )
    policy = load_registration(args.policy, args.expected_policy_sha256)
    refs = registration["artifacts"]
    binding = dict(
        project_id=registration["project_id"],
        index_sha256=refs[registration["pins"]["index"]]["sha256"],
        manifest_sha256=refs[registration["pins"]["manifest"]]["sha256"],
    )
    inbox = MaintenanceInbox(args.database, {registration["case_ref"]: binding})
    try:
        review = SavedReviewService(
            inbox,
            package_root=args.package_root,
            registration_path=args.registration,
            registration_sha256=args.expected_registration_sha256,
            allow_register=False,
        )
        service = SavedReviewQueueService(
            review,
            registration_path=args.registration,
            policy=policy,
            result_root=args.result_root,
            allow_register=args.command == "admit",
        )
        if args.command in {"admit", "claim", "finish"}:
            body = decode(read(Path(args.request), 64 * 1024))
            target = review.ref if args.command == "admit" else args.queue_ref
            result = getattr(service, args.command)(args.principal, target, body)
        elif args.command == "history":
            result = service.history(
                args.principal,
                args.queue_ref,
                after_revision=args.after_revision,
                limit=args.limit,
            )
        else:
            result = service.action(args.principal, args.queue_ref, args.key)
        print(canonical(result).decode())
        return 0
    finally:
        inbox.close()


if __name__ == "__main__":
    raise SystemExit(main())
