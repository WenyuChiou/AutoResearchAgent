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
from .project_stage3_feedback import _reference
from .project_stage3_feedback import _rows as _feedback_rows
from .project_stage3_planning import SOURCE_FIELDS, default_key
from .session_api import SessionApiError, _check

MODE = "replan-from-revision"
DECISION = "revise-then-review"
RECEIPTS = ("decision_receipt_sha256", "plan_revision_receipt_sha256")
FIELDS = SOURCE_FIELDS | {"mode", *RECEIPTS}


def replan_key(base_key, decision_receipt, revision_receipt):
    return "stage3-replan-" + digest([base_key, decision_receipt, revision_receipt])


def _source(body, extra=()):
    return {
        name: body[name]
        for name in SOURCE_FIELDS | ({"request_sha256", *extra} & set(body))
    }


def _saved(item):
    return (
        item["status"] == "completed"
        and (item["evidence"] or {}).get("outcome") == "saved"
    )


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
        decision = next(
            (
                row
                for row in _decision_rows(jobs, base)
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
        """Before a dispatch: the displayed revision must still be the frozen one."""
        frozen = payload["revision_input"]
        with self.service.intake._lock:
            view = self.transport._view(credential, ref, check_deadline=check_deadline)
            jobs = self.service.bindings.get(ref)["jobs"]
            try:
                _, binding, _, ambiguous = _binding(jobs, ref, view)
            except SessionApiError:
                binding, ambiguous = None, True
            _check(
                not ambiguous
                and binding["plan_request_sha256"] == frozen["parent_request_sha256"]
                and binding[REVISION] == frozen["plan_revision_receipt_sha256"],
                "stage3-replan-revision-changed",
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
