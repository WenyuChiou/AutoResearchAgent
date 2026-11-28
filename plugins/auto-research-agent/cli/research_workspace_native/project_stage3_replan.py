"""Replan a saved Stage 3 plan from the researcher's manual revision (source mode).

``prepare|run|inspect|recover`` with ``mode: "replan-from-revision"`` create and
run one new planning job whose input is the displayed saved plan's newest manual
revision (its draft and the comments it cites), bound to a ``revise-then-review``
decision on that same revision. The original plans, comments and decisions stay
immutable and readable as history. ``prepare`` makes no call; ``run`` makes one
planning call through the configured adapter; an uncertain result is never resent.

Only the source mode (a saved Stage 2 selection) is supported. Every refusal that
needs no write happens before the checkpoint or journal intent is written.
"""

from copy import deepcopy

from stage3_plan.contracts import Stage3Error, digest
from stage3_plan.intake import admit_intake
from stage3_plan.preparation import sha256
from stage3_plan.prompts import RevisionContextTooLarge, build_prompt

from .project_intake_contract import _fields
from .project_stage3_decision import REVISION, _binding
from .project_stage3_decision import _rows as _decision_rows
from .project_stage3_decision import read_decisions
from .project_stage3_feedback import EDIT_FIELDS, _reference, fits_response
from .project_stage3_feedback import read_feedback
from .project_stage3_feedback import _rows as _feedback_rows
from .project_stage3_planning import SOURCE_FIELDS, default_key
from .session_api import SessionApiError, _check

MODE = "replan-from-revision"
DECISION = "revise-then-review"
RECEIPTS = ("decision_receipt_sha256", "plan_revision_receipt_sha256")
FIELDS = SOURCE_FIELDS | {"mode", *RECEIPTS}
MAX_CHAIN = 32
UNREADABLE = "stage3-replan-plan-unreadable"


def replan_key(base_key, decision_receipt, revision_receipt):
    return "stage3-replan-" + digest([base_key, decision_receipt, revision_receipt])


def _source(body, extra=()):
    return {
        name: body[name]
        for name in SOURCE_FIELDS | ({"request_sha256", *extra} & set(body))
    }


def _latest(rows, binding):
    """The last decision on this exact displayed revision, by server sequence.

    Only the latest decision counts: a later accept or return-to-stage2 on the
    same revision supersedes an earlier revise-then-review.
    """
    current = [row for row in rows if row["record"]["binding"] == binding]
    return max(current, key=lambda row: row["record"]["sequence"], default=None)


def _changes(parent, revised):
    """Every place the researcher's draft differs from the model's saved plan.

    Manual revisions can only replace question-level text fields (EDIT_FIELDS),
    and they can form a chain (parent_revision). Comparing the final draft with
    the saved (model-generated) parent plan gives the net edits relative to that
    previous plan, whatever the chain looked like.
    """
    before = {
        row.get("question_ref"): row
        for row in parent.get("question_plans", [])
        if type(row) is dict
    }
    changes = []
    for row in revised.get("question_plans", []):
        old = before.get(row.get("question_ref"), {})
        for field in sorted(EDIT_FIELDS):
            value = row.get(field)
            if type(value) is str and value != old.get(field):
                changes.append(
                    {
                        "question_ref": row["question_ref"],
                        "field": field,
                        "model_value": old.get(field)
                        if type(old.get(field)) is str
                        else "",
                        "researcher_value": value,
                    }
                )
    return changes


def _saved(item):
    return (
        item["status"] == "completed"
        and (item["evidence"] or {}).get("outcome") == "saved"
    )


def newest(transport, credential, ref, jobs, result, check_deadline=None):
    """Point the view at the newest saved replan; earlier plans become history.

    A replan job names its parent (the plan displayed when it was prepared) by
    request and manifest hash. Without a saved replan the view is unchanged.
    """
    intents = list(jobs.journal.snapshot(jobs.project_id)["intents"].values())
    previous = []
    for _ in range(MAX_CHAIN):
        job = result["job"]
        kids = [
            item
            for item in intents
            if item["method"] == jobs.method
            and _saved(item)
            and (item["payload"].get("revision_input") or {}).get(
                "parent_request_sha256"
            )
            == job["request_sha256"]
            and item["payload"]["revision_input"]["parent_plan_manifest_sha256"]
            == job["plan_manifest_sha256"]
        ]
        if not kids:
            break
        if len(kids) > 1:  # never chosen by an arbitrary rule
            result["replan_error"] = "stage3-replan-history-ambiguous"
            break
        kid = kids[0]
        body = _source(dict(result["default_request"], key=kid["payload"]["key"]))
        body.pop("request_sha256", None)
        frozen = kid["payload"]["revision_input"]
        try:
            body, child, plan, _ = transport._saved_job(
                credential, ref, jobs, body, kid, check_deadline
            )
        except (SessionApiError, Stage3Error, KeyError, ValueError, OSError) as error:
            # One unreadable new plan (for example after a Core upgrade without a
            # trusted pin) is reported on its own; the rest of the view and the
            # comment/revise/decide writes on the displayed plan keep working.
            result["unreadable_plans"] = [
                {
                    "key": kid["payload"]["key"],
                    "request_sha256": digest(kid["payload"]),
                    "error": getattr(error, "code", UNREADABLE),
                    "parent_request_sha256": frozen["parent_request_sha256"],
                    "from_revision_receipt_sha256": frozen[
                        "plan_revision_receipt_sha256"
                    ],
                    "from_decision_receipt_sha256": frozen["decision_receipt_sha256"],
                }
            ]
            break
        previous.append(
            {
                "job": job,
                "plan": result["plan"],
                "replanned_by": {
                    "key": body["key"],
                    "request_sha256": body["request_sha256"],
                    "from_revision_receipt_sha256": frozen[
                        "plan_revision_receipt_sha256"
                    ],
                    "from_decision_receipt_sha256": frozen["decision_receipt_sha256"],
                },
            }
        )
        result["job"], result["plan"] = child, plan
    if previous:
        result["previous_plans"] = previous
        for entry in previous:  # oldest bodies give way first; say so
            if fits_response(result):
                break
            entry["plan"] = {"omitted": "response-bound"}
    return result


class ProjectStage3Replan:
    """Replan operations; the transport supplies the displayed (newest) view."""

    def __init__(self, transport):
        self.transport = transport

    @property
    def service(self):
        return self.transport.service

    @staticmethod
    def _shape(body, extra=()):
        _fields(body, FIELDS | set(extra))
        _check(body["mode"] == MODE, "stage3-replan-mode-invalid", 400)
        for name in RECEIPTS:
            try:
                sha256(body[name])
            except Stage3Error:
                raise SessionApiError("stage3-replan-receipt-invalid", 400) from None

    def _job_item(self, credential, ref, body, check_deadline):
        """Version-checked current state and the job for this key (may be None)."""
        service = self.service
        ack = service._current(credential, ref, None, check_deadline)[2]
        _check(ack is not None, "stage3-replan-direction-mode-unsupported", 409)
        current = service._current(credential, ref, _source(body), check_deadline)
        _check(current[4] is not None, "stage3-planning-unconfigured")
        _check(
            body["key"]
            == replan_key(
                default_key(
                    ref, body["input_version"], body["selection_request_sha256"]
                ),
                body["decision_receipt_sha256"],
                body["plan_revision_receipt_sha256"],
            ),
            "stage3-replan-key-differs",
            400,
        )
        jobs = current[4]["jobs"]
        item = jobs.journal.snapshot(jobs.project_id)["intents"].get(
            jobs._key(body["key"])
        )
        if item is not None:
            frozen = item["payload"].get("revision_input") or {}
            _check(
                item["method"] == jobs.method
                and all(frozen.get(name) == body[name] for name in RECEIPTS),
                "stage3-replan-key-payload-differs",
                409,
            )
        return current, item

    @staticmethod
    def _revision_input(jobs, ref, view, body):
        base, binding, plan, ambiguous = _binding(jobs, ref, view)
        _check(not ambiguous, "stage3-decision-revision-ambiguous", 409)
        receipt = binding[REVISION]
        _check(receipt is not None, "stage3-replan-revision-required", 409)
        _check(
            body["plan_revision_receipt_sha256"] == receipt,
            "stage3-replan-revision-changed",
            409,
        )
        rows = _decision_rows(jobs, base)
        decision = next(
            (
                row
                for row in rows
                if row["receipt_sha256"] == body["decision_receipt_sha256"]
            ),
            None,
        )
        _check(
            decision is not None and decision["record"]["decision"] == DECISION,
            "stage3-replan-decision-required",
            409,
        )
        _check(
            decision["record"]["binding"] == binding,
            "stage3-replan-decision-differs",
            409,
        )
        _check(
            _latest(rows, binding)["record"]["decision"] == DECISION,
            "stage3-replan-decision-superseded",
            409,
        )
        feedback = _feedback_rows(jobs, base)
        revision = next(row for row in feedback if row["receipt_sha256"] == receipt)
        comments = [
            _reference(feedback, value, "comment")
            for value in revision["record"]["comments"]
        ]
        value = {
            "plan_revision_receipt_sha256": receipt,
            "decision_receipt_sha256": decision["receipt_sha256"],
            "parent_plan_manifest_sha256": base["parent_plan_manifest_sha256"],
            "parent_request_sha256": base["plan_request_sha256"],
            "plan": deepcopy(plan),
            "changes": _changes(view["plan"], plan),
            "comments": [
                {"question_ref": row["question_ref"], "text": row["text"]}
                for row in comments
            ],
        }
        value["sha256"] = digest(value)
        return value

    @staticmethod
    def _fits(source, key, revision_input):
        intake = admit_intake(
            source["package"],
            source["delivery"],
            expected_manifest_sha256=source["manifest_sha256"],
        )
        try:
            build_prompt(
                intake,
                plan_id="host-plan-" + digest(key),
                version=1,
                schema_version="1.1.0",
                revision_input=revision_input,
            )
        except RevisionContextTooLarge:
            raise SessionApiError("stage3-replan-input-too-large", 413) from None

    def prepare(self, credential, ref, body, *, check_deadline=None):
        """Freeze the displayed revision into a new job intent; zero calls."""
        self._shape(body)
        service = self.service
        with service.intake._lock:
            current, item = self._job_item(credential, ref, body, check_deadline)
            if item is None:
                view = self.transport._view(
                    credential, ref, check_deadline=check_deadline
                )
                jobs = current[4]["jobs"]
                # A newer plan exists but cannot be read: never fork its parent.
                _check(not view.get("unreadable_plans"), UNREADABLE, 409)
                revision_input = self._revision_input(jobs, ref, view, body)
                _, source, _ = service._job(current, body["key"])
                self._fits(source, body["key"], revision_input)
                current = service._current(
                    credential, ref, _source(body), check_deadline, write=True
                )
                configured, source, _ = service._job(current, body["key"])
                result = service._create(
                    configured, source, body["key"], revision_input=revision_input
                )
            else:
                configured, _, _ = service._job(current, body["key"])
                result = configured["jobs"].inspect(
                    body["key"],
                    expected_request_sha256=digest(item["payload"]),
                    current_checkpoint=item["payload"]["checkpoint"],
                )
            return service._public(ref, result)

    def _prepared(self, credential, ref, body, check_deadline):
        with self.service.intake._lock:
            _, item = self._job_item(credential, ref, body, check_deadline)
            _check(item is not None, "stage3-job-not-prepared")
        return item

    def inspect(self, credential, ref, body, *, check_deadline=None):
        self._shape(body, {"request_sha256"})
        self._prepared(credential, ref, body, check_deadline)
        return self.service.inspect(
            credential, ref, _source(body), check_deadline=check_deadline
        )

    def check_current(self, credential, ref, payload, check_deadline=None):
        """Before a dispatch: the displayed revision must still be the frozen one,
        and the latest decision on it must still be revise-then-review."""
        frozen = payload["revision_input"]
        with self.service.intake._lock:
            view = self.transport._view(credential, ref, check_deadline=check_deadline)
            jobs = self.service.bindings.get(ref)["jobs"]
            try:
                base, binding, _, ambiguous = _binding(jobs, ref, view)
            except SessionApiError:
                binding, ambiguous = None, True
            _check(
                not ambiguous
                and binding["plan_request_sha256"] == frozen["parent_request_sha256"]
                and binding[REVISION] == frozen["plan_revision_receipt_sha256"],
                "stage3-replan-revision-changed",
                409,
            )
            latest = _latest(_decision_rows(jobs, base), binding)
            # The frozen decision itself must still be the latest one: a later
            # decision (even another revise-then-review) needs a new prepare.
            _check(
                latest is not None
                and latest["record"]["decision"] == DECISION
                and latest["receipt_sha256"] == frozen["decision_receipt_sha256"],
                "stage3-replan-decision-superseded",
                409,
            )

    def admit(self, credential, ref, body, *, check_deadline=None):
        """Inspect for the run admission, refusing a changed revision before ack."""
        job = self.inspect(credential, ref, body, check_deadline=check_deadline)
        if job["status"] == "intent-recorded":
            item = self._prepared(credential, ref, body, check_deadline)
            self.check_current(credential, ref, item["payload"], check_deadline)
        return job

    def run(self, credential, ref, body, *, check_deadline=None):
        self._shape(body, {"request_sha256", "confirmed"})
        _check(body["confirmed"] is True, "explicit-stage3-planning-required", 400)
        self._prepared(credential, ref, body, check_deadline)
        return self.service.run(
            credential,
            ref,
            _source(body, {"confirmed"}),
            check_deadline=check_deadline,
            before_dispatch=lambda payload: self.check_current(
                credential, ref, payload, check_deadline
            ),
        )

    def recover(
        self,
        credential,
        ref,
        body,
        *,
        expected_plan_manifest_sha256,
        check_deadline=None,
    ):
        self._shape(body, {"request_sha256"})
        self._prepared(credential, ref, body, check_deadline)
        return self.service.recover(
            credential,
            ref,
            _source(body),
            expected_plan_manifest_sha256=expected_plan_manifest_sha256,
            check_deadline=check_deadline,
        )

    def describe(self, credential, ref, view, jobs, check_deadline=None):
        """The ``replan`` view field, or None when nothing about it has changed."""
        try:
            base, binding, _, ambiguous = _binding(jobs, ref, view)
            rows = _decision_rows(jobs, base)
        except SessionApiError as error:
            return {"error": error.code}
        receipt = binding[REVISION]
        if receipt is None and not ambiguous and "previous_plans" not in view:
            return None
        latest = None if ambiguous else _latest(rows, binding)
        decisions = (
            [latest["receipt_sha256"]]
            if latest is not None and latest["record"]["decision"] == DECISION
            else []
        )
        out = {
            "available": False,
            "reason": None,
            "request": None,
            "job": None,
            "parent_plan_manifest_sha256": base["parent_plan_manifest_sha256"],
            "from_revision_receipt_sha256": receipt,
            "from_decision_receipt_sha256": None
            if ambiguous or not decisions
            else decisions[-1],
        }
        if view.get("planning_mode") == "direction-intent":
            out["reason"] = "stage3-replan-direction-mode-unsupported"
        elif view.get("unreadable_plans"):
            out["reason"] = UNREADABLE
        elif ambiguous:
            out["reason"] = "stage3-decision-revision-ambiguous"
        elif receipt is None:
            out["reason"] = "stage3-replan-revision-required"
        elif latest is None:
            out["reason"] = "stage3-replan-decision-required"
        elif not decisions:
            out["reason"] = "stage3-replan-decision-superseded"
        else:
            default = view["default_request"]
            request = dict(
                _source(default),
                mode=MODE,
                key=replan_key(default["key"], decisions[-1], receipt),
                decision_receipt_sha256=decisions[-1],
                plan_revision_receipt_sha256=receipt,
            )
            request.pop("request_sha256", None)
            item = jobs.journal.snapshot(jobs.project_id)["intents"].get(
                jobs._key(request["key"])
            )
            if item is not None:
                request["request_sha256"] = digest(item["payload"])
                try:
                    out["job"] = self.service.inspect(
                        credential, ref, _source(request), check_deadline=check_deadline
                    )
                except (SessionApiError, Stage3Error) as error:
                    out["job"] = {
                        "error": getattr(error, "code", "stage3-replan-job-unreadable")
                    }
            out["request"] = request
            out["available"] = True
        return out

    def decorate(self, credential, ref, view, jobs, check_deadline=None):
        """Add history readbacks and the ``replan`` field when they fit."""
        if view.get("previous_plans"):
            enriched = []
            for entry in view["previous_plans"]:
                entry = dict(entry)
                if "omitted" not in entry["plan"]:
                    old = dict(view, job=entry["job"], plan=entry["plan"])
                    for name, read in (
                        ("feedback", read_feedback),
                        ("host_decision", read_decisions),
                    ):
                        try:
                            entry[name] = read(jobs, ref, old)
                        except SessionApiError as error:
                            entry[name] = {"error": error.code}
                enriched.append(entry)
            candidate = dict(view, previous_plans=enriched)
            if fits_response(candidate):
                view = candidate
        described = self.describe(credential, ref, view, jobs, check_deadline)
        if described is not None:
            candidate = dict(view, replan=described)
            if fits_response(candidate):
                view = candidate
        return view
