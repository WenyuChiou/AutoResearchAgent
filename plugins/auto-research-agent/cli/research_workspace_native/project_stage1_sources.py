"""Inspect already saved, original public-reader observations; never acquire."""

from pathlib import Path

from stage1_deliverable import sources
from stage1_deliverable.common import safe_path, sha
from stage1_ledger.journal import canonical, decode

from .project_stage1_delivery import (
    MAX_RECORD_BYTES,
    _raw,
    _source_attempt,
    _source_outcome,
)
from .session_api import _check
from .project_stage1_saved_import import source_observation_time_matches


def source_record(ledger, materials_root, entry):
    """Recompute physical and Core bindings of a trusted registry entry."""
    events = {row["payload"]["event_id"]: row["payload"] for row in ledger.events()}
    start = events.get(entry["source_id"])
    _check(
        start is not None and start["kind"] == "SourceReadStarted",
        "saved-source-start-required",
    )
    finishes = [
        row
        for row in events.values()
        if row["kind"] == "SourceReadFinished"
        and row["attempt_id"] == start["event_id"]
    ]
    _check(len(finishes) == 1, "saved-source-finish-required")
    finish = finishes[0]
    path = safe_path(materials_root, entry["result_path"])
    raw = _raw(path, entry["result_sha256"])
    receipt = decode(raw, "original saved source receipt")
    sources.validate_receipt_shape(receipt)
    _check(
        Path(receipt["output_dir"]).absolute() == path.parent
        and Path(receipt["request"]["output_dir"]).absolute() == path.parent,
        "saved-source-original-directory-differs",
    )
    _check(
        receipt["receipt_sha256"] == sources.receipt_digest(receipt),
        "saved-source-sdk-digest-differs",
    )
    observed = _source_attempt(receipt)
    _check(
        entry["work_id"] == start["work_id"]
        and entry["version_id"] == start["version_id"]
        and entry["finish_event_id"] == finish["event_id"]
        and entry["start_sha256"] == sha(canonical(start))
        and entry["finish_sha256"] == sha(canonical(finish))
        and finish["outcome"] == _source_outcome(receipt)
        and start["source_uri"] == (receipt["request"]["url"] or receipt["source_url"])
        and finish["resolved_uri"] == receipt["final_url"]
        and finish["http_status"] == observed["http_status"]
        and source_observation_time_matches(
            start,
            finish,
            receipt,
            entry["result_sha256"],
            materials_root=materials_root,
            result_path=path,
        ),
        "saved-source-core-observation-differs",
    )
    artifacts = {
        name: sha(_raw(safe_path(path.parent, name), digest))
        for name, digest in entry["artifacts"].items()
    }
    mapping = sources.artifact_map(receipt)
    _check(set(artifacts) == set(mapping.values()), "saved-source-artifact-set-differs")
    hashes = [
        (receipt["raw_path"], receipt["raw_sha256"]),
        (receipt["extracted_text_path"], receipt["extracted_text_sha256"]),
    ]
    hashes += [(row["raw_path"], row["raw_sha256"]) for row in receipt["attempts"]]
    for name, digest in hashes:
        if name is not None:
            _check(
                artifacts[mapping[name]] == digest, "saved-source-artifact-hash-differs"
            )
    if finish["raw_ref"] is not None:
        expected = receipt["raw_sha256"] or observed["raw_sha256"]
        actual = ledger.read_ref(finish["raw_ref"])
        _check(
            sha(actual) == expected
            if expected is not None
            else actual == raw and finish["outcome"] != "available",
            "saved-source-core-raw-differs",
        )
    if finish["text_ref"] is not None:
        _check(
            sha(ledger.read_ref(finish["text_ref"]))
            == receipt["extracted_text_sha256"],
            "saved-source-core-text-differs",
        )
    return {
        key: entry[key]
        for key in (
            "source_id",
            "work_id",
            "version_id",
            "result_path",
            "result_sha256",
            "access_note",
        )
    }, receipt


def describe_source(ledger, materials_root, source_id, path, digest, access_note):
    """Capture only a server-selected original receipt under its fixed root."""
    path = Path(path).absolute()
    _check(path.is_relative_to(materials_root), "saved-source-outside-materials-root")
    start = ledger.event(source_id, "SourceReadStarted")
    finishes = [
        row["payload"]
        for row in ledger.events()
        if row["payload"]["kind"] == "SourceReadFinished"
        and row["payload"]["attempt_id"] == source_id
    ]
    _check(len(finishes) == 1, "saved-source-finish-required")
    receipt = decode(_raw(path, digest), "original source receipt")
    sources.validate_receipt_shape(receipt)
    entry = dict(
        source_id=source_id,
        work_id=start["work_id"],
        version_id=start["version_id"],
        finish_event_id=finishes[0]["event_id"],
        start_sha256=sha(canonical(start)),
        finish_sha256=sha(canonical(finishes[0])),
        result_path=path.relative_to(materials_root).as_posix(),
        result_sha256=digest,
        access_note=access_note,
        artifacts={
            name: artifact_digest(safe_path(path.parent, name))
            for name in set(sources.artifact_map(receipt).values())
        },
    )
    source_record(ledger, materials_root, entry)
    return entry


def artifact_digest(path):
    with path.open("rb") as stream:
        raw = stream.read(MAX_RECORD_BYTES + 1)
    _check(len(raw) <= MAX_RECORD_BYTES, "saved-source-artifact-too-large")
    digest = sha(raw)
    _raw(path, digest)
    return digest
