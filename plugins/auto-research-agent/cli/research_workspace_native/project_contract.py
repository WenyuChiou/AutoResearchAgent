"""Versioned UI projection, shared by current and future Harness stage adapters.

This is a presentation boundary, not a new rubric or an execution engine.
An adapter must supply source-bound evidence before exposing real completion.
Missing measurements remain null; reserved calls are distinct from actual use.
"""

from copy import deepcopy
import math

STAGES = {
    "1": (
        "literature-evidence",
        [
            "scope",
            "search-plan",
            "coverage-ledger",
            "source-notes",
            "canonical-delivery",
        ],
    ),
    "2": (
        "comparison-research-directions",
        [
            "source-handoff",
            "comparison",
            "candidate-routes",
            "independent-review",
            "selection-package",
        ],
    ),
    "3": ("design-feasibility", ["design", "feasibility-review"]),
    "4": ("experiment-execution", ["experiment-plan", "run-records"]),
    "5": ("analysis-figures", ["analysis", "figures"]),
    "6": ("writing-submission", ["manuscript", "submission-review"]),
}


def measurement(unit, *, value=None, status="unknown", evidence=()):
    """No implicit zero, synthetic-to-real promotion or score normalization."""
    if status not in {"unknown", "recorded", "stale", "partial", "failed"}:
        raise ValueError("measurement status differs")
    if value is not None and (
        type(value) not in (int, float) or not math.isfinite(value) or value < 0
    ):
        raise ValueError("nonnegative measured value required")
    if value is not None and status == "unknown":
        raise ValueError("unknown cannot have a measured value")
    return dict(
        value=value, unit=unit, status=status, evidence=deepcopy(list(evidence))
    )


def project_view(
    intake,
    credential,
    ref,
    *,
    models=None,
    stage1=None,
    stage2=None,
    stage1_delivery=None,
):
    """GET-only projection. Does not acquire a provider or derive new authority."""
    view = intake.read(credential, ref)
    identity = {
        key: view.get(key)
        for key in (
            "project_ref",
            "project_id",
            "revision",
            "input_version",
            "brief_sha256",
        )
    }
    identity["plan_manifest_sha256"] = (view.get("plan") or {}).get("manifest_sha256")
    model = models.read(credential, ref) if models is not None else None
    second = stage2.read(credential, ref) if stage2 is not None else None
    stages = {}
    for number, (name, outputs) in STAGES.items():
        stages[number] = dict(
            stage=number,
            name=name,
            input=deepcopy(identity),
            status="planned" if int(number) > 2 else "not-started",
            connected=False,
            execution_authorized=False,
            accepted=False,
            expected_outputs=outputs,
            artifacts=[],
            pending_questions=[],
            approvals=[],
            attempts=[],
            assessment=dict(status="not-evaluated", score=None, rubric_sha256=None),
            metrics={
                "actual_model_calls": measurement("calls"),
                "actual_search_calls": measurement("attempts"),
                "source_reads": measurement("reads"),
                "elapsed_seconds": measurement("seconds"),
                "input_tokens": measurement("tokens"),
                "output_tokens": measurement("tokens"),
                "monetary_cost": measurement("currency-unknown"),
            },
        )
    first = stages["1"]
    first["intake"] = dict(
        necessary_clarification_complete=(view.get("intake_report") or {}).get(
            "necessary_clarification_complete", False
        ),
        compiled_plan=identity["plan_manifest_sha256"] is not None,
        readiness=view.get("stage1_intake_ready", False),
        research_execution="unconnected",
    )
    if stage1 is not None:
        ledger = stage1.read(credential, ref)
        first["coverage_ledger"] = deepcopy(ledger)
        first["status"] = ledger["stage1_status"]
        # A checkpoint/export is not the validated canonical delivery package.
    if stage1_delivery is not None:
        delivery = stage1_delivery.read(credential, ref)
        first["saved_evidence_delivery"] = deepcopy(delivery)
        artifact = delivery["canonical_package"]
        if artifact is not None:
            first["artifacts"].append(deepcopy(artifact))
        # A structurally valid package with a continue gate is still incomplete.
        # Scientific acceptance never follows from a package hash or render.
    if model is not None:
        first["content_planning"] = deepcopy(model)
        first["metrics"]["model_calls_reserved"] = measurement(
            "reservations", value=model["calls_reserved"], status="recorded"
        )
        # Content planning is not a Stage1 search/read/delivery executor.
        first["attempts"] = deepcopy(model.get("jobs", []))
    queries = getattr(stage1, "query_service", None)
    if queries is not None:
        query = queries.read(credential, ref)
        first["search_execution"] = deepcopy(query)
        first["connected"] = True
        first["execution_authorized"] = query["execution_authorized"]
        first["intake"]["research_execution"] = "explicit-planned-query-only"
        first["attempts"].extend(deepcopy(query["jobs"]))
        history = (query.get("query_history") or {}).get("history", [])
        first["attempts"].extend(deepcopy(history))
        budget = query.get("budget")
        if budget is not None:
            for name, unit, field in (
                ("search_attempts_reserved", "reservations", "attempts"),
                ("runtime_probes_reserved", "reservations", "probes"),
                ("search_seconds_reserved", "seconds", "seconds"),
            ):
                first["metrics"][name] = measurement(
                    unit,
                    value=budget[field],
                    status="recorded",
                    evidence=[query.get("permit_sha256")],
                )
        observed = [
            row
            for row in history
            if row["status"] == "completed"
            and (row.get("result") or {}).get("execution_ref")
        ]
        if observed:
            # Count only saved runner receipts. Unknown attempts remain separate;
            # a backend attempt is not its provider's HTTP request or cost count.
            first["metrics"]["actual_search_calls"] = measurement(
                "backend-attempts",
                value=len(observed),
                status="partial"
                if any(row["status"] != "completed" for row in history)
                else "recorded",
                evidence=[row["result"]["execution_ref"] for row in observed],
            )
    if second is not None:
        activation = second.get("activation")
        stages["2"]["source_activation"] = deepcopy(activation)
        stages["2"]["offers"] = deepcopy(second.get("offers", []))
        if activation is not None:
            stages["2"]["status"] = activation["stage2_status"]
        stages["2"]["assessment"]["route"] = "stage2-general-v3/daily_v3"
    return dict(
        kind="HarnessUiProjectView",
        schema_version="1.1.0" if type(identity["input_version"]) is str else "1.0.0",
        identity=identity,
        stages=stages,
        resources=deepcopy(view.get("settings")),
        automatic_resend=False,
        completion_rule="explicit-source-bound-stage-acceptance",
        future_adapter_requirements=[
            "same-project-and-input-version",
            "immutable-source-and-artifact-hashes",
            "durable-intent-before-execution",
            "server-bound-questions-and-approvals",
            "no-replay-of-unknown-attempts",
            "explicit-permit-and-bounded-resources",
            "retained-failure-and-stale-history",
            "independent-assessment-with-original-rubric",
        ],
    )
