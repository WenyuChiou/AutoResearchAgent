"""Pure saved-reading record preparation from validated agent event plans."""

from copy import deepcopy
import re

from .project_analysis_events import _core_ref, _hash, _text
from .session_api import _check


_EVENT_ID = re.compile(r"e[0-9]{6,}")
_PLAN_FIELDS_V1 = {
    "kind",
    "schema_version",
    "proposal_ref",
    "actor",
    "method",
    "proposal",
    "decision_arguments",
    "claims",
    "source_receipt_hashes",
    "source_ids",
    "core_events_created",
    "human_authorization",
    "researcher_acceptance",
    "scientific_acceptance",
}
_PLAN_FIELDS_V1_1 = _PLAN_FIELDS_V1 | {"proposal_sha256", "proposal_storage"}
_SPAN_FIELDS = {"claim_id", "source_id", "text_sha256", "start", "end", "quote"}


def _event_id(value, code):
    _check(type(value) is str and _EVENT_ID.fullmatch(value) is not None, code, 400)


def _reading_span(value, source_ids, code):
    _check(type(value) is dict and set(value) == _SPAN_FIELDS, code, 400)
    _event_id(value["claim_id"], code)
    source_id = value["source_id"]
    _check(
        source_id is None or type(source_id) is str and source_id in source_ids,
        code,
        400,
    )
    _check(_hash(value["text_sha256"]), code, 400)
    locator = (value["start"], value["end"], value["quote"])
    if locator == (None, None, None):
        return deepcopy(value)
    start, end, quote = locator
    _check(
        type(start) is int
        and type(end) is int
        and 0 <= start < end <= 2 * 1024 * 1024
        and type(quote) is str
        and bool(quote)
        and len(quote) == end - start,
        code,
        400,
    )
    return deepcopy(value)


def prepare_reading_record(
    plan,
    saved_metadata,
    *,
    decision_event_id,
    claim_event_ids,
    previous_claim_spans,
    review_event_id,
):
    """Build a saved-reading 1.1 proposal from parent-supplied Core event IDs.

    This validates only mechanical bindings.  The caller must establish that the
    supplied events exist, are current, and were authorized before registration.
    """
    _check(type(plan) is dict, "analysis-reading-plan-invalid", 400)
    version = plan.get("schema_version")
    expected_fields = (
        _PLAN_FIELDS_V1
        if version == "1.0.0"
        else _PLAN_FIELDS_V1_1
        if version == "1.1.0"
        else None
    )
    _check(
        expected_fields is not None and set(plan) == expected_fields,
        "analysis-reading-plan-invalid",
        400,
    )
    _check(
        plan["kind"] == "Stage1AgentAnalysisEventPlan"
        and plan["schema_version"] in {"1.0.0", "1.1.0"}
        and all(
            plan[field] is False
            for field in (
                "core_events_created",
                "human_authorization",
                "researcher_acceptance",
                "scientific_acceptance",
            )
        ),
        "analysis-reading-plan-invalid",
        400,
    )
    if version == "1.0.0":
        _core_ref(plan["proposal_ref"], "analysis-reading-plan-invalid")
    else:
        _check(
            plan["proposal_ref"] is None
            and _hash(plan["proposal_sha256"])
            and plan["proposal_storage"] == "original-model-job",
            "analysis-reading-plan-invalid",
            400,
        )
    _check(type(saved_metadata) is dict, "analysis-reading-metadata-invalid", 400)
    _check(
        saved_metadata.get("kind") == "Stage1SavedTextReadingInput"
        and saved_metadata.get("schema_version") == "1.0.0",
        "analysis-reading-metadata-invalid",
        400,
    )
    proposal = plan["proposal"]
    _check(
        type(proposal) is dict
        and proposal.get("work_id") == saved_metadata.get("work_id")
        and proposal.get("version_id") == saved_metadata.get("version_id"),
        "analysis-reading-version-differs",
        400,
    )
    available = saved_metadata.get("sources")
    failures = saved_metadata.get("source_failures")
    _check(
        type(available) is list and type(failures) is list,
        "analysis-reading-source-set-differs",
        400,
    )
    available_ids = []
    all_ids = []
    for row in available:
        _check(
            type(row) is dict and "source_id" in row,
            "analysis-reading-source-set-differs",
            400,
        )
        _text(row["source_id"], "analysis-reading-source-set-differs")
        _check(
            row["source_id"] not in available_ids,
            "analysis-reading-source-set-differs",
            400,
        )
        available_ids.append(row["source_id"])
        all_ids.append(row["source_id"])
    for row in failures:
        _check(
            type(row) is dict and "source_id" in row,
            "analysis-reading-source-set-differs",
            400,
        )
        _text(row["source_id"], "analysis-reading-source-set-differs")
        if row["source_id"] not in all_ids:
            all_ids.append(row["source_id"])
    _check(plan["source_ids"] == all_ids, "analysis-reading-source-set-differs", 400)

    candidate_event_id = saved_metadata.get("candidate_event_id")
    _event_id(candidate_event_id, "analysis-reading-event-id-invalid")
    _event_id(decision_event_id, "analysis-reading-event-id-invalid")
    _check(
        review_event_id is None or type(review_event_id) is str,
        "analysis-reading-event-id-invalid",
        400,
    )
    if review_event_id is not None:
        _event_id(review_event_id, "analysis-reading-event-id-invalid")

    claims = plan["claims"]
    _check(
        type(claims) is list and type(claim_event_ids) is dict,
        "analysis-reading-claim-map-invalid",
        400,
    )
    _check(
        all(type(row) is dict and type(row.get("claim_key")) is str for row in claims),
        "analysis-reading-claim-map-invalid",
        400,
    )
    keys = [row["claim_key"] for row in claims]
    for key in keys:
        _text(key, "analysis-reading-claim-map-invalid")
    _check(
        len(keys) == len(set(keys)) and set(claim_event_ids) == set(keys),
        "analysis-reading-claim-map-invalid",
        400,
    )
    new_spans = []
    new_ids = set()
    for row in claims:
        claim_id = claim_event_ids[row["claim_key"]]
        _event_id(claim_id, "analysis-reading-event-id-invalid")
        _check(claim_id not in new_ids, "analysis-reading-claim-id-duplicate", 400)
        new_ids.add(claim_id)
        span = row.get("span")
        _check(
            type(span) is dict and set(span) == _SPAN_FIELDS - {"claim_id"},
            "analysis-reading-span-invalid",
            400,
        )
        new_spans.append(
            _reading_span(
                {"claim_id": claim_id, **deepcopy(span)},
                set(available_ids),
                "analysis-reading-span-invalid",
            )
        )

    _check(type(previous_claim_spans) is list, "analysis-reading-span-invalid", 400)
    previous = [
        _reading_span(row, set(all_ids), "analysis-reading-span-invalid")
        for row in previous_claim_spans
    ]
    ids = [row["claim_id"] for row in [*new_spans, *previous]]
    _check(len(ids) == len(set(ids)), "analysis-reading-claim-id-duplicate", 400)
    reading = proposal.get("reading")
    _check(
        type(reading) is dict
        and type(reading.get("classification")) is dict
        and type(reading.get("findings")) is dict,
        "analysis-reading-proposal-invalid",
        400,
    )
    return {
        "schema_version": "1.1.0",
        "work_id": saved_metadata["work_id"],
        "version_id": saved_metadata["version_id"],
        "candidate_event_id": candidate_event_id,
        "decision_event_id": decision_event_id,
        "review_event_id": review_event_id,
        "source_ids": deepcopy(all_ids),
        "classification": deepcopy(reading["classification"]),
        "findings": deepcopy(reading["findings"]),
        "roles": [],
        "claims": [*new_spans, *previous],
    }
