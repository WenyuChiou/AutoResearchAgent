"""Deterministic, role-isolated audit views and inspectable submission manifests."""

from .common import EvaluationError, canonical, sha


def _observations(audits, work_ids=None):
    """Retain target/unit identity and all conclusions, without transport receipts."""
    if audits is None:
        return None
    selected = {}
    for role, audit in sorted(audits.items()):
        target_ids = [row["target"]["id"] for row in audit["summaries"]]
        unit_ids = [row["unit_id"] for row in audit["leaves"]]
        if (
            len(target_ids) != len(set(target_ids))
            or len(unit_ids) != len(set(unit_ids))
            or any(row["target_id"] not in target_ids for row in audit["leaves"])
        ):
            raise EvaluationError("source audit has duplicate or unbound obligations")
        summaries = [
            {key: row[key] for key in ("target", "verdict", "unknown_reason")}
            for row in audit["summaries"]
            if work_ids is None or work_ids.intersection(row["target"]["work_ids"])
        ]
        targets = {row["target"]["id"] for row in summaries}
        leaves = []
        for row in audit["leaves"]:
            if row["target_id"] not in targets:
                continue
            value = row["value"]
            leaves.append(
                {
                    "unit_id": row["unit_id"],
                    "target_id": row["target_id"],
                    "value": {
                        "verdict": value["verdict"],
                        "reason": value["reason"],
                        "passages": [
                            {
                                key: passage.get(key)
                                for key in (
                                    "evidence_id",
                                    "view",
                                    "start",
                                    "end",
                                    "source_level",
                                )
                            }
                            for passage in value["passages"]
                        ],
                    },
                }
            )
        selected[role] = {
            "summaries": sorted(summaries, key=lambda row: row["target"]["id"]),
            "leaves": sorted(leaves, key=lambda row: row["unit_id"]),
            "score_awarded": False,
        }
    return selected


def _audit_manifest(audits, supplied, role, phase, prior):
    """Describe the exact supplied view, including unknowns and scope exclusions."""
    if role not in {"r1", "r2", "adj"}:
        raise EvaluationError("unknown complete judge role")
    expected = {"r1", "r2"} if role == "adj" else {role}
    if supplied is not None and set(supplied) != expected:
        raise EvaluationError("source audit role isolation violated")
    if role == "adj" and not prior:
        raise EvaluationError("source audit adjudication requires disagreement")
    views = {}
    for source_role, audit in (supplied or {}).items():
        targets = [row["target"]["id"] for row in audit["summaries"]]
        units = [row["unit_id"] for row in audit["leaves"]]
        original = audits[source_role]
        views[source_role] = {
            "target_ids": targets,
            "unit_ids": units,
            "unavailable_targets": [
                {"target_id": row["target"]["id"], "reason": row["unknown_reason"]}
                for row in audit["summaries"]
                if row["verdict"] == "unverifiable"
            ],
            "unavailable_unit_ids": [
                row["unit_id"]
                for row in audit["leaves"]
                if row["value"]["verdict"] == "unverifiable"
            ],
            "out_of_scope_target_ids": sorted(
                {row["target"]["id"] for row in original["summaries"]} - set(targets)
            ),
            "out_of_scope_unit_ids": sorted(
                {row["unit_id"] for row in original["leaves"]} - set(units)
            ),
            "supplied_view_sha256": sha(canonical(audit)),
            "omitted_target_ids": [],
            "omitted_unit_ids": [],
            "truncated": False,
        }
    return {
        "kind": "Stage1SourceAuditViewManifest.v1",
        "judge_role": role.upper(),
        "audit_source_roles": sorted(views),
        "state": "not-applicable"
        if phase == "process"
        else ("supplied" if supplied is not None else "unavailable"),
        "unavailable_reason": "source-audit-view-unavailable"
        if phase == "content" and supplied is None
        else None,
        "roles": views,
        "supplied_view_sha256": sha(canonical(supplied)),
        "omitted": False,
        "truncated": False,
    }
