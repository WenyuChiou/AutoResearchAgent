"""Closed local CLI composition of the existing Stage3 planning components.

Configuration is server-owned and is not a model-call or research grant. Loading
it is read-only; the resource owner opens only the existing Journal and jobs.
"""

from copy import deepcopy
import hashlib
import math
from pathlib import Path
import secrets
import threading

from stage3_plan.contracts import Stage3Error, digest
from stage3_plan.jobs import PlanningJobs
from stage3_plan.native import NativePlanner
from stage3_plan.preparation import closed, sha256, text
from stage3_plan.storage import decode_json, private_output, read_bytes, safe_path

from .journal import Journal
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


def _path(value, *, private=False):
    if type(value) is not str or not Path(value).is_absolute():
        raise Stage3Error("stage3-planning-configuration-absolute-path-required")
    return private_output(value) if private else safe_path(value)


def _overlaps(left, right):
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


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
        if (
            type(timeout) not in (int, float)
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise Stage3Error("stage3-planning-configuration-deadline")
        for path in (
            _path(row["jobs_root"], private=True),
            _path(native["capture_dir"], private=True),
        ):
            if any(_overlaps(path, existing) for existing in outputs):
                raise Stage3Error("stage3-planning-configuration-output-overlap")
            outputs.append(path)
        pins = row["recovery_pins"]
        if type(pins) is not list or len(pins) > 256:
            raise Stage3Error("stage3-planning-configuration-recovery-count")
        identities = set()
        for pin in pins:
            closed(
                pin, {"key", "request_sha256", "plan_manifest_sha256"}, "recovery pin"
            )
            text(pin["key"], "recovery key")
            sha256(pin["request_sha256"])
            sha256(pin["plan_manifest_sha256"])
            identity = (pin["key"], pin["request_sha256"])
            if identity in identities:
                raise Stage3Error("stage3-planning-configuration-duplicate-recovery")
            identities.add(identity)
    return deepcopy(configuration)


def load_stage3_planning_configuration(intake, credential, path, expected_sha256):
    """Read and validate all settings before opening any journal or listener."""
    path = _path(str(path))
    sha256(expected_sha256)
    raw = read_bytes(path)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise Stage3Error("stage3-planning-configuration-hash-differs")
    return _validated(intake, credential, decode_json(raw, label="planning config"))


class Stage3PlanningHostResources:
    """One CLI owner for existing journals; never owns the intake or a runner."""

    def __init__(self, intake, credential, selection_view, configuration):
        if selection_view is None or selection_view.intake is not intake:
            raise Stage3Error("stage3-planning-configuration-selection-required")
        configuration = _validated(intake, credential, configuration)
        self._lock = threading.RLock()
        self._closed, self._close_failure = False, None
        self.journal, self._owners = None, {}
        self.recovery_pins, self.identities = {}, {}
        try:
            self.journal = Journal(configuration["journal_path"])
            bindings = {}
            for row in configuration["bindings"]:
                ref, project_id = row["project_ref"], row["project_id"]
                identity = {
                    "kind": "ProjectHostStage3JournalIdentity",
                    "schema_version": "1.0.0",
                    "project_ref": ref,
                    "project_id": project_id,
                    "projects_root": str(safe_path(intake.root)),
                }
                # An actual Host identity token, never a native ProjectIndex proof.
                self.identities[ref] = identity
                self.journal.bind_project(project_id, digest(identity))
                owner = self.journal.acquire_owner(
                    project_id, "stage3-host-" + secrets.token_hex(16)
                )
                self._owners[project_id] = owner
                native = row["native"]
                bindings[ref] = {
                    "jobs": PlanningJobs(
                        self.journal,
                        project_id,
                        owner,
                        row["jobs_root"],
                        project_ref=ref,
                    ),
                    "configuration": row["configuration"],
                    "callback": NativePlanner(**native),
                }
                for pin in row["recovery_pins"]:
                    key = (ref, pin["key"], pin["request_sha256"])
                    self.recovery_pins[key] = pin["plan_manifest_sha256"]
            self.service = ProjectStage3PlanningService(
                intake, selection_view, bindings=bindings
            )
        except BaseException as error:
            try:
                self.close()
            except BaseException as cleanup:
                error.add_note(f"Planning resource cleanup failed: {cleanup!r}")
            raise

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
