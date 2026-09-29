"""Versioned, source-supplied Stage 2 diagnostic target contract."""

import hashlib
import json
from copy import deepcopy

from stage2_common import canonical_hash

CASE_FIELDS = {
    "kind",
    "schema_version",
    "case_id",
    "research_candidate",
    "claim_under_review",
    "screening_action",
    "source_facts",
}
RESULT_FIELDS = {
    "case_id",
    "case_sha256",
    "disposition_target",
    "disposition",
    "rationale",
    "evidence_refs",
    "next_step",
    "checks",
    "unsupported_assumptions",
}
CHECK_NAMES = ("opportunity", "value", "answerability", "materials", "execution")


class DiagnosticError(ValueError):
    """A diagnostic case, binding, or model output is malformed."""


def _require(condition, message):
    if not condition:
        raise DiagnosticError(message)


def _exact_fields(value, fields, label):
    _require(isinstance(value, dict), f"{label} must be an object")
    _require(set(value) == fields, f"invalid {label} fields")


def _text(value, label):
    _require(isinstance(value, str) and value.strip(), f"missing {label}")


def _positive_int(value, label):
    _require(type(value) is int and value > 0, f"{label} must be a positive integer")


def _sha256(value, label):
    _require(
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value),
        f"invalid {label}",
    )


def _validate_cases(cases):
    _require(
        isinstance(cases, list) and cases, "diagnostic cases must be a nonempty list"
    )
    case_ids = []
    evidence_ids = []
    validated = []
    for case in cases:
        _exact_fields(case, CASE_FIELDS, "case")
        _require(case["kind"] == "Stage2DiagnosticCase", "wrong diagnostic case kind")
        _require(case["schema_version"] == "2.0.0", "wrong diagnostic case version")
        _text(case["case_id"], "case_id")
        case_ids.append(case["case_id"])

        candidate = case["research_candidate"]
        _exact_fields(candidate, {"id", "version", "text"}, "research_candidate")
        _text(candidate["id"], "research candidate ID")
        _positive_int(candidate["version"], "research candidate version")
        _text(candidate["text"], "research candidate text")

        claim = case["claim_under_review"]
        _exact_fields(claim, {"id", "text"}, "claim_under_review")
        _text(claim["id"], "claim ID")
        _text(claim["text"], "claim text")

        action = case["screening_action"]
        if action is not None:
            _exact_fields(action, {"id", "action", "rationale"}, "screening_action")
            _text(action["id"], "screening action ID")
            _text(action["action"], "screening action")
            _text(action["rationale"], "screening action rationale")

        facts = case["source_facts"]
        _require(
            isinstance(facts, list) and facts, "source_facts must be a nonempty list"
        )
        case_evidence_ids = []
        for fact in facts:
            _exact_fields(
                fact,
                {"evidence_id", "work_id", "version_id", "text", "sha256"},
                "source fact",
            )
            for field in ("evidence_id", "work_id", "version_id", "text"):
                _text(fact[field], f"source fact {field}")
            _sha256(fact["sha256"], "source fact sha256")
            actual = hashlib.sha256(fact["text"].encode("utf-8")).hexdigest()
            _require(
                fact["sha256"] == actual,
                f"source fact hash mismatch: {fact['evidence_id']}",
            )
            case_evidence_ids.append(fact["evidence_id"])
            evidence_ids.append(fact["evidence_id"])
        _require(
            len(case_evidence_ids) == len(set(case_evidence_ids)),
            f"duplicate evidence_id in case: {case['case_id']}",
        )
        validated.append(case)
    _require(len(case_ids) == len(set(case_ids)), "duplicate case_id")
    _require(len(evidence_ids) == len(set(evidence_ids)), "duplicate evidence_id")
    return validated


def _validate_evidence_refs(refs, case, label):
    _require(isinstance(refs, list), f"{label} evidence_refs must be a list")
    facts = {row["evidence_id"]: row for row in case["source_facts"]}
    seen = []
    for ref in refs:
        _exact_fields(ref, {"evidence_id", "exact_quote"}, "evidence reference")
        _text(ref["evidence_id"], "evidence reference ID")
        _text(ref["exact_quote"], "exact evidence quote")
        fact = facts.get(ref["evidence_id"])
        _require(fact is not None, f"unknown evidence reference: {ref['evidence_id']}")
        _require(
            ref["exact_quote"] in fact["text"],
            f"evidence quote is not exact contiguous source text: {ref['evidence_id']}",
        )
        seen.append(ref["evidence_id"])
    _require(len(seen) == len(set(seen)), f"duplicate {label} evidence reference")


def _validate_target(target, case):
    _exact_fields(target, {"kind", "id", "version"}, "disposition target")
    _require(
        target["kind"] in ("candidate", "claim", "screening-action"),
        "invalid disposition target kind",
    )
    _text(target["id"], "disposition target ID")
    if target["kind"] == "candidate":
        candidate = case["research_candidate"]
        _require(target["id"] == candidate["id"], "candidate target mismatch")
        _positive_int(target["version"], "candidate target version")
        _require(
            target["version"] == candidate["version"],
            "stale candidate version",
        )
    elif target["kind"] == "claim":
        _require(
            target["id"] == case["claim_under_review"]["id"], "claim target mismatch"
        )
        _require(target["version"] is None, "claim target version must be null")
    else:
        action = case["screening_action"]
        _require(action is not None, "screening-action target has no source action")
        _require(target["id"] == action["id"], "screening-action target mismatch")
        _require(
            target["version"] is None, "screening-action target version must be null"
        )


def _validate_check(check, case, name, next_step):
    _exact_fields(
        check,
        {"status", "score", "rationale", "evidence_refs"},
        f"{name} check",
    )
    _require(
        check["status"] in ("assessed", "unknown", "not-applicable"),
        f"invalid {name} check status",
    )
    _text(check["rationale"], f"{name} check rationale")
    _validate_evidence_refs(check["evidence_refs"], case, name)
    if check["status"] == "assessed":
        _require(
            type(check["score"]) is int and check["score"] in {0, 1, 2},
            "assessed check needs integer 0, 1, or 2",
        )
        _require(check["evidence_refs"], "assessed check needs evidence")
    elif check["status"] == "unknown":
        _require(check["score"] is None, "unknown check needs null score")
        _text(next_step, "next check for unknown judgment")
    else:
        _require(check["score"] is None, "not-applicable check needs null score")


def prepare_diagnostic_prompt(cases, *, source_ids=False):
    """Build a tool-free prompt from validated synthetic diagnostic facts."""

    _validate_cases(cases)
    schema = {
        "kind": "Stage2DiagnosticOutput",
        "schema_version": "2.0.0",
        "results": [
            {
                "case_id": "...",
                "case_sha256": "copy the supplied CASE BINDINGS value for this case_id",
                "disposition_target": {
                    "kind": "candidate|claim|screening-action",
                    "id": "...",
                    "version": "positive integer for candidate; null otherwise",
                },
                "disposition": "recommend|revise|park|reject",
                "rationale": "...",
                "evidence_refs": [{"evidence_id": "...", "exact_quote": "..."}],
                "next_step": "...",
                "checks": {
                    name: {
                        "status": "assessed|unknown|not-applicable",
                        "score": "0|1|2|null",
                        "rationale": "...",
                        "evidence_refs": [{"evidence_id": "...", "exact_quote": "..."}],
                    }
                    for name in CHECK_NAMES
                },
                "unsupported_assumptions": ["..."],
            }
        ],
    }
    instructions = """Assess each case using natural scientific judgment and only the supplied facts.
Return JSON with exactly the specified fields and exactly one result per case. Keep unknown distinct from a score of zero. An assessed check needs source evidence; an unknown check needs a concrete next check in its rationale or next_step. Quote source text exactly.

A disposition applies only to disposition_target. Rejecting a claim or screening decision does not itself reject the research candidate. Assess opportunity, value, answerability, materials, and execution for the research candidate, separately from the disposition target. Support judgments with the supplied evidence and distinguish facts, unresolved research questions, and unverified prerequisites. Do not assume the initial claim or screening action is correct. The binding table is supplied by the host; copy hashes rather than calculating them.

If cases are presented as variants, use the exact same supplied scientific facts across variants. Do not infer topic answers, hidden keys, expected outcomes, or facts outside the case."""
    if source_ids:
        row = schema["results"][0]
        row["evidence_refs"] = [{"evidence_id": "..."}]
        for check in row["checks"].values():
            check["evidence_refs"] = [{"evidence_id": "..."}]
        instructions = instructions.replace(
            "Quote source text exactly.",
            "Select evidence_id values from this case. The host will restore their exact source text; do not retype quotes.",
        )
    return (
        instructions
        + "\n\nOUTPUT CONTRACT:\n"
        + json.dumps(schema, sort_keys=True, ensure_ascii=False, indent=2)
        + "\n\nCASE BINDINGS:\n"
        + json.dumps(
            {case["case_id"]: canonical_hash(case) for case in cases}, sort_keys=True
        )
        + "\n\nCASES:\n"
        + json.dumps(cases, sort_keys=True, ensure_ascii=False, indent=2)
    )


def validate_diagnostic_output(output, cases):
    """Validate only structure, identity, coverage, hashes, and verbatim bindings."""

    _validate_cases(cases)
    _exact_fields(output, {"kind", "schema_version", "results"}, "diagnostic output")
    _require(output["kind"] == "Stage2DiagnosticOutput", "wrong diagnostic output kind")
    _require(output["schema_version"] == "2.0.0", "wrong diagnostic output version")
    rows = output["results"]
    _require(isinstance(rows, list), "diagnostic results must be a list")
    case_by_id = {case["case_id"]: case for case in cases}
    result_ids = []
    for row in rows:
        _exact_fields(row, RESULT_FIELDS, "diagnostic result")
        _text(row["case_id"], "result case_id")
        result_ids.append(row["case_id"])
    _require(
        len(result_ids) == len(set(result_ids)) and set(result_ids) == set(case_by_id),
        "diagnostic output needs exact case coverage",
    )
    for row in rows:
        case = case_by_id[row["case_id"]]
        _sha256(row["case_sha256"], "case_sha256")
        _require(
            row["case_sha256"] == canonical_hash(case),
            f"case_sha256 mismatch: {row['case_id']}",
        )
        _validate_target(row["disposition_target"], case)
        _require(
            row["disposition"] in ("recommend", "revise", "park", "reject"),
            "invalid disposition",
        )
        _text(row["rationale"], "disposition rationale")
        _text(row["next_step"], "next_step")
        _validate_evidence_refs(row["evidence_refs"], case, "disposition")
        if row["disposition"] in {"recommend", "reject"}:
            _require(
                row["evidence_refs"], "recommend/reject disposition needs evidence"
            )
        checks = row["checks"]
        _require(isinstance(checks, dict), "checks must be an object")
        _require(
            set(checks) == set(CHECK_NAMES),
            "checks need all five dimensions exactly once",
        )
        for name in CHECK_NAMES:
            _validate_check(checks[name], case, name, row["next_step"])
        assumptions = row["unsupported_assumptions"]
        _require(
            isinstance(assumptions, list)
            and all(isinstance(value, str) and value.strip() for value in assumptions),
            "unsupported_assumptions must be nonblank strings",
        )
        _require(
            len(assumptions) == len(set(assumptions)),
            "duplicate unsupported assumption",
        )
    return {
        "valid": True,
        "scope": "technical-validity-only",
        "case_count": len(cases),
        "semantic_correctness_established": False,
        "formal_readiness_established": False,
        "quality_score": None,
        "improvement_established": False,
    }


def prepare_diagnostic_judge_view(output, cases):
    """Return a source-bound view without converting checks into quality claims."""

    validate_diagnostic_output(output, cases)
    case_by_id = {case["case_id"]: case for case in cases}
    rows = []
    for result in output["results"]:
        case = case_by_id[result["case_id"]]
        rows.append(
            {
                "case_id": result["case_id"],
                "case_sha256": result["case_sha256"],
                "research_candidate": deepcopy(case["research_candidate"]),
                "claim_under_review": deepcopy(case["claim_under_review"]),
                "screening_action": deepcopy(case["screening_action"]),
                "source_facts": deepcopy(case["source_facts"]),
                "disposition_target": deepcopy(result["disposition_target"]),
                "disposition": result["disposition"],
                "rationale": result["rationale"],
                "evidence_refs": deepcopy(result["evidence_refs"]),
                "next_step": result["next_step"],
                "checks": deepcopy(result["checks"]),
                "unsupported_assumptions": deepcopy(result["unsupported_assumptions"]),
            }
        )
    return {
        "kind": "Stage2DiagnosticJudgeView",
        "schema_version": "2.0.0",
        "validation_scope": "technical-validity-only",
        "semantic_correctness_established": False,
        "formal_readiness_established": False,
        "improvement_established": False,
        "cases": rows,
    }
