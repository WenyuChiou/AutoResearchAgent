"""Recompute Stage 2 delivery completeness without granting scientific authority."""

from html import escape

from stage2_check.contracts import latest_candidates, validate_assessment
from stage2_common import Stage2Error, canonical_hash, current_prior_work_reviews
from stage2_ideation.topic_tables import validate_research_tables
from stage2_eval.evaluation import validate_action_record


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def derive_content_gate(selection):
    """Inspect already source-validated selection records, not research truth.

    Callers must validate source bytes and the selection's producer before using
    this projection. Unknown material can be fully documented in a parked idea;
    it cannot support a recommendation. This function never searches or judges.
    """
    if not isinstance(selection, dict):
        raise Stage2Error("content-gate-selection-shape")
    packet = selection.get("evaluation_packet")
    if not isinstance(packet, dict) or not isinstance(packet.get("candidates"), list):
        raise Stage2Error("content-gate-packet-shape")
    if any(
        not isinstance(row, dict)
        or not _text(row.get("candidate_id"))
        or type(row.get("version")) is not int
        or row["version"] < 1
        for row in packet["candidates"]
    ):
        raise Stage2Error("content-gate-candidate-shape")
    try:
        _, latest = latest_candidates(packet, [])
    except (KeyError, TypeError, ValueError) as error:
        raise Stage2Error("content-gate-candidate-shape") from error
    blockers, checks = [], []

    def check(check_id, passed, reason):
        checks.append(
            {"check_id": check_id, "status": "complete" if passed else "pending"}
        )
        if not passed:
            blockers.append({"check_id": check_id, "reason": reason})

    tables = packet.get("research_tables")
    prepared = (
        packet.get("schema_version") in {"2.2.0", "2.3.0", "2.4.0"}
        and tables is not None
    )
    if prepared:
        try:
            tables = validate_research_tables(tables, packet)
        except (KeyError, TypeError, ValueError) as error:
            raise Stage2Error("content-gate-table-shape") from error
    check(
        "topic-matrix",
        prepared,
        "Prepare the topic-specific comparison matrix before final delivery.",
    )
    represented = (
        {(row["work_id"], row["version_id"]) for row in tables["work_refs"]}
        if prepared
        else set()
    )
    literature = [
        *packet.get("literature", []),
        *packet.get("supplemental_literature", []),
    ]
    if not isinstance(literature, list) or any(
        not isinstance(row, dict)
        or not _text(row.get("work_id"))
        or not _text(row.get("version_id"))
        for row in literature
    ):
        raise Stage2Error("content-gate-literature-shape")
    required_works = {(row.get("work_id"), row.get("version_id")) for row in literature}
    check(
        "literature-coverage",
        prepared and bool(required_works) and required_works <= represented,
        "Represent the supplied literature in the matrix, using explicit unknown or not-applicable cells where needed.",
    )
    check(
        "comparison",
        _text(packet.get("comparison")),
        "Record the source-grounded comparison and its limits.",
    )
    options = selection.get("current_options")
    if not isinstance(options, list):
        raise Stage2Error("content-gate-options-shape")
    by_id = {}
    for option in options:
        if not isinstance(option, dict) or not isinstance(
            option.get("candidate"), dict
        ):
            raise Stage2Error("content-gate-option-shape")
        candidate = option["candidate"]
        candidate_id = candidate.get("candidate_id")
        if not _text(candidate_id) or candidate_id in by_id:
            raise Stage2Error("content-gate-option-identity")
        by_id[candidate_id] = option
    check(
        "current-candidate-set",
        set(by_id) == set(latest),
        "Every current candidate needs a matching direction record.",
    )
    resources = tables["direction_resources"] if prepared else []
    prior_work = current_prior_work_reviews(packet)
    actual_recommendations = set()
    for candidate_id, candidate in latest.items():
        key = f"{candidate_id}:v{candidate['version']}"
        option = by_id.get(candidate_id)
        current = option is not None and option["candidate"] == candidate
        check(
            key + ":current",
            current,
            "The direction must use the current candidate version.",
        )
        if not current:
            continue
        if packet.get("schema_version") == "2.4.0":
            check(
                key + ":prior-work",
                candidate_id in prior_work,
                "Complete a candidate/source-bound prior-work review before final delivery.",
            )
        check(
            key + ":proposal",
            all(
                _text(candidate.get(field))
                for field in ("question", "opportunity", "value", "approach")
            )
            and isinstance(candidate.get("requirements"), list)
            and all(_text(item) for item in candidate["requirements"])
            and isinstance(candidate.get("limitations"), list)
            and all(_text(item) for item in candidate["limitations"]),
            "Record the question, contribution, method, required materials and limitations.",
        )
        assessment = option.get("assessment")
        valid = isinstance(assessment, dict)
        if valid:
            try:
                if (
                    assessment.get("packet_sha256") != selection.get("packet_sha256")
                    or assessment.get("candidate_id") != candidate_id
                    or assessment.get("candidate_version") != candidate["version"]
                ):
                    raise Stage2Error("content-gate-assessment-input-binding-mismatch")
                validate_assessment(assessment, packet, latest)
            except Stage2Error as error:
                valid = False
                reason = str(error)
        else:
            reason = "The current direction has no completed five-axis check."
        check(key + ":review", valid, reason if not valid else "")
        if not valid:
            continue
        candidate_resources = [
            row
            for row in resources
            if row["candidate_id"] == candidate_id
            and row["candidate_version"] == candidate["version"]
        ]
        materials = assessment["checks"]["materials"]
        check(
            key + ":resources",
            bool(candidate_resources) or materials["status"] == "not-applicable",
            "Provide the direction's relevant resource table, or a checked reason why research materials do not apply.",
        )
        if assessment["disposition"] == "recommend":
            actual_recommendations.add(candidate_id)
            unresolved = [
                row
                for row in candidate_resources
                if row["required"]
                and (
                    row["status"] in {"unknown", "unavailable", "not-applicable"}
                    or (
                        row["status"] == "restricted"
                        and not _text(row["access_conditions"])
                    )
                )
            ]
            check(
                key + ":required-access",
                not unresolved,
                "A necessary resource is unavailable or its access conditions are unknown; revise or park until those conditions are checked.",
            )
        check(
            key + ":next-step",
            _text(assessment.get("reason"))
            and (
                _text(assessment.get("next_step"))
                or assessment["disposition"] == "recommend"
            ),
            "Explain the disposition and a useful next step.",
        )
    recommendations = selection.get("recommendations")
    if not isinstance(recommendations, list) or any(
        not isinstance(row, dict) for row in recommendations
    ):
        raise Stage2Error("content-gate-recommendations-shape")
    declared = [row.get("candidate_id") for row in recommendations]
    if any(not _text(item) for item in declared):
        raise Stage2Error("content-gate-recommendation-identity")
    check(
        "recommendation-consistency",
        len(declared) == len(set(declared)) and set(declared) == actual_recommendations,
        "The shortlist must agree with the current checked dispositions.",
    )
    if not latest:
        unresolved = selection.get("unresolved")
        check(
            "zero-directions-explanation",
            isinstance(unresolved, list)
            and bool(unresolved)
            and all(_text(item) for item in unresolved),
            "Explain why no direction is currently supported and what to investigate next.",
        )
    decisions_valid = selection.get(
        "action_record_status"
    ) == "complete" and isinstance(selection.get("action_record"), dict)
    if decisions_valid:
        try:
            validate_action_record(selection["action_record"], packet)
            recorded = {
                (row["candidate_id"], row["candidate_version"]): row["disposition"]
                for row in selection["action_record"]["latest_dispositions"]
            }
            checked = {
                (row["candidate"]["candidate_id"], row["candidate"]["version"]): row[
                    "assessment"
                ].get("disposition")
                for row in options
                if isinstance(row.get("assessment"), dict)
            }
            decisions_valid = recorded == checked and set(
                selection["action_record"]["selected_candidate_ids"]
            ) == set(declared)
        except Stage2Error:
            decisions_valid = False
    check(
        "decision-record",
        decisions_valid,
        "Complete the version-bound comparison, disposition and revision records; a missing record is not completed work.",
    )
    result = {
        "kind": "Stage2ContentGate",
        "schema_version": "1.0.0",
        "core_selection_sha256": canonical_hash(selection),
        "status": "content-complete" if not blockers else "draft",
        "checks": checks,
        "blocking_items": blockers,
        "meaning": "Recorded delivery completeness only; source validation and independent semantic assessment remain required.",
        "scientific_truth_validated": False,
        "formal_ready": False,
        "human_selection": "pending",
        "stage3_authorized": False,
        "improvement_demonstrated": False,
    }
    return {**result, "record_sha256": canonical_hash(result)}


def validate_content_gate(record, selection, expected_sha256):
    """Reject foreign or rehashed gate claims by reconstructing current inputs."""
    if not isinstance(record, dict) or canonical_hash(record) != expected_sha256:
        raise Stage2Error("content-gate-external-hash-mismatch")
    if record != derive_content_gate(selection):
        raise Stage2Error("content-gate-reconstruction-mismatch")
    return record


def render_content_gate_html(record):
    """Keep the recorded completeness state and decisive missing work visible."""
    rows = "".join(
        "<li>" + escape(row["reason"]) + "</li>" for row in record["blocking_items"]
    )
    details = "<ul>" + rows + "</ul>" if rows else ""
    return (
        '<section id="stage2-content-gate" aria-label="Selection package completeness">'
        "<h3>Selection package: "
        + escape(record["status"])
        + "</h3>"
        + details
        + "<p>Record completeness only. Independent scores, material readiness and your choice are separate.</p></section>"
    )


def render_content_gate_markdown(record):
    lines = ["## Selection package completeness", "", "Status: " + record["status"], ""]
    lines.extend("- " + row["reason"] for row in record["blocking_items"])
    lines.extend(
        [
            "",
            "Record completeness only. Independent scores, material readiness and your choice are separate.",
            "",
        ]
    )
    return "\n".join(lines)
