"""The researcher's decision on a saved Stage 3 plan, recorded by the local Host UI.

Same family as ``project_stage3_feedback``: an immutable record in the owned
planning journal, bound to the exact displayed plan version, idempotent by key,
never a native message, never a model call, never an execution grant. Every
refusal that needs no write happens before the record is attempted, so a refused
decision leaves nothing behind.

The reason (``text``) is optional, at most 4096 UTF-8 bytes (413 beyond that);
``confirmed: true`` is always required.

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
from .project_stage3_feedback import _rows as _feedback_rows
from .session_api import _check

METHOD = "stage3/project-host-decision/1"
MAX_RECORDS = 32
DECISIONS = ("accept", "revise-then-review", "return-to-stage2")
STATUS = "recorded-by-local-host-ui"
REVISION = "plan_revision_receipt_sha256"
FIELDS = BINDING_FIELDS | {REVISION, "key", "decision", "text", "confirmed"}
TEXT_BYTES = 4096  # UTF-8 bytes; the reason is optional (may be empty)


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


def _current_revision(jobs, base):
    """Receipt, plan and ambiguity of the newest manual revision of this saved plan.

    A manual revision (comment/revise) leaves the saved plan untouched, so it must
    be part of what a decision is bound to; otherwise a decision made before the
    revision would still look current. The newest is the highest revision_number.
    Two drafts can share that number (both written from the same parent) and the
    journal has no write order for them, so a tie is reported as ambiguous rather
    than resolved by an arbitrary rule: no decision can be made until one draft is
    revised further (its child has the higher number).
    """
    revisions = [
        row for row in _feedback_rows(jobs, base) if row["record"]["kind"] == "revision"
    ]
    if not revisions:
        return None, None, False
    top = max(row["record"]["revision_number"] for row in revisions)
    newest = [row for row in revisions if row["record"]["revision_number"] == top]
    if len(newest) > 1:
        return None, None, True
    return newest[0]["receipt_sha256"], newest[0]["record"]["plan"], False


def _binding(jobs, ref, view):
    base = _context(ref, view)
    receipt, plan, ambiguous = _current_revision(jobs, base)
    return base, {**base, REVISION: receipt}, plan, ambiguous


def _key(binding, key):
    return "stage3-decision-" + digest([binding, key])


def _rows(jobs, base):
    """Every decision for this saved plan, across its manual revisions, in write order."""
    state = jobs.journal.snapshot(jobs.project_id)
    rows = []
    for item in state["intents"].values():
        if item["method"] != METHOD:
            continue
        record = item["payload"]
        recorded = record.get("binding") or {}
        if {k: v for k, v in recorded.items() if k != REVISION} != base:
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
            and item["key"] == _key(recorded, record["request"]["key"]),
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
    """Decisions for the displayed plan version only; older ones go to history."""
    base, binding, _, ambiguous = _binding(jobs, ref, view)
    rows = _rows(jobs, base)
    current = (
        []
        if ambiguous
        else [
            r for r in rows if r["record"]["binding"].get(REVISION) == binding[REVISION]
        ]
    )
    history = [
        dict(r, superseded_by_manual_revision=True)
        for r in rows
        if ambiguous or r["record"]["binding"].get(REVISION) != binding[REVISION]
    ]
    return {
        "kind": "ProjectStage3PlanDecisionView",
        "schema_version": 1,
        "binding": binding,
        "has_manual_revision": binding[REVISION] is not None or ambiguous,
        "revision_ambiguous": ambiguous,
        "records": current,
        "latest": deepcopy(current[-1]) if current else None,
        "history": history,
        "decision_status": STATUS,
        "identity_authenticated": False,
        **POLICY,
    }


READY_STATUSES = ("draft", "ready-for-plan-review")


def accept_condition(plan, job=None):
    """The strongest readiness test this build can make from the saved views.

    Returns ``(ok, name, reason)``; ``name`` lists every signal used and
    ``reason`` is the refusal code when ``ok`` is false. Signals:
    - ``job.planning_status`` MUST be present (it is saved with the plan and is
      ``needs-information`` when the plan says so or when the independent design
      review found a question not adequately answerable) and must be ``draft`` or
      ``ready-for-plan-review``; a missing status refuses;
    - a direction plan carries its own ``planning_status``: it must be present
      and not ``needs-information``; every question plan must have all content
      fields filled;
    - a full plan must pass ``check_plan`` with no blocked question.
    A saved human-readable review file is not read by this build, so none is
    required or claimed.
    """
    used = ["job-planning-status-draft-or-ready"]
    status = (job or {}).get("planning_status")
    if status is None:
        return False, "+".join(used), "stage3-decision-planning-status-missing"
    if status not in READY_STATUSES:
        return False, "+".join(used), "stage3-decision-plan-not-ready"
    if plan.get("kind") == "Stage3DirectionPlanningResult":
        own = plan.get("planning_status")
        used.append("plan-planning-status-present-and-not-needs-information")
        if own is None:
            return False, "+".join(used), "stage3-decision-planning-status-missing"
        if own == "needs-information":
            return False, "+".join(used), "stage3-decision-plan-not-ready"
        plans = plan.get("question_plans")
        used.append("every-question-plan-has-all-content-fields")
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
    else:
        check = check_plan(plan)
        used.append("structurally-valid-with-no-blocked-question")
        ok = bool(check["structural_valid"]) and not check["blocked_questions"]
    return ok, "+".join(used), None if ok else "stage3-decision-plan-not-ready"


def check_shape(body):
    """Everything about the request that needs neither the journal nor a lease.

    The Host calls this before it takes the journal owner lease, so a malformed
    request leaves no ``owner-acquired`` event behind.
    """
    _fields(body, FIELDS)
    _check(body["confirmed"] is True, "explicit-stage3-decision-required", 400)
    _check(body["decision"] in DECISIONS, "stage3-decision-invalid", 400)
    _text(body["key"], "stage3-decision-key", 128)
    _check(type(body["text"]) is str, "stage3-decision-text-invalid", 400)
    _check(
        len(body["text"].encode("utf8")) <= TEXT_BYTES,
        "stage3-decision-text-too-long",
        413,
    )


def record_decision(jobs, ref, view, body, check_deadline=None):
    """Append once; replay returns the stored record and never dispatches."""
    check_shape(body)
    base, binding, revised, ambiguous = _binding(jobs, ref, view)
    _check(not ambiguous, "stage3-decision-revision-ambiguous", 409)
    _check(
        all(
            type(body[name]) is type(binding[name]) and body[name] == binding[name]
            for name in BINDING_FIELDS | {REVISION}
        ),
        "stage3-decision-version-differs",
        409,
    )
    rows = _rows(jobs, base)
    existing = next(
        (
            row
            for row in rows
            if row["record"]["request"]["key"] == body["key"]
            and row["record"]["binding"] == binding
        ),
        None,
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
        ok, name, reason = accept_condition(revised or view["plan"], view.get("job"))
        _check(ok, reason, 409)
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
