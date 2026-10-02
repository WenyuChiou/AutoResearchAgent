"""Validated bibliography projection shared by Stage 2 report formats."""

import json

from jsonschema import Draft202012Validator

from stage2_common import Stage2Error, stage1_projection_hash
from stage2_common.contract import SCHEMA_PATHS
from stage2_ideation.report import _source_url


def build_bibliography(packet, snapshots, evidence):
    """Validate and project packet literature without inventing metadata."""
    if packet.get("schema_version") != "2.0.0":
        return {
            "available": False,
            "message": (
                "Structured bibliography is unavailable in this v1 packet: title, authors, "
                "year, venue, DOI, URL, origin, evidence level, and claim-specific roles "
                "are not recorded."
            ),
            "works": [],
            "by_evidence": {},
        }

    rows = packet.get("literature")
    if not isinstance(rows, list):
        raise Stage2Error("report-literature-missing")
    schema = json.loads(SCHEMA_PATHS["2.0.0"].read_text(encoding="utf-8"))
    validator = Draft202012Validator(
        {"$defs": schema["$defs"], "$ref": "#/$defs/literature"}
    )
    for row in rows:
        error = next(validator.iter_errors(row), None)
        if error is not None:
            raise Stage2Error(f"report-literature-schema: {error.message}")
    upstream = packet.get("upstream")
    stage1_rows = [row for row in rows if row.get("origin") == "stage1"]
    if not isinstance(upstream, dict) or upstream.get(
        "stage1_literature_sha256"
    ) != stage1_projection_hash(stage1_rows):
        raise Stage2Error("report-stage1-literature-binding-mismatch")

    seen_works = set()
    projected = []
    by_evidence = {}
    for row in rows:
        work_id = row.get("work_id")
        if row.get("origin") not in {"stage1", "stage2"}:
            raise Stage2Error(f"report-literature-origin-invalid: {work_id}")
        if work_id in seen_works:
            raise Stage2Error(f"report-duplicate-literature: {work_id}")
        seen_works.add(work_id)
        source_ids = row.get("source_ids")
        claim_ids = row.get("claim_ids")
        roles = row.get("roles")
        if (
            not isinstance(source_ids, list)
            or not source_ids
            or len(source_ids) != len(set(source_ids))
        ):
            raise Stage2Error(f"report-duplicate-literature-source: {work_id}")
        if not isinstance(claim_ids, list) or len(claim_ids) != len(set(claim_ids)):
            raise Stage2Error(f"report-duplicate-literature-claim: {work_id}")
        if not isinstance(roles, list):
            raise Stage2Error(f"report-literature-roles-invalid: {work_id}")

        work_sources = []
        for source_id in source_ids:
            source = snapshots.get(source_id)
            if source is None or any(
                source.get(field) != row.get(field)
                for field in ("work_id", "version_id", "origin")
            ):
                raise Stage2Error(
                    f"report-literature-source-binding-mismatch: {work_id}"
                )
            work_sources.append(
                {
                    "source_id": source_id,
                    "evidence_level": source.get("evidence_level"),
                    "path": source.get("path"),
                }
            )

        for claim_id in claim_ids:
            claim = evidence.get(claim_id)
            if (
                claim is None
                or any(
                    claim.get(field) != row.get(field)
                    for field in ("work_id", "version_id", "origin")
                )
                or claim.get("source_id") not in source_ids
            ):
                raise Stage2Error(
                    f"report-literature-claim-binding-mismatch: {work_id}"
                )

        role_names = set()
        projected_roles = []
        for role in roles:
            if not isinstance(role, dict):
                raise Stage2Error(f"report-literature-role-invalid: {work_id}")
            role_name = role.get("role")
            role_claim_ids = role.get("claim_ids")
            if role_name in role_names:
                raise Stage2Error(f"report-duplicate-literature-role: {work_id}")
            role_names.add(role_name)
            if (
                not isinstance(role_claim_ids, list)
                or not role_claim_ids
                or len(role_claim_ids) != len(set(role_claim_ids))
                or not set(role_claim_ids).issubset(claim_ids)
            ):
                raise Stage2Error(f"report-literature-role-claim-mismatch: {work_id}")
            projected_role = {
                "role": role_name,
                "reason": role.get("reason"),
                "claim_ids": list(role_claim_ids),
            }
            projected_roles.append(projected_role)
            for claim_id in role_claim_ids:
                by_evidence.setdefault(claim_id, []).append(projected_role)

        projected.append(
            {
                **row,
                "doi_href": _source_url(f"https://doi.org/{row['doi']}")
                if row.get("doi")
                else None,
                "url_href": _source_url(row.get("url")),
                "sources": work_sources,
                "claim_ids": list(claim_ids),
                "roles": projected_roles,
            }
        )
    projected.sort(key=lambda row: (row["work_id"], row["version_id"]))
    return {
        "available": True,
        "message": None,
        "works": projected,
        "by_evidence": by_evidence,
    }
