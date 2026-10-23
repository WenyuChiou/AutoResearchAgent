"""Automatic local identity triage of saved observations, without new research.

This opt-in companion preserves the frozen index. It reuses the saved candidate
proof validator, looks up exact identifiers in the saved source inventory and
keeps acquisition, semantic reading and researcher decisions separate.
"""

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

from stage1_deliverable.common import (
    DeliverableError,
    canonical,
    private_output,
    reject_links,
    sha,
)

from .candidate_reassessment import validate_candidates
from .original_record_recovery import _pointer

CONTRACT = "S1-AUTOMATIC-BACKLOG-1.0.0"
MAX_INDEX_BYTES = 32 * 1024 * 1024


def _require(condition, reason):
    if not condition:
        raise DeliverableError("automatic-backlog: " + reason)


def _json(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            _require(key not in value, "duplicate JSON key")
            value[key] = item
        return value

    def finite(_):
        raise DeliverableError("automatic-backlog: nonfinite JSON")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=finite)


def _hash(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _url(value):
    """Remove explicit tracking fields only; retain version, path case and query."""
    if type(value) is not str or not value.strip():
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 80, 443}
        ):
            return None
    except ValueError:
        return None
    host = parsed.hostname.lower().removeprefix("www.")
    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.startswith("utm_") and key not in {"trk", "fbclid"}
    ]
    path = unquote(parsed.path).rstrip("/")
    # HTTP transport and a fragment do not identify a different saved document.
    return host + path + ("?" + urlencode(sorted(query)) if query else "")


def _identifiers(value, *, doi=False):
    """Cross identifiers establish possible work matches, never source versions."""
    result = set()
    if type(value) is not str:
        return result
    value = unquote(value).strip()
    normalized = _url(value)
    if normalized:
        result.add(("url", normalized))
        parsed = urlsplit(value)
        host, path = parsed.hostname.lower().removeprefix("www."), parsed.path
        if host in {"doi.org", "dx.doi.org"}:
            value, doi = unquote(path).lstrip("/"), True
        if host == "arxiv.org":
            match = re.fullmatch(r"/(?:abs|pdf|html)/(.+?)(?:\.pdf)?/?", path)
            if match:
                identifier = match[1]
                if re.fullmatch(
                    r"(?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7})(?:v\d+)?", identifier
                ):
                    result.add(("arxiv-work", re.sub(r"v\d+$", "", identifier)))
                    if re.search(r"v\d+$", identifier):
                        result.add(("arxiv-version", identifier))
        if host in {"pmc.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov"}:
            match = re.fullmatch(r"/(?:pmc/)?articles/(PMC\d+)/?", path, re.I)
            if match:
                result.add(("pmcid", match[1].upper()))
        if host == "pubmed.ncbi.nlm.nih.gov":
            match = re.fullmatch(r"/(\d+)/?", path)
            if match:
                result.add(("pmid", match[1]))
    if doi and re.fullmatch(r"10\.\d{4,9}/\S+", value, re.I):
        result.add(("doi", value.casefold()))
    return result


def _inventory(index):
    """Use only explicit per-source identity fields; never infer from titles."""
    papers = {(row["work_id"], row["version_id"]): row for row in index["papers"]}
    by_identifier = defaultdict(set)
    for key, paper in papers.items():
        for token in _identifiers(paper.get("url")) | _identifiers(
            paper.get("doi"), doi=True
        ):
            by_identifier[token].add(key)
    for source in index.get("sources", []):
        key = source.get("work_id"), source.get("version_id")
        if key not in papers:
            continue
        receipt = source.get("receipt") or {}
        rows = [
            source,
            receipt,
            *source.get("attempts", []),
            *receipt.get("attempts", []),
        ]
        for row in rows:
            for field in ("url", "final_url", "requested_uri", "resolved_uri"):
                for token in _identifiers(row.get(field)):
                    by_identifier[token].add(key)
    return papers, by_identifier


def _saved_cohort(index):
    recovery = index.get("original_record_recovery") or {}
    payload = recovery.get("payload") or {}
    reference = payload.get("new_candidate_screening")
    _require(type(reference) is dict, "saved candidate cohort required")
    _require(
        payload.get("project_id") == index["project_id"], "recovery project differs"
    )
    _require(
        sha(canonical(payload)) == recovery.get("payload_sha256"),
        "recovery payload hash differs",
    )
    artifacts = recovery.get("artifacts_utf8")
    _require(
        type(artifacts) is dict and len(artifacts) <= 512,
        "saved proof inventory required",
    )
    manifest_raw = recovery.get("manifest_utf8")
    _require(type(manifest_raw) is str, "original proof manifest required")
    _require(
        sha(manifest_raw.encode("utf-8")) == recovery.get("manifest_sha256"),
        "original manifest hash differs",
    )
    declared = _json(manifest_raw).get("files")
    _require(
        type(declared) is dict and set(declared) == set(artifacts),
        "original proof inventory differs",
    )

    def resolve(ref):
        _require(
            type(ref) is dict and type(ref.get("path")) is str,
            "proof reference required",
        )
        text = artifacts.get(ref["path"])
        _require(type(text) is str, "original proof missing")
        raw = text.encode("utf-8")
        digest = declared.get(ref["path"])
        _require(_hash(digest) and sha(raw) == digest, "original proof hash differs")
        _require(
            all(
                ref[key] == digest for key in ("sha256", "source_sha256") if key in ref
            ),
            "proof reference hash differs",
        )
        try:
            document = _json(raw)
        except json.JSONDecodeError:
            document = text
        return {
            "value": _pointer(document, ref.get("pointer", "")),
            "source_sha256": sha(raw),
        }

    observed = resolve(reference)
    _require(
        observed["value"] == reference.get("value"), "candidate projection differs"
    )
    cohort = validate_candidates(
        reference, resolve, index, payload["input_canonical_sha256"]
    )
    _require(
        cohort["observations"] == reference.get("observations"),
        "original observations differ",
    )
    return cohort


def inspect_backlog(raw, *, expected_index_sha256, project_id, input_version):
    """Perform local proof/identity/dedup steps and retain all unresolved work.

    Only the hosting caller chooses the expected pin and typed input identity.
    Matching an identifier is not a full-source, semantic or scientific review.
    """
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_INDEX_BYTES, "index byte bound")
    _require(
        _hash(expected_index_sha256) and sha(raw) == expected_index_sha256,
        "external index hash differs",
    )
    index = _json(raw)
    _require(
        type(project_id) is str and index.get("project_id") == project_id,
        "project differs",
    )
    _require(
        type(input_version) in {str, int} and bool(input_version),
        "typed input version required",
    )
    papers = index.get("papers")
    _require(type(papers) is list and 0 < len(papers) <= 5000, "saved papers required")
    _require(
        all(
            type(row.get("input_version")) is type(input_version)
            and row["input_version"] == input_version
            for row in papers
        ),
        "input version value or type differs",
    )
    _require(
        len({(p["work_id"], p["version_id"]) for p in papers}) == len(papers),
        "duplicate saved work/version",
    )
    cohort = _saved_cohort(index)
    _, lookup = _inventory(index)
    pending = [row for row in cohort["value"]["rows"] if row["decision"] == "pending"]
    earlier = {}
    rows = []
    for row in pending:
        url_key = _url(row.get("url_observed"))
        tokens = _identifiers(row.get("url_observed"))
        matches = set().union(*(lookup[token] for token in tokens)) if tokens else set()
        work_ids = {key[0] for key in matches}
        duplicate_of = earlier.get(url_key) if url_key else None
        if url_key:
            earlier.setdefault(url_key, row["observation_ref"])
        if len(work_ids) > 1:
            status, next_step = "identity-conflict", "resolve-identity-conflict"
        elif matches:
            status, next_step = (
                "saved-work-match-version-not-certified",
                "verify-version-and-read-complete-source",
            )
        else:
            status, next_step = (
                "identity-and-source-unresolved",
                "resolve-identifiers-and-acquire-lawful-source",
            )
        if duplicate_of:
            status, next_step = (
                "repeated-observation",
                "reuse-earlier-source-work-without-dropping-observation",
            )
        rows.append(
            {
                "observation_ref": row["observation_ref"],
                "original_observation_sha256": row["original_observation_sha256"],
                "original_decision_sha256": sha(canonical(row)),
                "original_decision": "pending",
                "original_rationale": row["rationale"],
                "saved_evidence": {
                    key: row["saved_evidence"][key]
                    for key in ("batch_ref", "source_sha256", "start", "end")
                },
                "url_observed": row["url_observed"],
                "need_ids": deepcopy(row.get("need_ids", [])),
                "status": status,
                "same_url_prior_observation": duplicate_of,
                "saved_work_matches": [
                    dict(work_id=work, version_id=version)
                    for work, version in sorted(matches)
                ],
                "identifier_matches": [
                    dict(kind=kind, value=value)
                    for kind, value in sorted(tokens)
                    if lookup[(kind, value)]
                ],
                "executed_steps": [
                    "original-capture-and-observation-proof",
                    "saved-identifier-lookup",
                    "saved-observation-dedup-check",
                ],
                "next_automatic_step": next_step,
                "automatic_work_status": "not-executed",
                "academic_decision": None,
                "complete_source_read": False,
                "researcher_decision_required": None,
                "researcher_decision_reason": "No demonstrated researcher-only blocker; automatic source/review work remains.",
            }
        )
    formal = (index.get("readiness") or {}).get("formal_progress") or {}
    return {
        "kind": "Stage1AutomaticBacklogCompanion",
        "contract": CONTRACT,
        "binding": {
            "project_id": project_id,
            "input_version": input_version,
            "index_sha256": expected_index_sha256,
        },
        "cohort_sha256": sha(canonical(cohort["value"])),
        "scope": "saved-observation-local-proof-and-identity-triage-only",
        "counts": {
            "saved_observations": cohort["counts"]["saved_observations"],
            "original_pending": len(pending),
            "local_triage_executed": len(rows),
            "saved_work_matches": sum(bool(row["saved_work_matches"]) for row in rows),
            "status": dict(sorted(Counter(row["status"] for row in rows).items())),
            "academic_automatically_resolved": 0,
            "automatic_not_executed_or_retry": len(rows),
            "demonstrated_researcher_only_decisions": 0,
        },
        "rows": rows,
        "researcher_questions": [],
        "recorded_stop": {
            "original_formal_progress": deepcopy(formal),
            "original_coverage_stop_reasons": [
                row.get("stop_reason") for row in index.get("coverage", [])
            ],
            "new_complete_rounds_executed": 0,
            "new_marginal_yield": None,
            "automatic_steps_exhausted": False,
            "pending_source_review_is_not_human_required": True,
            "sufficient_stop_recomputed": False,
        },
        "authority": {
            "execution_authorized": False,
            "source_acquisition_permit_supplied": False,
            "model_review_permit_supplied": False,
            "scientific_acceptance": False,
            "eligible_for_stage2": False,
            "changes_original_decisions": False,
        },
        "calls": {"model": 0, "query": 0, "acquisition": 0},
        "unconnected_execution_dependencies": [
            "original-host-current-run-permit-provider-and-budget",
            "source-version-and-complete-source-reading-producer",
            "semantic-automatic-screening-and-full-note-producer",
            "coverage-rounds-and-complete-stage1-package-validation",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True)
    parser.add_argument("--expected-index-sha256", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--input-version-json", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    source = Path(args.index)
    reject_links(source)
    _require(
        source.is_file() and source.stat().st_size <= MAX_INDEX_BYTES,
        "index byte bound",
    )
    result = inspect_backlog(
        source.read_bytes(),
        expected_index_sha256=args.expected_index_sha256,
        project_id=args.project_id,
        input_version=_json(args.input_version_json),
    )
    output = private_output(args.output)
    _require(output.parent.is_dir(), "existing private output parent required")
    with output.open("xb") as stream:
        stream.write(canonical(result) + b"\n")
    print(
        json.dumps(
            {
                "contract": CONTRACT,
                "output_sha256": sha(output.read_bytes()),
                "counts": result["counts"],
            }
        )
    )


if __name__ == "__main__":
    main()
