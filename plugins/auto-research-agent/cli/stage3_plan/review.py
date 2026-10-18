"""Source-bound semantic assessment, distinct from structural validation."""

from .contracts import Stage3Error, digest
from .validation import check_plan

RUBRIC = {
    "version": "stage3-semantic-v1",
    "axes": [
        "answerability",
        "resource-fit",
        "inference-boundary",
        "result-interpretation",
        "feasibility",
    ],
    "rule": "Every core question assessed; concrete reasons and plan locations. Unknown is not pass.",
}


def review_plan(plan, intake, callback):
    """Invoke a host reviewer; callers retain its raw/capture evidence separately."""
    if not callable(callback):
        raise Stage3Error("semantic review callback required")
    review = callback(plan=plan, intake=intake, rubric=RUBRIC)
    return validate_review(plan, intake, review)


def validate_review(plan, intake, review):
    expected = {
        "kind",
        "plan_sha256",
        "intake_sha256",
        "rubric_sha256",
        "reviewer",
        "findings",
        "execution_authorized",
    }
    if (
        not isinstance(review, dict)
        or set(review) != expected
        or review["kind"] != "Stage3SemanticReview"
        or review["plan_sha256"] != digest(plan)
        or review["intake_sha256"] != digest(intake)
        or review["rubric_sha256"] != digest(RUBRIC)
        or review["execution_authorized"] is not False
    ):
        raise Stage3Error("semantic review binding mismatch")
    reviewer = review["reviewer"]
    if (
        not isinstance(reviewer, dict)
        or set(reviewer) != {"actor", "kind", "identity_authenticated", "evidence_ref"}
        or reviewer["kind"] not in {"native-model", "human-record", "synthetic"}
        or reviewer["identity_authenticated"] is not False
        or not all(
            isinstance(reviewer[k], str) and reviewer[k].strip()
            for k in ("actor", "evidence_ref")
        )
    ):
        raise Stage3Error(
            "reviewer scope must be explicit; host does not authenticate humans"
        )
    questions = {q["question_ref"] for q in plan["questions"]}
    expected_pairs = {(q, axis) for q in questions for axis in RUBRIC["axes"]}
    found = set()
    for finding in review["findings"]:
        if (
            set(finding)
            != {"question_ref", "axis", "status", "reason", "plan_locations"}
            or finding["status"] not in {"adequate", "needs-revision", "unknown"}
            or not isinstance(finding["reason"], str)
            or not finding["reason"].strip()
            or not finding["plan_locations"]
        ):
            raise Stage3Error("semantic finding missing assessment/reason/location")
        pair = (finding["question_ref"], finding["axis"])
        if pair not in expected_pairs or pair in found:
            raise Stage3Error("semantic review question/axis duplicate or unknown")
        found.add(pair)
        for location in finding["plan_locations"]:
            value = plan
            try:
                if not location.startswith("/"):
                    raise KeyError(location)
                for token in location[1:].split("/"):
                    token = token.replace("~1", "/").replace("~0", "~")
                    value = (
                        value[int(token)] if isinstance(value, list) else value[token]
                    )
            except (KeyError, ValueError, IndexError, TypeError) as error:
                raise Stage3Error("semantic review location does not exist") from error
    if found != expected_pairs:
        raise Stage3Error("semantic review missing question assessments")
    return review


def plan_status(plan, intake, review=None, *, admission_scope="unverified"):
    check = check_plan(plan, intake=intake)
    if not check["structural_valid"]:
        return "needs-revision"
    if check["blocked_questions"]:
        return "needs-information"
    if review is None:
        return "draft"
    validate_review(plan, intake, review)
    statuses = {finding["status"] for finding in review["findings"]}
    if "needs-revision" in statuses:
        return "needs-revision"
    if "unknown" in statuses:
        return "needs-information"
    # Synthetic reviews exercise mechanics only; never promote a real plan.
    if (
        review["reviewer"]["kind"] == "synthetic"
        or admission_scope != "strict-selected"
    ):
        return "draft"
    return "ready-for-plan-review"
