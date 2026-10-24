"""Offline, version-bound P7/P8/P9 evaluation artifacts; no evaluator calls."""

import hashlib
from pathlib import Path
import re

from .contracts import Stage3Error, canonical_bytes, digest
from .preparation import CRITERIA, closed, sha256, text
from .review import RUBRIC as SEMANTIC_RUBRIC
from .storage import (
    decode_json,
    inspect_package,
    private_output,
    read_bytes,
    safe_path,
    write_new,
)
from .validation import check_plan


EVALUATION_SCHEMA_VERSION = "1.0.0"
GUIDANCE_VERSION = "stage3-evaluation-guidance-v1"
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = PLUGIN_ROOT / "evals/rubrics/stage23-general.v1.json"
GUIDANCE_PATH = PLUGIN_ROOT / "references/stage3-evaluation-guidance.v1.md"
LIMITATIONS = [
    "Offline external judgment only; no evaluator, model, provider, or native call was made.",
    "Artifact hashes establish byte integrity, not reviewer identity or scientific validity.",
    "Scores do not change plan status, satisfy blockers, authorize research, or support an external claim.",
]


def _raw_sha256(path):
    return hashlib.sha256(read_bytes(path)).hexdigest()


def _catalog_binding(path=CATALOG_PATH):
    raw = read_bytes(path)
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    catalog = decode_json(raw, label=path)
    if (
        not isinstance(catalog, dict)
        or catalog.get("rubric_id") != "stage23-general-v1"
        or catalog.get("formal_execution_enabled") is not False
        or not isinstance(catalog.get("criteria"), list)
    ):
        raise Stage3Error("invalid generic Stage3 criterion catalog")
    indexed = {}
    for row in catalog["criteria"]:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise Stage3Error("invalid generic Stage3 criterion")
        if row["id"] in indexed:
            raise Stage3Error("duplicate generic Stage3 criterion")
        indexed[row["id"]] = row
    selected = []
    for dimension, criterion_id in CRITERIA.items():
        row = indexed.get(criterion_id)
        if (
            row is None
            or row.get("dimension") != dimension
            or not isinstance(row.get("anchors"), dict)
            or set(row.get("anchors", {})) != {"0", "1", "2"}
            or any(
                not isinstance(item, str) or not item.strip()
                for item in row["anchors"].values()
            )
        ):
            raise Stage3Error("current P7/P8/P9 criterion anchors missing")
        selected.append(row)
    return {
        "path": str(safe_path(path)),
        "rubric_id": catalog["rubric_id"],
        "raw_sha256": raw_sha256,
        "selected_criteria": selected,
    }


def _guidance_binding(path=GUIDANCE_PATH):
    raw = read_bytes(path)
    try:
        decoded = raw.decode("utf-8")
    except UnicodeError as error:
        raise Stage3Error("Stage3 evaluation guidance must be UTF-8") from error
    if GUIDANCE_VERSION not in decoded:
        raise Stage3Error("Stage3 evaluation guidance version marker missing")
    return {
        "path": str(safe_path(path)),
        "version": GUIDANCE_VERSION,
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _source_snapshot(package, expected_manifest_sha256):
    saved = inspect_package(package, expected_manifest_sha256)
    plan = saved["artifacts"].get("plan.json")
    request = saved["artifacts"].get("request.json")
    if plan is None or not isinstance(request, dict) or "intake" not in request:
        raise Stage3Error("evaluation requires a valid saved plan and intake")
    intake = request["intake"]
    report = check_plan(plan, intake=intake)
    if not report["structural_valid"]:
        raise Stage3Error("saved plan fails source-aware structural validation")
    question_refs = [row["question_ref"] for row in plan["questions"]]
    if not question_refs or len(question_refs) != len(set(question_refs)):
        raise Stage3Error("saved plan question identity is empty or duplicated")
    return saved, plan, intake, request, question_refs


def prepare_evaluation(
    package,
    *,
    expected_manifest_sha256,
    output,
    catalog_path=CATALOG_PATH,
    guidance_path=GUIDANCE_PATH,
):
    """Save one immutable assessor request derived from a verified plan package."""
    target = private_output(output)
    if target.exists():
        raise Stage3Error(
            "evaluation request output exists; inspect it, do not overwrite"
        )
    saved, plan, intake, source_request, question_refs = _source_snapshot(
        package, expected_manifest_sha256
    )
    value = {
        "kind": "Stage3EvaluationRequest",
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "source": {
            "package": str(safe_path(package)),
            "manifest_sha256": expected_manifest_sha256,
            "manifest_raw_sha256": _raw_sha256(Path(package) / "manifest.json"),
            "request_raw_sha256": _raw_sha256(Path(package) / "request.json"),
            "plan_raw_sha256": _raw_sha256(Path(package) / "plan.json"),
        },
        "bindings": {
            "plan_sha256": digest(plan),
            "intake_sha256": digest(intake),
            "source_manifest_sha256": intake["source_manifest_sha256"],
            "plan_id": plan["plan_id"],
            "plan_version": plan["version"],
            "plan_schema_version": plan["schema_version"],
            "selected_candidates": plan["selected_candidates"],
            "question_refs": question_refs,
            "admission_scope": source_request["admission_scope"],
        },
        "assessor_view": {"plan": plan, "intake": intake},
        "catalog": _catalog_binding(catalog_path),
        "guidance": _guidance_binding(guidance_path),
        "semantic_rubric": {
            "version": SEMANTIC_RUBRIC["version"],
            "sha256": digest(SEMANTIC_RUBRIC),
            "distinct_from_scoring": True,
        },
        "policy": {
            "scores_are_separate": True,
            "automatic_retry": False,
            "execution_authorized": False,
            "evaluation_calls_authorized": False,
            "formal_execution_enabled": False,
            "external_claim_ready": False,
        },
        "limitations": LIMITATIONS,
    }
    # Reuse the inspected value so preparation cannot claim an unverified manifest.
    if saved["manifest"]["manifest_sha256"] != expected_manifest_sha256:
        raise Stage3Error("saved plan manifest binding changed")
    write_new(target, value)
    return value


def _validate_request(value):
    closed(
        value,
        {
            "kind",
            "schema_version",
            "source",
            "bindings",
            "assessor_view",
            "catalog",
            "guidance",
            "semantic_rubric",
            "policy",
            "limitations",
        },
        "evaluation request",
    )
    if (
        value["kind"] != "Stage3EvaluationRequest"
        or value["schema_version"] != EVALUATION_SCHEMA_VERSION
    ):
        raise Stage3Error("unsupported evaluation request version")
    closed(
        value["source"],
        {
            "package",
            "manifest_sha256",
            "manifest_raw_sha256",
            "request_raw_sha256",
            "plan_raw_sha256",
        },
        "evaluation source",
    )
    source = value["source"]
    text(source["package"], "evaluation source package")
    for name in (
        "manifest_sha256",
        "manifest_raw_sha256",
        "request_raw_sha256",
        "plan_raw_sha256",
    ):
        sha256(source[name])
    saved, plan, intake, source_request, question_refs = _source_snapshot(
        source["package"], source["manifest_sha256"]
    )
    expected_source = {
        "package": str(safe_path(source["package"])),
        "manifest_sha256": source["manifest_sha256"],
        "manifest_raw_sha256": _raw_sha256(Path(source["package"]) / "manifest.json"),
        "request_raw_sha256": _raw_sha256(Path(source["package"]) / "request.json"),
        "plan_raw_sha256": _raw_sha256(Path(source["package"]) / "plan.json"),
    }
    expected_bindings = {
        "plan_sha256": digest(plan),
        "intake_sha256": digest(intake),
        "source_manifest_sha256": intake["source_manifest_sha256"],
        "plan_id": plan["plan_id"],
        "plan_version": plan["version"],
        "plan_schema_version": plan["schema_version"],
        "selected_candidates": plan["selected_candidates"],
        "question_refs": question_refs,
        "admission_scope": source_request["admission_scope"],
    }
    expected_policy = {
        "scores_are_separate": True,
        "automatic_retry": False,
        "execution_authorized": False,
        "evaluation_calls_authorized": False,
        "formal_execution_enabled": False,
        "external_claim_ready": False,
    }
    closed(
        value["catalog"],
        {"path", "rubric_id", "raw_sha256", "selected_criteria"},
        "evaluation catalog binding",
    )
    closed(
        value["guidance"],
        {"path", "version", "raw_sha256"},
        "evaluation guidance binding",
    )
    text(value["catalog"]["path"], "evaluation catalog path")
    text(value["guidance"]["path"], "evaluation guidance path")
    if (
        source != expected_source
        or digest(value["bindings"]) != digest(expected_bindings)
        or digest(value["assessor_view"]) != digest({"plan": plan, "intake": intake})
        or value["catalog"] != _catalog_binding(value["catalog"].get("path"))
        or value["guidance"] != _guidance_binding(value["guidance"].get("path"))
        or digest(value["semantic_rubric"])
        != digest(
            {
                "version": SEMANTIC_RUBRIC["version"],
                "sha256": digest(SEMANTIC_RUBRIC),
                "distinct_from_scoring": True,
            }
        )
        or digest(value["policy"]) != digest(expected_policy)
        or value["limitations"] != LIMITATIONS
        or saved["manifest"]["manifest_sha256"] != source["manifest_sha256"]
    ):
        raise Stage3Error("evaluation request binding mismatch")
    return plan, question_refs


def _pointer_exists(plan, pointer):
    if not isinstance(pointer, str) or not pointer.startswith("/") or pointer == "/":
        return False
    value = plan
    try:
        for token in pointer[1:].split("/"):
            if re.search(r"~(?![01])", token):
                return False
            token = token.replace("~1", "/").replace("~0", "~")
            if isinstance(value, list):
                if re.fullmatch(r"0|[1-9][0-9]*", token) is None:
                    return False
                value = value[int(token)]
            else:
                value = value[token]
    except (KeyError, IndexError, TypeError, ValueError):
        return False
    return True


def _validate_judgment(judgment, request_sha256, plan, question_refs):
    closed(
        judgment,
        {"kind", "schema_version", "request_sha256", "reviewer", "criteria"},
        "evaluation judgment",
    )
    if (
        judgment["kind"] != "Stage3EvaluationJudgment"
        or judgment["schema_version"] != EVALUATION_SCHEMA_VERSION
        or judgment["request_sha256"] != request_sha256
    ):
        raise Stage3Error("evaluation judgment request/version mismatch")
    reviewer = judgment["reviewer"]
    closed(
        reviewer,
        {
            "actor",
            "kind",
            "relationship_to_author",
            "identity_authenticated",
            "evidence_ref",
        },
        "evaluation reviewer",
    )
    if (
        not isinstance(reviewer["kind"], str)
        or reviewer["kind"]
        not in {"human-record", "external-model-record", "synthetic"}
        or reviewer["identity_authenticated"] is not False
    ):
        raise Stage3Error("reviewer kind and unauthenticated identity must be explicit")
    for field in ("actor", "relationship_to_author", "evidence_ref"):
        text(reviewer[field], "reviewer " + field)
    if not isinstance(judgment["criteria"], list):
        raise Stage3Error("evaluation criteria must be a list")
    indexed = {}
    for row in judgment["criteria"]:
        if not isinstance(row, dict) or not isinstance(row.get("criterion_id"), str):
            raise Stage3Error("invalid evaluation criterion record")
        criterion_id = row["criterion_id"]
        if criterion_id in indexed or criterion_id not in CRITERIA.values():
            raise Stage3Error("duplicate or unknown evaluation criterion")
        status = row.get("status")
        if not isinstance(status, str):
            raise Stage3Error("criterion status must be a string")
        if status == "grader_error":
            closed(row, {"criterion_id", "status", "score", "error"}, "grader error")
            if row["score"] is not None:
                raise Stage3Error("grader_error score must be null")
            closed(row["error"], {"kind", "message"}, "grader error detail")
            text(row["error"]["kind"], "grader error kind")
            text(row["error"]["message"], "grader error message")
        elif status in {"scored", "unverifiable"}:
            required = {"criterion_id", "status", "score", "question_assessments"}
            if status == "unverifiable":
                required.add("missing_evidence_reason")
            closed(row, required, "criterion assessment")
            if status == "scored":
                if type(row["score"]) is not int or row["score"] not in {0, 1, 2}:
                    raise Stage3Error("scored criterion requires integer 0, 1, or 2")
            elif row["score"] is not None:
                raise Stage3Error("unverifiable score must be null")
            if status == "unverifiable":
                text(row["missing_evidence_reason"], "missing evidence reason")
            assessments = row["question_assessments"]
            if not isinstance(assessments, list) or len(assessments) != len(
                question_refs
            ):
                raise Stage3Error("every selected question requires one assessment")
            seen = set()
            for item in assessments:
                closed(
                    item,
                    {
                        "question_ref",
                        "applicability_basis",
                        "rationale",
                        "plan_locations",
                    },
                    "question assessment",
                )
                question_ref = item["question_ref"]
                if question_ref not in question_refs or question_ref in seen:
                    raise Stage3Error("question assessment is duplicate or unknown")
                seen.add(question_ref)
                text(item["applicability_basis"], "applicability basis")
                text(item["rationale"], "assessment rationale")
                if (
                    not isinstance(item["plan_locations"], list)
                    or not item["plan_locations"]
                ):
                    raise Stage3Error("question assessment needs plan evidence")
                if any(
                    not _pointer_exists(plan, pointer)
                    for pointer in item["plan_locations"]
                ):
                    raise Stage3Error(
                        "question assessment plan location does not exist"
                    )
            if seen != set(question_refs):
                raise Stage3Error("criterion does not cover every selected question")
        else:
            raise Stage3Error(
                "criterion status must be scored, unverifiable, or grader_error"
            )
        indexed[criterion_id] = row
    if set(indexed) != set(CRITERIA.values()):
        raise Stage3Error("exactly the current P7/P8/P9 criteria are required")
    return indexed


def _failure_record(request_sha256, judgment_sha256, raw_text, error):
    return {
        "kind": "Stage3EvaluationRecord",
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "record_status": "failed",
        "request_sha256": request_sha256,
        "judgment_sha256": judgment_sha256,
        "raw_judgment_text": raw_text,
        "error": {"kind": type(error).__name__, "message": str(error)},
        "execution_authorized": False,
        "evaluation_calls_authorized": False,
        "formal_execution_enabled": False,
        "external_claim_ready": False,
        "limitations": LIMITATIONS,
    }


def record_evaluation(
    request,
    *,
    expected_request_sha256,
    judgment,
    expected_judgment_sha256,
    output,
):
    """Validate an externally supplied judgment and save its exact UTF-8 text."""
    target = private_output(output)
    if target.exists():
        raise Stage3Error(
            "evaluation record output exists; inspect it, do not overwrite"
        )
    request_raw = read_bytes(request)
    if hashlib.sha256(request_raw).hexdigest() != expected_request_sha256:
        raise Stage3Error("external evaluation request hash mismatch")
    request_value = decode_json(request_raw, label=request)
    plan, question_refs = _validate_request(request_value)
    judgment_raw = read_bytes(judgment)
    judgment_sha256 = hashlib.sha256(judgment_raw).hexdigest()
    try:
        raw_text = judgment_raw.decode("utf-8")
    except UnicodeError as error:
        raise Stage3Error("evaluation judgment must be UTF-8") from error
    if judgment_sha256 != expected_judgment_sha256:
        raise Stage3Error("external evaluation judgment hash mismatch")
    try:
        judgment_value = decode_json(judgment_raw, label=judgment)
        indexed = _validate_judgment(
            judgment_value, expected_request_sha256, plan, question_refs
        )
        # Reject unencodable text while the unchanged raw judgment can be retained.
        canonical_bytes(judgment_value)
    except (Stage3Error, OSError, ValueError) as error:
        write_new(
            target,
            _failure_record(expected_request_sha256, judgment_sha256, raw_text, error),
        )
        raise Stage3Error(
            f"invalid judgment retained in failure record: {error}"
        ) from error
    vector = {
        dimension: {
            "criterion_id": criterion_id,
            "status": indexed[criterion_id]["status"],
            "score": indexed[criterion_id]["score"],
        }
        for dimension, criterion_id in CRITERIA.items()
    }
    value = {
        "kind": "Stage3EvaluationRecord",
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "record_status": "recorded",
        "request_sha256": expected_request_sha256,
        "judgment_sha256": judgment_sha256,
        "raw_judgment_text": raw_text,
        "reviewer": judgment_value["reviewer"],
        "criteria": [indexed[criterion_id] for criterion_id in CRITERIA.values()],
        "score_vector": vector,
        "bindings": request_value["bindings"],
        "catalog": request_value["catalog"],
        "guidance": request_value["guidance"],
        "semantic_rubric": request_value["semantic_rubric"],
        "execution_authorized": False,
        "evaluation_calls_authorized": False,
        "formal_execution_enabled": False,
        "external_claim_ready": False,
        "limitations": LIMITATIONS,
    }
    write_new(target, value)
    return value


def inspect_evaluation_request(path, *, expected_sha256):
    """Revalidate a pinned request against its saved plan, sources and guidance."""
    from .preparation import file_binding

    value = file_binding(path, expected_sha256)
    _validate_request(value)
    return value
