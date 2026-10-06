"""Offline Stage 2 v3 judging that preserves v2 bytes and behavior."""

import json
from copy import deepcopy
from pathlib import Path

from stage1_brief.brief import validate_brief
from stage2_common import Stage2Error, canonical_hash, validate_evidence_refs

from . import evaluation as v2


RUBRIC_PATH_V3 = (
    Path(__file__).resolve().parents[2] / "evals/rubrics/stage2-general.v3.json"
)
CRITERIA_V3 = (
    "P4V3.FIDELITY",
    "P4V3.COMPARABILITY",
    "P4V3.SYNTHESIS",
    "P5V3.PRECEDENT",
    "P5V3.CONTRIBUTION",
    "P5V3.REVISION",
    "P6V3.VALUE",
    "P6V3.FEASIBILITY",
    "P6V3.CHOICE",
)
DIMENSIONS_V3 = {
    "P4": CRITERIA_V3[:3],
    "P5": CRITERIA_V3[3:6],
    "P6": CRITERIA_V3[6:],
}
HASH_FIELDS_V3 = v2.HASH_FIELDS


def _require(condition, message):
    if not condition:
        raise Stage2Error(message)


def _load_rubric_v3(path=None):
    if path is not None:
        supplied = Path(path).resolve()
        _require(
            supplied == RUBRIC_PATH_V3.resolve(),
            "custom Stage 2 rubrics are unsupported by the fixed offline v3 contract",
        )
    try:
        raw = RUBRIC_PATH_V3.read_bytes()
        rubric = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise Stage2Error(f"cannot load Stage 2 v3 rubric: {error}") from error
    _require(rubric.get("rubric_id") == "stage2-general-v3", "wrong Stage 2 v3 rubric")
    _require(rubric.get("status") == "experimental", "rubric must remain experimental")
    rows = rubric.get("criteria")
    _require(isinstance(rows, list), "rubric criteria missing")
    _require(
        tuple(row.get("id") for row in rows) == CRITERIA_V3,
        "v3 rubric needs all nine criteria exactly once",
    )
    for dimension, keys in DIMENSIONS_V3.items():
        _require(len(keys) == 3, f"{dimension} must have three required criteria")
    for row in rows:
        _require(row.get("dimension") == row["id"][:2], "rubric dimension mismatch")
        v2._text(row.get("question"), "rubric question")
        anchors = row.get("anchors")
        _require(
            isinstance(anchors, dict) and set(anchors) == {"0", "1", "2"},
            "rubric anchors changed",
        )
        for value in anchors.values():
            v2._text(value, "rubric anchor")
    return rubric, canonical_hash(rubric)


def _bindings_v3(packet, subject_id, input_sha256, config_sha256, rubric_path):
    v2._text(subject_id, "opaque subject ID")
    v2._hash(input_sha256, "input_sha256")
    v2._hash(config_sha256, "config_sha256")
    rubric, rubric_sha256 = _load_rubric_v3(rubric_path)
    return {
        "subject_id": subject_id,
        "packet_sha256": canonical_hash(packet),
        "input_sha256": input_sha256,
        "config_sha256": config_sha256,
        "rubric_id": rubric["rubric_id"],
        "rubric_sha256": rubric_sha256,
    }


def prepare_content_view_v3(
    packet, subject_id, input_sha256, config_sha256, *, rubric_path=None
):
    """Build the condition-blind, latest-version content view for rubric v3."""

    candidates = []
    for row in v2._latest(packet):
        candidates.append(
            {
                key: row[key]
                for key in (
                    "candidate_id",
                    "version",
                    "question",
                    "research_mode",
                    "opportunity",
                    "value",
                    "approach",
                    "requirements",
                    "limitations",
                    "evidence_ids",
                )
            }
        )
    brief = packet["brief"]
    view = {
        "kind": "Stage2ContentView",
        "schema_version": "1.0.0",
        **_bindings_v3(packet, subject_id, input_sha256, config_sha256, rubric_path),
        "scientific_content": {
            "brief": {
                "original_description": brief["original_description"],
                "needs": [
                    {"need_id": row["need_id"], "question": row["question"]}
                    for row in brief["needs"]
                ],
            },
            "confirmed_scope": validate_brief(packet["brief"], require_confirmed=True)[
                "scope"
            ],
            "resources": packet["resources"],
            "comparison": packet["comparison"],
            "unresolved": deepcopy(packet["unresolved"]),
            "sources": [
                {
                    key: row[key]
                    for key in (
                        "source_id",
                        "work_id",
                        "version_id",
                        "sha256",
                        "evidence_level",
                    )
                }
                for row in packet["sources"]
            ],
            "evidence": deepcopy(packet["evidence"]),
            "candidates": candidates,
        },
    }
    if packet.get("schema_version") == "2.2.0":
        tables = packet.get("research_tables")
        if tables is not None:
            from stage2_ideation.topic_tables import validate_research_tables

            tables = validate_research_tables(tables, packet)
        content = view["scientific_content"]
        content["literature"] = deepcopy(packet["literature"])
        content["topic_comparison"] = (
            {
                "dimensions": [
                    {k: deepcopy(v) for k, v in row.items() if k != "spans"}
                    for row in tables["dimensions"]
                ],
                "work_refs": deepcopy(tables["work_refs"]),
                "cells": [
                    {k: deepcopy(v) for k, v in row.items() if k != "spans"}
                    for row in tables["cells"]
                ],
            }
            if tables is not None
            else None
        )
        current = {(row["candidate_id"], row["version"]) for row in candidates}
        content["direction_resources"] = (
            [
                {k: deepcopy(v) for k, v in row.items() if k != "spans"}
                for row in tables["direction_resources"]
                if (row["candidate_id"], row["candidate_version"]) in current
            ]
            if tables is not None
            else None
        )
    return view


def _validate_content_assessment_v3(assessment, view, packet):
    expected_view = prepare_content_view_v3(
        packet,
        view.get("subject_id"),
        view.get("input_sha256"),
        view.get("config_sha256"),
    )
    _require(
        view == expected_view,
        "content assessment view is not the version-locked v3 allowlist view",
    )
    _require(
        assessment.get("kind") == "Stage2ContentAssessment",
        "wrong content assessment kind",
    )
    _require(
        assessment.get("schema_version") == "1.0.0",
        "wrong content assessment version",
    )
    _require(
        view.get("packet_sha256") == canonical_hash(packet),
        "content view packet_sha256 no longer matches packet content",
    )
    for field in HASH_FIELDS_V3[:-1]:
        expected = (
            canonical_hash(view) if field == "content_view_sha256" else view[field]
        )
        _require(
            assessment.get(field) == expected,
            f"content assessment {field} mismatch",
        )
    _require(
        assessment.get("evaluator_status") == "complete",
        "content assessment is not complete",
    )
    findings = assessment.get("findings")
    _require(
        isinstance(findings, list) and findings, "content assessment has no findings"
    )
    finding_ids = []
    for finding in findings:
        _require(isinstance(finding, dict), "invalid content finding")
        v2._text(finding.get("finding_id"), "content finding ID")
        v2._text(finding.get("statement"), "content finding statement")
        refs = finding.get("evidence_ids")
        _require(
            isinstance(refs, list) and refs, "content finding lacks source evidence"
        )
        validate_evidence_refs(refs, packet)
        finding_ids.append(finding["finding_id"])
    _require(len(finding_ids) == len(set(finding_ids)), "duplicate content finding ID")


def prepare_action_view_v3(packet, content_view, content_assessment, action_record):
    """Expose actions only after a valid independent v3 content assessment."""

    _validate_content_assessment_v3(content_assessment, content_view, packet)
    v2.validate_action_record(action_record, packet)
    bindings = {field: content_view[field] for field in HASH_FIELDS_V3[:-2]}
    return {
        "kind": "Stage2ActionView",
        "schema_version": "1.0.0",
        **bindings,
        "content_view_sha256": canonical_hash(content_view),
        "content_assessment_sha256": canonical_hash(content_assessment),
        "content_assessment": deepcopy(content_assessment),
        "action_record_sha256": canonical_hash(action_record),
        "action_record": deepcopy(action_record),
        "candidate_revision_history": sorted(
            deepcopy(packet["candidates"]),
            key=lambda row: (row["candidate_id"], row["version"]),
        ),
    }


def validate_judge_output_v3(
    result, content_view, action_view, packet, *, rubric_path=None
):
    """Validate one source-bound R1, R2, or ADJ output for all nine criteria."""

    rubric, rubric_sha256 = _load_rubric_v3(rubric_path)
    expected_content = prepare_content_view_v3(
        packet,
        content_view.get("subject_id"),
        content_view.get("input_sha256"),
        content_view.get("config_sha256"),
        rubric_path=rubric_path,
    )
    _require(
        content_view == expected_content,
        "content view is not the version-locked v3 allowlist view",
    )
    embedded_assessment = action_view.get("content_assessment")
    _require(
        isinstance(embedded_assessment, dict), "action view lacks content assessment"
    )
    embedded_action_record = action_view.get("action_record")
    _require(
        isinstance(embedded_action_record, dict), "action view lacks action record"
    )
    expected_action = prepare_action_view_v3(
        packet, content_view, embedded_assessment, embedded_action_record
    )
    _require(
        action_view == expected_action,
        "action view is not the version-locked v3 admitted view",
    )
    _require(
        content_view.get("packet_sha256") == canonical_hash(packet),
        "judge packet_sha256 no longer matches packet content",
    )
    _require(result.get("kind") == "Stage2JudgeAssessment", "wrong judge output kind")
    _require(result.get("schema_version") == "1.0.0", "wrong judge output version")
    _require(result.get("role") in {"R1", "R2", "ADJ"}, "invalid judge role")
    expected_bindings = {
        **{field: content_view[field] for field in HASH_FIELDS_V3[:-2]},
        "rubric_id": rubric["rubric_id"],
        "rubric_sha256": rubric_sha256,
        "content_view_sha256": canonical_hash(content_view),
        "action_view_sha256": canonical_hash(action_view),
    }
    for field, expected in expected_bindings.items():
        _require(result.get(field) == expected, f"judge {field} mismatch")
    _require(
        result.get("candidate_coverage") == v2._coverage(packet),
        "judge candidate coverage is stale or incomplete",
    )
    rows = result.get("criteria")
    _require(isinstance(rows, list), "judge criteria missing")
    _require(
        [row.get("criterion_id") for row in rows] == list(CRITERIA_V3),
        "judge needs all nine v3 criteria exactly once",
    )
    evaluator_status = result.get("evaluator_status")
    _require(
        evaluator_status in {"complete", "technical-failure"},
        "invalid evaluator status",
    )
    for row in rows:
        _require(
            row.get("status") in {"assessed", "unknown"}, "invalid criterion status"
        )
        v2._text(row.get("rationale"), "criterion rationale")
        refs = row.get("evidence_ids")
        _require(isinstance(refs, list), "criterion evidence_ids must be a list")
        validate_evidence_refs(refs, packet)
        if row["status"] == "assessed":
            _require(
                type(row.get("score")) is int and row["score"] in {0, 1, 2},
                "assessed criterion needs integer 0-2",
            )
            _require(refs, "assessed criterion needs source evidence")
            _require(
                row.get("unknown_reason") is None,
                "assessed criterion cannot have unknown_reason",
            )
        else:
            _require(row.get("score") is None, "unknown criterion needs null score")
            _require(
                row.get("unknown_reason")
                in {
                    "source-lookup-failure",
                    "evidence-unavailable",
                    "evaluator-failure",
                },
                "unknown criterion needs a distinct failure reason",
            )
    major = result.get("major_error_ids")
    _require(
        isinstance(major, list)
        and all(isinstance(row, str) and row.strip() for row in major),
        "invalid major_error_ids",
    )
    _require(len(major) == len(set(major)), "duplicate major error ID")
    _require(set(major).issubset(rubric["major_error_ids"]), "unknown major error ID")
    _require(
        type(result.get("audit_required")) is bool, "audit_required must be boolean"
    )
    reasons = result.get("audit_reasons")
    _require(
        isinstance(reasons, list)
        and all(isinstance(row, str) and row.strip() for row in reasons),
        "invalid audit reasons",
    )
    _require(
        result["audit_required"] == bool(reasons), "audit trigger and reasons disagree"
    )
    expected_audit_status = "required" if result["audit_required"] else "not-required"
    _require(
        result.get("audit_status") == expected_audit_status,
        "judge audit status is invalid or self-certified",
    )
    _require(
        result.get("confidence") in {"high", "medium", "low"},
        "invalid judge confidence",
    )
    _require(
        type(result.get("central_evidence_inaccessible")) is bool,
        "central_evidence_inaccessible must be boolean",
    )
    if evaluator_status == "technical-failure":
        v2._text(result.get("failure_reason"), "technical failure reason")
        _require(
            all(row["status"] == "unknown" for row in rows),
            "technical failure cannot score the subject",
        )
        _require(
            all(row["unknown_reason"] == "evaluator-failure" for row in rows),
            "technical failure must remain evaluator-failure, not subject deficiency",
        )
        _require(not major, "technical failure cannot create subject major errors")
    else:
        _require(
            result.get("failure_reason") is None,
            "complete evaluator cannot report technical failure",
        )


def _signature_v3(result):
    return (
        tuple(
            (row["criterion_id"], row["status"], row["score"])
            for row in result["criteria"]
        ),
        tuple(sorted(result["major_error_ids"])),
    )


def _criterion_projection(row, confidence):
    return {
        "status": row["status"],
        "score": row["score"],
        "rationale": row["rationale"],
        "evidence_ids": deepcopy(row["evidence_ids"]),
        "unknown_reason": row.get("unknown_reason"),
        "confidence": confidence,
    }


def _merged_criteria(selected, r1, r2, adj):
    rows_by_role = {
        "R1": {row["criterion_id"]: row for row in r1["criteria"]},
        "R2": {row["criterion_id"]: row for row in r2["criteria"]},
        "ADJ": (
            {row["criterion_id"]: row for row in adj["criteria"]}
            if adj is not None
            else None
        ),
    }
    selected_role = selected["role"]
    merged = []
    for selected_row in selected["criteria"]:
        criterion_id = selected_row["criterion_id"]
        merged.append(
            {
                "criterion_id": criterion_id,
                **_criterion_projection(selected_row, selected["confidence"]),
                "selected_role": selected_role,
                "judgments": {
                    role: (
                        _criterion_projection(rows[criterion_id], result["confidence"])
                        if rows is not None
                        else None
                    )
                    for role, rows, result in (
                        ("R1", rows_by_role["R1"], r1),
                        ("R2", rows_by_role["R2"], r2),
                        ("ADJ", rows_by_role["ADJ"], adj),
                    )
                },
            }
        )
    return merged


def merge_judgments_v3(
    r1,
    r2,
    content_view,
    action_view,
    packet,
    *,
    action_view_r2=None,
    adj=None,
    action_view_adj=None,
    audit=None,
    rubric_path=None,
):
    """Merge v3 judges, preserving comments and requiring ADJ on any disagreement."""

    action_view_r2 = action_view if action_view_r2 is None else action_view_r2
    validate_judge_output_v3(
        r1, content_view, action_view, packet, rubric_path=rubric_path
    )
    validate_judge_output_v3(
        r2, content_view, action_view_r2, packet, rubric_path=rubric_path
    )
    _require(r1["role"] == "R1" and r2["role"] == "R2", "merge requires R1 and R2")
    for field in HASH_FIELDS_V3[:-1]:
        _require(r1[field] == r2[field], f"judge bundle {field} mismatch")
    _require(
        action_view["content_view_sha256"] == action_view_r2["content_view_sha256"]
        and action_view["action_record_sha256"]
        == action_view_r2["action_record_sha256"],
        "independent action views must share content and action-record bindings",
    )
    technical = (
        r1["evaluator_status"] == "technical-failure"
        or r2["evaluator_status"] == "technical-failure"
    )
    disagreed = _signature_v3(r1) != _signature_v3(r2)
    if technical:
        _require(
            adj is None,
            "technical evaluator failure cannot be adjudicated into a score",
        )
        _require(
            action_view_adj is None,
            "technical evaluator failure cannot admit an ADJ action view",
        )
        selected = None
    elif disagreed:
        _require(adj is not None, "judge disagreement requires ADJ")
        selected_action_view = (
            action_view if action_view_adj is None else action_view_adj
        )
        validate_judge_output_v3(
            adj, content_view, selected_action_view, packet, rubric_path=rubric_path
        )
        _require(adj["role"] == "ADJ", "disagreement requires ADJ role")
        for field in HASH_FIELDS_V3[:-1]:
            _require(adj[field] == r1[field], f"ADJ {field} mismatch")
        _require(
            selected_action_view["content_view_sha256"]
            == action_view["content_view_sha256"]
            and selected_action_view["action_record_sha256"]
            == action_view["action_record_sha256"],
            "ADJ action view must share content and action-record bindings",
        )
        _require(
            adj["evaluator_status"] == "complete",
            "failed ADJ cannot resolve disagreement",
        )
        selected = adj
    else:
        _require(adj is None, "ADJ is not allowed without disagreement")
        _require(
            action_view_adj is None,
            "ADJ action view is not allowed without disagreement",
        )
        selected = r1
    judged_rows = (r1, r2) + ((adj,) if adj is not None else ())
    audit_required = (
        disagreed
        or any(row["audit_required"] for row in judged_rows)
        or any(row["major_error_ids"] for row in judged_rows)
        or any(row["confidence"] == "low" for row in judged_rows)
        or any(row["central_evidence_inaccessible"] for row in judged_rows)
    )
    if audit_required and selected is not None:
        v2._validate_audit(audit, selected)
    elif not audit_required:
        _require(audit is None, "unexpected audit")
    return {
        "kind": "Stage2JudgeBundle",
        "schema_version": "1.0.0",
        **{field: r1[field] for field in HASH_FIELDS_V3[:-1]},
        "action_view_sha256": (
            selected["action_view_sha256"]
            if selected is not None
            else r1["action_view_sha256"]
        ),
        "action_view_sha256s": {
            "R1": r1["action_view_sha256"],
            "R2": r2["action_view_sha256"],
            "ADJ": adj["action_view_sha256"] if adj is not None else None,
        },
        "evaluator_status": "technical-failure" if technical else "complete",
        "usable": not technical,
        "adjudicated": disagreed and not technical,
        "audit_required": audit_required,
        "audit_accepted": audit_required and selected is not None,
        "audit_status": (
            "accepted"
            if audit_required and selected is not None
            else "blocked-technical-failure"
            if audit_required
            else "not-required"
        ),
        "criteria": (
            _merged_criteria(selected, r1, r2, adj) if selected is not None else []
        ),
        "major_error_ids": deepcopy(selected["major_error_ids"]) if selected else [],
        "diagnostic_only": True,
        "external_claim_ready": False,
        "raw": {
            "packet": deepcopy(packet),
            "content_view": deepcopy(content_view),
            "action_view_r1": deepcopy(action_view),
            "action_view_r2": deepcopy(action_view_r2),
            "action_view_adj": deepcopy(action_view_adj),
            "r1": deepcopy(r1),
            "r2": deepcopy(r2),
            "adj": deepcopy(adj),
            "audit": deepcopy(audit),
        },
    }


def dimension_scores_v3(bundle):
    """Return transparent P4-P6 scores with fixed three-item, six-point maxima."""

    if not bundle.get("usable"):
        return None
    rows = {row["criterion_id"]: row for row in bundle["criteria"]}
    scores = {}
    for dimension, keys in DIMENSIONS_V3.items():
        assessed = sum(rows[key]["status"] == "assessed" for key in keys)
        complete = assessed == len(keys)
        raw_sum = sum(rows[key]["score"] for key in keys) if complete else None
        scores[dimension] = {
            "score": round(100 * raw_sum / 6, 6) if raw_sum is not None else None,
            "sum": raw_sum,
            "max": 6,
            "assessed": assessed,
            "required": 3,
        }
    return scores


def validate_bundle_v3(bundle):
    """Replay a v3 bundle and reject altered summaries, views, or raw judgments."""

    _require(bundle.get("kind") == "Stage2JudgeBundle", "pair needs judge bundles")
    _require(bundle.get("schema_version") == "1.0.0", "wrong judge bundle version")
    for field in (
        "packet_sha256",
        "input_sha256",
        "config_sha256",
        "rubric_sha256",
        "content_view_sha256",
        "action_view_sha256",
    ):
        v2._hash(bundle.get(field), field)
    v2._text(bundle.get("subject_id"), "bundle subject ID")
    _require(bundle.get("rubric_id") == "stage2-general-v3", "wrong bundle rubric")
    _require(
        bundle.get("diagnostic_only") is True
        and bundle.get("external_claim_ready") is False,
        "bundle cannot support a formal claim",
    )
    _require(type(bundle.get("usable")) is bool, "bundle usability missing")
    rows = bundle.get("criteria")
    _require(isinstance(rows, list), "bundle criteria missing")
    if bundle["usable"]:
        _require(
            [row.get("criterion_id") for row in rows] == list(CRITERIA_V3),
            "usable bundle needs nine v3 criteria",
        )
        for row in rows:
            _require(
                row.get("status") in {"assessed", "unknown"},
                "invalid bundled criterion status",
            )
            _require(
                row.get("confidence") in {"high", "medium", "low"},
                "invalid bundled confidence",
            )
            _require(
                row.get("selected_role") in {"R1", "ADJ"}, "invalid selected judge role"
            )
            judgments = row.get("judgments")
            _require(
                isinstance(judgments, dict) and set(judgments) == {"R1", "R2", "ADJ"},
                "bundled criterion judgments are incomplete",
            )
            if row["status"] == "assessed":
                _require(
                    type(row.get("score")) is int and row["score"] in {0, 1, 2},
                    "invalid bundled score",
                )
            else:
                _require(row.get("score") is None, "unknown bundled score must be null")
    else:
        _require(
            not rows and bundle.get("evaluator_status") == "technical-failure",
            "unusable bundle must be a technical failure",
        )
    major = bundle.get("major_error_ids")
    _require(
        isinstance(major, list) and len(major) == len(set(major)),
        "invalid bundled major errors",
    )
    raw = bundle.get("raw")
    _require(isinstance(raw, dict), "bundle lacks replay inputs")
    _require(
        all(
            isinstance(raw.get(key), dict)
            for key in (
                "packet",
                "content_view",
                "action_view_r1",
                "action_view_r2",
                "r1",
                "r2",
            )
        ),
        "bundle raw replay inputs are incomplete",
    )
    rebuilt = merge_judgments_v3(
        raw.get("r1"),
        raw.get("r2"),
        raw.get("content_view"),
        raw.get("action_view_r1"),
        raw.get("packet"),
        action_view_r2=raw.get("action_view_r2"),
        adj=raw.get("adj"),
        action_view_adj=raw.get("action_view_adj"),
        audit=raw.get("audit"),
    )
    _require(bundle == rebuilt, "bundle summary differs from replayed raw judgments")


def compare_pairs_v3(pairs):
    """Apply the v3 AB/BA/AB diagnostic rule without candidate-count score caps."""

    _require(
        isinstance(pairs, list) and len(pairs) == 3,
        "comparison requires exactly three pairs",
    )
    _require(
        [row.get("order") for row in pairs] == ["AB", "BA", "AB"],
        "pair order must be AB, BA, AB",
    )
    pair_ids = [row.get("pair_id") for row in pairs]
    _require(
        all(isinstance(row, str) and row.strip() for row in pair_ids)
        and len(set(pair_ids)) == 3,
        "pair IDs must be unique",
    )
    diagnostics = []
    inconclusive = False
    seen_subjects = set()
    common_settings = None
    for pair in pairs:
        baseline, treatment = pair.get("A"), pair.get("B")
        _require(
            isinstance(baseline, dict) and isinstance(treatment, dict),
            "pair needs A and B bundles",
        )
        validate_bundle_v3(baseline)
        validate_bundle_v3(treatment)
        _require(
            pair.get("A_content_view_sha256") == baseline["content_view_sha256"]
            and pair.get("B_content_view_sha256") == treatment["content_view_sha256"],
            "pair external content-view binding mismatch",
        )
        _require(
            baseline["subject_id"] != treatment["subject_id"],
            "paired subjects must be distinct",
        )
        for field in ("input_sha256", "config_sha256", "rubric_id", "rubric_sha256"):
            _require(baseline[field] == treatment[field], f"pair {field} mismatch")
        subjects = {baseline["subject_id"], treatment["subject_id"]}
        _require(
            not seen_subjects.intersection(subjects), "subject reused across pairs"
        )
        seen_subjects.update(subjects)
        settings = tuple(
            baseline[field]
            for field in ("input_sha256", "config_sha256", "rubric_id", "rubric_sha256")
        )
        if common_settings is None:
            common_settings = settings
        _require(settings == common_settings, "starting settings changed across pairs")
        a_scores = dimension_scores_v3(baseline)
        b_scores = dimension_scores_v3(treatment)
        if a_scores is None or b_scores is None:
            inconclusive = True
            diagnostics.append(
                {
                    "pair_id": pair["pair_id"],
                    "order": pair["order"],
                    "status": "inconclusive",
                    "reason": "evaluator failure",
                }
            )
            continue
        deltas = {
            key: (
                None
                if a_scores[key]["score"] is None or b_scores[key]["score"] is None
                else round(b_scores[key]["score"] - a_scores[key]["score"], 6)
            )
            for key in DIMENSIONS_V3
        }
        added_errors = sorted(
            set(treatment["major_error_ids"]) - set(baseline["major_error_ids"])
        )
        shared_error_categories = sorted(
            set(treatment["major_error_ids"]) & set(baseline["major_error_ids"])
        )
        inconclusive = inconclusive or bool(shared_error_categories)
        status = (
            "partial" if any(value is None for value in deltas.values()) else "assessed"
        )
        inconclusive = inconclusive or status == "partial"
        diagnostics.append(
            {
                "pair_id": pair["pair_id"],
                "order": pair["order"],
                "status": status,
                "A": a_scores,
                "B": b_scores,
                "delta": deltas,
                "added_major_error_ids": added_errors,
                "unmatched_shared_major_error_categories": shared_error_categories,
            }
        )
    assessed = [row for row in diagnostics if row["status"] == "assessed"]
    if inconclusive:
        decision = "inconclusive"
    else:
        target_ok = all(
            sum(row["delta"][dimension] > 0 for row in assessed) >= 2
            and all(row["delta"][dimension] >= 0 for row in assessed)
            for dimension in ("P5", "P6")
        )
        guardrails = all(
            row["delta"]["P4"] >= 0 and not row["added_major_error_ids"]
            for row in assessed
        )
        decision = (
            "diagnostic-improvement" if target_ok and guardrails else "not-improved"
        )
    return {
        "kind": "Stage2PairedDiagnostic",
        "schema_version": "1.0.0",
        "decision": decision,
        "pairs": diagnostics,
        "diagnostic_only": True,
        "external_claim_ready": False,
        "formal_claim_status": "rejected",
        "formal_claim_reason": "This slice has no native capture, runtime attestation, or judge-call attestation.",
        "presentation_invariance_tested": False,
    }
