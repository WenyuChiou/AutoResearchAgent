"""Conservative work keys; agreement never means bibliographic verification."""

import re
import unicodedata
from urllib.parse import unquote

from .journal import LedgerError, canonical, digest


def text_key(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def work_key(record):
    doi = record.get("doi")
    if doi:
        doi = unquote(doi.strip()).casefold()
        doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi)
        if not re.fullmatch(r"10\.\d{4,9}/\S+", doi):
            raise LedgerError("invalid-doi: saved record needs correction")
        return "doi:" + doi
    if record.get("arxiv"):
        arxiv = record["arxiv"].strip().casefold()
        if not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7})(?:v[1-9]\d*)?", arxiv):
            raise LedgerError("invalid-arxiv")
        return "arxiv:" + re.sub(r"v\d+$", "", arxiv)
    if record.get("pmid"):
        pmid = record["pmid"].strip()
        if not re.fullmatch(r"[1-9]\d*", pmid):
            raise LedgerError("invalid-pmid")
        return "pmid:" + pmid
    if (
        not record.get("title")
        or not record.get("authors")
        or record.get("year") is None
    ):
        raise LedgerError(
            "insufficient-identity: title, year and first author required without an identifier"
        )
    return "metadata:" + digest(
        canonical(
            [text_key(record["title"]), record["year"], text_key(record["authors"][0])]
        )
    )


def candidate_revision(previous, *, record, completion, query_id, index):
    key = work_key(record)
    work_id = "work-" + digest(key.encode())
    discovery_id = f"{completion['event_id']}:{index}"
    # Unstated versions stay separate until explicit relationship evidence exists.
    version_key = record.get("version") or "unresolved:" + discovery_id
    version_id = "version-" + digest(canonical([key, version_key]))
    discoveries = ([] if previous is None else previous["discoveries"]) + [
        dict(
            discovery_id=discovery_id,
            query_id=query_id,
            attempt_id=completion["attempt_id"],
            completion_id=completion["event_id"],
            record_index=index,
            version_id=version_id,
            record=record,
            source_ref=completion["records"],
        )
    ]
    fingerprints = {
        canonical(
            [
                text_key(d["record"]["title"]),
                d["record"].get("year"),
                [text_key(a) for a in d["record"]["authors"]],
            ]
        )
        for d in discoveries
    }
    return dict(
        kind="CandidateRevision",
        work_id=work_id,
        canonical_key=key,
        revision=1 if previous is None else previous["revision"] + 1,
        identity_status="conflict" if len(fingerprints) > 1 else "unverified",
        evidence_level="metadata",
        version_ids=sorted({d["version_id"] for d in discoveries}),
        discoveries=discoveries,
    )
