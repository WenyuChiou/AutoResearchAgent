"""Build evidence-bound tasks for opt-in Stage 2 follow-up research.

The task describes what native research should check.  It never infers novelty,
feasibility, a scientific score, or a resource price from candidate wording.
"""

import copy
import re

from stage2_check.contracts import latest_candidates
from stage2_common import Stage2Error, canonical_hash

VERSION = "1.0.0"
_DIGEST = re.compile(r"[0-9a-f]{64}")
_QUERY_FAMILIES = (
    "problem_synonyms",
    "mechanism_synonyms",
    "method_synonyms",
    "validation_synonyms",
    "cross_domain_analogues",
    "citation_chaining",
    "counterevidence",
)
_RESOURCE_CHECKS = (
    "required_content",
    "access",
    "version",
    "license_and_sharing",
    "variables",
    "granularity",
    "linkage",
)
_OUTCOMES = (
    "supported",
    "no-result",
    "failure",
    "inaccessible",
    "unverified",
    "required-content-absent",
)


def _policy(policy):
    if not isinstance(policy, dict) or set(policy) != {
        "kind",
        "schema_version",
        "canonical_policy_ref",
        "probe_boundary",
    }:
        raise Stage2Error("research-followup-policy-shape")
    boundary = policy["probe_boundary"]
    if (
        policy["kind"] != "Stage2ResearchFollowupPolicy"
        or policy["schema_version"] != VERSION
        or not isinstance(policy["canonical_policy_ref"], str)
        or not policy["canonical_policy_ref"].strip()
        or not isinstance(boundary, dict)
        or set(boundary)
        != {"max_queries_per_family", "stop_after_repeated_no_progress"}
        or isinstance(boundary["max_queries_per_family"], bool)
        or not isinstance(boundary["max_queries_per_family"], int)
        or boundary["max_queries_per_family"] < 1
        or boundary["stop_after_repeated_no_progress"] is not True
    ):
        raise Stage2Error("research-followup-policy-invalid")
    return copy.deepcopy(policy)


def validate_research_followup_policy(policy):
    """Validate and copy the externally configured canonical probe policy."""

    return _policy(policy)


def _evidence_snapshot(packet):
    return canonical_hash(
        {
            "packet_schema_version": packet.get("schema_version"),
            "sources": packet.get("sources"),
            "evidence": packet.get("evidence"),
            "literature": packet.get("literature"),
            "comparisons": packet.get("comparisons"),
            "unresolved": packet.get("unresolved"),
        }
    )


def _candidate_map(packet):
    try:
        _, current = latest_candidates(packet, [])
    except (KeyError, TypeError, ValueError) as error:
        raise Stage2Error("research-followup-packet-invalid") from error
    return current


def _text(value, label, *, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise Stage2Error(f"research-followup-{label}-invalid")
    return value


def _issue_fingerprint(row):
    return canonical_hash(
        {
            "candidate_id": row.get("candidate_id"),
            "candidate_version": row.get("candidate_version"),
            "decision_affected": row.get("decision_affected"),
            "scope_change_requested": row.get("scope_change_requested"),
        }
    )


def _normalize_followups(followups):
    required = {
        "candidate_id",
        "candidate_version",
        "missing_evidence",
        "decision_affected",
        "scope_change_requested",
    }
    if not isinstance(followups, list) or not followups:
        raise Stage2Error("research-followup-rows-required")
    normalized = []
    seen = set()
    for row in followups:
        if not isinstance(row, dict) or set(row) != required:
            raise Stage2Error("research-followup-row-shape")
        candidate_id = _text(row["candidate_id"], "candidate-id")
        version = row["candidate_version"]
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise Stage2Error("research-followup-candidate-version-invalid")
        if candidate_id in seen:
            raise Stage2Error("research-followup-duplicate-candidate")
        seen.add(candidate_id)
        missing = row["missing_evidence"]
        if not isinstance(missing, list) or any(
            not isinstance(value, str) or not value.strip() for value in missing
        ):
            raise Stage2Error("research-followup-missing-evidence-shape")
        if not isinstance(row["scope_change_requested"], bool):
            raise Stage2Error("research-followup-scope-change-invalid")
        normalized.append(
            {
                "candidate_id": candidate_id,
                "candidate_version": version,
                "missing_evidence": sorted(set(missing)),
                "decision_affected": _text(
                    row["decision_affected"], "decision-affected"
                ),
                "scope_change_requested": row["scope_change_requested"],
            }
        )
    return sorted(normalized, key=lambda row: row["candidate_id"])


def _task_digest(task):
    if not isinstance(task, dict) or not isinstance(task.get("task_sha256"), str):
        raise Stage2Error("research-followup-previous-task-shape")
    unhashed = {key: value for key, value in task.items() if key != "task_sha256"}
    if task["task_sha256"] != canonical_hash(unhashed):
        raise Stage2Error("research-followup-previous-task-hash-mismatch")
    return task["task_sha256"]


def _previous_index(previous_task):
    if previous_task is None:
        return {}
    if not isinstance(previous_task, dict):
        raise Stage2Error("research-followup-previous-task-shape")
    return {
        (row.get("candidate_id"), row.get("issue_fingerprint")): row
        for row in previous_task.get("tasks", [])
        if isinstance(row, dict)
    }


def _queries(candidate):
    anchors = {
        "question": candidate["question"],
        "opportunity": candidate["opportunity"],
        "approach": candidate["approach"],
        "research_mode": candidate["research_mode"],
    }
    prompts = {
        "problem_synonyms": "Find prior work addressing equivalent problem formulations.",
        "mechanism_synonyms": "Find prior work using equivalent or competing mechanisms.",
        "method_synonyms": "Find prior work using equivalent method families.",
        "validation_synonyms": "Find validation, replication, or falsification studies.",
        "cross_domain_analogues": "Find transferable analogues in other domains and state limits.",
        "citation_chaining": "Trace backward and forward citations from supported closest work.",
        "counterevidence": "Search for evidence that weakens the opportunity or proposed increment.",
    }
    return {
        name: {"instruction": prompts[name], "anchors": copy.deepcopy(anchors)}
        for name in _QUERY_FAMILIES
    }


def _resources(candidate):
    checks = {}
    for name in _RESOURCE_CHECKS:
        checks[name] = {
            "status": "unknown",
            "evidence_refs": [],
            "required_for_decision": True,
        }
    checks["license_and_sharing"]["alternatives_required"] = True
    checks["variables"]["absence_must_be_evidenced"] = True
    checks["linkage"]["requires_joint_evidence"] = True
    return {
        "requirements": copy.deepcopy(candidate.get("requirements", [])),
        "checks": checks,
        "cost": "unknown",
        "cost_evidence_refs": [],
        "alternatives": [],
        "joint_dependencies": {
            "status": "unknown",
            "requires_joint_evidence": True,
            "evidence_refs": [],
        },
        "allowed_outcomes": list(_OUTCOMES),
        "probe_rule": (
            "Record each no-result, failure, inaccessible, unverified, absent, or supported "
            "outcome separately; metadata or downloadability alone is not scientific support."
        ),
    }


def build_research_followup_task(
    packet,
    snapshot_sha256,
    followups,
    policy,
    *,
    previous_task=None,
):
    """Create a versioned native-research task pack from controller follow-ups."""

    policy = _policy(policy)
    if not isinstance(snapshot_sha256, str) or not _DIGEST.fullmatch(snapshot_sha256):
        raise Stage2Error("research-followup-snapshot-sha256-invalid")
    followups = _normalize_followups(followups)
    candidates = _candidate_map(packet)
    evidence_snapshot = _evidence_snapshot(packet)
    if previous_task is not None:
        _task_digest(previous_task)
    prior = _previous_index(previous_task)
    tasks = []
    for row in followups:
        candidate_id = row["candidate_id"]
        candidate = candidates.get(candidate_id)
        if candidate is None:
            raise Stage2Error("research-followup-candidate-missing")
        version = row["candidate_version"]
        if candidate.get("version") != version:
            raise Stage2Error("research-followup-candidate-version-stale")
        missing = row["missing_evidence"]
        decision = row["decision_affected"]
        issue = _issue_fingerprint(row)
        no_next_action = not missing and not row["scope_change_requested"]
        repeated = prior.get((candidate_id, issue))
        stop = bool(
            no_next_action
            and repeated
            and repeated.get("action")
            in {"native-research-followup", "stop-no-progress"}
            and previous_task.get("evidence_snapshot_sha256") == evidence_snapshot
            and previous_task.get("policy_sha256") == canonical_hash(policy)
        )
        needs = (
            []
            if stop
            else [
                {
                    "need_ref": f"{candidate_id}:need:{index}",
                    "question": value,
                    "decision_affected": decision,
                    "status": "unknown",
                }
                for index, value in enumerate(sorted(set(missing)), start=1)
            ]
        )
        tasks.append(
            {
                "candidate_id": candidate_id,
                "candidate_version": version,
                "candidate_sha256": canonical_hash(candidate),
                "issue_fingerprint": issue,
                "action": "stop-no-progress" if stop else "native-research-followup",
                "needs": needs,
                "decision_affected": decision,
                "scope_change_requested": row["scope_change_requested"],
                "closest_work": {
                    "query_families": _queries(candidate),
                    "novelty_status": "unknown",
                    "scientific_support_status": "unknown",
                    "metadata_only_is_support": False,
                },
                "resource_checks": _resources(candidate),
                "decision_state": {
                    "feasibility": "unknown",
                    "scientific_performance": "unknown",
                    "human_budget": "unknown",
                    "portfolio_utility": "unknown",
                },
                "output_contract": {
                    "action_ref_required": True,
                    "need_refs": [value["need_ref"] for value in needs],
                    "accepted_revision_kinds": [
                        "Stage2SourceUpdate",
                        "Stage2ContentRevision",
                    ],
                    "preserve_outcome_distinctions": list(_OUTCOMES),
                },
            }
        )
    result = {
        "kind": "Stage2ResearchFollowupTask",
        "schema_version": VERSION,
        "packet_sha256": canonical_hash(packet),
        "snapshot_sha256": snapshot_sha256,
        "evidence_snapshot_sha256": evidence_snapshot,
        "policy": policy,
        "policy_sha256": canonical_hash(policy),
        "probe_boundary": copy.deepcopy(policy["probe_boundary"]),
        "originating_followups": copy.deepcopy(followups),
        "prior_task_sha256": (
            None if previous_task is None else previous_task["task_sha256"]
        ),
        "tasks": tasks,
    }
    result["task_sha256"] = canonical_hash(result)
    return result


def validate_research_followup_task(
    task,
    packet,
    snapshot_sha256,
    policy,
    *,
    expected_followups,
    expected_previous_task=None,
):
    """Reconstruct a task from trusted inputs and require exact equality."""

    if not isinstance(task, dict):
        raise Stage2Error("research-followup-task-shape")
    if task.get("snapshot_sha256") != snapshot_sha256:
        raise Stage2Error("research-followup-snapshot-stale")
    if task.get("policy_sha256") != canonical_hash(_policy(policy)):
        raise Stage2Error("research-followup-policy-mismatch")
    candidates = _candidate_map(packet)
    for row in task.get("tasks", []):
        if not isinstance(row, dict):
            raise Stage2Error("research-followup-task-row-shape")
        candidate = candidates.get(row.get("candidate_id"))
        if candidate is None or candidate.get("version") != row.get(
            "candidate_version"
        ):
            raise Stage2Error("research-followup-candidate-version-stale")
    if task.get("evidence_snapshot_sha256") != _evidence_snapshot(packet):
        raise Stage2Error("research-followup-evidence-revision-stale")
    expected = build_research_followup_task(
        packet,
        snapshot_sha256,
        expected_followups,
        policy,
        previous_task=expected_previous_task,
    )
    if task != expected:
        raise Stage2Error("research-followup-task-reconstruction-mismatch")
    return task
