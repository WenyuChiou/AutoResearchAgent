"""Explicit topic revision archives settled query ownership without refunding it.

The old brief is still current while this guard runs. Reads never restore an
owner. A legacy project already revised with a used stale seal remains held;
this helper does not manufacture historical execution or adopt that ledger.
"""

from copy import deepcopy
import json

from stage1_deliverable.common import canonical, sha
from .planned_query_contract import require
from .project_model_recovery import retired
from .project_query_permit import inspect_seal
from .project_resource_budget import query_resources, resource_view


def current_budget(intake, state, principal):
    rows, intents = query_resources(intake, state, principal)
    budget = dict(probes=0, attempts=0, seconds=0)
    for digest, (seconds, _, basis) in rows.items():
        if basis["input_version"] != state["input_version"]:
            continue
        budget[
            "probes"
            if intents[digest]["kind"] == "stage1-query-bootstrap"
            else "attempts"
        ] += 1
        budget["seconds"] += seconds
    return budget


def archived_versions(intake, state):
    events = [
        json.loads(event[0])
        for event in intake.db.execute(
            "SELECT payload FROM intake_events WHERE project=? AND kind=?",
            (state["project_ref"], "revise-saved"),
        )
    ]
    versions = state.get("stage1_query_versions", {})
    require(
        len(versions) == sum("archived_query_scope_sha256" in event for event in events)
        and {sha(canonical(row)) for row in versions.values()}
        == {
            event["archived_query_scope_sha256"]
            for event in events
            if "archived_query_scope_sha256" in event
        },
        "project-query-version-archive-history-differs",
    )
    result = []
    for digest, row in versions.items():
        require(
            digest == row["authorization"]["sha256"]
            and row["input_version"] < state["input_version"],
            "project-query-version-archive-differs",
        )
        require(
            any(
                saved.get("request_sha256") == row["revise_request_sha256"]
                and saved.get("archived_query_scope_sha256") == sha(canonical(row))
                for saved in events
            ),
            "project-query-version-archive-history-differs",
        )
        result.append(
            dict(
                input_version=row["input_version"],
                brief_sha256=row["brief_sha256"],
                permit_sha256=digest,
                budget=deepcopy(row["budget"]),
                run_ref=row["run_ref"],
                jobs=[
                    {
                        key: deepcopy(job[key])
                        for key in (
                            "key",
                            "status",
                            "request_sha256",
                            "permit_sha256",
                            "receipt",
                            "error",
                            "automatic_retry",
                        )
                        if key in job
                    }
                    for job in row["jobs"].values()
                ],
                execution_authorized=False,
                automatic_retry=False,
            )
        )
    return result


def check_revision(queries, credential, state, *, request_hash=None):
    """Run under intake lock before the revision intent and again before close."""
    require(not queries.closing, "project-query-service-closing")
    principal = queries.intake._principal(credential)
    ref = state["project_ref"]
    for raw in queries.intake.db.execute(
        "SELECT receipt FROM intake_actions WHERE principal=? AND project=?",
        (principal, ref),
    ):
        saved = json.loads(raw[0])
        require(
            saved["status"] in {"saved", "failed", "known-unsent"}
            or request_hash is not None
            and saved.get("kind") == "revise"
            and saved.get("request_sha256") == request_hash
            and saved["status"] == "intent-recorded",
            "project-query-revision-unsettled",
        )
    for job in state.get("model_operations", {}).get("jobs", {}).values():
        require(
            not job.get("close_failure")
            and (
                job["status"]
                in {
                    "content-review-pending",
                    "plan-validated-not-executed",
                    "validation-failed",
                }
                or retired(job)
            ),
            "project-query-revision-unsettled",
        )
    for job in state.get("stage1_source_operations", {}).get("jobs", {}).values():
        require(
            job["status"]
            in {"source-observation-saved", "failed-observed", "refused-known-unsent"}
            and (
                job.get("followup") is None
                or job["followup"].get("status") == "source-core-registered"
            ),
            "project-query-revision-unsettled",
        )
        require(
            not (
                job["status"] == "source-observation-saved"
                and job.get("binding", {}).get("pipeline_sha256")
                and job.get("result", {}).get("body_complete") is not False
            )
            or (job.get("followup") or {}).get("status") == "source-core-registered",
            "project-query-revision-unsettled",
        )
    archived_versions(queries.intake, state)
    authorization = state.get("stage1_query_authorization")
    if authorization is None:
        return
    binding, _ = inspect_seal(
        queries.intake, ref, authorization, queries.config, ready=False
    )
    require(
        binding["input_version"] == state["input_version"],
        "project-query-revision-input-differs",
    )
    resource_view(queries.intake, state, principal)
    from .project_query_history import reserved_intents

    permit = authorization["permit"]
    reserved_intents(
        queries.intake,
        state,
        principal,
        permit["limits"],
        permit["limits"]["timeout_seconds"],
    )
    worker = queries.workers.get(ref)
    jobs = list(state.get("stage1_query_jobs", {}).values())
    require(
        (worker is None or not worker.is_alive())
        and all(job["status"] in {"completed", "refused-known-unsent"} for job in jobs),
        "project-query-revision-unsettled",
    )
    if jobs:
        observations = queries.intake.db.execute(
            "SELECT payload FROM intake_events WHERE project=? AND kind=?",
            (ref, "stage1-query-bootstrap-observation"),
        ).fetchall()
        require(
            len(jobs) == 1
            and jobs[0]["permit_sha256"] == authorization["sha256"]
            and any(json.loads(raw[0]) == jobs[0] for raw in observations),
            "project-query-revision-bootstrap-history-differs",
        )
        if jobs[0]["status"] == "completed":
            service = queries.services.get(ref)
            require(service is not None, "project-query-revision-owner-required")
            require(
                not service._closing
                and not service._closed
                and not any(worker.is_alive() for worker in service._workers.values()),
                "project-query-revision-unsettled",
            )
            service.inspect_saved(credential, ref)


def archive_revision(queries, credential, state, request_hash):
    check_revision(queries, credential, state, request_hash=request_hash)
    authorization = state.get("stage1_query_authorization")
    if authorization is None:
        return None
    ref = state["project_ref"]
    row = dict(
        input_version=state["input_version"],
        brief_sha256=queries.intake._brief(state)[0]["sha256"],
        authorization=deepcopy(authorization),
        jobs=deepcopy(state.get("stage1_query_jobs", {})),
        budget=current_budget(
            queries.intake, state, queries.intake._principal(credential)
        ),
        run_ref=state.get("stage1_active"),
        revise_request_sha256=request_hash,
    )
    versions = state.setdefault("stage1_query_versions", {})
    require(
        authorization["sha256"] not in versions,
        "project-query-version-already-archived",
    )
    service = queries.services.get(ref)
    if service is not None:
        try:
            service.close()
        finally:
            if service._closed:
                queries.services.pop(ref, None)
    versions[authorization["sha256"]] = row
    state.pop("stage1_query_authorization", None)
    state.pop("stage1_query_jobs", None)
    # Keep the lifetime budget, all run/expansion maps, immutable files and DB
    # events/actions. A new input requires new settings/plan and an explicit seal.
    return sha(canonical(row))
