"""Fail-closed admission bridge for replayable Stage 2 v3 artifacts."""

from stage2_common import Stage2Error

from .evaluation_v3 import (
    CRITERIA_V3,
    compare_pairs_v3,
    dimension_scores_v3,
    validate_bundle_v3,
)
from .formal import (
    FormalError,
    _arm_contamination,
    _fields,
    _read_manifest,
    _read_ref,
    _require,
    _sha,
)
from .formal_v3 import validate_formal_plan_v2

VERSION = "2.0.0"
ORDERS = ("AB", "BA", "AB")
READINESS_BLOCKERS = (
    "complete-subagent-budget-accounting-unavailable",
    "formal-preflight-replay-format-unsupported",
    "native-v3-quality-replay-unavailable",
    "per-execution-inventory-collector-unavailable",
    "pilot-controller-replay-format-unsupported",
)


def _read_bound_ref(root, binding, label):
    _fields(binding, ("artifact", "receipt"), f"{label} binding")
    _sha(binding["receipt"], f"{label} receipt")
    result = _read_ref(root, binding["artifact"], label)
    _require(
        binding["receipt"] == binding["artifact"]["sha256"],
        f"{label} receipt mismatch",
    )
    return result


def _neutral(value, label):
    _require(not _arm_contamination(value), f"{label} contains arm assignment")


def validate_readiness_v2(
    manifest_path, evidence_root, externally_retained_manifest_receipt
):
    """Authenticate v3 readiness inputs while retaining explicit blockers."""

    manifest = _read_manifest(
        manifest_path,
        evidence_root,
        externally_retained_manifest_receipt,
        "Stage2FormalReadinessManifest",
        versions=(VERSION,),
    )
    _fields(
        manifest,
        (
            "kind",
            "schema_version",
            "formal_plan",
            "source_context",
            "preflights",
            "pilots",
            "calibration",
        ),
        "formal v3 readiness manifest",
    )
    plan, _ = _read_bound_ref(evidence_root, manifest["formal_plan"], "formal plan")
    validate_formal_plan_v2(plan, evidence_root)
    source, _ = _read_bound_ref(
        evidence_root, manifest["source_context"], "source context"
    )
    _require(
        manifest["source_context"]["artifact"] == plan["stage1_source_manifest"],
        "readiness source differs from frozen plan",
    )
    _neutral(source, "formal source context")
    preflights = manifest["preflights"]
    _require(isinstance(preflights, list), "preflights must be a list")
    for row in preflights:
        _fields(row, ("arm", "evidence"), "v3 preflight binding")
    _require(isinstance(preflights, list), "readiness preflights must be a list")
    _require(
        [row.get("arm") for row in preflights] == ["A", "B"],
        "readiness needs A/B preflights",
    )
    for row in preflights:
        _fields(row, ("arm", "evidence"), "v3 preflight binding")
        value, _ = _read_bound_ref(
            evidence_root, row["evidence"], f"{row['arm']} preflight"
        )
        _require(isinstance(value, dict), "preflight evidence must be an object")
    pilots = manifest["pilots"]
    _require(isinstance(pilots, list), "pilots must be a list")
    for row in pilots:
        _fields(row, ("topic_id", "evidence"), "v3 pilot binding")
    _require(
        isinstance(pilots, list)
        and [row.get("topic_id") for row in pilots] == ["US-aging", "flaky-tests"],
        "readiness needs two ordered pilots",
    )
    for row in pilots:
        _fields(row, ("topic_id", "evidence"), "v3 pilot binding")
        value, _ = _read_bound_ref(
            evidence_root, row["evidence"], f"{row['topic_id']} pilot"
        )
        _require(isinstance(value, dict), "pilot evidence must be an object")
    calibration, _ = _read_bound_ref(
        evidence_root, manifest["calibration"], "v3 calibration"
    )
    _require(isinstance(calibration, dict), "calibration evidence must be an object")
    _neutral(calibration, "formal calibration")

    return {
        "kind": "Stage2FormalReadinessValidation",
        "schema_version": VERSION,
        "status": "blocked",
        "formal_ready": False,
        "external_claim_ready": False,
        "validation_scope": "artifact-binding-only",
        "evidence_class": "manifest-bound-inputs",
        "blockers": list(READINESS_BLOCKERS),
        "plan_sha256": plan["plan_sha256"],
    }


def validate_formal_result_v2(
    manifest_path,
    evidence_root,
    externally_retained_manifest_receipt,
    plan,
):
    """Replay six v3 bundles and their pairs without promoting a claim."""

    validate_formal_plan_v2(plan, evidence_root)
    manifest = _read_manifest(
        manifest_path,
        evidence_root,
        externally_retained_manifest_receipt,
        "Stage2FormalResultManifest",
        versions=(VERSION,),
    )
    _fields(
        manifest,
        (
            "kind",
            "schema_version",
            "plan_sha256",
            "readiness",
            "runs",
            "pairs",
        ),
        "formal v3 result manifest",
    )
    _require(
        manifest["plan_sha256"] == plan["plan_sha256"],
        "formal result plan mismatch",
    )
    _read_bound_ref(evidence_root, manifest["readiness"], "readiness manifest")
    readiness = validate_readiness_v2(
        manifest["readiness"]["artifact"]["path"],
        evidence_root,
        manifest["readiness"]["receipt"],
    )
    _require(
        readiness["plan_sha256"] == plan["plan_sha256"],
        "readiness plan mismatch",
    )

    runs = manifest["runs"]
    _require(isinstance(runs, list) and len(runs) == 6, "formal result needs six runs")
    for row in runs:
        _fields(row, ("subject_id", "judge_bundle"), "formal v3 run")
    expected_subjects = [row["subject_id"] for row in plan["runs"]]
    _require(
        [row.get("subject_id") for row in runs] == expected_subjects,
        "formal result subject coverage mismatch",
    )
    bundles = {}
    for row in runs:
        _fields(row, ("subject_id", "judge_bundle"), "formal v3 run")
        bundle, _ = _read_bound_ref(
            evidence_root, row["judge_bundle"], f"{row['subject_id']} judge bundle"
        )
        try:
            validate_bundle_v3(bundle)
        except Stage2Error as error:
            raise FormalError(f"invalid v3 judge bundle: {error}") from error
        _require(
            bundle["subject_id"] == row["subject_id"], "judge bundle subject mismatch"
        )
        scores = dimension_scores_v3(bundle)
        if scores is not None:
            _require(
                set(scores) == {"P4", "P5", "P6"}
                and all(value["max"] == 6 for value in scores.values())
                and [item["criterion_id"] for item in bundle["criteria"]]
                == list(CRITERIA_V3),
                "v3 bundle criteria or denominators changed",
            )
        bundles[row["subject_id"]] = bundle

    expected_pairs = []
    for index, order in enumerate(ORDERS):
        planned = plan["runs"][index * 2 : index * 2 + 2]
        by_arm = {row["arm"]: bundles[row["subject_id"]] for row in planned}
        expected_pairs.append(
            {
                "pair_id": f"pair-{index + 1}",
                "order": order,
                "A": by_arm["A"],
                "B": by_arm["B"],
                "A_content_view_sha256": by_arm["A"]["content_view_sha256"],
                "B_content_view_sha256": by_arm["B"]["content_view_sha256"],
            }
        )
    pairs, _ = _read_bound_ref(evidence_root, manifest["pairs"], "formal pairs")
    _require(pairs == expected_pairs, "formal pairs differ from six bound runs")
    try:
        comparison = compare_pairs_v3(pairs)
    except Stage2Error as error:
        raise FormalError(f"invalid v3 formal pairs: {error}") from error

    blockers = sorted(set(readiness["blockers"]))
    return {
        "kind": "Stage2FormalResultValidation",
        "schema_version": VERSION,
        "status": "inconclusive",
        "formal_ready": False,
        "external_claim_ready": False,
        "validation_scope": "artifact-binding-and-v3-bundle-replay",
        "blockers": blockers,
        "comparison": comparison,
        "formal_decision": "inconclusive",
        "improvement_established": False,
    }
