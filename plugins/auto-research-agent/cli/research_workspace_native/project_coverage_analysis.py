"""Pure, source-bound identity/coverage proposals; never Core acceptance or authority."""

from copy import deepcopy
import re
from stage1_deliverable.common import canonical, sha
from .project_full_reading import full_reading_prompt
from .project_semantic_drafts import (
    MAX_PROMPT_BYTES,
    full_source_prompt,
    validate_full_source_draft,
)
from .session_api import _check

FIELDS = {"title", "authors", "year", "identifier", "version"}
COMPARISON_FIELDS = {"status", "observed", "claim_key", "rationale"}
PROPOSAL_FIELDS = {
    "context_sha256",
    "identity_status",
    "identity_comparisons",
    "cluster_claim_keys",
    "closest",
    "rationale",
}
CONTEXT_FIELDS = {
    "kind",
    "schema_version",
    "binding",
    "expected_identity",
    "candidate_identity_status",
    "clusters",
}


def _text(v, cap=4096):
    _check(type(v) is str and bool(v.strip()), "coverage-analysis-text-invalid", 400)
    try:
        size = len(v.encode("utf8", errors="strict"))
    except UnicodeError:
        _check(False, "coverage-analysis-text-invalid", 400)
    _check(size <= cap, "coverage-analysis-text-bound", 400)


def _identity(v):
    _check(
        type(v) is dict and set(v) == FIELDS, "coverage-analysis-identity-fields", 400
    )
    for name in ("title", "version"):
        if v[name] is not None:
            _text(v[name])
    _check(
        v["year"] is None or type(v["year"]) is int and 1000 <= v["year"] <= 9999,
        "coverage-analysis-year-invalid",
        400,
    )
    authors = v["authors"]
    _check(
        authors is None or type(authors) is list and 1 <= len(authors) <= 128,
        "coverage-analysis-authors-invalid",
        400,
    )
    for author in authors or []:
        _text(author, 1024)
    identifier = v["identifier"]
    if identifier is not None:
        _check(
            type(identifier) is dict
            and set(identifier) == {"scheme", "value"}
            and type(identifier["scheme"]) is str
            and identifier["scheme"] in {"doi", "arxiv", "pmid"},
            "coverage-analysis-identifier-invalid",
            400,
        )
        _text(identifier["value"], 1024)


def validate_context(value, full_source):
    full_source_prompt(full_source, max_prompt_bytes=MAX_PROMPT_BYTES)
    _check(
        type(value) is dict
        and set(value) == CONTEXT_FIELDS
        and value["kind"] == "Stage1IdentityCoverageContext"
        and value["schema_version"] == "1.0.0",
        "coverage-analysis-context-fields",
        400,
    )
    _check(
        value["binding"] == full_source["binding"],
        "coverage-analysis-context-binding",
        400,
    )
    _identity(value["expected_identity"])
    _check(
        type(value["candidate_identity_status"]) is str
        and value["candidate_identity_status"] in {"unverified", "conflict"},
        "coverage-analysis-candidate-state",
        400,
    )
    clusters = value["clusters"]
    _check(
        type(clusters) is list and 1 <= len(clusters) <= 64,
        "coverage-analysis-clusters-bound",
        400,
    )
    ids = []
    for c in clusters:
        _check(
            type(c) is dict and set(c) == {"cluster_id", "title"},
            "coverage-analysis-cluster-fields",
            400,
        )
        _text(c["cluster_id"], 256)
        _text(c["title"], 8192)
        ids.append(c["cluster_id"])
    _check(len(set(ids)) == len(ids), "coverage-analysis-duplicate-cluster", 400)
    _check(len(canonical(value)) <= 256 * 1024, "coverage-analysis-context-bound", 400)
    return deepcopy(value)


def coverage_context(reading_input, clusters, *, candidate_identity_status):
    """Caller supplies actual replayed compiled clusters, never brief need IDs."""
    full_reading_prompt(reading_input)
    saved = reading_input["saved_reading"]
    discovery = saved["discovery"]
    _check(type(discovery) is dict, "coverage-analysis-discovery-invalid", 400)
    record = discovery.get("record")
    _check(type(record) is dict, "coverage-analysis-discovery-record-required", 400)
    selected = next(
        (
            dict(scheme=k, value=record[k])
            for k in ("doi", "arxiv", "pmid")
            if record.get(k)
        ),
        None,
    )
    authors = deepcopy(record.get("authors"))
    if type(authors) is list and not authors:
        authors = None
    value = dict(
        kind="Stage1IdentityCoverageContext",
        schema_version="1.0.0",
        binding=deepcopy(reading_input["full_source"]["binding"]),
        expected_identity=dict(
            title=record.get("title"),
            authors=authors,
            year=record.get("year"),
            identifier=selected,
            version=record.get("version"),
        ),
        candidate_identity_status=candidate_identity_status,
        clusters=deepcopy(clusters),
    )
    return validate_context(value, reading_input["full_source"])


def coverage_instructions(context, full_source):
    value = validate_context(context, full_source)
    return (
        "For the opt-in analysis1.1 proposal add exactly one coverage object with context_sha256, identity_status, identity_comparisons, cluster_claim_keys, closest, rationale. "
        "This is an agent proposal, never human review, scientific acceptance or permission. Retain missing metadata, conflicts and Unknown. "
        "context_sha256 must equal the supplied context hash. identity_status is verified, unverifiable or conflict. "
        "identity_comparisons has exactly title/authors/year/identifier/version; each contains exactly status (match/conflict/unknown), observed, claim_key, rationale. "
        "Compare each expected field against primary source text separately. A match requires a distinct supports claim with exact quoted evidence containing its observed value; observed must equal the expected value. "
        "authors is an array, year is an integer, identifier is {scheme,value}, title/version are strings. "
        "For unknown use claim_key=null. A conflict requires different known expected and observed values and its own distinct supports claim quoting the observed primary-source field. Missing expected or observed data remains unknown; it cannot match or establish conflict. Preserve other contradictory evidence separately in claims. "
        "An opaque Core version_id, readable SDK text, DOI match or five arbitrary claims does not verify publication version. Missing record.version stays unknown. "
        "cluster_claim_keys maps actual compiled cluster IDs to supports/partial claim keys from this same proposal, never to brief need IDs. "
        "Use separate topic/relevance claims rather than bibliographic identity claims for these mappings. Include decisions need at least one such mapping. closest is a boolean judgment and requires all identity fields verified; it does not establish citation coverage or sufficient stopping. "
        "Use work-specific reasons. Do not output canonical event IDs, roles, authorizations or acceptance fields.\n"
        + canonical(dict(context=value, context_sha256=sha(canonical(value)))).decode(
            "utf8"
        )
    )


def _fold(v):
    return re.sub(r"\s+", " ", str(v)).strip().casefold()


def _bound_proposal(proposal, full_source):
    # Revalidate the exact primary-source spans at this public helper boundary.
    # The normalized full-analysis wrapper uses a separate outer snapshot hash;
    # its explicit full_source_sha256 preserves the original input identity.
    _check(
        type(proposal) is dict
        and {"reading", "claims", "work_id", "version_id"} <= set(proposal),
        "coverage-analysis-proposal-invalid",
        400,
    )
    screening = proposal.get("screening")
    _check(
        type(screening) is dict
        and type(screening.get("decision")) is str
        and screening["decision"] in {"include", "exclude", "pending"},
        "coverage-analysis-screening-invalid",
        400,
    )
    reading = validate_full_source_draft(canonical(proposal["reading"]), full_source)
    _check(
        proposal["work_id"] == reading["work_id"]
        and proposal["version_id"] == reading["version_id"]
        and proposal.get("full_source_sha256", proposal.get("snapshot_sha256"))
        == reading["input_sha256"],
        "coverage-analysis-proposal-binding",
        400,
    )
    rows = proposal["claims"]
    _check(
        type(rows) is list and len(rows) <= 128, "coverage-analysis-claims-invalid", 400
    )
    keys = []
    for row in rows:
        _check(
            type(row) is dict
            and {"claim_key", "relation", "evidence_index"} <= set(row),
            "coverage-analysis-claim-invalid",
            400,
        )
        _text(row["claim_key"], 64)
        _check(
            type(row["relation"]) is str
            and row["relation"]
            in {
                "supports",
                "partial",
                "contradicts",
                "unclear",
                "unverifiable",
                "context",
            },
            "coverage-analysis-claim-invalid",
            400,
        )
        index = row["evidence_index"]
        _check(
            type(index) is int and 0 <= index < len(reading["draft"]["evidence"]),
            "coverage-analysis-evidence-index",
            400,
        )
        keys.append(row["claim_key"])
    _check(len(set(keys)) == len(keys), "coverage-analysis-duplicate-claim", 400)


def validate_coverage(value, context, proposal, full_source):
    """Validate references and literal comparisons only; meaning remains agent-assessed."""
    validate_context(context, full_source)
    _bound_proposal(proposal, full_source)
    _check(
        type(value) is dict and set(value) == PROPOSAL_FIELDS,
        "coverage-analysis-proposal-fields",
        400,
    )
    _check(
        value["context_sha256"] == sha(canonical(context)),
        "coverage-analysis-context-sha256",
        400,
    )
    status = value["identity_status"]
    _check(
        type(status) is str and status in {"verified", "unverifiable", "conflict"},
        "coverage-analysis-status",
        400,
    )
    comparisons = value["identity_comparisons"]
    _check(
        type(comparisons) is dict and set(comparisons) == FIELDS,
        "coverage-analysis-comparison-fields",
        400,
    )
    claims = {c["claim_key"]: c for c in proposal["claims"]}
    evidence = proposal["reading"]["evidence"]
    selected = []
    matched = []
    for field in sorted(FIELDS):
        row = comparisons[field]
        _check(
            type(row) is dict and set(row) == COMPARISON_FIELDS,
            "coverage-analysis-comparison-fields",
            400,
        )
        _text(row["rationale"], 1024)
        _check(
            type(row["status"]) is str
            and row["status"] in {"match", "conflict", "unknown"},
            "coverage-analysis-comparison-status",
            400,
        )
        observed = deepcopy(context["expected_identity"])
        observed[field] = row["observed"]
        _identity(observed)
        if row["status"] == "unknown":
            _check(row["claim_key"] is None, "coverage-analysis-unmatched-claim", 400)
            continue
        expected = context["expected_identity"][field]
        _check(
            expected is not None
            and row["observed"] is not None
            and (canonical(row["observed"]) == canonical(expected))
            == (row["status"] == "match"),
            "coverage-analysis-comparison-differs",
            400,
        )
        key = row["claim_key"]
        _check(
            type(key) is str and key in claims,
            "coverage-analysis-identity-claim-missing",
            400,
        )
        claim = claims[key]
        _check(
            claim["relation"] == "supports",
            "coverage-analysis-identity-needs-support",
            400,
        )
        quote = evidence[claim["evidence_index"]]["quote"]
        parts = (
            row["observed"]
            if field == "authors"
            else [row["observed"]["value"]]
            if field == "identifier"
            else [row["observed"]]
        )
        _check(
            all(_fold(part) in _fold(quote) for part in parts),
            "coverage-analysis-identity-quote-differs",
            400,
        )
        selected.append(key)
        if row["status"] == "match":
            matched.append(field)
    _check(
        len(set(selected)) == len(selected),
        "coverage-analysis-distinct-identity-claims",
        400,
    )
    all_match = len(matched) == 5 and context["candidate_identity_status"] != "conflict"
    has_conflict = context["candidate_identity_status"] == "conflict" or any(
        r["status"] == "conflict" for r in comparisons.values()
    )
    _check(
        status
        == (
            "conflict" if has_conflict else "verified" if all_match else "unverifiable"
        ),
        "coverage-analysis-inconsistent-status",
        400,
    )
    mapping = value["cluster_claim_keys"]
    _check(
        type(mapping) is dict
        and set(mapping) <= {c["cluster_id"] for c in context["clusters"]},
        "coverage-analysis-cluster-not-offered",
        400,
    )
    for key in mapping.values():
        _check(
            type(key) is str
            and key in claims
            and claims[key]["relation"] in {"supports", "partial"},
            "coverage-analysis-cluster-claim-missing",
            400,
        )
    _check(
        not set(mapping.values()).intersection(selected),
        "coverage-analysis-identity-is-not-topic-support",
        400,
    )
    _check(
        proposal["screening"]["decision"] != "include" or bool(mapping),
        "coverage-analysis-included-needs-cluster",
        400,
    )
    _check(
        type(value["closest"]) is bool
        and (not value["closest"] or status == "verified"),
        "coverage-analysis-closest-unverified",
        400,
    )
    _text(value["rationale"], 1024)
    return deepcopy(value)
