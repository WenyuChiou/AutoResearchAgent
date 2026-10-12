"""Read all saved screening candidates without manufacturing reading evidence.

This companion is not Stage1ResearchRecords or a canonical source package. Core
snapshots, discovery metadata and actual decisions remain bound to one validated
run. Reading, source availability and scientific acceptance stay separate.
"""

from copy import deepcopy

from stage1_deliverable.common import sha
from stage1_ledger.contracts import check
from stage1_ledger.handoff import snapshots
from stage1_ledger.journal import canonical, contained

from .project_stage1 import ProjectStage1Service, _basis
from .session_api import _check, _hash

MAX_PROJECTION_BYTES = 16 * 1024 * 1024
FAILURE_OUTCOMES = {
    "unavailable",
    "not_found",
    "rate_limited",
    "http_error",
    "network_error",
    "parse_error",
    "interrupted",
}


def _journal_hash(ledger):
    return sha(contained(ledger.root, "stage_events.jsonl").read_bytes())


def _queries(events):
    """Preserve unsuccessful backend attempts too, not only discovery producers."""
    finishes = {p["attempt_id"]: p for p in events if p["kind"] == "ActionFinished"}
    results = {p["query_id"]: p for p in events if p["kind"] == "QueryEvent"}
    return [
        dict(
            started=deepcopy(query),
            result=deepcopy(results.get(query["event_id"])),
            backend_attempts=[
                dict(
                    started=deepcopy(p), finished=deepcopy(finishes.get(p["event_id"]))
                )
                for p in events
                if p["kind"] == "ActionStarted"
                and p["operation"] == "backend"
                and p["parent_id"] == query["event_id"]
            ],
        )
        for query in events
        if query["kind"] == "ActionStarted" and query["operation"] == "search"
    ]


def _rows(candidates, claims, decisions, events, coverage, queries):
    event_index = {p["event_id"]: p for p in events}
    query_index = {row["started"]["event_id"]: row for row in queries}
    discoveries = sorted(
        (d for c in candidates for d in c["discoveries"]),
        key=lambda d: (int(d["completion_id"][1:]), d["record_index"]),
    )
    order = {d["discovery_id"]: i for i, d in enumerate(discoveries, 1)}
    current_reviews = coverage.evidence.current()
    rows = []
    for candidate in candidates:
        work = candidate["work_id"]
        history = [deepcopy(p) for p in decisions if p["subject_id"] == work]
        work_claims = [deepcopy(p) for p in claims if p["work_id"] == work]
        review = current_reviews.get(work)
        selected = (
            review["version_id"]
            if review
            else candidate["discoveries"][-1]["version_id"]
        )
        observed = []
        for discovery in candidate["discoveries"]:
            query = event_index[discovery["query_id"]]
            observed.append(
                dict(
                    deepcopy(discovery),
                    candidate_discovery_order_in_run=order[discovery["discovery_id"]],
                    result_position=discovery["record_index"] + 1,
                    completion_created_at=event_index[discovery["completion_id"]][
                        "created_at"
                    ],
                    round_number=query["arguments"]
                    .get("coverage", {})
                    .get("round_number"),
                )
            )
        query_ids = {d["query_id"] for d in observed}
        rounds = {d["round_number"] for d in observed if d["round_number"] is not None}
        sources = [
            dict(
                started=deepcopy(p),
                finished=deepcopy(
                    next(
                        (
                            f
                            for f in events
                            if f["kind"] == "SourceReadFinished"
                            and f["attempt_id"] == p["event_id"]
                        ),
                        None,
                    )
                ),
            )
            for p in events
            if p["kind"] == "SourceReadStarted" and p["work_id"] == work
        ]
        imports = [
            dict(
                started=deepcopy(p),
                artifacts=[
                    deepcopy(a["ref"])
                    for a in events
                    if a["kind"] == "ArtifactStored"
                    and a["ref"]["producer"] == p["event_id"]
                ],
            )
            for p in events
            if p["kind"] == "SourceImportStarted" and p["work_id"] == work
        ]
        latest_source = next(
            (s for s in reversed(sources) if s["started"]["version_id"] == selected),
            None,
        )
        selected_imports = [
            p for p in imports if p["started"]["version_id"] == selected
        ]
        selected_claims = [p for p in work_claims if p["version_id"] == selected]
        rows.append(
            dict(
                work_id=work,
                candidate_event_id=candidate["event_id"],
                candidate_revision=candidate["revision"],
                canonical_key=candidate["canonical_key"],
                identity_status=candidate["identity_status"],
                metadata_evidence_level=candidate["evidence_level"],
                selected_version_id=selected,
                metadata=deepcopy(
                    next(
                        d["record"]
                        for d in reversed(observed)
                        if d["version_id"] == selected
                    )
                ),
                versions=[
                    dict(
                        version_id=v,
                        discovery_ids=[
                            d["discovery_id"] for d in observed if d["version_id"] == v
                        ],
                    )
                    for v in candidate["version_ids"]
                ],
                discoveries=observed,
                query_history=[
                    deepcopy(query_index[q])
                    for q in sorted(query_ids, key=lambda value: int(value[1:]))
                ],
                current_decision=deepcopy(history[-1]) if history else None,
                screening_status=history[-1]["new_decision"]
                if history
                else "not-screened",
                decision_history=history,
                source_attempts=sources,
                source_imports=imports,
                source_status=(
                    "not-acquired"
                    if not selected_imports
                    else "saved-import-bytes-recorded"
                    if any(p["artifacts"] for p in selected_imports)
                    else "saved-import-intent-recorded"
                )
                if latest_source is None
                else (
                    "pending"
                    if latest_source["finished"] is None
                    else latest_source["finished"]["outcome"]
                ),
                claims=work_claims,
                current_review=deepcopy(review),
                relevance=dict(
                    score=None,
                    status="Unknown",
                    basis="no-relevance-assessment-in-core-snapshot",
                ),
                reading=dict(
                    status="claim-evidence-recorded"
                    if selected_claims
                    else "no-reading-evidence-recorded",
                    selected_version_claim_count=len(selected_claims),
                    model_execution="Unknown",
                    complete_body_reading="Unknown",
                ),
                counts=dict(
                    discoveries=len(observed),
                    distinct_queries=len(query_ids),
                    discovery_producing_backend_attempts=len(
                        {d["attempt_id"] for d in observed}
                    ),
                    query_backend_attempts=sum(
                        len(query_index[q]["backend_attempts"]) for q in query_ids
                    ),
                    recorded_rounds=len(rounds),
                    round_ids_known=all(
                        d["round_number"] is not None for d in observed
                    ),
                    decisions=len(history),
                    reversals=sum(p["reverses_event_id"] is not None for p in history),
                    source_attempts=len(sources),
                    claims=len(work_claims),
                ),
                first_candidate_discovery_order_in_run=min(
                    order[d["discovery_id"]] for d in observed
                ),
            )
        )
    return sorted(rows, key=lambda row: row["first_candidate_discovery_order_in_run"])


def _project(project_ref, binding, run, ledger, report):
    events = [row["payload"] for row in ledger.events()]
    core = snapshots(ledger.manifest, report["state_sha256"], events)
    checkpoints = [p for p in events if p["kind"] == "Checkpoint"]
    checkpoint = checkpoints[-1] if checkpoints else None
    current = (
        checkpoint is not None and checkpoint["state_sha256"] == report["state_sha256"]
    )
    refs = checkpoint["stage_result"]["outputs"][:3] if current else []
    projected = []
    for i, value in enumerate(core):
        check(value, value["kind"])
        raw = canonical(value)
        if refs:
            _check(
                ledger.read_ref(refs[i]) == raw,
                "stage1-library-checkpoint-bytes-differ",
            )
        projected.append(
            dict(
                deepcopy(value),
                sha256=sha(raw),
                persisted_refs=[deepcopy(refs[i])] if refs else [],
                origin="core-snapshot-read-only",
            )
        )
    queries = _queries(events)
    rows = _rows(
        core[0]["rows"],
        core[1]["rows"],
        core[2]["rows"],
        events,
        ledger.coverage_state(),
        queries,
    )
    return dict(
        kind="Stage1ScreeningLibrary",
        schema_version="1.0.0",
        binding=dict(
            _basis(binding),
            project_ref=project_ref,
            run_ref=run["run_ref"],
            run_id=ledger.manifest["research_run"]["run_id"],
            manifest_sha256=run["manifest_sha256"],
            ledger_state_sha256=report["state_sha256"],
            journal_sha256=_journal_hash(ledger),
        ),
        snapshots=projected,
        rows=rows,
        query_history=queries,
        counts=dict(
            core=deepcopy(report["counts"]),
            total_candidates=len(rows),
            query_intents=len(queries),
            completed_queries=sum(q["result"] is not None for q in queries),
            include=sum(r["screening_status"] == "include" for r in rows),
            exclude=sum(r["screening_status"] == "exclude" for r in rows),
            pending=sum(r["screening_status"] == "pending" for r in rows),
            not_screened=sum(r["screening_status"] == "not-screened" for r in rows),
            source_attempts=sum(len(r["source_attempts"]) for r in rows),
            source_pending=sum(
                s["finished"] is None for r in rows for s in r["source_attempts"]
            ),
            source_failures=sum(
                s["finished"] is not None
                and s["finished"]["outcome"] in FAILURE_OUTCOMES
                for r in rows
                for s in r["source_attempts"]
            ),
        ),
        coverage=deepcopy(report.get("coverage")),
        checkpoint=None
        if checkpoint is None
        else dict(
            event_id=checkpoint["event_id"],
            current=current,
            outputs=deepcopy(checkpoint["stage_result"]["outputs"]),
        ),
        status="partial-saved-screening",
        stage1_complete=False,
        canonical_package=None,
        execution_authorized=False,
        evaluation_status="not-scored",
    )


class ProjectStage1LibraryService:
    """Authenticated read-only projection over the attached Stage1 service."""

    def __init__(self, stage1):
        _check(isinstance(stage1, ProjectStage1Service), "stage1-service-required")
        self.stage1, self.intake = stage1, stage1.intake

    def read(
        self,
        credential,
        project_ref,
        *,
        expected_input_version=None,
        expected_ledger_state_sha256=None,
        expected_projection_sha256=None,
    ):
        _check(
            expected_input_version is None
            or type(expected_input_version) is int
            and expected_input_version > 0,
            "stage1-library-input-version-invalid",
            400,
        )
        for value in (expected_ledger_state_sha256, expected_projection_sha256):
            _check(
                value is None or _hash(value),
                "stage1-library-expected-hash-invalid",
                400,
            )
        principal = self.intake._principal(credential)
        with self.intake._lock:
            state = self.intake._load(principal, project_ref)
            _check(
                expected_input_version is None
                or state["input_version"] == expected_input_version,
                "stage1-library-input-version-stale",
            )
            binding = self.intake.binding(project_ref)
            run = state.get("stage1_runs", {}).get(state.get("stage1_active"))
            _check(run is not None, "stage1-ledger-not-initialized")
            _check(
                not run.get("query_owned")
                or getattr(self.stage1, "query_service", None) is not None,
                "stage1-query-owner-unconnected",
            )
            run, ledger, report = self.stage1._ledger(state, binding)
            _check(
                expected_ledger_state_sha256 is None
                or report["state_sha256"] == expected_ledger_state_sha256,
                "stage1-library-ledger-state-stale",
            )
            journal_hash = _journal_hash(ledger)
            projection = _project(project_ref, binding, run, ledger, report)
            raw = canonical(projection)
            _check(
                len(raw) <= MAX_PROJECTION_BYTES,
                "stage1-library-complete-projection-bound-exceeded",
            )
            digest = sha(raw)
            _check(
                expected_projection_sha256 is None
                or digest == expected_projection_sha256,
                "stage1-library-projection-stale",
            )
            # Include full journal bytes: checkpoint/artifact events can change
            # without changing the Core semantic state. Never repair on GET.
            after = self.intake._load(principal, project_ref)
            fresh_binding = self.intake.binding(project_ref)
            fresh_run, fresh_ledger, fresh_report = self.stage1._ledger(
                after, fresh_binding
            )
            _check(
                after == state
                and _basis(fresh_binding) == _basis(binding)
                and fresh_run == run
                and fresh_report["state_sha256"] == report["state_sha256"]
                and _journal_hash(fresh_ledger) == journal_hash
                and projection["binding"]["journal_sha256"] == journal_hash,
                "stage1-library-frontier-changed",
            )
            return dict(
                kind="Stage1ScreeningLibraryEnvelope",
                schema_version="1.0.0",
                project_ref=project_ref,
                input_version=state["input_version"],
                projection_sha256=digest,
                projection=projection,
            )
