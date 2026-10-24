"""Immutable external-judgment receipts; no provider or judge dispatch."""

import hashlib
from pathlib import Path

from .campaign import POLICY, binding, inspect_campaign, pinned
from .campaign_views import restore_judgment
from .contracts import Stage3Error, digest
from .evaluation import inspect_evaluation_record, record_evaluation
from .preparation import closed
from .storage import decode_json, private_output, read_bytes, write_new


def _unit(manifest, unit_id):
    matches = [row for row in manifest["units"] if row["unit_id"] == unit_id]
    if len(matches) != 1 or matches[0]["request"] is None:
        raise Stage3Error("unit lacks a verified saved-plan evaluation request")
    return matches[0]


def _mapped(raw, unit):
    return restore_judgment(decode_json(raw), unit["aliases"])


def inspect_receipt(ref, manifest, campaign_sha256):
    """Verify an externally pinned receipt and recompute its record from raw input."""
    value = pinned(ref)
    closed(
        value,
        {
            "kind",
            "schema_version",
            "campaign_sha256",
            "unit_id",
            "raw",
            "mapped",
            "record",
            "status",
            "error",
            "policy",
        },
        "campaign receipt",
    )
    if (
        value["kind"] != "Stage3CampaignReceipt"
        or value["schema_version"] != "1.0.0"
        or value["campaign_sha256"] != campaign_sha256
        or digest(value["policy"]) != digest(POLICY)
    ):
        raise Stage3Error("receipt campaign/version/policy mismatch")
    unit = _unit(manifest, value["unit_id"])
    root = Path(ref["path"]).parent
    for name, filename in (
        ("raw", "judgment.raw"),
        ("mapped", "judgment.json"),
        ("record", "record.json"),
    ):
        if value[name] is not None and Path(value[name]["path"]) != root / filename:
            raise Stage3Error("receipt artifact escapes its saved unit")
    raw = read_bytes(value["raw"]["path"])
    if hashlib.sha256(raw).hexdigest() != value["raw"]["sha256"]:
        raise Stage3Error("raw judgment hash mismatch")
    record = None
    if value["mapped"] is not None:
        if pinned(value["mapped"]) != _mapped(raw, unit):
            raise Stage3Error("neutral judgment mapping differs from supplied bytes")
        if value["record"] is not None:
            if binding(value["record"]["path"]) != value["record"]:
                raise Stage3Error("saved evaluation record hash mismatch")
            try:
                record = inspect_evaluation_record(
                    value["record"]["path"],
                    expected_sha256=value["record"]["sha256"],
                    request=unit["request"],
                    judgment=value["mapped"],
                )
            except (Stage3Error, UnicodeError):
                if value["status"] != "failed" or not value["error"]:
                    raise
    elif value["record"] is not None:
        raise Stage3Error("record missing its mapped judgment")
    expected_status = (
        "recorded" if record and record["record_status"] == "recorded" else "failed"
    )
    if expected_status == "failed":
        closed(value["error"], {"kind", "message"}, "retained failure")
    if value["status"] != expected_status or (
        expected_status == "recorded" and value["error"] is not None
    ):
        raise Stage3Error("receipt outcome mismatch")
    return value, record


def record_campaign(
    root, *, expected_sha256, unit_id, judgment, expected_judgment_sha256, output
):
    campaign = inspect_campaign(root, expected_sha256=expected_sha256)["manifest"]
    unit = _unit(campaign, unit_id)
    raw = read_bytes(judgment)
    if hashlib.sha256(raw).hexdigest() != expected_judgment_sha256:
        raise Stage3Error("external raw judgment hash mismatch")
    target = private_output(output)
    if target.exists():
        receipt, _ = inspect_receipt(
            binding(target / "receipt.json"), campaign, expected_sha256
        )
        if (
            receipt["unit_id"] != unit_id
            or receipt["raw"]["sha256"] != expected_judgment_sha256
        ):
            raise Stage3Error("same output key has different input bytes")
        if receipt["status"] == "failed":
            raise Stage3Error("retained failed unit; no automatic retry")
        return {
            "receipt": receipt,
            "receipt_binding": binding(target / "receipt.json"),
            "replayed": True,
        }
    target.mkdir(parents=True)
    write_new(target / "judgment.raw", raw, raw=True)
    receipt = {
        "kind": "Stage3CampaignReceipt",
        "schema_version": "1.0.0",
        "campaign_sha256": expected_sha256,
        "unit_id": unit_id,
        "raw": binding(target / "judgment.raw"),
        "mapped": None,
        "record": None,
        "status": "failed",
        "error": None,
        "policy": POLICY,
    }
    failure = None
    try:
        write_new(target / "judgment.json", _mapped(raw, unit))
        receipt["mapped"] = binding(target / "judgment.json")
        record_evaluation(
            unit["request"]["path"],
            expected_request_sha256=unit["request"]["sha256"],
            judgment=target / "judgment.json",
            expected_judgment_sha256=receipt["mapped"]["sha256"],
            output=target / "record.json",
        )
        receipt["record"] = binding(target / "record.json")
        receipt["status"] = "recorded"
    except (Stage3Error, OSError, ValueError, UnicodeError, RecursionError) as error:
        failure = error
        receipt["error"] = {"kind": type(error).__name__, "message": str(error)[:2000]}
        if (target / "record.json").is_file():
            receipt["record"] = binding(target / "record.json")
    write_new(target / "receipt.json", receipt)
    if failure is not None:
        raise Stage3Error(
            f"failed judgment retained without retry: {failure}"
        ) from failure
    return {
        "receipt": receipt,
        "receipt_binding": binding(target / "receipt.json"),
        "replayed": False,
    }
