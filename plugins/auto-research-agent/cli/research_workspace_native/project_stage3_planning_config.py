"""Closed local CLI composition of the existing Stage3 planning components.

Configuration is server-owned and is not a model-call or research grant. Loading
it is read-only; the resource owner opens only the existing Journal and jobs.
"""

from copy import deepcopy
import hashlib
import math
from os.path import samestat
from pathlib import Path
import re
import secrets
import threading

from stage1_deliverable.common import safe_path as _relative_path
from stage3_plan.contracts import Stage3Error, digest
from stage3_plan.jobs import PlanningJobs
from stage3_plan.native import NativePlanner
from stage3_plan.preparation import closed, sha256, text
from stage3_plan.storage import decode_json, private_output, read_bytes, safe_path

from .journal import Journal, JournalError
from .project_stage_connections import PLANNING_STAGE, ConnectionStore
from .project_stage3_planning import ProjectStage3PlanningService


FIELDS = {
    "project_ref",
    "project_id",
    "jobs_root",
    "configuration",
    "native",
    "recovery_pins",
}
NATIVE_FIELDS = {"codex", "codex_home", "capture_dir", "timeout_seconds"}
PROFILE_FIELDS = (FIELDS - {"project_ref", "project_id"}) | {
    "kind",
    "schema_version",
    "journal_path",
    "project_parent",
    "max_projects",
}


def _path(value, *, private=False):
    if type(value) is not str or not Path(value).is_absolute():
        raise Stage3Error("stage3-planning-configuration-absolute-path-required")
    return private_output(value) if private else safe_path(value)


def _overlaps(left, right):
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _output_paths(row):
    capture = _path(row["native"]["capture_dir"], private=True)
    return (
        _path(row["jobs_root"], private=True),
        capture,
        _path(str(capture.with_name(capture.name + "-direction")), private=True),
    )


def _reserve_output_paths(db, project_id, paths):
    """Record ownership within the Journal's project-binding transaction."""
    db.execute(
        """CREATE TABLE IF NOT EXISTS stage3_planning_paths (
            project TEXT NOT NULL, path TEXT NOT NULL, PRIMARY KEY(project, path)
        )"""
    )
    owned = set()
    for owner, value in db.execute("SELECT project, path FROM stage3_planning_paths"):
        existing = Path(value)
        if owner == project_id:
            owned.add(existing)
        elif any(_overlaps(path, existing) for path in paths):
            raise Stage3Error("stage3-planning-configuration-output-overlap")
    # Releasing a Host lease does not free previously used directories.
    db.executemany(
        "INSERT INTO stage3_planning_paths VALUES (?, ?)",
        [(project_id, str(path)) for path in paths if path not in owned],
    )


def _validated_settings(row, outputs):
    closed(row["configuration"], {"model", "reasoning"}, "configuration")
    for value in row["configuration"].values():
        text(value, "configuration value")
    native = row["native"]
    closed(native, NATIVE_FIELDS, "native planning configuration")
    codex = _path(native["codex"])
    home = _path(native["codex_home"])
    if not codex.is_file() or not home.is_dir():
        raise Stage3Error("stage3-planning-configuration-native-path-missing")
    timeout = native["timeout_seconds"]
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise Stage3Error("stage3-planning-configuration-deadline")
    for path in _output_paths(row):
        if any(_overlaps(path, existing) for existing in outputs):
            raise Stage3Error("stage3-planning-configuration-output-overlap")
        outputs.append(path)
    pins = row["recovery_pins"]
    if type(pins) is not list or len(pins) > 256:
        raise Stage3Error("stage3-planning-configuration-recovery-count")
    identities = set()
    for pin in pins:
        closed(pin, {"key", "request_sha256", "plan_manifest_sha256"}, "recovery pin")
        text(pin["key"], "recovery key")
        sha256(pin["request_sha256"])
        sha256(pin["plan_manifest_sha256"])
        identity = (pin["key"], pin["request_sha256"])
        if identity in identities:
            raise Stage3Error("stage3-planning-configuration-duplicate-recovery")
        identities.add(identity)


def _validated(intake, credential, configuration):
    closed(
        configuration,
        {"kind", "schema_version", "journal_path", "bindings"},
        "Stage3 planning configuration",
    )
    if (
        configuration["kind"] != "ProjectStage3PlanningConfiguration"
        or configuration["schema_version"] != "1.0.0"
    ):
        raise Stage3Error("stage3-planning-configuration-version")
    journal_path = _path(configuration["journal_path"], private=True)
    rows = configuration["bindings"]
    if type(rows) is not list or not 1 <= len(rows) <= 32:
        raise Stage3Error("stage3-planning-configuration-count")
    refs, ids, outputs = set(), set(), [journal_path]
    for row in rows:
        closed(row, FIELDS, "Stage3 planning binding")
        ref, project_id = row["project_ref"], row["project_id"]
        text(ref, "project reference")
        text(project_id, "project id")
        if ref in refs or project_id in ids:
            raise Stage3Error("stage3-planning-configuration-duplicate-project")
        project = intake.read(credential, ref)
        if project.get("project_id") != project_id:
            raise Stage3Error("stage3-planning-configuration-project-differs")
        refs.add(ref)
        ids.add(project_id)
        _validated_settings(row, outputs)
    return deepcopy(configuration)


def _pinned(path, expected_sha256):
    path = _path(str(path))
    sha256(expected_sha256)
    raw = read_bytes(path)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise Stage3Error("stage3-planning-configuration-hash-differs")
    return decode_json(raw, label="planning configuration")


def load_stage3_planning_configuration(intake, credential, path, expected_sha256):
    """Read and validate all settings before opening any journal or listener."""
    return _validated(intake, credential, _pinned(path, expected_sha256))


class Stage3PlanningProfile:
    """Pin a trusted row template. The Host supplies project identity."""

    def __init__(self, path, expected_sha256):
        self.path, self.sha256 = path, expected_sha256
        value, parent = self._profile()
        self.journal_path = _path(value["journal_path"], private=True)
        self.max_projects = value["max_projects"]
        _validated_settings(self._row(value, parent), [self.journal_path])

    def _profile(self):
        value = _pinned(self.path, self.sha256)
        closed(value, PROFILE_FIELDS, "Stage3 planning profile")
        if (
            value["kind"] != "ProjectStage3PlanningProfile"
            or value["schema_version"] != "1.0.0"
            or type(value["max_projects"]) is not int
            or not 1 <= value["max_projects"] <= 32
        ):
            raise Stage3Error("stage3-planning-profile-invalid")
        return value, _path(value["project_parent"], private=True)

    @staticmethod
    def _row(value, root):
        native = deepcopy(value["native"])
        closed(native, NATIVE_FIELDS, "native planning configuration")
        native["capture_dir"] = str(_relative_path(root, native["capture_dir"]))
        return {
            "jobs_root": str(_relative_path(root, value["jobs_root"])),
            "configuration": deepcopy(value["configuration"]),
            "native": native,
            "recovery_pins": deepcopy(value["recovery_pins"]),
        }

    def _located(self, ref):
        if type(ref) is not str or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", ref) is None:
            raise Stage3Error("stage3-planning-profile-project-invalid")
        value, parent = self._profile()
        return value, _relative_path(parent, ref)

    def output_paths(self, ref):
        value, root = self._located(ref)
        return _output_paths(self._row(value, root))

    def validate_static_outputs(self, row):
        _, own_root = self._located(row["project_ref"])
        if any(
            _overlaps(path, own_root.parent) and not path.is_relative_to(own_root)
            for path in _output_paths(row)
        ):
            raise Stage3Error("stage3-planning-profile-output-overlap")

    def resolve(self, ref, project_id):
        text(project_id, "project id")
        value, root = self._located(ref)
        row = self._row(value, root)
        _validated_settings(row, [_path(value["journal_path"], private=True)])
        return dict(row, project_ref=ref, project_id=project_id)


def validate_profile_journal(profile, configuration):
    if (
        profile is not None
        and configuration is not None
        and profile.journal_path != _path(configuration["journal_path"], private=True)
    ):
        raise Stage3Error("stage3-planning-profile-journal-differs")


class Stage3PlanningHostResources:
    """One CLI owner for existing journals; never owns the intake or a runner."""

    def __init__(
        self, intake, credential, selection_view, configuration, *, profile=None
    ):
        if selection_view is None or selection_view.intake is not intake:
            raise Stage3Error("stage3-planning-configuration-selection-required")
        if configuration is not None:
            configuration = _validated(intake, credential, configuration)
        validate_profile_journal(profile, configuration)
        if configuration is None and profile is None:
            raise Stage3Error("stage3-planning-configuration-required")
        self.intake, self.credential, self.profile = intake, credential, profile
        self.store = ConnectionStore(intake, credential)
        self._lock = threading.RLock()
        self._closed, self._close_failure = False, None
        self.journal, self._owners = None, {}
        self._rows, self._dynamic = {}, {}
        self.recovery_pins, self.identities = {}, {}
        rows = () if configuration is None else configuration["bindings"]
        self.static_refs = frozenset(row["project_ref"] for row in rows)
        for ref in self.static_refs:
            if self.store.resolve(ref, PLANNING_STAGE) is not None:
                raise Stage3Error("stage3-planning-bindings-overlap")
        journal_path = (
            profile.journal_path
            if configuration is None
            else _path(configuration["journal_path"], private=True)
        )
        if (
            profile is not None
            and self.store.references(PLANNING_STAGE)
            and not journal_path.is_file()
        ):
            raise Stage3Error("stage3-planning-saved-journal-missing")
        if rows:
            reserved = [
                path for outputs in self._retained_paths().values() for path in outputs
            ]
            for row in rows:
                if any(
                    _overlaps(path, existing)
                    for path in _output_paths(row)
                    for existing in reserved
                ):
                    raise Stage3Error("stage3-planning-configuration-output-overlap")
                if profile is not None:
                    profile.validate_static_outputs(row)
        try:
            self.journal = Journal(journal_path)
            self._journal_file = self.journal.path.stat()
            bindings = {row["project_ref"]: self._open_binding(row) for row in rows}
            self.service = ProjectStage3PlanningService(
                intake,
                selection_view,
                bindings=bindings,
                saved_read_pins=self.recovery_pins,
            )
            from .project_stage3_planning_connections import Stage3PlanningConnections

            self.connections = Stage3PlanningConnections(self)
            if profile is not None:
                self.service.bindings = self.connections
                self.service.saved_read_pins = self.connections.recovery_pins
        except BaseException as error:
            try:
                self.close()
            except BaseException as cleanup:
                error.add_note(f"Planning resource cleanup failed: {cleanup!r}")
            raise

    def _retained_paths(self):
        paths = {}
        for ref in self.store.references(PLANNING_STAGE):
            try:
                record = self.store._resolve(ref, PLANNING_STAGE, current=False)
                if record is not None:
                    paths[ref] = _output_paths(record["row"])
            except (OSError, ValueError, KeyError, TypeError, RecursionError):
                # Keep the trusted profile's slots for a saved but damaged
                # connection. Its normal read still requires the raw receipt.
                if self.profile is not None:
                    try:
                        paths[ref] = self.profile.output_paths(ref)
                    except (OSError, ValueError, KeyError, TypeError, RecursionError):
                        continue
        return paths

    def _open_binding(self, row, *, require_existing=False):
        ref, project_id = row["project_ref"], row["project_id"]
        identity = {
            "kind": "ProjectHostStage3JournalIdentity",
            "schema_version": "1.0.0",
            "project_ref": ref,
            "project_id": project_id,
            "projects_root": str(safe_path(self.intake.root)),
        }
        identity_sha = digest(identity)
        if require_existing:
            try:
                original = self.journal.snapshot(project_id)
            except JournalError as error:
                raise Stage3Error(
                    "stage3-planning-saved-journal-project-missing"
                ) from error
            if original["index_sha256"] != identity_sha:
                raise Stage3Error("stage3-planning-saved-journal-project-differs")
        paths = _output_paths(row)

        def bind():
            self.journal.bind_project(
                project_id,
                identity_sha,
                require_existing=require_existing,
                reserve=lambda db: _reserve_output_paths(db, project_id, paths),
            )

        owner = self.journal.acquire_owner(
            project_id, "stage3-host-" + secrets.token_hex(16), bind=bind
        )
        self._owners[project_id] = owner
        self._rows[ref] = deepcopy(row)
        self.identities[ref] = identity
        binding = {
            "jobs": PlanningJobs(
                self.journal, project_id, owner, row["jobs_root"], project_ref=ref
            ),
            "configuration": row["configuration"],
            "callback": NativePlanner(**row["native"]),
        }
        for pin in row["recovery_pins"]:
            key = (ref, pin["key"], pin["request_sha256"])
            self.recovery_pins[key] = pin["plan_manifest_sha256"]
        return binding

    def add_project(self, row, *, require_existing=False):
        """Compose one verified runtime row under the existing Journal owner."""
        with self.intake._lock, self._lock:
            if self._closed:
                raise Stage3Error("stage3-planning-resources-closed")
            if not samestat(safe_path(self.journal.path).stat(), self._journal_file):
                raise Stage3Error("stage3-planning-saved-journal-file-differs")
            closed(row, FIELDS, "Stage3 planning binding")
            ref, project_id = row["project_ref"], row["project_id"]
            current = self.intake.read(self.credential, ref)
            if current["project_id"] != project_id:
                raise Stage3Error("stage3-planning-configuration-project-differs")
            if ref in self.static_refs:
                raise Stage3Error("stage3-planning-bindings-overlap")
            row_sha = digest(row)
            if (
                self.profile is None
                or digest(self.profile.resolve(ref, project_id)) != row_sha
            ):
                raise Stage3Error("stage3-planning-runtime-row-differs")
            existing = self._dynamic.get(ref)
            if existing is not None:
                if existing[0] != row_sha:
                    raise Stage3Error("stage3-planning-runtime-row-differs")
                owner = self.journal.snapshot(project_id)["owner"]
                if owner is None or owner["token"] != existing[1]["jobs"].owner:
                    raise Stage3Error("stage3-planning-runtime-owner-differs")
                return existing[1], False
            if ref in self._rows or project_id in self._owners:
                raise Stage3Error("stage3-planning-owner-already-attached")
            reserved = self._retained_paths()
            reserved.update(
                {key: _output_paths(old) for key, old in self._rows.items()}
            )
            outputs = [self.journal.path]
            outputs.extend(
                path for key, paths in reserved.items() if key != ref for path in paths
            )
            _validated_settings(row, outputs)
            try:
                configured = self.service._validate_binding(
                    ref, self._open_binding(row, require_existing=require_existing)
                )
            except BaseException as error:
                try:
                    self.release_project(ref)
                except BaseException as cleanup:
                    error.add_note(f"Planning lease cleanup failed: {cleanup!r}")
                raise
            self._dynamic[ref] = (row_sha, configured)
            return configured, True

    def release_project(self, ref):
        """Roll back only a local runtime lease after an unsuccessful publication."""
        with self._lock:
            if ref not in self._rows or ref in self.static_refs:
                return
            project_id = self._rows[ref]["project_id"]
            self.journal.release_owner(project_id, self._owners[project_id])
            del self._owners[project_id]
            del self._rows[ref]
            del self.identities[ref]
            self._dynamic.pop(ref, None)
            for key in tuple(self.recovery_pins):
                if key[0] == ref:
                    del self.recovery_pins[key]

    def close(self):
        """Close only this owner's resources, once the Host has drained calls."""
        with self._lock:
            if self._closed:
                if self._close_failure is not None:
                    raise self._close_failure
                return
            errors = []
            if self.journal is not None:
                for project_id, owner in reversed(tuple(self._owners.items())):
                    try:
                        self.journal.release_owner(project_id, owner)
                    except BaseException as error:
                        errors.append(error)
                try:
                    self.journal.close()
                except BaseException as error:
                    errors.append(error)
            self._owners.clear()
            self._closed = True
            if errors:
                self._close_failure = errors[0]
                for error in errors[1:]:
                    errors[0].add_note(f"Additional cleanup failure: {error!r}")
                raise errors[0]
