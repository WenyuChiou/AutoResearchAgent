"""Current selected-project binding for the same Stage 3 Journal and Host."""

from collections.abc import Mapping
from sqlite3 import Error as SqliteError

from stage3_plan.contracts import digest
from .project_stage_connections import PLANNING_STAGE
from .session_api import SessionApiError, _check


class Stage3PlanningConnections(Mapping):
    def __init__(self, resources):
        self.resources = resources
        self.intake = resources.intake
        self.profile = resources.profile
        self.store = resources.store
        self.static = resources.service.bindings
        self.selection = resources.service.selection_view
        self.recovery_pins = _RecoveryPins(self)

    def _saved(self, ref):
        saved = self.store.resolve(ref, PLANNING_STAGE)
        _check(
            ref not in self.static or saved is None,
            "stage3-planning-bindings-overlap",
        )
        return saved

    def _verified(self, credential, ref, deadline):
        _check(self.profile is not None, "stage3-planning-profile-unavailable")
        try:
            if deadline is not None:
                deadline()
            verified, _ = self.selection._current_context(credential, ref)
            project, binding, delivery, _, ack, admitted = verified
            _check(
                type(project["input_version"]) is int,
                "stage3-planning-integer-version-required",
            )
            _check(
                ack is not None and admitted is not None,
                "stage3-current-selection-required",
            )
            row = self.profile.resolve(ref, project["project_id"])
            identity = self.store._identity(ref)
            derived = {
                "profile_sha256": self.profile.sha256,
                "selection_request_sha256": ack["request_sha256"],
                "planning_manifest_sha256": ack["planning_manifest_sha256"],
                "selection_workflow_head_sha256": ack["workflow_head_sha256"],
                "delivery_manifest_sha256": binding["delivery_manifest_sha256"],
                "snapshot_sha256": delivery["manifest"]["snapshot_sha256"],
            }
            if deadline is not None:
                deadline()
            return row, identity, derived
        except (SessionApiError, TimeoutError):
            raise
        except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
            raise SessionApiError(
                "stage3-planning-profile-verification-required", 409
            ) from error

    @staticmethod
    def _match(saved, row, identity, derived):
        _check(
            digest(saved["row"]) == digest(row)
            and digest(saved["identity"]) == digest(identity)
            and digest(saved["derived_from"]) == digest(derived),
            "stage3-planning-connection-differs",
        )

    def _attach(self, row, *, require_existing=False):
        try:
            return self.resources.add_project(row, require_existing=require_existing)
        except (OSError, ValueError, RuntimeError, SqliteError) as error:
            raise SessionApiError(
                "stage3-planning-resource-unavailable", 409
            ) from error

    def __getitem__(self, ref):
        with self.intake._lock:
            saved = self._saved(ref)
            if ref in self.static:
                return self.static[ref]
            if saved is None:
                raise KeyError(ref)
            row, identity, derived = self._verified(self.store.credential, ref, None)
            self._match(saved, row, identity, derived)
            return self._attach(row, require_existing=True)[0]

    def __iter__(self):
        return iter(
            sorted(self.static.keys() | set(self.store.references(PLANNING_STAGE)))
        )

    def __len__(self):
        return sum(1 for _ in self)

    def discover(self, credential, ref, deadline):
        with self.intake._lock:
            self.intake.read(credential, ref)
            try:
                saved = self._saved(ref)
                if ref in self.static:
                    return self._public(ref, "connected", static=True)
                row, identity, derived = self._verified(credential, ref, deadline)
                if saved is None:
                    self.store.check_project_limit(
                        ref, PLANNING_STAGE, self.profile.max_projects
                    )
                    return self._public(ref, "connectable")
                self._match(saved, row, identity, derived)
                self._attach(row, require_existing=True)
                return self._public(ref, "connected", saved=saved)
            except SessionApiError as error:
                if error.status != 409:
                    raise
                return self._public(ref, "unavailable", reason=error.code)

    def register(self, credential, ref, body, deadline):
        with self.intake._lock:
            project = self.intake.read(credential, ref)
            _check(
                type(project["input_version"]) is int
                and type(body["input_version"]) is int
                and body["input_version"] == project["input_version"]
                and body["brief_sha256"] == project["brief_sha256"],
                "stage3-planning-project-stale",
            )
            previous = self._saved(ref)
            _check(ref not in self.static, "stage3-planning-bindings-overlap")
            _check(
                self.profile is not None
                and body["profile_sha256"] == self.profile.sha256,
                "stage3-planning-profile-differs",
            )
            row, identity, derived = self._verified(credential, ref, deadline)
            if previous is not None:
                self._match(previous, row, identity, derived)
            acquired = False

            def attach():
                nonlocal acquired
                _, acquired = self._attach(row)

            try:
                saved = self.store.record(
                    ref,
                    PLANNING_STAGE,
                    row,
                    derived_from=derived,
                    expected_identity=identity,
                    expected_revision=body["revision"],
                    request_key=body["key"],
                    maximum_projects=self.profile.max_projects,
                    check_deadline=deadline,
                    reserve_resource=attach,
                )
            except BaseException as error:
                if acquired:
                    try:
                        self.resources.release_project(ref)
                    except BaseException as cleanup:
                        error.add_note(f"Planning lease cleanup failed: {cleanup!r}")
                raise
            # A saved registration bypasses reservation and may reopen its lease.
            if not acquired:
                self._attach(row, require_existing=True)
            return self._public(ref, "connected", saved=saved)

    def _public(self, ref, status, *, reason=None, saved=None, static=False):
        return {
            "project_ref": ref,
            "connections": {
                PLANNING_STAGE: {
                    "status": status,
                    "reason": reason,
                    "profile_sha256": None
                    if self.profile is None or static
                    else self.profile.sha256,
                    "connection_id": None if saved is None else saved["connection_id"],
                    "receipt_id": None if saved is None else saved["receipt_id"],
                }
            },
            "execution_authorized": False,
        }


class _RecoveryPins:
    """Resolve the trusted saved row even when recover is the first HTTP call."""

    def __init__(self, connections):
        self.connections = connections

    def get(self, identity, default=None):
        ref, key, request = identity
        connections = self.connections
        if ref in connections.static:
            return connections.resources.recovery_pins.get(identity, default)
        with connections.intake._lock:
            saved = connections._saved(ref)
            if saved is None:
                return default
            row, expected, derived = connections._verified(
                connections.store.credential, ref, None
            )
            connections._match(saved, row, expected, derived)
            for pin in row["recovery_pins"]:
                if pin["key"] == key and pin["request_sha256"] == request:
                    return pin["plan_manifest_sha256"]
            return default

    def __contains__(self, identity):
        return self.get(identity) is not None
