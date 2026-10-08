"""Private, read-only inventory projection for one observed native execution."""

import hashlib
import json
import os
from pathlib import Path
import stat

from stage2_common import canonical_hash

from . import observation, trace_capture, trace_observation, trace_producer
from .native import CaptureError
from .producer_replay import (
    verify_historical_producer_inventory,
    verify_producer_inventory,
)
from .trace_files import _json, _load_inventory
from .trace_parsing import _tools
from .trace_seal_io import SealDirectory


def _read_bound_json(path, expected_sha256, label):
    """Read one already-receipted private artifact without following redirects."""
    path = Path(path)
    limit = observation.MAX_RPC_STREAM_BYTES
    try:
        with SealDirectory(path.parent) as directory:
            status = directory.status(path.name)
            if not stat.S_ISREG(status.st_mode) or status.st_size > limit:
                raise CaptureError(f"{label} is not a bounded regular file")
            with directory.reader(path.name) as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or (
                    status.st_dev,
                    status.st_ino,
                    status.st_size,
                ) != (before.st_dev, before.st_ino, before.st_size):
                    raise CaptureError(f"{label} identity changed before reading")
                raw = stream.read(limit + 1)
                after = os.fstat(stream.fileno())
    except OSError as error:
        raise CaptureError(f"{label} could not be read") from error
    if (
        (before.st_dev, before.st_ino, before.st_size)
        != (after.st_dev, after.st_ino, after.st_size)
        or len(raw) > limit
        or hashlib.sha256(raw).hexdigest() != expected_sha256
    ):
        raise CaptureError(f"{label} bytes differ from the verified receipt")
    try:
        return json.loads(raw), hashlib.sha256(raw).hexdigest()
    except (UnicodeDecodeError, ValueError, TypeError) as error:
        raise CaptureError(f"{label} is malformed") from error


def _request_inventory(observed, raw):
    """Project exact model inputs and per-call tools from authenticated payload bytes."""
    prior_tools, rows = {}, []
    for item in observed["inferences"]:
        source_ref = item["request_ref"]
        request = _json(raw[source_ref], source_ref)
        source_sha = hashlib.sha256(raw[source_ref]).hexdigest()
        if source_sha != item["request_sha256"]:
            raise CaptureError(
                "inference request source differs from trace observation"
            )
        definitions = _tools(request)
        inherited_from = None
        if definitions is None and item["tools_inherited"]:
            previous = request.get("previous_response_id")
            prior = prior_tools.get(previous)
            if prior is not None and prior["thread_id"] == item["thread_id"]:
                definitions = prior["definitions"]
                inherited_from = previous
        response_id = None
        if item["response_ref"] is not None:
            response = _json(raw[item["response_ref"]], item["response_ref"])
            if (
                hashlib.sha256(raw[item["response_ref"]]).hexdigest()
                != item["response_sha256"]
            ):
                raise CaptureError(
                    "inference response source differs from trace observation"
                )
            response_id = response.get("response_id")
            if isinstance(response_id, str) and definitions is not None:
                prior_tools[response_id] = {
                    "thread_id": item["thread_id"],
                    "definitions": definitions,
                }
        inputs = request.get("input")
        developer_inputs = (
            [value for value in inputs if value.get("role") == "developer"]
            if isinstance(inputs, list)
            and all(isinstance(value, dict) for value in inputs)
            else None
        )
        rows.append(
            {
                "inference_call_id": item["inference_call_id"],
                "thread_id": item["thread_id"],
                "status": item["status"],
                "request_source": {"ref": source_ref, "sha256": source_sha},
                "model": request.get("model"),
                "instructions": request.get("instructions"),
                "reasoning": request.get("reasoning"),
                "developer_inputs": developer_inputs,
                "offered_tools": None
                if definitions is None
                else {
                    "definitions": definitions,
                    "sha256": canonical_hash(definitions),
                    "inherited_from_response_id": inherited_from,
                },
                "token_usage": item["token_usage"],
            }
        )
    return rows


def _metadata_inventory(root, runtime_record):
    rpc_path = root / "bundle" / "inventory" / "rpc.json"
    rows, source_sha = _read_bound_json(
        rpc_path, runtime_record["artifacts"]["rpc.json"], "execution inventory RPC"
    )
    if not isinstance(rows, list):
        raise CaptureError("execution inventory RPC rows are malformed")
    inventories = []
    for row in rows:
        reply = row["response"]
        inventories.append(
            {
                "method": row["method"],
                "status": row["status"],
                "result": reply.get("result"),
                "error": reply["error"]
                if "error" in reply
                else reply.get("host_error"),
                "source": {
                    "ref": "bundle/inventory/rpc.json",
                    "sha256": source_sha,
                },
            }
        )
    return inventories


def inspect_execution_inventory(telemetry_root, producer_receipt, *, capture_request):
    """Authenticate and inventory an existing producer archive without dispatch or writes."""
    return _inspect_execution_inventory(
        telemetry_root,
        producer_receipt,
        capture_request=capture_request,
        workspace_mode="current",
    )


def inspect_historical_execution_inventory(
    telemetry_root, producer_receipt, *, capture_request
):
    """Read authenticated completed actions without authorizing their resumption."""
    return _inspect_execution_inventory(
        telemetry_root,
        producer_receipt,
        capture_request=capture_request,
        workspace_mode="archived",
    )


def _inspect_execution_inventory(
    telemetry_root, producer_receipt, *, capture_request, workspace_mode
):
    verifier = (
        verify_producer_inventory
        if workspace_mode == "current"
        else verify_historical_producer_inventory
    )
    base = verifier(telemetry_root, producer_receipt, capture_request=capture_request)
    root = trace_capture._absolute(telemetry_root)
    mode = {} if workspace_mode == "current" else {"workspace_mode": "archived"}
    record = trace_producer._verify(
        capture_request, root, producer_receipt, allow_synthetic=False, **mode
    )
    trace = record["trace"]
    observed = trace_observation.inspect_native_trace(
        root / trace["root"], trace["inventory"], trace["receipt_sha256"]
    )
    runtime = observation.verify_runtime_observation(
        root / "bundle" / "inventory", record["runtime_observation_receipt"]
    )
    raw = _load_inventory(
        root / trace["root"], trace["inventory"], trace["receipt_sha256"]
    )
    requests = _request_inventory(observed, raw)
    metadata = _metadata_inventory(root, runtime)
    tool_context_complete = all(row["offered_tools"] is not None for row in requests)
    structural_blockers = [
        blocker
        for blocker in observed["blockers"]
        if not blocker.startswith("token-usage-unknown:")
    ]
    rpc_complete = runtime["status"] == "observed" and all(
        item["status"] == "observed" for item in metadata
    )
    coverage_complete = bool(
        requests
        and tool_context_complete
        and not structural_blockers
        and base["call_accounting_complete"]
        and base["token_usage_complete"]
        and rpc_complete
    )
    return {
        "kind": "Stage2ExecutionInventory",
        "schema_version": "1.0.0" if workspace_mode == "current" else "1.1.0",
        "evidence_class": base["evidence_class"],
        "formal_ready": False,
        "coverage_complete": coverage_complete,
        "producer_receipt": producer_receipt,
        "capture": base["capture"],
        "settings_runtime_binding": runtime["binding"],
        "supported_metadata_inventory": metadata,
        "inferences": requests,
        "threads": observed["threads"],
        "child_lineage": observed["thread_edges"],
        "counts": observed["counts"],
        "call_accounting_complete": base["call_accounting_complete"],
        "token_usage_complete": base["token_usage_complete"],
        "token_usage_totals": observed["token_usage_totals"],
        "cost": {"amount": None, "currency": None, "state": "unknown"},
        "blockers": observed["blockers"],
        "privacy": "private-local-report; captured content must not enter public artifacts",
        "resume_action": "verified-replay-no-execution"
        if workspace_mode == "current"
        else "verified-history-no-execution",
        "limitations": [
            "inventory replay is non-formal and makes no admission or readiness claim",
            "metadata RPC results are observations, not effective instructions",
            "unknown tokens block complete coverage; unavailable costs remain null",
        ],
    }
