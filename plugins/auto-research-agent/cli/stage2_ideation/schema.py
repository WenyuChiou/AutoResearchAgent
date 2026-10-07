"""Machine-readable contract for Stage 2 proposal extraction."""

import copy
import json
from pathlib import Path


SCHEMA_VERSION = "1.0.0"
SCHEMA_VERSION_1_1 = "1.1.0"
_PACKET_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "schemas/stage2-packet.v1.schema.json"
)


def _packet_defs():
    packet_schema = json.loads(_PACKET_SCHEMA_PATH.read_text(encoding="utf-8"))
    return {
        name: copy.deepcopy(packet_schema["$defs"][name])
        for name in ("text", "id", "sha", "candidate")
    }


def _add_research_table_defs(defs):
    defs.update(
        {
            "research_dimension": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "dimension_id",
                    "label",
                    "research_need",
                    "rationale",
                    "definition",
                    "value_kind",
                    "conditions",
                    "spans",
                ],
                "properties": {
                    "dimension_id": {"$ref": "#/$defs/id"},
                    "label": {"$ref": "#/$defs/text"},
                    "research_need": {"$ref": "#/$defs/text"},
                    "rationale": {"$ref": "#/$defs/text"},
                    "definition": {"$ref": "#/$defs/text"},
                    "value_kind": {"enum": ["feature", "text", "quantity"]},
                    "conditions": {"type": "array", "items": {"$ref": "#/$defs/text"}},
                    "spans": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"$ref": "#/$defs/span"},
                    },
                },
            },
            "research_work_ref": {
                "type": "object",
                "additionalProperties": False,
                "required": ["work_id", "version_id"],
                "properties": {
                    "work_id": {"$ref": "#/$defs/id"},
                    "version_id": {"$ref": "#/$defs/id"},
                },
            },
            "research_cell": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "dimension_id",
                    "work_id",
                    "version_id",
                    "status",
                    "value",
                    "reason",
                    "inspection_scope",
                    "negative_basis",
                    "evidence_ids",
                    "spans",
                ],
                "properties": {
                    "dimension_id": {"$ref": "#/$defs/id"},
                    "work_id": {"$ref": "#/$defs/id"},
                    "version_id": {"$ref": "#/$defs/id"},
                    "status": {
                        "enum": [
                            "present",
                            "absent",
                            "partial",
                            "described",
                            "unknown",
                            "not-applicable",
                        ]
                    },
                    "value": {"type": ["string", "number", "boolean", "null"]},
                    "reason": {"$ref": "#/$defs/nullable_text"},
                    "inspection_scope": {"$ref": "#/$defs/nullable_text"},
                    "negative_basis": {
                        "enum": [
                            "explicit-statement",
                            "bounded-design-inspection",
                            None,
                        ]
                    },
                    "evidence_ids": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": {"$ref": "#/$defs/id"},
                    },
                    "spans": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"$ref": "#/$defs/span"},
                    },
                },
            },
            "research_resource": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "resource_id",
                    "candidate_index",
                    "category",
                    "name",
                    "purpose",
                    "url",
                    "version",
                    "required",
                    "status",
                    "access_conditions",
                    "license",
                    "cost_basis",
                    "limitations",
                    "alternatives",
                    "evidence_ids",
                    "checked_at",
                    "spans",
                ],
                "properties": {
                    "resource_id": {"$ref": "#/$defs/id"},
                    "candidate_index": {"type": "integer", "minimum": 0},
                    "category": {
                        "enum": ["dataset", "report", "reference", "model", "tool"]
                    },
                    "name": {"$ref": "#/$defs/text"},
                    "purpose": {"$ref": "#/$defs/text"},
                    "url": {"$ref": "#/$defs/nullable_text"},
                    "version": {"$ref": "#/$defs/nullable_text"},
                    "required": {"type": "boolean"},
                    "status": {
                        "enum": [
                            "available",
                            "restricted",
                            "unavailable",
                            "unknown",
                            "not-applicable",
                        ]
                    },
                    "access_conditions": {"$ref": "#/$defs/nullable_text"},
                    "license": {"$ref": "#/$defs/nullable_text"},
                    "cost_basis": {"$ref": "#/$defs/nullable_text"},
                    "limitations": {"type": "array", "items": {"$ref": "#/$defs/text"}},
                    "alternatives": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/text"},
                    },
                    "evidence_ids": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": {"$ref": "#/$defs/id"},
                    },
                    "checked_at": {"$ref": "#/$defs/nullable_text"},
                    "spans": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"$ref": "#/$defs/span"},
                    },
                },
            },
            "research_tables_extraction": {
                "type": "object",
                "additionalProperties": False,
                "required": ["dimensions", "work_refs", "cells", "direction_resources"],
                "properties": {
                    "dimensions": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"$ref": "#/$defs/research_dimension"},
                    },
                    "work_refs": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"$ref": "#/$defs/research_work_ref"},
                    },
                    "cells": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/research_cell"},
                    },
                    "direction_resources": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/research_resource"},
                    },
                },
            },
        }
    )


def extraction_schema(version=SCHEMA_VERSION):
    """Return a fresh JSON Schema using the canonical Stage 2 candidate shape."""

    if version not in {SCHEMA_VERSION, SCHEMA_VERSION_1_1}:
        raise ValueError(f"unsupported extraction schema version: {version}")
    defs = _packet_defs()
    defs.update(
        {
            "nullable_text": {"anyOf": [{"$ref": "#/$defs/text"}, {"type": "null"}]},
            "source_ref": {
                "type": "object",
                "additionalProperties": False,
                "required": ["source_id", "work_id", "version_id"],
                "properties": {
                    "source_id": {"$ref": "#/$defs/id"},
                    "work_id": {"$ref": "#/$defs/id"},
                    "version_id": {"$ref": "#/$defs/id"},
                },
            },
            "span": {
                "type": "object",
                "additionalProperties": False,
                "required": ["start", "end", "quote"],
                "properties": {
                    "start": {"type": "integer", "minimum": 0},
                    "end": {"type": "integer", "minimum": 1},
                    "quote": {"$ref": "#/$defs/text"},
                },
            },
            "bibliography_row": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "source_id",
                    "work_id",
                    "version_id",
                    "title",
                    "authors",
                    "year",
                    "identifier",
                    "roles",
                ],
                "properties": {
                    "source_id": {"$ref": "#/$defs/id"},
                    "work_id": {"$ref": "#/$defs/id"},
                    "version_id": {"$ref": "#/$defs/id"},
                    "title": {"$ref": "#/$defs/nullable_text"},
                    "authors": {"$ref": "#/$defs/nullable_text"},
                    "year": {"$ref": "#/$defs/nullable_text"},
                    "identifier": {"$ref": "#/$defs/nullable_text"},
                    "roles": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/text"},
                    },
                },
            },
            "source_role": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "source_id",
                    "work_id",
                    "version_id",
                    "role",
                    "evidence_ids",
                ],
                "properties": {
                    "source_id": {"$ref": "#/$defs/id"},
                    "work_id": {"$ref": "#/$defs/id"},
                    "version_id": {"$ref": "#/$defs/id"},
                    "role": {"$ref": "#/$defs/text"},
                    "evidence_ids": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/id"},
                    },
                },
            },
            "relationship": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "relationship",
                    "source_refs",
                    "evidence_ids",
                    "detail",
                ],
                "properties": {
                    "relationship": {
                        "enum": [
                            "shared-study",
                            "shared-data",
                            "shared-citation",
                            "other",
                        ]
                    },
                    "source_refs": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/source_ref"},
                    },
                    "evidence_ids": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/id"},
                    },
                    "detail": {"$ref": "#/$defs/text"},
                },
            },
            "comparison_row": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "dimension",
                    "finding",
                    "comparability",
                    "noncomparability",
                    "source_roles",
                    "shared_relationships",
                    "evidence_ids",
                    "spans",
                ],
                "properties": {
                    "dimension": {"$ref": "#/$defs/text"},
                    "finding": {"$ref": "#/$defs/text"},
                    "comparability": {
                        "enum": [
                            "comparable",
                            "partly-comparable",
                            "noncomparable",
                            "unknown",
                        ]
                    },
                    "noncomparability": {"$ref": "#/$defs/nullable_text"},
                    "source_roles": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/source_role"},
                    },
                    "shared_relationships": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/relationship"},
                    },
                    "evidence_ids": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/id"},
                    },
                    "spans": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"$ref": "#/$defs/span"},
                    },
                },
            },
            "closest_work_ref": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "source_id",
                    "work_id",
                    "version_id",
                    "evidence_ids",
                ],
                "properties": {
                    "source_id": {"$ref": "#/$defs/id"},
                    "work_id": {"$ref": "#/$defs/id"},
                    "version_id": {"$ref": "#/$defs/id"},
                    "evidence_ids": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/id"},
                    },
                },
            },
            "claim_label": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "status", "evidence_ids"],
                "properties": {
                    "text": {"$ref": "#/$defs/text"},
                    "status": {
                        "enum": ["fact", "inference", "untested-benefit", "unknown"]
                    },
                    "evidence_ids": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/id"},
                    },
                },
            },
            "candidate_row": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "candidate",
                    "route",
                    "mechanism",
                    "closest_work_refs",
                    "strong_alternatives",
                    "change_mind_conditions",
                    "claim_labels",
                    "spans",
                ],
                "properties": {
                    "candidate": {"$ref": "#/$defs/candidate"},
                    "route": {
                        "enum": [
                            "improvement",
                            "new-concept",
                            "mixed",
                            "unspecified",
                        ]
                    },
                    "mechanism": {"$ref": "#/$defs/text"},
                    "closest_work_refs": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/closest_work_ref"},
                    },
                    "strong_alternatives": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"$ref": "#/$defs/text"},
                    },
                    "change_mind_conditions": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"$ref": "#/$defs/text"},
                    },
                    "claim_labels": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"$ref": "#/$defs/claim_label"},
                    },
                    "spans": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"$ref": "#/$defs/span"},
                    },
                },
            },
        }
    )
    required = [
        "kind",
        "schema_version",
        "snapshot_sha256",
        "packet_sha256",
        "raw_proposal_sha256",
        "input_hash",
        "receipt",
        "bibliography",
        "comparison_rows",
        "candidates",
        "unresolved",
    ]
    properties = {
        "kind": {"const": "Stage2IdeationExtraction"},
        "schema_version": {"const": version},
        "snapshot_sha256": {"$ref": "#/$defs/sha"},
        "packet_sha256": {"$ref": "#/$defs/sha"},
        "raw_proposal_sha256": {"$ref": "#/$defs/sha"},
        "input_hash": {"$ref": "#/$defs/sha"},
        "receipt": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "policy_boundary",
                "tools_policy",
                "tool_calls",
                "isolation_verified",
            ],
            "properties": {
                "policy_boundary": {"const": "declared-task-policy"},
                "tools_policy": {"const": "none"},
                "tool_calls": {"type": "array", "maxItems": 0},
                "isolation_verified": {"const": False},
            },
        },
        "bibliography": {
            "type": "array",
            "items": {"$ref": "#/$defs/bibliography_row"},
        },
        "comparison_rows": {
            "type": "array",
            "items": {"$ref": "#/$defs/comparison_row"},
        },
        "candidates": {"type": "array", "items": {"$ref": "#/$defs/candidate_row"}},
        "unresolved": {"type": "array", "items": {"$ref": "#/$defs/text"}},
    }
    if version == SCHEMA_VERSION_1_1:
        _add_research_table_defs(defs)
        required.append("research_tables")
        properties["research_tables"] = {
            "anyOf": [{"$ref": "#/$defs/research_tables_extraction"}, {"type": "null"}]
        }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (
            "stage2-ideation-extraction.v1.schema.json"
            if version == SCHEMA_VERSION
            else "stage2-ideation-extraction.v1_1.schema.json"
        ),
        "title": (
            "Stage 2 ideation extraction v1"
            if version == SCHEMA_VERSION
            else "Stage 2 ideation extraction v1.1"
        ),
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
        "$defs": defs,
    }
