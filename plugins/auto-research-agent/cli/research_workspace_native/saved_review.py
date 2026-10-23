"""Source-bound review of saved packages through the existing maintenance inbox.

Only trusted local bootstrap registers roots, independent pins and principals.
No active project, historical run, CoverageLedger or Core acceptance is created.
Embedding HTTP hosts must authenticate before calling this API; they must never
forward browser-supplied registration paths, pins or principal identities.
"""

import argparse
from copy import deepcopy
import json
from pathlib import Path

from stage1_deliverable.common import canonical, safe_path, sha

from .atlas_local_source import decode
from .maintenance_inbox import (
    HASH,
    KEY,
    PROJECT,
    REF,
    MAX_MESSAGE_BYTES,
    MaintenanceInbox,
    MaintenanceInboxError,
    _match,
    _private_path,
    _require,
)
from .saved_source_parser_runtime import read

SCHEMA = "SavedStage1ReviewRegistration.v1"
CONTEXT = "SavedStage1ReviewContext.v1"
OPERATIONS = {"submit-review", "request-fix", "request-handoff"}
MAX_FILE = 32 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_INPUT_VERSION_BYTES = 256
PIN_NAMES = {"index", "manifest", "view", "brief", "ledger", "run_manifest"}


def load_registration(path, expected_sha256):
    """Trusted local entry only; a hash submitted by a browser is not a pin."""
    _require(_match(HASH, expected_sha256), "registration-pin-required")
    raw = read(Path(path), 1024 * 1024)
    _require(sha(raw) == expected_sha256, "registration-pin-differs")
    return decode(raw)


def _validate_registration(value):
    fields = {
        "schema_version",
        "case_ref",
        "project_id",
        "input_version",
        "run_id",
        "artifacts",
        "pins",
        "works",
        "unknowns",
    }
    _require(isinstance(value, dict) and set(value) == fields, "registration-fields")
    _require(value["schema_version"] == SCHEMA, "registration-version")
    _require(_match(REF, value["case_ref"]), "invalid-case-reference")
    _require(_match(PROJECT, value["project_id"]), "invalid-project-identity")
    input_version = value["input_version"]
    _require(
        input_version is None
        or (type(input_version) is int and input_version >= 0)
        or (
            type(input_version) is str
            and bool(input_version.strip())
            and len(input_version.encode("utf8")) <= MAX_INPUT_VERSION_BYTES
        ),
        "invalid-original-input-version",
    )
    _require(
        value["run_id"] is None or _match(KEY, value["run_id"]), "invalid-original-run"
    )
    artifacts, pins, works = value["artifacts"], value["pins"], value["works"]
    _require(
        isinstance(artifacts, dict) and 1 <= len(artifacts) <= 1024, "artifact-bound"
    )
    total = 0
    for ref, artifact in artifacts.items():
        _require(_match(REF, ref), "invalid-artifact-reference")
        _require(
            isinstance(artifact, dict)
            and set(artifact) == {"path", "sha256", "bytes", "kind"}
            and _match(HASH, artifact["sha256"])
            and type(artifact["bytes"]) is int
            and 0 < artifact["bytes"] <= MAX_FILE
            and artifact["kind"] in {"utf8-text", "opaque"},
            "invalid-artifact-binding",
        )
        total += artifact["bytes"]
    _require(total <= MAX_TOTAL, "snapshot-byte-bound")
    _require(isinstance(pins, dict) and set(pins) == PIN_NAMES, "pin-fields")
    for name, ref in pins.items():
        _require(
            ref in artifacts if isinstance(ref, str) else ref is None, "pin-reference"
        )
        if name in {"index", "manifest", "view"}:
            _require(ref is not None, "required-package-pin")
    _require(isinstance(works, list) and 1 <= len(works) <= 500, "work-bound")
    seen = set()
    for work in works:
        _require(
            isinstance(work, dict)
            and set(work) == {"work_ref", "version_id", "source_refs"}
            and _match(KEY, work["work_ref"])
            and _match(KEY, work["version_id"]),
            "invalid-work-version",
        )
        identity = (work["work_ref"], work["version_id"])
        _require(identity not in seen, "duplicate-work-version")
        seen.add(identity)
        refs = work["source_refs"]
        _require(
            isinstance(refs, list)
            and 1 <= len(refs) <= 32
            and all(isinstance(ref, str) and ref in artifacts for ref in refs)
            and len(set(refs)) == len(refs),
            "invalid-work-source-bindings",
        )
    missing = {name for name, ref in pins.items() if ref is None}
    missing.update(name for name in ("run_id", "input_version") if value[name] is None)
    _require(
        isinstance(value["unknowns"], dict)
        and set(value["unknowns"]) == missing
        and all(
            isinstance(reason, str)
            and 0 < len(reason.encode("utf8")) <= 1024
            and reason.strip()
            for reason in value["unknowns"].values()
        ),
        "explicit-unknown-reasons-required",
    )


class SavedReviewService:
    """An extension of one borrowed MaintenanceInbox, never a research runner.

    Each registration is immutable. A changed package needs a new case/ref and
    review; this service cannot silently carry decisions across snapshots.
    Principal strings must come from the trusted embedding authentication layer.
    They record who submitted an opinion, not proof of human scientific review.
    """

    def __init__(
        self,
        inbox,
        *,
        package_root,
        registration_path,
        registration_sha256,
        allow_register=True,
    ):
        _require(isinstance(inbox, MaintenanceInbox), "maintenance-inbox-required")
        self.inbox = inbox
        self.root = Path(package_root)
        _require(
            self.root.is_absolute() and self.root.is_dir(), "package-root-required"
        )
        # Reuse the inbox's no-process private-storage boundary for package roots.
        _private_path(self.root / "saved-review-private-boundary")
        self.registration = load_registration(registration_path, registration_sha256)
        _validate_registration(self.registration)
        self.case_ref = self.registration["case_ref"]
        self.registration_sha256 = registration_sha256
        self.ref = (
            "saved-review-" + sha(canonical([self.case_ref, registration_sha256]))[:32]
        )
        self._raw = canonical(
            dict(
                package_root=str(self.root),
                registration=self.registration,
                registration_sha256=registration_sha256,
                saved_review_ref=self.ref,
            )
        )
        with inbox._lock:
            binding = inbox._binding(self.case_ref)
            _require(
                binding == self._case_binding(), "saved-review-case-binding-differs"
            )
            inbox.db.execute("""CREATE TABLE IF NOT EXISTS maintenance_review_bindings (
                case_ref TEXT PRIMARY KEY, registration TEXT NOT NULL,
                registration_sha256 TEXT NOT NULL)""")
            for action in ("UPDATE", "DELETE"):
                inbox.db.execute(
                    f"CREATE TRIGGER IF NOT EXISTS maintenance_review_no_{action} "
                    f"BEFORE {action} ON maintenance_review_bindings BEGIN "
                    "SELECT RAISE(ABORT, 'immutable saved review binding'); END"
                )
            inbox.db.execute("BEGIN IMMEDIATE")
            try:
                row = inbox.db.execute(
                    "SELECT * FROM maintenance_review_bindings WHERE case_ref=?",
                    (self.case_ref,),
                ).fetchone()
                if row is None:
                    _require(
                        allow_register is True, "saved-review-registration-required"
                    )
                    self._verify_files()
                    inbox.db.execute(
                        "INSERT INTO maintenance_review_bindings VALUES(?,?,?)",
                        (
                            self.case_ref,
                            self._raw.decode(),
                            sha(self._raw),
                        ),
                    )
                else:
                    _require(
                        row["registration"].encode() == self._raw
                        and row["registration_sha256"] == sha(self._raw),
                        "saved-review-registration-differs",
                    )
                inbox.db.commit()
            except BaseException:
                inbox.db.rollback()
                raise

    def _case_binding(self):
        return dict(
            project_id=self.registration["project_id"],
            index_sha256=self._pin("index"),
            manifest_sha256=self._pin("manifest"),
        )

    def _pin(self, name):
        ref = self.registration["pins"][name]
        return self.registration["artifacts"][ref]["sha256"] if ref else None

    def _bound(self, ref):
        _require(ref == self.ref, "saved-review-not-registered")
        _require(
            canonical(
                dict(
                    package_root=str(self.root),
                    registration=self.registration,
                    registration_sha256=self.registration_sha256,
                    saved_review_ref=self.ref,
                )
            )
            == self._raw,
            "saved-review-registration-differs",
        )
        _require(
            self.inbox._binding(self.case_ref) == self._case_binding(),
            "case-binding-differs",
        )
        row = self.inbox.db.execute(
            "SELECT * FROM maintenance_review_bindings WHERE case_ref=?",
            (self.case_ref,),
        ).fetchone()
        _require(
            row is not None
            and row["registration"].encode() == self._raw
            and row["registration_sha256"] == sha(self._raw),
            "saved-review-registration-differs",
        )

    def _read(self, ref):
        artifact = self.registration["artifacts"][ref]
        path = safe_path(self.root, artifact["path"])
        raw = read(path, artifact["bytes"])
        _require(
            len(raw) == artifact["bytes"] and sha(raw) == artifact["sha256"],
            "saved-review-source-changed",
        )
        if artifact["kind"] == "utf8-text":
            raw.decode("utf8")
        return raw

    def _verify_files(self):
        _private_path(self.root / "saved-review-private-boundary")
        for ref in self.registration["artifacts"]:
            self._read(ref)

    def _target(self, target):
        if target is None:
            return None
        _require(
            isinstance(target, dict)
            and set(target) == {"work_ref", "version_id", "source_ref"},
            "review-target-fields",
        )
        work = next(
            (
                w
                for w in self.registration["works"]
                if w["work_ref"] == target["work_ref"]
                and w["version_id"] == target["version_id"]
            ),
            None,
        )
        _require(
            work is not None
            and isinstance(target["source_ref"], str)
            and target["source_ref"] in work["source_refs"],
            "review-target-differs",
        )
        return dict(
            target,
            source_sha256=self.registration["artifacts"][target["source_ref"]][
                "sha256"
            ],
        )

    def _context(self):
        return dict(
            schema_version=CONTEXT,
            saved_review_ref=self.ref,
            project_id=self.registration["project_id"],
            input_version=self.registration["input_version"],
            original_run_id=self.registration["run_id"],
            registration_sha256=self.registration_sha256,
            source_snapshot_sha256=sha(
                canonical(
                    dict(
                        artifacts=self.registration["artifacts"],
                        works=self.registration["works"],
                    )
                )
            ),
            pins={name + "_sha256": self._pin(name) for name in sorted(PIN_NAMES)},
            unknowns=deepcopy(self.registration["unknowns"]),
            active_project_ref=None,
            stage1_complete=False,
            core_acceptance=False,
            execution_authorized=False,
        )

    def _records(self):
        rows = self.inbox.db.execute(
            "SELECT * FROM maintenance_feedback WHERE case_ref=? ORDER BY seq",
            (self.case_ref,),
        ).fetchall()
        result = []
        for row in rows:
            request = json.loads(row["request"])
            if "saved_review" not in request:
                continue
            public = self.inbox._public(row)
            detail = request["saved_review"]
            _require(
                isinstance(detail, dict)
                and canonical(detail.get("context")) == canonical(self._context())
                and detail.get("revision") == len(result),
                "saved-review-history-differs",
            )
            target = detail.get("target")
            if target is not None:
                _require(
                    isinstance(target, dict)
                    and set(target)
                    == {"work_ref", "version_id", "source_ref", "source_sha256"},
                    "saved-review-history-differs",
                )
                target = {k: v for k, v in target.items() if k != "source_sha256"}
            expected = self._offer(
                detail.get("principal_ref"),
                detail.get("operation"),
                target,
                len(result),
            )
            expected.update(decision=detail.get("decision"), confirmed=True)
            _require(
                canonical(detail) == canonical(expected)
                and request["stage"] == 1
                and set(request)
                == {"case_ref", "binding", "stage", "message", "key", "saved_review"}
                and row["feedback_ref"]
                == sha(canonical([self.case_ref, row["client_key"]])),
                "saved-review-history-differs",
            )
            _require(
                detail["decision"] in {"include", "exclude", "pending"}
                if detail["operation"] == "submit-review"
                else detail["decision"] is None,
                "saved-review-history-differs",
            )
            result.append(
                dict(public, **deepcopy(detail), review_revision=len(result) + 1)
            )
        return result

    def _offer(self, principal_ref, operation, target, revision):
        _require(_match(KEY, principal_ref), "trusted-principal-required")
        _require(
            isinstance(operation, str) and operation in OPERATIONS,
            "review-operation-rejected",
        )
        bound_target = self._target(target)
        _require(
            operation != "submit-review" or bound_target is not None,
            "review-target-required",
        )
        _require(
            operation != "request-handoff" or bound_target is None,
            "handoff-is-package-scoped",
        )
        basis = dict(
            context=self._context(),
            principal_ref=principal_ref,
            operation=operation,
            target=bound_target,
            revision=revision,
        )
        digest = sha(canonical(basis))
        return dict(
            basis, offer_ref="saved-review-offer-" + digest[:32], offer_sha256=digest
        )

    def offer(self, principal_ref, ref, operation, target=None):
        with self.inbox._lock:
            self._bound(ref)
            self._verify_files()
            return self._offer(principal_ref, operation, target, len(self._records()))

    def submit(self, principal_ref, ref, body, *, before_commit=None):
        """Save explicit review intent only. Same-key replay never rereads sources."""
        _require(
            isinstance(body, dict)
            and set(body) == {"key", "offer", "decision", "message", "confirmed"},
            "review-fields-rejected",
        )
        _require(body["confirmed"] is True, "review-confirmation-required")
        _require(_match(KEY, body["key"]), "invalid-idempotency-key")
        message = body["message"]
        _require(isinstance(message, str) and message.strip(), "message-required")
        try:
            _require(
                len(message.encode("utf8")) <= MAX_MESSAGE_BYTES,
                "message-byte-bound-exceeded",
            )
        except UnicodeError:
            raise MaintenanceInboxError("message-not-utf8") from None
        offered = body["offer"]
        _require(
            isinstance(offered, dict)
            and type(offered.get("revision")) is int
            and offered["revision"] >= 0,
            "review-offer-required",
        )
        target = offered.get("target")
        if target is not None:
            _require(
                isinstance(target, dict)
                and set(target)
                == {"work_ref", "version_id", "source_ref", "source_sha256"},
                "review-target-fields",
            )
            target = {k: v for k, v in target.items() if k != "source_sha256"}
        expected = self._offer(
            principal_ref, offered.get("operation"), target, offered["revision"]
        )
        _require(canonical(offered) == canonical(expected), "review-offer-differs")
        operation = expected["operation"]
        _require(
            isinstance(body["decision"], str)
            and body["decision"] in {"include", "exclude", "pending"}
            if operation == "submit-review"
            else body["decision"] is None,
            "review-decision-rejected",
        )
        _require(
            before_commit is None or callable(before_commit), "invalid-deadline-check"
        )
        detail = dict(expected, decision=body["decision"], confirmed=True)
        request = dict(
            case_ref=self.case_ref,
            binding=self._case_binding(),
            stage=1,
            key=body["key"],
            message=message,
            saved_review=detail,
        )
        with self.inbox._lock:
            self._bound(ref)

            def current():
                _require(
                    len(self._records()) == expected["revision"],
                    "stale-review-revision",
                )

            def guard():
                if before_commit is not None:
                    before_commit()
                self._bound(ref)
                self._verify_files()

            receipt = self.inbox._append(
                request, validate_current=current, before_commit=guard
            )
            # Reopen the committed row; response loss is recovered through action().
            result = self.action(ref, body["key"])
            result["replayed"] = receipt["replayed"]
            return result

    def history(self, ref, *, after_revision=0, limit=100):
        with self.inbox._lock:
            self._bound(ref)
            _require(
                type(after_revision) is int and 0 <= after_revision <= 1000,
                "invalid-cursor",
            )
            _require(type(limit) is int and 1 <= limit <= 100, "invalid-history-limit")
            return self._records()[after_revision : after_revision + limit]

    def submit_review(self, principal_ref, ref, body, **kwargs):
        _require(
            isinstance(body, dict)
            and isinstance(body.get("offer"), dict)
            and body["offer"].get("operation") == "submit-review",
            "review-operation-rejected",
        )
        return self.submit(principal_ref, ref, body, **kwargs)

    def request_fix(self, principal_ref, ref, body, **kwargs):
        _require(
            isinstance(body, dict)
            and isinstance(body.get("offer"), dict)
            and body["offer"].get("operation") == "request-fix",
            "review-operation-rejected",
        )
        return self.submit(principal_ref, ref, body, **kwargs)

    def request_handoff(self, principal_ref, ref, body, **kwargs):
        _require(
            isinstance(body, dict)
            and isinstance(body.get("offer"), dict)
            and body["offer"].get("operation") == "request-handoff",
            "review-operation-rejected",
        )
        return self.submit(principal_ref, ref, body, **kwargs)

    def action(self, ref, key):
        with self.inbox._lock:
            self._bound(ref)
            _require(_match(KEY, key), "invalid-idempotency-key")
            row = next((row for row in self._records() if row["key"] == key), None)
            _require(row is not None, "saved-review-action-not-found")
            return row

    def source(self, ref, target, *, offset=0, limit=4096):
        """Read bounded original UTF-8 text; positions are Unicode code points."""
        with self.inbox._lock:
            self._bound(ref)
            bound = self._target(target)
            _require(bound is not None, "review-target-required")
            _require(
                type(offset) is int
                and offset >= 0
                and type(limit) is int
                and 1 <= limit <= 4096,
                "source-page-bound",
            )
            _require(
                self.registration["artifacts"][bound["source_ref"]]["kind"]
                == "utf8-text",
                "source-is-not-text",
            )
            self._verify_files()
            value = self._read(bound["source_ref"]).decode("utf8")
            _require(offset <= len(value), "source-offset-outside-text")
            return dict(
                context=self._context(),
                target=bound,
                offset=offset,
                text=value[offset : offset + limit],
                total_characters=len(value),
                next_offset=min(offset + limit, len(value)),
            )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--registration", required=True)
    parser.add_argument("--expected-registration-sha256", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("register")
    offer = sub.add_parser("offer")
    offer.add_argument("--principal", required=True)
    offer.add_argument("--operation", choices=sorted(OPERATIONS), required=True)
    offer.add_argument("--target-json")
    submit = sub.add_parser("submit")
    submit.add_argument("--principal", required=True)
    submit.add_argument("--request", required=True)
    history = sub.add_parser("history")
    history.add_argument("--after-revision", type=int, default=0)
    history.add_argument("--limit", type=int, default=100)
    action = sub.add_parser("action")
    action.add_argument("--key", required=True)
    source = sub.add_parser("source")
    source.add_argument("--target-json", required=True)
    source.add_argument("--offset", type=int, default=0)
    source.add_argument("--limit", type=int, default=4096)
    args = parser.parse_args(argv)
    _require(
        args.command == "register" or Path(args.database).is_file(),
        "saved-review-registration-required",
    )
    registration = load_registration(
        args.registration, args.expected_registration_sha256
    )
    _validate_registration(registration)
    artifacts, pins = registration["artifacts"], registration["pins"]
    binding = dict(
        project_id=registration["project_id"],
        index_sha256=artifacts[pins["index"]]["sha256"],
        manifest_sha256=artifacts[pins["manifest"]]["sha256"],
    )
    inbox = MaintenanceInbox(args.database, {registration["case_ref"]: binding})
    try:
        service = SavedReviewService(
            inbox,
            package_root=args.package_root,
            registration_path=args.registration,
            registration_sha256=args.expected_registration_sha256,
            allow_register=args.command == "register",
        )
        target = (
            json.loads(args.target_json) if getattr(args, "target_json", None) else None
        )
        if args.command == "register":
            result = service._context()
        elif args.command == "offer":
            result = service.offer(args.principal, service.ref, args.operation, target)
        elif args.command == "submit":
            result = service.submit(
                args.principal, service.ref, decode(read(Path(args.request), 64 * 1024))
            )
        elif args.command == "history":
            result = service.history(
                service.ref, after_revision=args.after_revision, limit=args.limit
            )
        elif args.command == "source":
            result = service.source(
                service.ref, target, offset=args.offset, limit=args.limit
            )
        else:
            result = service.action(service.ref, args.key)
        print(canonical(result).decode())
        return 0
    finally:
        inbox.close()


if __name__ == "__main__":
    raise SystemExit(main())
