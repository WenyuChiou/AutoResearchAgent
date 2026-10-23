"""Recover only independently revalidated, completed frontier metadata."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json

from stage1_ledger.journal import canonical
from stage2_common import Stage2Error

from .session_api import SessionApiError, _check


def recover_completed_frontier(
    service,
    project_ref,
    *,
    key,
    expected_activation_sha256,
    expected_previous_head_sha256,
    new_workflow_head_sha256,
    check_deadline=None,
):
    """Use the original key and current project binding; unknown work stays held."""
    intake = service.intake
    _check(check_deadline is None or callable(check_deadline), "invalid-deadline", 400)
    with intake._lock:
        if check_deadline:
            check_deadline()
        intake.db.execute("BEGIN IMMEDIATE")
        try:
            row = intake.db.execute(
                "SELECT principal FROM intake_projects WHERE ref=?", (project_ref,)
            ).fetchone()
            _check(row is not None, "project-unavailable", 404)
            principal = row[0]
            state = intake._load(principal, project_ref)
            current = intake.binding(project_ref)
            semantic = dict(
                key=key,
                input_version=current["input_version"],
                brief_sha256=current["brief_sha256"],
                expected_activation_sha256=expected_activation_sha256,
                expected_previous_head_sha256=expected_previous_head_sha256,
                new_workflow_head_sha256=new_workflow_head_sha256,
            )
            digest = hashlib.sha256(
                canonical({"kind": "stage2-frontier", "body": semantic})
            ).hexdigest()
            row = intake.db.execute(
                "SELECT request_hash,receipt FROM intake_actions "
                "WHERE principal=? AND project=? AND key=?",
                (principal, project_ref, key),
            ).fetchone()
            _check(row is not None, "stage2-frontier-recovery-intent-missing")
            try:
                previous = json.loads(row["receipt"])
            except (ValueError, TypeError, RecursionError) as error:
                raise SessionApiError(
                    "stage2-frontier-recovery-intent-invalid"
                ) from error
            _check(
                isinstance(previous, dict)
                and row["request_hash"] == digest
                and previous.get("kind") == "stage2-frontier"
                and previous.get("project_ref") == project_ref
                and previous.get("key") == key
                and previous.get("request_sha256") == digest
                and canonical(previous.get("request")) == canonical(semantic),
                "stage2-frontier-recovery-request-differs",
            )
            if previous["status"] == "saved":
                _check(
                    any(
                        canonical(value) == canonical(previous)
                        for value in service._journal(
                            project_ref, "stage2-frontier-saved"
                        )
                    ),
                    "stage2-frontier-recovery-saved-receipt-differs",
                )
                intake.db.commit()
                return intake._receipt(previous, replayed=True)
            _check(
                previous["status"] == "execution-unknown"
                and previous.get("failure_phase") == "post-work-before-commit",
                "stage2-frontier-recovery-outcome-unverified",
            )
            failures = [
                value
                for value in service._journal(project_ref, "stage2-frontier-failed")
                if value.get("key") == key
            ]
            _check(
                len(failures) == 1 and canonical(failures[0]) == canonical(previous),
                "stage2-frontier-recovery-failure-receipt-differs",
            )
            try:
                current, activation, offer, root = service._activation_context(
                    project_ref, state
                )
                frontier = service._frontier(
                    project_ref, state, current, offer, activation
                )
                _check(
                    frontier["activation_sha256"] == expected_activation_sha256
                    and frontier["workflow_head_sha256"]
                    == expected_previous_head_sha256
                    and new_workflow_head_sha256 != expected_previous_head_sha256,
                    "stage2-frontier-recovery-cas-conflict",
                )
                service._inspect_frontier(
                    root,
                    activation,
                    expected_previous_head_sha256,
                    new_workflow_head_sha256,
                )
            except (Stage2Error, OSError) as error:
                raise SessionApiError(
                    "stage2-frontier-recovery-validation-failed"
                ) from error
            frontier.update(
                workflow_head_sha256=new_workflow_head_sha256,
                sequence=frontier["sequence"] + 1,
            )
            observation = dict(frontier=deepcopy(frontier), execution_authorized=False)
            _check(
                canonical(previous.get("output_observation")) == canonical(observation),
                "stage2-frontier-recovery-observation-differs",
            )
            receipt = deepcopy(previous)
            receipt.update(status="saved", **observation)
            receipt["recovered_from_receipt_sha256"] = hashlib.sha256(
                canonical(previous)
            ).hexdigest()
            receipt["registration_recovered_at"] = datetime.now(
                timezone.utc
            ).isoformat()
            if check_deadline:
                check_deadline()
            state["stage2_frontier"] = frontier
            state["revision"] += 1
            intake._save(state, "stage2-frontier-saved", receipt)
            intake.db.execute(
                "UPDATE intake_actions SET receipt=? WHERE principal=? AND project=? AND key=?",
                (canonical(receipt).decode(), principal, project_ref, key),
            )
            if check_deadline:
                check_deadline()
            intake.db.commit()
            return intake._receipt(receipt, replayed=True)
        except BaseException:
            intake.db.rollback()
            raise
