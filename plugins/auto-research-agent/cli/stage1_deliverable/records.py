"""Validate canonical versioned research records without awarding judgments."""

from datetime import datetime
from urllib.parse import parse_qsl, urlsplit

from .common import DeliverableError, identifier

CLASSIFICATION = (
    "topic_cluster",
    "method",
    "geography",
    "population",
    "data_type",
    "domain",
)
FINDINGS = (
    "question",
    "data",
    "method",
    "main_findings",
    "limitations",
    "relevance",
    "transferability",
)
LEVELS = {"metadata", "abstract", "full-text"}


def _keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise DeliverableError("unexpected or missing fields in " + label)


def _text(value):
    if (
        not isinstance(value, str)
        or not value.strip()
        or any(ord(c) < 32 and c not in "\n\t\r" for c in value)
    ):
        raise DeliverableError("missing text or forbidden control character")


def timestamp(value):
    _text(value)
    if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
        raise DeliverableError("access time requires timezone")


def public_uri(value):
    _text(value)
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or any(
            key.casefold().replace("-", "_")
            in {
                "token",
                "access_token",
                "api_key",
                "apikey",
                "password",
                "authorization",
                "signature",
                "x_amz_signature",
                "key",
            }
            for key, _ in parse_qsl(parsed.query)
        )
    ):
        raise DeliverableError(
            "source URI must be public HTTP(S), without credentials or query secrets"
        )


def _indexed(rows, field):
    if not isinstance(rows, list):
        raise DeliverableError("record collection must be a list")
    result = {}
    for row in rows:
        key = identifier(row[field])
        if key in result:
            raise DeliverableError("duplicate " + field)
        result[key] = row
    return result


def validate_records(records):
    _keys(
        records,
        (
            "kind",
            "schema_version",
            "topic",
            "as_of",
            "papers",
            "sources",
            "claims",
            "screening",
            "coverage",
        ),
        "records",
    )
    if (
        records["kind"] != "Stage1ResearchRecords"
        or records["schema_version"] != "1.0.0"
    ):
        raise DeliverableError("unsupported canonical record version")
    _text(records["topic"])
    timestamp(records["as_of"])
    papers = _indexed(records["papers"], "work_id")
    sources = _indexed(records["sources"], "source_id")
    claims = _indexed(records["claims"], "claim_id")
    decisions = _indexed(records["screening"], "decision_id")
    needs = _indexed(records["coverage"], "need_id")
    if not papers or not needs or not decisions:
        raise DeliverableError("papers, coverage and screening cannot be empty")

    def version(row):
        if (
            row["work_id"] not in papers
            or row["version_id"] != papers[row["work_id"]]["version_id"]
        ):
            raise DeliverableError("wrong work/version binding")

    for paper in papers.values():
        _keys(
            paper,
            (
                "work_id",
                "version_id",
                "title",
                "authors",
                "year",
                "venue",
                "doi",
                "url",
                "evidence_level",
                "source_ids",
                "classification",
                "roles",
                "findings",
                "claim_ids",
            ),
            "paper",
        )
        identifier(paper["version_id"])
        for name in ("title", "venue"):
            _text(paper[name])
        if not isinstance(paper["authors"], list) or not paper["authors"]:
            raise DeliverableError(
                "authors required; use explicit unknown when unverified"
            )
        for author in paper["authors"]:
            _text(author)
        if paper["year"] is not None and (
            type(paper["year"]) is not int or not 1000 <= paper["year"] <= 9999
        ):
            raise DeliverableError("invalid year")
        if paper["doi"] is not None and (
            not isinstance(paper["doi"], str) or not paper["doi"].startswith("10.")
        ):
            raise DeliverableError("DOI must be normalized or null")
        public_uri(paper["url"])
        if paper["evidence_level"] not in LEVELS:
            raise DeliverableError("invalid evidence level")
        _keys(paper["classification"], CLASSIFICATION, "classification")
        _keys(paper["findings"], FINDINGS, "findings")
        for value in (*paper["classification"].values(), *paper["findings"].values()):
            _text(value)
        for key, index in (("source_ids", sources), ("claim_ids", claims)):
            if not isinstance(paper[key], list) or len(set(paper[key])) != len(
                paper[key]
            ):
                raise DeliverableError("duplicate or invalid paper references")
            if any(
                x not in index or index[x]["work_id"] != paper["work_id"]
                for x in paper[key]
            ):
                raise DeliverableError("paper reference belongs to another work")
        if not paper["source_ids"]:
            raise DeliverableError("every paper needs a source attempt")
        if not isinstance(paper["roles"], list):
            raise DeliverableError("roles must be separate evidence-bound records")
        seen = set()
        for role in paper["roles"]:
            _keys(role, ("role", "reason", "claim_ids"), "role")
            if (
                role["role"]
                not in {"classic", "topic-core", "closest-work", "comparator"}
                or role["role"] in seen
            ):
                raise DeliverableError("invalid or duplicate literature role")
            seen.add(role["role"])
            _text(role["reason"])
            if not role["claim_ids"] or any(
                x not in paper["claim_ids"] for x in role["claim_ids"]
            ):
                raise DeliverableError(
                    "literature role needs same-work evidence claims"
                )
    for source in sources.values():
        _keys(
            source,
            (
                "source_id",
                "work_id",
                "version_id",
                "result_path",
                "result_sha256",
                "access_note",
            ),
            "source",
        )
        version(source)
        _text(source["access_note"])
        if source["source_id"] not in papers[source["work_id"]]["source_ids"]:
            raise DeliverableError("orphan source")
    for claim in claims.values():
        _keys(
            claim,
            (
                "claim_id",
                "work_id",
                "version_id",
                "text",
                "source_id",
                "relation",
                "evidence_level",
                "locator",
                "start",
                "end",
                "quote",
            ),
            "claim",
        )
        version(claim)
        for name in ("text", "locator", "quote"):
            _text(claim[name])
        source = sources.get(claim["source_id"])
        if (
            not source
            or source["work_id"] != claim["work_id"]
            or source["version_id"] != claim["version_id"]
        ):
            raise DeliverableError("claim source work/version differs")
        if claim["claim_id"] not in papers[claim["work_id"]]["claim_ids"]:
            raise DeliverableError("orphan claim")
        if (
            claim["relation"]
            not in {"supports", "partial", "contradicts", "unverified"}
            or claim["evidence_level"] not in LEVELS
        ):
            raise DeliverableError("invalid claim relation or level")
        if (
            type(claim["start"]) is not int
            or type(claim["end"]) is not int
            or not 0 <= claim["start"] < claim["end"]
        ):
            raise DeliverableError("invalid claim character range")
        if claim["locator"] != f"characters {claim['start']}:{claim['end']}":
            raise DeliverableError(
                "claim locator must identify the exact character range"
            )
    for decision in decisions.values():
        _keys(
            decision,
            (
                "decision_id",
                "work_id",
                "version_id",
                "status",
                "reason",
                "query",
                "discovery_path",
                "observed_at",
            ),
            "screening",
        )
        version(decision)
        if decision["status"] not in {"include", "exclude", "pending"}:
            raise DeliverableError("invalid screening state")
        for name in ("reason", "query", "discovery_path"):
            _text(decision[name])
        timestamp(decision["observed_at"])
    if set(x["work_id"] for x in decisions.values()) != set(papers):
        raise DeliverableError("every paper needs preserved screening history")
    for need in needs.values():
        _keys(
            need,
            (
                "need_id",
                "description",
                "work_ids",
                "recent_sweep",
                "closest_work_check",
                "unresolved",
                "stop_decision",
                "reason",
            ),
            "coverage",
        )
        for name in (
            "description",
            "recent_sweep",
            "closest_work_check",
            "unresolved",
            "reason",
        ):
            _text(need[name])
        if not isinstance(need["work_ids"], list) or any(
            x not in papers for x in need["work_ids"]
        ):
            raise DeliverableError("coverage references unknown work")
        if need["stop_decision"] not in {"stop", "continue"}:
            raise DeliverableError("stop decision must remain explicit")
    return records
