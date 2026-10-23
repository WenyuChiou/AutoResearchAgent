"""Universal, offline project intake backed by the real ResearchBrief compiler.

These records capture researcher choices. They are not native execution permits,
authenticated research conclusions, or permission to acquire a source. Reads and
replayed actions never run a model, search, launcher, or the coverage compiler.
"""

from copy import deepcopy
from datetime import datetime, timezone
import json
import sqlite3
import threading
import uuid

from stage1_brief.brief import (
    CHOICES,
    compile_confirmed,
    create_brief,
    validate_bound_plan,
    validate_brief,
)
from stage1_brief.formal_target import (
    formal_question,
    prepare_formal_intake,
    submit_formal_target,
)
from stage1_deliverable.common import identifier, private_output, safe_path, sha
from stage1_ledger.journal import canonical, decode
from .session_api import SessionApiError, _check

from .project_intake_contract import (
    BUDGETS as BUDGETS,
    CONSENTS as CONSENTS,
    MAX_ACTIONS,
    MAX_PROJECTS,
    MAX_REQUEST,
    MAX_VERSIONS,
    _fields as _fields,
    _resources,
    _scope,
    _text,
    refusal_shape,
)


class ProjectIntakeService:
    """Principal-scoped projects with immutable brief revisions and durable intents.

    Trusted bootstrap selects one private root. Browser bodies cannot select paths,
    principals, project IDs, connection epochs, RPC methods or execution permits.
    A crash gap remains unknown; the same key can only recover its saved history.
    """

    def __init__(self, root, *, authenticate):
        _check(callable(authenticate), "identity-check-required")
        self.root = private_output(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.authenticate = authenticate
        self._query_service = None
        self._lock = threading.RLock()
        path = safe_path(self.root, "project-intake.sqlite")
        for suffix in ("-wal", "-shm", "-journal"):
            safe_path(self.root, path.name + suffix)
        self.db = sqlite3.connect(
            path, timeout=5, isolation_level=None, check_same_thread=False
        )
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS intake_projects (
                ref TEXT PRIMARY KEY, principal TEXT NOT NULL, state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS intake_actions (
                principal TEXT NOT NULL, project TEXT NOT NULL, key TEXT NOT NULL,
                request_hash TEXT NOT NULL, receipt TEXT NOT NULL,
                PRIMARY KEY(principal, project, key));
            CREATE TABLE IF NOT EXISTS intake_events (
                id INTEGER PRIMARY KEY, project TEXT NOT NULL, kind TEXT NOT NULL,
                payload TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS intake_events_no_update BEFORE UPDATE ON intake_events
                BEGIN SELECT RAISE(ABORT, 'immutable intake event'); END;
            CREATE TRIGGER IF NOT EXISTS intake_events_no_delete BEFORE DELETE ON intake_events
                BEGIN SELECT RAISE(ABORT, 'immutable intake event'); END;
        """)

    def close(self):
        with self._lock:
            self.db.close()

    def _principal(self, credential):
        principal = self.authenticate(credential)
        _check(
            type(principal) is str and 0 < len(principal) <= 128, "unauthorized", 401
        )
        return principal

    def _load(self, principal, project_ref):
        row = self.db.execute(
            "SELECT principal,state FROM intake_projects WHERE ref=?", (project_ref,)
        ).fetchone()
        _check(
            row is not None and row["principal"] == principal,
            "project-unavailable",
            404,
        )
        return json.loads(row["state"])

    def _save(self, state, kind, payload):
        self.db.execute(
            "UPDATE intake_projects SET state=? WHERE ref=?",
            (canonical(state).decode(), state["project_ref"]),
        )
        self.db.execute(
            "INSERT INTO intake_events(project,kind,payload) VALUES(?,?,?)",
            (state["project_ref"], kind, canonical(payload).decode()),
        )

    def _path(self, ref, relative):
        return safe_path(self.root, ref + "/" + relative)

    def _brief(self, state):
        row = state["briefs"][-1]
        path = self._path(state["project_ref"], row["path"])
        with path.open("rb") as stream:
            raw = stream.read(MAX_REQUEST + 1)
        _check(
            len(raw) <= MAX_REQUEST
            and sha(raw) == row["sha256"]
            and raw.decode("utf-8") == row["raw_utf8"],
            "intake-source-bytes-differ",
        )
        value = decode(raw, "intake brief")
        validate_brief(value)
        return row, path, value

    @staticmethod
    def _receipt(row, *, replayed=False):
        value = deepcopy(row)
        value.pop("request", None)
        value["replayed"] = replayed
        value["execution_authorized"] = False
        if value["status"] == "intent-recorded":
            value["status"] = "execution-unknown"
        return value

    def _perform(
        self,
        principal,
        project_ref,
        kind,
        body,
        work,
        *,
        create=False,
        check_deadline=None,
        reserve=None,
    ):
        semantic = {key: value for key, value in body.items() if key != "revision"}
        request_hash = sha(canonical({"kind": kind, "body": semantic}))
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                saved = self.db.execute(
                    "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                    (principal, project_ref, body["key"]),
                ).fetchone()
                if saved:
                    _check(
                        saved["request_hash"] == request_hash,
                        "idempotency-payload-differs",
                    )
                    self.db.commit()
                    return self._receipt(json.loads(saved["receipt"]), replayed=True)
                count = self.db.execute(
                    "SELECT COUNT(*) FROM intake_actions WHERE principal=? AND project=?",
                    (principal, project_ref),
                ).fetchone()[0]
                if count >= MAX_ACTIONS:
                    from .project_stage1_run_grant import saved_history_limit

                    limit = (
                        MAX_ACTIONS
                        if create
                        else saved_history_limit(self, principal, project_ref)
                    )
                    _check(count < limit, "intake-action-bound-exceeded")
                if create:
                    _check(
                        self.db.execute(
                            "SELECT COUNT(*) FROM intake_projects WHERE principal=?",
                            (principal,),
                        ).fetchone()[0]
                        < MAX_PROJECTS,
                        "intake-project-bound-exceeded",
                    )
                    actual_ref = "project-" + uuid.uuid4().hex
                    state = {
                        "project_ref": actual_ref,
                        "project_id": actual_ref,
                        "input_version": 1,
                        "revision": 0,
                        "briefs": [],
                        "settings": None,
                        "plan": None,
                    }
                    self.db.execute(
                        "INSERT INTO intake_projects VALUES(?,?,?)",
                        (actual_ref, principal, canonical(state).decode()),
                    )
                else:
                    state = self._load(principal, project_ref)
                    _check(
                        type(body["revision"]) is int
                        and body["revision"] == state["revision"],
                        "stale-revision",
                    )
                    row, _, _ = self._brief(state)
                    _check(
                        type(body["input_version"]) is type(state["input_version"])
                        and body["input_version"] == state["input_version"]
                        and body["brief_sha256"] == row["sha256"],
                        "intake-source-version-differs",
                    )
                _check(
                    "stage1_import" not in state
                    or kind.startswith(("stage2-", "stage3-")),
                    "imported-intake-is-read-only",
                )
                if check_deadline is not None:
                    check_deadline()
                if reserve is not None:
                    reserve(state, request_hash, principal)
                state["revision"] += 1
                receipt = {
                    "project_ref": state["project_ref"],
                    "key": body["key"],
                    "kind": kind,
                    "request_sha256": request_hash,
                    "request": semantic,
                    "status": "intent-recorded",
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                }
                self.db.execute(
                    "INSERT INTO intake_actions VALUES(?,?,?,?,?)",
                    (
                        principal,
                        project_ref,
                        body["key"],
                        request_hash,
                        canonical(receipt).decode(),
                    ),
                )
                self._save(state, kind + "-intent", receipt)
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise
            # The intent is durable before any core compiler/file producer runs.
            self.db.execute("BEGIN IMMEDIATE")
            work_completed = False
            try:
                current = self._load(principal, state["project_ref"])
                _check(
                    current["revision"] == state["revision"],
                    "intake-intent-state-differs",
                )
                if check_deadline is not None:
                    check_deadline()
                result = work(current, request_hash, principal)
                work_completed = True
                if check_deadline is not None:
                    check_deadline()
                current["revision"] += 1
                receipt.update(status="saved", **result)
                self._save(current, kind + "-saved", receipt)
                self.db.execute(
                    "UPDATE intake_actions SET receipt=? WHERE principal=? AND project=? AND key=?",
                    (canonical(receipt).decode(), principal, project_ref, body["key"]),
                )
                if check_deadline is not None:
                    check_deadline()
                self.db.commit()
            except BaseException as error:
                self.db.rollback()
                receipt.update(
                    status="execution-unknown"
                    if work_completed
                    or kind
                    in {
                        "stage1-coverage",
                        "stage1-claim",
                        "stage1-agent-pending",
                        "stage1-agent-analysis",
                        "stage2-select",
                    }
                    else "failed",
                    error=str(error)[:512],
                )
                if work_completed:
                    receipt.update(
                        failure_phase="post-work-before-commit",
                        output_observation=deepcopy(result),
                    )
                elif kind in {
                    "stage1-coverage",
                    "stage1-claim",
                    "stage1-agent-pending",
                    "stage1-agent-analysis",
                    "stage2-select",
                }:
                    # A Core append can succeed before its producer raises.
                    # Keep this new local action held; failed is unlockable by UI.
                    receipt["failure_phase"] = "core-write-outcome-unobserved"
                self.db.execute("BEGIN IMMEDIATE")
                try:
                    self.db.execute(
                        "UPDATE intake_actions SET receipt=? WHERE principal=? AND project=? AND key=?",
                        (
                            canonical(receipt).decode(),
                            principal,
                            project_ref,
                            body["key"],
                        ),
                    )
                    self.db.execute(
                        "INSERT INTO intake_events(project,kind,payload) VALUES(?,?,?)",
                        (
                            state["project_ref"],
                            kind + "-failed",
                            canonical(receipt).decode(),
                        ),
                    )
                    self.db.commit()
                except BaseException:
                    self.db.rollback()
                    raise
                if isinstance(
                    error, (ValueError, OSError, KeyError, TypeError, TimeoutError)
                ):
                    raised = SessionApiError(
                        "intake-operation-failed",
                        408 if isinstance(error, TimeoutError) else 409,
                    )
                    raised.receipt = self._receipt(receipt)
                    raise raised from error
                raise
            return self._receipt(receipt)

    def record_refusal(self, credential, key, project_ref, kind, body, code):
        """Trusted post-mutation rejection evidence; never retry or alter an intent.

        The caller must have invoked that operation and caught SessionApiError.
        This is not a browser route. Invalid envelopes yield no unlock evidence.
        Existing durable outcomes win even when a new payload reuses their key.
        """
        principal = self._principal(credential)
        if not refusal_shape(kind, body, key, project_ref):
            return None
        try:
            identifier(code)
        except (ValueError, TypeError):
            return None
        project = "" if project_ref is None else project_ref
        semantic = {name: value for name, value in body.items() if name != "revision"}
        request_hash = sha(canonical({"kind": kind, "body": semantic}))
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                saved = self.db.execute(
                    "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                    (principal, project, key),
                ).fetchone()
                if saved:
                    self.db.commit()
                    return self._receipt(json.loads(saved[0]), replayed=True)
                if project_ref is not None:
                    self._load(principal, project_ref)
                count = self.db.execute(
                    "SELECT COUNT(*) FROM intake_actions WHERE principal=? AND project=?",
                    (principal, project),
                ).fetchone()[0]
                _check(count < MAX_ACTIONS, "intake-action-bound-exceeded")
                receipt = {
                    "project_ref": project_ref,
                    "key": key,
                    "kind": kind,
                    "request_sha256": request_hash,
                    "request": semantic,
                    "status": "known-unsent",
                    "error": code,
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                }
                self.db.execute(
                    "INSERT INTO intake_actions VALUES(?,?,?,?,?)",
                    (
                        principal,
                        project,
                        key,
                        request_hash,
                        canonical(receipt).decode(),
                    ),
                )
                self.db.execute(
                    "INSERT INTO intake_events(project,kind,payload) VALUES(?,?,?)",
                    (project, kind + "-refused", canonical(receipt).decode()),
                )
                self.db.commit()
                return self._receipt(receipt)
            except BaseException:
                self.db.rollback()
                raise

    def _write_brief(self, state, value, previous=None):
        _check(len(state["briefs"]) < MAX_VERSIONS, "intake-version-bound-exceeded")
        expected = deepcopy(value)
        expected["previous_sha256"] = (
            None if previous is None else sha(previous.read_bytes())
        )
        _check(len(canonical(expected)) + 1 <= MAX_REQUEST, "intake-brief-too-large")
        name = "brief-" + uuid.uuid4().hex + ".json"
        path = self._path(state["project_ref"], name)
        path.parent.mkdir(parents=True, exist_ok=True)
        create_brief(value, path, previous=previous)
        raw = path.read_bytes()
        state["briefs"].append(
            {
                "input_version": state["input_version"],
                "path": name,
                "sha256": sha(raw),
                "raw_utf8": raw.decode("utf-8"),
            }
        )
        state["plan"] = None
        return {"input_version": state["input_version"], "brief_sha256": sha(raw)}

    def create(self, credential, body, *, check_deadline=None):
        _fields(body, {"key", "topic"}, {"needs", "scope_fields"})
        topic = _text(body["topic"])
        request = _scope(topic, body)

        def work(state, request_hash, _):
            value = prepare_formal_intake(
                request,
                project_id=state["project_id"],
                input_version=state["input_version"],
                request_id="formal-" + request_hash[:24],
                proposed_target=30,
            )
            return self._write_brief(state, value)

        return self._perform(
            self._principal(credential),
            "",
            "create",
            deepcopy(body),
            work,
            create=True,
            check_deadline=check_deadline,
        )

    def submit(self, credential, project_ref, body, *, check_deadline=None):
        _fields(
            body,
            {
                "key",
                "revision",
                "input_version",
                "brief_sha256",
                "choices",
                "formal_target",
                "priority_reading_target",
                "resource_envelope",
                "budgets",
                "consent",
                "user_input",
                "confirmed",
            },
        )
        _check(body["confirmed"] is True, "explicit-intake-confirmation-required", 400)
        for field in ("formal_target", "priority_reading_target"):
            _check(
                type(body[field]) is int and 0 < body[field] <= 10000,
                "intake-target-invalid",
                400,
            )
        _resources(body)
        choices = body["choices"]
        _check(
            type(choices) is list and 0 < len(choices) <= 32,
            "intake-choices-required",
            400,
        )

        def work(state, request_hash, principal):
            _, previous, brief = self._brief(state)
            now = datetime.now(timezone.utc).isoformat()
            source_ref = f"project:{state['project_id']}/input:{state['input_version']}/intake:{request_hash}"
            seen = set()
            for choice in choices:
                _check(
                    type(choice) is dict
                    and set(choice)
                    == {"field", "status", "value", "reason", "user_input"}
                    and choice["field"] not in seen
                    and choice["field"] != "priority_reading_target"
                    and choice["status"] in CHOICES,
                    "intake-choice-invalid",
                    400,
                )
                seen.add(choice["field"])
                brief["decisions"].append(
                    dict(
                        choice,
                        event_id=sha(canonical([request_hash, choice["field"]])),
                        actor=principal,
                        authority="user",
                        recorded_at=now,
                        source_ref=source_ref,
                    )
                )
            brief["decisions"].append(
                {
                    "event_id": "priority-" + request_hash,
                    "field": "priority_reading_target",
                    "status": "specified",
                    "value": str(body["priority_reading_target"]),
                    "actor": principal,
                    "authority": "user",
                    "recorded_at": now,
                    "source_ref": source_ref,
                    "user_input": body["user_input"],
                }
            )
            brief = submit_formal_target(
                brief,
                {
                    "event_id": "formal-" + request_hash,
                    "project_id": state["project_id"],
                    "input_version": state["input_version"],
                    "request_id": brief["formal_final_count"]["request_id"],
                    "status": "submitted",
                    "target": body["formal_target"],
                    "actor": principal,
                    "authority": "user",
                    "user_input": body["user_input"],
                    "source_ref": source_ref,
                    "recorded_at": now,
                    "provenance": "user-attested",
                },
            )
            validate_brief(brief, require_confirmed=True)
            result = self._write_brief(state, brief, previous)
            state["settings"] = {
                key: deepcopy(body[key])
                for key in ("resource_envelope", "budgets", "consent", "user_input")
            }
            state["settings"].update(
                brief_sha256=result["brief_sha256"],
                provenance="user-attested",
                execution_authorized=False,
            )
            return result

        return self._perform(
            self._principal(credential),
            project_ref,
            "submit",
            deepcopy(body),
            work,
            check_deadline=check_deadline,
        )

    def configure(self, credential, project_ref, body, *, check_deadline=None):
        """Save a draft resource request without confirming topic or scope."""
        _fields(
            body,
            {
                "key",
                "revision",
                "input_version",
                "brief_sha256",
                "resource_envelope",
                "budgets",
                "consent",
                "user_input",
                "confirmed",
            },
        )
        _check(
            body["confirmed"] is True, "explicit-resource-confirmation-required", 400
        )
        _resources(body)

        def work(state, _, __):
            state["settings"] = {
                key: deepcopy(body[key])
                for key in ("resource_envelope", "budgets", "consent", "user_input")
            }
            state["settings"].update(
                brief_sha256=body["brief_sha256"],
                provenance="user-attested",
                execution_authorized=False,
            )
            return {
                "settings_status": "resource-request-saved",
                "brief_sha256": body["brief_sha256"],
            }

        return self._perform(
            self._principal(credential),
            project_ref,
            "configure",
            deepcopy(body),
            work,
            check_deadline=check_deadline,
        )

    def compile(self, credential, project_ref, body, *, check_deadline=None):
        _fields(
            body,
            {"key", "revision", "input_version", "brief_sha256", "request", "as_of"},
        )

        def work(state, request_hash, principal):
            _, path, brief = self._brief(state)
            _check(
                type(body["request"]) is dict
                and set(body["request"]) == {"proposal", "query_bindings"},
                "intake-search-request-invalid",
                400,
            )
            _check(
                body["request"]["proposal"]["topic"] == brief["original_description"],
                "intake-plan-topic-differs",
            )
            _check(
                all(
                    not (
                        {"priority_reading_target", "formal_final_count"}
                        & set(row.get("scope_filters", {}))
                    )
                    for row in body["request"]["query_bindings"]
                ),
                "intake-count-is-not-query-filter",
            )
            relative = "plan-" + request_hash
            output = self._path(project_ref, relative)
            result = compile_confirmed(
                path, body["request"], output, as_of=body["as_of"], actor=principal
            )
            validate_bound_plan(output, path)
            manifest_hash = sha((output / "plan_manifest.json").read_bytes())
            state["plan"] = {
                "path": relative,
                "brief_sha256": body["brief_sha256"],
                "manifest_sha256": manifest_hash,
                "execution_status": "not-executed",
            }
            return {
                "plan_manifest_sha256": manifest_hash,
                "plan_execution_status": result["execution_status"],
            }

        return self._perform(
            self._principal(credential),
            project_ref,
            "compile",
            deepcopy(body),
            work,
            check_deadline=check_deadline,
        )

    def revise(self, credential, project_ref, body, *, check_deadline=None):
        """A new input version requires new researcher answers and a new plan."""
        _fields(
            body,
            {"key", "revision", "input_version", "brief_sha256", "topic"},
            {"needs", "scope_fields"},
        )
        request = _scope(_text(body["topic"]), body)

        def reserve(state, _, __):
            from .project_query_versions import check_revision

            service = self._query_service
            _check(
                service is not None or not state.get("stage1_query_authorization"),
                "project-query-revision-service-required",
            )
            if service is not None:
                check_revision(service, credential, state)

        def work(state, request_hash, _):
            from .project_query_versions import archive_revision

            archive_sha = None
            if self._query_service is not None:
                archive_sha = archive_revision(
                    self._query_service, credential, state, request_hash
                )
            state["input_version"] += 1
            state["settings"] = None
            value = prepare_formal_intake(
                request,
                project_id=state["project_id"],
                input_version=state["input_version"],
                request_id="formal-" + request_hash[:24],
                proposed_target=30,
            )
            result = self._write_brief(state, value)
            if archive_sha is not None:
                result["archived_query_scope_sha256"] = archive_sha
            return result

        return self._perform(
            self._principal(credential),
            project_ref,
            "revise",
            deepcopy(body),
            work,
            reserve=reserve,
            check_deadline=check_deadline,
        )

    def read(self, credential, project_ref):
        principal = self._principal(credential)
        with self._lock:
            state = self._load(principal, project_ref)
            if not state["briefs"]:
                return {
                    "project_ref": project_ref,
                    "revision": state["revision"],
                    "status": "execution-unknown",
                    "execution_authorized": False,
                }
            row, path, brief = self._brief(state)
            if "stage1_import" in state:
                from .project_stage1_import import imported_binding

                imported_binding(self, state)
            report = validate_brief(brief)
            if state["plan"] is not None:
                validate_bound_plan(
                    self._path(project_ref, state["plan"]["path"]), path
                )
            return {
                "project_ref": project_ref,
                "project_id": state["project_id"],
                "input_version": state["input_version"],
                "revision": state["revision"],
                "brief_sha256": row["sha256"],
                "brief": brief,
                "intake_report": report,
                "formal_question": None
                if "stage1_import" in state
                else formal_question(brief),
                "suggested_priority_target": 30,
                "settings": deepcopy(state["settings"]),
                "plan": None
                if state["plan"] is None
                else {
                    key: value for key, value in state["plan"].items() if key != "path"
                },
                "stage1_intake_ready": report["necessary_clarification_complete"]
                and state["plan"] is not None,
                "stage1_status": "imported-verified-delivery"
                if "stage1_import" in state
                else "not-started",
                "stage2_status": "not-started",
                "later_stages": {
                    str(i): {"status": "planned", "connected": False}
                    for i in range(3, 7)
                },
                "execution_authorized": False,
                "model_calls": None,
                "search_calls": None,
                "monetary_cost": None,
            }

    def list(self, credential):
        principal = self._principal(credential)
        with self._lock:
            refs = [
                row[0]
                for row in self.db.execute(
                    "SELECT ref FROM intake_projects WHERE principal=? ORDER BY rowid",
                    (principal,),
                )
            ]
            result = []
            for ref in refs:
                try:
                    view = self.read(credential, ref)
                except (ValueError, OSError):
                    result.append(
                        {
                            "project_ref": ref,
                            "status": "source-binding-failed",
                            "stage1_intake_ready": False,
                            "execution_authorized": False,
                            "topic": None,
                        }
                    )
                    continue
                summary = {
                    key: view[key]
                    for key in (
                        "project_ref",
                        "revision",
                        "status",
                        "project_id",
                        "input_version",
                        "brief_sha256",
                        "stage1_intake_ready",
                        "stage1_status",
                        "stage2_status",
                        "execution_authorized",
                    )
                    if key in view
                }
                summary["topic"] = view.get("brief", {}).get("original_description")
                result.append(summary)
            return result

    def history(self, credential, project_ref):
        principal = self._principal(credential)
        with self._lock:
            state = self._load(principal, project_ref)
            rows = self.db.execute(
                "SELECT receipt FROM intake_actions WHERE principal=? AND (project=? OR project='') ORDER BY rowid",
                (principal, project_ref),
            )
            actions = [
                self._receipt(json.loads(row[0]))
                for row in rows
                if json.loads(row[0])["project_ref"] == project_ref
            ]
            return {
                "project_ref": project_ref,
                "revision": state["revision"],
                "versions": [
                    {key: row[key] for key in ("input_version", "sha256")}
                    for row in state["briefs"]
                ],
                "actions": actions,
                "execution_authorized": False,
            }

    def action(self, credential, key, *, project_ref=None):
        """Recover one existing intent; None addresses catalog-level creations."""
        principal = self._principal(credential)
        identifier(key)
        with self._lock:
            project = "" if project_ref is None else project_ref
            if project_ref is not None:
                self._load(principal, project_ref)
            row = self.db.execute(
                "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                (principal, project, key),
            ).fetchone()
            _check(row is not None, "intake-action-unavailable", 404)
            return self._receipt(json.loads(row[0]), replayed=True)

    def binding(self, project_ref):
        """Trusted service bootstrap only; never expose physical paths to browsers."""
        with self._lock:
            row = self.db.execute(
                "SELECT principal FROM intake_projects WHERE ref=?", (project_ref,)
            ).fetchone()
            _check(row is not None, "project-unavailable", 404)
            state = self._load(row[0], project_ref)
            if "stage1_import" in state:
                from .project_stage1_import import imported_binding

                return imported_binding(self, state)
            brief, path, value = self._brief(state)
            validate_brief(value, require_confirmed=True)
            _check(
                state["plan"] is not None
                and state["settings"] is not None
                and state["settings"]["brief_sha256"] == brief["sha256"],
                "intake-plan-not-ready",
            )
            plan = self._path(project_ref, state["plan"]["path"])
            validate_bound_plan(plan, path)
            return {
                "project_id": state["project_id"],
                "input_version": state["input_version"],
                "brief_path": path,
                "brief_sha256": brief["sha256"],
                "plan_root": plan,
                "plan_manifest_sha256": state["plan"]["manifest_sha256"],
                "settings": deepcopy(state["settings"]),
                "execution_authorized": False,
            }

    def brief_binding(self, project_ref, *, require_confirmed=False):
        """Trusted planning input; no compiled plan or execution authority required."""
        with self._lock:
            row = self.db.execute(
                "SELECT principal FROM intake_projects WHERE ref=?", (project_ref,)
            ).fetchone()
            _check(row is not None, "project-unavailable", 404)
            state = self._load(row[0], project_ref)
            saved, path, brief = self._brief(state)
            validate_brief(brief, require_confirmed=require_confirmed)
            return {
                "project_id": state["project_id"],
                "input_version": state["input_version"],
                "revision": state["revision"],
                "brief_path": path,
                "brief_sha256": saved["sha256"],
                "brief": brief,
                "settings": deepcopy(state["settings"]),
                "execution_authorized": False,
            }
