"""Version-bound assessments; new reviews require actionable content."""

import copy
import re

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

# Keep v1 byte-identical: completed archives and evaluation fingerprints bind it.
ACTIONABLE_RUBRIC = {
    "version": "stage3-semantic-v2",
    "axes": list(RUBRIC["axes"]),
    "rule": (
        "Every question/axis requires status, reason and existing plan_locations. "
        "Statuses: adequate, needs-revision, not-adequate, unknown. "
        "Each finding also requires revision and missing_information. "
        "For needs-revision/not-adequate, revision is {location, action}: cite a "
        "specific scalar plan field also listed in plan_locations and describe the "
        "concrete next action. Otherwise revision is null. For unknown, "
        "missing_information is {needed, owner}: name the missing evidence and "
        "the person or role to ask. Otherwise missing_information is null. "
        "These fields do not authenticate a person or prove scientific adequacy."
    ),
}


def review_plan(plan, intake, callback):
    """Invoke a host reviewer; callers retain its raw/capture evidence separately."""
    if not callable(callback):
        raise Stage3Error("semantic review callback required")
    review = callback(plan=plan, intake=intake, rubric=copy.deepcopy(ACTIONABLE_RUBRIC))
    return validate_new_review(plan, intake, review)


def validate_new_review(plan, intake, review):
    """Creation gate. Old rubric records remain readable, not newly attachable."""
    if not isinstance(review, dict) or review.get("rubric_sha256") != digest(
        ACTIONABLE_RUBRIC
    ):
        raise Stage3Error("new semantic review requires stage3-semantic-v2")
    return validate_review(plan, intake, review)


def _plan_location(plan, location, *, strict):
    value = plan
    try:
        if not isinstance(location, str) or not location.startswith("/"):
            raise KeyError(location)
        for token in location[1:].split("/"):
            if strict and re.search(r"~(?![01])", token):
                raise KeyError(token)
            token = token.replace("~1", "/").replace("~0", "~")
            if isinstance(value, list):
                if strict and not re.fullmatch(r"0|[1-9][0-9]*", token):
                    raise KeyError(token)
                value = value[int(token)]
            else:
                value = value[token]
    except (KeyError, ValueError, IndexError, TypeError) as error:
        raise Stage3Error("semantic review location does not exist") from error
    return value


def _content_fields(plan, finding):
    revision = finding["revision"]
    missing = finding["missing_information"]
    if finding["status"] in {"needs-revision", "not-adequate"}:
        if (
            not isinstance(revision, dict)
            or set(revision) != {"location", "action"}
            or not isinstance(revision["action"], str)
            or not revision["action"].strip()
            or revision["location"] not in finding["plan_locations"]
        ):
            raise Stage3Error("semantic revision requires a cited location and action")
        value = _plan_location(plan, revision["location"], strict=True)
        if isinstance(value, (dict, list)):
            raise Stage3Error("semantic revision must locate a specific plan field")
    elif revision is not None:
        raise Stage3Error("semantic revision is only for a revision or rejection")
    if finding["status"] == "unknown":
        if (
            not isinstance(missing, dict)
            or set(missing) != {"needed", "owner"}
            or not all(isinstance(v, str) and v.strip() for v in missing.values())
        ):
            raise Stage3Error("semantic unknown requires missing information and owner")
    elif missing is not None:
        raise Stage3Error("semantic missing information is only for unknown")


def validate_review(plan, intake, review):
    """Read either pinned rubric version without upgrading archived records."""
    current = isinstance(review, dict) and review.get("rubric_sha256") == digest(
        ACTIONABLE_RUBRIC
    )
    rubric = ACTIONABLE_RUBRIC if current else RUBRIC
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
        or review["rubric_sha256"] != digest(rubric)
        or review["execution_authorized"] is not False
        or not isinstance(review["findings"], list)
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
    expected_pairs = {(q, axis) for q in questions for axis in rubric["axes"]}
    found = set()
    fields = {"question_ref", "axis", "status", "reason", "plan_locations"}
    statuses = {"adequate", "needs-revision", "unknown"}
    if current:
        fields |= {"revision", "missing_information"}
        statuses.add("not-adequate")
    for finding in review["findings"]:
        if (
            not isinstance(finding, dict)
            or set(finding) != fields
            or not isinstance(finding["status"], str)
            or finding["status"] not in statuses
            or not isinstance(finding["question_ref"], str)
            or not isinstance(finding["axis"], str)
            or not isinstance(finding["reason"], str)
            or not finding["reason"].strip()
            or not isinstance(finding["plan_locations"], list)
            or not finding["plan_locations"]
        ):
            raise Stage3Error("semantic finding missing assessment/reason/location")
        pair = (finding["question_ref"], finding["axis"])
        if pair not in expected_pairs or pair in found:
            raise Stage3Error("semantic review question/axis duplicate or unknown")
        found.add(pair)
        for location in finding["plan_locations"]:
            _plan_location(plan, location, strict=current)
        if current:
            _content_fields(plan, finding)
    if found != expected_pairs:
        raise Stage3Error("semantic review missing question assessments")
    return review


def plan_status(plan, intake, review=None, *, admission_scope="unverified"):
    if review is not None:
        validate_review(plan, intake, review)
    check = check_plan(plan, intake=intake)
    if not check["structural_valid"]:
        return "needs-revision"
    if check["blocked_questions"]:
        return "needs-information"
    if review is None:
        return "draft"
    statuses = {finding["status"] for finding in review["findings"]}
    if statuses & {"needs-revision", "not-adequate"}:
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
