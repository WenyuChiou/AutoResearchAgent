"""Pure navigation over one shared-lock overview; never execution authority.

Recorded counts describe retained observations, not completeness. In particular,
a checkpoint, operational coverage gate or valid package cannot accept research.
"""

import re

PHASES = ("scope", "planning", "query", "screening", "reading", "coverage", "delivery")
ACTIVE = {"intent-recorded", "queued", "running", "dispatching"}
UNCERTAIN = {"dispatch-unobserved", "execution-unknown", "failed-or-unknown"}


def _dict(value):
    return value if type(value) is dict else {}


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _hash(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _ref(value):
    return (
        type(value) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is not None
    )


def _rows(value):
    if value is None:
        return []
    if type(value) is dict:
        value = list(value.values())
    return (
        value if type(value) is list and all(type(v) is dict for v in value) else None
    )


def _offer(value):
    value = _dict(value)
    return _ref(value.get("offer_ref")) and _hash(value.get("offer_sha256"))


def _bound(value, binding, keys):
    return all(
        type(value.get(key)) is type(binding[key]) and value.get(key) == binding[key]
        for key in keys
    )


def project_progress(overview):
    """Return fixed navigation keys and fresh objects; read no files or services."""
    overview = _dict(overview)
    project = _dict(overview.get("project"))
    binding = {
        key: project.get(key)
        for key in ("project_ref", "revision", "input_version", "brief_sha256")
    }
    phases = {
        key: dict(phase_id=key, status="unknown", reason="unknown-state")
        for key in PHASES
    }
    result = dict(
        kind="ProjectStage1Progress",
        schema_version="1.0.0",
        binding=binding,
        phases=list(phases.values()),
        next_action=None,
        research_complete=False,
    )

    def phase(key, status, reason):
        phases[key].update(status=status, reason=reason)

    def next_action(key, target, reason):
        result["next_action"] = dict(phase_id=key, target=target, reason=reason)
        return result

    def hold(key, reason="uncertain-action", target="history"):
        phase(key, "held", reason)
        return next_action(key, target, reason)

    if not project:
        binding.update(dict.fromkeys(binding))
        return next_action("scope", "scope", "scope-required")
    valid = (
        _ref(binding["project_ref"])
        and len(binding["project_ref"]) <= 64
        and _count(binding["revision"]) is not None
        and type(binding["input_version"]) is int
        and binding["input_version"] > 0
        and _hash(binding["brief_sha256"])
    )
    if not valid:
        binding.update(dict.fromkeys(binding))
        return hold("scope", "unknown-state")
    stage = overview.get("stage1")
    models = overview.get("models")
    model_offers = overview.get("model_offers")
    for view, keys in (
        (stage, ("project_ref", "revision", "input_version")),
        (models, tuple(binding)),
        (model_offers, ("project_ref", "revision")),
    ):
        if view is None:
            continue
        if type(view) is not dict or any(key not in view for key in keys):
            return hold("query", "unknown-state")
        if not _bound(view, binding, keys):
            return hold("query", "stale-input")
    stage, models, model_offers = _dict(stage), _dict(models), _dict(model_offers)

    def model_offer(operation):
        if not _bound(model_offers, binding, ("project_ref", "revision")):
            return False
        return any(
            _offer(row)
            and row.get("operation") == operation
            and row.get("available") is True
            and _bound(row, binding, ("input_version", "brief_sha256"))
            for row in _rows(model_offers.get("offers")) or []
        )

    if project.get("status") == "execution-unknown":
        return hold("scope")
    if stage.get("stage1_status") == "stale-input":
        return hold("query", "stale-input")
    if stage.get("stage1_status") == "owner-reopen-required":
        return hold("query", "owner-reopen-required")
    queries = _dict(stage.get("query_execution"))
    sources = _dict(stage.get("source_execution"))
    coverage = _dict(stage.get("coverage_actions"))
    ledger = _dict(stage.get("ledger"))
    for name in ("blocking_unknown_count", "unknown_count"):
        if name in models:
            count = _count(models[name])
            if count is None:
                return hold("reading", "unknown-state")
            if count and (
                name == "blocking_unknown_count"
                or "blocking_unknown_count" not in models
            ):
                return hold("reading")
    active = None
    for key, jobs in (
        ("reading", models.get("active_jobs")),
        ("query", queries.get("jobs")),
        ("query", _dict(queries.get("query_history")).get("history")),
        ("reading", sources.get("jobs")),
    ):
        rows = _rows(jobs)
        if rows is None:
            return hold(key, "unknown-state")
        for row in rows:
            status = row.get("status")
            if type(status) is not str:
                return hold(key, "unknown-state")
            if status in UNCERTAIN:
                return hold(key)
            if status in ACTIVE and active is None:
                active = (
                    key,
                    "active-action",
                    "native"
                    if key == "reading" and jobs is models.get("active_jobs")
                    else "history",
                )
    if active:
        return hold(*active)
    if queries.get("status") in UNCERTAIN | ACTIVE or str(
        stage.get("stage1_status", "")
    ).startswith("query-action-"):
        return hold("query")
    if queries.get("status") == "unavailable-or-stale":
        return hold("query", "stale-input")
    if coverage.get("held") is True:
        return hold("coverage")
    if "held" in coverage and coverage["held"] is not False:
        return hold("coverage", "unknown-state")
    if ledger and (
        ledger.get("valid") is not True or not _hash(ledger.get("state_sha256"))
    ):
        return hold("query", "unknown-state")
    if "pending_actions" in ledger and type(ledger["pending_actions"]) is not list:
        return hold("query", "unknown-state")
    if ledger.get("pending_actions"):
        return hold("query")
    confirmed = _dict(project.get("intake_report")).get(
        "necessary_clarification_complete"
    )
    phase(
        "scope",
        "recorded"
        if confirmed is True
        else "required"
        if confirmed is False
        else "unknown",
        "scope-recorded" if confirmed is True else "scope-required",
    )
    plan = _dict(project.get("plan"))
    planned = _hash(plan.get("manifest_sha256"))
    phase(
        "planning",
        "recorded"
        if planned
        else "available"
        if model_offer("plan-search")
        else "required",
        "plan-recorded" if planned else "plan-required",
    )
    counts = _dict(ledger.get("counts"))
    works, decisions, claims = (
        _count(counts.get(key)) for key in ("works", "decisions", "claims")
    )
    query_count = _count(counts.get("queries"))
    query_reason = "query-permission-required"
    for field, reason in (
        ("authorization_offer", "query-permission-required"),
        ("bootstrap_offer", "query-bootstrap-required"),
        ("query_offer", "query-offered"),
    ):
        if _offer(queries.get(field)):
            query_reason = reason
    query_available = any(
        _offer(queries.get(field))
        for field in ("authorization_offer", "bootstrap_offer", "query_offer")
    )
    phase(
        "query",
        "partial"
        if query_count
        else "available"
        if query_available
        else "unknown"
        if ledger and query_count is None
        else "unconnected"
        if not queries
        else "required",
        "query-recorded" if query_count else query_reason,
    )
    phase(
        "screening",
        "unknown"
        if ledger and (works is None or decisions is None)
        else "recorded"
        if decisions
        else "available"
        if works
        else "required"
        if ledger
        else "unconnected",
        "screening-recorded" if decisions else "screening-required",
    )
    reading_available = (
        models.get("saved_reading_available") is True
        or stage.get("saved_records_connected") is True
        or model_offer("read-paper")
    )
    phase(
        "reading",
        "unknown"
        if ledger and claims is None
        else "partial"
        if claims
        else "available"
        if reading_available
        else "unconnected",
        "reading-partial" if claims else "reading-required",
    )
    gate = _dict(ledger.get("gate"))
    coverage_recorded = (
        gate.get("gate_name") == "stage1-coverage-readiness"
        and gate.get("outcome") == "pass"
        and gate.get("blocking_items") == []
        and ledger.get("next_allowed_action") == "stop-sufficient"
        and coverage.get("blockers") == []
    )
    coverage_offers = _rows(coverage.get("offers"))
    coverage_available = any(_offer(row) for row in coverage_offers or [])
    phase(
        "coverage",
        "recorded"
        if coverage_recorded
        else "unknown"
        if coverage_offers is None
        else "available"
        if coverage_available
        else "required"
        if coverage
        else "unconnected",
        "coverage-recorded" if coverage_recorded else "coverage-required",
    )
    delivery = _dict(stage.get("delivery"))
    saved = _dict(delivery.get("canonical_package"))
    if saved.get("status") in {"stale-input", "source-binding-failed"}:
        return hold("delivery", "stale-input")
    saved_binding = _dict(saved.get("binding"))
    saved_valid = (
        saved.get("status") == "saved-evidence-validated"
        and saved.get("artifact_kind") == "Stage1ResearchDeliverable"
        and _hash(saved.get("manifest_sha256"))
        and _hash(saved.get("records_sha256"))
        and _hash(saved.get("handoff_sha256"))
        and _ref(saved.get("artifact_ref"))
        and _bound(saved_binding, binding, ("input_version", "brief_sha256"))
        and type(project.get("project_id")) is str
        and saved_binding.get("project_id") == project["project_id"]
        and _hash(saved.get("ledger_state_sha256"))
        and saved.get("ledger_state_sha256") == ledger.get("state_sha256")
    )
    offers = _rows(delivery.get("offers")) or []
    delivery_available = any(
        _offer(row) and row.get("status") == "ready-for-saved-evidence-delivery"
        for row in offers
    )
    phase(
        "delivery",
        "partial"
        if saved_valid
        else "unknown"
        if saved
        else "available"
        if delivery_available
        else "required"
        if delivery
        else "unconnected",
        "package-saved-review-required"
        if saved_valid
        else "unknown-state"
        if saved
        else "delivery-offered"
        if delivery_available
        else "delivery-required",
    )
    if confirmed is not True:
        return next_action("scope", "scope", "scope-required")
    if not planned:
        return next_action("planning", "planning", "plan-required")
    if saved:
        return next_action(
            "delivery",
            "delivery" if saved_valid else "history",
            phases["delivery"]["reason"],
        )
    if not stage or not ledger:
        return next_action(
            "query",
            "query",
            query_reason if query_available else "query-unconnected",
        )
    if delivery_available or coverage_recorded:
        return next_action(
            "delivery",
            "delivery",
            "delivery-offered" if delivery_available else "delivery-required",
        )
    if None in (works, decisions, claims):
        return next_action("query", "history", "unknown-state")
    if not works:
        return next_action("query", "query", query_reason)
    if not decisions:
        return next_action("screening", "screening", "screening-required")
    if not claims:
        return next_action("reading", "reading", "reading-required")
    return next_action("coverage", "coverage", "coverage-required")
