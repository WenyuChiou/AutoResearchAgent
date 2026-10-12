"""Derive a conservative, read-only technical source selection.

Selection is a view over a validated workspace index.  It does not repair source
records, reassess claims, execute research, or promote a Stage 2 import.
"""

from copy import deepcopy
import json
import re

from stage1_deliverable.common import DeliverableError, canonical, sha
from stage1_deliverable.views import csv_bytes, workbook_bytes

from .body_completeness import assess_body_completeness
from .whole_source_review import review_key, reviewed_body_completeness


RULE_VERSION = "1.1.0"
_SHA256 = re.compile(r"[0-9a-f]{64}")


class _HeaderOnly:
    """Supply workbook headers without inventing a data identity."""

    def __init__(self, headers):
        self.headers = dict.fromkeys(headers, "")

    def __getitem__(self, position):
        if position == 0:
            return self.headers
        raise IndexError(position)

    def __iter__(self):
        return iter(())


def _require(condition, message):
    if not condition:
        raise DeliverableError(message)


def _unique(values):
    return list(dict.fromkeys(values))


def _selected_attempt(row):
    return next(
        (
            attempt
            for attempt in row["original_attempts"]
            if attempt["sequence"] == row.get("selected_sequence")
        ),
        None,
    )


def _diagnostic_reasons(row):
    diagnostics = row["reading"].get("diagnostics") or {}
    reasons = []
    if diagnostics.get("omitted_pages"):
        reasons.append("source-pages-omitted")
    if diagnostics.get("truncated") is True:
        reasons.append("source-truncated")
    if (
        diagnostics.get("incomplete") not in (None, False, "", [], {}, 0)
        or diagnostics.get("complete") is False
    ):
        reasons.append("source-incomplete")
    for key, value in diagnostics.items():
        if key.startswith("omitted_") and key != "omitted_pages" and value:
            reasons.append("source-omission:" + key)
        if key.startswith("incomplete_") and value:
            reasons.append("source-incomplete:" + key)
    return _unique(reasons)


def _binding(row, artifacts, body_reviews=None, source_reviews=None):
    """Return the exact current binding and reject a forged admissible row."""
    from .body_review_attachment import body_review_key

    reading = row["reading"]
    raw_path = row.get("raw_path")
    text_path = row.get("extracted_path")
    raw_hash = row.get("raw_sha256")
    text_hash = reading.get("text_sha256")
    if reading["status"] == "extracted" and reading["evidence_level"] == "full-text":
        _require(
            raw_path
            and text_path
            and isinstance(raw_hash, str)
            and _SHA256.fullmatch(raw_hash)
            and isinstance(text_hash, str)
            and _SHA256.fullmatch(text_hash),
            "full-text selection binding incomplete",
        )
        _require(
            row.get("source_version") == "sha256:" + raw_hash,
            "full-text source version differs",
        )
        _require(
            artifacts.get(raw_path, {}).get("sha256") == raw_hash
            and artifacts.get(text_path, {}).get("sha256") == text_hash,
            "full-text selection artifact hash differs",
        )
        _require(reading["locators"], "full-text selection locator missing")
    return {
        "source_id": row["source_id"],
        "attempt_id": row["attempt_id"],
        "source_version": row.get("source_version"),
        "raw_path": raw_path,
        "raw_sha256": raw_hash,
        "extracted_path": text_path,
        "text_sha256": text_hash,
        "reading_status": reading["status"],
        "evidence_level": reading["evidence_level"],
        "identity_status": reading["identity_status"],
        "characters": reading["characters"],
        "locators": deepcopy(reading["locators"]),
        "diagnostics": deepcopy(reading.get("diagnostics") or {}),
        "body_completeness": assess_body_completeness(row),
        **(
            {
                "reviewed_body_completeness": reviewed_body_completeness(
                    row, source_reviews
                ),
                "whole_source_review_reference": deepcopy(row["whole_source_review"]),
            }
            if review_key(row) in (source_reviews or {})
            else {}
        ),
        **(
            {
                "independent_body_review": deepcopy(
                    body_reviews[body_review_key(row)]["evidence"]
                )
            }
            if body_review_key(row) in (body_reviews or {})
            else {}
        ),
        "error": deepcopy(reading.get("error")),
        "metadata": deepcopy(row.get("metadata") or {}),
        "metadata_provenance": deepcopy(row.get("metadata_provenance") or {}),
        "failure_reasons": _source_reasons(row, source_reviews),
    }


def _source_reasons(row, source_reviews=None):
    reading = row["reading"]
    reasons = _diagnostic_reasons(row)
    if (
        reading["identity_status"] == "mismatch"
        or reading["status"] == "identity-mismatch"
    ):
        reasons.append("identity-mismatch")
    elif reading["identity_status"] == "unverified":
        reasons.append("identity-unverified")

    selected = _selected_attempt(row)
    if selected and selected.get("response_truncated") is True:
        reasons.append("source-truncated")
    if reading["status"] == "inaccessible":
        reasons.append("inaccessible")
    elif reading["status"] == "failed-engineering":
        reasons.append("broken-parser")
    elif reading["status"] == "not-attempted-no-saved-response":
        reasons.append("source-incomplete")
    elif reading["status"] in {"extracted", "identity-mismatch"}:
        if reading["evidence_level"] == "abstract":
            reasons.append("abstract-only")
        elif reading["evidence_level"] == "metadata":
            reasons.append("metadata-only")
        elif reading["evidence_level"] == "full-text":
            reasons.extend(reviewed_body_completeness(row, source_reviews)["reasons"])
    return _unique(reasons)


def _eligible(row, source_reviews=None):
    reading = row["reading"]
    selected = _selected_attempt(row)
    return (
        reading["status"] == "extracted"
        and reading["evidence_level"] == "full-text"
        and reading["identity_status"] in {"consistent", "verified"}
        and reading["characters"] > 0
        and bool(reading["locators"])
        and selected is not None
        and selected.get("response_truncated") is False
        and not _diagnostic_reasons(row)
        and reviewed_body_completeness(row, source_reviews)["status"] == "confirmed"
    )


def _pending_source_review(row):
    reading = row["reading"]
    body = assess_body_completeness(row)
    return (
        reading["identity_status"] in {"consistent", "verified", "unverified"}
        and reading["status"] == "extracted"
        and reading["evidence_level"] == "full-text"
        and reading["characters"] > 0
        and bool(reading["locators"])
        and (_selected_attempt(row) or {}).get("response_truncated") is False
        and not _diagnostic_reasons(row)
        and body["status"] != "incomplete"
        and (reading["identity_status"] == "unverified" or body["status"] == "pending")
    )


def derive_literature_selection(index):
    """Return one conservative selection row per exact work/version identity."""
    from .projection import validate_index

    validate_index(index)
    input_hash = sha(canonical(index))
    version = index["schema_version"]
    rerun = index.get("source_rerun") if version == "3.0.0" else None
    rerun_rows = rerun["data"]["rows"] if rerun else []
    artifacts = rerun["artifact_hashes"] if rerun else {}
    body_reviews = rerun.get("body_reviews", {}) if rerun else {}
    source_reviews = rerun.get("whole_source_reviews", {}) if rerun else {}
    by_identity = {}
    for source in rerun_rows:
        by_identity.setdefault((source["work_id"], source["version_id"]), []).append(
            source
        )

    rows = []
    for paper in index["papers"]:
        identity = (paper["work_id"], paper["version_id"])
        sources = by_identity.get(identity, [])
        _require(
            all(
                source["source_id"] in paper.get("source_ids", []) for source in sources
            ),
            "rerun source is outside canonical paper membership",
        )
        bindings = [
            _binding(source, artifacts, body_reviews, source_reviews)
            for source in sources
        ]
        eligible = [
            source["source_id"]
            for source in sources
            if _eligible(source, source_reviews)
        ]
        reasons = _unique(
            reason
            for source in sources
            for reason in _source_reasons(source, source_reviews)
        )
        if eligible:
            status = "included"
            reasons = ["readable-full-text-identity-confirmed"]
        elif not rerun or not sources:
            status, reasons = "pending", ["pending-source-review"]
        elif any(_pending_source_review(source) for source in sources):
            status = "pending"
        else:
            status = "excluded"
        rows.append(
            {
                "work_id": paper["work_id"],
                "version_id": paper["version_id"],
                "citation_key": "work_" + sha(canonical(identity)),
                "source_ids": list(paper.get("source_ids", [])),
                "eligible_source_ids": eligible,
                "status": status,
                "reasons": reasons or ["source-incomplete"],
                "source_binding_references": bindings,
            }
        )

    identities = [
        {"work_id": row["work_id"], "version_id": row["version_id"]} for row in rows
    ]
    counts = {
        "screened": len(rows),
        "included": sum(row["status"] == "included" for row in rows),
        "excluded": sum(row["status"] == "excluded" for row in rows),
        "pending": sum(row["status"] == "pending" for row in rows),
    }
    _require(
        sum(counts[name] for name in ("included", "excluded", "pending"))
        == counts["screened"],
        "selection counts differ",
    )
    return {
        "kind": "WorkspaceLiteratureSelection",
        "schema_version": "1.0.0",
        "rule_version": "1.2.0" if source_reviews else RULE_VERSION,
        "input_canonical_sha256": input_hash,
        "counts": counts,
        "included_identities": [
            identity
            for identity, row in zip(identities, rows)
            if row["status"] == "included"
        ],
        "screening_identities": identities,
        "rows": rows,
        "claim_assessments_changed": False,
        "coverage_complete": False,
        "official_stage2_import_eligible": False,
        "research_execution": False,
    }


def _table_rows(rows):
    return [
        {
            **row,
            "source_ids": json.dumps(row["source_ids"], ensure_ascii=False),
            "eligible_source_ids": json.dumps(
                row["eligible_source_ids"], ensure_ascii=False
            ),
            "reasons": json.dumps(row["reasons"], ensure_ascii=False),
            "source_binding_references": json.dumps(
                row["source_binding_references"], ensure_ascii=False, sort_keys=True
            ),
        }
        for row in rows
    ]


def _selection_workbook_tables(selection):
    """Keep long bindings in the complete JSON and expose page checks as rows."""
    rows = _table_rows(selection["rows"])
    pages = []
    for original, row in zip(selection["rows"], rows):
        for binding in original["source_binding_references"]:
            review = binding.get("reviewed_body_completeness", {})
            reference = binding.get("whole_source_review_reference", {})
            for page in review.get("extracted_page_checks", []):
                pages.append(
                    {
                        "work_id": original["work_id"],
                        "version_id": original["version_id"],
                        "source_id": binding["source_id"],
                        "attempt_id": binding["attempt_id"],
                        "raw_sha256": binding["raw_sha256"],
                        "text_sha256": binding["text_sha256"],
                        "manifest_path": reference["manifest_path"],
                        "manifest_sha256": reference["manifest_sha256"],
                        "acceptance_sha256": reference["acceptance_sha256"],
                        "page": page["page"],
                        "fidelity_status": page["fidelity_status"],
                        "reading_order_status": page["reading_order_status"],
                        "limitations": json.dumps(
                            page["limitations"], ensure_ascii=False
                        ),
                    }
                )
        if len(row["source_binding_references"].encode("utf-16-le")) // 2 > 32767:
            row["source_binding_references"] = json.dumps(
                {
                    "path": "literature/selection.json",
                    "sha256": sha(canonical(selection)),
                    "work_id": original["work_id"],
                    "version_id": original["version_id"],
                    "field": "source_binding_references",
                    "complete_binding_count": len(
                        original["source_binding_references"]
                    ),
                    "page_checks_sheet": "SourceReviewPages" if pages else None,
                    "content_truncated": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
    tables = {"Selection": rows}
    if pages:
        tables["SourceReviewPages"] = pages
    return tables


def selection_files(index):
    """Render deterministic bytes for the formal literature selection view."""
    index = json.loads(canonical(index))
    selection = derive_literature_selection(index)
    selected = {
        (row["work_id"], row["version_id"])
        for row in selection["rows"]
        if row["status"] == "included"
    }
    papers = {
        (paper["work_id"], paper["version_id"]): paper for paper in index["papers"]
    }
    bibliography = index.get("source_rerun", {}).get(
        "bibliography", index["bibliography"]
    )
    entry_map = {
        (entry["work_id"], entry["version_id"]): entry
        for entry in bibliography["entries"]
    }
    _require(set(papers) == set(entry_map), "screening bibliography identity missing")
    versioned_entries = {}
    for row in selection["rows"]:
        identity = (row["work_id"], row["version_id"])
        entry, count = re.subn(
            r"(@[A-Za-z]+\{)[^,\r\n]+,",
            lambda match: match[1] + row["citation_key"] + ",",
            entry_map[identity]["bibtex"].rstrip(),
            count=1,
        )
        _require(count == 1, "bibliography citation key missing")
        versioned_entries[identity] = entry
    included_bib = "\n".join(
        versioned_entries[identity] for identity in papers if identity in selected
    )
    if included_bib:
        included_bib += "\n"
    screening_bib = "\n".join(versioned_entries[identity] for identity in papers)
    if screening_bib:
        screening_bib += "\n"

    rows = _table_rows(selection["rows"])
    included_rows = [papers[key] for key in papers if key in selected]
    screening_rows = [papers[key] for key in papers]
    included_table = included_rows or _HeaderOnly(
        ("work_id", "version_id", "title", "source_ids")
    )
    screening_table = screening_rows or _HeaderOnly(
        ("work_id", "version_id", "title", "source_ids")
    )
    selection_table = rows or _HeaderOnly(
        (
            "work_id",
            "version_id",
            "citation_key",
            "source_ids",
            "eligible_source_ids",
            "status",
            "reasons",
            "source_binding_references",
        )
    )
    markdown = [
        "# Source selection",
        "",
        "Read-only selection from validated work/version/source bindings. Claim assessments and coverage remain unchanged.",
        "",
        f"Technically eligible versions: {selection['counts']['included']}; excluded: {selection['counts']['excluded']}; pending: {selection['counts']['pending']}. These counts do not certify formal admission.",
        "",
    ]
    for row in selection["rows"]:
        markdown.append(
            f"- `{row['work_id']}@{row['version_id']}` — {row['status']}: "
            + ", ".join(row["reasons"])
        )
    markdown.append("")
    workbook_tables = _selection_workbook_tables(selection)
    workbook_tables["Selection"] = workbook_tables["Selection"] or selection_table
    return {
        "literature/selection.json": canonical(selection),
        "literature/selection.csv": csv_bytes("Selection", selection_table),
        "literature/included.bib": included_bib.encode("utf-8"),
        "literature/screening.bib": screening_bib.encode("utf-8"),
        "literature/selection.md": "\n".join(markdown).encode("utf-8"),
        "literature/catalog.xlsx": workbook_bytes(
            {
                "Included": included_table,
                "Screening": screening_table,
                **workbook_tables,
            }
        ),
    }
