"""Strict generation schemas for the Stage 2 v2 judge adapter."""

from copy import deepcopy

from stage2_common import canonical_hash
from stage2_eval.evaluation import CRITERIA, HASH_FIELDS


def _const(value):
    return {"const": value}


def _object(properties, required=None):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": False,
    }


def _text():
    return {"type": "string", "minLength": 1}


def _evidence_ids(packet, *, require_one=False):
    return {
        "type": "array",
        "items": {
            "type": "string",
            "enum": [row["evidence_id"] for row in packet["evidence"]],
        },
        "minItems": 1 if require_one else 0,
        "uniqueItems": True,
    }


def _content_bindings(view):
    fields = HASH_FIELDS[:-1]
    return {
        field: _const(
            canonical_hash(view) if field == "content_view_sha256" else view[field]
        )
        for field in fields
    }


def content_assessment_schema(view, packet):
    """Return the exact accepted Stage2ContentAssessment object shape."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **_object(
            {
                "kind": _const("Stage2ContentAssessment"),
                "schema_version": _const("1.0.0"),
                **_content_bindings(view),
                "evaluator_status": _const("complete"),
                "findings": {
                    "type": "array",
                    "minItems": 1,
                    "items": _object(
                        {
                            "finding_id": _text(),
                            "statement": _text(),
                            "evidence_ids": _evidence_ids(packet, require_one=True),
                        }
                    ),
                },
            }
        ),
    }


def _criterion_schema(criterion_id, packet):
    return _object(
        {
            "criterion_id": _const(criterion_id),
            "status": {"type": "string", "enum": ["assessed", "unknown"]},
            "score": {"type": ["integer", "null"], "minimum": 0, "maximum": 2},
            "rationale": _text(),
            "evidence_ids": _evidence_ids(packet),
            "unknown_reason": {
                "type": ["string", "null"],
                "enum": [
                    None,
                    "source-lookup-failure",
                    "evidence-unavailable",
                    "evaluator-failure",
                ],
            },
        }
    )


def judge_assessment_schema(role, content_view, action_view, packet, rubric):
    """Return the exact accepted Stage2JudgeAssessment object shape."""

    bindings = {field: _const(content_view[field]) for field in HASH_FIELDS[:-2]}
    bindings.update(
        {
            "rubric_id": _const(rubric["rubric_id"]),
            "rubric_sha256": _const(content_view["rubric_sha256"]),
            "content_view_sha256": _const(canonical_hash(content_view)),
            "action_view_sha256": _const(canonical_hash(action_view)),
        }
    )
    latest = {}
    for row in packet["candidates"]:
        latest[row["candidate_id"]] = max(
            row["version"], latest.get(row["candidate_id"], 0)
        )
    coverage = [
        {"candidate_id": candidate_id, "version": latest[candidate_id]}
        for candidate_id in sorted(latest)
    ]
    coverage_schema = {
        "type": "array",
        "items": _object(
            {"candidate_id": _text(), "version": {"type": "integer", "minimum": 1}}
        ),
        "minItems": len(coverage),
        "maxItems": len(coverage),
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **_object(
            {
                "kind": _const("Stage2JudgeAssessment"),
                "schema_version": _const("1.0.0"),
                "role": _const(role),
                **bindings,
                "candidate_coverage": coverage_schema,
                "evaluator_status": {
                    "type": "string",
                    "enum": ["complete", "technical-failure"],
                },
                "failure_reason": {"type": ["string", "null"]},
                "criteria": {
                    "type": "array",
                    "items": {
                        "anyOf": [
                            _criterion_schema(criterion_id, packet)
                            for criterion_id in CRITERIA
                        ]
                    },
                    "minItems": len(CRITERIA),
                    "maxItems": len(CRITERIA),
                },
                "major_error_ids": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": deepcopy(rubric["major_error_ids"]),
                    },
                    "uniqueItems": True,
                },
                "audit_required": {"type": "boolean"},
                "audit_reasons": {
                    "type": "array",
                    "items": _text(),
                    "uniqueItems": True,
                },
                "audit_status": {
                    "type": "string",
                    "enum": ["required", "not-required"],
                },
                "confidence": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                },
                "central_evidence_inaccessible": {"type": "boolean"},
            }
        ),
    }
