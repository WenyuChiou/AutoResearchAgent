"""Source-bound prerequisite and joint-resource records, not scientific approval."""

from copy import deepcopy
import math

from stage2_check.contracts import latest_candidates
from stage2_common import (
    Stage2Error,
    canonical_hash,
    validate_evidence_refs,
    validate_packet,
)

KINDS = {"data", "tool", "model", "license", "cost", "premise", "validation-path"}
STATES = {"supported", "contradicted", "unknown", "not-applicable"}


def _require(value, message):
    if not value:
        raise Stage2Error(message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _quantity(value):
    if value is None:
        return True
    if type(value) not in {int, float} or value < 0:
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, ValueError):
        return False


def _text_list(value, message, *, nonempty=True):
    _require(
        isinstance(value, list)
        and (bool(value) or not nonempty)
        and all(_text(item) for item in value),
        message,
    )
    _require(len(value) == len(set(value)), message)
    return value


def prepare_prerequisite_review(
    packet, source_root, candidate_ids, checks, demands, capacities
):
    """Keep individual checks separate from combined resource feasibility.

    A demand component is charged once across its explicitly declared users.
    Separate components cannot share work merely because their names match.
    Evidence identity is validated here; an independent reviewer must assess
    whether it actually supports a premise, license or estimate.
    """
    validate_packet(packet, source_root)
    _, latest = latest_candidates(packet, [])
    _text_list(candidate_ids, "candidate scope required")
    _require(set(candidate_ids).issubset(latest), "unknown prerequisite candidate")
    _require(
        isinstance(checks, list)
        and isinstance(demands, list)
        and isinstance(capacities, list),
        "prerequisite collections required",
    )
    seen = set()
    covered = set()
    for row in checks:
        _require(
            isinstance(row, dict)
            and set(row)
            == {
                "check_id",
                "candidate_id",
                "candidate_version",
                "kind",
                "statement",
                "status",
                "evidence_ids",
                "reason",
                "next_check",
            },
            "prerequisite check shape",
        )
        _require(
            _text(row["check_id"]) and row["check_id"] not in seen,
            "duplicate or empty check ID",
        )
        seen.add(row["check_id"])
        candidate = row["candidate_id"]
        _require(
            _text(candidate)
            and candidate in candidate_ids
            and type(row["candidate_version"]) is int
            and row["candidate_version"] == latest[candidate]["version"],
            "stale prerequisite candidate",
        )
        _require(
            _text(row["kind"])
            and row["kind"] in KINDS
            and _text(row["status"])
            and row["status"] in STATES,
            "invalid prerequisite kind/state",
        )
        _require(
            _text(row["statement"]) and _text(row["reason"]),
            "prerequisite statement/reason required",
        )
        validate_evidence_refs(row["evidence_ids"], packet)
        if row["status"] in {"supported", "contradicted"}:
            _require(bool(row["evidence_ids"]), "prerequisite evidence required")
        if row["status"] == "unknown":
            _require(
                _text(row["next_check"]), "unknown prerequisite next check required"
            )
        else:
            _require(
                row["next_check"] is None or _text(row["next_check"]),
                "invalid next check",
            )
        key = (candidate, row["kind"])
        _require(key not in covered, "duplicate prerequisite category")
        covered.add(key)
    _require(
        covered == {(candidate, kind) for candidate in candidate_ids for kind in KINDS},
        "missing prerequisite category; record explicit not-applicable with reason",
    )

    units, component_ids = set(), set()
    for row in demands:
        _require(
            isinstance(row, dict)
            and set(row)
            == {
                "component_id",
                "candidate_ids",
                "unit",
                "amount",
                "evidence_ids",
                "basis",
            },
            "resource demand shape",
        )
        _require(
            _text(row["component_id"]) and row["component_id"] not in component_ids,
            "duplicate resource component",
        )
        component_ids.add(row["component_id"])
        _text_list(row["candidate_ids"], "resource component candidate scope")
        _require(
            set(row["candidate_ids"]).issubset(candidate_ids),
            "resource component candidate scope",
        )
        _require(_quantity(row["amount"]), "unsupported resource quantity")
        _require(
            _text(row["unit"]) and _text(row["basis"]), "invalid resource estimate"
        )
        validate_evidence_refs(row["evidence_ids"], packet)
        _require(
            row["amount"] is None or bool(row["evidence_ids"]),
            "known estimate needs evidence",
        )
        units.add(row["unit"])
    budgets = {}
    for row in capacities:
        _require(
            isinstance(row, dict) and set(row) == {"unit", "amount", "decision_ref"},
            "resource capacity shape",
        )
        _require(_quantity(row["amount"]), "unsupported resource quantity")
        _require(
            _text(row["unit"]) and row["unit"] not in budgets,
            "duplicate or invalid capacity",
        )
        _require(_text(row["decision_ref"]), "capacity decision provenance required")
        budgets[row["unit"]] = row["amount"]
        units.add(row["unit"])
    totals = []
    applicable_cost_candidates = {
        row["candidate_id"]
        for row in checks
        if row["kind"] == "cost" and row["status"] != "not-applicable"
    }
    _require(
        not applicable_cost_candidates or bool(units),
        "applicable cost requires explicit resource demand",
    )
    for unit in sorted(units):
        parts = [row for row in demands if row["unit"] == unit]
        covered_candidates = {
            candidate_id for row in parts for candidate_id in row["candidate_ids"]
        }
        missing_candidates = sorted(applicable_cost_candidates - covered_candidates)
        amount = (
            None
            if missing_candidates
            or not parts
            or any(row["amount"] is None for row in parts)
            else sum(row["amount"] for row in parts)
        )
        _require(_quantity(amount), "unsupported aggregate resource quantity")
        capacity = budgets.get(unit)
        state = (
            "unknown"
            if amount is None or capacity is None
            else "exceeds"
            if amount > capacity
            else "within"
        )
        totals.append(
            {
                "unit": unit,
                "demand": amount,
                "capacity": capacity,
                "status": state,
                "missing_candidate_ids": missing_candidates,
            }
        )
    payload = {
        "kind": "Stage2PrerequisiteReview",
        "schema_version": "1.0.0",
        "packet_sha256": canonical_hash(packet),
        "candidate_refs": [
            {"candidate_id": key, "version": latest[key]["version"]}
            for key in sorted(candidate_ids)
        ],
        "checks": deepcopy(checks),
        "demands": deepcopy(demands),
        "capacities": deepcopy(capacities),
        "portfolio_resources": totals,
        "semantic_verification": "not-established",
        "recommendation_authorized": False,
        "stage3_authorized": False,
    }
    return {**payload, "record_sha256": canonical_hash(payload)}


def inspect_prerequisite_review(record, packet, source_root, expected_sha256):
    """Reconstruct from bound current evidence; rehashed stale records fail."""
    _require(isinstance(record, dict), "prerequisite record shape")
    _require(
        set(record)
        == {
            "kind",
            "schema_version",
            "packet_sha256",
            "candidate_refs",
            "checks",
            "demands",
            "capacities",
            "portfolio_resources",
            "semantic_verification",
            "recommendation_authorized",
            "stage3_authorized",
            "record_sha256",
        },
        "prerequisite record shape",
    )
    _require(
        canonical_hash(record) == expected_sha256, "external prerequisite hash mismatch"
    )
    refs = record["candidate_refs"]
    _require(isinstance(refs, list) and refs, "prerequisite candidate refs")
    for row in refs:
        _require(
            isinstance(row, dict)
            and set(row) == {"candidate_id", "version"}
            and _text(row["candidate_id"])
            and type(row["version"]) is int
            and row["version"] >= 1,
            "prerequisite candidate refs",
        )
    reconstructed = prepare_prerequisite_review(
        packet,
        source_root,
        [row["candidate_id"] for row in refs],
        record["checks"],
        record["demands"],
        record["capacities"],
    )
    _require(record == reconstructed, "prerequisite record reconstruction mismatch")
    return reconstructed
