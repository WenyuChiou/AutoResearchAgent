"""Replay references and derived records. This does not judge scientific truth."""

from datetime import datetime

from .contracts import check_manifest, check_payload, check_record
from .identity import candidate_revision, work_key
from .journal import Journal, LedgerError, canonical, contained, decode, digest
from .readiness import coverage_text, readiness
from .semantics import SUCCESS, claim_check, completion_count, query_fields
from .verification import comparison


COUNT_NAMES = (
    "queries",
    "backend_attempts",
    "backend_failures",
    "success_empty",
    "discoveries",
    "works",
    "candidate_revisions",
    "decisions",
    "claims",
)
META = {"schema_version", "event_id", "created_at"}


def require(condition, reason):
    if not condition:
        raise LedgerError(reason)


def validate_run(root):
    journal = Journal(root)
    counts = dict.fromkeys(COUNT_NAMES, 0)
    starts, finishes, queries, stored, works, decisions = {}, {}, {}, {}, {}, {}
    seen, expected_discoveries, material = set(), set(), []
    failed_extractions = set()
    comparisons = {}
    errors, pending = [], []
    state_sha256 = None

    def state_hash():
        return digest(canonical({"manifest": manifest, "events": material}))

    def read_ref(ref):
        require(
            stored.get(ref["artifact_id"]) == ref,
            f"unregistered-or-altered-artifact: {ref['path']}",
        )
        return journal.read_ref(ref)

    try:
        manifest = journal.manifest
        check_manifest(manifest)
        events = journal.reconcile(repair=False)
        contained(journal.root, "coverage_and_stop.md").read_bytes()
        for row in events:
            p = row["payload"]
            check_payload(p)
            kind, event_id = p["kind"], p["event_id"]
            if kind == "ActionStarted":
                if p["operation"] == "backend":
                    parent = starts.get(p["parent_id"])
                    require(
                        parent
                        and parent["operation"] == "search"
                        and p["parent_id"] not in queries
                        and p["backend"],
                        "invalid-backend-parent",
                    )
                    counts["backend_attempts"] += 1
                else:
                    require(
                        p["parent_id"] is None and p["backend"] is None,
                        "search-has-backend-parent",
                    )
                starts[event_id] = p
            elif kind == "ArtifactStored":
                ref = p["ref"]
                require(
                    ref["artifact_id"] not in stored, "duplicate-artifact-registration"
                )
                require(
                    ref["artifact_type"] in {"raw-output", "validator-report"},
                    "unknown-artifact-type",
                )
                require(
                    datetime.fromisoformat(ref["created_at"].replace("Z", "+00:00"))
                    <= datetime.fromisoformat(p["created_at"].replace("Z", "+00:00")),
                    "artifact-time-order",
                )
                if ref["artifact_type"] == "raw-output":
                    require(ref["producer"] in starts, "missing-artifact-producer")
                else:
                    require(
                        ref["producer"] == "stage1-validator",
                        "unknown-validator-producer",
                    )
                require(
                    ref["path"] == f"raw/{ref['sha256']}.bin",
                    "artifact-content-address",
                )
                require(
                    ref["artifact_id"] == "artifact-" + ref["sha256"],
                    "artifact-identity",
                )
                require(
                    0 <= p["bytes"] <= manifest["max_artifact_bytes"],
                    "artifact-size-limit",
                )
                data = journal.read_ref(ref)
                require(len(data) == p["bytes"], "artifact-byte-count")
                stored[ref["artifact_id"]] = ref
            elif kind == "ActionFinished":
                attempt = starts.get(p["attempt_id"])
                require(
                    attempt
                    and attempt["operation"] == "backend"
                    and p["attempt_id"] not in finishes,
                    "invalid-attempt-completion",
                )
                for ref in (p["stdout"], p["stderr"]):
                    read_ref(ref)
                require(
                    completion_count(p, read_ref) == p["result_count"],
                    "completion-count-mismatch",
                )
                finishes[p["attempt_id"]] = p
                if p["outcome"] not in SUCCESS:
                    counts["backend_failures"] += 1
                if p["outcome"] == "success_empty":
                    counts["success_empty"] += 1
            elif kind == "QueryEvent":
                query = starts.get(p["query_id"])
                require(
                    query
                    and query["operation"] == "search"
                    and p["query_id"] not in queries,
                    "invalid-query-completion",
                )
                children = [
                    s for s in starts.values() if s["parent_id"] == p["query_id"]
                ]
                require(
                    children and all(c["event_id"] in finishes for c in children),
                    "query-has-unfinished-backends",
                )
                child_ids = {c["event_id"] for c in children}
                completed = [
                    f for f in finishes.values() if f["attempt_id"] in child_ids
                ]
                expected = dict(
                    kind="QueryEvent", **query_fields(query, children, completed)
                )
                require(
                    {k: v for k, v in p.items() if k not in META} == expected,
                    "query-replay-mismatch",
                )
                for completion in completed:
                    expected_discoveries.update(
                        f"{completion['event_id']}:{index}"
                        for index in range(completion["result_count"])
                    )
                queries[p["query_id"]] = p
                counts["queries"] += 1
            elif kind == "ExtractionFailure":
                discovery_id = f"{p['completion_id']}:{p['record_index']}"
                require(
                    discovery_id in expected_discoveries
                    and discovery_id not in seen
                    and discovery_id not in failed_extractions,
                    "invalid-extraction-failure",
                )
                completion = next(
                    (
                        f
                        for f in finishes.values()
                        if f["event_id"] == p["completion_id"]
                    ),
                    None,
                )
                require(
                    completion and p["source_ref"] == completion["records"],
                    "extraction-failure-source",
                )
                record = decode(read_ref(p["source_ref"]), p["source_ref"]["path"])[
                    p["record_index"]
                ]
                actual_error = None
                try:
                    check_record(record)
                    work_key(record)
                except LedgerError as error:
                    actual_error = str(error)
                require(
                    actual_error == p["error"], "extraction-failure-replay-mismatch"
                )
                failed_extractions.add(discovery_id)
            elif kind == "CandidateRevision":
                discovery = p["discoveries"][-1]
                require(
                    discovery["discovery_id"] not in seen
                    and discovery["discovery_id"] in expected_discoveries,
                    "duplicate-or-unknown-discovery",
                )
                completion = finishes.get(discovery["attempt_id"])
                query = queries.get(discovery["query_id"])
                require(
                    completion
                    and query
                    and completion["event_id"] in query["completion_ids"],
                    "discovery-query-mismatch",
                )
                records = decode(
                    read_ref(completion["records"]), completion["records"]["path"]
                )
                require(discovery["record_index"] < len(records), "discovery-index")
                record = records[discovery["record_index"]]
                check_record(record)
                expected = candidate_revision(
                    works.get(p["work_id"]),
                    record=record,
                    completion=completion,
                    query_id=discovery["query_id"],
                    index=discovery["record_index"],
                )
                require(
                    {k: v for k, v in p.items() if k not in META} == expected,
                    "candidate-replay-mismatch",
                )
                seen.add(discovery["discovery_id"])
                works[p["work_id"]] = p
                counts["candidate_revisions"] += 1
            elif kind == "DecisionEvent":
                require(p["subject_id"] in works, "decision-unknown-work")
                require(
                    p["run_id"] == manifest["research_run"]["run_id"]
                    and p["stage_run_id"] == "stage1"
                    and p["sequence"] == row["sequence"],
                    "decision-run-sequence",
                )
                prior = decisions.get(p["subject_id"])
                require(
                    p["prior_decision"] == (prior["new_decision"] if prior else None)
                    and p["reverses_event_id"]
                    == (prior["event_id"] if prior else None),
                    "decision-history-mismatch",
                )
                for ref in p["evidence_refs"]:
                    read_ref(ref)
                if p["actor_type"] == "human":
                    require(
                        p["authorization"]["state_sha256"] == state_hash(),
                        "stale-human-authorization",
                    )
                decisions[p["subject_id"]] = p
                counts["decisions"] += 1
            elif kind == "ClaimEvidence":
                work = works.get(p["work_id"])
                require(
                    work and p["version_id"] in work["version_ids"],
                    "claim-unknown-version",
                )
                claim_check(p, read_ref)
                counts["claims"] += 1
            elif kind == "IdentityComparison":
                expected = comparison(
                    works,
                    starts,
                    comparisons,
                    read_ref,
                    target_work_id=p["target_work_id"],
                    target_discovery_id=p["target_discovery_id"],
                    reference_discovery_id=p["reference_discovery_id"],
                    resolver_ref=p["resolver_ref"],
                    assessor=p["assessor"],
                )
                require(
                    {k: v for k, v in p.items() if k not in META} == expected,
                    "identity-comparison-replay-mismatch",
                )
                comparisons[(p["target_work_id"], p["target_version_id"])] = p
            elif kind == "Checkpoint":
                result = p["stage_result"]
                require(
                    result["stage_run_id"] == "stage1" and result["outputs"] == [],
                    "checkpoint-stage-or-outputs",
                )
                report = decode(
                    read_ref(result["validator_report"]), "validator report"
                )
                require(
                    p["state_sha256"] == state_hash() == report["state_sha256"],
                    "checkpoint-state-mismatch",
                )
                current_counts = dict(counts, works=len(works), discoveries=len(seen))
                require(
                    report["counts"] == current_counts == result["metrics"],
                    "checkpoint-count-mismatch",
                )
                require(
                    report["pending_actions"]
                    == [i for i in starts if i not in finishes and i not in queries],
                    "checkpoint-pending-mismatch",
                )
                require(
                    report["missing_discoveries"]
                    == sorted(expected_discoveries - seen),
                    "checkpoint-extraction-mismatch",
                )
                require(
                    report["valid"] is True and report["errors"] == [],
                    "checkpoint-invalid-report",
                )
                require(
                    report["schema_version"] == "1.0.0"
                    and report["scientific_truth"] == "not-evaluated",
                    "checkpoint-report-contract",
                )
                gate, action = readiness(report)
                require(
                    result["gate"] == gate and result["next_allowed_action"] == action,
                    "checkpoint-gate-mismatch",
                )
                require(
                    result["status"]
                    == ("human-review" if action == "human-review" else "running"),
                    "checkpoint-status-mismatch",
                )
            if kind != "Checkpoint" and not (
                kind == "ArtifactStored"
                and p["ref"]["artifact_type"] == "validator-report"
            ):
                material.append(p)
        counts.update(works=len(works), discoveries=len(seen))
        checkpoints = [
            e["payload"] for e in events if e["payload"]["kind"] == "Checkpoint"
        ]
        expected_view = coverage_text(checkpoints[-1] if checkpoints else None)
        require(
            contained(journal.root, "coverage_and_stop.md").read_text(encoding="utf-8")
            == expected_view,
            "coverage-view-mismatch: use recover to rebuild derived view",
        )
        pending = [i for i in starts if i not in finishes and i not in queries]
        state_sha256 = state_hash()
    except (LedgerError, OSError, KeyError, TypeError, IndexError, ValueError) as error:
        errors.append(str(error))
        # Partial replay counts are not complete run denominators.
        counts = dict.fromkeys(COUNT_NAMES)
    return dict(
        schema_version="1.0.0",
        valid=not errors,
        errors=errors,
        counts=counts,
        pending_actions=pending,
        missing_discoveries=sorted(expected_discoveries - seen),
        state_sha256=state_sha256,
        scientific_truth="not-evaluated",
    )
