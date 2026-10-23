"""Read-only, host-bound decision cards from a verified current Stage 2 package."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from stage2_common import Stage2Error
from stage2_workflow.decision_cards import derive_decision_cards
from stage2_workflow.delivery import inspect_delivery
from stage2_workflow.store import inspect_workflow
from stage2_workflow.ui_submission import valid_input_version
from stage3_plan.intake import admit_intake
from .project_stage2 import ProjectStage2Service
from .session_api import SessionApiError, _check, _hash


class ProjectStage2SelectionView:
    """Host configuration supplies paths; browser input supplies only a project ref."""

    def __init__(self, intake, bindings):
        self.intake = intake
        self.bindings = deepcopy(bindings)
        for ref, binding in self.bindings.items():
            _check(
                isinstance(ref, str) and isinstance(binding, dict),
                "selection-binding-invalid",
            )
            _check(
                set(binding)
                == {
                    "input_version",
                    "brief_sha256",
                    "workflow_root",
                    "delivery_root",
                    "delivery_manifest_sha256",
                },
                "selection-binding-shape",
            )
            _check(
                valid_input_version(binding["input_version"], allow_string=True),
                "selection-binding-version",
            )
            _check(
                _hash(binding["delivery_manifest_sha256"])
                and _hash(binding["brief_sha256"]),
                "selection-binding-hash",
            )

    def _project_context(self, project_ref, state, binding):
        service = ProjectStage2Service(self.intake)
        _, activation, _, root = service._activation_context(project_ref, state)
        _check(
            Path(binding["workflow_root"]).resolve() == (root / "workflow").resolve(),
            "stage2-selection-project-workflow-differs",
        )
        return service, activation

    def _current(self, credential, project_ref, *, validate_frontier=True):
        project = self.intake.read(credential, project_ref)
        binding = self.bindings.get(project_ref)
        _check(binding is not None, "stage2-selection-unconnected", 409)
        _check(
            type(project.get("input_version")) is type(binding["input_version"])
            and project.get("input_version") == binding["input_version"]
            and project.get("brief_sha256") == binding["brief_sha256"],
            "stage2-selection-project-stale",
        )
        try:
            delivery = inspect_delivery(
                binding["delivery_root"], binding["delivery_manifest_sha256"]
            )
            workflow = inspect_workflow(binding["workflow_root"])
        except (Stage2Error, OSError, ValueError) as error:
            raise SessionApiError("stage2-selection-source-invalid", 409) from error
        principal = self.intake._principal(credential)
        state = self.intake._load(principal, project_ref)
        context = self._project_context(project_ref, state, binding)
        ack = state.get("stage2_selected_planning")
        expected_head = (
            ack["workflow_head_sha256"]
            if ack
            else delivery["manifest"]["workflow_head_sha256"]
        )
        _check(
            workflow["head_sha256"] == expected_head
            and workflow["manifest"]["manifest_sha256"]
            == delivery["manifest"]["workflow_manifest_sha256"],
            "stage2-selection-workflow-stale",
        )
        _check(
            workflow["latest_snapshot"]["event"]["payload"]["snapshot_sha256"]
            == delivery["manifest"]["snapshot_sha256"],
            "stage2-selection-snapshot-stale",
        )
        if context:
            _check(
                context[1]["workflow_manifest_sha256"]
                == workflow["manifest"]["manifest_sha256"],
                "stage2-selection-project-manifest-differs",
            )
            if validate_frontier:
                frontier = context[0].binding(project_ref)
                _check(
                    frontier["workflow_head_sha256"] == expected_head,
                    "stage2-selection-project-frontier-differs",
                )
        admitted = None
        if ack:
            _check(
                ack["delivery_manifest_sha256"] == binding["delivery_manifest_sha256"],
                "stage2-selection-delivery-stale",
            )
            action = self.intake.db.execute(
                "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                (principal, project_ref, ack["key"]),
            ).fetchone()
            _check(
                action is not None and action["request_hash"] == ack["request_sha256"],
                "stage2-selection-receipt-missing",
            )
            saved = json.loads(action["receipt"])
            _check(
                saved["status"] == "saved"
                and all(saved.get(k) == v for k, v in ack.items()),
                "stage2-selection-receipt-differs",
            )
            output = self.intake._path(project_ref, ack["artifact_ref"])
            try:
                _check(
                    hashlib.sha256(
                        (output / "interaction" / "interaction.json").read_bytes()
                    ).hexdigest()
                    == ack["interaction_file_sha256"],
                    "stage2-selection-interaction-differs",
                )
                admitted = admit_intake(
                    output / "planning",
                    binding["delivery_root"],
                    expected_manifest_sha256=ack["planning_manifest_sha256"],
                )
            except (Stage2Error, OSError, ValueError) as error:
                raise SessionApiError(
                    "stage2-selection-retained-input-invalid", 409
                ) from error
        return project, binding, delivery, workflow, ack, admitted

    def read(self, credential, project_ref, *, check_deadline=None):
        with self.intake._lock:
            if check_deadline:
                check_deadline()
            project, binding, delivery, workflow, ack, admitted = self._current(
                credential, project_ref
            )
            result = dict(
                kind="Stage2SelectionView",
                project_ref=project_ref,
                input_version=project["input_version"],
                revision=project["revision"],
                brief_sha256=project["brief_sha256"],
                delivery_manifest_sha256=binding["delivery_manifest_sha256"],
                workflow_head_sha256=workflow["head_sha256"],
                snapshot_sha256=delivery["manifest"]["snapshot_sha256"],
                cards=derive_decision_cards(delivery["selection"]),
                planning_input=admitted,
                selection_receipt=deepcopy(ack),
                eligible=delivery["manifest"]["recommendation_candidate_versions"],
                delivery_status=delivery["manifest"]["delivery_status"],
                selection_status="recorded" if ack else "pending",
                planning_status="verified" if ack else "awaiting-valid-selection",
                input_origin="projecthost-ui-submission",
                identity_authenticated=False,
                execution_authorized=False,
            )
            if check_deadline:
                check_deadline()
            return result
