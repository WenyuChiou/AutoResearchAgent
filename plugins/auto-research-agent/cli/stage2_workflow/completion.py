"""Inspect retained Stage 2 completion evidence without executing research."""

from pathlib import Path

from stage2_check.contracts import decode_json
from stage2_common import Stage2Error, canonical_hash
from .content_gate import derive_content_gate
from .delivery import inspect_delivery
from .evaluation_delivery import inspect_evaluated_delivery


def inspect_completion(
    delivery_dir,
    expected_manifest_sha256,
    *,
    evaluation_dir=None,
    expected_evaluation_manifest_sha256=None,
):
    """Recompute readiness; invalid receipts reject, missing work stays incomplete.

    Optional assessment must assess the exact inspected delivery selection and
    bind the retained workflow head or its separate delivery checker head.
    This establishes retained evidence completeness, never scientific truth,
    native execution, formal A/B readiness, or permission to begin Stage 3.
    """
    if (evaluation_dir is None) != (expected_evaluation_manifest_sha256 is None):
        raise Stage2Error("completion-evaluation-receipt-required")
    delivery = inspect_delivery(delivery_dir, expected_manifest_sha256)
    manifest, selection = delivery["manifest"], delivery["selection"]
    gate = derive_content_gate(selection)
    blockers = list(gate["blocking_items"])
    local_ready = delivery["reconciliation"]["local_reconciliation_ready"]
    if not local_ready:
        blockers.append(
            {
                "check_id": "local-reconciliation",
                "reason": "Complete the current independent direction reviews and reconciliation.",
            }
        )
    research_ready = gate["status"] == "content-complete" and local_ready
    status, dimensions, audit_status = "missing", None, "assessment-incomplete"
    evaluation_manifest = None
    if evaluation_dir is not None:
        root = Path(evaluation_dir).resolve()
        try:
            evaluation_manifest = inspect_evaluated_delivery(
                root, expected_manifest_sha256=expected_evaluation_manifest_sha256
            )
            core = decode_json(
                (root / "core_selection.json").read_bytes(), "core selection"
            )
            projection = decode_json(
                (root / "evaluation_projection.json").read_bytes(),
                "evaluation projection",
            )
        except Stage2Error:
            raise
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise Stage2Error("completion-evaluation-invalid") from error
        if (
            evaluation_manifest.get("kind") != "Stage2EvaluatedDelivery"
            or evaluation_manifest.get("schema_version") != "3.0.0"
            or core != selection
            or evaluation_manifest.get("core_selection_sha256")
            != canonical_hash(selection)
            or evaluation_manifest.get("event_head")
            not in {
                manifest["workflow_head_sha256"],
                manifest["delivery_checker_event_head_sha256"],
            }
            or evaluation_manifest.get("stored_packet_sha256")
            != delivery["checker"]["manifest"]["stored_packet_sha256"]
        ):
            raise Stage2Error("completion-evaluation-delivery-binding-mismatch")
        # The replay inspector reconstructs this projection from source-bound
        # R1/R2 and required ADJ/audit evidence. Manifest status flags are ignored.
        status = projection["evaluation_status"]
        dimensions = projection["dimensions"]
        audit_status = (
            "required"
            if status == "audit-required"
            else (
                projection["rows"][0]["final"]["audit_status"]
                if projection["rows"]
                else "assessment-incomplete"
            )
        )
        if status == "completed" and any(
            row["score"] is None for row in dimensions.values()
        ):
            status = "unknown"
    if status != "completed":
        blockers.append(
            {
                "check_id": "independent-assessment",
                "reason": {
                    "missing": "No independently assessed delivery and external manifest receipt were supplied.",
                    "audit-required": "The required named audit is pending; retained scores remain provisional.",
                    "unknown": "Necessary assessment evidence is unknown; null scores are not zero.",
                }.get(
                    status,
                    "Independent R1/R2 and required adjudication assessment is incomplete.",
                ),
            }
        )
    return {
        "kind": "Stage2Completion",
        "schema_version": "1.0.0",
        "research_delivery_ready": research_ready,
        "assessment_status": status,
        "assessment_dimensions": dimensions,
        "audit_status": audit_status,
        "stage2_complete": research_ready and status == "completed",
        "blockers": blockers,
        "content_gate": gate,
        "delivery_manifest_sha256": expected_manifest_sha256,
        "evaluation_manifest_sha256": expected_evaluation_manifest_sha256,
        "evaluation_bundle_sha256": evaluation_manifest["bundle_sha256"]
        if evaluation_manifest
        else None,
        "selection_sha256": canonical_hash(selection),
        "current_packet_sha256": canonical_hash(delivery["input_packet"]),
        "snapshot_sha256": manifest["snapshot_sha256"],
        "snapshot_sequence": manifest["snapshot_sequence"],
        "workflow_head_sha256": manifest["workflow_head_sha256"],
        "human_selection": "pending",
        "stage3_execution_authorized": False,
        "formal_ready": False,
    }
