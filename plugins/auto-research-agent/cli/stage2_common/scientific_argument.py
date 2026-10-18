"""Reference-closure checks for opt-in Stage 2.5 scientific arguments."""


def _require(condition, message, error_type):
    if not condition:
        raise error_type(message)


def _claim_records(argument):
    yield argument["motivation"]
    yield from argument["current_state"]
    for gap in argument["gaps"]:
        yield gap["statement"]
        yield gap["importance"]
    for challenge in argument["challenges"]:
        yield challenge["statement"]


def validate_scientific_argument(
    candidate, packet, *, raw_proposal=None, error_type=ValueError
):
    """Validate semantic references that JSON Schema cannot close."""

    argument = candidate["scientific_argument"]
    evidence = {row["evidence_id"]: row for row in packet["evidence"]}
    sources = {row["source_id"]: row for row in packet["sources"]}
    gaps = {row["gap_id"] for row in argument["gaps"]}
    questions = {row["question_id"] for row in argument["questions"]}
    challenges = [row["challenge_id"] for row in argument["challenges"]]
    _require(
        len(gaps) == len(argument["gaps"]),
        "duplicate scientific argument gap_id",
        error_type,
    )
    _require(
        len(questions) == len(argument["questions"]),
        "duplicate scientific argument question_id",
        error_type,
    )
    _require(
        len(challenges) == len(set(challenges)),
        "duplicate scientific argument challenge_id",
        error_type,
    )
    _require(
        any(row["priority"] == "core" for row in argument["questions"]),
        "scientific argument requires a core question",
        error_type,
    )

    for claim in _claim_records(argument):
        _require(
            set(claim["evidence_ids"]).issubset(evidence),
            "scientific argument references unknown evidence",
            error_type,
        )
        _require(
            claim["status"] != "fact" or claim["evidence_ids"],
            "scientific argument fact requires evidence",
            error_type,
        )
        for ref in claim["source_refs"]:
            source = sources.get(ref["source_id"])
            _require(
                source is not None
                and source["work_id"] == ref["work_id"]
                and source["version_id"] == ref["version_id"],
                "scientific argument source_ref does not resolve",
                error_type,
            )
        if raw_proposal is not None:
            for span in claim["proposal_spans"]:
                _require(
                    0 <= span["start"] < span["end"] <= len(raw_proposal),
                    "scientific argument proposal span is outside the raw proposal",
                    error_type,
                )

    for row in argument["questions"]:
        _require(
            set(row["gap_ids"]).issubset(gaps),
            "scientific question references unknown gap",
            error_type,
        )
    for row in argument["challenges"]:
        _require(
            set(row["gap_ids"]).issubset(gaps),
            "scientific challenge references unknown gap",
            error_type,
        )
        _require(
            set(row["question_ids"]).issubset(questions),
            "scientific challenge references unknown question",
            error_type,
        )
    for row in argument["contribution_claims"]:
        _require(
            set(row["question_ids"]).issubset(questions),
            "contribution claim references unknown question",
            error_type,
        )

    resources = {
        row["resource_id"]
        for row in (packet.get("research_tables") or {}).get("direction_resources", [])
        if row["candidate_id"] == candidate["candidate_id"]
        and row["candidate_version"] == candidate["version"]
    }
    for row in argument["resource_refs"]:
        _require(
            row["resource_id"] in resources,
            "scientific argument resource_ref does not resolve",
            error_type,
        )
        _require(
            set(row["question_ids"]).issubset(questions),
            "scientific resource references unknown question",
            error_type,
        )
        _require(
            set(row["evidence_ids"]).issubset(evidence),
            "scientific resource references unknown evidence",
            error_type,
        )
