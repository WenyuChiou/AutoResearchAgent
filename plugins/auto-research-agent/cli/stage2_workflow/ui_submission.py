"""Honest ProjectHost submission provenance; never synthesize native messages."""

from datetime import datetime

from stage2_check.contracts import decode_json
from stage2_common import Stage2Error

UI_VERSION = "1.1.0"
UI_MESSAGE_FILE = "projecthost-user-submission.json"


def valid_input_version(value, *, allow_string=False):
    return (type(value) is int and value > 0) or (
        allow_string
        and type(value) is str
        and 0 < len(value) <= 128
        and value == value.strip()
        and all(ord(c) >= 32 and ord(c) != 127 for c in value)
    )


def read_ui_submission(raw, *, expected=None):
    """Check retained request bytes; credential access does not identify a person."""
    if not isinstance(raw, bytes):
        raise Stage2Error("projecthost-submission-bytes-required")
    try:
        value = decode_json(raw, "ProjectHost user submission")
        raw.decode("utf-8").encode("utf-8")
    except (RecursionError, UnicodeError) as error:
        raise Stage2Error("projecthost-submission-invalid-encoding-or-depth") from error
    fields = {
        "kind",
        "schema_version",
        "project_ref",
        "input_version",
        "principal",
        "request_sha256",
        "received_at",
        "confirmed",
        "decision",
        "workflow_manifest_sha256",
        "workflow_head_sha256",
        "snapshot_sha256",
        "delivery_manifest_sha256",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise Stage2Error("projecthost-submission-shape")
    if (
        value["kind"] != "Stage2ProjectHostUserSubmission"
        or value["schema_version"] not in ("1.0.0", "1.1.0")
        or value["confirmed"] is not True
        or not valid_input_version(
            value["input_version"], allow_string=value["schema_version"] == "1.1.0"
        )
    ):
        raise Stage2Error("projecthost-submission-version-confirmation")
    for name in ("project_ref", "principal", "received_at"):
        if not isinstance(value[name], str) or not value[name].strip():
            raise Stage2Error("projecthost-submission-missing-" + name)
    try:
        timestamp = datetime.fromisoformat(value["received_at"].replace("Z", "+00:00"))
        if timestamp.utcoffset() is None:
            raise ValueError("timezone required")
    except ValueError as error:
        raise Stage2Error("projecthost-submission-timestamp") from error
    for name in fields:
        if name.endswith("sha256") and (
            not isinstance(value[name], str)
            or len(value[name]) != 64
            or any(c not in "0123456789abcdef" for c in value[name])
        ):
            raise Stage2Error("projecthost-submission-hash")
    decision = value["decision"]
    if not isinstance(decision, dict) or not isinstance(decision.get("user_text"), str):
        raise Stage2Error("projecthost-submission-decision-shape")
    from .interaction import _validate_decision

    _validate_decision(decision, decision["user_text"])
    try:
        import json

        json.dumps(value, ensure_ascii=False).encode("utf-8")
    except (UnicodeError, RecursionError) as error:
        raise Stage2Error("projecthost-submission-invalid-encoding-or-depth") from error
    if expected is not None and any(
        value.get(k) != v
        or (k == "input_version" and type(value.get(k)) is not type(v))
        for k, v in expected.items()
    ):
        raise Stage2Error("projecthost-submission-binding-mismatch")
    return value


def submission_origin(value):
    return {
        "kind": "projecthost-ui-submission",
        **{
            k: value[k]
            for k in (
                "project_ref",
                "input_version",
                "principal",
                "request_sha256",
                "received_at",
            )
        },
        "human_identity": "not-established",
    }
