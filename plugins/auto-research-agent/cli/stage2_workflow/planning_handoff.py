"""Derive and revalidate a non-authorizing Stage 2 planning package."""

import copy
import hashlib
import json
import os
from pathlib import Path

from stage2_check.contracts import decode_json
from stage2_common import Stage2Error, canonical_hash, current_prior_work_reviews

from .delivery import _relative_files, _safe_package_path, inspect_delivery
from .interaction import _record, _user_text, _validate_decision

VERSION = "1.0.0"
MANIFEST = "planning_manifest.json"
FILES = {
    "handoff": "planning_handoff.json",
    "interaction": "interaction.json",
    "native_message": "native-user-message.jsonl",
    "delivery_manifest": "delivery_manifest.json",
}
DELIVERY_REFS = {
    "selection_json": "selection.json",
    "selection_markdown": "selection.md",
    "selection_html": "selection.html",
    "review_audit": "review_audit.json",
}


def _require(condition, reason):
    if not condition:
        raise Stage2Error(reason)


def _canonical_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _private_output(path):
    output = Path(path).resolve()
    _require(
        not any((parent / ".git").exists() for parent in (output, *output.parents)),
        "planning-output-must-be-private",
    )
    return output


def _read_regular(path, reason):
    _require(path.is_file() and not path.is_symlink(), reason)
    try:
        return path.read_bytes()
    except OSError as error:
        raise Stage2Error(reason) from error


def _interaction_bytes(interaction_dir):
    root = Path(interaction_dir).resolve()
    _require(root.is_dir() and not root.is_symlink(), "planning-interaction-directory")
    actual = set()
    for path in root.iterdir():
        _require(path.is_file() and not path.is_symlink(), "planning-interaction-entry")
        actual.add(path.name)
    _require(
        actual == set(FILES.values()) - {FILES["handoff"]},
        "planning-interaction-inventory",
    )
    return root, {
        name: _read_regular(root / relative, f"planning-interaction-{name}-invalid")
        for name, relative in FILES.items()
        if name != "handoff"
    }


def _validate_interaction(
    delivery, raw_interaction, raw_message, raw_delivery_manifest
):
    record = decode_json(raw_interaction, "planning interaction")
    _require(
        isinstance(record, dict)
        and {"kind", "schema_version", "message_index", "decision"}.issubset(record),
        "planning-interaction-shape",
    )
    _require(
        record["kind"] == "Stage2HumanInteraction"
        and record["schema_version"] == "1.0.0",
        "planning-interaction-version",
    )
    _validate_decision(
        record["decision"], _user_text(raw_message, record["message_index"])
    )
    _require(record["decision"]["kind"] == "select", "planning-selection-required")
    manifest = delivery["manifest"]
    # Reconstruct only the saved record, not a live workflow or execution authority.
    state = {
        "manifest": {"manifest_sha256": manifest["workflow_manifest_sha256"]},
        "head_sha256": manifest["workflow_head_sha256"],
        "latest_snapshot": {
            "packet": delivery["input_packet"],
            "event": {
                "payload": {
                    "snapshot_sha256": manifest["snapshot_sha256"],
                    "snapshot_sequence": manifest["snapshot_sequence"],
                }
            },
            "checker": {
                "manifest": {
                    "manifest_sha256": manifest["snapshot_checker_manifest_sha256"],
                }
            },
        },
    }
    expected = _record(
        state, delivery, record["decision"], raw_message, record["message_index"]
    )
    _require(
        _canonical_bytes(record) == _canonical_bytes(expected),
        "planning-interaction-reconstruction-mismatch",
    )
    original_manifest = _read_regular(
        delivery["root"] / "delivery_manifest.json",
        "planning-delivery-manifest-invalid",
    )
    _require(
        raw_delivery_manifest == original_manifest,
        "planning-retained-delivery-manifest-mismatch",
    )
    return record


def _project_handoff(delivery, record, interaction_sha256, message_sha256):
    packet = copy.deepcopy(delivery["selection"]["evaluation_packet"])
    selected = record["decision"]["selected"]
    keys = {(row["candidate_id"], row["candidate_version"]) for row in selected}
    option_map = {
        (row["candidate"]["candidate_id"], row["candidate"]["version"]): row
        for row in delivery["selection"]["current_options"]
    }
    options = [
        copy.deepcopy(option_map[(row["candidate_id"], row["candidate_version"])])
        for row in selected
    ]
    tables = packet.get("research_tables")
    if tables is None:
        table_context = {"status": "unknown-not-recorded", "value": None}
        direction_resources = {"status": "unknown-not-recorded", "rows": []}
    else:
        table_context = {"status": "recorded", "value": copy.deepcopy(tables)}
        direction_resources = {
            "status": "recorded",
            "rows": [
                copy.deepcopy(row)
                for row in tables["direction_resources"]
                if (row["candidate_id"], row["candidate_version"]) in keys
            ],
        }
    reviews = current_prior_work_reviews(packet)
    prior_work = (
        {
            "status": "recorded",
            "rows": [copy.deepcopy(reviews[row["candidate_id"]]) for row in selected],
        }
        if packet.get("schema_version") == "2.4.0"
        else {"status": "unknown-not-recorded", "rows": []}
    )
    inventory = {row["path"] for row in delivery["manifest"]["files"]}
    _require(
        set(DELIVERY_REFS.values()).issubset(inventory),
        "planning-delivery-reference-not-inventoried",
    )
    return {
        "kind": "Stage2ToStage3PlanningPackage",
        "schema_version": VERSION,
        "required_delivery_manifest_sha256": delivery["manifest"]["manifest_sha256"],
        "report_manifest_sha256": record["report_manifest_sha256"],
        "snapshot_sha256": record["snapshot_sha256"],
        "interaction_file_sha256": interaction_sha256,
        "native_user_message_sha256": message_sha256,
        "delivery_refs": copy.deepcopy(DELIVERY_REFS),
        "source_base_in_required_delivery": "sources",
        "evaluation_packet": packet,
        "selected_options": options,
        "selected_direction_resources": direction_resources,
        "selected_prior_work_reviews": prior_work,
        "research_tables": table_context,
        "decision": copy.deepcopy(record["decision"]),
        "human_identity": "not-established",
        "semantic_verification": "not-established",
        "execution_authorized": False,
    }


def _manifest_hash(manifest):
    return canonical_hash(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )


def _package_files(root):
    return [
        row
        for row in _relative_files(root, include_manifest=True)
        if row["path"] != MANIFEST
    ]


def _write_new(path, data):
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise Stage2Error("planning-output-exists") from error


def prepare_planning_handoff(
    delivery_dir,
    interaction_dir,
    *,
    expected_delivery_manifest_sha256,
    expected_interaction_file_sha256,
    output_dir,
):
    delivery = inspect_delivery(delivery_dir, expected_delivery_manifest_sha256)
    _, raw = _interaction_bytes(interaction_dir)
    interaction_sha = hashlib.sha256(raw["interaction"]).hexdigest()
    _require(
        interaction_sha == expected_interaction_file_sha256,
        "planning-interaction-receipt-mismatch",
    )
    record = _validate_interaction(
        delivery, raw["interaction"], raw["native_message"], raw["delivery_manifest"]
    )
    handoff = _project_handoff(
        delivery,
        record,
        interaction_sha,
        hashlib.sha256(raw["native_message"]).hexdigest(),
    )
    output = _private_output(output_dir)
    _require(not output.exists(), "planning-output-exists")
    output.mkdir(parents=False)
    values = {
        FILES["handoff"]: _canonical_bytes(handoff),
        FILES["interaction"]: raw["interaction"],
        FILES["native_message"]: raw["native_message"],
        FILES["delivery_manifest"]: raw["delivery_manifest"],
    }
    for name, data in values.items():
        _write_new(output / name, data)
    manifest = {
        "kind": "Stage2ToStage3PlanningPackageManifest",
        "schema_version": VERSION,
        "required_delivery_manifest_sha256": expected_delivery_manifest_sha256,
        "files": _package_files(output),
    }
    manifest["manifest_sha256"] = _manifest_hash(manifest)
    _write_new(output / MANIFEST, _canonical_bytes(manifest))
    return inspect_planning_handoff(
        output, delivery_dir, expected_manifest_sha256=manifest["manifest_sha256"]
    )


def inspect_planning_handoff(package_dir, delivery_dir, *, expected_manifest_sha256):
    root = Path(package_dir).resolve()
    raw_manifest = _read_regular(root / MANIFEST, "planning-manifest-invalid")
    manifest = decode_json(raw_manifest, "planning manifest")
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
        and manifest["kind"] == "Stage2ToStage3PlanningPackageManifest"
        and manifest["schema_version"] == VERSION
        and manifest["manifest_sha256"] == _manifest_hash(manifest)
        and manifest["manifest_sha256"] == expected_manifest_sha256,
        "planning-manifest-binding",
    )
    _require(_package_files(root) == manifest["files"], "planning-package-inventory")
    _require(
        {row["path"] for row in manifest["files"]} == set(FILES.values()),
        "planning-package-file-set",
    )
    delivery = inspect_delivery(
        delivery_dir, manifest["required_delivery_manifest_sha256"]
    )
    raw = {
        name: _read_regular(
            _safe_package_path(root, relative), f"planning-{name}-invalid"
        )
        for name, relative in FILES.items()
    }
    record = _validate_interaction(
        delivery, raw["interaction"], raw["native_message"], raw["delivery_manifest"]
    )
    handoff = decode_json(raw["handoff"], "planning handoff")
    expected = _project_handoff(
        delivery,
        record,
        hashlib.sha256(raw["interaction"]).hexdigest(),
        hashlib.sha256(raw["native_message"]).hexdigest(),
    )
    _require(
        _canonical_bytes(handoff) == _canonical_bytes(expected),
        "planning-handoff-projection-mismatch",
    )
    return {"manifest": manifest, "handoff": handoff}
