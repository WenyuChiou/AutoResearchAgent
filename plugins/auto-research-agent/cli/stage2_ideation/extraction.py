"""Fail-closed validation for tool-free Stage 2 proposal extraction."""

import copy
import hashlib
import re

from jsonschema import Draft202012Validator

from stage2_common import canonical_hash

from .schema import SCHEMA_VERSION, SCHEMA_VERSION_1_1, extraction_schema
from .topic_tables import TopicTableError, materialize_research_tables

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class IdeationError(ValueError):
    """An ideation extraction cannot be bound to its proposal and packet."""


def _require(condition, message):
    if not condition:
        raise IdeationError(message)


def _text(value, label, *, nullable=False):
    if nullable and value is None:
        return
    _require(isinstance(value, str) and value.strip(), f"{label} must be nonempty text")


def _text_list(value, label):
    _require(isinstance(value, list), f"{label} must be an array")
    for item in value:
        _text(item, label)


def _unique(values, label):
    _require(len(values) == len(set(values)), f"duplicate {label}")


def _span(span, raw_proposal, label):
    _require(
        isinstance(span, dict) and set(span) == {"start", "end", "quote"},
        f"{label} span has unexpected fields",
    )
    start, end, quote = span["start"], span["end"], span["quote"]
    _require(
        isinstance(start, int)
        and not isinstance(start, bool)
        and isinstance(end, int)
        and not isinstance(end, bool)
        and 0 <= start < end <= len(raw_proposal),
        f"{label} span offsets are invalid",
    )
    _text(quote, f"{label} span quote")
    _require(
        raw_proposal[start:end] == quote,
        f"{label} span quote does not match raw proposal offsets",
    )


def _spans(value, raw_proposal, label):
    _require(isinstance(value, list) and value, f"{label} requires proposal spans")
    for span in value:
        _span(span, raw_proposal, label)


def _evidence_ids(value, known, label):
    _require(isinstance(value, list), f"{label} evidence_ids must be an array")
    _text_list(value, f"{label} evidence_id")
    _unique(value, f"{label} evidence reference")
    _require(set(value).issubset(known), f"{label} references unknown evidence")


def _source_ref(row, source_by_id, label):
    _require(isinstance(row, dict), f"{label} must be an object")
    source_id = row.get("source_id")
    _text(source_id, f"{label} source_id")
    source = source_by_id.get(source_id)
    _require(source is not None, f"{label} references unknown source")
    _require(row.get("work_id") == source.get("work_id"), f"{label} work_id mismatch")
    _require(
        row.get("version_id") == source.get("version_id"),
        f"{label} version_id mismatch",
    )
    return source


def _evidence_matches_source(evidence_ids, evidence_by_id, source, label):
    for evidence_id in evidence_ids:
        evidence = evidence_by_id[evidence_id]
        _require(
            evidence.get("source_id") == source.get("source_id")
            and evidence.get("work_id") == source.get("work_id")
            and evidence.get("version_id") == source.get("version_id"),
            f"{label} evidence belongs to another source version",
        )


def _expected_input_hash(raw_sha256, packet, snapshot_sha256, schema_version):
    return canonical_hash(
        {
            "kind": "Stage2IdeationExtractionTask",
            "schema_version": schema_version,
            "snapshot_sha256": snapshot_sha256,
            "packet_sha256": canonical_hash(packet),
            "raw_proposal_sha256": raw_sha256,
        }
    )


def _schema_validate(extraction, schema_version):
    errors = sorted(
        Draft202012Validator(extraction_schema(schema_version)).iter_errors(extraction),
        key=str,
    )
    if errors:
        first = errors[0]
        where = "/".join(map(str, first.absolute_path)) or "$"
        raise IdeationError(f"extraction schema {where}: {first.message}")


def _validate_candidate_lineage(packet, extracted_candidates):
    histories = {}
    for candidate in packet.get("candidates", []):
        histories.setdefault(candidate["candidate_id"], []).append(candidate)
    for row in extracted_candidates:
        candidate = row["candidate"]
        histories.setdefault(candidate["candidate_id"], []).append(candidate)
    for candidate_id, rows in histories.items():
        ordered = sorted(rows, key=lambda row: row["version"])
        versions = [row["version"] for row in ordered]
        _require(
            versions == list(range(1, len(ordered) + 1)),
            f"non-contiguous candidate history: {candidate_id}",
        )
        for index, row in enumerate(ordered):
            expected_parent = None if index == 0 else index
            _require(
                row["parent_version"] == expected_parent,
                f"wrong candidate parent version: {candidate_id} v{row['version']}",
            )


def validate_extraction(
    raw_proposal: str,
    extraction: dict,
    packet: dict,
    snapshot_sha256: str,
    *,
    completeness_record=None,
    expected_completeness_sha256=None,
) -> dict:
    """Validate extraction bindings and return an order-preserving deep copy.

    ``packet`` must already have passed ``stage2_common.validate_packet``; this
    focused validator does not reopen source snapshots or independently verify
    the declared no-tool policy.
    """

    _require(isinstance(raw_proposal, str), "raw_proposal must be text")
    _require(isinstance(packet, dict), "packet must be an object")
    _require(
        isinstance(snapshot_sha256, str) and _SHA256.fullmatch(snapshot_sha256),
        "snapshot_sha256 must be a lowercase SHA-256",
    )
    _require(isinstance(extraction, dict), "extraction must be an object")
    result = copy.deepcopy(extraction)
    schema_version = result.get("schema_version")
    _require(
        schema_version in {SCHEMA_VERSION, SCHEMA_VERSION_1_1},
        "unsupported extraction schema version",
    )
    expected_version = (
        SCHEMA_VERSION_1_1
        if packet.get("schema_version") == "2.2.0"
        else SCHEMA_VERSION
    )
    _require(
        schema_version == expected_version,
        "extraction schema version does not match packet",
    )
    _schema_validate(result, schema_version)
    _require(result["snapshot_sha256"] == snapshot_sha256, "snapshot hash mismatch")
    packet_sha256 = canonical_hash(packet)
    _require(result["packet_sha256"] == packet_sha256, "packet hash mismatch")
    raw_sha256 = hashlib.sha256(raw_proposal.encode("utf-8")).hexdigest()
    _require(result["raw_proposal_sha256"] == raw_sha256, "raw proposal hash mismatch")
    expected_input = _expected_input_hash(
        raw_sha256, packet, snapshot_sha256, schema_version
    )
    _require(result["input_hash"] == expected_input, "extraction input hash mismatch")

    sources = packet.get("sources", [])
    evidence = packet.get("evidence", [])
    _require(
        isinstance(sources, list) and isinstance(evidence, list),
        "invalid packet indexes",
    )
    source_by_id = {
        row.get("source_id"): row for row in sources if isinstance(row, dict)
    }
    evidence_by_id = {
        row.get("evidence_id"): row for row in evidence if isinstance(row, dict)
    }
    known_evidence = set(evidence_by_id)

    bibliography = result["bibliography"]
    _require(isinstance(bibliography, list), "bibliography must be an array")
    bibliography_ids = []
    for row in bibliography:
        expected = {
            "source_id",
            "work_id",
            "version_id",
            "title",
            "authors",
            "year",
            "identifier",
            "roles",
        }
        _require(
            isinstance(row, dict) and set(row) == expected, "invalid bibliography row"
        )
        _source_ref(row, source_by_id, "bibliography")
        bibliography_ids.append(row["source_id"])
        for key in ("title", "authors", "year", "identifier"):
            _text(row[key], f"bibliography {key}", nullable=True)
        _text_list(row["roles"], "bibliography role")
    _unique(bibliography_ids, "bibliography source")

    comparison_rows = result["comparison_rows"]
    _require(isinstance(comparison_rows, list), "comparison_rows must be an array")
    for row in comparison_rows:
        expected = {
            "dimension",
            "finding",
            "comparability",
            "noncomparability",
            "source_roles",
            "shared_relationships",
            "evidence_ids",
            "spans",
        }
        _require(
            isinstance(row, dict) and set(row) == expected, "invalid comparison row"
        )
        _text(row["dimension"], "comparison dimension")
        _text(row["finding"], "comparison finding")
        _text(row["noncomparability"], "noncomparability", nullable=True)
        if row["comparability"] == "noncomparable":
            _text(row["noncomparability"], "noncomparability")
        _evidence_ids(row["evidence_ids"], known_evidence, "comparison")
        _spans(row["spans"], raw_proposal, "comparison")
        _require(isinstance(row["source_roles"], list), "source_roles must be an array")
        for role in row["source_roles"]:
            _require(
                isinstance(role, dict)
                and set(role)
                == {"source_id", "work_id", "version_id", "role", "evidence_ids"},
                "invalid source role",
            )
            source = _source_ref(role, source_by_id, "source role")
            _text(role["role"], "source role")
            _evidence_ids(role["evidence_ids"], known_evidence, "source role")
            _evidence_matches_source(
                role["evidence_ids"], evidence_by_id, source, "source role"
            )
        _require(
            isinstance(row["shared_relationships"], list),
            "shared_relationships must be an array",
        )
        for relationship in row["shared_relationships"]:
            _require(
                isinstance(relationship, dict)
                and set(relationship)
                == {"relationship", "source_refs", "evidence_ids", "detail"},
                "invalid shared relationship",
            )
            source_refs = relationship["source_refs"]
            source_ids = []
            for ref in source_refs:
                _source_ref(ref, source_by_id, "shared relationship source")
                source_ids.append(ref["source_id"])
            _unique(source_ids, "shared relationship source")
            _evidence_ids(
                relationship["evidence_ids"], known_evidence, "shared relationship"
            )
            _require(
                all(
                    evidence_by_id[evidence_id].get("source_id") in source_ids
                    for evidence_id in relationship["evidence_ids"]
                ),
                "shared relationship evidence belongs to an unlisted source",
            )
            _text(relationship["detail"], "shared relationship detail")

    candidates = result["candidates"]
    _require(isinstance(candidates, list), "candidates must be an array")
    for row in candidates:
        expected = {
            "candidate",
            "route",
            "mechanism",
            "closest_work_refs",
            "strong_alternatives",
            "change_mind_conditions",
            "claim_labels",
            "spans",
        }
        _require(
            isinstance(row, dict) and set(row) == expected, "invalid candidate row"
        )
        candidate = row["candidate"]
        _evidence_ids(candidate["evidence_ids"], known_evidence, "candidate")
        _spans(row["spans"], raw_proposal, "candidate")
        _require(
            isinstance(row["closest_work_refs"], list),
            "closest_work_refs must be an array",
        )
        for ref in row["closest_work_refs"]:
            _require(
                isinstance(ref, dict)
                and set(ref) == {"source_id", "work_id", "version_id", "evidence_ids"},
                "invalid closest-work reference",
            )
            source = _source_ref(ref, source_by_id, "closest-work reference")
            _evidence_ids(ref["evidence_ids"], known_evidence, "closest-work reference")
            _evidence_matches_source(
                ref["evidence_ids"], evidence_by_id, source, "closest-work reference"
            )
        _require(isinstance(row["claim_labels"], list), "claim_labels must be an array")
        _require(row["claim_labels"], "candidate requires claim labels")
        for claim in row["claim_labels"]:
            _require(
                isinstance(claim, dict)
                and set(claim) == {"text", "status", "evidence_ids"},
                "invalid candidate claim label",
            )
            _text(claim["text"], "candidate claim")
            _evidence_ids(claim["evidence_ids"], known_evidence, "candidate claim")
    _validate_candidate_lineage(packet, candidates)
    if schema_version == SCHEMA_VERSION_1_1 and result["research_tables"] is not None:
        try:
            materialize_research_tables(
                result["research_tables"],
                candidates,
                packet,
                raw_proposal,
                snapshot_sha256,
            )
        except TopicTableError as error:
            raise IdeationError(f"research_tables: {error}") from error
    if completeness_record is not None or expected_completeness_sha256 is not None:
        _validate_completeness(
            raw_proposal,
            result,
            packet,
            snapshot_sha256,
            completeness_record,
            expected_completeness_sha256,
        )
    return result


def prepare_completeness_record(
    raw_proposal, extraction, packet, snapshot_sha256, ideas
):
    """Bind only caller-supplied idea spans; this is not semantic discovery."""
    _require(isinstance(ideas, list), "idea completeness entries must be an array")
    candidate_spans = {
        row["candidate"]["candidate_id"]: row["spans"]
        for row in extraction["candidates"]
    }
    candidate_ids = set(candidate_spans)
    mapped = set()
    span_keys = []
    for row in ideas:
        _require(
            isinstance(row, dict)
            and set(row) == {"idea_id", "span", "outcome", "candidate_id", "reason"},
            "idea completeness entry shape",
        )
        _text(row["idea_id"], "idea_id")
        _span(row["span"], raw_proposal, "idea completeness")
        span_keys.append((row["span"]["start"], row["span"]["end"]))
        _require(
            isinstance(row["outcome"], str)
            and row["outcome"] in {"extracted", "retained-unformed", "excluded"},
            "idea outcome",
        )
        _text(row["reason"], "idea completeness reason")
        if row["outcome"] == "extracted":
            _require(
                row["candidate_id"] in candidate_ids, "idea maps unknown candidate"
            )
            _require(
                row["span"] in candidate_spans[row["candidate_id"]],
                "idea span does not bind mapped candidate",
            )
            mapped.add(row["candidate_id"])
        else:
            _require(
                row["candidate_id"] is None,
                "unformed/excluded idea cannot map candidate",
            )
    _unique([row["idea_id"] for row in ideas], "idea ID")
    _unique(span_keys, "idea span")
    _require(
        mapped == candidate_ids,
        "formed extracted idea omitted from completeness record",
    )
    payload = {
        "kind": "Stage2IdeationCompleteness",
        "schema_version": "1.0.0",
        "scope": "caller-supplied-spans-only",
        "packet_sha256": canonical_hash(packet),
        "snapshot_sha256": snapshot_sha256,
        "raw_proposal_sha256": hashlib.sha256(raw_proposal.encode("utf-8")).hexdigest(),
        "extraction_sha256": canonical_hash(extraction),
        "ideas": copy.deepcopy(ideas),
    }
    return {**payload, "record_sha256": canonical_hash(payload)}


def _validate_completeness(
    raw_proposal, extraction, packet, snapshot_sha256, record, expected_sha256
):
    _require(
        isinstance(record, dict) and isinstance(expected_sha256, str),
        "opt-in completeness record and expected hash required",
    )
    _require(
        canonical_hash(record) == expected_sha256, "external completeness hash mismatch"
    )
    rebuilt = prepare_completeness_record(
        raw_proposal, extraction, packet, snapshot_sha256, record.get("ideas")
    )
    _require(record == rebuilt, "completeness record reconstruction mismatch")
