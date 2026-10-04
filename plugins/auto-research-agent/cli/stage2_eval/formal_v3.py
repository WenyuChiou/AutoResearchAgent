"""Separate formal-plan admission for balanced Stage 2 rubric v3.

Plan freeze is not runtime readiness, completed execution, or improvement.
Historical v1 plans and their seven-criterion results are never relabelled.
"""

from copy import deepcopy

from stage2_common import canonical_hash
from .evaluation_v3 import CRITERIA_V3, DIMENSIONS_V3, RUBRIC_PATH_V3
from .formal import _fields, _freeze_formal_plan, _require, _read_ref, _verify_ref

VERSION = "2.0.0"


def validate_common_evidence_v2(manifest, evidence_root, brief_ref):
    """Admit source facts and unknowns, never a prior subject's selection."""
    _fields(
        manifest,
        ("kind", "schema_version", "brief", "sources", "claims", "unknowns"),
        "formal common evidence",
    )
    _require(
        manifest["kind"] == "Stage2FormalCommonEvidence"
        and manifest["schema_version"] == "1.0.0",
        "formal common evidence version",
    )
    _require(manifest["brief"] == brief_ref, "formal common brief mismatch")
    _require(
        isinstance(manifest["sources"], list) and bool(manifest["sources"]),
        "formal common sources required",
    )
    sources = {}
    for row in manifest["sources"]:
        _fields(
            row,
            ("source_id", "work_id", "version_id", "artifact", "evidence_level"),
            "formal common source",
        )
        for key in ("source_id", "work_id", "version_id"):
            _require(
                isinstance(row[key], str) and bool(row[key].strip()),
                "formal common source identifier",
            )
        _require(row["source_id"] not in sources, "formal common duplicate source")
        _require(
            row["evidence_level"] in ("metadata", "abstract", "full-text", "unknown"),
            "formal common evidence level",
        )
        _verify_ref(evidence_root, row["artifact"], "formal common source")
        sources[row["source_id"]] = row
    _require(isinstance(manifest["claims"], list), "formal common claims required")
    claim_ids = set()
    for row in manifest["claims"]:
        _fields(
            row,
            (
                "claim_id",
                "source_id",
                "work_id",
                "version_id",
                "text",
                "verification",
                "locator",
            ),
            "formal common claim",
        )
        _require(
            isinstance(row["claim_id"], str) and bool(row["claim_id"].strip()),
            "formal common claim identifier",
        )
        _require(row["claim_id"] not in claim_ids, "formal common duplicate claim")
        claim_ids.add(row["claim_id"])
        _require(
            isinstance(row["source_id"], str) and row["source_id"] in sources,
            "formal common claim source",
        )
        source = sources[row["source_id"]]
        _require(
            row["work_id"] == source["work_id"]
            and row["version_id"] == source["version_id"],
            "formal common claim work/version",
        )
        _require(
            row["verification"] in ("verified", "unverified", "unknown"),
            "formal common verification",
        )
        _require(
            isinstance(row["text"], str) and bool(row["text"].strip()),
            "formal common claim text",
        )
        _require(
            isinstance(row["locator"], str)
            and (bool(row["locator"].strip()) or row["verification"] != "verified"),
            "formal common claim locator",
        )
    _require(
        isinstance(manifest["unknowns"], list)
        and all(
            isinstance(value, str) and bool(value.strip())
            for value in manifest["unknowns"]
        ),
        "formal common unknowns",
    )


def freeze_formal_plan_v2(config, evidence_root):
    """Freeze common evidence and all six subjects with nine fixed criteria."""
    plan = _freeze_formal_plan(config, evidence_root, RUBRIC_PATH_V3, VERSION)
    manifest, _ = _read_ref(
        evidence_root, config["stage1_source_manifest"], "formal common evidence"
    )
    validate_common_evidence_v2(manifest, evidence_root, config["brief"])
    plan.pop("plan_sha256")
    plan.update(
        rubric_id="stage2-general-v3",
        criterion_ids=list(CRITERIA_V3),
        dimension_denominators={
            key: 2 * len(ids) for key, ids in DIMENSIONS_V3.items()
        },
    )
    plan["plan_sha256"] = canonical_hash(plan)
    return plan


def validate_formal_plan_v2(plan, evidence_root):
    """Recompute from external artifact bytes, rejecting rehashed tampering."""
    extra = {"rubric_id", "criterion_ids", "dimension_denominators"}
    core = deepcopy(plan)
    for key in extra:
        core.pop(key, None)
    _fields(
        core,
        (
            "kind",
            "schema_version",
            "status",
            "brief",
            "rubric",
            "stage1_source_manifest",
            "prompt",
            "model",
            "reasoning",
            "task",
            "native_capability_policy",
            "cutoff",
            "investment_policy",
            "runtime_sha256",
            "plugin_sha256",
            "dependency_sha256",
            "evaluator_contracts",
            "runtime_contracts",
            "runs",
            "plan_sha256",
        ),
        "formal v3 plan",
    )
    config = {
        key: value
        for key, value in core.items()
        if key not in {"kind", "schema_version", "status", "plan_sha256"}
    }
    _require(
        plan == freeze_formal_plan_v2(config, evidence_root),
        "formal v3 plan changed after freeze",
    )
