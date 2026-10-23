"""Pure decision-card projection for a validated Stage 2 selection."""

from copy import deepcopy


def _candidate_next_checks(option, option_index, prior_review, review_index):
    """Return recorded next checks with paths back to the selection."""

    rows = []
    assessment = option.get("assessment")
    if isinstance(assessment, dict):
        next_step = assessment.get("next_step")
        if next_step is not None:
            rows.append(
                {
                    "text": deepcopy(next_step),
                    "source": f"current_options[{option_index}].assessment.next_step",
                }
            )
        checks = assessment.get("checks")
        if isinstance(checks, dict):
            for axis in sorted(checks):
                finding = checks[axis]
                if not isinstance(finding, dict):
                    continue
                next_check = finding.get("next_check")
                if next_check is not None:
                    rows.append(
                        {
                            "text": deepcopy(next_check),
                            "source": (
                                f"current_options[{option_index}].assessment.checks"
                                f".{axis}.next_check"
                            ),
                        }
                    )
    if prior_review is not None:
        for unresolved_index, text in enumerate(prior_review.get("unresolved", [])):
            rows.append(
                {
                    "text": deepcopy(text),
                    "source": (
                        f"evaluation_packet.prior_work_reviews[{review_index}]"
                        f".unresolved[{unresolved_index}]"
                    ),
                }
            )
    return rows


def _question_card(question, argument, current_resources, next_checks):
    question_id = question["question_id"]
    refs = [
        (index, row)
        for index, row in enumerate(argument.get("resource_refs", []))
        if question_id in row.get("question_ids", [])
    ]
    resources_by_id = {
        row.get("resource_id"): (index, row)
        for index, row in current_resources
        if isinstance(row, dict)
    }
    resource_uses = []
    unresolved_refs = []
    for ref_index, ref in refs:
        matched = resources_by_id.get(ref.get("resource_id"))
        if matched is None:
            unresolved_refs.append(
                {
                    "resource_ref": deepcopy(ref),
                    "source": f"scientific_argument.resource_refs[{ref_index}]",
                }
            )
            continue
        resource_index, resource = matched
        resource_uses.append(
            {
                "resource_ref": deepcopy(ref),
                "resource": deepcopy(resource),
                "resource_ref_source": (
                    f"scientific_argument.resource_refs[{ref_index}]"
                ),
                "resource_source": (
                    "evaluation_packet.research_tables.direction_resources"
                    f"[{resource_index}]"
                ),
            }
        )

    if not resource_uses:
        mapping_status = "unmapped"
    elif question.get("status") == "unknown" or any(
        use["resource_ref"].get("fit_status") == "unknown"
        or use["resource"].get("status") == "unknown"
        for use in resource_uses
    ):
        mapping_status = "unknown"
    else:
        mapping_status = "mapped"

    contributions = [
        deepcopy(row)
        for row in argument.get("contribution_claims", [])
        if question_id in row.get("question_ids", [])
    ]
    return {
        "question": deepcopy(question),
        "resource_mapping_status": mapping_status,
        "resource_uses": resource_uses,
        "unresolved_resource_refs": unresolved_refs,
        "contributions": contributions,
        "next_checks": deepcopy(next_checks),
        "next_check_status": "recorded" if next_checks else "none-recorded",
    }


def derive_decision_cards(selection):
    """Project current scientific questions and recorded decision evidence.

    The function copies source records without changing scientific assessments,
    recommendation state, access claims, or evidence status.  Resources and
    prior-work reviews are joined only to the exact current candidate version.
    """

    packet = selection["evaluation_packet"]
    tables = packet.get("research_tables") or {}
    resources = tables.get("direction_resources") or []
    prior_reviews = packet.get("prior_work_reviews") or []
    cards = []

    for option_index, option in enumerate(selection["current_options"]):
        candidate = option["candidate"]
        candidate_id = candidate["candidate_id"]
        candidate_version = candidate["version"]
        current_resources = [
            (index, row)
            for index, row in enumerate(resources)
            if isinstance(row, dict)
            and row.get("candidate_id") == candidate_id
            and row.get("candidate_version") == candidate_version
        ]
        prior_matches = [
            (index, row)
            for index, row in enumerate(prior_reviews)
            if isinstance(row, dict)
            and row.get("candidate_id") == candidate_id
            and row.get("candidate_version") == candidate_version
        ]
        review_index, prior_review = prior_matches[0] if prior_matches else (None, None)
        next_checks = _candidate_next_checks(
            option, option_index, prior_review, review_index
        )
        argument = candidate.get("scientific_argument")
        argument_status = "recorded" if isinstance(argument, dict) else "not-recorded"
        argument = argument if isinstance(argument, dict) else {}
        questions = [
            _question_card(question, argument, current_resources, next_checks)
            for question in argument.get("questions", [])
        ]
        mapped_resource_ids = {
            use["resource"]["resource_id"]
            for question in questions
            for use in question["resource_uses"]
        }
        unmapped_resources = [
            {
                "resource": deepcopy(row),
                "resource_mapping_status": "unmapped",
                "source": (
                    f"evaluation_packet.research_tables.direction_resources[{index}]"
                ),
            }
            for index, row in current_resources
            if row.get("resource_id") not in mapped_resource_ids
        ]
        alternatives = [
            {
                "resource_id": deepcopy(row.get("resource_id")),
                "alternatives": deepcopy(row.get("alternatives", [])),
                "source": (
                    "evaluation_packet.research_tables.direction_resources"
                    f"[{index}].alternatives"
                ),
            }
            for index, row in current_resources
        ]
        cards.append(
            {
                "candidate_id": deepcopy(candidate_id),
                "candidate_version": deepcopy(candidate_version),
                "candidate_question": deepcopy(candidate.get("question")),
                "research_mode": deepcopy(candidate.get("research_mode")),
                "closest_prior_work": {
                    "mapping_status": (
                        "mapped" if prior_review is not None else "unmapped"
                    ),
                    "review": deepcopy(prior_review),
                    "source": (
                        f"evaluation_packet.prior_work_reviews[{review_index}]"
                        if prior_review is not None
                        else None
                    ),
                },
                "contribution": deepcopy(argument.get("contribution_claims", [])),
                "suggested_approach": deepcopy(candidate.get("approach")),
                "requirements": deepcopy(candidate.get("requirements", [])),
                "limitations": deepcopy(candidate.get("limitations", [])),
                "alternatives": alternatives,
                "next_checks": deepcopy(next_checks),
                "scientific_argument_status": argument_status,
                "scientific_questions": questions,
                "unmapped_resources": unmapped_resources,
            }
        )

    return {
        "kind": "Stage2DecisionCards",
        "schema_version": "1.0.0",
        "cards": cards,
    }
