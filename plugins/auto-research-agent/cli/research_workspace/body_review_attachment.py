"""Attach separately bound engineering evidence without changing source gates."""

from copy import deepcopy

from stage1_deliverable.common import DeliverableError, canonical, sha

from .body_review import SCOPE, verify_body_review
from .source_rerun import require


def body_review_key(row):
    return sha(
        canonical([row[name] for name in ("work_id", "version_id", "source_id")])
    )


def attach_body_reviews(rows, artifacts, artifact_hashes, expected_acceptance_hashes):
    expected = list(expected_acceptance_hashes or [])
    require(len(set(expected)) == len(expected), "duplicate body review acceptance")
    reviews = {}
    used = set()
    for row in rows:
        if not row.get("body_review"):
            require(
                not row.get("body_review_result_path"),
                "body review result lacks review",
            )
            continue
        digest = row["body_review"].get("acceptance_sha256")
        require(digest in expected, "explicit external body review acceptance required")
        evidence = verify_body_review(row, artifacts, digest)
        name = row.get("body_review_result_path")
        raw = canonical(evidence)
        require(
            name in artifact_hashes and artifacts.get(name) == raw,
            "body review result artifact differs",
        )
        require(
            artifact_hashes[name]["sha256"] == sha(raw),
            "body review result hash differs",
        )
        key = body_review_key(row)
        require(key not in reviews, "duplicate body review identity")
        reviews[key] = {"result_path": name, "evidence": evidence}
        used.add(digest)
    require(used == set(expected), "unused external body review acceptance")
    return reviews


def _validate_body_reviews(extension):
    rows = {
        body_review_key(row): row
        for row in extension["data"]["rows"]
        if row.get("body_review")
    }
    reviews = extension.get("body_reviews", {})
    require(isinstance(reviews, dict), "body review cache invalid")
    require(set(reviews) == set(rows), "body review cache membership differs")
    for key, cached in reviews.items():
        row = rows[key]
        require(
            set(cached) == {"result_path", "evidence"},
            "body review cache fields differ",
        )
        evidence = cached["evidence"]
        artifact = extension["artifact_hashes"].get(cached["result_path"], {})
        require(
            cached["result_path"] == row.get("body_review_result_path")
            and artifact.get("sha256") == sha(canonical(evidence))
            and artifact.get("bytes") == len(canonical(evidence)),
            "body review cache/result binding differs",
        )
        require(
            evidence["review_reference"] == row["body_review"]
            and evidence["acceptance_sha256"] == row["body_review"]["acceptance_sha256"]
            and evidence["manifest_sha256"] == row["body_review"]["manifest_sha256"],
            "body review reference differs",
        )
        binding = evidence["binding"]
        require(
            all(
                binding[name] == row[name]
                for name in (
                    "work_id",
                    "source_id",
                    "version_id",
                    "source_version",
                    "attempt_id",
                    "raw_sha256",
                )
            )
            and binding["reading_sha256"] == sha(canonical(row["reading"]))
            and binding["text_sha256"] == row["reading"]["text_sha256"]
            and evidence["current_diagnostics"] == row["reading"]["diagnostics"],
            "body review source/reading differs",
        )
        require(
            all(
                extension["artifact_hashes"].get(name, {}).get("sha256") == digest
                for name, digest in evidence["artifact_bindings"].items()
            ),
            "body review artifact binding differs",
        )
        require(
            evidence["scope"] == SCOPE
            and evidence["formal_eligibility_override"] is False
            and evidence["reviewer_identity_authenticated"] is False
            and evidence["official_stage2_import_eligible"] is False
            and evidence["research_execution"] is False
            and evidence["quality_score"] is None
            and evidence["scientific_claim_adequacy"] == "not-assessed",
            "body review cannot promote eligibility, identity, claims or execution",
        )
    return deepcopy(reviews)


def validate_body_reviews(extension):
    try:
        return _validate_body_reviews(extension)
    except (KeyError, TypeError, AttributeError) as error:
        raise DeliverableError(
            "body review cache: malformed supplied evidence"
        ) from error
