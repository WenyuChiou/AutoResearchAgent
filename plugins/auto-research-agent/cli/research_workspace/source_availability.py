"""Derive source readability separately from historical claim assessment."""

import json

from stage1_deliverable.common import DeliverableError, sha


AVAILABILITY = (
    "full-text-readable",
    "abstract-only",
    "bibliography-only",
    "engineering-read-failure",
)


def _require(value, message):
    if not value:
        raise DeliverableError(message)


def _accepted_passages(index, rerun_rows):
    supplement = index.get("supplement", {})
    if supplement.get("status") != "accepted-scoped-private":
        return {}
    evidence = supplement.get("evidence_files", {})
    sources = {
        (row["work_id"], row["version_id"], row["source_id"], row.get("raw_sha256"))
        for row in rerun_rows
    }
    accepted = {}
    for name, document in evidence.items():
        if not name.endswith(".json"):
            continue
        _require(
            sha(document["text"].encode("utf-8")) == document["sha256"],
            "supplement evidence snapshot hash differs",
        )
        payload = json.loads(document["text"])
        if "passages" not in payload:
            continue
        source_kind = str(payload.get("source_kind", "")).casefold()
        _require(source_kind, "supplement passage source kind missing")
        explicit_abstract = "abstract" in source_kind and (
            "full text" not in source_kind
            or "not article full text" in source_kind
            or "not full text" in source_kind
        )
        if not explicit_abstract:
            continue
        for passage in payload["passages"]:
            locator = passage.get("raw_html") or {}
            clean = passage.get("clean_source") or passage.get("clean_abstract") or {}
            clean_document = next(
                (
                    item
                    for item in evidence.values()
                    if item["sha256"] == clean.get("sha256")
                ),
                None,
            )
            clean_text = clean_document["text"] if clean_document else ""
            binding = (
                passage.get("work_id"),
                passage.get("version_id"),
                passage.get("source_id"),
                passage.get("raw_sha256"),
            )
            if (
                binding in sources
                and str(passage.get("quote", "")).strip()
                and any(locator.get(key) for key in ("xpath", "selector", "line"))
                and locator.get("sha256") == passage.get("raw_sha256")
                and clean.get("sha256")
                and sha(clean_text.encode()) == clean.get("sha256")
                and type(clean.get("start")) is int
                and type(clean.get("end")) is int
                and 0 <= clean["start"] < clean["end"] <= len(clean_text)
                and clean_text[clean["start"] : clean["end"]] == passage["quote"]
            ):
                accepted.setdefault(binding[:2], []).append(passage["passage_id"])
    return accepted


def _atomic_version(index, atom, rerun_rows):
    """Resolve an already accepted reference, never guess from a work name."""
    reference = atom.get("evidence_ref", "")
    path = reference[3:] if reference.startswith("../") else reference
    document = index["supplement"].get("evidence_files", {}).get(path)
    if not document or not path.endswith(".json"):
        return None
    _require(
        sha(document["text"].encode()) == document["sha256"],
        "atomic reference hash differs",
    )
    payload = json.loads(document["text"])
    candidates = payload.get("passages", [])
    if "atomic_claims" in payload:
        candidates = [
            row
            for row in payload["atomic_claims"]
            if row.get("claim_id") == atom["atom_id"]
        ]
    elif atom.get("passage_ids"):
        candidates = [
            row for row in candidates if row.get("passage_id") in atom["passage_ids"]
        ]
    bindings = {
        (row["work_id"], row["version_id"], row["source_id"]): row.get("raw_sha256")
        for row in rerun_rows
    }
    versions = set()
    for candidate in candidates:
        key = tuple(
            candidate.get(name) for name in ("work_id", "version_id", "source_id")
        )
        raw_hash = candidate.get("raw_sha256") or payload.get("source_binding", {}).get(
            "source_sha256"
        )
        if key[0] == atom["work_id"] and key in bindings and raw_hash == bindings[key]:
            versions.add(key[1])
    explicit = atom.get("version_id")
    if explicit:
        return explicit if versions == {explicit} else None
    return next(iter(versions)) if len(versions) == 1 else None


def derive_source_availability(index):
    """Return deterministic per-work and per-claim source availability rows."""
    _require(
        index.get("schema_version") == "3.0.0",
        "source availability requires a rerun index",
    )
    rerun_rows = index["source_rerun"]["data"]["rows"]
    by_work = {}
    for row in rerun_rows:
        by_work.setdefault((row["work_id"], row["version_id"]), []).append(row)
    passages = _accepted_passages(index, rerun_rows)
    source_rows = []
    for paper in index["papers"]:
        identity = (paper["work_id"], paper["version_id"])
        rows = by_work.get(identity, [])
        full = [
            row
            for row in rows
            if row["reading"]["status"] == "extracted"
            and row["reading"]["identity_status"] != "mismatch"
            and row["reading"]["evidence_level"] == "full-text"
            and row["reading"]["characters"] > 0
        ]
        abstract = [
            row
            for row in rows
            if row["reading"]["status"] == "extracted"
            and row["reading"]["identity_status"] != "mismatch"
            and row["reading"]["evidence_level"] == "abstract"
            and row["reading"]["characters"] > 0
        ]
        passage_ids = passages.get(identity, [])
        if full:
            availability, basis = "full-text-readable", "saved-rerun-full-text"
        elif abstract or passage_ids:
            availability = "abstract-only"
            basis = (
                "saved-rerun-abstract" if abstract else "accepted-supplement-passage"
            )
        elif any(row["reading"]["status"] == "failed-engineering" for row in rows):
            availability, basis = (
                "engineering-read-failure",
                "saved-rerun-engineering-failure",
            )
        else:
            availability, basis = "bibliography-only", "no-readable-body"
        source_rows.append(
            {
                "work_id": identity[0],
                "version_id": identity[1],
                "source_ids": [row["source_id"] for row in rows],
                "availability": availability,
                "availability_basis": basis,
                "readable": availability in {"full-text-readable", "abstract-only"},
                "supplement_passage_ids": passage_ids,
            }
        )
    _require(
        len(source_rows) == len(index["papers"]),
        "source availability lost a bibliography work",
    )
    source_by_work = {(row["work_id"], row["version_id"]): row for row in source_rows}
    claim_rows = []
    for claim in index["claims"]:
        source = source_by_work[(claim["work_id"], claim["version_id"])]
        claim_rows.append(
            {
                "claim_id": claim["claim_id"],
                "record_type": "original-claim",
                "work_id": claim["work_id"],
                "version_id": claim["version_id"],
                "original_assessment": claim.get("relation", claim.get("support")),
                "source_availability": source["availability"],
                "source_readable": source["readable"],
                "assessment_preserved": True,
                "availability_is_not_claim_assessment": True,
            }
        )
    if index.get("supplement", {}).get("status") == "accepted-scoped-private":
        for atom in index["supplement"]["data"].get("atomic_revisions", []):
            version_id = _atomic_version(index, atom, rerun_rows)
            source = (
                source_by_work.get((atom["work_id"], version_id))
                if version_id
                else None
            )
            claim_rows.append(
                {
                    "claim_id": atom["atom_id"],
                    "record_type": "accepted-atomic-revision",
                    "parent_claim_id": atom["parent_claim_id"],
                    "work_id": atom["work_id"],
                    "version_id": version_id,
                    "original_assessment": atom["assessment"],
                    "source_availability": source["availability"]
                    if source
                    else "version-unmapped",
                    "source_readable": source["readable"] if source else None,
                    "assessment_preserved": True,
                    "availability_is_not_claim_assessment": True,
                }
            )
    counts = {
        name: sum(row["availability"] == name for row in source_rows)
        for name in AVAILABILITY
    }
    counts.update(
        historical_bibliography=len(source_rows),
        readable=sum(row["readable"] for row in source_rows),
    )
    return {
        "kind": "WorkspaceSourceAvailability",
        "schema_version": "1.0.0",
        "counts": counts,
        "source_rows": source_rows,
        "claim_rows": claim_rows,
        "scientific_judgments_changed": False,
        "official_stage2_import_eligible": False,
    }
