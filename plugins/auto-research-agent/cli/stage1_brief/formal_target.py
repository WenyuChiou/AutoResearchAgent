"""Explicit formal-count intake and arithmetic progress, without native I/O."""

from copy import deepcopy
from datetime import datetime

from stage1_ledger.journal import LedgerError, canonical, digest

VERSION = "1.1.0"
_ANSWER_KEYS = {
    "event_id",
    "project_id",
    "input_version",
    "request_id",
    "status",
    "target",
    "actor",
    "authority",
    "user_input",
    "source_ref",
    "recorded_at",
    "provenance",
}


def require(condition, message):
    if not condition:
        raise LedgerError("formal-final-count: " + message)


def text(value):
    return type(value) is str and bool(value.strip())


def positive(value):
    require(type(value) is int and value > 0, "target must be a positive integer")
    return value


def binding(record):
    require(type(record) is dict, "binding must be an object")
    require(text(record.get("project_id")), "project_id missing")
    version = record.get("input_version")
    require(
        text(version) or (type(version) is int and version > 0), "input_version missing"
    )
    return record["project_id"], version


def same_binding(actual, expected):
    require(
        binding(actual) == binding(expected)
        and type(actual["input_version"]) is type(expected["input_version"]),
        "wrong project or stale input_version",
    )


def prepare_formal_intake(
    request, *, project_id, input_version, request_id, proposed_target=30
):
    require(type(request) is dict, "intake request must be an object")
    require(
        "formal_final_count" not in request and not request.get("previous_sha256"),
        "new intake cannot adopt prior formal answers",
    )
    require(text(request_id), "request_id missing")
    result = deepcopy(request)
    result.update(
        kind="ResearchBrief",
        schema_version=VERSION,
        project_id=project_id,
        input_version=input_version,
    )
    binding(result)
    result["formal_final_count"] = {
        "request_id": request_id,
        "proposed_target": positive(proposed_target),
        "decisions": [],
    }
    return result


def formal_target_state(brief, *, require_confirmed=False):
    require(
        type(brief) is dict and brief.get("schema_version") == VERSION,
        "requires ResearchBrief 1.1",
    )
    binding(brief)
    target = brief.get("formal_final_count")
    require(
        type(target) is dict
        and set(target) == {"request_id", "proposed_target", "decisions"},
        "invalid formal question fields",
    )
    require(text(target["request_id"]), "request_id missing")
    positive(target["proposed_target"])
    decisions = target["decisions"]
    require(type(decisions) is list, "decisions must be a list")
    ids = set()
    for answer in decisions:
        require(
            type(answer) is dict and set(answer) == _ANSWER_KEYS,
            "invalid submitted answer fields",
        )
        same_binding(answer, brief)
        require(answer["request_id"] == target["request_id"], "mismatched request_id")
        positive(answer["target"])
        require(
            answer["status"] == "submitted"
            and answer["authority"] == "user"
            and answer["provenance"] == "user-attested",
            "explicit user-attested submission required",
        )
        require(
            all(
                text(answer[key])
                for key in (
                    "event_id",
                    "actor",
                    "user_input",
                    "source_ref",
                    "recorded_at",
                )
            ),
            "answer provenance missing",
        )
        require(answer["event_id"] not in ids, "duplicate answer event")
        ids.add(answer["event_id"])
        try:
            timestamp = datetime.fromisoformat(
                answer["recorded_at"].replace("Z", "+00:00")
            )
            require(
                timestamp.utcoffset() is not None, "answer timestamp lacks timezone"
            )
        except ValueError as error:
            raise LedgerError("formal-final-count: invalid answer timestamp") from error
    require(
        not require_confirmed or bool(decisions), "formal final count question pending"
    )
    return {
        "project_id": brief["project_id"],
        "input_version": brief["input_version"],
        "request_id": target["request_id"],
        "proposed_target": target["proposed_target"],
        "status": "confirmed" if decisions else "pending",
        "target": decisions[-1]["target"] if decisions else None,
        "answer_sha256": digest(canonical(decisions[-1])) if decisions else None,
    }


def formal_question(brief):
    state = formal_target_state(brief)
    return {
        "kind": "FormalFinalCountQuestion",
        "schema_version": VERSION,
        **{
            key: state[key]
            for key in (
                "project_id",
                "input_version",
                "request_id",
                "proposed_target",
                "status",
            )
        },
        "question": f"How many formally usable distinct works should the final selection include? Proposed: {state['proposed_target']}. Submit an explicit positive integer; silence is not confirmation.",
        "answer_type": "positive-integer",
    }


def submit_formal_target(brief, answer):
    formal_target_state(brief)
    result = deepcopy(brief)
    result["formal_final_count"]["decisions"].append(deepcopy(answer))
    formal_target_state(result, require_confirmed=True)
    return result


def formal_selection_progress(brief, selection):
    """Count caller-admitted selection rows; do not validate source eligibility."""
    state = formal_target_state(brief, require_confirmed=True)
    same_binding(selection, brief)
    rows = selection.get("rows")
    require(type(rows) is list, "selection rows must be a list")
    works, included_rows = set(), 0
    for row in rows:
        require(
            type(row) is dict and text(row.get("work_id")), "selection work_id missing"
        )
        require(
            row.get("status") in ("included", "pending", "excluded"),
            "unknown selection status",
        )
        if row["status"] == "included":
            works.add(row["work_id"])
            included_rows += 1
    shortfall = max(0, state["target"] - len(works))
    return {
        **state,
        "selection_row_count": len(rows),
        "included_version_row_count": included_rows,
        "included_work_ids": sorted(works),
        "formally_usable_distinct_works": len(works),
        "target_shortfall": shortfall,
        "formal_target_met": shortfall == 0,
        "action": "continue-target" if shortfall else "target-met",
        "scientific_sufficiency": "not-assessed",
        "coverage": "not-assessed",
        "stop_decision": "not-assessed",
        "stage2_eligibility": "not-assessed",
    }
