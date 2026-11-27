"""The researcher's decision on a saved Stage 3 plan, recorded by the local Host UI.

Same family as ``project_stage3_feedback``: an immutable record in the owned
planning journal, bound to the exact displayed plan version, idempotent by key,
never a native message, never a model call, never an execution grant. Every
refusal that needs no write happens before the record is attempted, so a refused
decision leaves nothing behind.

Decisions: ``accept`` (the plan is accepted), ``revise-then-review`` (intent only:
the researcher then uses comments and revisions and starts a new planning job
explicitly), ``return-to-stage2`` (intent only: Stage 2's saved selection cannot
be changed, so the record says ``stage2_selection_change_required``).

The record is honest about its origin: ``decision_status`` is always
``recorded-by-local-host-ui`` and ``identity_authenticated`` is false. Core's
``record_plan_decision`` (which needs a real native user message) is not used.
"""

from copy import deepcopy

from stage3_plan.contracts import digest
from stage3_plan.jobs import POLICY
from stage3_plan.validation import check_plan

from .project_intake_contract import _fields
from .project_stage3_feedback import BINDING_FIELDS, EDIT_FIELDS, _text, fits_response
from .session_api import _check

METHOD = "stage3/project-host-decision/1"
MAX_RECORDS = 32
DECISIONS = ("accept", "revise-then-review", "return-to-stage2")
STATUS = "recorded-by-local-host-ui"
FIELDS = BINDING_FIELDS | {"key", "decision", "text", "confirmed"}
TEXT_BYTES = 2000


def _context(ref, view):
    job, plan = view.get("job") or {}, view.get("plan")
    _check(
        type(plan) is dict
        and job.get("outcome") == "saved"
        and job.get("plan_manifest_sha256")
        and job.get("request_sha256"),
        "stage3-decision-saved-plan-required",
        409,
    )
    return {
        "project_ref": ref,
        **{name: view[name] for name in ("revision", "input_version", "brief_sha256")},
        "parent_plan_manifest_sha256": job["plan_manifest_sha256"],
        "parent_plan_sha256": digest(plan),
        "plan_request_sha256": job["request_sha256"],
    }


def _key(binding, key):
    return "stage3-decision-" + digest([binding, key])


def _rows(jobs, binding):
    state = jobs.journal.snapshot(jobs.project_id)
    rows = []
    for item in state["intents"].values():
        if item["method"] != METHOD:
            continue
        record = item["payload"]
        if record.get("binding") != binding:
            continue
        _check(
            record.get("kind") == "decision"
            and record.get("request_sha256") == digest(record.get("request"))
            and item["request_identity"] is None
            and item["record_sha256"]
            == digest(
                {
                    name: item[name]
                    for name in ("key", "method", "payload", "request_identity")
                }
            )
            and item["key"] == _key(binding, record["request"]["key"]),
            "stage3-decision-record-differs",
            409,
        )
        rows.append(
            {"receipt_sha256": item["record_sha256"], "record": deepcopy(record)}
        )
    _check(len(rows) <= MAX_RECORDS, "stage3-decision-record-bound", 409)
    # The journal stores intents sorted by their (hashed) key, so file order is
    # random. The server-assigned sequence, taken inside the locked write path,
    # is the only order that means "written first / last".
    rows.sort(key=lambda row: row["record"].get("sequence", 0))
    _check(
        [row["record"].get("sequence") for row in rows]
        == list(range(1, len(rows) + 1)),
        "stage3-decision-record-differs",
        409,
    )
    return rows


def read_decisions(jobs, ref, view):
    """Records for the currently displayed saved plan only; writes nothing."""
    binding = _context(ref, view)
    rows = _rows(jobs, binding)
    return {
        "kind": "ProjectStage3PlanDecisionView",
        "schema_version": 1,
        "binding": binding,
        "records": rows,
        "latest": deepcopy(rows[-1]) if rows else None,
        "decision_status": STATUS,
        "identity_authenticated": False,
        **POLICY,
    }


def accept_condition(plan):
    """The strongest readiness test this build can make without a saved review.

    Returns ``(ok, name)``. A direction plan is ready when every question plan has
    all of its content fields filled; a full plan must pass ``check_plan`` with
    no blocked question. Neither test needs, or claims, an independent review.
    """
    if plan.get("kind") == "Stage3DirectionPlanningResult":
        plans = plan.get("question_plans")
        ok = (
            type(plans) is list
            and bool(plans)
            and all(
                type(row) is dict
                and all(
                    type(row.get(name)) is str and row[name].strip()
                    for name in EDIT_FIELDS
                )
                for row in plans
            )
        )
        return ok, "every-question-plan-has-all-content-fields"
    check = check_plan(plan)
    return (
        bool(check["structural_valid"]) and not check["blocked_questions"],
        "structurally-valid-with-no-blocked-question",
    )


def record_decision(jobs, ref, view, body, check_deadline=None):
    """Append once; replay returns the stored record and never dispatches."""
    _fields(body, FIELDS)
    _check(body["confirmed"] is True, "explicit-stage3-decision-required", 400)
    _check(body["decision"] in DECISIONS, "stage3-decision-invalid", 400)
    _text(body["key"], "stage3-decision-key", 128)
    _text(body["text"], "stage3-decision-text", TEXT_BYTES)
    binding = _context(ref, view)
    _check(
        all(
            type(body[name]) is type(binding[name]) and body[name] == binding[name]
            for name in BINDING_FIELDS
        ),
        "stage3-decision-version-differs",
        409,
    )
    rows = _rows(jobs, binding)
    existing = next(
        (row for row in rows if row["record"]["request"]["key"] == body["key"]), None
    )
    if existing:
        _check(
            existing["record"]["request_sha256"] == digest(body),
            "stage3-decision-key-payload-differs",
            409,
        )
        return dict(existing, replayed=True, **POLICY)
    _check(len(rows) < MAX_RECORDS, "stage3-decision-record-bound", 409)
    record = {
        "kind": "decision",
        "schema_version": 1,
        "binding": binding,
        "request": deepcopy(body),
        "request_sha256": digest(body),
        "decision": body["decision"],
        "text": body["text"],
        "sequence": len(rows) + 1,
        "decision_status": STATUS,
        "identity_authenticated": False,
        "input_source": "project-host-user-submission",
        "native_message": False,
        "model_generated": False,
        "stage2_selection_change_required": body["decision"] == "return-to-stage2",
        **POLICY,
    }
    if body["decision"] == "accept":
        ok, name = accept_condition(view["plan"])
        _check(ok, "stage3-decision-plan-not-ready", 409)
        record["accept_condition"] = name
        record["independent_review_required_by_this_build"] = False
    pending = {
        "receipt_sha256": "0" * 64,
        "record": record,
        "replayed": False,
        **POLICY,
    }
    _check(
        fits_response(pending)
        and fits_response(
            dict(
                view,
                host_decision=dict(
                    read_decisions(jobs, ref, view), records=rows + [pending]
                ),
            )
        ),
        "stage3-decision-response-bound",
        413,
    )
    if check_deadline:
        check_deadline()
    state = jobs.journal.snapshot(jobs.project_id)
    item = jobs.journal.record_intent(
        jobs.project_id,
        jobs.owner,
        _key(binding, body["key"]),
        METHOD,
        record,
        expected_revision=state["revision"],
    )
    return {
        "receipt_sha256": item["record_sha256"],
        "record": deepcopy(item["payload"]),
        "replayed": item["replayed"],
        **POLICY,
    }
