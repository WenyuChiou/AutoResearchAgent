"""Offline A/B preparation, never a formal plan, judge, or execution runner."""

import hashlib
import json
from pathlib import Path
import re

from .contracts import Stage3Error, digest
from .storage import read_bytes, safe_path

CRITERIA = {
    "P7": "P7V1.QUESTION_DESIGN",
    "P8": "P8V1.EVIDENCE_INTERPRETATION",
    "P9": "P9V1.FEASIBILITY",
}


def closed(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise Stage3Error(f"invalid {label} fields")


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise Stage3Error(f"nonempty {label} required")


def sha256(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise Stage3Error(
            "external SHA-256 must be 64 lowercase hexadecimal characters"
        )


def file_binding(path, expected_sha256):
    if not isinstance(path, (str, Path)):
        raise Stage3Error("artifact path required")
    sha256(expected_sha256)
    raw = read_bytes(path)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise Stage3Error("external file hash mismatch")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    try:
        return json.loads(
            raw,
            object_pairs_hook=unique,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (ValueError, UnicodeError) as error:
        raise Stage3Error(f"invalid pinned JSON: {error}") from error


def prepare_ab(definition, intake):
    """Reconstruct unrun comparison slots from a pinned, explicit definition."""
    closed(
        definition,
        {
            "kind",
            "schema_version",
            "case_id",
            "intake_sha256",
            "common_prompt",
            "runtime",
            "arms",
            "rubric",
            "judges",
            "decision_rule",
            "audit_triggers",
        },
        "A/B preparation definition",
    )
    if (
        definition["kind"] != "Stage3ABPreparationDefinition"
        or definition["schema_version"] != "1.0.0"
        or definition["intake_sha256"] != digest(intake)
    ):
        raise Stage3Error("A/B definition input/version mismatch")
    for name in ("case_id", "common_prompt", "decision_rule"):
        text(definition[name], name)
    runtime = definition["runtime"]
    closed(runtime, {"model", "reasoning", "tool_policy", "timeout_seconds"}, "runtime")
    for name in ("model", "reasoning"):
        text(runtime[name], name)
    if (
        runtime["tool_policy"] != "none"
        or type(runtime["timeout_seconds"]) is not int
        or runtime["timeout_seconds"] <= 0
    ):
        raise Stage3Error("shared no-tool runtime and positive deadline required")
    closed(definition["arms"], {"A", "B"}, "arms")
    for arm in definition["arms"].values():
        closed(arm, {"build_sha256", "protocol"}, "arm")
        sha256(arm["build_sha256"])
        text(arm["protocol"], "arm protocol")
    closed(definition["judges"], {"R1", "R2", "ADJ"}, "judge configurations")
    for judge in definition["judges"].values():
        closed(judge, {"model", "reasoning"}, "judge configuration")
        for name in judge:
            text(judge[name], "judge " + name)
    triggers = definition["audit_triggers"]
    if not isinstance(triggers, list) or not triggers:
        raise Stage3Error("explicit audit triggers required")
    for trigger in triggers:
        text(trigger, "audit trigger")
    rubric_ref = definition["rubric"]
    closed(rubric_ref, {"path", "sha256"}, "rubric binding")
    text(rubric_ref["path"], "rubric path")
    if not Path(rubric_ref["path"]).is_absolute():
        raise Stage3Error("absolute rubric path required for cwd-independent replay")
    rubric = file_binding(rubric_ref["path"], rubric_ref["sha256"])
    if (
        not isinstance(rubric, dict)
        or rubric.get("rubric_id") != "stage23-general-v1"
        or not isinstance(rubric.get("criteria"), list)
    ):
        raise Stage3Error("generic Stage3 rubric required")
    indexed = {}
    for row in rubric["criteria"]:
        if not isinstance(row, dict):
            raise Stage3Error("invalid rubric criterion")
        text(row.get("id"), "rubric criterion ID")
        if row["id"] in indexed or not isinstance(row.get("anchors"), dict):
            raise Stage3Error("duplicate criterion ID or invalid rubric anchors")
        for anchor in row["anchors"].values():
            text(anchor, "rubric anchor")
        indexed[row["id"]] = row
    for metric, criterion in CRITERIA.items():
        row = indexed.get(criterion, {})
        if row.get("dimension") != metric or set(row.get("anchors", {})) != {
            "0",
            "1",
            "2",
        }:
            raise Stage3Error("Stage3 criterion/anchors missing")
    if not intake["questions"] or intake["legacy_candidates"]:
        raise Stage3Error(
            "A/B preparation needs admitted structured scientific questions"
        )
    return {
        "kind": "Stage3ABPreparation",
        "schema_version": "1.0.0",
        "definition_sha256": digest(definition),
        "case_id": definition["case_id"],
        "intake_sha256": digest(intake),
        "source_manifest_sha256": intake["source_manifest_sha256"],
        "question_refs": [q["question_ref"] for q in intake["questions"]],
        "rubric": {
            "path": str(safe_path(rubric_ref["path"])),
            "sha256": rubric_ref["sha256"],
        },
        "criteria": CRITERIA,
        "pairs": [
            {
                "pair": index,
                "order": order,
                "runs": {
                    arm: {
                        "status": "not-run",
                        "scores": {metric: None for metric in CRITERIA},
                    }
                    for arm in ("A", "B")
                },
            }
            for index, order in enumerate((["A", "B"], ["B", "A"], ["A", "B"]), 1)
        ],
        "judgments": {role: "not-run" for role in ("R1", "R2", "ADJ")},
        "formal_execution_enabled": False,
        "external_claim_ready": False,
        "execution_authorized": False,
        "limitations": [
            "Preparation only; no formal authority or run attestations.",
            "Judge configuration does not establish independent blinded execution.",
            "Declared decision/audit rules still need formal protocol review.",
        ],
    }
