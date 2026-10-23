"""Strict pure dispatch for saved-text reading and full-source analysis."""

from .project_full_analysis import (
    ANALYZE_OPERATION,
    ANALYZE_SCOPE,
    full_analysis_draft,
    full_analysis_prompt,
)
from .project_full_reading import (
    FULL_READ_OPERATION,
    FULL_READ_SCOPE,
    full_reading_prompt,
    model_reading_draft as _reading_draft,
    model_reading_prompt as _reading_prompt,
)
from .project_model_reading import READ_OPERATION, READ_SCOPE, reading_prompt
from .session_api import _check


READING_OPERATIONS = {READ_OPERATION, FULL_READ_OPERATION, ANALYZE_OPERATION}
FULL_SOURCE_OPERATIONS = {FULL_READ_OPERATION, ANALYZE_OPERATION}

_LEGACY_KIND = "Stage1SavedTextReadingInput"
_FULL_KIND = "Stage1SavedFullSourceReadingInput"
_ANALYSIS_KIND = "Stage1SavedFullSourceAnalysisInput"
_KINDS = {_LEGACY_KIND, _FULL_KIND, _ANALYSIS_KIND}
_LEGACY_FIELDS = {
    "kind",
    "schema_version",
    "principal",
    "project_ref",
    "project_id",
    "input_version",
    "brief_sha256",
    "basis",
    "ledger_state_sha256",
    "checkpoint",
    "work_id",
    "version_id",
    "candidate_event_id",
    "decision_event_id",
    "review_event_id",
    "discovery",
    "sources",
    "source_failures",
    "existing_claims",
    "model_creates_core_claims",
    "entire_work_read",
    "scientific_acceptance",
}


def _kind(snapshot):
    _check(type(snapshot) is dict, "reading-dispatch-snapshot-fields", 400)
    kind = snapshot.get("kind")
    _check(
        type(kind) is str and kind in _KINDS, "reading-dispatch-kind-unsupported", 400
    )
    _check(
        snapshot.get("schema_version") == "1.0.0",
        "reading-dispatch-schema-version",
        400,
    )
    if kind == _LEGACY_KIND:
        _check(
            set(snapshot) == _LEGACY_FIELDS,
            "reading-dispatch-legacy-fields",
            400,
        )
    return kind


def reading_scope(operation):
    _check(
        type(operation) is str and operation in READING_OPERATIONS,
        "reading-dispatch-operation",
        400,
    )
    if operation == ANALYZE_OPERATION:
        return ANALYZE_SCOPE
    if operation == FULL_READ_OPERATION:
        return FULL_READ_SCOPE
    return READ_SCOPE


def model_reading_prompt(snapshot):
    kind = _kind(snapshot)
    if kind == _ANALYSIS_KIND:
        return full_analysis_prompt(snapshot)
    return _reading_prompt(snapshot)


def model_reading_draft(raw, snapshot):
    kind = _kind(snapshot)
    if kind == _ANALYSIS_KIND:
        return full_analysis_draft(raw, snapshot)
    return _reading_draft(raw, snapshot)


def reading_metadata(snapshot):
    kind = _kind(snapshot)
    if kind == _ANALYSIS_KIND:
        full_analysis_prompt(snapshot)
        return snapshot["reading_input"]["saved_reading"]
    if kind == _FULL_KIND:
        full_reading_prompt(snapshot)
        return snapshot["saved_reading"]
    reading_prompt(snapshot)
    return snapshot
