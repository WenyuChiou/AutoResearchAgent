"""User comments and manual plan revisions on the existing owned journal.

These records are not native messages, model output, review acceptance or an
execution grant. Original planning packages remain immutable. A revision is an
explicit user-authored draft, with its parent and comment receipts preserved.
"""

from copy import deepcopy
import json

from stage3_plan.contracts import canonical_bytes, digest
from stage3_plan.jobs import POLICY

from .project_intake_contract import _fields
from .http import MAX_RESPONSE
from .session_api import _check


METHOD = "stage3/project-host-feedback/1"
MAX_RECORDS = 32
BINDING_FIELDS = {
    "revision",
    "input_version",
    "brief_sha256",
    "parent_plan_manifest_sha256",
    "parent_plan_sha256",
    "plan_request_sha256",
}
EDIT_FIELDS = {
    "method",
    "materials",
    "design",
    "analysis",
    "interpretation",
    "validation",
    "minimum_deliverable",
}


def fits_response(value):
    """Match the Host wire encoding, with room for connection-state changes."""
    raw = json.dumps(value, ensure_ascii=True, allow_nan=False).encode("utf8")
    return len(raw) <= MAX_RESPONSE - 1024


def _text(value, name, limit=1800):
    _check(type(value) is str and bool(value.strip()), name + "-required", 400)
    _check(len(value.encode("utf8")) <= limit, name + "-too-long", 400)
    return value


def _context(ref, view):
    job, plan = view.get("job") or {}, view.get("plan")
    _check(
        type(plan) is dict
        and job.get("outcome") == "saved"
        and job.get("plan_manifest_sha256")
        and job.get("request_sha256"),
        "stage3-feedback-saved-plan-required",
        409,
    )
    return {
        "project_ref": ref,
        **{name: view[name] for name in ("revision", "input_version", "brief_sha256")},
        "parent_plan_manifest_sha256": job["plan_manifest_sha256"],
        "parent_plan_sha256": digest(plan),
        "plan_request_sha256": job["request_sha256"],
    }


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
            record.get("kind") in {"comment", "revision"}
            and record.get("request_sha256") == digest(record.get("request"))
            and item["request_identity"] is None
            and item["record_sha256"]
            == digest(
                {
                    name: item[name]
                    for name in ("key", "method", "payload", "request_identity")
                }
            )
            and item["key"] == _key(binding, record["kind"], record["request"]["key"]),
            "stage3-feedback-record-differs",
            409,
        )
        rows.append(
            {"receipt_sha256": item["record_sha256"], "record": deepcopy(record)}
        )
    _check(len(rows) <= MAX_RECORDS, "stage3-feedback-record-bound", 409)
    return rows


def _key(binding, kind, key):
    return "stage3-feedback-" + digest([binding, kind, key])


def _reference(rows, ref, kind):
    _fields(ref, {"key", "sha256"})
    matched = [
        row
        for row in rows
        if row["record"]["kind"] == kind
        and row["record"]["request"]["key"] == ref["key"]
    ]
    _check(
        len(matched) == 1 and matched[0]["receipt_sha256"] == ref["sha256"],
        "stage3-feedback-parent-receipt-differs",
        409,
    )
    return matched[0]["record"]


def read_feedback(jobs, ref, view):
    """Read only records for the currently verified saved planning package."""
    binding = _context(ref, view)
    return {
        "kind": "ProjectStage3PlanningFeedbackView",
        "schema_version": 1,
        "binding": binding,
        "records": _rows(jobs, binding),
        **POLICY,
    }


def record_feedback(jobs, ref, view, body, action, check_deadline=None):
    """Append once; replay uses the stored record and never a planning callback.

    The caller holds the same intake lock used to authenticate/read the parent.
    Journal.record_intent supplies its existing atomic transaction and owner
    checks. This local-record method is never dispatched as a native request.
    """
    kind = {"comment": "comment", "revise": "revision"}[action]
    extra = (
        {"text", "question_ref"}
        if kind == "comment"
        else {"comments", "parent_revision", "changes"}
    )
    _fields(body, BINDING_FIELDS | {"key"} | extra)
    _text(body["key"], "stage3-feedback-key", 128)
    binding = _context(ref, view)
    _check(
        all(
            type(body[name]) is type(binding[name]) and body[name] == binding[name]
            for name in BINDING_FIELDS
        ),
        "stage3-feedback-version-differs",
        409,
    )
    rows = _rows(jobs, binding)
    key = _key(binding, kind, body["key"])
    existing = next(
        (
            row
            for row in rows
            if row["record"]["kind"] == kind
            and row["record"]["request"]["key"] == body["key"]
        ),
        None,
    )
    if existing:
        _check(
            existing["record"]["request_sha256"] == digest(body),
            "stage3-feedback-key-payload-differs",
            409,
        )
        return dict(existing, replayed=True, **POLICY)
    _check(len(rows) < MAX_RECORDS, "stage3-feedback-record-bound", 409)
    plan = view["plan"]
    questions = {row["question_ref"]: row for row in plan.get("question_plans", [])}
    record = {
        "kind": kind,
        "schema_version": 1,
        "binding": binding,
        "request": deepcopy(body),
        "request_sha256": digest(body),
        "input_source": "project-host-user-submission",
        "native_message": False,
        "model_generated": False,
        **POLICY,
    }
    if kind == "comment":
        _text(body["text"], "stage3-feedback-text")
        _check(
            body["question_ref"] is None or body["question_ref"] in questions,
            "stage3-feedback-question-differs",
            409,
        )
        record.update(text=body["text"], question_ref=body["question_ref"])
    else:
        # Bound draft copies without hiding a previously valid original plan.
        _check(len(canonical_bytes(plan)) <= 262144, "stage3-feedback-plan-bound", 413)
        refs, changes = body["comments"], body["changes"]
        _check(
            type(refs) is list and 0 < len(refs) <= 8,
            "stage3-feedback-comments-required",
            400,
        )
        comments = [_reference(rows, value, "comment") for value in refs]
        _check(
            len({digest(value) for value in refs}) == len(refs),
            "stage3-feedback-duplicate-comment",
            400,
        )
        parent = (
            None
            if body["parent_revision"] is None
            else _reference(rows, body["parent_revision"], "revision")
        )
        revised = deepcopy(plan if parent is None else parent["plan"])
        revised_questions = {
            row["question_ref"]: row for row in revised.get("question_plans", [])
        }
        _check(
            type(changes) is list and 0 < len(changes) <= 8,
            "stage3-feedback-changes-required",
            400,
        )
        seen = set()
        for change in changes:
            _check(
                type(change) is dict
                and set(change) == {"question_ref", "field", "value"},
                "stage3-feedback-change-invalid",
                400,
            )
            _check(
                type(change["question_ref"]) is str and type(change["field"]) is str,
                "stage3-feedback-change-invalid",
                400,
            )
            target = (change["question_ref"], change["field"])
            _check(
                target not in seen
                and target[0] in revised_questions
                and target[1] in EDIT_FIELDS
                and type(revised_questions[target[0]].get(target[1])) is str,
                "stage3-feedback-change-invalid",
                400,
            )
            _text(change["value"], "stage3-feedback-change")
            seen.add(target)
            revised_questions[target[0]][target[1]] = change["value"]
        _check(
            all(
                comment["question_ref"] is None
                or comment["question_ref"] in {target[0] for target in seen}
                for comment in comments
            ),
            "stage3-feedback-comment-scope-differs",
            409,
        )
        record.update(
            revision_number=2 if parent is None else parent["revision_number"] + 1,
            parent_revision=deepcopy(body["parent_revision"]),
            comments=deepcopy(refs),
            changes=deepcopy(changes),
            plan=revised,
            authoring_mode="manual-planning-draft",
            original_markdown_preserved=True,
            comment_texts=[comment["text"] for comment in comments],
        )
    pending = {
        "receipt_sha256": "0" * 64,
        "record": record,
        "replayed": False,
        **POLICY,
    }
    projected = dict(read_feedback(jobs, ref, view), records=rows + [pending])
    _check(
        fits_response(pending) and fits_response(dict(view, feedback=projected)),
        "stage3-feedback-response-bound",
        413,
    )
    if check_deadline:
        check_deadline()
    state = jobs.journal.snapshot(jobs.project_id)
    item = jobs.journal.record_intent(
        jobs.project_id,
        jobs.owner,
        key,
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
