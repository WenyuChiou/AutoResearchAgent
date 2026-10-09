"""Bind a separately accepted PDF body review without rewriting diagnostics.

This carrier resolves reviewed technical body uncertainty only. Formal
admission, claim support, coverage and execution still use their own gates.
The existing engineering-only body_review carrier retains its original scope.
"""

from copy import deepcopy
import json
import re

from stage1_deliverable.common import DeliverableError, canonical, sha

from .body_completeness import assess_body_completeness


SCOPE = "whole-pdf-source-body-and-reading-order"
_REPRESENTATIONS = {"extracted-text", "rendered-raw-with-extracted-text"}
_HASH = re.compile(r"[0-9a-f]{64}")
_RESOLVABLE = {
    "extraction-fidelity-unreviewed",
    "reading-order-unreviewed",
    "pdf-geometry-fallback-unreviewed",
}
_FENCE = {
    "formal_admission": False,
    "claim_assessments_changed": False,
    "official_stage2_import_eligible": False,
    "research_execution": False,
    "quality_score": None,
    "reviewer_identity_authenticated": False,
}


def _require(condition, message):
    if not condition:
        raise DeliverableError("whole source review: " + message)


def review_key(row):
    return sha(
        canonical([row[name] for name in ("work_id", "version_id", "source_id")])
    )


def source_binding(row):
    return {
        **{
            name: row[name]
            for name in (
                "work_id",
                "version_id",
                "source_id",
                "source_version",
                "attempt_id",
                "raw_sha256",
            )
        },
        "text_sha256": row["reading"]["text_sha256"],
        "reading_sha256": sha(canonical(row["reading"])),
    }


def _source_ready(row):
    reading = row["reading"]
    selected = next(
        (
            a
            for a in row["original_attempts"]
            if a["sequence"] == row.get("selected_sequence")
        ),
        None,
    )
    _require(
        reading["status"] == "extracted"
        and reading["evidence_level"] == "full-text"
        and reading["identity_status"] in {"consistent", "verified"}
        and selected is not None
        and selected.get("response_truncated") is False,
        "source status, identity or acquisition is ineligible",
    )
    body = assess_body_completeness(row)
    _require(
        body["status"] in {"confirmed", "pending"}
        and set(body["reasons"]) <= _RESOLVABLE,
        "review cannot resolve incomplete or missing extent proof",
    )
    diagnostics = reading["diagnostics"]
    fidelity = diagnostics.get("extraction_fidelity", "")
    order = diagnostics.get("reading_order")
    _require(
        diagnostics.get("truncated") is not True
        and diagnostics.get("complete") is not False
        and diagnostics.get("incomplete") in (None, False, "", [], {}, 0)
        and not any(
            value and (name.startswith("omitted_") or name.startswith("incomplete_"))
            for name, value in diagnostics.items()
        )
        and not (isinstance(fidelity, str) and "incomplete" in fidelity.casefold())
        and (
            order is None
            or (
                isinstance(order, dict)
                and order.get("status") in {"pending", "confirmed", "not-applicable"}
            )
        ),
        "review cannot resolve source omissions or truncation",
    )
    total = diagnostics.get("pages_total")
    _require(type(total) is int and total > 0, "PDF page extent required")
    _require(
        row.get("source_version") == "sha256:" + row["raw_sha256"]
        and all(
            _HASH.fullmatch(source_binding(row)[name])
            for name in ("raw_sha256", "text_sha256", "reading_sha256")
        ),
        "source hashes or source version invalid",
    )
    return total


def _fence(document):
    _require(
        all(document.get(key) is value for key, value in _FENCE.items()),
        "review cannot promote admission, claims, import, identity or execution",
    )


def _validate(row, cached, hashes):
    total = _source_ready(row)
    reference = row["whole_source_review"]
    _require(
        set(reference)
        == {"manifest_path", "manifest_sha256", "acceptance_path", "acceptance_sha256"},
        "reference fields differ",
    )
    _require(
        set(cached) == {"reference", "manifest", "acceptance", "render_proof"}
        and cached["reference"] == reference,
        "cache reference differs",
    )
    manifest, acceptance = cached["manifest"], cached["acceptance"]
    representation = manifest.get("representation")
    _require(
        representation in _REPRESENTATIONS, "source reading representation invalid"
    )
    for document, label in ((manifest, "manifest"), (acceptance, "acceptance")):
        raw = canonical(document)
        artifact = hashes.get(reference[label + "_path"], {})
        _require(
            sha(raw) == reference[label + "_sha256"]
            and artifact.get("sha256") == sha(raw)
            and artifact.get("bytes") == len(raw),
            label + " byte/hash binding differs",
        )
        _require(
            document.get("schema_version") == "1.0.0"
            and document.get("scope") == SCOPE
            and document.get("binding") == source_binding(row),
            label + " scope or source/reading binding differs",
        )
        _fence(document)
    _require(manifest.get("kind") == "Stage1WholeSourceReview", "manifest kind differs")
    _require(
        acceptance.get("kind") == "Stage1WholeSourceReviewAcceptance"
        and acceptance.get("manifest_sha256") == reference["manifest_sha256"]
        and acceptance.get("decision") == "accepted"
        and acceptance.get("unresolved_material_defects") == [],
        "acceptance is not a complete accepted review",
    )
    for document in (manifest, acceptance):
        _require(
            isinstance(document.get("reviewer_id"), str)
            and bool(document["reviewer_id"].strip())
            and isinstance(document.get("evidence_refs"), list)
            and bool(document["evidence_refs"]),
            "reviewer provenance or evidence missing",
        )
    _require(
        manifest.get("unresolved_material_defects") == [],
        "material source defect unresolved",
    )
    limitations = manifest.get("limitations")
    _require(
        isinstance(limitations, list)
        and all(isinstance(item, str) and item.strip() for item in limitations),
        "limitations must be explicitly declared",
    )
    pages = manifest.get("page_reviews")
    _require(
        isinstance(pages, list)
        and len(pages) == total
        and all(isinstance(item, dict) for item in pages)
        and [item.get("page") for item in pages] == list(range(1, total + 1))
        and all(type(item["page"]) is int for item in pages),
        "complete ordered page review required",
    )
    references = list(manifest["evidence_refs"]) + list(acceptance["evidence_refs"])
    for page in pages:
        locator = next(
            item
            for item in row["reading"]["locators"]
            if item.get("type") == "pdf-page" and item["value"] == page["page"]
        )
        _require(
            all(
                page.get(key) is True
                for key in ("body_checked", "reading_order_checked", "fidelity_checked")
            )
            and all(
                page.get(key) == "confirmed"
                for key in ("body_status", "reading_order_status", "fidelity_status")
            )
            and isinstance(page.get("evidence_refs"), list)
            and bool(page["evidence_refs"]),
            "page body/order/fidelity review incomplete",
        )
        _require(
            type(page.get("start")) is int
            and type(page.get("end")) is int
            and page.get("start") == locator["start"]
            and page.get("end") == locator["end"]
            and isinstance(page.get("text_sha256"), str)
            and _HASH.fullmatch(page["text_sha256"]) is not None
            and isinstance(page.get("render_path"), str)
            and isinstance(page.get("render_sha256"), str)
            and _HASH.fullmatch(page["render_sha256"]) is not None,
            "page text extent or rendered evidence missing",
        )
        references.extend(page["evidence_refs"])
        _require(
            page.get("extracted_fidelity_status")
            in {"confirmed", "partial", "failed", "pending"}
            and page.get("extracted_reading_order_status")
            in {"confirmed", "partial", "failed", "pending"}
            and isinstance(page.get("limitations"), list)
            and all(
                isinstance(item, str) and item.strip() for item in page["limitations"]
            ),
            "extracted text status or limitations missing",
        )
        if representation == "extracted-text":
            _require(
                page["extracted_fidelity_status"] == "confirmed"
                and page["extracted_reading_order_status"] == "confirmed",
                "extracted representation has unresolved text fidelity/order",
            )
        elif (
            page["extracted_fidelity_status"] != "confirmed"
            or page["extracted_reading_order_status"] != "confirmed"
        ):
            _require(
                bool(page["limitations"]),
                "raw representation must disclose text defects",
            )
    bindings = manifest.get("artifact_bindings")
    _require(isinstance(bindings, dict), "artifact bindings missing")
    _require(
        bindings.get(row["raw_path"]) == row["raw_sha256"]
        and bindings.get(row["extracted_path"]) == row["reading"]["text_sha256"],
        "raw/text artifact bindings missing",
    )
    _require(
        all(isinstance(name, str) and name in bindings for name in references),
        "review evidence reference unbound",
    )
    for name, digest in bindings.items():
        _require(
            isinstance(name, str)
            and isinstance(digest, str)
            and _HASH.fullmatch(digest) is not None
            and hashes.get(name, {}).get("sha256") == digest,
            "review artifact binding differs",
        )
    _require(
        all(
            bindings.get(page["render_path"]) == page["render_sha256"] for page in pages
        ),
        "page render evidence unbound",
    )
    proof = cached["render_proof"]
    proof_ref = manifest.get("render_proof", {})
    _require(
        set(proof_ref) == {"path", "sha256"}
        and bindings.get(proof_ref["path"]) == proof_ref["sha256"]
        and sha(canonical(proof)) == proof_ref["sha256"],
        "render reproduction proof unbound",
    )
    _require(
        proof.get("kind") == "PDFRenderReproductionCheck"
        and proof.get("schema_version") == "1.0.0"
        and proof.get("raw_sha256") == row["raw_sha256"]
        and proof.get("pages")
        == [
            {
                "page": page["page"],
                "path": page["render_path"],
                "sha256": page["render_sha256"],
                "matches_raw_render": True,
            }
            for page in pages
        ]
        and isinstance(proof.get("renderer"), dict)
        and all(
            isinstance(proof["renderer"].get(key), str)
            and proof["renderer"][key].strip()
            for key in (
                "name",
                "version",
                "program_path",
                "program_sha256",
                "runtime_path",
                "runtime_sha256",
            )
        ),
        "complete raw render reproduction proof required",
    )
    renderer = proof["renderer"]
    _require(
        all(
            bindings.get(renderer[label + "_path"]) == renderer[label + "_sha256"]
            for label in ("program", "runtime")
        ),
        "renderer program/runtime artifacts unbound",
    )
    return cached


def attach_whole_source_reviews(rows, artifacts, hashes, expected_acceptance_hashes):
    """Verify original bytes and an externally pinned acceptance for each review."""
    expected = list(expected_acceptance_hashes or [])
    _require(len(expected) == len(set(expected)), "duplicate external acceptance")
    used, cache = set(), {}
    try:
        for row in rows:
            if "whole_source_review" not in row:
                continue
            reference = row["whole_source_review"]
            digest = reference["acceptance_sha256"]
            _require(digest in expected, "explicit external acceptance required")
            documents = {}
            for label in ("manifest", "acceptance"):
                raw = artifacts[reference[label + "_path"]]
                document = json.loads(raw)
                _require(
                    raw == canonical(document), "review JSON must use canonical bytes"
                )
                documents[label] = document
            proof_raw = artifacts[documents["manifest"]["render_proof"]["path"]]
            proof = json.loads(proof_raw)
            _require(
                proof_raw == canonical(proof),
                "render proof JSON must use canonical bytes",
            )
            documents["render_proof"] = proof
            cached = {"reference": deepcopy(reference), **documents}
            _validate(row, cached, hashes)
            for name, bound in documents["manifest"]["artifact_bindings"].items():
                _require(sha(artifacts[name]) == bound, "review artifact bytes differ")
            text = artifacts[row["extracted_path"]].decode("utf-8")
            for page in documents["manifest"]["page_reviews"]:
                _require(
                    sha(text[page["start"] : page["end"]].encode("utf-8"))
                    == page["text_sha256"],
                    "page text slice differs",
                )
            key = review_key(row)
            _require(key not in cache, "duplicate review source/version")
            cache[key] = cached
            used.add(digest)
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        raise DeliverableError(
            "whole source review: malformed supplied evidence"
        ) from error
    _require(used == set(expected), "unused external acceptance")
    return cache


def validate_whole_source_reviews(extension):
    """Revalidate immutable cached evidence on every workspace projection."""
    try:
        rows = [
            row for row in extension["data"]["rows"] if "whole_source_review" in row
        ]
        cache = extension.get("whole_source_reviews", {})
        _require(isinstance(cache, dict), "cache invalid")
        keys = [review_key(row) for row in rows]
        _require(
            len(keys) == len(set(keys)) and set(cache) == set(keys),
            "cache membership differs",
        )
        for row in rows:
            _validate(row, cache[review_key(row)], extension["artifact_hashes"])
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        raise DeliverableError(
            "whole source review: malformed cached evidence"
        ) from error
    return deepcopy(cache)


def reviewed_body_completeness(row, reviews=None):
    """Use an already validated review while retaining the automatic assessment."""
    original = assess_body_completeness(row)
    if not reviews:
        return original
    review = (reviews or {}).get(review_key(row))
    if review is None:
        return original
    _require(
        review["manifest"]["binding"] == source_binding(row),
        "effective review binding differs",
    )
    page_checks = [
        {
            "page": page["page"],
            "fidelity_status": page["extracted_fidelity_status"],
            "reading_order_status": page["extracted_reading_order_status"],
            "limitations": deepcopy(page["limitations"]),
        }
        for page in review["manifest"]["page_reviews"]
    ]
    limitations = deepcopy(review["manifest"]["limitations"])
    for page in page_checks:
        limitations.extend(
            f"Page {page['page']}: {limitation}" for limitation in page["limitations"]
        )
    return {
        "status": "confirmed",
        "reasons": [],
        "basis": "externally-accepted-whole-source-review",
        "representation": review["manifest"]["representation"],
        "acceptance_sha256": review["reference"]["acceptance_sha256"],
        "automatic_assessment": original,
        "limitations": limitations,
        "extracted_page_checks": page_checks,
    }
