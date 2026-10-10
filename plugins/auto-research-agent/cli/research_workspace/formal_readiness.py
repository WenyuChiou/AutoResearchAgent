"""Derive formal Stage 1 readiness from explicit, source-bound evidence."""

from collections import Counter
from copy import deepcopy
import re

from stage1_brief.formal_target import formal_target_state
from stage1_deliverable.common import DeliverableError

from .literature_selection import derive_literature_selection


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_QUALIFICATION_FIELDS = {
    "status",
    "work_id",
    "version_id",
    "source_id",
    "raw_sha256",
    "text_sha256",
    "identity_checked",
    "body_checked",
    "reading_order_checked",
    "relevance_checked",
    "evidence_refs",
}
_FINDING_FIELDS = (
    "question",
    "data",
    "method",
    "main_findings",
    "limitations",
    "relevance",
)
_PLACEHOLDERS = {
    "",
    "unknown",
    "not scored",
    "not-scored",
    "pending",
    "tbd",
    "todo",
    "n/a",
    "not available",
    "not assessed",
}


def _require(condition, message):
    if not condition:
        raise DeliverableError("formal-readiness: " + message)


def _substantial(value):
    if type(value) is not str or not value.strip():
        return False
    normalized = " ".join(value.casefold().split())
    if normalized in _PLACEHOLDERS:
        return False
    if any(
        normalized.startswith(marker + " ")
        or normalized.startswith(marker + ";")
        or normalized.startswith(marker + ":")
        for marker in ("pending", "tbd", "todo")
    ):
        return False
    if normalized.startswith("unknown") or normalized.startswith("source not reported"):
        return len(normalized) >= 24 and any(
            marker in normalized
            for marker in ("evidence", "source", "reported", "not state", "not provide")
        )
    return len(value.strip()) >= 8


def _note_complete(paper):
    note = paper.get("fresh_note")
    findings = paper.get("findings")
    return (
        type(note) is dict
        and note.get("paper_note_status") == "complete"
        and type(findings) is dict
        and all(_substantial(findings.get(field)) for field in _FINDING_FIELDS)
    )


def _qualification(paper, selection_row, input_version):
    note = paper.get("fresh_note")
    if type(note) is not dict or "source_qualification" not in note:
        return None
    declaration = note["source_qualification"]
    _require(
        paper.get("input_version") == input_version,
        "qualification input version differs",
    )
    _require(type(declaration) is dict, "source qualification must be an object")
    _require(
        set(declaration) == _QUALIFICATION_FIELDS,
        "source qualification fields malformed",
    )
    _require(declaration["status"] == "qualified", "qualification status invalid")
    _require(
        (declaration["work_id"], declaration["version_id"])
        == (paper["work_id"], paper["version_id"]),
        "qualification work/version differs",
    )
    _require(
        declaration["source_id"] in selection_row["eligible_source_ids"],
        "qualification source is not technically eligible",
    )
    binding = next(
        (
            item
            for item in selection_row["source_binding_references"]
            if item["source_id"] == declaration["source_id"]
        ),
        None,
    )
    _require(binding is not None, "qualification source binding missing")
    for name in ("raw_sha256", "text_sha256"):
        value = declaration[name]
        _require(
            type(value) is str and _SHA256.fullmatch(value) and value == binding[name],
            "qualification " + name + " differs",
        )
    for name in (
        "identity_checked",
        "body_checked",
        "reading_order_checked",
        "relevance_checked",
    ):
        _require(declaration[name] is True, "qualification " + name + " incomplete")
    refs = declaration["evidence_refs"]
    _require(
        type(refs) is list
        and bool(refs)
        and all(type(ref) is str and bool(ref.strip()) for ref in refs),
        "qualification evidence_refs malformed",
    )
    return deepcopy(declaration)


def _resources(resources):
    if resources is None:
        return None
    _require(type(resources) is dict, "resources must be an object")
    _require(set(resources) == {"queries", "acquisitions"}, "resource fields malformed")
    result = {}
    for name in ("queries", "acquisitions"):
        value = resources[name]
        _require(
            type(value) is dict and set(value) == {"used", "limit"},
            name + " resource receipt malformed",
        )
        used, limit = value["used"], value["limit"]
        _require(
            type(used) is int
            and type(limit) is int
            and used >= 0
            and limit >= 0
            and used <= limit,
            name + " resource values invalid",
        )
        result[name] = {"used": used, "limit": limit, "exhausted": used == limit}
    return result


def derive_formal_readiness(index, brief, *, resources=None):
    """Validate explicit qualification bindings and derive a non-authorizing decision."""
    selection = derive_literature_selection(index)
    target = formal_target_state(brief)
    _require(brief["project_id"] == index["project_id"], "wrong brief project")
    normalized_resources = _resources(resources)
    rows = {(row["work_id"], row["version_id"]): row for row in selection["rows"]}
    formal_work_ids = set()
    technical_work_ids = set()
    pending_work_ids = set()
    note_complete_versions = 0
    reasons = Counter()
    qualification_rows = []
    for paper in index["papers"]:
        identity = (paper["work_id"], paper["version_id"])
        row = rows[identity]
        technical = row["status"] == "included"
        if technical:
            technical_work_ids.add(paper["work_id"])
        qualified = _qualification(paper, row, brief["input_version"])
        if qualified:
            formal_work_ids.add(paper["work_id"])
        elif technical:
            pending_work_ids.add(paper["work_id"])
            reasons["source-qualification-pending"] += 1
        else:
            reasons["technical-source-ineligible"] += 1
        note_complete = _note_complete(paper)
        note_complete_versions += note_complete
        if not note_complete:
            reasons["paper-note-pending"] += 1
        qualification_rows.append(
            {
                "work_id": paper["work_id"],
                "version_id": paper["version_id"],
                "technical_status": row["status"],
                "qualification_status": "qualified" if qualified else "pending",
                "note_status": "complete" if note_complete else "pending",
            }
        )

    coverage_rows = deepcopy(index.get("coverage", []))
    coverage_statuses = []
    unresolved_need_ids = []
    seen_needs = set()
    for position, row in enumerate(coverage_rows):
        _require(type(row) is dict, "coverage row must be an object")
        need_id = row.get("need_id")
        status = row.get("evidence_status", row.get("status"))
        _require(
            type(need_id) is str and bool(need_id.strip()),
            "coverage need_id missing",
        )
        _require(
            type(status) is str and bool(status.strip()), "coverage status missing"
        )
        _require(need_id not in seen_needs, "duplicate coverage need_id")
        seen_needs.add(need_id)
        coverage_statuses.append(
            {"need_id": need_id, "evidence_status": status, "position": position}
        )
        work_ids, evidence_refs = row.get("work_ids"), row.get("evidence_refs")
        bound_coverage = (
            status == "qualified"
            and type(work_ids) is list
            and bool(work_ids)
            and all(
                type(work_id) is str and work_id in formal_work_ids
                for work_id in work_ids
            )
            and type(evidence_refs) is list
            and bool(evidence_refs)
            and all(type(ref) is str and bool(ref.strip()) for ref in evidence_refs)
        )
        if not bound_coverage:
            unresolved_need_ids.append(need_id)
            reasons[
                "coverage-"
                + ("qualification-binding-missing" if status == "qualified" else status)
            ] += 1
    needs = brief.get("needs")
    _require(type(needs) is list and bool(needs), "brief needs missing")
    expected_needs = [item.get("need_id") for item in needs if type(item) is dict]
    _require(
        len(expected_needs) == len(needs)
        and all(type(item) is str and bool(item.strip()) for item in expected_needs)
        and len(set(expected_needs)) == len(expected_needs),
        "brief need inventory malformed",
    )
    _require(seen_needs <= set(expected_needs), "coverage contains a foreign need")
    for need_id in expected_needs:
        if need_id not in seen_needs:
            coverage_statuses.append(
                {"need_id": need_id, "evidence_status": "missing", "position": None}
            )
            unresolved_need_ids.append(need_id)
            reasons["coverage-missing"] += 1
    all_coverage_qualified = not unresolved_need_ids

    formal_count = len(formal_work_ids)
    confirmed = target["status"] == "confirmed"
    shortfall = max(0, target["target"] - formal_count) if confirmed else None
    target_met = confirmed and shortfall == 0
    pending_work_ids -= formal_work_ids
    recoverable = len(pending_work_ids)
    artifacts = index.get("source_rerun", {}).get("artifact_hashes", {})
    diagnostic_backlog = {
        row["work_id"]
        for row in selection["rows"]
        if row["work_id"] not in formal_work_ids
        and any(
            (
                row["status"] == "pending"
                or "broken-parser" in binding["failure_reasons"]
            )
            and type(binding.get("raw_sha256")) is str
            and _SHA256.fullmatch(binding["raw_sha256"])
            and artifacts.get(binding.get("raw_path"), {}).get("sha256")
            == binding["raw_sha256"]
            and type(artifacts.get(binding.get("raw_path"), {}).get("bytes")) is int
            and artifacts[binding["raw_path"]]["bytes"] > 0
            for binding in row["source_binding_references"]
        )
    }
    if target_met and all_coverage_qualified:
        decision = "stop-count-target-and-covered"
    elif target_met:
        decision = "coverage-directed-work"
    elif recoverable:
        decision = "review-saved-backlog"
    elif diagnostic_backlog:
        decision = "diagnose-saved-backlog"
    elif normalized_resources and any(
        value["exhausted"] for value in normalized_resources.values()
    ):
        decision = "partial-resource-exhausted"
    elif normalized_resources is None:
        decision = "resources-unknown"
    else:
        decision = "continue-bounded"

    return {
        "kind": "Stage1FormalReadiness",
        "schema_version": "1.0.0",
        **target,
        "candidate_version_count": len(index["papers"]),
        "candidate_distinct_works": len(
            {paper["work_id"] for paper in index["papers"]}
        ),
        "technical_eligible_distinct_works": len(technical_work_ids),
        "technical_eligible_work_ids": sorted(technical_work_ids),
        "formally_usable_distinct_works": formal_count,
        "formally_usable_work_ids": sorted(formal_work_ids),
        "formal_target_met": target_met,
        "target_shortfall": shortfall,
        "note_complete_versions": note_complete_versions,
        "note_pending_versions": len(index["papers"]) - note_complete_versions,
        "qualification_rows": qualification_rows,
        "qualified_coverage": all_coverage_qualified,
        "coverage_need_statuses": coverage_statuses,
        "coverage_rows": coverage_rows,
        "unresolved_need_ids": unresolved_need_ids,
        "pending_distinct_backlog": len(pending_work_ids | diagnostic_backlog),
        "recoverable_distinct_backlog": recoverable,
        "parser_or_identity_distinct_backlog": len(diagnostic_backlog),
        "backlog_reason_counts": dict(sorted(reasons.items())),
        "resources": normalized_resources,
        "decision": decision,
        "stage1_completed": False,
        "official_stage2_import_eligible": False,
        "tool_actions_authorized": False,
        "limits": "Qualification receipts validate declared bindings only; source semantics, reviewer identity, scientific sufficiency, completion, import, and tool execution remain unassessed or unauthorized.",
    }
