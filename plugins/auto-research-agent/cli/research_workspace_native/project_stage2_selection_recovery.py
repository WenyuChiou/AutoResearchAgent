"""Metadata-only recovery of a completed, independently reopened UI choice."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json

from stage1_ledger.journal import canonical
from stage2_workflow.delivery import inspect_delivery
from stage2_workflow.store import inspect_workflow
from stage2_workflow.ui_submission import UI_MESSAGE_FILE, read_ui_submission
from stage3_plan.intake import admit_intake
from .session_api import SessionApiError, _check


def recover_completed_selection(
    service, credential, project_ref, body, *, check_deadline=None
):
    """Same key resumes registration only; unknown core outcomes stay blocked."""
    intake = service.intake
    principal = intake._principal(credential)
    _check(check_deadline is None or callable(check_deadline), "invalid-deadline", 400)
    with intake._lock:
        if check_deadline:
            check_deadline()
        intake.db.execute("BEGIN IMMEDIATE")
        try:
            row = intake.db.execute(
                "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                (principal, project_ref, body["key"]),
            ).fetchone()
            _check(row is not None, "stage2-selection-recovery-intent-missing")
            try:
                previous = json.loads(row["receipt"])
            except (ValueError, TypeError, RecursionError) as error:
                raise SessionApiError(
                    "stage2-selection-recovery-intent-invalid"
                ) from error
            semantic = {k: v for k, v in body.items() if k != "revision"}
            expected = hashlib.sha256(
                canonical({"kind": "stage2-select", "body": semantic})
            ).hexdigest()
            _check(
                isinstance(previous, dict)
                and row["request_hash"] == expected
                and previous.get("kind") == "stage2-select"
                and previous.get("project_ref") == project_ref
                and previous.get("key") == body["key"]
                and previous.get("request_sha256") == expected
                and canonical(previous.get("request")) == canonical(semantic),
                "stage2-selection-recovery-request-differs",
            )
            events = intake.db.execute(
                "SELECT kind,payload FROM intake_events WHERE project=? AND kind IN (?,?,?)",
                (
                    project_ref,
                    "stage2-select-failed",
                    "stage2-select-saved",
                    "stage2-select-registration-recovered",
                ),
            ).fetchall()
            try:
                events = [
                    (event["kind"], json.loads(event["payload"])) for event in events
                ]
            except (ValueError, TypeError, RecursionError) as error:
                raise SessionApiError(
                    "stage2-selection-recovery-journal-invalid"
                ) from error
            _check(
                all(isinstance(value, dict) for _, value in events),
                "stage2-selection-recovery-journal-invalid",
            )
            if previous["status"] == "saved":
                saved_events = [
                    value
                    for kind, value in events
                    if kind
                    in {"stage2-select-saved", "stage2-select-registration-recovered"}
                    and value.get("key") == body["key"]
                ]
                _check(
                    len(saved_events) == 1
                    and canonical(saved_events[0]) == canonical(previous),
                    "stage2-selection-recovery-saved-receipt-differs",
                )
                if check_deadline:
                    check_deadline()
                intake.db.commit()
                return intake._receipt(previous, replayed=True)
            _check(
                previous["status"] == "execution-unknown"
                and previous.get("failure_phase") == "post-work-before-commit",
                "stage2-selection-recovery-outcome-unverified",
            )
            failures = [
                value
                for kind, value in events
                if kind == "stage2-select-failed" and value.get("key") == body["key"]
            ]
            _check(
                len(failures) == 1 and canonical(failures[0]) == canonical(previous),
                "stage2-selection-recovery-failure-receipt-differs",
            )
            state = intake._load(principal, project_ref)
            _check(
                state["revision"] == body["revision"] + 1
                and state["input_version"] == body["input_version"],
                "stage2-selection-recovery-stale",
            )
            brief_row, _, _ = intake._brief(state)
            binding = service.bindings.get(project_ref)
            _check(
                binding is not None
                and binding["input_version"] == state["input_version"]
                and binding["brief_sha256"]
                == brief_row["sha256"]
                == body["brief_sha256"],
                "stage2-selection-recovery-project-differs",
            )
            # Validate ownership before recovering any canonical project metadata.
            context = service._project_context(project_ref, state, binding)
            ack = deepcopy(previous["output_observation"])
            _check(
                set(ack)
                == {
                    "key",
                    "request_sha256",
                    "delivery_manifest_sha256",
                    "interaction_file_sha256",
                    "planning_manifest_sha256",
                    "workflow_head_sha256",
                    "artifact_ref",
                    "input_origin",
                    "selection_status",
                    "planning_status",
                    "execution_authorized",
                },
                "stage2-selection-recovery-observation-shape",
            )
            _check(
                ack["key"] == body["key"]
                and ack["request_sha256"] == expected
                and ack["artifact_ref"] == "stage2-choice-" + expected
                and ack["delivery_manifest_sha256"]
                == binding["delivery_manifest_sha256"]
                == body["delivery_manifest_sha256"]
                and ack["input_origin"] == "projecthost-ui-submission"
                and ack["execution_authorized"] is False,
                "stage2-selection-recovery-observation-differs",
            )
            delivery = inspect_delivery(
                binding["delivery_root"], binding["delivery_manifest_sha256"]
            )
            workflow = inspect_workflow(
                binding["workflow_root"], expected_head=ack["workflow_head_sha256"]
            )
            _check(
                context[1]["workflow_manifest_sha256"]
                == workflow["manifest"]["manifest_sha256"]
                == delivery["manifest"]["workflow_manifest_sha256"]
                and workflow["latest_snapshot"]["event"]["payload"]["snapshot_sha256"]
                == body["snapshot_sha256"],
                "stage2-selection-recovery-source-differs",
            )
            output = intake._path(project_ref, ack["artifact_ref"])
            interaction_raw = (output / "interaction" / "interaction.json").read_bytes()
            _check(
                hashlib.sha256(interaction_raw).hexdigest()
                == ack["interaction_file_sha256"],
                "stage2-selection-recovery-interaction-differs",
            )
            submission = read_ui_submission(
                (output / "interaction" / UI_MESSAGE_FILE).read_bytes()
            )
            _check(
                submission["project_ref"] == project_ref
                and submission["principal"] == principal
                and submission["input_version"] == body["input_version"]
                and submission["request_sha256"] == expected
                and submission["decision"] == body["decision"]
                and submission["workflow_head_sha256"] == body["workflow_head_sha256"],
                "stage2-selection-recovery-origin-differs",
            )
            admitted = admit_intake(
                output / "planning",
                binding["delivery_root"],
                expected_manifest_sha256=ack["planning_manifest_sha256"],
            )
            _check(
                admitted["execution_authorized"] is False,
                "stage2-selection-recovery-authority-invalid",
            )
            if check_deadline:
                check_deadline()
            receipt = deepcopy(previous)
            receipt.update(status="saved", **ack)
            receipt["recovered_from_receipt_sha256"] = hashlib.sha256(
                canonical(previous)
            ).hexdigest()
            receipt["registration_recovered_at"] = datetime.now(
                timezone.utc
            ).isoformat()
            state["stage2_selected_planning"] = ack
            state["revision"] += 1
            intake._save(state, "stage2-select-registration-recovered", receipt)
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
