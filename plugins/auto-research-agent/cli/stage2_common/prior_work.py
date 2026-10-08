"""Candidate/source-bound validation for Stage 2 prior-work reviews."""

import copy
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath


def _require(condition, message, error_type):
    if not condition:
        raise error_type(message)


def _receipt_path(root, relative, error_type):
    _require(
        isinstance(relative, str), "prior-work receipt path must be text", error_type
    )
    posix = PurePosixPath(relative)
    windows = PureWindowsPath(relative)
    _require(
        not posix.is_absolute()
        and not windows.is_absolute()
        and windows.drive == ""
        and "\\" not in relative
        and relative == posix.as_posix()
        and all(part not in {"", ".", ".."} for part in posix.parts),
        f"prior-work receipt path must be portable and relative: {relative}",
        error_type,
    )
    root = Path(root).resolve()
    path = (root / Path(*posix.parts)).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise error_type(f"prior-work receipt path escapes root: {relative}") from error
    _require(path.is_file(), f"prior-work receipt missing: {relative}", error_type)
    return path


def _strict_json(raw, label, error_type):
    def pairs(values):
        result = {}
        for key, value in values:
            _require(
                key not in result,
                f"prior-work receipt duplicate key: {label}: {key}",
                error_type,
            )
            result[key] = value
        return result

    def reject_constant(value):
        raise error_type(f"prior-work receipt uses non-JSON constant: {label}: {value}")

    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise error_type(
            f"prior-work receipt is not strict UTF-8 JSON: {label}"
        ) from error


def source_set_hash(packet, canonical_hash):
    """Bind every source and evidence row without claiming scientific truth."""

    return canonical_hash(
        {"sources": packet["sources"], "evidence": packet["evidence"]}
    )


def validate_prior_work_reviews(packet, root, *, canonical_hash, error_type):
    """Validate current review identities, receipt bytes, and evidence bindings."""

    if packet.get("schema_version") != "2.4.0":
        return []
    reviews = packet["prior_work_reviews"]
    latest = {}
    for candidate in packet["candidates"]:
        current = latest.get(candidate["candidate_id"])
        if current is None or candidate["version"] > current["version"]:
            latest[candidate["candidate_id"]] = candidate
    review_ids = [row["candidate_id"] for row in reviews]
    _require(
        len(review_ids) == len(set(review_ids)),
        "duplicate prior-work candidate review",
        error_type,
    )
    literature = {
        (row["work_id"], row["version_id"]): row
        for row in [*packet["literature"], *packet["supplemental_literature"]]
    }
    evidence = {row["evidence_id"]: row for row in packet["evidence"]}
    sources = {row["source_id"]: row for row in packet["sources"]}
    expected_source_set = source_set_hash(packet, canonical_hash)
    for review in reviews:
        candidate = latest.get(review["candidate_id"])
        _require(
            candidate is not None,
            "prior-work review references unknown candidate",
            error_type,
        )
        _require(
            review["candidate_version"] == candidate["version"],
            "prior-work review is not for latest candidate version",
            error_type,
        )
        _require(
            review["candidate_sha256"] == canonical_hash(candidate),
            "prior-work candidate hash mismatch",
            error_type,
        )
        _require(
            review["source_set_sha256"] == expected_source_set,
            "prior-work source-set hash mismatch",
            error_type,
        )
        search_ids = [row["search_id"] for row in review["searches"]]
        _require(
            len(search_ids) == len(set(search_ids)),
            "duplicate prior-work search ID",
            error_type,
        )
        for search in review["searches"]:
            refs = [(row["work_id"], row["version_id"]) for row in search["work_refs"]]
            _require(
                len(refs) == len(set(refs)),
                "duplicate prior-work search work reference",
                error_type,
            )
            _require(
                set(refs).issubset(literature),
                "prior-work search references unknown work version",
                error_type,
            )
            if search["status"] == "planned":
                _require(
                    search["tool_ref"] is None
                    and search["raw_path"] is None
                    and search["raw_sha256"] is None
                    and search["outcome"] == "unknown"
                    and not search["work_refs"],
                    "planned prior-work search must remain uncaptured and unknown",
                    error_type,
                )
                continue
            _require(
                all(
                    search[field] is not None
                    for field in ("tool_ref", "raw_path", "raw_sha256")
                ),
                "executed or unavailable prior-work search requires captured receipt and tool reference",
                error_type,
            )
            if root is not None:
                path = _receipt_path(root, search["raw_path"], error_type)
                raw = path.read_bytes()
                _require(
                    hashlib.sha256(raw).hexdigest() == search["raw_sha256"],
                    "prior-work receipt hash mismatch",
                    error_type,
                )
                receipt = _strict_json(raw, search["raw_path"], error_type)
                _require(
                    isinstance(receipt, dict)
                    and set(receipt)
                    == {"query", "tool_ref", "outcome", "work_refs", "raw_output"},
                    "prior-work receipt shape mismatch",
                    error_type,
                )
                for field in ("query", "tool_ref", "outcome", "work_refs"):
                    _require(
                        receipt[field] == search[field],
                        f"prior-work receipt {field} mismatch",
                        error_type,
                    )
        comparison_keys = [
            (row["work_id"], row["version_id"]) for row in review["comparisons"]
        ]
        _require(
            len(comparison_keys) == len(set(comparison_keys)),
            "duplicate prior-work comparison work version",
            error_type,
        )
        for comparison in review["comparisons"]:
            key = (comparison["work_id"], comparison["version_id"])
            _require(
                key in literature,
                "prior-work comparison references unknown work version",
                error_type,
            )
            rows = []
            for evidence_id in comparison["evidence_ids"]:
                row = evidence.get(evidence_id)
                _require(
                    row is not None,
                    "prior-work comparison references unknown evidence",
                    error_type,
                )
                _require(
                    (row["work_id"], row["version_id"]) == key,
                    "prior-work comparison evidence belongs to another work version",
                    error_type,
                )
                source = sources.get(row["source_id"])
                _require(
                    source is not None,
                    "prior-work comparison evidence source is missing",
                    error_type,
                )
                rows.append((row, source))
            asserted = any(
                comparison[field].strip().casefold() != "unknown"
                for field in ("established", "overlap", "difference")
            )
            if asserted:
                _require(
                    all(
                        row.get("evidence_level", source.get("evidence_level"))
                        != "metadata"
                        and source.get("evidence_level") != "metadata"
                        for row, source in rows
                    ),
                    "prior-work comparison cannot promote metadata into method or finding evidence",
                    error_type,
                )
    return copy.deepcopy(reviews)


def current_prior_work_reviews(packet):
    """Return candidate-indexed reviews after all non-I/O bindings are rechecked."""

    if packet.get("schema_version") != "2.4.0":
        return {}
    from .contract import Stage2Error, canonical_hash

    reviews = validate_prior_work_reviews(
        packet, None, canonical_hash=canonical_hash, error_type=Stage2Error
    )
    return {row["candidate_id"]: row for row in reviews}
