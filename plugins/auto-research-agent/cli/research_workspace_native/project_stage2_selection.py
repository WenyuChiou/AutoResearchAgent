"""Confirmed UI choice composes the verified read view and existing intake cores."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json

from stage2_common import Stage2Error, canonical_hash
from stage1_deliverable.common import canonical
from stage2_workflow.interaction import record_interaction
from stage2_workflow.planning_handoff import prepare_planning_handoff
from stage3_plan.intake import admit_intake
from .project_intake_contract import BOUND_FIELDS, _fields
from .project_stage2_selection_view import ProjectStage2SelectionView
from .session_api import SessionApiError, _check


class ProjectStage2SelectionService(ProjectStage2SelectionView):
    """No filesystem, research, or execution authority comes from UI fields."""

    def _advance_selected_frontier(
        self, credential, project_ref, body, result, check_deadline
    ):
        # Run after the choice transaction commits; nested intake writes would
        # otherwise be overwritten by its earlier project-state snapshot.
        with self.intake._lock:
            _, binding, _, _, ack, _ = self._current(
                credential, project_ref, validate_frontier=False
            )
            state = self.intake._load(self.intake._principal(credential), project_ref)
            context = self._project_context(project_ref, state, binding)
            if context is None:
                return result
            _check(
                ack is not None and ack["request_sha256"] == result["request_sha256"],
                "stage2-selection-receipt-differs",
            )
            try:
                request = dict(
                    key="frontier-" + result["request_sha256"],
                    expected_activation_sha256=canonical_hash(context[1]),
                    expected_previous_head_sha256=body["workflow_head_sha256"],
                    new_workflow_head_sha256=result["workflow_head_sha256"],
                    check_deadline=check_deadline,
                )
                advanced = context[0].advance_frontier(project_ref, **request)
                if advanced["status"] != "saved":
                    advanced = context[0].recover_frontier(project_ref, **request)
                _check(
                    advanced["status"] == "saved", "stage2-selection-frontier-unsaved"
                )
                self._current(credential, project_ref)
            except (SessionApiError, Stage2Error, OSError) as error:
                raise SessionApiError(
                    "stage2-selection-frontier-needs-recovery", 409
                ) from error
            return result

    def select(self, credential, project_ref, body, *, check_deadline=None):
        _fields(
            body,
            BOUND_FIELDS
            | {
                "delivery_manifest_sha256",
                "workflow_head_sha256",
                "snapshot_sha256",
                "decision",
                "confirmed",
            },
        )
        _check(body["confirmed"] is True, "explicit-stage2-selection-required", 400)
        principal = self.intake._principal(credential)

        def reserve(state, _request_hash, actor):
            rows = self.intake.db.execute(
                "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=?",
                (actor, project_ref),
            ).fetchall()
            for row in rows:
                try:
                    prior = json.loads(row["receipt"])
                except (ValueError, TypeError, RecursionError) as error:
                    raise SessionApiError(
                        "stage2-selection-prior-intent-invalid"
                    ) from error
                _check(
                    isinstance(prior, dict) and isinstance(prior.get("request"), dict),
                    "stage2-selection-prior-intent-invalid",
                )
                digest = hashlib.sha256(
                    canonical({"kind": prior.get("kind"), "body": prior["request"]})
                ).hexdigest()
                _check(
                    digest == row["request_hash"] == prior.get("request_sha256"),
                    "stage2-selection-prior-intent-invalid",
                )
                if prior.get("kind") == "stage2-select":
                    version = prior["request"].get("input_version")
                    _check(
                        type(version) is int and version > 0,
                        "stage2-selection-prior-intent-invalid",
                    )
                    events = self.intake.db.execute(
                        "SELECT payload FROM intake_events WHERE project=? AND kind IN (?,?)",
                        (
                            project_ref,
                            "stage2-select-saved",
                            "stage2-select-registration-recovered",
                        ),
                    ).fetchall()
                    _check(
                        prior.get("status") == "saved"
                        and sum(
                            event["payload"] == canonical(prior).decode()
                            for event in events
                        )
                        == 1,
                        "stage2-selection-unresolved",
                    )

        def work(state, request_hash, actor):
            _, binding, delivery, workflow, ack, _ = self._current(
                credential, project_ref
            )
            _check(ack is None, "stage2-selection-already-recorded")
            manifest = delivery["manifest"]
            _check(
                body["delivery_manifest_sha256"] == binding["delivery_manifest_sha256"]
                and body["workflow_head_sha256"] == workflow["head_sha256"]
                and body["snapshot_sha256"] == manifest["snapshot_sha256"],
                "stage2-selection-view-stale",
            )
            decision = body["decision"]
            _check(
                isinstance(decision, dict) and decision.get("kind") == "select",
                "stage2-selection-required",
                400,
            )
            # _record verifies exact current recommendations before a workflow append.
            output = self.intake._path(project_ref, "stage2-choice-" + request_hash)
            _check(not output.exists(), "stage2-choice-requires-recovery")
            if check_deadline:
                check_deadline()
            output.mkdir()
            submission = dict(
                kind="Stage2ProjectHostUserSubmission",
                schema_version="1.0.0",
                project_ref=project_ref,
                input_version=state["input_version"],
                principal=actor,
                request_sha256=request_hash,
                received_at=datetime.now(timezone.utc).isoformat(),
                confirmed=True,
                decision=deepcopy(decision),
                workflow_manifest_sha256=workflow["manifest"]["manifest_sha256"],
                workflow_head_sha256=body["workflow_head_sha256"],
                snapshot_sha256=body["snapshot_sha256"],
                delivery_manifest_sha256=body["delivery_manifest_sha256"],
            )
            raw = json.dumps(submission, ensure_ascii=False, sort_keys=True).encode()
            message = output / "submission.json"
            with message.open("xb") as stream:
                stream.write(raw)
                stream.flush()
            try:
                result = record_interaction(
                    binding["workflow_root"],
                    binding["delivery_root"],
                    binding["delivery_manifest_sha256"],
                    decision,
                    message,
                    0,
                    "ui-choice-" + request_hash,
                    output / "interaction",
                    workflow["head_sha256"],
                    input_origin="projecthost-ui-submission",
                    expected_message_sha256=hashlib.sha256(raw).hexdigest(),
                    expected_project_ref=project_ref,
                    expected_input_version=state["input_version"],
                )
                interaction_sha = hashlib.sha256(
                    (output / "interaction" / "interaction.json").read_bytes()
                ).hexdigest()
                planning = prepare_planning_handoff(
                    binding["delivery_root"],
                    output / "interaction",
                    expected_delivery_manifest_sha256=binding[
                        "delivery_manifest_sha256"
                    ],
                    expected_interaction_file_sha256=interaction_sha,
                    output_dir=output / "planning",
                )
                admitted = admit_intake(
                    output / "planning",
                    binding["delivery_root"],
                    expected_manifest_sha256=planning["manifest"]["manifest_sha256"],
                )
            except (Stage2Error, OSError, ValueError) as error:
                raise SessionApiError("stage2-selection-needs-recovery", 409) from error
            _check(
                admitted["execution_authorized"] is False,
                "stage2-planning-authority-invalid",
            )
            receipt = dict(
                key=body["key"],
                request_sha256=request_hash,
                delivery_manifest_sha256=binding["delivery_manifest_sha256"],
                interaction_file_sha256=interaction_sha,
                planning_manifest_sha256=planning["manifest"]["manifest_sha256"],
                workflow_head_sha256=result["head_sha256"],
                artifact_ref="stage2-choice-" + request_hash,
                input_origin="projecthost-ui-submission",
                selection_status="recorded",
                planning_status="verified",
                execution_authorized=False,
            )
            state["stage2_selected_planning"] = receipt
            return receipt

        result = self.intake._perform(
            principal,
            project_ref,
            "stage2-select",
            deepcopy(body),
            work,
            check_deadline=check_deadline,
            reserve=reserve,
        )
        from .project_stage2_selection_recovery import recover_completed_selection

        result = recover_completed_selection(
            self, credential, project_ref, body, check_deadline=check_deadline
        )
        return self._advance_selected_frontier(
            credential, project_ref, body, result, check_deadline
        )
