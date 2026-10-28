"""Durable UI preferences for conditional planning, separate from formal choice."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json

from stage1_ledger.journal import canonical
from stage2_common import Stage2Error
from stage2_workflow.direction_intent import (
    inspect_direction_intent,
    retain_direction_intent,
    validate_preferences,
)
from .project_intake_contract import BOUND_FIELDS, _fields, _text
from .session_api import SessionApiError, _check

KIND = "stage2-direction-intent"
FIELDS = BOUND_FIELDS | {
    "delivery_manifest_sha256",
    "workflow_head_sha256",
    "snapshot_sha256",
    "preferred_directions",
    "user_input",
    "conditions",
    "unresolved",
    "confirmed",
}


class ProjectStage2DirectionIntent:
    """Mixin using the same principal, intake journal, current view and paths."""

    def read(self, credential, project_ref, *, check_deadline=None):
        with self.intake._lock:
            result = super().read(
                credential, project_ref, check_deadline=check_deadline
            )
            principal = self.intake._principal(credential)
            ack = self.intake._load(principal, project_ref).get(
                "stage2_direction_intent"
            )
            if ack and result["selection_status"] != "recorded":
                self.direction_intent_context(
                    credential,
                    project_ref,
                    expected_intent_sha256=ack["intent_sha256"],
                    check_deadline=check_deadline,
                )
            elif result["selection_status"] == "recorded":
                ack = None
            result["direction_intent"] = deepcopy(ack)
            return result

    def _direction_source(self, credential, project_ref, body):
        project, binding, delivery, workflow, selected, _ = self._current(
            credential, project_ref
        )
        _check(selected is None, "direction-intent-formal-selection-already-recorded")
        _check(
            type(body["input_version"]) is type(project["input_version"])
            and body["input_version"] == project["input_version"]
            and body["brief_sha256"] == project["brief_sha256"]
            and body["delivery_manifest_sha256"] == binding["delivery_manifest_sha256"]
            and body["workflow_head_sha256"] == workflow["head_sha256"]
            and body["snapshot_sha256"] == delivery["manifest"]["snapshot_sha256"],
            "direction-intent-view-stale",
        )
        try:
            validate_preferences(delivery, body["preferred_directions"])
        except Stage2Error as error:
            raise SessionApiError(str(error), 409) from error
        return binding, delivery, workflow

    def _retain_direction(self, credential, project_ref, state, request_hash):
        pending = state["stage2_direction_intent_pending"]
        body = pending["request"]
        _check(
            pending["request_sha256"] == request_hash,
            "direction-intent-pending-differs",
        )
        binding, _, workflow = self._direction_source(credential, project_ref, body)
        submission = dict(
            deepcopy(body),
            kind="Stage2ProjectHostDirectionSubmission",
            schema_version="1.0.0",
            project_ref=project_ref,
            project_id=state["project_id"],
            base_revision=pending["base_revision"],
            received_at=pending["received_at"],
            principal=pending["principal"],
            request_sha256=request_hash,
            workflow_manifest_sha256=workflow["manifest"]["manifest_sha256"],
        )
        ref = "stage2-direction-" + request_hash
        intent = retain_direction_intent(
            self.intake._path(project_ref, ref), binding["delivery_root"], submission
        )
        ack = dict(
            kind="Stage2DirectionPlanningIntentReceipt",
            schema_version="1.0.0",
            status="saved",
            key=body["key"],
            request_sha256=request_hash,
            intent_sha256=hashlib.sha256(canonical(intent)).hexdigest(),
            submission_sha256=intent["submission_sha256"],
            advisory_manifest_sha256=intent["advisory_manifest_sha256"],
            artifact_ref=ref,
            mode="direction-advice",
            human_selection="pending",
            execution_authorized=False,
        )
        state["stage2_direction_intent"] = ack
        del state["stage2_direction_intent_pending"]
        return {k: v for k, v in ack.items() if k not in {"kind", "status"}}

    def direction_intent(self, credential, project_ref, body, *, check_deadline=None):
        _fields(body, FIELDS)
        _check(body["confirmed"] is True, "explicit-direction-intent-required", 400)
        _text(body["user_input"], 4000)
        for field in ("conditions", "unresolved"):
            _check(
                type(body[field]) is list and len(body[field]) <= 32,
                "direction-intent-list-invalid",
                400,
            )
            for text in body[field]:
                _text(text, 4000)
        principal = self.intake._principal(credential)

        def reserve(state, request_hash, actor):
            self._direction_source(credential, project_ref, body)
            _check(
                not state.get("stage2_direction_intent_pending"),
                "direction-intent-needs-recovery",
            )
            state["stage2_direction_intent_pending"] = dict(
                request={k: deepcopy(v) for k, v in body.items() if k != "revision"},
                request_sha256=request_hash,
                base_revision=body["revision"],
                principal=actor,
                received_at=datetime.now(timezone.utc).isoformat(),
            )

        try:
            result = self.intake._perform(
                principal,
                project_ref,
                KIND,
                deepcopy(body),
                lambda state, digest, actor: self._retain_direction(
                    credential, project_ref, state, digest
                ),
                reserve=reserve,
                check_deadline=check_deadline,
            )
            if result["status"] != "saved":
                result = self._recover_direction(
                    credential, project_ref, body, check_deadline
                )
            self.direction_intent_context(
                credential,
                project_ref,
                expected_intent_sha256=result["intent_sha256"],
                check_deadline=check_deadline,
            )
            return result
        except SessionApiError:
            raise
        except (Stage2Error, OSError, ValueError, KeyError) as error:
            raise SessionApiError(
                "direction-intent-retained-input-invalid", 409
            ) from error

    def _recover_direction(self, credential, project_ref, body, check_deadline):
        intake = self.intake
        principal = intake._principal(credential)
        semantic = {k: v for k, v in body.items() if k != "revision"}
        digest = hashlib.sha256(canonical(dict(kind=KIND, body=semantic))).hexdigest()
        with intake._lock:
            intake.db.execute("BEGIN IMMEDIATE")
            try:
                row = intake.db.execute(
                    "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                    (principal, project_ref, body["key"]),
                ).fetchone()
                _check(
                    row is not None and row["request_hash"] == digest,
                    "direction-intent-recovery-request-differs",
                )
                previous = json.loads(row["receipt"])
                _check(
                    previous["kind"] == KIND
                    and previous["request"] == semantic
                    and previous["status"]
                    in {"failed", "execution-unknown", "intent-recorded"},
                    "direction-intent-recovery-receipt-differs",
                )
                event_kind = KIND + (
                    "-intent" if previous["status"] == "intent-recorded" else "-failed"
                )
                events = intake.db.execute(
                    "SELECT payload FROM intake_events WHERE project=? AND kind=?",
                    (project_ref, event_kind),
                ).fetchall()
                _check(
                    sum(
                        event["payload"] == canonical(previous).decode()
                        for event in events
                    )
                    == 1,
                    "direction-intent-recovery-journal-differs",
                )
                state = intake._load(principal, project_ref)
                pending = state.get("stage2_direction_intent_pending")
                _check(
                    pending is not None
                    and pending["request"] == semantic
                    and pending["principal"] == principal
                    and state["revision"] == pending["base_revision"] + 1,
                    "direction-intent-recovery-stale",
                )
                if check_deadline:
                    check_deadline()
                result = self._retain_direction(credential, project_ref, state, digest)
                receipt = dict(
                    previous,
                    **result,
                    status="saved",
                    recovered_from_receipt_sha256=hashlib.sha256(
                        canonical(previous)
                    ).hexdigest(),
                )
                state["revision"] += 1
                intake._save(state, KIND + "-recovered", receipt)
                intake.db.execute(
                    "UPDATE intake_actions SET receipt=? WHERE principal=? AND project=? AND key=?",
                    (canonical(receipt).decode(), principal, project_ref, body["key"]),
                )
                if check_deadline:
                    check_deadline()
                intake.db.commit()
                return intake._receipt(receipt, replayed=True)
            except BaseException:
                intake.db.rollback()
                raise

    def direction_intent_context(
        self, credential, project_ref, *, expected_intent_sha256, check_deadline=None
    ):
        try:
            return self._direction_intent_context(
                credential,
                project_ref,
                expected_intent_sha256=expected_intent_sha256,
                check_deadline=check_deadline,
            )
        except SessionApiError:
            raise
        except (Stage2Error, OSError, ValueError, KeyError, TypeError) as error:
            raise SessionApiError(
                "direction-intent-retained-input-invalid", 409
            ) from error

    def _direction_intent_context(
        self, credential, project_ref, *, expected_intent_sha256, check_deadline=None
    ):
        with self.intake._lock:
            if check_deadline:
                check_deadline()
            principal = self.intake._principal(credential)
            state = self.intake._load(principal, project_ref)
            ack = state.get("stage2_direction_intent")
            _check(
                ack is not None and ack["intent_sha256"] == expected_intent_sha256,
                "direction-intent-not-current",
            )
            row = self.intake.db.execute(
                "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                (principal, project_ref, ack["key"]),
            ).fetchone()
            _check(
                row is not None and row["request_hash"] == ack["request_sha256"],
                "direction-intent-receipt-missing",
            )
            saved = json.loads(row["receipt"])
            _check(
                saved["kind"] == KIND
                and saved["status"] == "saved"
                and all(saved.get(k) == v for k, v in ack.items() if k != "kind"),
                "direction-intent-receipt-differs",
            )
            events = self.intake.db.execute(
                "SELECT payload FROM intake_events WHERE project=? AND kind IN (?,?)",
                (project_ref, KIND + "-saved", KIND + "-recovered"),
            ).fetchall()
            _check(
                sum(event["payload"] == canonical(saved).decode() for event in events)
                == 1,
                "direction-intent-journal-differs",
            )
            binding, _, workflow = self._direction_source(
                credential, project_ref, saved["request"]
            )
            output = self.intake._path(project_ref, ack["artifact_ref"])
            intent = inspect_direction_intent(
                output,
                binding["delivery_root"],
                expected_intent_sha256=expected_intent_sha256,
            )
            _check(
                intent["project_ref"] == project_ref
                and intent["project_id"] == state["project_id"]
                and intent["principal"] == principal
                and intent["request_sha256"] == row["request_hash"]
                and intent["workflow_manifest_sha256"]
                == workflow["manifest"]["manifest_sha256"]
                and all(
                    intent.get(k) == v
                    for k, v in saved["request"].items()
                    if k not in {"confirmed"}
                ),
                "direction-intent-source-differs",
            )
            if check_deadline:
                check_deadline()
            return dict(
                intent=intent,
                intent_sha256=expected_intent_sha256,
                advisory_dir=output / "advisory",
                advisory_manifest_sha256=intent["advisory_manifest_sha256"],
                delivery_dir=binding["delivery_root"],
                delivery_manifest_sha256=binding["delivery_manifest_sha256"],
            )
