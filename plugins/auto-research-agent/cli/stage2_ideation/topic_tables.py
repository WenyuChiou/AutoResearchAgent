"""Source-bound validation for Stage 2 topic comparison tables.

This module validates structure and provenance bindings only.  It never calls a
model and does not decide whether a paper supports a scientific interpretation.
"""

import copy
from datetime import datetime, timezone
import hashlib
import math
import re

from stage2_common import Stage2Error, canonical_hash


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_KNOWN_CELL_STATUSES = {"present", "absent", "partial", "described"}
_RESOURCE_EVIDENCE_STATUSES = {"available", "restricted", "unavailable"}


class TopicTableError(Stage2Error):
    """A research table is malformed or is not bound to its packet."""


def _require(condition, message):
    if not condition:
        raise TopicTableError(message)


def _text(value, label, *, nullable=False):
    if nullable and value is None:
        return
    _require(isinstance(value, str) and value.strip(), f"{label} must be nonempty text")


def _sha(value, label):
    _require(
        isinstance(value, str) and _SHA256.fullmatch(value),
        f"{label} must be a lowercase SHA-256",
    )


def _span(span, raw_proposal, label):
    _require(
        isinstance(span, dict) and set(span) == {"start", "end", "quote"},
        f"{label} span has unexpected fields",
    )
    start, end = span["start"], span["end"]
    _require(
        isinstance(start, int)
        and not isinstance(start, bool)
        and isinstance(end, int)
        and not isinstance(end, bool)
        and 0 <= start < end <= len(raw_proposal),
        f"{label} span offsets are invalid",
    )
    _text(span["quote"], f"{label} span quote")
    _require(
        raw_proposal[start:end] == span["quote"],
        f"{label} span quote does not match raw proposal offsets",
    )


def _spans(spans, raw_proposal, label):
    _require(isinstance(spans, list) and spans, f"{label} requires proposal spans")
    for span in spans:
        _span(span, raw_proposal, label)


def _evidence_ids(value, evidence_by_id, label):
    _require(isinstance(value, list), f"{label} evidence_ids must be an array")
    _require(len(value) == len(set(value)), f"duplicate {label} evidence reference")
    for evidence_id in value:
        _text(evidence_id, f"{label} evidence_id")
        _require(evidence_id in evidence_by_id, f"{label} references unknown evidence")


def _validate_cell_format(row, value_kind):
    status = row["status"]
    _require(
        status
        in {
            "present",
            "absent",
            "partial",
            "described",
            "unknown",
            "not-applicable",
        },
        "invalid cell status",
    )
    if value_kind == "feature":
        _require(status != "described", "feature cells cannot use described")
        if status == "present":
            _require(
                row["value"] is None or row["value"] is True,
                "present feature value must be true or null",
            )
        if status == "absent":
            _require(
                row["value"] is None or row["value"] is False,
                "absent feature value must be false or null",
            )
    else:
        _require(
            status not in {"present", "absent"},
            "text and quantity cells cannot use present or absent",
        )
    if status in {"unknown", "not-applicable"}:
        _require(row["value"] is None, f"{status} cell value must be null")
    if status == "unknown":
        _require(row["negative_basis"] is None, "unknown cannot claim a negative basis")
    _require(
        row["negative_basis"]
        in {None, "explicit-statement", "bounded-design-inspection"},
        "invalid negative_basis",
    )
    if status != "absent":
        _require(
            row["negative_basis"] is None,
            "negative_basis is allowed only for absent",
        )
    else:
        _require(
            row["negative_basis"]
            in {"explicit-statement", "bounded-design-inspection"},
            "absent requires negative_basis",
        )
    if status in _KNOWN_CELL_STATUSES and value_kind in {"text", "quantity"}:
        _require(
            row["value"] is not None,
            "described or partial text/quantity cell requires a value",
        )
        if value_kind == "text":
            _text(row["value"], "text cell value")
        if value_kind == "quantity":
            _require(
                isinstance(row["value"], (int, float))
                and not isinstance(row["value"], bool)
                and math.isfinite(row["value"]),
                "quantity cell value must be a finite number",
            )


def _cell_context(index, row):
    return (
        f"cell[{index}] (dimension_id={row.get('dimension_id')!r}, "
        f"work_id={row.get('work_id')!r}, version_id={row.get('version_id')!r})"
    )


def validate_research_tables(research_tables: dict, packet: dict) -> dict:
    """Return a validated copy of tables bound to ``packet``.

    Validation covers shape, exact prose spans, complete work-by-dimension
    coverage, and source/evidence/candidate identities.  It does not certify the
    scientific meaning of a status or value.
    """

    _require(isinstance(research_tables, dict), "research_tables must be an object")
    _require(isinstance(packet, dict), "packet must be an object")
    result = copy.deepcopy(research_tables)
    expected_fields = {
        "kind",
        "schema_version",
        "brief_sha256",
        "input_packet_sha256",
        "input_snapshot_sha256",
        "raw_proposal",
        "raw_proposal_sha256",
        "dimensions",
        "work_refs",
        "cells",
        "direction_resources",
    }
    _require(set(result) == expected_fields, "research_tables has unexpected fields")
    _require(result["kind"] == "Stage2ResearchTables", "research_tables kind mismatch")
    _require(
        result["schema_version"] == "1.0.0", "research_tables schema version mismatch"
    )
    for field in (
        "brief_sha256",
        "input_packet_sha256",
        "input_snapshot_sha256",
        "raw_proposal_sha256",
    ):
        _sha(result[field], field)
    _text(result["raw_proposal"], "raw_proposal")
    raw_proposal = result["raw_proposal"]
    _require(
        hashlib.sha256(raw_proposal.encode("utf-8")).hexdigest()
        == result["raw_proposal_sha256"],
        "raw proposal hash mismatch",
    )
    _require(
        result["brief_sha256"] == canonical_hash(packet.get("brief")),
        "brief hash mismatch",
    )

    sources = packet.get("sources")
    evidence = packet.get("evidence")
    candidates = packet.get("candidates")
    _require(
        isinstance(sources, list)
        and isinstance(evidence, list)
        and isinstance(candidates, list),
        "packet indexes are invalid",
    )
    source_by_id = {
        row.get("source_id"): row for row in sources if isinstance(row, dict)
    }
    evidence_by_id = {
        row.get("evidence_id"): row for row in evidence if isinstance(row, dict)
    }
    candidate_keys = {
        (row.get("candidate_id"), row.get("version"))
        for row in candidates
        if isinstance(row, dict)
    }
    literature_by_key = {
        (row.get("work_id"), row.get("version_id")): row
        for row in [
            *packet.get("literature", []),
            *packet.get("supplemental_literature", []),
        ]
        if isinstance(row, dict)
    }
    if not literature_by_key:
        literature_by_key = {
            (row.get("work_id"), row.get("version_id")): {
                "source_ids": [row.get("source_id")]
            }
            for row in sources
            if isinstance(row, dict)
        }
    literature_keys = set(literature_by_key)

    dimensions = result["dimensions"]
    _require(
        isinstance(dimensions, list) and dimensions,
        "research_tables requires dimensions",
    )
    dimension_by_id = {}
    for row in dimensions:
        _require(
            isinstance(row, dict)
            and set(row)
            == {
                "dimension_id",
                "label",
                "research_need",
                "rationale",
                "definition",
                "value_kind",
                "conditions",
                "spans",
            },
            "invalid research dimension",
        )
        dimension_id = row["dimension_id"]
        _text(dimension_id, "dimension_id")
        _require(dimension_id not in dimension_by_id, "duplicate dimension_id")
        for field in ("label", "research_need", "rationale", "definition"):
            _text(row[field], f"dimension {field}")
        _require(
            row["value_kind"] in {"feature", "text", "quantity"},
            "invalid dimension value_kind",
        )
        _require(
            isinstance(row["conditions"], list), "dimension conditions must be an array"
        )
        for condition in row["conditions"]:
            _text(condition, "dimension condition")
        _spans(row["spans"], raw_proposal, "dimension")
        dimension_by_id[dimension_id] = row

    work_refs = result["work_refs"]
    _require(
        isinstance(work_refs, list) and work_refs, "research_tables requires work_refs"
    )
    work_keys = []
    for row in work_refs:
        _require(
            isinstance(row, dict) and set(row) == {"work_id", "version_id"},
            "invalid work_ref",
        )
        key = (row["work_id"], row["version_id"])
        _require(key in literature_keys, "work_ref does not identify packet literature")
        work_keys.append(key)
    _require(len(work_keys) == len(set(work_keys)), "duplicate work_ref")
    # Source acquisition can temporarily leave a valid previous matrix short of
    # the new versions. The content gate requires full coverage before delivery;
    # keeping the old cells here permits a bound rebuild without losing history.

    cells = result["cells"]
    _require(isinstance(cells, list), "cells must be an array")
    expected_cell_fields = {
        "dimension_id",
        "work_id",
        "version_id",
        "status",
        "value",
        "reason",
        "inspection_scope",
        "negative_basis",
        "evidence_ids",
        "spans",
    }
    cell_format_errors = []
    for index, row in enumerate(cells):
        context = (
            _cell_context(index, row) if isinstance(row, dict) else f"cell[{index}]"
        )
        _require(
            isinstance(row, dict) and set(row) == expected_cell_fields,
            f"{context}: invalid research table cell",
        )
        _require(
            row["dimension_id"] in dimension_by_id,
            f"{context}: cell references unknown dimension",
        )
        try:
            _validate_cell_format(
                row, dimension_by_id[row["dimension_id"]]["value_kind"]
            )
        except TopicTableError as error:
            cell_format_errors.append(f"{context}: {error}")
    if cell_format_errors:
        raise TopicTableError(
            "invalid research table cell formats: " + "; ".join(cell_format_errors)
        )

    seen_cells = set()
    for row in cells:
        key = (row["work_id"], row["version_id"])
        cell_key = (row["dimension_id"], *key)
        _require(key in set(work_keys), "cell references undeclared work version")
        _require(cell_key not in seen_cells, "duplicate work-dimension cell")
        seen_cells.add(cell_key)
        status = row["status"]
        if status == "unknown":
            _text(row["reason"], "unknown reason and next lookup")
        if status == "not-applicable":
            _text(row["reason"], "not-applicable reason")
        _text(row["reason"], "cell reason", nullable=True)
        _text(row["inspection_scope"], "inspection_scope", nullable=True)
        _evidence_ids(row["evidence_ids"], evidence_by_id, "cell")
        _spans(row["spans"], raw_proposal, "cell")

        if status in _KNOWN_CELL_STATUSES:
            _require(row["evidence_ids"], "known cell status requires evidence")
            _text(row["reason"], "known cell reason")
            _text(row["inspection_scope"], "known cell inspection_scope")
            allowed_source_ids = set(literature_by_key[key].get("source_ids", []))
            for evidence_id in row["evidence_ids"]:
                evidence_row = evidence_by_id[evidence_id]
                _require(
                    (evidence_row.get("work_id"), evidence_row.get("version_id"))
                    == key,
                    "cell evidence belongs to another work version",
                )
                source = source_by_id.get(evidence_row.get("source_id"))
                _require(source is not None, "cell evidence references unknown source")
                _require(
                    source.get("source_id") in allowed_source_ids,
                    "cell evidence source is not referenced by its literature row",
                )
                _require(
                    (source.get("work_id"), source.get("version_id")) == key,
                    "cell evidence source belongs to another work version",
                )
                _require(
                    source.get("evidence_level") != "metadata",
                    "known cell status requires non-metadata evidence: "
                    f"dimension={row['dimension_id']}, work={key[0]}, "
                    f"version={key[1]}, evidence={evidence_id}, "
                    f"source={source.get('source_id')}, status={status}; "
                    "use unknown with null value and a next lookup when "
                    "the source does not establish the answer",
                )
        if status == "absent":
            _text(row["inspection_scope"], "absent inspection_scope")
            if row["negative_basis"] == "bounded-design-inspection":
                _require(
                    all(
                        source_by_id[evidence_by_id[eid]["source_id"]].get(
                            "evidence_level"
                        )
                        == "full-text"
                        for eid in row["evidence_ids"]
                    ),
                    "bounded-design-inspection requires full-text evidence",
                )

    expected_cells = {
        (dimension_id, work_id, version_id)
        for dimension_id in dimension_by_id
        for work_id, version_id in work_keys
    }
    _require(
        seen_cells == expected_cells,
        "cells must cover every declared work-dimension pair exactly once",
    )

    resources = result["direction_resources"]
    _require(isinstance(resources, list), "direction_resources must be an array")
    resource_ids = []
    for row in resources:
        _require(
            isinstance(row, dict)
            and set(row)
            == {
                "resource_id",
                "candidate_id",
                "candidate_version",
                "category",
                "name",
                "purpose",
                "url",
                "version",
                "required",
                "status",
                "access_conditions",
                "license",
                "cost_basis",
                "limitations",
                "alternatives",
                "evidence_ids",
                "checked_at",
                "spans",
            },
            "invalid direction resource",
        )
        resource_ids.append(row["resource_id"])
        _text(row["resource_id"], "resource_id")
        _require(
            (row["candidate_id"], row["candidate_version"]) in candidate_keys,
            "resource references unknown candidate version",
        )
        _require(
            row["category"] in {"dataset", "report", "reference", "model", "tool"},
            "invalid resource category",
        )
        for field in ("name", "purpose"):
            _text(row[field], f"resource {field}")
        for field in (
            "url",
            "version",
            "access_conditions",
            "license",
            "cost_basis",
            "checked_at",
        ):
            _text(row[field], f"resource {field}", nullable=True)
        _require(isinstance(row["required"], bool), "resource required must be boolean")
        _require(
            isinstance(row["candidate_version"], int)
            and not isinstance(row["candidate_version"], bool)
            and row["candidate_version"] > 0,
            "resource candidate_version must be a positive integer",
        )
        _require(
            row["status"]
            in {"available", "restricted", "unavailable", "unknown", "not-applicable"},
            "invalid resource status",
        )
        for field in ("limitations", "alternatives"):
            _require(isinstance(row[field], list), f"resource {field} must be an array")
            for value in row[field]:
                _text(value, f"resource {field}")
        if row["status"] == "not-applicable":
            _require(
                row["limitations"],
                "not-applicable resource requires a limitation reason",
            )
        _evidence_ids(row["evidence_ids"], evidence_by_id, "resource")
        if row["status"] in _RESOURCE_EVIDENCE_STATUSES:
            _require(
                row["evidence_ids"],
                "non-unknown resource access status requires evidence",
            )
            for evidence_id in row["evidence_ids"]:
                evidence_row = evidence_by_id[evidence_id]
                source = source_by_id.get(evidence_row.get("source_id"))
                _require(
                    source is not None, "resource evidence references unknown source"
                )
                _require(
                    source.get("evidence_level") != "metadata",
                    "resource access status requires non-metadata evidence",
                )
            _text(row["checked_at"], "known resource checked_at")
            try:
                checked_at = datetime.fromisoformat(
                    row["checked_at"].replace("Z", "+00:00")
                )
            except ValueError as error:
                raise TopicTableError(
                    "known resource checked_at must be ISO-8601 UTC"
                ) from error
            _require(
                checked_at.tzinfo is not None
                and checked_at.utcoffset() == timezone.utc.utcoffset(checked_at),
                "known resource checked_at must be ISO-8601 UTC",
            )
        _spans(row["spans"], raw_proposal, "resource")
    _require(len(resource_ids) == len(set(resource_ids)), "duplicate resource_id")
    return result


def materialize_research_tables(
    extracted_tables, extracted_candidates, packet, raw_proposal, snapshot_sha256
):
    """Add host-owned bindings and resolve extraction-local candidate indexes."""

    if extracted_tables is None:
        return None
    _require(
        isinstance(extracted_tables, dict),
        "extracted research_tables must be an object or null",
    )
    _require(
        isinstance(extracted_candidates, list), "extracted candidates must be an array"
    )
    _require(
        isinstance(raw_proposal, str) and raw_proposal.strip(),
        "raw_proposal must be nonempty text",
    )
    _sha(snapshot_sha256, "snapshot_sha256")
    expected = {"dimensions", "work_refs", "cells", "direction_resources"}
    _require(
        set(extracted_tables) == expected,
        "extracted research_tables has unexpected fields",
    )
    resources = []
    for row in extracted_tables["direction_resources"]:
        _require(
            isinstance(row, dict) and "candidate_index" in row,
            "resource requires candidate_index",
        )
        index = row["candidate_index"]
        _require(
            isinstance(index, int)
            and not isinstance(index, bool)
            and 0 <= index < len(extracted_candidates),
            "resource candidate_index is out of range",
        )
        candidate = extracted_candidates[index].get("candidate")
        _require(
            isinstance(candidate, dict),
            "resource candidate_index has no assigned identity",
        )
        materialized = copy.deepcopy(row)
        materialized.pop("candidate_index")
        materialized["candidate_id"] = candidate.get("candidate_id")
        materialized["candidate_version"] = candidate.get("version")
        resources.append(materialized)
    tables = {
        "kind": "Stage2ResearchTables",
        "schema_version": "1.0.0",
        "brief_sha256": canonical_hash(packet.get("brief")),
        "input_packet_sha256": canonical_hash(packet),
        "input_snapshot_sha256": snapshot_sha256,
        "raw_proposal": raw_proposal,
        "raw_proposal_sha256": hashlib.sha256(raw_proposal.encode("utf-8")).hexdigest(),
        "dimensions": copy.deepcopy(extracted_tables["dimensions"]),
        "work_refs": copy.deepcopy(extracted_tables["work_refs"]),
        "cells": copy.deepcopy(extracted_tables["cells"]),
        "direction_resources": resources,
    }
    validation_packet = copy.deepcopy(packet)
    validation_packet["candidates"] = [
        *packet.get("candidates", []),
        *(row["candidate"] for row in extracted_candidates),
    ]
    return validate_research_tables(tables, validation_packet)
