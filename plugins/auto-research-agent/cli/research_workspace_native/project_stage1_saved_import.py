"""Reconcile untouched SDK import-saved bytes with a later local Core read.

This is a saved-input observation, not HTTP execution or acquisition attestation.
The owner records a new SourceReadStarted after the original SDK observation,
holds the real mutation guard and persists its action intent before calling the
completion helper. No source, parser, model, retry or permissions are created.
"""

from datetime import datetime, timezone
from pathlib import Path
import stat

from stage1_deliverable import sources
from stage1_deliverable.common import private_output, reject_links, safe_path, sha
from stage1_deliverable.records import _text
from stage1_ledger.journal import decode
from stage1_ledger.sources import replay

from .session_api import _check, _hash

TOOL = "saved-sdk-source-import"
KIND = "SavedSdkSourceImport"
MAX_BYTES = 16 * 1024 * 1024
SCOPE = "saved SDK import-saved local observation; not HTTP, native or scientific acceptance"


def _time(value):
    observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _check(observed.tzinfo is not None, "saved-import-timezone-required")
    return observed.astimezone(timezone.utc)


def _read(path, digest):
    _check(_hash(digest), "saved-import-hash-required")
    reject_links(path)
    _check(stat.S_ISREG(path.stat().st_mode), "saved-import-not-regular")
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    _check(len(raw) <= MAX_BYTES and sha(raw) == digest, "saved-import-bytes-differ")
    return raw


def _inspect(materials_root, result_path, result_sha256):
    """Reopen the original SDK receipt and every declared saved artifact."""
    from research_hub.source_fetch_saved import validate_saved_input_manifest
    from research_hub.utils.doi import normalize_doi

    root = private_output(materials_root)
    path = Path(result_path).absolute()
    _check(root.is_dir() and path.is_relative_to(root), "saved-import-outside-root")
    path = safe_path(root, path.relative_to(root).as_posix())
    original = _read(path, result_sha256)
    receipt = decode(original, "original SDK import-saved receipt")
    sources.validate_receipt_shape(receipt)
    request = receipt["request"]
    _check(
        receipt["schema_version"] == "source-fetch-result/v1"
        and set(request)
        == {"operation", "doi", "url", "title", "output_dir", "public_only"}
        and request["operation"] == "source import-saved"
        and request["public_only"] is True
        and Path(request["output_dir"]).absolute() == path.parent
        and Path(receipt["output_dir"]).absolute() == path.parent
        and receipt["receipt_sha256"] == sources.receipt_digest(receipt)
        and receipt["status"]
        in {"available", "inaccessible", "parse-error", "identity-mismatch"},
        "saved-import-sdk-binding-differs",
    )
    attempts = receipt["attempts"]
    _check(
        len(attempts) == 2
        and all(type(a["sequence"]) is int for a in attempts)
        and [a["sequence"] for a in attempts] == [1, 2]
        and [a["purpose"] for a in attempts]
        == ["saved-input-provenance", "saved-public-source"]
        and all(
            a["http_status"] is None and a["response_truncated"] is False
            for a in attempts
        ),
        "saved-import-attempts-differ",
    )
    mapping = sources.artifact_map(receipt)
    hashes = [
        (receipt["raw_path"], receipt["raw_sha256"]),
        (receipt["extracted_text_path"], receipt["extracted_text_sha256"]),
    ]
    hashes += [(a["raw_path"], a["raw_sha256"]) for a in attempts]
    artifacts, data, total = {}, {}, len(original)
    for name, digest in hashes:
        _check((name is None) == (digest is None), "saved-import-artifact-pair-differs")
        if name is None:
            continue
        relative = mapping[name]
        raw = _read(safe_path(path.parent, relative), digest)
        if relative in data:
            _check(data[relative] == raw, "saved-import-artifact-alias-differs")
        else:
            total += len(raw)
            _check(total <= MAX_BYTES, "saved-import-bundle-too-large")
            data[relative], artifacts[relative] = raw, digest
    provenance = data[mapping[attempts[0]["raw_path"]]]
    manifest = decode(provenance, "original SDK saved-input provenance")
    validated_manifest = validate_saved_input_manifest(manifest)
    diagnostics = receipt.get("diagnostics", {}).get("saved_import", {})
    _check(
        type(manifest) is dict
        and type(diagnostics) is dict
        and set(diagnostics)
        == {
            "manifest_sha256",
            "manifest_schema_version",
            "original_acquired_at",
            "import_started_at",
            "import_completed_at",
            "imported_at",
            "original_http_acquisition_verified",
        }
        and set(manifest)
        == {
            "schema_version",
            "url",
            "final_url",
            "doi",
            "title",
            "raw_path",
            "raw_sha256",
            "content_type",
            "original_acquired_at",
        }
        and manifest["schema_version"] == "saved-public-source-input/v1"
        and diagnostics.get("manifest_schema_version") == manifest["schema_version"]
        and diagnostics.get("manifest_sha256") == sha(provenance)
        and diagnostics.get("original_http_acquisition_verified") is False
        and diagnostics.get("original_acquired_at") == manifest["original_acquired_at"]
        and request["url"] == validated_manifest["url"] == receipt["source_url"]
        and request["doi"] == normalize_doi(manifest["doi"])
        and request["title"] == validated_manifest["title"]
        and receipt["expected_identity"]
        == {"doi": request["doi"], "title": request["title"]}
        and receipt["final_url"] == validated_manifest["final_url"]
        and attempts[0]["raw_path"] != attempts[1]["raw_path"]
        and attempts[0]["content_type"] == "application/json"
        and attempts[0]["outcome"] == "imported"
        and attempts[0]["error"] is None
        and attempts[1]["content_type"] == validated_manifest["content_type"]
        and attempts[1]["outcome"]
        == (
            "parsed"
            if receipt["status"] in {"available", "identity-mismatch"}
            else receipt["status"]
        )
        and attempts[1]["raw_sha256"] == manifest["raw_sha256"]
        and diagnostics["import_completed_at"]
        == diagnostics["imported_at"]
        == receipt["retrieved_at"]
        and receipt["source_version"] == "sha256:" + manifest["raw_sha256"],
        "saved-import-original-provenance-differs",
    )
    parsed = receipt["status"] in {"available", "identity-mismatch"}
    _check(
        (
            receipt["raw_path"] == attempts[1]["raw_path"]
            and receipt["raw_sha256"] == attempts[1]["raw_sha256"]
            and receipt["extracted_text_path"] is not None
            and attempts[1]["error"] is None
        )
        if parsed
        else all(
            receipt[field] is None
            for field in (
                "raw_path",
                "raw_sha256",
                "extracted_text_path",
                "extracted_text_sha256",
            )
        ),
        "saved-import-selected-artifact-differs",
    )
    retrieved = _time(receipt["retrieved_at"])
    _check(
        _time(manifest["original_acquired_at"])
        <= _time(diagnostics["import_started_at"])
        <= retrieved
        <= datetime.now(timezone.utc),
        "saved-import-original-time-order",
    )
    for attempt in attempts:
        _check(
            attempt["requested_at"] == diagnostics["import_started_at"]
            and attempt["received_at"] == diagnostics["import_completed_at"]
            and attempt["url"] == request["url"]
            and attempt["final_url"] == receipt["final_url"]
            and _time(manifest["original_acquired_at"])
            <= _time(attempt["requested_at"])
            <= _time(attempt["received_at"])
            <= retrieved,
            "saved-import-original-attempt-differs",
        )
        _check(
            len(data[mapping[attempt["raw_path"]]]) == attempt["response_bytes"],
            "saved-import-original-size-differs",
        )
    _read(path, result_sha256)
    return root, path, receipt, original, data, mapping


def _request(receipt, result_sha256, runtime_sha256):
    _check(_hash(runtime_sha256), "saved-import-runtime-hash-required")
    return dict(
        kind=KIND,
        schema_version="1.0.0",
        public_only=True,
        sdk_request=receipt["request"],
        sdk_result_sha256=result_sha256,
        runtime_sha256=runtime_sha256,
    )


def prepare_saved_sdk_import(
    *,
    materials_root,
    result_path,
    expected_result_sha256,
    runtime_sha256,
    check_current,
):
    """Trusted owner selects a saved receipt; this proposal grants no authority."""
    _check(callable(check_current), "saved-import-owner-check-required")
    check_current()
    _, _, receipt, _, _, _ = _inspect(
        materials_root, result_path, expected_result_sha256
    )
    check_current()
    return dict(
        tool=TOOL,
        source_uri=receipt["request"]["url"] or receipt["source_url"],
        request=_request(receipt, expected_result_sha256, runtime_sha256),
        sdk_retrieved_at=receipt["retrieved_at"],
        execution_authorized=False,
        evidence_scope=SCOPE,
    )


def source_observation_time_matches(
    start, finish, receipt, receipt_sha256, *, materials_root, result_path
):
    """Keep the old fetch equality; only the exact import kind has later time."""
    if start["tool"] != TOOL:
        return datetime.fromisoformat(
            finish["observed_at"].replace("Z", "+00:00")
        ) == datetime.fromisoformat(receipt["retrieved_at"].replace("Z", "+00:00"))
    runtime = start["request"].get("runtime_sha256")
    _, _, actual, _, _, _ = _inspect(materials_root, result_path, receipt_sha256)
    _check(
        actual == receipt
        and start["request"] == _request(actual, receipt_sha256, runtime)
        and finish["http_status"] is None,
        "saved-import-core-request-differs",
    )
    expected = (
        {"method": TOOL, "version": "sha256:" + runtime}
        if finish["text_ref"] is not None
        else None
    )
    _check(finish["extraction"] == expected, "saved-import-core-extraction-differs")
    return (
        _time(receipt["retrieved_at"])
        <= _time(start["created_at"])
        <= _time(finish["observed_at"])
        <= _time(finish["created_at"])
    )


def complete_saved_sdk_import(
    ledger,
    *,
    materials_root,
    source_id,
    expected_start,
    result_path,
    expected_result_sha256,
    runtime_sha256,
    reason,
    check_current,
):
    """Complete one owned local start; original SDK/acquired times never change."""
    from .project_stage1_delivery import _source_attempt, _source_outcome
    from .project_stage1_sources import describe_source, source_record

    _text(reason)
    _check(callable(check_current), "saved-import-owner-check-required")
    with ledger.writing(repair=False):
        check_current()
        start = ledger.event(source_id, "SourceReadStarted")
        state = replay(ledger)
        _check(
            start == expected_start
            and start["tool"] == TOOL
            and source_id not in state.finishes
            and state.latest.get((start["work_id"], start["version_id"])) == source_id,
            "saved-import-source-start-not-open",
        )
        root, path, receipt, original, data, mapping = _inspect(
            materials_root, result_path, expected_result_sha256
        )
        _check(
            start["request"]
            == _request(receipt, expected_result_sha256, runtime_sha256)
            and start["source_uri"]
            == (receipt["request"]["url"] or receipt["source_url"])
            and _time(receipt["retrieved_at"]) <= _time(start["created_at"]),
            "saved-import-source-start-differs",
        )
        attempt, outcome = _source_attempt(receipt), _source_outcome(receipt)
        raw_name = receipt["raw_path"] or attempt["raw_path"]
        raw = data[mapping[raw_name]] if raw_name is not None else original
        text = None
        if outcome == "available":
            _check(
                receipt["extracted_text_path"] is not None, "saved-import-text-required"
            )
            text = data[mapping[receipt["extracted_text_path"]]]
            _check(bool(text.decode("utf-8").strip()), "saved-import-text-empty")
        check_current()
        raw_ref = ledger.save_bytes.__wrapped__(ledger, raw, producer=source_id)
        text_ref = None
        if text is not None:
            check_current()
            text_ref = ledger.save_bytes.__wrapped__(ledger, text, producer=source_id)
        check_current()
        _inspect(root, path, expected_result_sha256)
        observed_at = ledger.clock()
        finish_id = ledger.finish_source.__wrapped__(
            ledger,
            attempt_id=source_id,
            outcome=outcome,
            observed_at=observed_at,
            http_status=None,
            resolved_uri=receipt["final_url"],
            raw_ref=raw_ref,
            text_ref=text_ref,
            extraction={"method": TOOL, "version": "sha256:" + runtime_sha256}
            if text is not None
            else None,
            reason=reason,
        )
        check_current()
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
            original_receipt_sha256=sha(original),
            sdk_receipt_sha256=receipt["receipt_sha256"],
            original_acquired_at=receipt["diagnostics"]["saved_import"][
                "original_acquired_at"
            ],
            sdk_retrieved_at=receipt["retrieved_at"],
            local_observed_at=observed_at,
            original_http_acquisition_verified=False,
            automatic_retry=False,
            evidence_scope=SCOPE,
            ledger_state_sha256=ledger.state_hash(),
        )
