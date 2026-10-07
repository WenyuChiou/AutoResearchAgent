"""Convert validated prose extraction into a new packet, never an approval."""

import copy

from stage2_common import Stage2Error, canonical_hash, validate_packet

from .extraction import validate_extraction
from .topic_tables import materialize_research_tables, validate_research_tables


UPDATE_MODES = {"append", "replace-comparison-unresolved"}
EXPLORATORY_PACKET_VERSIONS = {"2.1.0", "2.2.0", "2.3.0"}


def _comparison_text(rows, *, replacement):
    additions = []
    for row in rows:
        refs = ", ".join(row["evidence_ids"]) or "no verified evidence reference"
        additions.append(
            f"{row['dimension']} [{row['comparability']}]: {row['finding']} "
            f"(evidence: {refs}; limitations: {row['noncomparability'] or 'not stated'})"
        )
    if not additions:
        return None
    heading = (
        "Corrected proposal comparison (supersedes the current comparison; prior "
        "snapshots retain history):\n"
        if replacement
        else "Additional proposal comparison (subject to independent review):\n"
    )
    return heading + "\n".join(additions)


def _exploratory_acceptance_limitations(packet):
    if packet.get("schema_version") not in EXPLORATORY_PACKET_VERSIONS:
        return []
    upstream = packet.get("upstream", {})
    if upstream.get("intake_mode") != "exploratory":
        return []
    return copy.deepcopy(upstream["acceptance"]["limitations"])


def _replacement_unresolved(packet, extracted):
    acceptance_limitations = _exploratory_acceptance_limitations(packet)
    if not acceptance_limitations:
        replacement = copy.deepcopy(extracted)
        return replacement, replacement != packet["unresolved"]
    replacement = []
    for item in extracted:
        if item not in replacement:
            replacement.append(copy.deepcopy(item))
    for item in acceptance_limitations:
        if item not in replacement:
            replacement.append(copy.deepcopy(item))
    acceptance_set = set(acceptance_limitations)
    prior_current = [
        item for item in packet["unresolved"] if item not in acceptance_set
    ]
    next_current = [item for item in replacement if item not in acceptance_set]
    return replacement, next_current != prior_current


def build_next_packet(
    packet,
    source_root,
    raw_proposal,
    extraction,
    snapshot_sha256,
    *,
    update_mode="append",
):
    """Preserve old evidence/candidates and validate a proposed next snapshot.

    The caller must save the raw proposal before invoking an extractor and record
    native execution separately. This pure conversion neither runs a model nor
    verifies that extraction was tool-free. It never applies a scientific check.
    """
    validate_packet(packet, source_root)
    if update_mode not in UPDATE_MODES:
        raise Stage2Error("ideation-packet-update-mode-invalid")
    result = validate_extraction(raw_proposal, extraction, packet, snapshot_sha256)
    next_packet = copy.deepcopy(packet)
    existing = {
        (row["candidate_id"], row["version"]): row for row in packet["candidates"]
    }
    affected = []
    for row in result["candidates"]:
        candidate = row["candidate"]
        key = (candidate["candidate_id"], candidate["version"])
        if key in existing:
            if candidate != existing[key]:
                raise Stage2Error("ideation-cannot-rewrite-candidate-version")
        else:
            next_packet["candidates"].append(copy.deepcopy(candidate))
            existing[key] = candidate
            affected.append(candidate["candidate_id"])
    comparison = _comparison_text(
        result["comparison_rows"],
        replacement=update_mode == "replace-comparison-unresolved",
    )
    if update_mode == "replace-comparison-unresolved":
        latest = {
            candidate_id: max(
                (
                    row
                    for row in packet["candidates"]
                    if row["candidate_id"] == candidate_id
                ),
                key=lambda row: row["version"],
            )
            for candidate_id in {row["candidate_id"] for row in packet["candidates"]}
        }
        if len(affected) != len(set(affected)):
            raise Stage2Error("ideation-content-revision-duplicate-candidate")
        candidate_changed = False
        for row in result["candidates"]:
            candidate = row["candidate"]
            previous = latest.get(candidate["candidate_id"])
            if (
                previous is None
                or candidate["version"] != previous["version"] + 1
                or candidate["parent_version"] != previous["version"]
                or {
                    key: value
                    for key, value in candidate.items()
                    if key not in {"version", "parent_version"}
                }
                == {
                    key: value
                    for key, value in previous.items()
                    if key not in {"version", "parent_version"}
                }
            ):
                raise Stage2Error("ideation-content-revision-invalid-candidate")
            candidate_changed = True
        next_comparison = comparison or packet["comparison"]
        next_unresolved, unresolved_changed = _replacement_unresolved(
            packet, result["unresolved"]
        )
        if not (
            candidate_changed
            or next_comparison != packet["comparison"]
            or unresolved_changed
        ):
            raise Stage2Error("ideation-content-revision-no-substantive-change")
        next_packet["comparison"] = next_comparison
        next_packet["unresolved"] = next_unresolved
    else:
        if comparison:
            next_packet["comparison"] += "\n\n" + comparison
        for unknown in result["unresolved"]:
            if unknown not in next_packet["unresolved"]:
                next_packet["unresolved"].append(unknown)
    if (
        result.get("schema_version") == "1.1.0"
        and result["research_tables"] is not None
    ):
        next_packet["research_tables"] = materialize_research_tables(
            result["research_tables"],
            result["candidates"],
            packet,
            raw_proposal,
            snapshot_sha256,
        )
        validate_research_tables(next_packet["research_tables"], next_packet)
    next_packet["packet_id"] = (
        "ideation-" + canonical_hash({"parent": packet, "extraction": result})[:24]
    )
    validate_packet(next_packet, source_root)
    return {
        "packet": next_packet,
        "parent_packet_sha256": canonical_hash(packet),
        "extraction_sha256": canonical_hash(result),
        "snapshot_sha256": snapshot_sha256,
        "review_required": True,
        "native_execution_verified": False,
        "scientific_quality_verified": False,
        "update_mode": update_mode,
        "affected_candidate_ids": sorted(affected),
    }
