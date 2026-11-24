"""Bounded Wiki handoff to an explicitly installed saved-candidate application."""

from copy import deepcopy
import json
import re
from secrets import token_hex
from urllib.parse import urlsplit

from research_workspace_native.session_api import SessionApiError, _check, _hash
from stage1_deliverable.common import reject_links
from stage1_ledger.journal import canonical, digest


ROUTE = "/api/v9/saved-candidate/"
OPERATION = "admit-saved-candidate"
ACTION = "stage1-" + OPERATION
SCOPE = (
    "project_ref",
    "input_version",
    "brief_sha256",
    "material_id",
    "material_sha256",
)
BINDING = {*SCOPE, "revision", "ledger_state_sha256"}
INTENT = BINDING | {"key", "offer_ref", "request_sha256", "confirmed"}
PROVENANCE = (
    "source_uri",
    "original_type",
    "record",
    "work_id",
    "version_id",
    "reason",
)
REF = re.compile(r"[A-Za-z0-9_-]{1,64}")
FILE = re.compile(r"file-[0-9a-f]{32}")
KEY = re.compile(r"saved-candidate-[0-9a-f]{32}")
OFFER = re.compile(r"saved-offer-[0-9a-f]{32}")
WORK = re.compile(r"work-[0-9a-f]{64}")
VERSION = re.compile(r"version-[0-9a-f]{64}")
EVENT = re.compile(r"e[0-9]+")


def _version(value):
    return (type(value) is int and 0 <= value < 2**53) or (
        type(value) is str and 0 < len(value) <= 128
    )


def _identifier(pattern, value):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _same(actual, expected):
    return all(
        type(actual.get(key)) is type(value) and actual[key] == value
        for key, value in expected.items()
    )


def _scope(binding):
    return {key: binding[key] for key in SCOPE}


def _request_sha(body):
    return digest(
        canonical(
            {"kind": ACTION, "body": {k: v for k, v in body.items() if k != "revision"}}
        )
    )


def _validate(value, *, intent=False):
    _check(
        type(value) is dict
        and set(value) == (INTENT if intent else BINDING)
        and _identifier(REF, value["project_ref"])
        and _identifier(FILE, value["material_id"])
        and _version(value["input_version"])
        and type(value["revision"]) is int
        and 0 <= value["revision"] < 2**53
        and _hash(value["brief_sha256"])
        and _hash(value["material_sha256"])
        and (
            _hash(value["ledger_state_sha256"])
            or not intent
            and value["ledger_state_sha256"] is None
        ),
        "saved-candidate-binding-invalid",
        400,
    )
    if intent:
        _check(
            value["confirmed"] is True
            and _identifier(KEY, value["key"])
            and _identifier(OFFER, value["offer_ref"])
            and _hash(value["request_sha256"]),
            "saved-candidate-intent-invalid",
            400,
        )


def _public_url(value):
    if not isinstance(value, str) or not 0 < len(value) <= 4096:
        return False
    try:
        parts = urlsplit(value)
        return (
            parts.scheme in {"http", "https"}
            and bool(parts.hostname)
            and parts.username is None
            and parts.password is None
        )
    except ValueError:
        return False


class SavedCandidateAdmission:
    """Store intent before calling the application, and recover through its action reader."""

    def __init__(self, projects, stage1, store, application, provenance):
        self.projects, self.stage1, self.store = projects, stage1, store
        if application is not None and (
            application is not stage1 or application.intake is not projects
        ):
            raise ValueError("same Stage 1 application owner required")
        self.application = (
            application
            if callable(getattr(application, "admit_saved_candidate", None))
            else None
        )
        self.provenance = deepcopy(provenance or {})
        reject_links(store.db)
        with store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS saved_candidate_intents "
                "(scope_sha256 TEXT PRIMARY KEY, record TEXT NOT NULL, started INTEGER NOT NULL)"
            )

    def _check_binding(self, credential, binding, *, historical=False):
        ref = binding["project_ref"]
        with self.projects._lock:
            project = self.projects.read(credential, ref)
            project_keys = ("project_ref", "input_version", "brief_sha256")
            if not historical:
                project_keys += ("revision",)
            _check(
                _same(project, {key: binding[key] for key in project_keys}),
                "saved-candidate-project-stale",
            )
            if not historical:
                stage = (
                    self.stage1.read(credential, ref) if self.stage1 is not None else {}
                )
                if self.stage1 is not None:
                    _check(
                        _same(
                            stage,
                            {
                                key: binding[key]
                                for key in ("project_ref", "input_version", "revision")
                            },
                        ),
                        "saved-candidate-project-stale",
                    )
                ledger = stage.get("ledger") or {}
                state = (
                    ledger.get("state_sha256") if ledger.get("valid") is True else None
                )
                _check(
                    state == binding["ledger_state_sha256"],
                    "saved-candidate-ledger-stale",
                )

        identity = binding["material_id"]
        item = self.store._get("materials", identity)
        _check(
            item.get("project_ref") == ref, "saved-candidate-material-project-differs"
        )
        _check(
            item.get("sha256") == binding["material_sha256"]
            and item.get("stage") == 1
            and item.get("kind") == "manual-file"
            and item.get("status") == "registered",
            "saved-candidate-material-differs",
        )
        reject_links(self.store.root / "files" / (identity + ".bin"))
        self.store.file_bytes(identity)

    def _source(self, binding):
        row = self.provenance.get(binding["material_id"])
        scope = _scope(binding)
        claimed = row.get("binding") if isinstance(row, dict) else None
        if (
            not isinstance(claimed, dict)
            or set(claimed) != set(scope)
            or not _same(claimed, scope)
        ):
            return {}, list(PROVENANCE)
        source = {key: row.get(key) for key in PROVENANCE}
        valid = {
            "source_uri": _public_url(source["source_uri"]),
            "original_type": isinstance(source["original_type"], str)
            and bool(source["original_type"].strip()),
            "record": type(source["record"]) is dict
            and bool(source["record"].get("version")),
            "work_id": _identifier(WORK, source["work_id"]),
            "version_id": _identifier(VERSION, source["version_id"]),
            "reason": isinstance(source["reason"], str)
            and bool(source["reason"].strip()),
        }
        return source, [key for key in PROVENANCE if not valid[key]]

    @staticmethod
    def _application_body(binding, key, source):
        return {
            **{
                k: binding[k]
                for k in (
                    "revision",
                    "input_version",
                    "brief_sha256",
                    "ledger_state_sha256",
                    "material_sha256",
                )
            },
            **source,
            "key": key,
            "confirmed": True,
            "source_project_ref": binding["project_ref"],
            "source_relative": "files/" + binding["material_id"] + ".bin",
        }

    @staticmethod
    def _operation(db, scope):
        row = db.execute(
            "SELECT record, started FROM saved_candidate_intents WHERE scope_sha256=?",
            (scope,),
        ).fetchone()
        if row is None:
            return None, False
        operation = json.loads(row[0])
        intent, request = operation["intent"], operation["request"]
        _validate(intent, intent=True)
        _check(
            row[1] in (0, 1)
            and digest(canonical(_scope(intent))) == scope
            and _request_sha(request) == intent["request_sha256"]
            and intent["offer_ref"] == "saved-offer-" + intent["request_sha256"][:32]
            and canonical(request)
            == canonical(
                SavedCandidateAdmission._application_body(
                    intent, intent["key"], {key: request[key] for key in PROVENANCE}
                )
            ),
            "saved-candidate-operation-differs",
        )
        return operation, bool(row[1])

    def offer(self, credential, binding, check_deadline):
        _validate(binding)
        self._check_binding(credential, binding)
        source, missing = self._source(binding)
        reason = None
        if self.application is None:
            reason = "saved-candidate-admission-unconnected"
        elif binding["ledger_state_sha256"] is None:
            reason = "saved-candidate-ledger-unavailable"
        elif missing:
            reason = "saved-candidate-provenance-incomplete"
        scope = digest(canonical(_scope(binding)))
        with self.store.connect() as db:
            if reason is None:
                db.execute("BEGIN IMMEDIATE")
            operation, started = self._operation(db, scope)
            if started:
                return dict(
                    status="recovery",
                    intent=operation["intent"],
                    execution_authorized=False,
                )
            if reason is not None:
                return dict(
                    status="unavailable",
                    reason=reason,
                    missing=missing,
                    execution_authorized=False,
                )
            key = (
                operation["intent"]["key"]
                if operation
                else "saved-candidate-" + token_hex(16)
            )
            body = self._application_body(binding, key, source)
            request_sha = _request_sha(body)
            intent = dict(
                binding,
                key=key,
                offer_ref="saved-offer-" + request_sha[:32],
                request_sha256=request_sha,
                confirmed=True,
            )
            check_deadline()
            db.execute(
                "INSERT INTO saved_candidate_intents VALUES (?, ?, 0) "
                "ON CONFLICT(scope_sha256) DO UPDATE SET record=excluded.record "
                "WHERE record != excluded.record",
                (scope, canonical(dict(intent=intent, request=body)).decode("utf-8")),
            )
        offer = {key: value for key, value in intent.items() if key != "confirmed"}
        return dict(
            status="available",
            offer=dict(offer, operation=OPERATION, execution_authorized=False),
            execution_authorized=False,
        )

    def submit(self, credential, intent, check_deadline):
        _validate(intent, intent=True)
        _check(self.application is not None, "saved-candidate-admission-unconnected")
        self._check_binding(credential, intent)
        scope = digest(canonical(_scope(intent)))
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            operation, started = self._operation(db, scope)
            _check(
                operation is not None and _same(operation["intent"], intent),
                "saved-candidate-offer-differs",
            )
            if not started:
                source, missing = self._source(intent)
                _check(
                    not missing
                    and _request_sha(
                        self._application_body(intent, intent["key"], source)
                    )
                    == intent["request_sha256"],
                    "saved-candidate-offer-differs",
                )
                check_deadline()
                db.execute(
                    "UPDATE saved_candidate_intents SET started=1 WHERE scope_sha256=?",
                    (scope,),
                )
        if not started:
            try:
                self.application.admit_saved_candidate(
                    credential,
                    intent["project_ref"],
                    deepcopy(operation["request"]),
                    materials_root=self.store.root,
                    check_deadline=check_deadline,
                )
            except Exception:
                # A lost application reply cannot clear the durable send barrier.
                pass
        return self._result(credential, operation)

    def read(self, credential, intent):
        _validate(intent, intent=True)
        self._check_binding(credential, intent, historical=True)
        with self.store.connect() as db:
            operation, started = self._operation(db, digest(canonical(_scope(intent))))
        _check(
            started and _same(operation["intent"], intent),
            "saved-candidate-operation-unavailable",
            404,
        )
        return self._result(credential, operation)

    def _result(self, credential, operation):
        intent, body = operation["intent"], operation["request"]
        result = dict(intent, status="execution-unknown", execution_authorized=False)
        try:
            action = self.projects.action(
                credential, intent["key"], project_ref=intent["project_ref"]
            )
        except (SessionApiError, ValueError, OSError):
            return result
        identity = {
            key: intent[key] for key in ("project_ref", "key", "request_sha256")
        }
        # A receipt may describe the revision and ledger state after this write.
        # The request hash and immutable scope identify the original operation.
        if (
            not isinstance(action, dict)
            or not _same(
                action, dict(identity, kind=ACTION, execution_authorized=False)
            )
            or not _same(action, {key: intent[key] for key in SCOPE if key in action})
        ):
            return result
        if (
            action.get("status") == "saved"
            and _identifier(EVENT, action.get("event_id"))
            and _same(action, {key: body[key] for key in ("work_id", "version_id")})
        ):
            result.update(
                status="saved",
                candidate_event_id=action["event_id"],
                provenance="provided",
                identity_status="unverified",
                screening_status="not-screened",
                reading_evidence=None,
            )
        elif action.get("status") in {"failed", "known-unsent"}:
            result["status"] = action["status"]
        return result
