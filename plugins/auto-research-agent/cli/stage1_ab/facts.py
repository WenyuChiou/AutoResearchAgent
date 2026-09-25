"""Derive v2 hard counts from private, evidence-linked human source checks.

Support and identity labels are reviewer judgments. This code checks their
provenance and arithmetic; it does not infer scientific truth from a DOI.
"""

from datetime import datetime
from pathlib import Path

from .runner import ExecutionBlocked, read_json, sha, verify_bound_file, verify_capture


def _evidence(annotations, eval_root, evidence_id):
    if evidence_id not in annotations["evidence"]:
        raise ExecutionBlocked(f"missing source evidence ID: {evidence_id}")
    binding = annotations["evidence"][evidence_id]
    if not binding["path"].startswith("private/") or not binding.get("locator"):
        raise ExecutionBlocked("source evidence needs a private file and locator")
    verify_bound_file(eval_root, binding)


def derive_facts(annotations, holdout, plan, capture_dir, eval_root):
    record = verify_capture(capture_dir, verify_runtime=False)
    if record["status"] != "complete":
        raise ExecutionBlocked("an incomplete subject cannot receive factual scores")
    runs = {
        run["run_id"]: condition
        for repeat in plan["paired_repeats"]
        for condition in ("baseline", "treatment")
        for run in (repeat[condition],)
    }
    if record["run_id"] not in runs or record["condition"] != runs[record["run_id"]]:
        raise ExecutionBlocked("captured subject is not a frozen plan run")
    for evidence_id in annotations["evidence"]:
        _evidence(annotations, eval_root, evidence_id)
    works = annotations["works"]
    claims = annotations["claims"]
    decisions = annotations["decisions"]
    searches = annotations["searches"]
    work_ids = [work["work_id"] for work in works]
    if len(work_ids) != len(set(work_ids)):
        raise ExecutionBlocked("duplicate work ID")
    anchor_ids = {anchor["anchor_id"]: anchor for anchor in holdout["anchors"]}
    hits = set()
    clusters = set()
    for work in works:
        if work["identity_status"] not in {
            "correct",
            "incorrect",
            "unverifiable",
        } or work["link_status"] not in {"correct", "incorrect", "unverifiable"}:
            raise ExecutionBlocked("invalid identity or link status")
        for key in (
            "identity_evidence_id",
            "link_evidence_id",
            "discovery_evidence_id",
        ):
            if work.get(key):
                _evidence(annotations, eval_root, work[key])
        if work["identity_status"] == "correct" and not work.get(
            "identity_evidence_id"
        ):
            raise ExecutionBlocked("correct identity lacks source check")
        if work["link_status"] == "correct" and not work.get("link_evidence_id"):
            raise ExecutionBlocked("correct link lacks source check")
        for anchor_id in work.get("matched_anchor_ids", []):
            if (
                anchor_id not in anchor_ids
                or not work.get("anchor_evidence_id")
                or work["identity_status"] != "correct"
                or work["link_status"] != "correct"
            ):
                raise ExecutionBlocked("anchor hit lacks frozen ID or evidence")
            _evidence(annotations, eval_root, work["anchor_evidence_id"])
            hits.add(anchor_id)
        for cluster in work.get("verified_clusters", []):
            if (
                cluster not in holdout["coverage_clusters"]
                or not work.get("cluster_evidence_id")
                or work["identity_status"] != "correct"
                or work["link_status"] != "correct"
            ):
                raise ExecutionBlocked("cluster hit lacks rubric ID or source evidence")
            _evidence(annotations, eval_root, work["cluster_evidence_id"])
            clusters.add(cluster)
    for claim in claims:
        if claim["work_id"] not in work_ids or claim["status"] not in {
            "supported",
            "partial",
            "contradicted",
            "unverifiable",
        }:
            raise ExecutionBlocked("invalid claim source or support state")
        if claim.get("locator_evidence_id"):
            _evidence(annotations, eval_root, claim["locator_evidence_id"])
        if claim["status"] != "unverifiable" and not claim.get("locator_evidence_id"):
            raise ExecutionBlocked("scored claim lacks source locator")
    for decision in decisions:
        if decision.get("reason_evidence_id"):
            _evidence(annotations, eval_root, decision["reason_evidence_id"])
    kinds = set()
    for search in searches:
        if search["state"] not in {
            "results",
            "zero-results",
            "backend-failure",
            "credential-failure",
            "rate-limited",
        }:
            raise ExecutionBlocked("unknown search outcome")
        _evidence(annotations, eval_root, search["evidence_id"])
        kinds.add(search["kind"])
    if not {"recent", "closest-work"}.issubset(kinds):
        raise ExecutionBlocked("recent and closest-work search evidence required")
    if annotations.get("stop_evidence_id"):
        _evidence(annotations, eval_root, annotations["stop_evidence_id"])
    cutoff_year = int(plan["subject_runtime"]["data_cutoff"][:4])
    year_verified_works = [
        work
        for work in works
        if work["identity_status"] == "correct"
        and work["link_status"] == "correct"
        and work.get("identity_evidence_id")
        and work.get("link_evidence_id")
        and isinstance(work.get("year"), int)
        and not isinstance(work["year"], bool)
        and work["year"] <= cutoff_year
    ]
    year_known = [work["year"] for work in year_verified_works]
    core = {
        key
        for key, anchor in anchor_ids.items()
        if anchor["anchor_type"] in {"core", "core-and-must-have"}
    }
    must = {
        key
        for key, anchor in anchor_ids.items()
        if anchor["anchor_type"] in {"must-have", "core-and-must-have"}
    }
    identity = {
        state: sum(w["identity_status"] == state for w in works)
        for state in ("correct", "incorrect", "unverifiable")
    }
    link = {
        state: sum(w["link_status"] == state for w in works)
        for state in ("correct", "incorrect", "unverifiable")
    }
    support = {
        state: sum(c["status"] == state for c in claims)
        for state in ("supported", "partial", "contradicted", "unverifiable")
    }
    seconds = sum(
        (
            datetime.fromisoformat(a["ended_at"])
            - datetime.fromisoformat(a["started_at"])
        ).total_seconds()
        for a in record["attempts"]
    )
    events = [
        read_json_line
        for a in record["attempts"]
        for read_json_line in _events(
            Path(capture_dir)
            / next(name for name in a["files"] if name.endswith(".jsonl"))
        )
    ]
    tool_items = [
        e["item"]
        for e in events
        if e.get("type") == "item.completed"
        and e.get("item", {}).get("type")
        in {"command_execution", "mcp_tool_call", "web_search", "file_change"}
    ]
    usage = [
        a["summary"]["usage"] for a in record["attempts"] if a["summary"].get("usage")
    ]
    facts = {
        "bibliographic_identity": dict(identity, total=len(works)),
        "identifier_or_link": dict(link, total=len(works)),
        "claim_support": dict(support, total=len(claims)),
        "central_source_mismatch": sum(
            bool(c.get("central_source_mismatch")) for c in claims
        ),
        "coverage": {
            "clusters_hit": len(clusters),
            "clusters_total": 6,
            "core_hit": len(hits & core),
            "core_total": len(core),
            "must_have_hit": len(hits & must),
            "must_have_total": len(must),
            "recent_works": sum(
                cutoff_year - 2 <= work["year"] <= cutoff_year
                for work in year_verified_works
            ),
            "year_confirmed_works": len(year_known),
            "latest_year": max(year_known, default=None),
        },
        "auditability": {
            "works_with_trace": sum(
                bool(w.get("discovery_evidence_id")) for w in works
            ),
            "works_total": len(works),
            "claims_with_locator": sum(
                bool(c.get("locator_evidence_id")) for c in claims
            ),
            "claims_total": len(claims),
            "decisions_with_reason": sum(
                bool(d.get("reason_evidence_id")) for d in decisions
            ),
            "decisions_total": len(decisions),
            "versions_with_access_date": sum(
                bool(w.get("source_version")) and bool(w.get("access_date"))
                for w in works
                if w.get("included")
            ),
            "included_works_total": sum(bool(w.get("included")) for w in works),
            "stop_decision_with_evidence": bool(annotations.get("stop_evidence_id")),
        },
    }
    efficiency = {
        "elapsed_seconds": round(seconds),
        "tool_calls": len(tool_items),
        "failed_tool_calls": sum(
            t.get("status") in {"failed", "declined"}
            or (isinstance(t.get("exit_code"), int) and t["exit_code"] != 0)
            for t in tool_items
        ),
        "human_interventions": annotations["human_interventions"],
        "retries": max(0, len(record["attempts"]) - 1),
        "tokens": sum(
            u.get("input_tokens", 0) + u.get("output_tokens", 0) for u in usage
        )
        if usage
        else None,
        "cost": annotations.get("actual_cost"),
    }
    return facts, efficiency


def _events(path):
    import json

    for line in path.read_bytes().splitlines():
        yield json.loads(line)


def make_result(annotations_path, holdout_path, plan_path, capture_dir, eval_root):
    from validators.holdout_manifest import canonical_sha256
    from validators.stage1_evaluation_result_v2 import validate_result_v2

    annotations = read_json(annotations_path)
    holdout = read_json(holdout_path)
    plan = read_json(plan_path)
    facts, efficiency = derive_facts(annotations, holdout, plan, capture_dir, eval_root)
    if facts["central_source_mismatch"] and not any(
        issue["code"] == "fabricated_or_mismatched_evidence"
        for issue in annotations["major_issues"]
    ):
        raise ExecutionBlocked(
            "central source mismatch must record the major-error gate"
        )
    record = verify_capture(capture_dir, verify_runtime=False)
    rel = (
        Path(annotations_path)
        .resolve()
        .relative_to(Path(eval_root).resolve())
        .as_posix()
    )
    if not rel.startswith("private/"):
        raise ExecutionBlocked("factual annotations must remain private")
    result = {
        "kind": "Stage1EvaluationResult",
        "schema_version": "2.0.0",
        "run_id": record["run_id"],
        "condition": record["condition"],
        "benchmark_version": holdout["manifest_id"],
        "metric_spec_version": (
            "stage1-primary-metrics-v2.1"
            if holdout["schema_version"] == "2.1.0"
            else "stage1-primary-metrics-v2"
        ),
        "prompt_sha256": plan["bindings"]["prompt"]["artifact"]["sha256"],
        "capture_provenance": {
            "series_id": record["series_id"],
            "run_sha256": sha((Path(capture_dir) / "run.json").read_bytes()),
        },
        "fact_metrics": facts,
        "major_issues": annotations["major_issues"],
        "efficiency": efficiency,
        "artifacts": [
            {
                "type": "factual-evidence",
                "path": rel,
                "sha256": sha(Path(annotations_path).read_bytes()),
            }
        ],
        "evaluation_plan_sha256": canonical_sha256(plan),
        "holdout_sha256": canonical_sha256(holdout),
    }
    errors = validate_result_v2(result, holdout, plan)
    if errors:
        raise ExecutionBlocked("v2 result invalid: " + "; ".join(errors))
    return result
