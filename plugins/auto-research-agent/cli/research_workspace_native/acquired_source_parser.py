"""Join a controlled acquisition observation to a distinct saved-public parser.

This component grants no source, import, model or scientific authority. Its
trusted caller supplies current job/request bindings, literal parse admission
and one existing deadline. The parser runner is unavailable by default; a
production runner must separately contain and stop its owned parser process.
Before/after checks here cannot interrupt a hung synchronous parser. Original
transport bytes and the SDK's import-saved/HTTP-unverified receipt never change.
An exclusive local intent precedes parsing; failed or repeated jobs need owner
reconciliation, never automatic replay or adoption of an existing output.
"""

from datetime import datetime, timezone
import ipaddress
import math
import os
from pathlib import Path
import stat
from urllib.parse import urlsplit

from stage1_deliverable import sources
from stage1_deliverable.common import (
    canonical,
    private_output,
    reject_links,
    safe_path,
    sha,
)
from stage1_ledger.journal import decode
from stage1_ledger.source_arguments import check_source_arguments

from .session_api import _check, _hash

MAX_BYTES = 16 * 1024 * 1024
MAX_JSON_BYTES = 256 * 1024
REQUEST_FIELDS = {
    "kind",
    "schema_version",
    "request_id",
    "job_binding_sha256",
    "source_uri",
    "runtime_sha256",
    "resolver_sha256",
    "deadline_utc",
    "total_timeout_seconds",
    "io_timeout_seconds",
    "max_http_attempts",
    "max_response_bytes",
    "max_aggregate_bytes",
}
RECEIPT_FIELDS = {
    "kind",
    "schema_version",
    "request",
    "request_sha256",
    "output_dir",
    "started_at",
    "finished_at",
    "status",
    "outcome",
    "final_url",
    "http_attempts",
    "http_requests_attempted",
    "aggregate_bytes",
    "attempts",
    "selected_attempt_sequence",
    "raw_path",
    "raw_sha256",
    "content_type",
    "body_bytes",
    "body_complete",
}
ATTEMPT_FIELDS = {
    "sequence",
    "url",
    "started_at",
    "finished_at",
    "resolved_addresses",
    "selected_address",
    "peer_address",
    "http_request_attempted",
    "http_status",
    "content_type",
    "outcome",
    "raw_path",
    "raw_sha256",
    "body_bytes",
    "body_complete",
    "error_code",
}


def _time(value):
    _check(type(value) is str and len(value) <= 128, "acquired-parse-time-invalid")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("acquired-parse-time-invalid") from error
    _check(result.tzinfo is not None, "acquired-parse-timezone-required")
    return result.astimezone(timezone.utc)


def _read(path, maximum, expected=None):
    """Bound a regular, single-link file and recheck its opened identity."""
    path = Path(path).absolute()
    reject_links(path)
    before = path.lstat()
    _check(
        stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
        "acquired-parse-file-invalid",
    )
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        reject_links(path)
        _check(
            stat.S_ISREG(opened.st_mode)
            and opened.st_nlink == 1
            and before.st_ino
            and (before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino),
            "acquired-parse-file-changed",
        )
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    _check(
        len(raw) <= maximum
        and (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns, opened.st_nlink)
        == (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_nlink),
        "acquired-parse-file-bound",
    )
    reject_links(path)
    if expected is not None:
        _check(
            _hash(expected) and sha(raw) == expected, "acquired-parse-file-hash-differs"
        )
    return raw


def _write_once(path, value):
    raw = canonical(value) + b"\n"
    with path.open("xb") as stream:
        _check(stream.write(raw) == len(raw), "acquired-parse-short-write")
        stream.flush()
        os.fsync(stream.fileno())
    _read(path, MAX_JSON_BYTES, sha(raw))
    return sha(raw)


def _uri(value):
    check_source_arguments(
        dict(kind="SourceReadStarted", source_uri=value, request={"public_only": True})
    )
    _check(type(value) is str and 0 < len(value) <= 4096, "acquired-parse-uri-invalid")
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        valid = (
            parsed.scheme in {"http", "https"}
            and host
            and not parsed.fragment
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443 if parsed.scheme == "https" else 80)
            and "%" not in host
            and "\\" not in value
            and not any(ord(char) < 33 for char in value)
            and host not in {"localhost", "localhost.localdomain"}
            and not host.endswith((".local", ".localhost", ".internal"))
        )
        try:
            address = ipaddress.ip_address(host)
            valid = valid and address.is_global and not address.is_multicast
        except ValueError:
            valid = valid and "." in host
    except ValueError:
        valid = False
    _check(bool(valid), "acquired-parse-uri-invalid")


def _acquisition(path, digest, request, job_sha, runtime_sha):
    raw = _read(path, MAX_JSON_BYTES, digest)
    receipt = decode(raw, "source acquisition receipt")
    _check(
        type(receipt) is dict and set(receipt) == RECEIPT_FIELDS,
        "acquired-parse-receipt-shape",
    )
    _check(
        receipt["kind"] == "PublicSourceAcquisitionReceipt"
        and receipt["schema_version"] == "1.0.0"
        and receipt["request"] == request
        and receipt["request_sha256"] == sha(canonical(request))
        and request["job_binding_sha256"] == job_sha
        and request["runtime_sha256"] == runtime_sha,
        "acquired-parse-binding-differs",
    )
    _check(
        Path(receipt["output_dir"]).absolute() == path.parent,
        "acquired-parse-original-directory-differs",
    )
    _check(
        receipt["status"] == "completed"
        and receipt["outcome"] == "http-body-complete"
        and receipt["body_complete"] is True,
        "acquired-parse-complete-acquisition-required",
    )
    began, ended = _time(receipt["started_at"]), _time(receipt["finished_at"])
    _check(
        began <= ended <= datetime.now(timezone.utc)
        and ended <= _time(request["deadline_utc"]),
        "acquired-parse-time-order",
    )
    attempts = receipt["attempts"]
    _check(
        type(attempts) is list
        and 0 < len(attempts) <= request["max_http_attempts"] <= 16,
        "acquired-parse-attempt-bound",
    )
    _check(
        attempts[0].get("url") == request["source_uri"],
        "acquired-parse-initial-uri-differs",
    )
    aggregate, calls, artifacts = 0, 0, {}
    for number, attempt in enumerate(attempts, 1):
        _check(
            type(attempt) is dict
            and set(attempt) == ATTEMPT_FIELDS
            and type(attempt["sequence"]) is int
            and attempt["sequence"] == number,
            "acquired-parse-attempt-shape",
        )
        _uri(attempt["url"])
        _check(
            began
            <= _time(attempt["started_at"])
            <= _time(attempt["finished_at"])
            <= ended,
            "acquired-parse-attempt-time-order",
        )
        _check(
            type(attempt["http_request_attempted"]) is bool
            and type(attempt["body_complete"]) is bool
            and type(attempt["body_bytes"]) is int
            and 0 <= attempt["body_bytes"] <= request["max_response_bytes"],
            "acquired-parse-attempt-values",
        )
        status = attempt["http_status"]
        _check(
            status is None or type(status) is int and 100 <= status <= 599,
            "acquired-parse-http-invalid",
        )
        addresses = attempt["resolved_addresses"]
        _check(
            type(addresses) is list and len(addresses) <= 64,
            "acquired-parse-address-bound",
        )
        if attempt["http_request_attempted"]:
            try:
                public = all(
                    ipaddress.ip_address(address).is_global
                    and not ipaddress.ip_address(address).is_multicast
                    for address in addresses
                )
            except (ValueError, TypeError):
                public = False
            _check(
                bool(addresses)
                and public
                and attempt["selected_address"] in addresses
                and attempt["peer_address"] == attempt["selected_address"],
                "acquired-parse-peer-observation-differs",
            )
        calls += int(attempt["http_request_attempted"])
        if attempt["raw_path"] is None:
            _check(
                attempt["raw_sha256"] is None and attempt["body_bytes"] == 0,
                "acquired-parse-raw-pair-differs",
            )
        else:
            relative = attempt["raw_path"]
            _check(relative not in artifacts, "acquired-parse-raw-alias")
            data = _read(
                safe_path(path.parent, relative),
                min(MAX_BYTES, request["max_response_bytes"]),
                attempt["raw_sha256"],
            )
            _check(
                len(data) == attempt["body_bytes"], "acquired-parse-raw-size-differs"
            )
            artifacts[relative] = sha(data)
        aggregate += attempt["body_bytes"]
    _check(
        type(receipt["http_attempts"]) is int
        and receipt["http_attempts"] == len(attempts)
        and type(receipt["http_requests_attempted"]) is int
        and receipt["http_requests_attempted"] == calls
        and type(receipt["aggregate_bytes"]) is int
        and receipt["aggregate_bytes"] == aggregate
        and aggregate <= min(MAX_BYTES, request["max_aggregate_bytes"]),
        "acquired-parse-counts-differ",
    )
    selected = attempts[-1]
    _uri(receipt["final_url"])
    _check(
        type(receipt["selected_attempt_sequence"]) is int
        and receipt["selected_attempt_sequence"] == len(attempts)
        and selected["url"] == receipt["final_url"]
        and selected["http_request_attempted"] is True
        and type(selected["http_status"]) is int
        and 200 <= selected["http_status"] < 300
        and selected["body_complete"] is True
        and selected["outcome"] == "http-body-complete"
        and all(
            receipt[key] == selected[key]
            for key in (
                "raw_path",
                "raw_sha256",
                "content_type",
                "body_bytes",
                "body_complete",
            )
        )
        and type(receipt["body_bytes"]) is int
        and receipt["body_bytes"] > 0,
        "acquired-parse-selected-observation-differs",
    )
    return receipt, artifacts


def parse_acquired_source(
    *,
    materials_root,
    acquisition_receipt_path,
    expected_acquisition_sha256,
    expected_request,
    expected_job_binding_sha256,
    runtime_sha256,
    expected_identity,
    parser_output_dir,
    parse_admission,
    deadline,
    parser_runner=None,
    check_current=None,
):
    """Parse only explicitly admitted fresh public bytes; never mutate Core.

    ``parser_runner`` accepts input_manifest, expected_manifest_sha256,
    output_dir and this same deadline. Its result must match the original SDK
    receipt it saved. Injecting a synchronous SDK runner proves parser behavior
    only; the caller still owns durable jobs and real timeout containment.
    """
    _check(parse_admission is True, "acquired-parse-admission-required")
    _check(callable(parser_runner), "acquired-parse-runner-unavailable")
    _check(
        check_current is None or callable(check_current),
        "acquired-parse-current-check-invalid",
    )
    _check(
        callable(getattr(deadline, "check", None)), "acquired-parse-deadline-required"
    )
    _check(
        type(expected_request) is dict
        and set(expected_request) == REQUEST_FIELDS
        and expected_request["kind"] == "BoundedPublicSourceRequest"
        and expected_request["schema_version"] == "1.0.0",
        "acquired-parse-request-shape",
    )
    _check(
        _hash(expected_acquisition_sha256)
        and _hash(expected_job_binding_sha256)
        and _hash(runtime_sha256)
        and _hash(expected_request["resolver_sha256"]),
        "acquired-parse-hash-required",
    )
    _check(
        type(expected_identity) is dict
        and set(expected_identity) == {"doi", "title"}
        and all(
            type(value) is str and len(value) <= (512 if key == "doi" else 4096)
            for key, value in expected_identity.items()
        ),
        "acquired-parse-identity-invalid",
    )
    _check(
        all(
            type(expected_request[key]) is int and expected_request[key] > 0
            for key in (
                "max_http_attempts",
                "max_response_bytes",
                "max_aggregate_bytes",
            )
        ),
        "acquired-parse-request-bounds",
    )
    _check(
        all(
            type(expected_request[key]) in (int, float)
            and math.isfinite(expected_request[key])
            and 0 < expected_request[key] <= 300
            for key in ("total_timeout_seconds", "io_timeout_seconds")
        )
        and expected_request["io_timeout_seconds"]
        <= expected_request["total_timeout_seconds"],
        "acquired-parse-request-timeout-invalid",
    )
    _check(
        type(expected_request["request_id"]) is str
        and 0 < len(expected_request["request_id"]) <= 128,
        "acquired-parse-request-id-invalid",
    )
    _uri(expected_request["source_uri"])

    def current():
        deadline.check()
        _check(
            datetime.now(timezone.utc) < _time(expected_request["deadline_utc"]),
            "acquired-parse-request-expired",
        )
        if check_current is not None:
            check_current()
        deadline.check()

    current()
    root = private_output(materials_root)
    _check(root.is_dir(), "acquired-parse-materials-root-required")
    path, output = (
        Path(acquisition_receipt_path).absolute(),
        Path(parser_output_dir).absolute(),
    )
    _check(
        path.is_relative_to(root)
        and output.is_relative_to(root)
        and path.name == "public-source-acquisition.json",
        "acquired-parse-private-path-required",
    )
    path = safe_path(root, path.relative_to(root).as_posix())
    output = safe_path(root, output.relative_to(root).as_posix())
    private_output(output)
    _check(
        output.parent.is_dir()
        and not output.exists()
        and not output.is_relative_to(path.parent),
        "acquired-parse-fresh-output-required",
    )
    receipt, acquisition_artifacts = _acquisition(
        path,
        expected_acquisition_sha256,
        expected_request,
        expected_job_binding_sha256,
        runtime_sha256,
    )
    manifest_path = safe_path(path.parent, "source-parse-input.json")
    intent_path = safe_path(path.parent, "source-parse-intent.json")
    _check(
        not manifest_path.exists() and not intent_path.exists(),
        "acquired-parse-existing-intent-refused",
    )
    manifest = dict(
        schema_version="saved-public-source-input/v1",
        url=expected_request["source_uri"],
        final_url=receipt["final_url"],
        doi=expected_identity["doi"],
        title=expected_identity["title"],
        raw_path=receipt["raw_path"],
        raw_sha256=receipt["raw_sha256"],
        content_type=receipt["content_type"],
        original_acquired_at=receipt["finished_at"],
    )
    current()
    intent = dict(
        kind="SourceAcquisitionParseIntent",
        schema_version="1.0.0",
        status="dispatch-unobserved",
        acquisition_receipt_sha256=expected_acquisition_sha256,
        request_sha256=receipt["request_sha256"],
        job_binding_sha256=expected_job_binding_sha256,
        runtime_sha256=runtime_sha256,
        manifest_sha256=sha(canonical(manifest) + b"\n"),
        parser_output_dir=str(output),
        expected_identity=expected_identity,
        created_at=datetime.now(timezone.utc).isoformat(),
        automatic_retry=False,
        evidence_scope="component intent; not native execution attestation",
    )
    intent_sha = _write_once(intent_path, intent)
    current()
    manifest_sha = _write_once(manifest_path, manifest)
    current()
    observed = parser_runner(
        input_manifest=manifest_path,
        expected_manifest_sha256=manifest_sha,
        output_dir=output,
        deadline=deadline,
    )
    current()
    sdk_path = safe_path(output, "source-fetch-result.json")
    sdk_raw = _read(sdk_path, MAX_JSON_BYTES)
    sdk = decode(sdk_raw, "original acquired-source parser receipt")
    sources.validate_receipt_shape(sdk)
    returned = (
        observed.to_dict() if callable(getattr(observed, "to_dict", None)) else observed
    )
    _check(
        returned == sdk and sdk["receipt_sha256"] == sources.receipt_digest(sdk),
        "acquired-parse-sdk-receipt-differs",
    )
    request = sdk["request"]
    from research_hub.utils.doi import normalize_doi

    _check(
        request["operation"] == "source import-saved"
        and request["public_only"] is True
        and request["url"] == manifest["url"]
        and request["doi"] == normalize_doi(manifest["doi"])
        and request["title"] == manifest["title"]
        and Path(request["output_dir"]).absolute() == output
        and Path(sdk["output_dir"]).absolute() == output
        and sdk["source_url"] == manifest["url"]
        and sdk["final_url"] == manifest["final_url"]
        and sdk["expected_identity"]
        == {"doi": request["doi"], "title": request["title"]}
        and sdk["source_version"] == "sha256:" + receipt["raw_sha256"],
        "acquired-parse-sdk-request-differs",
    )
    _check(
        sdk["schema_version"] == "source-fetch-result/v1"
        and sdk["status"]
        in {"available", "inaccessible", "parse-error", "identity-mismatch"}
        and sdk["evidence_level"] in {"metadata", "abstract", "full-text"},
        "acquired-parse-sdk-status-invalid",
    )
    diagnostics = sdk.get("diagnostics", {}).get("saved_import", {})
    _check(
        diagnostics.get("original_http_acquisition_verified") is False
        and diagnostics.get("manifest_sha256") == manifest_sha
        and diagnostics.get("manifest_schema_version") == manifest["schema_version"]
        and diagnostics.get("original_acquired_at") == manifest["original_acquired_at"],
        "acquired-parse-sdk-import-provenance-differs",
    )
    _check(
        len(sdk["attempts"]) == 2
        and [item["purpose"] for item in sdk["attempts"]]
        == ["saved-input-provenance", "saved-public-source"]
        and all(item["http_status"] is None for item in sdk["attempts"]),
        "acquired-parse-sdk-attempts-differ",
    )
    _check(
        _time(receipt["finished_at"])
        <= _time(sdk["retrieved_at"])
        <= datetime.now(timezone.utc),
        "acquired-parse-sdk-time-order",
    )
    selected = sdk["attempts"][-1]
    parsed = sdk["status"] in {"available", "identity-mismatch"}
    _check(
        (sdk["raw_path"], sdk["raw_sha256"])
        == ((selected["raw_path"], receipt["raw_sha256"]) if parsed else (None, None))
        and (sdk["extracted_text_path"] is not None) == parsed
        and (sdk["extracted_text_sha256"] is not None) == parsed,
        "acquired-parse-sdk-selected-bytes-differ",
    )
    mapping, artifacts, total = sources.artifact_map(sdk), {}, len(sdk_raw)
    for item in sdk["attempts"]:
        _check(
            item["url"] == manifest["url"]
            and item["final_url"] == manifest["final_url"]
            and _time(receipt["finished_at"])
            <= _time(item["requested_at"])
            <= _time(item["received_at"])
            <= _time(sdk["retrieved_at"])
            and item["response_truncated"] is False,
            "acquired-parse-sdk-attempt-binding-differs",
        )
        relative = mapping[item["raw_path"]]
        _check(relative not in artifacts, "acquired-parse-sdk-artifact-alias")
        data = _read(safe_path(output, relative), MAX_BYTES, item["raw_sha256"])
        _check(
            len(data) == item["response_bytes"],
            "acquired-parse-sdk-artifact-size-differs",
        )
        artifacts[relative] = sha(data)
        total += len(data)
        _check(
            data
            == (
                canonical(manifest) + b"\n"
                if item["purpose"] == "saved-input-provenance"
                else _read(
                    safe_path(path.parent, receipt["raw_path"]),
                    MAX_BYTES,
                    receipt["raw_sha256"],
                )
            ),
            "acquired-parse-sdk-original-bytes-differ",
        )
    if sdk["extracted_text_path"] is not None:
        relative = mapping[sdk["extracted_text_path"]]
        _check(relative not in artifacts, "acquired-parse-sdk-artifact-alias")
        text = _read(
            safe_path(output, relative), MAX_BYTES, sdk["extracted_text_sha256"]
        )
        _check(bool(text.decode("utf8").strip()), "acquired-parse-sdk-text-empty")
        total += len(text)
        artifacts[relative] = sha(text)
    _check(total <= MAX_BYTES, "acquired-parse-sdk-bundle-bound")
    _read(manifest_path, MAX_JSON_BYTES, manifest_sha)
    _read(intent_path, MAX_JSON_BYTES, intent_sha)
    _acquisition(
        path,
        expected_acquisition_sha256,
        expected_request,
        expected_job_binding_sha256,
        runtime_sha256,
    )
    current()
    bundle = dict(
        kind="SourceAcquisitionParseBundle",
        schema_version="1.0.0",
        job_binding_sha256=expected_job_binding_sha256,
        request_sha256=receipt["request_sha256"],
        runtime_sha256=runtime_sha256,
        acquisition=dict(
            receipt_path=path.relative_to(root).as_posix(),
            receipt_sha256=expected_acquisition_sha256,
            artifacts=acquisition_artifacts,
            http_status=receipt["attempts"][-1]["http_status"],
            final_url=receipt["final_url"],
            observed_at=receipt["finished_at"],
        ),
        parser=dict(
            receipt_path=sdk_path.relative_to(root).as_posix(),
            receipt_sha256=sha(sdk_raw),
            sdk_receipt_sha256=sdk["receipt_sha256"],
            manifest_path=manifest_path.relative_to(root).as_posix(),
            manifest_sha256=manifest_sha,
            intent_path=intent_path.relative_to(root).as_posix(),
            intent_sha256=intent_sha,
            artifacts=artifacts,
            status=sdk["status"],
            evidence_level=sdk["evidence_level"],
            identity_status=sdk["identity_status"],
            original_http_acquisition_verified=False,
        ),
        automatic_retry=False,
        evidence_scope="saved controlled transport and SDK import parser observations; not native or scientific acceptance",
    )
    bundle_path = safe_path(output, "source-acquisition-parse-bundle.json")
    bundle_sha = _write_once(bundle_path, bundle)
    current()
    return dict(bundle=bundle, bundle_path=str(bundle_path), bundle_sha256=bundle_sha)
