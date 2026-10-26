"""Pinned trusted startup configuration for receiving direct Stage2 deliveries."""

from stage1_deliverable.common import identifier
from stage1_ledger.journal import decode
from stage2_workflow.ui_submission import valid_input_version
from .project_intake_contract import MAX_PROJECTS, MAX_REQUEST
from .project_stage2_direct_import import _verified, import_direct_request_project
from .session_api import _check


def load_direct_request_imports(service, credential, path, expected_sha256):
    """Validate the entire pinned host configuration before allocating a listener."""
    from .project_stage2 import _raw

    raw = _raw(path, expected_sha256, maximum=MAX_REQUEST)
    config = decode(raw, "direct Stage2 import configuration")
    _check(
        type(config) is dict
        and set(config) == {"kind", "schema_version", "entries"}
        and config["kind"] == "ProjectStage2DirectImportConfiguration"
        and config["schema_version"] == "1.0.0",
        "direct-import-config-shape",
        400,
    )
    entries = config["entries"]
    fields = {
        "delivery_dir",
        "expected_manifest_sha256",
        "expected_request_sha256",
        "project_id",
        "input_version",
    }
    _check(
        type(entries) is list and 0 < len(entries) <= MAX_PROJECTS,
        "direct-import-config-entries",
        400,
    )
    seen = set()
    for entry in entries:
        _check(
            type(entry) is dict and set(entry) == fields,
            "direct-import-config-entry-shape",
            400,
        )
        identifier(entry["project_id"])
        _check(
            entry["project_id"] not in seen,
            "direct-import-config-duplicate-project",
            400,
        )
        seen.add(entry["project_id"])
        _check(
            valid_input_version(entry["input_version"], allow_string=True),
            "direct-import-input-version-invalid",
            400,
        )
        _verified(
            entry["delivery_dir"],
            entry["expected_manifest_sha256"],
            entry["expected_request_sha256"],
        )
    bindings = {}
    for entry in entries:
        result = import_direct_request_project(service, credential, **entry)
        bindings[result["project_ref"]] = result["selection_binding"]
    return bindings
