"""Bind an original saved SDK observation to one existing Core source intent.

This local seam has no downloader, model, permit or retry. The caller owns the
project, current decision/version and mutation frontier. Its runtime hash is an
externally verified observation binding, not process or execution attestation.
Core journal writes cannot be rolled back; partial writes remain visible and
must be reconciled by the owner, never automatically repeated by this helper.
"""

from datetime import datetime, timezone
from pathlib import Path

from stage1_deliverable import sources
from stage1_deliverable.common import private_output, safe_path, sha
from stage1_deliverable.records import _text
from stage1_ledger.journal import decode
from stage1_ledger.sources import replay

from .project_stage1_delivery import (
    MAX_RECORD_BYTES,
    _raw,
    _source_attempt,
    _source_outcome,
)
from .project_stage1_sources import describe_source, source_record
from .session_api import _check, _hash

EVIDENCE_SCOPE = "saved-sdk-observation; not execution attestation"
REQUEST_FIELDS = {"operation", "doi", "url", "title", "output_dir", "public_only"}
SDK_STATUSES = {
    "available",
    "inaccessible",
    "rate-limited",
    "parse-error",
    "identity-mismatch",
}


def _time(value):
    observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _check(observed.tzinfo is not None, "source-observation-timezone-required")
    return observed.astimezone(timezone.utc)


def _inspect(ledger, root, start, path, expected_sha256):
    """Read and verify every declared byte before the first journal mutation."""
    original = _raw(path, expected_sha256)
    receipt = decode(original, "original SDK source observation")
    sources.validate_receipt_shape(receipt)
    _check(
        receipt["schema_version"] == "source-fetch-result/v1"
        and receipt["status"] in SDK_STATUSES,
        "source-observation-sdk-schema-differs",
    )
    request = start["request"]
    _check(
        set(request) == REQUEST_FIELDS
        and request == receipt["request"]
        and request["operation"] == "source fetch"
        and request["public_only"] is True
        and start["source_uri"] == (request["url"] or receipt["source_url"]),
        "source-observation-request-differs",
    )
    _check(
        Path(receipt["output_dir"]).absolute() == path.parent
        and Path(request["output_dir"]).absolute() == path.parent,
        "source-observation-original-directory-differs",
    )
    _check(
        receipt["receipt_sha256"] == sources.receipt_digest(receipt),
        "source-observation-sdk-digest-differs",
    )
    _check(len(receipt["attempts"]) <= 256, "source-observation-attempt-bound-exceeded")
    observed = _time(receipt["retrieved_at"])
    began, now = _time(start["created_at"]), _time(ledger.clock())
    _check(began <= observed <= now, "source-observation-time-order")
    for attempt in receipt["attempts"]:
        requested = _time(attempt["requested_at"])
        _check(began <= requested <= observed, "source-observation-attempt-time-order")
        if attempt["received_at"] is not None:
            _check(
                requested <= _time(attempt["received_at"]) <= observed,
                "source-observation-attempt-time-order",
            )
    mapping = sources.artifact_map(receipt)
    _check(
        len(set(mapping.values())) <= 256, "source-observation-artifact-bound-exceeded"
    )
    hashes = [
        (receipt["raw_path"], receipt["raw_sha256"]),
        (receipt["extracted_text_path"], receipt["extracted_text_sha256"]),
    ]
    hashes += [(a["raw_path"], a["raw_sha256"]) for a in receipt["attempts"]]
    data, total = {}, len(original)
    for name, digest in hashes:
        _check(
            (name is None) == (digest is None),
            "source-observation-artifact-pair-differs",
        )
        if name is None:
            continue
        _check(_hash(digest), "source-observation-artifact-hash-required")
        relative = mapping[name]
        raw = _raw(safe_path(path.parent, relative), digest)
        if relative in data:
            _check(data[relative] == raw, "source-observation-artifact-alias-differs")
        else:
            total += len(raw)
            _check(total <= MAX_RECORD_BYTES, "source-observation-bundle-too-large")
            data[relative] = raw
    selected = _source_attempt(receipt)
    outcome = _source_outcome(receipt)
    raw_name = receipt["raw_path"] or selected["raw_path"]
    raw = data[mapping[raw_name]] if raw_name is not None else original
    text = None
    if outcome == "available":
        _check(
            receipt["extracted_text_path"] is not None,
            "source-observation-text-required",
        )
        text = data[mapping[receipt["extracted_text_path"]]]
        _check(bool(text.decode("utf-8").strip()), "source-observation-text-empty")
    return receipt, original, raw, text


def complete_saved_source(
    ledger,
    *,
    materials_root,
    source_id,
    expected_start,
    result_path,
    expected_result_sha256,
    runtime_sha256,
    reason,
    check_current=None,
):
    """Complete exactly one open start using its unchanged original SDK bundle.

    ``expected_start`` is the owner's captured SourceReadStarted payload. The
    request must contain the SDK's six normalized receipt fields, recorded
    before I/O. Any external timeout/attempt budget stays in the owner's intent.
    ``check_current`` may recheck ownership before each local mutation; the
    caller still holds its own locks and makes the final durable action check.
    Repeated completion refuses, including after a true ledger reopen.
    """
    _text(reason)
    _check(
        _hash(expected_result_sha256) and _hash(runtime_sha256),
        "source-observation-hash-required",
    )
    _check(
        check_current is None or callable(check_current),
        "source-observation-check-required",
    )
    root = private_output(materials_root)
    _check(root.is_dir(), "source-observation-materials-root-required")
    path = Path(result_path).absolute()
    _check(path.is_relative_to(root), "source-observation-outside-materials-root")
    path = safe_path(root, path.relative_to(root).as_posix())
    with ledger.writing(repair=False):
        start = ledger.event(source_id, "SourceReadStarted")
        _check(
            isinstance(expected_start, dict) and start == expected_start,
            "source-observation-start-differs",
        )
        state = replay(ledger)
        _check(
            source_id not in state.finishes
            and state.latest.get((start["work_id"], start["version_id"])) == source_id,
            "source-observation-start-not-open",
        )
        receipt, original, raw, text = _inspect(
            ledger, root, start, path, expected_result_sha256
        )

        def check():
            if check_current is not None:
                check_current()

        check()
        # One exclusive Core writer lock covers validation and these existing
        # mutation implementations. Do not nest their public lock decorators.
        raw_ref = ledger.save_bytes.__wrapped__(ledger, raw, producer=source_id)
        text_ref = None
        if text is not None:
            check()
            text_ref = ledger.save_bytes.__wrapped__(ledger, text, producer=source_id)
        check()
        _inspect(ledger, root, start, path, expected_result_sha256)
        finish_id = ledger.finish_source.__wrapped__(
            ledger,
            attempt_id=source_id,
            outcome=_source_outcome(receipt),
            observed_at=receipt["retrieved_at"].replace("+00:00", "Z"),
            http_status=_source_attempt(receipt)["http_status"],
            resolved_uri=receipt["final_url"],
            raw_ref=raw_ref,
            text_ref=text_ref,
            extraction={"method": start["tool"], "version": "sha256:" + runtime_sha256}
            if text_ref is not None
            else None,
            reason=reason,
        )
        check()
        description = describe_source(
            ledger, root, source_id, path, expected_result_sha256, reason
        )
        source_record(ledger, root, description)
        return dict(
            source_id=source_id,
            finish_event_id=finish_id,
            finish=ledger.event(finish_id, "SourceReadFinished"),
            source_description=description,
            runtime_sha256=runtime_sha256,
            evidence_scope=EVIDENCE_SCOPE,
            original_receipt_sha256=sha(original),
            sdk_receipt_sha256=receipt["receipt_sha256"],
            ledger_state_sha256=ledger.state_hash(),
        )
