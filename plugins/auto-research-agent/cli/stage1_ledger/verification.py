"""Compare saved bibliographic records without authenticating sources or claims."""

import re

from .identity import text_key, work_key
from .journal import LedgerError

FIELDS = (
    "title",
    "authors",
    "year",
    "doi",
    "arxiv",
    "pmid",
    "version",
    "arxiv_version",
)


def normalized(record, field):
    if field == "arxiv_version":
        if not record.get("arxiv"):
            return None
        work_key({"arxiv": record["arxiv"]})
        match = re.search(r"v([1-9]\d*)$", record["arxiv"].strip().casefold())
        return match.group(1) if match else None
    value = record.get(field)
    if value is None or value == "" or value == []:
        return None
    if field in {"doi", "arxiv", "pmid"}:
        return work_key({field: value})
    if field == "authors":
        authors = [text_key(author) for author in value]
        return authors if all(authors) else None
    return value if field == "year" else text_key(value) or None


def field_agreement(target, reference, field):
    try:
        left, right = normalized(target, field), normalized(reference, field)
    except LedgerError:
        return "invalid"
    if left is None or right is None:
        return "unavailable"
    return "match" if left == right else "mismatch"


def comparison(
    works,
    starts,
    history,
    read_ref,
    *,
    target_work_id,
    target_discovery_id,
    reference_discovery_id,
    resolver_ref,
    assessor,
):
    discoveries = {
        d["discovery_id"]: (c, d) for c in works.values() for d in c["discoveries"]
    }
    if target_discovery_id not in discoveries:
        raise LedgerError("unknown-target-discovery")
    candidate, target = discoveries[target_discovery_id]
    if candidate["work_id"] != target_work_id:
        raise LedgerError("target-work-discovery-mismatch")
    if (reference_discovery_id is None) == (resolver_ref is None):
        raise LedgerError("one-reference-or-resolver-required")
    refs = [target["source_ref"]]
    fields = dict.fromkeys(FIELDS, "unavailable")
    reference_candidate = None
    relationship = "resolver-only"
    if reference_discovery_id is None:
        refs.append(resolver_ref)
    else:
        if reference_discovery_id == target_discovery_id:
            raise LedgerError("same-discovery-cannot-check-itself")
        if reference_discovery_id not in discoveries:
            raise LedgerError("unknown-reference-discovery")
        reference_candidate, reference = discoveries[reference_discovery_id]
        refs.append(reference["source_ref"])
        target_backend = starts[target["attempt_id"]]["backend"]
        reference_backend = starts[reference["attempt_id"]]["backend"]
        relationship = (
            "same-backend"
            if text_key(target_backend) == text_key(reference_backend)
            else "different-backends"
        )
        fields = {
            field: field_agreement(target["record"], reference["record"], field)
            for field in FIELDS
        }
    for ref in refs:
        read_ref(ref)
    work_fields = [fields[field] for field in FIELDS[:6]]
    if any(value in {"mismatch", "invalid"} for value in work_fields) or (
        reference_candidate is not None
        and (
            candidate["identity_status"] == "conflict"
            or reference_candidate["identity_status"] == "conflict"
        )
    ):
        work_agreement = "conflict"
    elif (
        relationship == "different-backends"
        and all(fields[field] == "match" for field in ("title", "authors", "year"))
        and any(fields[field] == "match" for field in ("doi", "arxiv", "pmid"))
    ):
        work_agreement = "consistent"
    else:
        work_agreement = "unverified"
    version_fields = [fields["version"], fields["arxiv_version"]]
    if any(value in {"mismatch", "invalid"} for value in version_fields):
        version_agreement = "conflict"
    elif work_agreement == "consistent" and "match" in version_fields:
        version_agreement = "consistent"
    else:
        version_agreement = "unverified"
    previous = history.get((target_work_id, target["version_id"]))
    return dict(
        kind="IdentityComparison",
        target_work_id=target_work_id,
        target_version_id=target["version_id"],
        target_candidate_event_id=candidate["event_id"],
        target_discovery_id=target_discovery_id,
        reference_discovery_id=reference_discovery_id,
        reference_candidate_event_id=reference_candidate["event_id"]
        if reference_candidate
        else None,
        resolver_ref=resolver_ref,
        assessor=assessor,
        fields=fields,
        source_relationship=relationship,
        work_agreement=work_agreement,
        version_agreement=version_agreement,
        evidence_refs=refs,
        previous_comparison_id=previous["event_id"] if previous else None,
        scope="saved-bibliographic-comparison",
    )


def current_comparisons(works, events):
    current = {c["event_id"] for c in works.values()}
    latest = {
        (p["target_work_id"], p["target_version_id"]): p
        for p in events
        if p["kind"] == "IdentityComparison"
    }
    return dict(
        identity_verification="not-performed",
        comparisons=[
            dict(
                comparison=p,
                current=p["target_candidate_event_id"] in current
                and (
                    p["reference_candidate_event_id"] is None
                    or p["reference_candidate_event_id"] in current
                ),
            )
            for p in latest.values()
        ],
    )
