"""Seal a verified native capture to receipt-bound raw trace bytes."""

import hashlib
import json
import os
from pathlib import Path
import stat

from stage2_common import canonical_hash

from .native import verify_capture
from .trace_files import (
    MAX_FILE_BYTES,
    _fail,
    _json,
    _load_inventory,
    _regular,
    _require,
)
from .trace_seal_io import SealDirectory
from .trace_observation import inspect_native_trace

SEAL_NAME = "seal.json"
_HEX = set("0123456789abcdef")
_CREDENTIAL_MARKERS = ("auth", "credential", "secret", "token", "api_key")


def _absolute(value):
    return Path(os.path.abspath(os.fspath(value)))


def _safe_root(value, label, *, new=False):
    path = _absolute(value)
    if new:
        _require(not os.path.lexists(path), f"{label}-already-exists")
        current = path.parent
    else:
        current = path
    for item in (current, *current.parents):
        status = _regular(item, label)
        _require(stat.S_ISDIR(status.st_mode), f"{label}-not-directory")
    return path


def _separate(output, *sources):
    for source in sources:
        source = _absolute(source)
        if (
            output == source
            or output.is_relative_to(source)
            or source.is_relative_to(output)
        ):
            _fail("seal-output-overlap")


def _validate_trace_names(receipt):
    _require(isinstance(receipt, dict) and bool(receipt), "receipt-invalid")
    for name in receipt:
        _require(isinstance(name, str) and bool(name), "receipt-path-invalid")
        if name in {"manifest.json", "trace.jsonl"}:
            continue
        parts = name.split("/")
        _require(
            len(parts) == 2 and parts[0] == "payloads" and parts[1].endswith(".json"),
            "unexpected-trace-file",
        )
        folded = parts[1].casefold()
        _require(
            not any(marker in folded for marker in _CREDENTIAL_MARKERS),
            "credential-like-trace-file",
        )


def _top_level(bound):
    names = set()
    with os.scandir(bound.target) as entries:
        for entry in entries:
            _require(
                entry.name in {SEAL_NAME, "trace"}
                and entry.name not in names
                and len(names) < 2,
                "seal-inventory-mismatch",
            )
            names.add(entry.name)
    _require(names == {SEAL_NAME, "trace"}, "seal-inventory-mismatch")
    seal_status = bound.status(SEAL_NAME)
    trace_status = bound.status("trace")
    _require(
        stat.S_ISREG(seal_status.st_mode)
        and not getattr(seal_status, "st_file_attributes", 0) & 0x400,
        "seal-control-file-invalid",
    )
    _require(
        stat.S_ISDIR(trace_status.st_mode)
        and not getattr(trace_status, "st_file_attributes", 0) & 0x400,
        "seal-trace-directory-invalid",
    )
    return seal_status


def _read_control(output):
    def identity(value):
        return value.st_dev, value.st_ino, value.st_size

    with SealDirectory(output) as bound:
        expected = _top_level(bound)
        _require(expected.st_size <= MAX_FILE_BYTES, "seal-file-size-limit")
        with bound.reader(SEAL_NAME) as stream:
            before = os.fstat(stream.fileno())
            _require(
                identity(expected) == identity(before), "seal-control-file-replaced"
            )
            value = stream.read(MAX_FILE_BYTES + 1)
            after = os.fstat(stream.fileno())
            _require(identity(before) == identity(after), "seal-control-file-changed")
    _require(len(value) <= MAX_FILE_BYTES, "seal-file-size-limit")
    return value


def _manifest_bytes(value):
    try:
        return (
            json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
        ).encode()
    except (TypeError, ValueError) as error:
        _fail(f"seal-json-invalid: {error}")


def _models(observation, raw):
    models = []
    for inference in observation["inferences"]:
        request = _json(raw[inference["request_ref"]], inference["request_ref"])
        model = request.get("model") if isinstance(request, dict) else None
        _require(isinstance(model, str) and model, "inference-model-missing")
        models.append(model)
    _require(bool(models), "inference-models-missing")
    return models


def _bind(record, observation, raw):
    summary = record.get("event_summary")
    stable = record.get("stable_request_binding")
    _require(
        isinstance(summary, dict) and isinstance(stable, dict),
        "capture-binding-invalid",
    )
    _require(
        observation["root_thread_id"] == summary.get("thread_id"),
        "capture-trace-root-mismatch",
    )
    model = stable.get("model")
    _require(
        isinstance(model, str)
        and model
        and all(value == model for value in _models(observation, raw)),
        "capture-trace-model-mismatch",
    )
    return model


def _write_trace(bound, raw):
    with bound.make_dir("trace") as trace, trace.make_dir("payloads") as payloads:
        for name, value in sorted(raw.items()):
            directory, leaf = (
                (payloads, name.split("/", 1)[1])
                if name.startswith("payloads/")
                else (trace, name)
            )
            directory.write(leaf, value)


def _seal_trace_capture(
    *,
    capture_dir,
    capture_receipt,
    trace_root,
    inventory_receipt,
    trace_receipt_sha256,
    output_dir,
    resume=False,
    seal_receipt=None,
    allow_injected_test_capture=False,
):
    """Private injected-capture seam; never changes the seal evidence class."""
    output = _absolute(output_dir)
    if resume:
        _require(isinstance(seal_receipt, str), "seal-receipt-required")
        manifest, record = _verify_core(
            output, seal_receipt, capture_dir, capture_receipt
        )
        _require(
            manifest["trace"]["receipt_sha256"] == trace_receipt_sha256
            and manifest["trace"]["inventory"] == inventory_receipt,
            "resume-trace-binding-mismatch",
        )
        _separate(
            output,
            capture_dir,
            trace_root,
            record["stable_request_binding"]["workspace"],
            record["stable_request_binding"]["codex_home"],
        )
        return {**manifest, "seal_receipt": seal_receipt}
    _require(seal_receipt is None, "unexpected-seal-receipt")
    capture = _safe_root(capture_dir, "capture-root")
    trace = _safe_root(trace_root, "trace-root")
    record, _ = verify_capture(
        capture,
        capture_receipt,
        allow_injected_test_capture=allow_injected_test_capture,
    )
    output = _safe_root(output, "seal-output", new=True)
    stable = record["stable_request_binding"]
    _separate(output, capture, trace, stable["workspace"], stable["codex_home"])
    _validate_trace_names(inventory_receipt)
    raw = _load_inventory(trace, inventory_receipt, trace_receipt_sha256)
    observation = inspect_native_trace(trace, inventory_receipt, trace_receipt_sha256)
    model = _bind(record, observation, raw)
    manifest = {
        "kind": "Stage2TraceCaptureSeal",
        "schema_version": "1.0.0",
        "status": "complete",
        "evidence_class": "receipt-bound-content-link",
        "formal_ready": False,
        "capture": {
            "record_sha256_receipt": capture_receipt,
            "capture_mode": record["capture_mode"],
            "capture_evidence_class": record["evidence_class"],
            "injected_test_capture": record["capture_mode"] == "injected-test-adapter",
            "root_thread_id": record["event_summary"]["thread_id"],
            "requested_model": model,
        },
        "trace": {
            "inventory": inventory_receipt,
            "receipt_sha256": trace_receipt_sha256,
        },
        "observation": observation,
        "observation_sha256": canonical_hash(observation),
        "limitations": [
            "post-execution content linkage only",
            "genuine producer acquisition is not established by this seal",
        ],
    }
    encoded = _manifest_bytes(manifest)
    with SealDirectory(output.parent) as parent, parent.make_dir(output.name) as bound:
        _write_trace(bound, raw)
        bound.write(SEAL_NAME, encoded)
    receipt = hashlib.sha256(encoded).hexdigest()
    _verify_core(output, receipt, capture, capture_receipt)
    return {**manifest, "seal_receipt": receipt}


def seal_trace_capture(
    *,
    capture_dir,
    capture_receipt,
    trace_root,
    inventory_receipt,
    trace_receipt_sha256,
    output_dir,
    resume=False,
    seal_receipt=None,
):
    """Create or resume a non-formal receipt-bound capture/trace seal."""
    return _seal_trace_capture(
        capture_dir=capture_dir,
        capture_receipt=capture_receipt,
        trace_root=trace_root,
        inventory_receipt=inventory_receipt,
        trace_receipt_sha256=trace_receipt_sha256,
        output_dir=output_dir,
        resume=resume,
        seal_receipt=seal_receipt,
    )


def _verify_core(output_dir, seal_receipt, capture_dir, capture_receipt):
    output = _safe_root(output_dir, "seal-output")
    capture_root = _safe_root(capture_dir, "capture-root")
    _require(
        isinstance(seal_receipt, str)
        and len(seal_receipt) == 64
        and all(char in _HEX for char in seal_receipt),
        "seal-receipt-invalid",
    )
    encoded = _read_control(output)
    _require(
        hashlib.sha256(encoded).hexdigest() == seal_receipt, "seal-receipt-mismatch"
    )
    manifest = _json(encoded, SEAL_NAME)
    required = {
        "kind",
        "schema_version",
        "status",
        "evidence_class",
        "formal_ready",
        "capture",
        "trace",
        "observation",
        "observation_sha256",
        "limitations",
    }
    _require(
        isinstance(manifest, dict) and set(manifest) == required, "seal-schema-invalid"
    )
    _require(
        manifest["kind"] == "Stage2TraceCaptureSeal"
        and manifest["schema_version"] == "1.0.0"
        and manifest["status"] == "complete"
        and manifest["evidence_class"] == "receipt-bound-content-link"
        and manifest["formal_ready"] is False,
        "seal-schema-invalid",
    )
    capture = manifest["capture"]
    trace = manifest["trace"]
    _require(
        isinstance(capture, dict)
        and set(capture)
        == {
            "record_sha256_receipt",
            "capture_mode",
            "capture_evidence_class",
            "injected_test_capture",
            "root_thread_id",
            "requested_model",
        },
        "seal-capture-binding-invalid",
    )
    _require(
        type(capture.get("injected_test_capture")) is bool
        and capture["injected_test_capture"]
        == (capture.get("capture_mode") == "injected-test-adapter"),
        "injected-capture-flag-mismatch",
    )
    _require(
        capture.get("record_sha256_receipt") == capture_receipt,
        "capture-receipt-mismatch",
    )
    _require(
        isinstance(trace, dict)
        and set(trace) == {"inventory", "receipt_sha256"}
        and isinstance(trace.get("inventory"), dict),
        "seal-trace-binding-invalid",
    )
    _validate_trace_names(trace["inventory"])
    raw = _load_inventory(output / "trace", trace["inventory"], trace["receipt_sha256"])
    record, _ = verify_capture(
        capture_root,
        capture_receipt,
        allow_injected_test_capture=capture.get("injected_test_capture") is True,
    )
    stable = record["stable_request_binding"]
    _separate(output, capture_root, stable["workspace"], stable["codex_home"])
    _require(
        capture.get("capture_mode") == record.get("capture_mode")
        and capture.get("capture_evidence_class") == record.get("evidence_class"),
        "capture-mode-mismatch",
    )
    _require(
        capture["injected_test_capture"]
        == (record.get("capture_mode") == "injected-test-adapter"),
        "injected-capture-flag-mismatch",
    )
    observation = inspect_native_trace(
        output / "trace", trace["inventory"], trace["receipt_sha256"]
    )
    _require(
        canonical_hash(manifest["observation"])
        == canonical_hash(observation)
        == manifest["observation_sha256"],
        "seal-observation-mismatch",
    )
    model = _bind(record, observation, raw)
    _require(
        capture.get("root_thread_id") == observation["root_thread_id"]
        and capture.get("requested_model") == model,
        "seal-capture-binding-mismatch",
    )
    return manifest, record


def verify_trace_capture(output_dir, seal_receipt, capture_dir, capture_receipt):
    """Replay every sealed byte and current capture binding without execution."""
    manifest, _ = _verify_core(output_dir, seal_receipt, capture_dir, capture_receipt)
    return manifest
