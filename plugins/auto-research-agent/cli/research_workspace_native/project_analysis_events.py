"""Pure event arguments for a validated saved full-source analysis proposal.

Callers must derive ``source_facts`` from current ``source_record`` validation
and a validated SDK receipt.  This module performs no I/O and establishes no
source provenance, execution authority, human judgment, or scientific result.
"""

from copy import deepcopy
import re

from stage1_deliverable.common import sha
from stage1_ledger.contracts import check
from stage1_ledger.semantics import claim_check

from .project_full_analysis import full_analysis_draft
from .session_api import _check


_FACT_FIELDS = {
    "source_id",
    "work_id",
    "version_id",
    "text_ref",
    "evidence_level",
    "receipt_sha256",
}
_HASH = re.compile(r"[0-9a-f]{64}")
_LEVELS = {"metadata", "abstract", "full-text"}


def _hash(value):
    return type(value) is str and _HASH.fullmatch(value) is not None


def _text(value, code):
    _check(type(value) is str and bool(value.strip()), code, 400)
    try:
        size = len(value.encode("utf8", errors="strict"))
    except UnicodeError:
        _check(False, code, 400)
    _check(size <= 256, code, 400)


def _core_ref(value, code):
    _check(type(value) is dict, code, 400)
    # ArtifactRef is a shared definition. Validate it through the existing Core
    # event that owns the reference rather than duplicating the versioned schema.
    check(
        {
            "kind": "ArtifactStored",
            "schema_version": "1.0.0",
            "event_id": "e000000",
            "created_at": value.get("created_at"),
            "ref": value,
            "bytes": 0,
        },
        "ArtifactStored",
    )


def _proposal_ref(value, raw):
    _core_ref(value, "analysis-event-proposal-ref-invalid")
    _check(value["sha256"] == sha(raw), "analysis-event-proposal-ref-invalid", 400)
    return deepcopy(value)


def _source_ids(saved):
    rows = saved.get("sources")
    failures = saved.get("source_failures")
    _check(
        type(rows) is list and type(failures) is list,
        "analysis-event-saved-sources-invalid",
        400,
    )
    result = []
    seen = set()
    for row in [*rows, *failures]:
        _check(
            type(row) is dict and "source_id" in row,
            "analysis-event-saved-source-id-invalid",
            400,
        )
        source_id = row["source_id"]
        _text(source_id, "analysis-event-saved-source-id-invalid")
        if source_id not in seen:
            seen.add(source_id)
            result.append(source_id)
    return result


def _facts(source_facts, full_source):
    _check(type(source_facts) is list, "analysis-event-source-facts-invalid", 400)
    binding = full_source["binding"]
    sources = {source["source_id"]: source for source in full_source["sources"]}
    _check(len(source_facts) == len(sources), "analysis-event-source-set-differs", 400)
    result = {}
    for fact in source_facts:
        _check(
            type(fact) is dict and set(fact) == _FACT_FIELDS,
            "analysis-event-source-fact-fields",
            400,
        )
        source_id = fact["source_id"]
        _check(
            type(source_id) is str and source_id in sources and source_id not in result,
            "analysis-event-source-set-differs",
            400,
        )
        source = sources[source_id]
        _check(
            fact["work_id"] == binding["work_id"]
            and fact["version_id"] == binding["version_id"],
            "analysis-event-source-version-differs",
            400,
        )
        _check(
            type(fact["evidence_level"]) is str and fact["evidence_level"] in _LEVELS,
            "analysis-event-evidence-level-invalid",
            400,
        )
        _check(
            _hash(fact["receipt_sha256"]),
            "analysis-event-source-receipt-invalid",
            400,
        )
        ref = fact["text_ref"]
        _core_ref(ref, "analysis-event-source-ref-invalid")
        _check(
            ref["sha256"] == source["text_sha256"]
            and len(source["text"].encode("utf8", errors="strict"))
            == source["text_bytes"],
            "analysis-event-source-ref-differs",
            400,
        )
        result[source_id] = deepcopy(fact)
    _check(set(result) == set(sources), "analysis-event-source-set-differs", 400)
    return result


def _span(evidence, sources):
    source = sources[evidence["source_id"]]
    raw = source["text"].encode("utf8", errors="strict")
    start_byte, end_byte = evidence["start_byte"], evidence["end_byte"]
    try:
        before = raw[:start_byte].decode("utf8", errors="strict")
        quote = raw[start_byte:end_byte].decode("utf8", errors="strict")
    except UnicodeError:
        _check(False, "analysis-event-span-invalid", 400)
    _check(
        quote == evidence["quote"] and evidence["text_sha256"] == source["text_sha256"],
        "analysis-event-span-differs",
        400,
    )
    start = len(before)
    return {
        "source_id": evidence["source_id"],
        "text_sha256": evidence["text_sha256"],
        "start": start,
        "end": start + len(quote),
        "quote": quote,
    }


def prepare_agent_events(
    raw,
    analysis_snapshot,
    source_facts,
    *,
    proposal_ref=None,
    actor,
    method,
    source_evidence=False,
):
    """Prepare unadopted agent event arguments from revalidated raw output."""
    proposal = full_analysis_draft(raw, analysis_snapshot)
    _check(type(source_evidence) is bool, "analysis-event-evidence-mode-invalid", 400)
    _text(actor, "analysis-event-actor-invalid")
    _text(method, "analysis-event-method-invalid")

    reading = analysis_snapshot["reading_input"]
    full_source = reading["full_source"]
    facts = _facts(source_facts, full_source)
    if source_evidence:
        _check(proposal_ref is None, "analysis-event-evidence-mode-invalid", 400)
        evidence_refs = []
        for source in full_source["sources"]:
            ref = facts[source["source_id"]]["text_ref"]
            if ref not in evidence_refs:
                evidence_refs.append(deepcopy(ref))
    else:
        proposal_ref = _proposal_ref(proposal_ref, raw)
        evidence_refs = [deepcopy(proposal_ref)]
    sources = {source["source_id"]: source for source in full_source["sources"]}
    evidence = proposal["reading"]["evidence"]
    claims = []
    for claim in proposal["claims"]:
        observed = evidence[claim["evidence_index"]]
        span = _span(observed, sources)
        fact = facts[span["source_id"]]
        claims.append(
            {
                "claim_key": claim["claim_key"],
                "arguments": {
                    "work_id": fact["work_id"],
                    "version_id": fact["version_id"],
                    "claim_text": claim["claim_text"],
                    "relation": claim["relation"],
                    "evidence_level": fact["evidence_level"],
                    "locator": {
                        "section": claim["section"],
                        "quote": span["quote"],
                    },
                    "source_ref": deepcopy(fact["text_ref"]),
                    "verifier": {
                        "actor": actor,
                        "actor_type": "agent",
                        "method": method,
                    },
                    "assessment": deepcopy(claim["assessment"]),
                },
                "span": span,
            }
        )

    for row in claims:
        source_id = row["span"]["source_id"]
        expected_ref = facts[source_id]["text_ref"]
        raw_source = sources[source_id]["text"].encode("utf8", errors="strict")

        def read_source(ref):
            _check(ref == expected_ref, "analysis-event-claim-source-ref-differs", 400)
            return raw_source

        claim_check(row["arguments"], read_source)

    screening = proposal["screening"]
    result = {
        "kind": "Stage1AgentAnalysisEventPlan",
        "schema_version": "1.1.0" if source_evidence else "1.0.0",
        "proposal_ref": proposal_ref,
        "actor": actor,
        "method": method,
        "proposal": deepcopy(proposal),
        "decision_arguments": {
            "work_id": proposal["work_id"],
            "decision": screening["decision"],
            "reason": screening["reason_code"],
            "rationale": screening["rationale"],
            "evidence_refs": evidence_refs,
            "actor": "agent",
            "authorization": None,
        },
        "claims": claims,
        "source_receipt_hashes": {
            source_id: fact["receipt_sha256"] for source_id, fact in facts.items()
        },
        "source_ids": _source_ids(reading["saved_reading"]),
        "core_events_created": False,
        "human_authorization": False,
        "researcher_acceptance": False,
        "scientific_acceptance": False,
    }
    if source_evidence:
        result["proposal_sha256"] = sha(raw)
        result["proposal_storage"] = "original-model-job"
    return result
