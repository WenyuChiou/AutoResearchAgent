"""Retain unselected Stage 2 context for Stage 3 direction advice, without execution."""

import copy
from pathlib import Path

from stage2_check.contracts import decode_json

from .delivery import _relative_files, inspect_delivery
from .planning_handoff import (
    DELIVERY_REFS,
    _canonical_bytes,
    _manifest_hash,
    _private_output,
    _read_regular,
    _require,
    _write_new,
)

VERSION = "1.0.0"
MANIFEST = "advisory_manifest.json"
CONTEXT = "advisory_context.json"


def _project_advisory(delivery):
    manifest = delivery["manifest"]
    inventory = {row["path"] for row in manifest["files"]}
    _require(
        set(DELIVERY_REFS.values()).issubset(inventory),
        "advisory-delivery-reference-not-inventoried",
    )
    return {
        "kind": "Stage2ToStage3AdvisoryContext",
        "schema_version": VERSION,
        "mode": "direction-advice",
        "required_delivery_manifest_sha256": manifest["manifest_sha256"],
        "workflow_head_sha256": manifest["workflow_head_sha256"],
        "snapshot_sha256": manifest["snapshot_sha256"],
        "delivery_refs": copy.deepcopy(DELIVERY_REFS),
        "source_base_in_required_delivery": "sources",
        "selection": copy.deepcopy(delivery["selection"]),
        "selected_options": [],
        "human_selection": "pending",
        "human_identity": "not-established",
        "semantic_verification": "not-established",
        "execution_authorized": False,
        "next_work": "Offer direction advice and conditional design options using the retained reviews, scope questions, resources and unknowns. Record a real current selection before a selected planning handoff or research execution.",
    }


def _files(root):
    return [
        row
        for row in _relative_files(root, include_manifest=True)
        if row["path"] != MANIFEST
    ]


def prepare_advisory_handoff(
    delivery_dir, *, expected_delivery_manifest_sha256, output_dir
):
    """Prepare direction-advice input, retaining zero recommendations and all options."""
    delivery = inspect_delivery(delivery_dir, expected_delivery_manifest_sha256)
    context = _project_advisory(delivery)
    output = _private_output(output_dir)
    _require(
        not output.is_relative_to(Path(delivery_dir).resolve()),
        "advisory-output-overlaps-delivery",
    )
    _require(not output.exists(), "advisory-output-exists")
    output.mkdir(parents=False)
    _write_new(output / CONTEXT, _canonical_bytes(context))
    manifest = {
        "kind": "Stage2ToStage3AdvisoryPackageManifest",
        "schema_version": VERSION,
        "required_delivery_manifest_sha256": expected_delivery_manifest_sha256,
        "files": _files(output),
    }
    manifest["manifest_sha256"] = _manifest_hash(manifest)
    _write_new(output / MANIFEST, _canonical_bytes(manifest))
    return inspect_advisory_handoff(
        output, delivery_dir, expected_manifest_sha256=manifest["manifest_sha256"]
    )


def inspect_advisory_handoff(package_dir, delivery_dir, *, expected_manifest_sha256):
    """Reconstruct advice context from the bound delivery; grant no selection authority."""
    root = Path(package_dir).resolve()
    manifest = decode_json(
        _read_regular(root / MANIFEST, "advisory-manifest-invalid"),
        "advisory manifest",
    )
    _require(
        isinstance(manifest, dict)
        and set(manifest)
        == {
            "kind",
            "schema_version",
            "required_delivery_manifest_sha256",
            "files",
            "manifest_sha256",
        }
        and manifest["kind"] == "Stage2ToStage3AdvisoryPackageManifest"
        and manifest["schema_version"] == VERSION
        and manifest["manifest_sha256"] == _manifest_hash(manifest)
        and manifest["manifest_sha256"] == expected_manifest_sha256,
        "advisory-manifest-binding",
    )
    _require(_files(root) == manifest["files"], "advisory-package-inventory")
    _require(
        {row["path"] for row in manifest["files"]} == {CONTEXT},
        "advisory-package-file-set",
    )
    delivery = inspect_delivery(
        delivery_dir, manifest["required_delivery_manifest_sha256"]
    )
    context = decode_json(
        _read_regular(root / CONTEXT, "advisory-context-invalid"), "advisory context"
    )
    _require(
        _canonical_bytes(context) == _canonical_bytes(_project_advisory(delivery)),
        "advisory-context-projection-mismatch",
    )
    return {"manifest": manifest, "context": context}
