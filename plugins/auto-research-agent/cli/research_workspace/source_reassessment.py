"""Bind newly authored source reviews without rewriting historical decisions."""

from copy import deepcopy
from datetime import datetime
import re

from stage1_deliverable.common import DeliverableError, canonical, sha

CONTRACT = "S1-SAVED-SOURCE-REASSESSMENT-1.0.0"
RELATIONS = {"supports", "partial", "contradicts", "context", "unverifiable"}


def _require(value, message):
    if not value:
        raise DeliverableError("source-reassessment: " + message)


def validate_review(reference, original, source, text, input_sha256, *, claim):
    """Validate declared review provenance and exact evidence, not its reasoning."""
    value = reference["value"]
    required = {
        "work_id",
        "version_id",
        "source_id",
        "source_sha256",
        "raw_source_sha256",
        "reviewer",
        "reviewed_at",
        "not_historical",
        "input_canonical_sha256",
        "reason_code",
        "rationale",
        "evidence",
        "record_kind",
    }
    _require(type(value) is dict and required <= value.keys(), "review fields missing")
    _require(
        value["record_kind"]
        == ("claim-support-review" if claim else "work-screening-review")
        and value["not_historical"] is True
        and value["input_canonical_sha256"] == input_sha256,
        "review scope differs",
    )
    for key in ("work_id", "version_id", "source_id"):
        _require(value[key] == source[key], "source identity differs")
    for key in ("work_id", "version_id"):
        _require(value[key] == original[key], "original identity differs")
    _require(
        value["source_sha256"]
        == sha(text.encode("utf-8"))
        == source["receipt"]["extracted_text_sha256"]
        and value["raw_source_sha256"] == source["receipt"].get("raw_sha256")
        and value["raw_source_sha256"] is not None,
        "source bytes differ",
    )
    reviewer = value["reviewer"]
    _require(
        type(reviewer) is dict
        and reviewer.get("type") in {"ai", "human"}
        and isinstance(reviewer.get("identity"), str)
        and reviewer["identity"].strip()
        and reviewer.get("authenticated") is False,
        "declared reviewer required; no invented authentication",
    )
    try:
        moment = datetime.fromisoformat(value["reviewed_at"].replace("Z", "+00:00"))
        _require(moment.tzinfo is not None, "review time needs timezone")
    except (ValueError, TypeError, AttributeError) as error:
        raise DeliverableError("source-reassessment: invalid review time") from error
    _require(
        isinstance(value["reason_code"], str)
        and re.fullmatch(r"[a-z][a-z0-9-]{2,95}", value["reason_code"])
        and isinstance(value["rationale"], str)
        and 24 <= len(value["rationale"].strip().encode("utf-8")) <= 8192,
        "specific reason required",
    )
    evidence = value["evidence"]
    for visual in value.get("visual_evidence", []):
        _require(
            visual.get("raw_pdf_sha256") == value["raw_source_sha256"]
            and type(visual.get("pdf_pages")) is list
            and all(type(p) is int and p > 0 for p in visual["pdf_pages"]),
            "visual source identity differs",
        )
    _require(
        type(evidence) is list and 0 < len(evidence) <= 64, "bounded evidence required"
    )
    for span in evidence:
        start, end, quote = (span.get(k) for k in ("start", "end", "quote"))
        _require(
            type(start) is int
            and type(end) is int
            and isinstance(quote, str)
            and 0 <= start < end <= len(text)
            and text[start:end] == quote
            and isinstance(span.get("locator"), str)
            and span["locator"].strip()
            and span.get("stance") in {"support", "limit", "contradict"},
            "review evidence span differs",
        )
    if claim:
        _require(
            value.get("claim_id") == original["claim_id"]
            and value.get("original_claim_sha256") == sha(canonical(original))
            and value.get("source_id") == original["source_id"],
            "original claim differs",
        )
        _require(value.get("relation") in RELATIONS, "unknown support relation")
        _require(
            value.get("claim_type")
            in {
                "paper-claim",
                "extraction-observation",
                "methodological-inference",
                "bibliographic",
                "study-boundary",
            }
            and isinstance(value.get("scope_limit"), str)
            and value["scope_limit"].strip(),
            "claim type and support scope required",
        )
        for key in ("supporting_subclaims", "unsupported_subclaims"):
            _require(
                type(value.get(key)) is list
                and len(value[key]) <= 256
                and all(isinstance(s, str) and s.strip() for s in value[key]),
                "subclaim explanation required",
            )
        _require(
            value["relation"] != "supports" or not value["unsupported_subclaims"],
            "partial assertion cannot be full support",
        )
        if value["relation"] in {"partial", "contradicts"}:
            _require(
                isinstance(value.get("revised_claim"), str)
                and value["revised_claim"].strip(),
                "narrowed assertion required",
            )
    else:
        _require(
            value.get("decision") in {"include", "exclude", "pending"}
            and isinstance(value.get("limitations"), str)
            and value["limitations"].strip()
            and type(value.get("need_ids")) is list
            and all(isinstance(n, str) and n.strip() for n in value["need_ids"])
            and (value["decision"] != "include" or value["need_ids"]),
            "work decision and needs required",
        )
    return deepcopy(reference)


def apply_screening_reviews(index, rows, events):
    """Expose new decisions and retain the earlier decisions as history."""
    recovered = index.get("original_record_recovery", {}).get("payload", {})
    works = {(w["work_id"], w["version_id"]): w for w in recovered.get("works", [])}
    for row in rows:
        source = works.get((row["work_id"], row["current_display_version_id"]), {})
        review = source.get("new_screening_review")
        if not review:
            continue
        value = review["value"]
        row["historical_current_decision"] = deepcopy(row["current_decision"])
        row["new_screening_review"] = deepcopy(review)
        event = dict(
            work_id=value["work_id"],
            current_display_version_id=value["version_id"],
            decision_version_id=value["version_id"],
            decision_scope="new-saved-source-review",
            decision_id="new-" + sha(canonical(value))[:24],
            academic_status=value["decision"],
            reason_code=value["reason_code"],
            reason=value["rationale"],
            observed_at=value["reviewed_at"],
            original_event=deepcopy(value),
            pointer=review["pointer"],
            source_path=review["path"],
            scientific_assessment=False,
        )
        events.append(event)
        row.update(
            academic_status=value["decision"],
            current_decision=deepcopy(event),
            reason=value["rationale"],
            reason_recorded=True,
            reason_nonempty=True,
            decision_scope="new-saved-source-review",
            recorded_vs_missing="new-review",
            decision_event_count=(
                row["decision_event_count"]
                if type(row["decision_event_count"]) is int
                else 0
            )
            + 1,
        )
