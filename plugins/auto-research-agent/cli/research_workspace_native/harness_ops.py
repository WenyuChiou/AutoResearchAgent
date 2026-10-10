"""Server-owned offline Harness operations over an immutable workspace snapshot.

Calls existing validators/selection producers; does not search, score, import,
launch native processes, or alter the source package. The trusted host owns roots
and principal allowlists. Browser requests contain only opaque references.
"""

from copy import deepcopy
import math
import os
from pathlib import Path
import re
import threading
import time
import uuid

from research_workspace.json_bytes import decode_json
from research_workspace.literature_selection import (
    derive_literature_selection,
    selection_files,
)
from research_workspace.projection import validate_index
from stage1_deliverable.common import canonical, private_output, safe_path, sha
from research_workspace_native.store import ProjectStore
from research_workspace_native.session_api import SessionApiError


ACTIONS = ("validate-index", "derive-literature-selection", "export-selection")
EXPORT_FILES = frozenset(
    "literature/" + name
    for name in (
        "selection.json",
        "selection.csv",
        "selection.md",
        "catalog.xlsx",
        "included.bib",
        "screening.bib",
    )
)
REF = re.compile(r"[A-Za-z0-9_-]{1,64}")
KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}")
HASH = re.compile(r"[0-9a-f]{64}")
MAX_FILE = 32 * 1024 * 1024
MAX_OUTPUT = 128 * 1024 * 1024
MAX_ACTIONS, HISTORY_LIMIT = 128, 64


class HarnessOpsError(SessionApiError):
    def __init__(self, code, status=409):
        super().__init__(code, status)


def _check(condition, code, status=409):
    if not condition:
        raise HarnessOpsError(code, status)


def _public(row):
    result = deepcopy({k: v for k, v in row.items() if k != "private_error_message"})
    if result.get("outcome") == "failed" and result["status"] == "completed":
        result["status"] = "failed"
    elif (
        result.get("outcome") == "rejected-known-unsent"
        and result["status"] == "completed"
    ):
        result["status"] = "rejected-known-unsent"
    return result


class HarnessOps:
    """One process owner per registered project, using the existing durable store.

    Registrations are trusted bootstrap data: index_raw bytes, its SHA-256,
    an absolute private output_root, and allowed principals. Reads do no work.
    The transport supplies an absolute monotonic deadline, never the browser.
    Deadline checks are cooperative between synchronous producer/file steps;
    this service does not forcibly interrupt an in-progress Python producer.
    """

    def __init__(self, store_path, *, registrations, authenticate):
        _check(callable(authenticate), "identity-check-required", 400)
        _check(
            isinstance(registrations, dict) and 1 <= len(registrations) <= 16,
            "bounded-registrations-required",
            400,
        )
        self._authenticate = authenticate
        self._lock = threading.RLock()
        self._projects = {}
        self._closed = False
        self.store = ProjectStore(store_path)
        try:
            total = 0
            for ref, value in registrations.items():
                _check(isinstance(ref, str) and REF.fullmatch(ref), "invalid-ref", 400)
                _check(
                    isinstance(value, dict)
                    and set(value)
                    == {"index_raw", "index_sha256", "output_root", "principals"},
                    "invalid-registration",
                    400,
                )
                raw, expected = value["index_raw"], value["index_sha256"]
                _check(
                    isinstance(raw, bytes)
                    and 0 < len(raw) <= MAX_FILE
                    and isinstance(expected, str)
                    and HASH.fullmatch(expected)
                    and sha(raw) == expected,
                    "index-binding-differs",
                    400,
                )
                total += len(raw)
                _check(total <= MAX_OUTPUT, "snapshot-bound-exceeded", 400)
                index = validate_index(decode_json(raw))
                principals = value["principals"]
                _check(
                    isinstance(principals, (list, tuple, set, frozenset))
                    and principals
                    and all(
                        isinstance(p, str) and 0 < len(p) <= 128 for p in principals
                    ),
                    "principal-allowlist-required",
                    400,
                )
                root = Path(value["output_root"])
                _check(root.is_absolute(), "absolute-output-root-required", 400)
                root = private_output(root).resolve()
                root.mkdir(parents=True, exist_ok=True)
                project_id = "harness-ops-" + sha(ref.encode())[:32]
                self.store.bind_project(project_id, expected)
                owner = self.store.acquire_owner(project_id, "offline-harness-ops")
                binding = dict(
                    project_ref=ref, index_sha256=expected, output_root=root.as_posix()
                )
                state = self.store.snapshot(project_id)
                with self.store._edit(
                    project_id, owner, state["revision"], "harness-ops-bound", binding
                ) as saved:
                    _check(
                        saved.get("harness_ops_binding", binding) == binding,
                        "saved-binding-differs",
                    )
                    saved["harness_ops_binding"] = binding
                self._projects[ref] = dict(
                    raw=raw,
                    index=deepcopy(index),
                    root=root,
                    expected=expected,
                    principals=frozenset(principals),
                    project_id=project_id,
                    owner=owner,
                )
        except BaseException:
            self.store.close()
            self._closed = True
            raise

    def _access(self, token, ref):
        _check(not self._closed, "service-closed", 503)
        try:
            principal = self._authenticate(token)
        except Exception:
            raise HarnessOpsError("identity-denied", 403) from None
        project = self._projects.get(ref) if isinstance(ref, str) else None
        _check(
            project is not None
            and isinstance(principal, str)
            and principal in project["principals"],
            "project-denied",
            403,
        )
        return project

    def _deadline(self, deadline):
        _check(
            type(deadline) in (float, int)
            and math.isfinite(deadline)
            and time.monotonic() < deadline,
            "request-deadline-exceeded",
            408,
        )

    def view(self, token, ref):
        """Current revision and retained operation history, with no execution."""
        with self._lock:
            project = self._access(token, ref)
            state = self.store.snapshot(project["project_id"])
            return dict(
                project_ref=ref,
                index_sha256=project["expected"],
                project_id=project["index"]["project_id"],
                input_canonical_sha256=sha(canonical(project["index"])),
                revision=state["revision"],
                capabilities=list(ACTIONS),
                operation_scope="offline-saved-input",
                research_execution=False,
                model_execution=False,
                scientific_admission=False,
                history=[
                    _public(row)
                    for row in sorted(
                        state["intents"].values(),
                        key=lambda row: (row["intent_revision"], row["key"]),
                    )[-HISTORY_LIMIT:]
                ],
                history_count=len(state["intents"]),
                history_limit=HISTORY_LIMIT,
                action_limit=MAX_ACTIONS,
            )

    def get_action(self, token, ref, key):
        with self._lock:
            project = self._access(token, ref)
            _check(
                isinstance(key, str) and KEY.fullmatch(key), "invalid-action-key", 400
            )
            row = self.store.snapshot(project["project_id"])["intents"].get(key)
            _check(row is not None, "action-not-found", 404)
            return _public(row)

    def bindings(self):
        with self._lock:
            _check(not self._closed, "service-closed", 503)
            return {
                ref: dict(
                    project_id=project["index"]["project_id"],
                    index_sha256=project["expected"],
                )
                for ref, project in self._projects.items()
            }

    def execute(self, token, ref, request, *, deadline):
        """Save an intent before work; the same key never executes twice."""
        self._deadline(deadline)
        with self._lock:
            self._deadline(deadline)  # A queued request can expire while waiting.
            project = self._access(token, ref)
            _check(
                isinstance(request, dict)
                and set(request)
                == {"action", "index_sha256", "expected_revision", "key"}
                and request["action"] in ACTIONS
                and isinstance(request["index_sha256"], str)
                and HASH.fullmatch(request["index_sha256"])
                and type(request["expected_revision"]) is int
                and request["expected_revision"] >= 0
                and isinstance(request["key"], str)
                and KEY.fullmatch(request["key"]),
                "invalid-action-request",
                400,
            )
            _check(
                request["index_sha256"] == project["expected"], "stale-index-binding"
            )
            request = deepcopy(request)
            digest = sha(canonical(dict(project_ref=ref, **request)))
            project_id, owner, key = (
                project["project_id"],
                project["owner"],
                request["key"],
            )
            state = self.store.snapshot(project_id)
            previous = state["intents"].get(key)
            if previous is not None:
                _check(
                    previous["request_sha256"] == digest, "idempotency-payload-differs"
                )
                if (
                    previous.get("outcome") == "rejected-known-unsent"
                    and previous["status"] == "completed"
                ):
                    error = HarnessOpsError("stale-revision")
                    error.receipt = _public(previous)
                    raise error
                return _public(previous)
            _check(
                len(state["intents"]) < MAX_ACTIONS,
                "project-action-bound-exceeded",
                429,
            )
            self._deadline(deadline)
            row = dict(
                key=key,
                project_ref=ref,
                method="harness-ops/" + request["action"],
                action=request["action"],
                status="running",
                request=request,
                request_sha256=digest,
                index_sha256=project["expected"],
                input_canonical_sha256=sha(canonical(project["index"])),
                contract_version="1.0.0",
                output_ref=uuid.uuid4().hex,
                artifacts=[],
                intent_revision=state["revision"] + 1,
                research_execution=False,
                model_execution=False,
                scientific_admission=False,
            )
            if request["expected_revision"] != state["revision"]:
                # Authenticated, source-bound and fully shaped; no producer was
                # admitted. Commit the refusal before claiming it is known unsent.
                row.update(
                    status="completed",
                    outcome="rejected-known-unsent",
                    completion_revision=state["revision"] + 1,
                    error=dict(code="stale-revision", type="HarnessOpsError"),
                    rejection=dict(
                        type="known-unsent",
                        phase="before-admission",
                        offer_revision=request["expected_revision"],
                        observed_revision=state["revision"],
                    ),
                )
                with self.store._edit(
                    project_id,
                    owner,
                    state["revision"],
                    "harness-ops-rejected",
                    request,
                ) as saved:
                    self._deadline(deadline)
                    saved["intents"][key] = deepcopy(row)
                    self._deadline(deadline)
                error = HarnessOpsError("stale-revision")
                error.receipt = _public(row)
                raise error
            with self.store._edit(
                project_id, owner, state["revision"], "harness-ops-intent", request
            ) as saved:
                saved["intents"][key] = deepcopy(row)
            try:
                self._deadline(deadline)
                result, files = self._produce(project, request["action"])
                self._deadline(deadline)
                root = safe_path(project["root"], row["output_ref"])
                root.mkdir(exist_ok=False)
                _check(
                    sum(len(raw) for raw in files.values()) <= MAX_OUTPUT,
                    "output-bound-exceeded",
                )
                for name, raw in files.items():
                    self._deadline(deadline)
                    _check(
                        isinstance(raw, bytes) and len(raw) <= MAX_FILE,
                        "file-bound-exceeded",
                    )
                    path = safe_path(root, name)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("xb") as stream:
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                    _check(path.read_bytes() == raw, "written-artifact-bytes-differ")
                    row["artifacts"].append(
                        dict(name=name, sha256=sha(raw), size=len(raw))
                    )
                self._deadline(deadline)
                row.update(status="completed", outcome="succeeded", result=result)
            except Exception as error:
                row.update(
                    # ProjectStore preserves completed attempts during owner recovery.
                    # A failed computation is terminal, not an unknown native execution.
                    status="completed",
                    outcome="failed",
                    error=dict(
                        code=getattr(error, "code", "operation-failed"),
                        type=type(error).__name__,
                    ),
                    private_error_message=str(error)[:4096],
                )
            state = self.store.snapshot(project_id)
            row["completion_revision"] = state["revision"] + 1
            with self.store._edit(
                project_id, owner, state["revision"], "harness-ops-result", _public(row)
            ) as saved:
                saved["intents"][key] = deepcopy(row)
            return _public(row)

    def _produce(self, project, action):
        index = decode_json(project["raw"])
        validate_index(index)
        if action == "validate-index":
            result, files = dict(validation="passed", papers=len(index["papers"])), {}
        elif action == "derive-literature-selection":
            selection = derive_literature_selection(index)
            result = dict(
                counts=selection["counts"], rule_version=selection["rule_version"]
            )
            files = {"literature/selection.json": canonical(selection)}
        else:
            files = selection_files(index)
            _check(set(files) == EXPORT_FILES, "producer-file-allowlist-differs")
            selection = decode_json(files["literature/selection.json"])
            result = dict(
                counts=selection["counts"], rule_version=selection["rule_version"]
            )
        result.update(
            input_canonical_sha256=sha(canonical(index)),
            research_execution=False,
            scientific_admission=False,
            official_stage2_import_eligible=False,
        )
        files["operation.json"] = canonical(result)
        return result, files

    def artifact(self, token, ref, key, name, expected_sha256):
        """Read only a named, saved operation artifact after an exact hash check."""
        with self._lock:
            project = self._access(token, ref)
            _check(
                isinstance(key, str)
                and KEY.fullmatch(key)
                and isinstance(name, str)
                and name in EXPORT_FILES | {"operation.json"}
                and isinstance(expected_sha256, str)
                and HASH.fullmatch(expected_sha256),
                "invalid-artifact-request",
                400,
            )
            row = self.store.snapshot(project["project_id"])["intents"].get(key)
            _check(
                row is not None and row["status"] in {"completed", "failed"},
                "artifact-unavailable",
                404,
            )
            item = next((f for f in row["artifacts"] if f["name"] == name), None)
            _check(
                item is not None and item["sha256"] == expected_sha256,
                "artifact-binding-differs",
            )
            root = safe_path(project["root"], row["output_ref"])
            path = safe_path(root, name)
            _check(
                path.is_file() and path.stat().st_size == item["size"] <= MAX_FILE,
                "artifact-bytes-differ",
            )
            with path.open("rb") as stream:
                raw = stream.read(MAX_FILE + 1)
            _check(
                len(raw) == item["size"] and sha(raw) == expected_sha256,
                "artifact-bytes-differ",
            )
            return raw

    def close(self):
        with self._lock:
            if not self._closed:
                self.store.close()
                self._closed = True
