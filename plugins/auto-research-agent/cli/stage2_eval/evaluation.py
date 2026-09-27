"""Pure validation and comparison mechanics; this module never calls a model."""

import json
from copy import deepcopy
from pathlib import Path

from stage1_brief.brief import validate_brief
from stage2_common import Stage2Error, canonical_hash, validate_evidence_refs

RUBRIC_PATH = (
    Path(__file__).resolve().parents[2] / "evals/rubrics/stage2-general.v2.json"
)
CRITERIA = (
    "P4V2.COMPARISON",
    "P5V2.OPPORTUNITY",
    "P5V2.REVISION",
    "P6V2.VALUE",
    "P6V2.FEASIBILITY",
    "P6V2.DISPOSITION",
    "P6V2.PORTFOLIO",
)
DIMENSIONS = {"P4": CRITERIA[:1], "P5": CRITERIA[1:3], "P6": CRITERIA[3:]}
HASH_FIELDS = (
    "subject_id",
    "packet_sha256",
    "input_sha256",
    "config_sha256",
    "rubric_id",
    "rubric_sha256",
    "content_view_sha256",
    "action_view_sha256",
)


def _require(condition, message):
    if not condition:
        raise Stage2Error(message)


def _hash(value, label):
    _require(
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value),
        f"invalid {label}",
    )


def _text(value, label):
    _require(isinstance(value, str) and value.strip(), f"missing {label}")


def _load_rubric(path=None):
    if path is not None:
        supplied = Path(path).resolve()
        _require(
            supplied == RUBRIC_PATH.resolve(),
            "custom Stage 2 rubrics are unsupported by the fixed offline v2 contract",
        )
    path = RUBRIC_PATH
    try:
        raw = path.read_bytes()
        rubric = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise Stage2Error(f"cannot load Stage 2 rubric: {error}") from error
    _require(rubric.get("rubric_id") == "stage2-general-v2", "wrong Stage 2 rubric")
    _require(rubric.get("status") == "experimental", "rubric must remain experimental")
    rows = rubric.get("criteria")
    _require(isinstance(rows, list), "rubric criteria missing")
    _require(
        tuple(row.get("id") for row in rows) == CRITERIA, "rubric criteria changed"
    )
    for row in rows:
        _require(row.get("dimension") == row["id"][:2], "rubric dimension mismatch")
        _text(row.get("question"), "rubric question")
        anchors = row.get("anchors")
        _require(
            isinstance(anchors, dict) and set(anchors) == {"0", "1", "2"},
            "rubric anchors changed",
        )
        for value in anchors.values():
            _text(value, "rubric anchor")
    return rubric, canonical_hash(rubric)


def _latest(packet):
    latest = {}
    for row in packet["candidates"]:
        current = latest.get(row["candidate_id"])
        if current is None or row["version"] > current["version"]:
            latest[row["candidate_id"]] = row
    return [deepcopy(latest[key]) for key in sorted(latest)]


def _bindings(packet, subject_id, input_sha256, config_sha256, rubric_path):
    _text(subject_id, "opaque subject ID")
    _hash(input_sha256, "input_sha256")
    _hash(config_sha256, "config_sha256")
    rubric, rubric_sha = _load_rubric(rubric_path)
    return {
        "subject_id": subject_id,
        "packet_sha256": canonical_hash(packet),
        "input_sha256": input_sha256,
        "config_sha256": config_sha256,
        "rubric_id": rubric["rubric_id"],
        "rubric_sha256": rubric_sha,
    }


def prepare_content_view(
    packet, subject_id, input_sha256, config_sha256, *, rubric_path=None
):
    """Create a version-locked scientific-content view with no condition metadata."""

    candidates = []
    for row in _latest(packet):
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
    return {
        "kind": "Stage2ContentView",
        "schema_version": "1.0.0",
        **_bindings(packet, subject_id, input_sha256, config_sha256, rubric_path),
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


def validate_content_assessment(assessment, view, packet):
    """Require a source-bound assessment before decision/action context is exposed."""

    expected_view = prepare_content_view(
        packet,
        view.get("subject_id"),
        view.get("input_sha256"),
        view.get("config_sha256"),
    )
    _require(
        view == expected_view,
        "content assessment view is not the version-locked allowlist view",
    )
    _require(
        assessment.get("kind") == "Stage2ContentAssessment",
        "wrong content assessment kind",
    )
    _require(
        assessment.get("schema_version") == "1.0.0", "wrong content assessment version"
    )
    _require(
        view.get("packet_sha256") == canonical_hash(packet),
        "content view packet_sha256 no longer matches packet content",
    )
    for field in HASH_FIELDS[:-1]:
        expected = (
            canonical_hash(view) if field == "content_view_sha256" else view[field]
        )
        _require(
            assessment.get(field) == expected, f"content assessment {field} mismatch"
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
        _text(finding.get("finding_id"), "content finding ID")
        _text(finding.get("statement"), "content finding statement")
        refs = finding.get("evidence_ids")
        _require(
            isinstance(refs, list) and refs, "content finding lacks source evidence"
        )
        validate_evidence_refs(refs, packet)
        finding_ids.append(finding["finding_id"])
    _require(len(finding_ids) == len(set(finding_ids)), "duplicate content finding ID")
    return None


def validate_action_record(action_record, packet):
    """Validate format-neutral native/checker actions against retained versions."""

    _require(
        action_record.get("kind") == "Stage2ActionRecord",
        "wrong action record kind",
    )
    _require(
        action_record.get("schema_version") == "1.0.0",
        "wrong action record version",
    )
    _require(
        action_record.get("packet_sha256") == canonical_hash(packet),
        "action record packet_sha256 mismatch",
    )
    candidate_keys = {
        (row["candidate_id"], row["version"]) for row in packet["candidates"]
    }
    latest_keys = {(row["candidate_id"], row["version"]) for row in _latest(packet)}
    dispositions = action_record.get("latest_dispositions")
    _require(isinstance(dispositions, list), "latest dispositions missing")
    disposition_keys = [
        (row.get("candidate_id"), row.get("candidate_version")) for row in dispositions
    ]
    _require(
        len(disposition_keys) == len(set(disposition_keys))
        and set(disposition_keys) == latest_keys,
        "latest dispositions are stale, duplicate, or incomplete",
    )
    history = action_record.get("history")
    _require(isinstance(history, list), "action history missing")
    event_ids = []
    for row in history:
        _text(row.get("event_id"), "action event ID")
        event_ids.append(row["event_id"])
        _validate_action_row(row, candidate_keys, packet)
    _require(len(event_ids) == len(set(event_ids)), "duplicate action event ID")
    for row in dispositions:
        _validate_action_row(row, candidate_keys, packet)
    selected = action_record.get("selected_candidate_ids")
    _require(
        isinstance(selected, list)
        and len(selected) == len(set(selected))
        and set(selected).issubset({row["candidate_id"] for row in _latest(packet)}),
        "selected candidate IDs are invalid",
    )
    _text(action_record.get("choice_rationale"), "choice rationale")
    revisions = action_record.get("revision_history")
    _require(isinstance(revisions, list), "revision history missing")
    expected_revisions = {
        (row["candidate_id"], row["version"] - 1, row["version"])
        for row in packet["candidates"]
        if row["version"] > 1
    }
    actual_revisions = []
    for row in revisions:
        key = (
            row.get("candidate_id"),
            row.get("from_version"),
            row.get("to_version"),
        )
        actual_revisions.append(key)
        _text(row.get("reason"), "revision reason")
        refs = row.get("evidence_ids")
        _require(isinstance(refs, list) and refs, "revision lacks evidence")
        validate_evidence_refs(refs, packet)
    _require(
        len(actual_revisions) == len(set(actual_revisions))
        and set(actual_revisions) == expected_revisions,
        "revision history is stale, duplicate, or incomplete",
    )
    return None


def _validate_action_row(row, candidate_keys, packet):
    _require(
        (row.get("candidate_id"), row.get("candidate_version")) in candidate_keys,
        "action references unknown candidate version",
    )
    _require(
        row.get("disposition") in {"recommend", "revise", "park", "reject"},
        "invalid disposition",
    )
    _text(row.get("reason"), "action reason")
    _text(row.get("next_step"), "action next step")
    refs = row.get("evidence_ids")
    _require(isinstance(refs, list), "action evidence_ids must be a list")
    validate_evidence_refs(refs, packet)
    _require(
        bool(refs) or row["disposition"] in {"park", "revise"},
        "recommend/reject action lacks source evidence",
    )


def prepare_action_view(packet, content_view, content_assessment, action_record):
    """Expose real decisions only after valid source-bound content assessment."""

    validate_content_assessment(content_assessment, content_view, packet)
    validate_action_record(action_record, packet)
    bindings = {field: content_view[field] for field in HASH_FIELDS[:-2]}
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


def _coverage(packet):
    return [
        {"candidate_id": row["candidate_id"], "version": row["version"]}
        for row in _latest(packet)
    ]


def validate_judge_output(
    result, content_view, action_view, packet, *, rubric_path=None
):
    """Validate one independent R1/R2/ADJ output against immutable views."""

    rubric, rubric_sha = _load_rubric(rubric_path)
    expected_content = prepare_content_view(
        packet,
        content_view.get("subject_id"),
        content_view.get("input_sha256"),
        content_view.get("config_sha256"),
        rubric_path=rubric_path,
    )
    _require(
        content_view == expected_content,
        "content view is not the version-locked allowlist view",
    )
    embedded_assessment = action_view.get("content_assessment")
    _require(
        isinstance(embedded_assessment, dict),
        "action view lacks validated content assessment",
    )
    embedded_action_record = action_view.get("action_record")
    _require(
        isinstance(embedded_action_record, dict), "action view lacks action record"
    )
    expected_action = prepare_action_view(
        packet, content_view, embedded_assessment, embedded_action_record
    )
    _require(
        action_view == expected_action,
        "action view is not the version-locked admitted view",
    )
    _require(
        content_view.get("packet_sha256") == canonical_hash(packet),
        "judge packet_sha256 no longer matches packet content",
    )
    _require(result.get("kind") == "Stage2JudgeAssessment", "wrong judge output kind")
    _require(result.get("schema_version") == "1.0.0", "wrong judge output version")
    _require(result.get("role") in {"R1", "R2", "ADJ"}, "invalid judge role")
    expected_bindings = {
        **{field: content_view[field] for field in HASH_FIELDS[:-2]},
        "rubric_id": rubric["rubric_id"],
        "rubric_sha256": rubric_sha,
        "content_view_sha256": canonical_hash(content_view),
        "action_view_sha256": canonical_hash(action_view),
    }
    for field, expected in expected_bindings.items():
        _require(result.get(field) == expected, f"judge {field} mismatch")
    _require(
        result.get("candidate_coverage") == _coverage(packet),
        "judge candidate coverage is stale or incomplete",
    )
    rows = result.get("criteria")
    _require(isinstance(rows, list), "judge criteria missing")
    _require(
        [row.get("criterion_id") for row in rows] == list(CRITERIA),
        "judge needs all seven criteria exactly once",
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
        _text(row.get("rationale"), "criterion rationale")
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
        _text(result.get("failure_reason"), "technical failure reason")
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
    return None


def _signature(result):
    return (
        tuple(
            (row["criterion_id"], row["status"], row["score"])
            for row in result["criteria"]
        ),
        tuple(sorted(result["major_error_ids"])),
    )


def _validate_audit(audit, selected):
    _require(isinstance(audit, dict), "accepted named audit required")
    _require(audit.get("kind") == "Stage2NamedAudit", "wrong audit kind")
    _require(audit.get("schema_version") == "1.0.0", "wrong audit version")
    for field in HASH_FIELDS:
        _require(audit.get(field) == selected[field], f"audit {field} mismatch")
    _require(
        audit.get("assessment_sha256") == canonical_hash(selected),
        "audit assessment binding mismatch",
    )
    _text(audit.get("reviewer"), "named audit reviewer")
    _require(
        audit.get("reviewer_role") == "human", "judge cannot self-certify an audit"
    )
    _require(audit.get("decision") == "accepted", "audit is not accepted")
    _text(audit.get("reason"), "audit reason")


def merge_judgments(
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
    """Merge independent views/outputs, requiring ADJ and audit when triggered."""

    action_view_r2 = action_view if action_view_r2 is None else action_view_r2
    validate_judge_output(
        r1, content_view, action_view, packet, rubric_path=rubric_path
    )
    validate_judge_output(
        r2, content_view, action_view_r2, packet, rubric_path=rubric_path
    )
    _require(r1["role"] == "R1" and r2["role"] == "R2", "merge requires R1 and R2")
    for field in HASH_FIELDS[:-1]:
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
    disagreed = _signature(r1) != _signature(r2)
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
        validate_judge_output(
            adj,
            content_view,
            selected_action_view,
            packet,
            rubric_path=rubric_path,
        )
        _require(adj["role"] == "ADJ", "disagreement requires ADJ role")
        for field in HASH_FIELDS[:-1]:
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
        selected_action_view = action_view
    judged_rows = (r1, r2) + (
        (selected,) if selected and selected not in (r1, r2) else ()
    )
    audit_required = (
        disagreed
        or any(row["audit_required"] for row in judged_rows)
        or any(row["major_error_ids"] for row in judged_rows)
        or any(row["confidence"] == "low" for row in judged_rows)
        or any(row["central_evidence_inaccessible"] for row in judged_rows)
    )
    if audit_required and selected is not None:
        _validate_audit(audit, selected)
    elif not audit_required:
        _require(audit is None, "unexpected audit")
    return {
        "kind": "Stage2JudgeBundle",
        "schema_version": "1.0.0",
        **{field: r1[field] for field in HASH_FIELDS[:-1]},
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
        "criteria": deepcopy(selected["criteria"]) if selected else [],
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


def _dimension_scores(bundle):
    rows = {row["criterion_id"]: row for row in bundle["criteria"]}
    if not bundle["usable"]:
        return None
    scores = {}
    for dimension, keys in DIMENSIONS.items():
        if any(rows[key]["status"] != "assessed" for key in keys):
            scores[dimension] = None
        else:
            scores[dimension] = round(
                100 * sum(rows[key]["score"] for key in keys) / (2 * len(keys)), 6
            )
    return scores


def _validate_bundle(bundle):
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
        _hash(bundle.get(field), field)
    _text(bundle.get("subject_id"), "bundle subject ID")
    _require(bundle.get("rubric_id") == "stage2-general-v2", "wrong bundle rubric")
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
            [row.get("criterion_id") for row in rows] == list(CRITERIA),
            "usable bundle needs seven criteria",
        )
        for row in rows:
            _require(
                row.get("status") in {"assessed", "unknown"},
                "invalid bundled criterion status",
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
    rebuilt = merge_judgments(
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


def compare_pairs(pairs):
    """Apply the fixed AB/BA/AB three-pair diagnostic rule."""

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
        _validate_bundle(baseline)
        _validate_bundle(treatment)
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
        a_scores, b_scores = _dimension_scores(baseline), _dimension_scores(treatment)
        if a_scores is None or b_scores is None:
            inconclusive = True
            diagnostics.append(
                {
                    "pair_id": pair["pair_id"],
                    "order": pair["order"],
                    "status": "inconclusive",
                    "reason": "unknown criterion or evaluator failure",
                }
            )
            continue
        deltas = {
            key: (
                None
                if a_scores[key] is None or b_scores[key] is None
                else round(b_scores[key] - a_scores[key], 6)
            )
            for key in DIMENSIONS
        }
        added_errors = sorted(
            set(treatment["major_error_ids"]) - set(baseline["major_error_ids"])
        )
        shared_error_categories = sorted(
            set(treatment["major_error_ids"]) & set(baseline["major_error_ids"])
        )
        # A shared category does not prove these are the same error instances.
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
