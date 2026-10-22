"""Pure diagnostics for Stage 3 planning conditions and unknowns."""

from copy import deepcopy

from .contracts import Stage3Error, digest


_PHASES = (
    "question-definition",
    "material-design",
    "method-design",
    "validation-design",
    "resource-planning",
    "plan-review",
    "before-access-use",
)
_PHASE_INDEX = {phase: position for position, phase in enumerate(_PHASES)}
_LATEST_PHASE = {
    "question-meaning": "question-definition",
    "material-fit": "material-design",
    "method-assumption": "method-design",
    "validation-reference": "validation-design",
    "feasibility": "resource-planning",
    "other": "plan-review",
    "usage-conditions": "before-access-use",
}


def _issue(issues, code, path, message):
    issues.append({"code": code, "path": path, "message": message})


def _source_collection(container, field, path):
    if field not in container:
        return []
    rows = container[field]
    if not isinstance(rows, list):
        raise Stage3Error(f"{path} must be an array")
    return rows


def condition_sources(intake):
    """Return immutable-by-copy bindings for admitted condition source values."""

    if not isinstance(intake, dict):
        raise Stage3Error("intake must be an object")

    collections = [
        (
            "selection_conditions",
            _source_collection(intake, "selection_conditions", "/selection_conditions"),
        ),
        ("unresolved", _source_collection(intake, "unresolved", "/unresolved")),
    ]
    if "legacy_mapping" in intake:
        legacy_mapping = intake["legacy_mapping"]
        if not isinstance(legacy_mapping, dict):
            raise Stage3Error("/legacy_mapping must be an object")
    else:
        legacy_mapping = {}
    collections.append(
        (
            "packet_unresolved",
            _source_collection(
                legacy_mapping,
                "packet_unresolved",
                "/legacy_mapping/packet_unresolved",
            ),
        )
    )

    sources = []
    for collection, rows in collections:
        for position, value in enumerate(rows):
            sources.append(
                {
                    "condition_ref": f"{collection}/{position}",
                    "source_sha256": digest(value),
                    "value": deepcopy(value),
                }
            )
    return sources


def _unique_index(rows, key, collection, issues):
    index = {}
    for position, row in enumerate(rows):
        identifier = row[key]
        if identifier in index:
            _issue(
                issues,
                "duplicate-id",
                f"/{collection}/{position}/{key}",
                f"duplicate {key}: {identifier}",
            )
        else:
            index[identifier] = row
    return index


def condition_diagnostics(plan, *, intake=None):
    """Return deterministic condition diagnostics without authorizing execution."""

    if plan.get("schema_version") == "1.0.0":
        return {
            "issues": [],
            "blocked_questions": [],
            "resolution_schedule": [],
            "execution_authorized": False,
        }

    issues = []
    blocked_questions = set()
    questions = {row["question_ref"] for row in plan["questions"]}
    resources = {row["resource_id"] for row in plan["resources"]}
    unknowns = _unique_index(plan["unknowns"], "unknown_id", "unknowns", issues)
    dispositions = _unique_index(
        plan["condition_dispositions"],
        "condition_ref",
        "condition_dispositions",
        issues,
    )

    for position, unknown in enumerate(plan["unknowns"]):
        path = f"/unknowns/{position}"
        for question_ref in unknown["question_refs"]:
            if question_ref not in questions:
                _issue(
                    issues,
                    "missing-reference",
                    f"{path}/question_refs",
                    f"unknown question: {question_ref}",
                )
        for resource_id in unknown["resource_ids"]:
            if resource_id not in resources:
                _issue(
                    issues,
                    "missing-reference",
                    f"{path}/resource_ids",
                    f"unknown resource: {resource_id}",
                )

        latest = _LATEST_PHASE[unknown["kind"]]
        if _PHASE_INDEX[unknown["resolve_before"]] > _PHASE_INDEX[latest]:
            _issue(
                issues,
                "late-resolution-deadline",
                f"{path}/resolve_before",
                f"{unknown['kind']} must resolve no later than {latest}",
            )

        if unknown["blocking"] or unknown["scope_change_required"]:
            blocked_questions.update(unknown["question_refs"])

    for position, disposition in enumerate(plan["condition_dispositions"]):
        path = f"/condition_dispositions/{position}"
        for question_ref in disposition["question_refs"]:
            if question_ref not in questions:
                _issue(
                    issues,
                    "missing-reference",
                    f"{path}/question_refs",
                    f"unknown question: {question_ref}",
                )
        linked_unknowns = []
        for unknown_id in disposition["unknown_ids"]:
            unknown = unknowns.get(unknown_id)
            if unknown is None:
                _issue(
                    issues,
                    "missing-reference",
                    f"{path}/unknown_ids",
                    f"unknown unknown_id: {unknown_id}",
                )
            else:
                linked_unknowns.append(unknown)
                if unknown["blocking"] and not set(unknown["question_refs"]).issubset(
                    disposition["question_refs"]
                ):
                    _issue(
                        issues,
                        "blocking-unknown-question-mismatch",
                        f"{path}/question_refs",
                        f"condition omits a question blocked by {unknown_id}",
                    )

        condition_ref = disposition["condition_ref"]
        requires_blocking_unknown = condition_ref.startswith(
            ("unresolved/", "packet_unresolved/")
        )
        if requires_blocking_unknown and not any(
            unknown["blocking"] for unknown in linked_unknowns
        ):
            _issue(
                issues,
                "unresolved-source-unblocked",
                f"{path}/unknown_ids",
                "an unresolved source must link at least one blocking unknown",
            )

        if disposition["disposition"] in (
            "blocked",
            "requires-scope-decision",
        ):
            blocked_questions.update(disposition["question_refs"])

    if intake is not None:
        source_rows = condition_sources(intake)
        sources = {row["condition_ref"]: row for row in source_rows}
        for condition_ref in sorted(set(sources) - set(dispositions)):
            _issue(
                issues,
                "missing-condition-source",
                "/condition_dispositions",
                f"source has no disposition: {condition_ref}",
            )
        for condition_ref in sorted(set(dispositions) - set(sources)):
            _issue(
                issues,
                "unknown-condition-source",
                "/condition_dispositions",
                f"disposition has no source: {condition_ref}",
            )
        for position, disposition in enumerate(plan["condition_dispositions"]):
            source = sources.get(disposition["condition_ref"])
            if (
                source is not None
                and disposition["source_sha256"] != source["source_sha256"]
            ):
                _issue(
                    issues,
                    "condition-source-mismatch",
                    f"/condition_dispositions/{position}/source_sha256",
                    f"source digest changed for {disposition['condition_ref']}",
                )

    for question_position, question_plan in enumerate(plan["question_plans"]):
        question_ref = question_plan["question_ref"]
        if question_plan["blockers"]:
            blocked_questions.add(question_ref)
        for use_position, resource_use in enumerate(question_plan["resource_uses"]):
            if resource_use["status"] == "available":
                continue
            blocked_questions.add(question_ref)
            resource_id = resource_use["resource_id"]
            linked = any(
                unknown["blocking"]
                and question_ref in unknown["question_refs"]
                and resource_id in unknown["resource_ids"]
                for unknown in plan["unknowns"]
            )
            if not linked:
                _issue(
                    issues,
                    "unknown-resource-unlinked",
                    (
                        f"/question_plans/{question_position}/resource_uses/"
                        f"{use_position}"
                    ),
                    (
                        f"unavailable resource {resource_id} requires a linked "
                        "blocking unknown"
                    ),
                )

    schedule = sorted(
        (deepcopy(unknown) for unknown in plan["unknowns"]),
        key=lambda unknown: (
            _PHASE_INDEX[unknown["resolve_before"]],
            unknown["unknown_id"],
        ),
    )
    return {
        "issues": issues,
        "blocked_questions": sorted(blocked_questions),
        "resolution_schedule": schedule,
        "execution_authorized": False,
    }
