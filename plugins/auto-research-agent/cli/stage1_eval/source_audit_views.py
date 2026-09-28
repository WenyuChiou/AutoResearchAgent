"""Deterministic, role-isolated audit views and inspectable submission manifests."""

from .common import EvaluationError, canonical, sha


_PASSAGE_IDENTITY_FIELDS = (
    "evidence_id",
    "artifact_sha256",
    "text_sha256",
    "source_version",
    "work_id",
    "origin",
    "view",
    "start",
    "end",
    "locator",
)
_PASSAGE_PROVENANCE_FIELDS = (
    "span_id",
    *_PASSAGE_IDENTITY_FIELDS,
    "level",
    "raw_source_sha256",
    "source_record_sha256",
    "version_alias",
)


def _passage_observation(passage):
    """Validate and retain every immutable source binding, but not source text."""
    required = {*_PASSAGE_PROVENANCE_FIELDS, "text"}
    if not isinstance(passage, dict) or required - set(passage):
        raise EvaluationError("source audit passage provenance is incomplete")
    identity = {key: passage[key] for key in _PASSAGE_IDENTITY_FIELDS}
    if passage["span_id"] != "span-" + sha(canonical(identity)):
        raise EvaluationError("source audit passage identity binding changed")
    for key in ("evidence_id", "source_version", "work_id", "origin", "view"):
        if not isinstance(passage[key], str) or not passage[key]:
            raise EvaluationError("source audit passage identity binding is invalid")
    if (
        not isinstance(passage["text"], str)
        or type(passage["start"]) is not int
        or type(passage["end"]) is not int
        or passage["start"] < 0
        or passage["end"] <= passage["start"]
        or len(passage["text"]) != passage["end"] - passage["start"]
    ):
        raise EvaluationError("source audit passage location is invalid")
    for key in ("artifact_sha256", "text_sha256"):
        value = passage[key]
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise EvaluationError("source audit passage hash binding is invalid")
    for key in ("raw_source_sha256", "source_record_sha256"):
        value = passage[key]
        if value is not None and (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise EvaluationError("source audit passage hash binding is invalid")
    if (
        passage["level"] not in {"metadata", "abstract", "full-text"}
        or not isinstance(passage["version_alias"], str)
        or not passage["version_alias"].endswith(
            ":" + sha(passage["source_version"].encode())[:12]
        )
    ):
        raise EvaluationError("source audit passage version binding is invalid")
    # Preserve future immutable fields by default. The source text remains available
    # through its evidence/span bindings and is intentionally not duplicated here.
    return {key: passage[key] for key in sorted(passage) if key != "text"}


def _observations(audits, work_ids=None):
    """Retain target/unit identity and all conclusions, without transport receipts."""
    if audits is None:
        return None
    selected = {}
    for role, audit in sorted(audits.items()):
        target_ids = [row["target"]["id"] for row in audit["summaries"]]
        unit_ids = [row["unit_id"] for row in audit["leaves"]]
        if (
            len(target_ids) != len(set(target_ids))
            or len(unit_ids) != len(set(unit_ids))
            or any(row["target_id"] not in target_ids for row in audit["leaves"])
        ):
            raise EvaluationError("source audit has duplicate or unbound obligations")
        summaries = [
            {key: row[key] for key in ("target", "verdict", "unknown_reason")}
            for row in audit["summaries"]
            if work_ids is None or work_ids.intersection(row["target"]["work_ids"])
        ]
        targets = {row["target"]["id"] for row in summaries}
        target_work_ids = {
            row["target"]["id"]: set(row["target"]["work_ids"]) for row in summaries
        }
        leaves = []
        for row in audit["leaves"]:
            if row["target_id"] not in targets:
                continue
            value = row["value"]
            if (
                value.get("verdict")
                not in {
                    "supported",
                    "partially-supported",
                    "contradicted",
                    "unverifiable",
                }
                or not isinstance(value.get("reason"), str)
                or not 1 <= len(value["reason"]) <= 400
                or not isinstance(value.get("passages"), list)
            ):
                raise EvaluationError("source audit leaf is invalid")
            passages = [_passage_observation(passage) for passage in value["passages"]]
            if any(
                passage["work_id"] not in target_work_ids[row["target_id"]]
                for passage in passages
            ):
                raise EvaluationError("source audit passage work binding changed")
            leaves.append(
                {
                    "unit_id": row["unit_id"],
                    "target_id": row["target_id"],
                    "value": {
                        "verdict": value["verdict"],
                        "reason": value["reason"],
                        "passages": passages,
                    },
                }
            )
        selected[role] = {
            "summaries": sorted(summaries, key=lambda row: row["target"]["id"]),
            "leaves": sorted(leaves, key=lambda row: row["unit_id"]),
            "score_awarded": False,
        }
    return selected


def _audit_manifest(audits, supplied, role, phase, prior):
    """Describe the exact supplied view, including unknowns and scope exclusions."""
    if role not in {"r1", "r2", "adj"}:
        raise EvaluationError("unknown complete judge role")
    expected = {"r1", "r2"} if role == "adj" else {role}
    if supplied is not None and set(supplied) != expected:
        raise EvaluationError("source audit role isolation violated")
    if role == "adj" and not prior:
        raise EvaluationError("source audit adjudication requires disagreement")
    views = {}
    for source_role, audit in (supplied or {}).items():
        targets = [row["target"]["id"] for row in audit["summaries"]]
        units = [row["unit_id"] for row in audit["leaves"]]
        original = audits[source_role]
        views[source_role] = {
            "target_ids": targets,
            "unit_ids": units,
            "unavailable_targets": [
                {"target_id": row["target"]["id"], "reason": row["unknown_reason"]}
                for row in audit["summaries"]
                if row["verdict"] == "unverifiable"
            ],
            "unavailable_unit_ids": [
                row["unit_id"]
                for row in audit["leaves"]
                if row["value"]["verdict"] == "unverifiable"
            ],
            "out_of_scope_target_ids": sorted(
                {row["target"]["id"] for row in original["summaries"]} - set(targets)
            ),
            "out_of_scope_unit_ids": sorted(
                {row["unit_id"] for row in original["leaves"]} - set(units)
            ),
            "supplied_view_sha256": sha(canonical(audit)),
            "omitted_target_ids": [],
            "omitted_unit_ids": [],
            "truncated": False,
        }
    return {
        "kind": "Stage1SourceAuditViewManifest.v1",
        "judge_role": role.upper(),
        "audit_source_roles": sorted(views),
        "state": "not-applicable"
        if phase == "process"
        else ("supplied" if supplied is not None else "unavailable"),
        "unavailable_reason": "source-audit-view-unavailable"
        if phase == "content" and supplied is None
        else None,
        "roles": views,
        "supplied_view_sha256": sha(canonical(supplied)),
        "omitted": False,
        "truncated": False,
    }
