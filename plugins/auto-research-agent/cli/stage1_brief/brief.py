"""Replay scope decisions and bind a search plan to the reviewed brief bytes."""

from copy import deepcopy
from datetime import datetime
from pathlib import Path

from stage1_coverage.plan import compile_plan, quote, validate_bundle
from stage1_ledger.journal import LedgerError, canonical, decode, digest, write_new

VERSION = "1.0.0"
CHOICES = {"specified", "unrestricted", "not-applicable"}


def require(condition, message):
    if not condition:
        raise LedgerError("research-brief: " + message)


def has_text(value):
    return isinstance(value, str) and bool(value.strip())


def state(brief):
    require(brief.get("kind") == "ResearchBrief", "wrong kind")
    require(brief.get("schema_version") == VERSION, "unsupported version")
    require(
        has_text(brief.get("original_description")),
        "missing original description",
    )
    needs = brief.get("needs", [])
    require(
        bool(needs)
        and all(
            has_text(n.get("need_id")) and has_text(n.get("question")) for n in needs
        ),
        "missing knowledge needs",
    )
    require(len({n["need_id"] for n in needs}) == len(needs), "duplicate need")
    fields = brief.get("scope_fields", [])
    require(
        bool(fields) and len({f["field"] for f in fields}) == len(fields),
        "missing or duplicate scope field",
    )
    require(
        all(
            has_text(f.get("field"))
            and type(f.get("material")) is bool
            and has_text(f.get("reason"))
            for f in fields
        ),
        "scope materiality needs a reason",
    )
    require(
        "geography" in {f["field"] for f in fields},
        "geography applicability must be considered",
    )
    current = {
        f["field"]: {"status": "pending", "value": None, "event_id": None}
        for f in fields
    }
    ids = set()
    suggestions = {s["suggestion_id"]: s for s in brief.get("suggestions", [])}
    require(
        len(suggestions) == len(brief.get("suggestions", [])), "duplicate suggestion"
    )
    for suggestion in suggestions.values():
        require(
            suggestion.get("field") in current and has_text(suggestion.get("value")),
            "invalid suggested scope",
        )
        require(
            all(
                has_text(suggestion.get(k))
                for k in (
                    "literature_basis",
                    "data_basis",
                    "validation_basis",
                )
            ),
            "recommendation lacks feasibility evidence",
        )
        refs = suggestion.get("source_refs")
        require(
            isinstance(refs, list) and bool(refs) and all(has_text(r) for r in refs),
            "recommendation lacks feasibility evidence: source refs",
        )
    for event in brief.get("decisions", []):
        require(
            event.get("event_id") and event["event_id"] not in ids,
            "duplicate decision event",
        )
        ids.add(event["event_id"])
        field = event.get("field")
        require(field in current, "unknown scope field")
        require(
            event.get("status") in CHOICES | {"pending", "recommendations-requested"},
            "invalid scope status",
        )
        require(
            all(has_text(event.get(k)) for k in ("actor", "source_ref", "recorded_at")),
            "decision lacks provenance",
        )
        try:
            timestamp = datetime.fromisoformat(
                event["recorded_at"].replace("Z", "+00:00")
            )
            require(
                timestamp.utcoffset() is not None, "decision timestamp lacks timezone"
            )
        except (ValueError, TypeError) as error:
            raise LedgerError("research-brief: invalid provenance timestamp") from error
        require(has_text(event.get("user_input")), "decision lacks verbatim user input")
        # This is an auditable operator attestation, not authentication of a person.
        require(
            event.get("authority") == "user", "system suggestions cannot decide scope"
        )
        if event["status"] == "specified":
            require(
                isinstance(event.get("value"), str) and bool(event["value"].strip()),
                "specified scope lacks value",
            )
        else:
            require(
                event.get("value") is None,
                "non-specific choice cannot hide a restriction",
            )
        if event["status"] == "not-applicable":
            require(
                has_text(event.get("reason")), "non-applicable scope needs a reason"
            )
        if event.get("selected_suggestion"):
            selected = suggestions.get(event["selected_suggestion"])
            require(
                selected
                and selected["field"] == field
                and selected["value"] == event["value"],
                "selection differs from suggestion",
            )
        current[field] = {k: event[k] for k in ("status", "value", "event_id")}
    return current


def validate_brief(brief, *, require_confirmed=False):
    current = state(brief)
    unresolved = [
        f["field"]
        for f in brief["scope_fields"]
        if f["material"] and current[f["field"]]["status"] not in CHOICES
    ]
    # Non-material geography may remain broad; a reason is still preserved.
    if require_confirmed:
        require(
            not unresolved,
            "necessary clarification incomplete: " + ", ".join(unresolved),
        )
    decisions = brief.get("decisions", [])
    return {
        "valid": True,
        "scope": current,
        "necessary_clarification_complete": not unresolved,
        "pending_fields": unresolved,
        "scope_decision_traceability": {
            "recorded": len(decisions),
            "total": len(decisions),
            "ratio": 1.0 if decisions else None,
        },
        "note": "Recorded provenance is not independent proof of user identity or semantic scope interpretation.",
    }


def create_brief(request, output, previous=None):
    brief = deepcopy(request)
    brief.update(kind="ResearchBrief", schema_version=VERSION)
    if previous is not None:
        raw = Path(previous).read_bytes()
        old = decode(raw, str(previous))
        validate_brief(old)
        require(
            brief["original_description"] == old["original_description"],
            "original description cannot be rewritten",
        )
        for key in ("decisions", "suggestions"):
            require(
                brief.get(key, [])[: len(old.get(key, []))] == old.get(key, []),
                "history must be append-only: " + key,
            )
        brief["previous_sha256"] = digest(raw)
    else:
        require(
            not brief.get("previous_sha256"), "new brief cannot invent prior history"
        )
        brief["previous_sha256"] = None
    report = validate_brief(brief)
    write_new(Path(output), canonical(brief) + b"\n")
    return report


def validate_search_request(brief, request):
    current = validate_brief(brief, require_confirmed=True)["scope"]
    proposal = request["proposal"]
    families = {
        f["family_id"] for c in proposal["clusters"] for f in c["query_families"]
    }
    mappings = request["query_bindings"]
    require(
        len(mappings) == len(families)
        and {r["family_id"] for r in mappings} == families,
        "each query family needs a need/scope mapping",
    )
    needs = {n["need_id"] for n in brief["needs"]}
    for row in mappings:
        require(
            bool(row.get("need_ids")) and set(row["need_ids"]).issubset(needs),
            "query family has no known research need",
        )
        require(
            row.get("purpose") in {"study-evidence", "transferable-method"},
            "query purpose missing",
        )
        require(
            set(row.get("scope_filters", {})).issubset(current),
            "unknown query scope field",
        )
        for field, value in row.get("scope_filters", {}).items():
            require(isinstance(value, str) and value.strip(), "empty scope filter")
            choice = current[field]
            # Comparator geography is evidence location, never the study population.
            if field == "geography" and row["purpose"] == "transferable-method":
                require(
                    has_text(row.get("transfer_rationale")),
                    "comparator needs a transfer rationale",
                )
                continue
            require(
                choice["status"] == "specified" and value == choice["value"],
                "unauthorized scope narrowing: " + field,
            )
    return {
        "unauthorized_scope_narrowing_count": 0,
        "query_families_mapped": len(mappings),
        **validate_brief(brief),
    }


def scoped_proposal(request, brief_sha256):
    """Apply declared filters to actual topical, recent and adversarial queries."""
    proposal = deepcopy(request["proposal"])
    proposal["plan_id"] += "-brief-" + digest(canonical([brief_sha256, request]))[:16]
    bindings = {r["family_id"]: r for r in request["query_bindings"]}
    existing = {c["concept_id"] for c in proposal["concepts"]}
    for cluster in proposal["clusters"]:
        for family in cluster["query_families"]:
            filters = bindings[family["family_id"]].get("scope_filters", {})
            for field, value in sorted(filters.items()):
                concept_id = (
                    "scope-" + digest(canonical([family["family_id"], field]))[:16]
                )
                require(concept_id not in existing, "scope concept collision")
                existing.add(concept_id)
                proposal["concepts"].append(
                    {"concept_id": concept_id, "terms": [value]}
                )
                family["concept_ids"].append(concept_id)
                family["adversarial_queries"] = [
                    "(" + q + ") AND " + quote(value)
                    for q in family["adversarial_queries"]
                ]
    return proposal


def compile_confirmed(brief_path, request, output, *, as_of, actor):
    raw = Path(brief_path).read_bytes()
    brief = decode(raw, str(brief_path))
    metrics = validate_search_request(brief, request)
    result = compile_plan(
        scoped_proposal(request, digest(raw)), output, as_of=as_of, actor=actor
    )
    binding = {
        "kind": "ResearchBriefPlanBinding",
        "schema_version": VERSION,
        "brief_sha256": digest(raw),
        "request": request,
        "plan_manifest_sha256": digest(
            (Path(output) / "plan_manifest.json").read_bytes()
        ),
        "intake_metrics": metrics,
    }
    write_new(Path(output) / "research_brief.json", raw)
    write_new(Path(output) / "research_brief_binding.json", canonical(binding) + b"\n")
    return {**result, "research_brief_sha256": digest(raw), "intake_metrics": metrics}


def validate_bound_plan(directory, current_brief_path):
    root = Path(directory)
    report = validate_bundle(root)
    require(report["valid"], "invalid coverage plan: " + str(report["errors"]))
    binding = decode(
        (root / "research_brief_binding.json").read_bytes(), "scope binding"
    )
    require(
        binding.get("kind") == "ResearchBriefPlanBinding"
        and binding.get("schema_version") == VERSION,
        "invalid scope binding version",
    )
    raw = Path(current_brief_path).read_bytes()
    require(
        raw == (root / "research_brief.json").read_bytes()
        and digest(raw) == binding["brief_sha256"],
        "search plan belongs to a different brief revision",
    )
    require(
        digest((root / "plan_manifest.json").read_bytes())
        == binding["plan_manifest_sha256"],
        "coverage manifest changed",
    )
    plan = decode((root / "coverage_plan.json").read_bytes(), "coverage plan")
    require(
        plan["proposal"] == scoped_proposal(binding["request"], digest(raw)),
        "scope mapping references a different proposal",
    )
    metrics = validate_search_request(decode(raw, "brief"), binding["request"])
    require(metrics == binding["intake_metrics"], "intake metrics changed")
    return {"valid": True, "intake_metrics": metrics}
