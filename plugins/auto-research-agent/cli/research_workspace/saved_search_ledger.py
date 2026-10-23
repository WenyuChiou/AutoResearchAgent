"""Recover pinned batch context without inventing per-work discovery events."""

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from stage1_deliverable.common import DeliverableError

CONTRACT = "S1-SAVED-SEARCH-LEDGER-1.0.0"
SCHEMA = Path(__file__).with_name("SavedSearchLedger.v1.schema.json")


def _require(condition, message):
    if not condition:
        raise DeliverableError("saved-search-ledger: " + message)


def _proof(reference):
    return {key: reference[key] for key in ("path", "pointer", "source_sha256")}


def _time(value):
    if value is None:
        return None
    _require(isinstance(value, str), "invalid batch timestamp")
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        _require(moment.tzinfo is not None, "batch timestamp timezone required")
    except ValueError as error:
        raise DeliverableError(
            "saved-search-ledger: invalid batch timestamp"
        ) from error
    return moment


def project_saved_search_ledger(spec, resolve, index, data, observations):
    """Replay declared ledger, snapshot and receipt bytes already pinned by recovery.

    Snapshot binding proves which saved resources were supplied, not independent
    acceptance. A batch's query arguments never establish which query returned a
    particular work, its first discovery, a research round or backend attempts.
    """
    try:
        Draft202012Validator(json.loads(SCHEMA.read_bytes())).validate(spec)
    except ValidationError as error:
        raise DeliverableError(
            "saved-search-ledger: attachment contract invalid"
        ) from error
    ledger_ref, snapshot_ref = resolve(spec["ledger"]), resolve(spec["snapshot"])
    ledger, snapshot = ledger_ref["value"], snapshot_ref["value"]
    _require(type(ledger) is dict and type(snapshot) is dict, "object sources required")
    _require(
        ledger.get("project_id") == snapshot.get("project_id") == index["project_id"]
        and ledger.get("input_version")
        == snapshot.get("input_version")
        == spec["input_version"],
        "project/input binding differs",
    )
    _require(
        snapshot.get("kind") == "SavedSourceCandidateSnapshot"
        and snapshot.get("schema_version") == "1.0.0",
        "unsupported snapshot",
    )
    bindings = snapshot.get("bindings", {})
    _require(type(bindings) is dict, "snapshot bindings required")
    resource, deliverable = (
        bindings.get("resources", {}),
        bindings.get("deliverable", {}),
    )
    _require(
        type(resource) is dict and type(deliverable) is dict,
        "snapshot bindings invalid",
    )
    _require(
        resource.get("sha256") == ledger_ref["source_sha256"]
        and type(resource.get("bytes")) is int
        and resource["bytes"] == len(data[ledger_ref["path"]])
        and isinstance(resource.get("path"), str)
        and bool(resource["path"]),
        "snapshot resource bytes differ",
    )
    _require(
        deliverable.get("sha256") == index["provenance"]["deliverable_manifest_sha256"],
        "snapshot deliverable binding differs",
    )
    reservations = ledger.get("search_reservations")
    _require(
        type(reservations) is list and 0 < len(reservations) <= 512, "reservation bound"
    )
    batches, seen, seen_receipts, seen_sources = [], set(), set(), set()
    for number, row in enumerate(reservations):
        _require(type(row) is dict, "reservation object required")
        batch = row.get("id")
        _require(
            isinstance(batch, str) and batch and batch not in seen,
            "duplicate/invalid batch",
        )
        seen.add(batch)
        entry = spec["receipts"].get(batch)
        _require(entry is not None, "unmapped receipt")
        receipt_ref = resolve(entry["receipt"])
        receipt_path = row.get("receipt")
        _require(
            isinstance(receipt_path, str)
            and receipt_path
            and receipt_path not in seen_receipts
            and receipt_ref["path"] not in seen_sources
            and row.get("receipt_sha256") == receipt_ref["source_sha256"],
            "receipt binding differs",
        )
        seen_receipts.add(receipt_path)
        seen_sources.add(receipt_ref["path"])
        _require(
            type(row.get("queries")) is int and 0 <= row["queries"] <= 10000,
            "query reservation count invalid",
        )
        moments = {
            key: _time(row.get(key))
            for key in ("reserved_at", "started_at", "receipt_persisted_at")
        }
        completion = row.get("tool_completion_time")
        completion_moment = (
            None if completion == "not-separately-captured" else _time(completion)
        )
        ordered = [
            moments["reserved_at"],
            moments["started_at"],
            completion_moment,
            moments["receipt_persisted_at"],
        ]
        known = [moment for moment in ordered if moment is not None]
        _require(known == sorted(known), "batch timestamp order differs")
        planned = row.get("planned_query_ids")
        _require(
            planned is None
            or (
                type(planned) is list
                and len(planned) == row["queries"]
                and all(isinstance(item, str) and item for item in planned)
            ),
            "planned query IDs differ",
        )
        query_ref, parameters = None, None
        if "query_parameters" in entry:
            query_ref = resolve(entry["query_parameters"])
            from_ledger = (
                query_ref["path"] == ledger_ref["path"]
                and query_ref["pointer"] == f"/search_reservations/{number}/query_texts"
            )
            from_receipt = query_ref["path"] == receipt_ref["path"] and query_ref[
                "pointer"
            ] in {"/query", "/queries", "/query_texts"}
            _require(from_ledger or from_receipt, "query source is outside this batch")
            parameters = query_ref["value"]
            _require(
                type(parameters) is list and len(parameters) == row["queries"],
                "query parameter count differs",
            )
            _require(
                all(
                    isinstance(item, str)
                    and item.strip()
                    or type(item) is dict
                    and any(
                        isinstance(item.get(key), str) and item[key].strip()
                        for key in ("q", "query")
                    )
                    for item in parameters
                ),
                "query parameter shape invalid",
            )
        receipt_value = receipt_ref["value"]
        receipt_started = (
            receipt_value.get("started_at") if type(receipt_value) is dict else None
        )
        _time(receipt_started)
        batches.append(
            dict(
                batch_ref=batch,
                ledger_pointer=f"/search_reservations/{number}",
                ledger_source=_proof(ledger_ref),
                receipt=dict(
                    **_proof(receipt_ref),
                    bytes=len(data[receipt_ref["path"]]),
                    original_path=receipt_path,
                ),
                status=row.get("status"),
                reserved_at=row.get("reserved_at"),
                started_at=row.get("started_at"),
                receipt_persisted_at=row.get("receipt_persisted_at"),
                tool_completion_time=completion,
                receipt_started_at=receipt_started,
                receipt_started_at_scope="saved-receipt-wrapper-time-not-substituted-for-ledger-start",
                time_scope="batch-reservation-start-and-persistence-not-work-discovery",
                reserved_query_count=row["queries"],
                planned_query_ids=deepcopy(planned),
                query_parameters=deepcopy(parameters),
                query_parameters_source=_proof(query_ref) if query_ref else None,
                query_scope="batch-parameters-without-query-to-work-or-backend-attribution",
            )
        )
    _require(set(spec["receipts"]) == seen, "extra/unmapped receipt")
    by_batch = {batch["batch_ref"]: batch for batch in batches}
    for observation in observations:
        batch = by_batch.get(observation.get("batch_ref"))
        _require(batch is not None, "observation batch has no mapped receipt")
        receipt = observation.get("saved_receipt_ref", {})
        _require(
            type(receipt) is dict
            and receipt.get("sha256") == batch["receipt"]["source_sha256"],
            "observation receipt differs",
        )
        if "bytes" in receipt:
            _require(
                type(receipt["bytes"]) is int
                and receipt["bytes"] == batch["receipt"]["bytes"],
                "observation receipt length differs",
            )
    return dict(
        contract_version=CONTRACT,
        project_id=index["project_id"],
        input_version=spec["input_version"],
        ledger_source=_proof(ledger_ref),
        snapshot_source=_proof(snapshot_ref),
        batches=batches,
        scope="saved-batch-context-only",
        independent_acceptance=False,
        scientific_assessment=False,
        historical_discovery_events_reconstructed=False,
    )
