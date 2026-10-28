"""Bounded direction preferences; these are never a formal selected handoff."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile

from stage1_deliverable.common import private_output, safe_path
from .advisory_handoff import prepare_advisory_handoff, inspect_advisory_handoff
from .decision_cards import derive_decision_cards
from .planning_handoff import _canonical_bytes, _read_regular, _require


def validate_preferences(delivery, preferences):
    """Any current delivered version can be discussed, including revise/park."""
    _require(
        type(preferences) is list and 0 < len(preferences) <= 16,
        "direction-intent-preferences-required",
    )
    current = {
        (row["candidate_id"], row["candidate_version"])
        for row in derive_decision_cards(delivery["selection"])["cards"]
    }
    seen = set()
    for row in preferences:
        _require(
            type(row) is dict and set(row) == {"candidate_id", "candidate_version"},
            "direction-intent-preference-shape",
        )
        _require(
            type(row["candidate_id"]) is str and type(row["candidate_version"]) is int,
            "direction-intent-preference-type",
        )
        pair = row["candidate_id"], row["candidate_version"]
        _require(
            pair in current and pair not in seen, "direction-intent-version-differs"
        )
        seen.add(pair)


def _retain(path, raw, *, staging_dir):
    if path.exists():
        _require(
            _read_regular(path, "direction-intent-file-invalid") == raw,
            "direction-intent-existing-bytes-differ",
        )
        return
    # Keep interrupted temporary files outside the final strict inventory.
    with tempfile.TemporaryDirectory(dir=staging_dir, prefix="direction-file-") as tmp:
        staged = Path(tmp) / path.name
        with staged.open("xb") as stream:
            _require(stream.write(raw) == len(raw), "direction-intent-short-write")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(staged, path)  # Atomic no-replace publication on this volume.
        except FileExistsError:
            _require(
                _read_regular(path, "direction-intent-file-invalid") == raw,
                "direction-intent-existing-bytes-differ",
            )


def retain_direction_intent(output_dir, delivery_dir, submission):
    """Complete missing deterministic files only; never overwrite original bytes.

    Advisory compilation is zero-model and deterministic. An interrupted copy is
    compared against a fresh verified projection; the final intent seals it last.
    """
    output = private_output(output_dir)
    output.mkdir(exist_ok=True)
    _require(
        not output.is_relative_to(Path(delivery_dir).resolve()),
        "direction-intent-output-overlaps-delivery",
    )
    # Stage3 consumes the existing advisory contract, without changing its schema.
    with tempfile.TemporaryDirectory(
        dir=output.parent, prefix="direction-projection-"
    ) as tmp:
        projected = Path(tmp) / "advisory"
        advisory = prepare_advisory_handoff(
            delivery_dir,
            expected_delivery_manifest_sha256=submission["delivery_manifest_sha256"],
            output_dir=projected,
        )
        target = safe_path(output, "advisory")
        target.mkdir(exist_ok=True)
        for name in ("advisory_context.json", "advisory_manifest.json"):
            _retain(
                safe_path(target, name),
                (projected / name).read_bytes(),
                staging_dir=output.parent,
            )
    raw = _canonical_bytes(submission)
    _retain(safe_path(output, "submission.json"), raw, staging_dir=output.parent)
    intent = dict(deepcopy(submission))
    intent.pop("confirmed")
    intent.update(
        kind="Stage2DirectionPlanningIntent",
        mode="direction-advice",
        submission_sha256=hashlib.sha256(raw).hexdigest(),
        advisory_manifest_sha256=advisory["manifest"]["manifest_sha256"],
        selected_options=[],
        human_selection="pending",
        input_origin="projecthost-ui-submission",
        identity_authenticated=False,
        execution_authorized=False,
    )
    raw_intent = _canonical_bytes(intent)
    _retain(safe_path(output, "intent.json"), raw_intent, staging_dir=output.parent)
    return inspect_direction_intent(
        output,
        delivery_dir,
        expected_intent_sha256=hashlib.sha256(raw_intent).hexdigest(),
    )


def inspect_direction_intent(output_dir, delivery_dir, *, expected_intent_sha256):
    root = private_output(output_dir)
    _require(
        {p.name for p in root.iterdir()}
        == {"intent.json", "submission.json", "advisory"},
        "direction-intent-inventory",
    )
    raw = _read_regular(safe_path(root, "intent.json"), "direction-intent-invalid")
    _require(
        hashlib.sha256(raw).hexdigest() == expected_intent_sha256,
        "direction-intent-hash-differs",
    )
    intent = json.loads(raw)
    submission_raw = _read_regular(
        safe_path(root, "submission.json"), "direction-submission-invalid"
    )
    _require(
        hashlib.sha256(submission_raw).hexdigest() == intent["submission_sha256"],
        "direction-submission-hash-differs",
    )
    submission = json.loads(submission_raw)
    expected = deepcopy(submission)
    expected.pop("confirmed")
    expected.update(
        kind="Stage2DirectionPlanningIntent",
        mode="direction-advice",
        submission_sha256=intent["submission_sha256"],
        advisory_manifest_sha256=intent["advisory_manifest_sha256"],
        selected_options=[],
        human_selection="pending",
        input_origin="projecthost-ui-submission",
        identity_authenticated=False,
        execution_authorized=False,
    )
    _require(
        _canonical_bytes(expected) == raw and submission["confirmed"] is True,
        "direction-intent-submission-differs",
    )
    advisory = inspect_advisory_handoff(
        safe_path(root, "advisory"),
        delivery_dir,
        expected_manifest_sha256=intent["advisory_manifest_sha256"],
    )
    _require(
        advisory["manifest"]["required_delivery_manifest_sha256"]
        == intent["delivery_manifest_sha256"],
        "direction-intent-delivery-differs",
    )
    return intent
