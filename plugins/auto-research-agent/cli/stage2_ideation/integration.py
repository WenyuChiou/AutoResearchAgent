"""Convert validated prose extraction into a new packet, never an approval."""

import copy

from stage2_common import Stage2Error, canonical_hash, validate_packet

from .extraction import validate_extraction


def build_next_packet(packet, source_root, raw_proposal, extraction, snapshot_sha256):
    """Preserve old evidence/candidates and validate a proposed next snapshot.

    The caller must save the raw proposal before invoking an extractor and record
    native execution separately. This pure conversion neither runs a model nor
    verifies that extraction was tool-free. It never applies a scientific check.
    """
    validate_packet(packet, source_root)
    result = validate_extraction(raw_proposal, extraction, packet, snapshot_sha256)
    next_packet = copy.deepcopy(packet)
    existing = {
        (row["candidate_id"], row["version"]): row for row in packet["candidates"]
    }
    for row in result["candidates"]:
        candidate = row["candidate"]
        key = (candidate["candidate_id"], candidate["version"])
        if key in existing:
            if candidate != existing[key]:
                raise Stage2Error("ideation-cannot-rewrite-candidate-version")
        else:
            next_packet["candidates"].append(copy.deepcopy(candidate))
            existing[key] = candidate
    additions = []
    for row in result["comparison_rows"]:
        refs = ", ".join(row["evidence_ids"]) or "no verified evidence reference"
        additions.append(
            f"{row['dimension']} [{row['comparability']}]: {row['finding']} "
            f"(evidence: {refs}; limitations: {row['noncomparability'] or 'not stated'})"
        )
    if additions:
        next_packet["comparison"] += (
            "\n\nAdditional proposal comparison (subject to independent review):\n"
            + "\n".join(additions)
        )
    for unknown in result["unresolved"]:
        if unknown not in next_packet["unresolved"]:
            next_packet["unresolved"].append(unknown)
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
    }
