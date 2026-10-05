"""Read-only Stage 2 sidecar; the frozen Stage 1 index remains unchanged."""

from copy import deepcopy
import re

from stage1_deliverable.common import (
    DeliverableError,
    canonical,
    private_output,
    safe_path,
    sha,
)
from stage2_workflow.evaluation_delivery import inspect_evaluated_delivery

from .json_bytes import decode_json
from .projection import validate_index


def _require(condition, reason):
    if not condition:
        raise DeliverableError("Stage 2 workspace import: " + reason)


def _digest(value):
    _require(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value),
        "expected SHA-256 is required",
    )
    return value


def _delivery(directory, expected_manifest_sha256):
    root = private_output(directory)
    expected = _digest(expected_manifest_sha256)
    manifest = inspect_evaluated_delivery(root, expected_manifest_sha256=expected)
    _require(
        manifest.get("kind") == "Stage2EvaluatedDelivery"
        and manifest.get("schema_version") == "3.0.0",
        "unsupported evaluated delivery",
    )
    _require(
        manifest.get("human_selection") == "pending"
        and all(
            manifest.get(key) is False
            for key in ("stage3_authorized", "formal_ready", "improvement_demonstrated")
        ),
        "a reading import cannot grant execution, choice or improvement",
    )
    files = {}
    for row in manifest["artifacts"]:
        raw = safe_path(root, row["path"]).read_bytes()
        _require(
            sha(raw) == row["sha256"] and len(raw) == row["bytes"],
            "artifact changed while importing",
        )
        files["stage2/" + row["path"]] = raw
    # Parse precisely the captured, hash-checked bytes, not a later path read.
    selection = decode_json(files["stage2/core_selection.json"])
    evaluation = decode_json(files["stage2/evaluation_projection.json"])
    _require(
        inspect_evaluated_delivery(root, expected_manifest_sha256=expected) == manifest,
        "delivery changed during import",
    )
    return manifest, files, selection, evaluation


def _bridge(index, manifest, selection):
    packet = selection["evaluation_packet"]
    return {
        "kind": "WorkspaceStage2BridgeReceipt",
        "schema_version": "1.0.0",
        "association": "explicit-operator-selected-binding",
        "project_id": index["project_id"],
        "stage1_index_sha256": sha(canonical(index)),
        "stage1_package_manifest_sha256": index["provenance"][
            "package_manifest_sha256"
        ],
        "stage2_manifest_sha256": manifest["manifest_sha256"],
        "selection_sha256": sha(canonical(selection)),
        "brief_sha256": sha(canonical(packet["brief"])),
        "resources_sha256": sha(canonical(packet["resources"])),
        "source_snapshot_sha256": sha(canonical(packet["sources"])),
        "workflow_event_head": manifest["event_head"],
        "stored_packet_sha256": manifest["stored_packet_sha256"],
        "original_stage1_lineage_attested": False,
        "human_selection": "pending",
        "stage3_authorized": False,
        "formal_ready": False,
        "improvement_demonstrated": False,
    }


def prepare_stage2_bridge(index, delivery_dir, *, expected_manifest_sha256):
    """Create an explicit association receipt for the caller to retain.

    This is a reading association, not proof that Stage 2 originally used this
    Stage 1 package. A matching topic or filename never creates that authority.
    """
    validate_index(index)
    manifest, _, selection, _ = _delivery(delivery_dir, expected_manifest_sha256)
    return _bridge(index, manifest, selection)


def import_evaluated_delivery(
    index, delivery_dir, bridge_receipt, *, expected_bridge_sha256
):
    """Return a verified sidecar and artifact bytes without mutating the index."""
    validate_index(index)
    _require(
        sha(canonical(bridge_receipt)) == _digest(expected_bridge_sha256),
        "external bridge receipt differs",
    )
    _require(isinstance(bridge_receipt, dict), "bridge must be an object")
    manifest, files, selection, evaluation = _delivery(
        delivery_dir, bridge_receipt.get("stage2_manifest_sha256")
    )
    _require(
        bridge_receipt == _bridge(index, manifest, selection),
        "project, Stage 1 index or Stage 2 version differs",
    )
    attachment = {
        "kind": "WorkspaceStage2Attachment",
        "schema_version": "1.0.0",
        "project_id": index["project_id"],
        "stage1_index_sha256": sha(canonical(index)),
        "bridge_receipt": deepcopy(bridge_receipt),
        "selection": selection,
        "evaluation": evaluation,
    }
    files["stage2/bridge-receipt.json"] = canonical(bridge_receipt)
    files["stage2/evaluated-delivery-manifest.json"] = canonical(manifest)
    return attachment, files
