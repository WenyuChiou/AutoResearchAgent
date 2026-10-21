"""Read-only academic decisions; independent of source eligibility and claims."""

from copy import deepcopy
import html
import json

from stage1_deliverable.common import canonical, sha
from stage1_deliverable.views import csv_bytes, workbook_bytes

JSON_PATH = "literature/academic_screening.json"
CONTRACT_VERSION = "S1-SCREENING-READMODEL-1.2.0"


def derive_academic_screening(index, *, include_original_records=True):
    """Preserve recorded decisions without assessing their scientific adequacy."""
    from .projection import validate_index

    validate_index(index)
    library = (
        index.get("screening_library") if index["schema_version"] == "1.2.0" else None
    )
    library_rows = (
        {r["work_id"]: (n, r) for n, r in enumerate(library["rows"])} if library else {}
    )
    rows, events = [], []
    for paper in index["papers"]:
        work, version = paper["work_id"], paper["version_id"]
        if library:
            number, bound = library_rows[work]
            originals = [
                (e, f"/screening_library/rows/{number}/decision_history/{n}")
                for n, e in enumerate(bound["decision_history"])
            ]
            scope = "work"
            status = bound["screening_status"]
            current = bound["current_decision"]
            current_review = deepcopy(bound["current_review"])
        else:
            originals = [
                (e, f"/screening/{n}")
                for n, e in enumerate(index["screening"])
                if (e.get("work_id"), e.get("version_id")) == (work, version)
            ]
            scope = "recorded-work-version"
            current = originals[-1][0] if originals else None
            status = current.get("status", "Unknown") if current else "Unknown"
            current_review = None
        raw_history = [deepcopy(e) for e, _ in originals]
        reason_field = "rationale" if library else "reason"
        reason = current.get(reason_field) if current else None
        rows.append(
            dict(
                work_id=work,
                current_display_version_id=version,
                academic_status=status,
                decision_scope=scope,
                decision_version_id=None if library else version,
                recorded_vs_missing="recorded"
                if originals
                else ("not-screened" if library else "missing"),
                decision_event_count=len(originals)
                if originals or library
                else "Unknown",
                current_decision=deepcopy(current),
                raw_history=raw_history if originals or library else None,
                current_review=current_review,
                reason=reason,
                reason_recorded=bool(current is not None and reason_field in current),
                reason_nonempty=isinstance(reason, str) and bool(reason.strip()),
                scientific_assessment=False,
            )
        )
        for order, (original, pointer) in enumerate(originals):
            events.append(
                dict(
                    work_id=work,
                    current_display_version_id=version,
                    decision_scope=scope,
                    decision_version_id=None if library else original.get("version_id"),
                    order_in_work=order + 1,
                    decision_id=original.get("event_id" if library else "decision_id"),
                    academic_status=original.get(
                        "new_decision" if library else "status", "Unknown"
                    ),
                    reason_code=original.get("reason_code"),
                    reason=original.get(reason_field),
                    observed_at=original.get(
                        "created_at" if library else "observed_at"
                    ),
                    pointer=pointer,
                    original_event=deepcopy(original),
                    scientific_assessment=False,
                )
            )
    reason_works = {}
    for row in rows:
        if row["reason_nonempty"]:
            reason_works.setdefault(row["reason"], set()).add(row["work_id"])
    for row in rows:
        row["reason_shared_work_count"] = (
            len(reason_works[row["reason"]]) if row["reason_nonempty"] else "Unknown"
        )
        stated_unknown = row["reason_nonempty"] and row[
            "reason"
        ].strip().casefold().startswith(
            ("unknown", "unverified", "not independently assessed")
        )
        status_only = row["reason_nonempty"] and row["reason"].strip().casefold() in {
            "include",
            "included",
            "exclude",
            "excluded",
            "pending",
            "not-screened",
            "unverifiable",
        }
        row["reason_review_required"] = (
            not row["reason_nonempty"]
            or stated_unknown
            or status_only
            or row["reason_shared_work_count"] != 1
        )
        row["reason_issues"] = (
            ["decision-reason-not-recorded"]
            if not row["reason_nonempty"]
            else ["decision-reason-stated-unknown"]
            if stated_unknown
            else ["decision-reason-is-status-only"]
            if status_only
            else ["shared-reason-needs-per-work-review"]
            if row["reason_shared_work_count"] != 1
            else []
        )
        row["reason_sufficiency"] = "not-scientifically-assessed"
        if library:
            bound = library_rows[row["work_id"]][1]
            row["saved_counts"] = deepcopy(bound["counts"])
            row["query_history"] = deepcopy(bound["query_history"])
            row["discoveries"] = deepcopy(bound["discoveries"])
    if include_original_records:
        recovery = index.get("original_record_recovery", {}).get("payload", {})
        recovered_works = {
            (r["work_id"], r["version_id"]): r for r in recovery.get("works", [])
        }
        for row, paper in zip(rows, index["papers"]):
            row["recorded_context"] = dict(
                findings=deepcopy(paper.get("findings", {})),
                roles=deepcopy(paper.get("roles", [])),
                recovery=deepcopy(
                    recovered_works.get((paper["work_id"], paper["version_id"]))
                ),
                context_is_historical_decision=False,
            )
        for n, event in enumerate(index["screening"]):
            if not any(
                (event.get("work_id"), event.get("version_id"))
                == (p["work_id"], p["version_id"])
                for p in index["papers"]
            ):
                events.append(
                    dict(
                        work_id=event.get("work_id"),
                        current_display_version_id=None,
                        decision_scope="outside-current-index",
                        decision_version_id=event.get("version_id"),
                        order_in_work=None,
                        decision_id=event.get("decision_id"),
                        reason_code=event.get("reason_code"),
                        observed_at=event.get("observed_at"),
                        academic_status=event.get("status", "Unknown"),
                        reason=event.get("reason"),
                        pointer=f"/screening/{n}",
                        original_event=deepcopy(event),
                        scientific_assessment=False,
                    )
                )
    counts = {
        name.replace("-", "_"): sum(r["academic_status"] == name for r in rows)
        for name in ("include", "exclude", "pending", "not-screened")
    }
    counts.update(
        index_paper_versions=len(rows),
        index_distinct_works=len({r["work_id"] for r in rows}),
        unknown=sum(
            r["academic_status"]
            not in {"include", "exclude", "pending", "not-screened"}
            for r in rows
        ),
        distinct_current_reasons=len(reason_works),
    )
    return dict(
        kind="WorkspaceAcademicScreening",
        schema_version="1.0.0",
        contract_version=CONTRACT_VERSION
        if include_original_records
        else "S1-SCREENING-READMODEL-1.1.0",
        input_canonical_sha256=sha(canonical(index)),
        records_sha256=index["provenance"]["records_sha256"],
        scope="index-papers",
        count_scope="bound-run" if library else "saved-index-only",
        library_counts=deepcopy(library["counts"]) if library else None,
        library_binding=deepcopy(library["binding"]) if library else None,
        historical_candidate_total="Unknown",
        scope_note="Counts describe only papers in this validated index, not all historical candidates.",
        decision_history_completeness="complete-for-bound-library"
        if library
        else "Unknown",
        unmatched_legacy_events=deepcopy(
            [
                e
                for e in index["screening"]
                if not any(
                    (e.get("work_id"), e.get("version_id"))
                    == (p["work_id"], p["version_id"])
                    for p in index["papers"]
                )
            ]
            if not library
            else []
        ),
        counts=counts,
        rows=rows,
        events=events,
        scientific_assessment=False,
        claim_assessments_changed=False,
        official_stage2_import_eligible=False,
        research_execution=False,
    )


def academic_screening_files(index, *, include_original_records=True):
    """Export additive sidecars; legacy selection files and HTTP contracts stay intact."""
    from .literature_selection import _HeaderOnly

    result = derive_academic_screening(
        index, include_original_records=include_original_records
    )
    raw = canonical(result)
    digest = sha(raw)
    tables = {"AcademicScreening": result["rows"], "ScreeningHistory": result["events"]}
    headers = {
        "AcademicScreening": (
            "work_id",
            "current_display_version_id",
            "academic_status",
            "recorded_vs_missing",
            "reason",
        ),
        "ScreeningHistory": (
            "work_id",
            "current_display_version_id",
            "decision_id",
            "decision_scope",
            "reason",
            "pointer",
        ),
    }
    workbook = {}
    for name, table in tables.items():
        formatted = []
        key = "rows" if name == "AcademicScreening" else "events"
        for position, original in enumerate(table):
            row = {}
            for field, value in original.items():
                text = (
                    json.dumps(value, ensure_ascii=False, sort_keys=True)
                    if isinstance(value, (list, dict))
                    else str(value)
                )
                # Histories are event rows. Large individual values remain complete in JSON/CSV.
                if field == "raw_history" or len(text.encode("utf-16-le")) // 2 > 32767:
                    value = dict(
                        path=JSON_PATH,
                        sha256=digest,
                        pointer=f"/{key}/{position}/{field}",
                        content_truncated=False,
                    )
                row[field] = value
            formatted.append(row)
        workbook[name] = formatted or _HeaderOnly(headers[name])
    markdown = [
        "# Recorded academic screening",
        "",
        result["scope_note"],
        "",
        "Recorded reasons may be shared templates. No scientific assessment was performed.",
        "Legacy missing history and the total historical candidate count remain Unknown.",
        "",
        "Counts: " + json.dumps(result["counts"], sort_keys=True),
        "",
    ]
    for row in result["rows"]:
        markdown.append(
            "<pre>"
            + html.escape(
                f"{row['work_id']} — {row['academic_status']} ({row['recorded_vs_missing']})"
            )
            + "</pre>"
        )
        if include_original_records:
            markdown.append(
                "<pre>"
                + html.escape(
                    json.dumps(
                        row["recorded_context"], ensure_ascii=False, sort_keys=True
                    )
                )
                + "</pre>"
            )
    for event in result["events"]:
        markdown.extend(
            [
                "",
                "<pre>"
                + html.escape(
                    f"{event['work_id']} / {event['decision_id']} / {event['academic_status']} / {event['pointer']}"
                )
                + "</pre>",
                "<pre>" + html.escape(str(event["reason"])) + "</pre>",
            ]
        )
    return {
        JSON_PATH: raw,
        "literature/academic_screening.csv": csv_bytes(
            "AcademicScreening",
            result["rows"] or _HeaderOnly(headers["AcademicScreening"]),
        ),
        "literature/academic_screening_history.csv": csv_bytes(
            "ScreeningHistory",
            result["events"] or _HeaderOnly(headers["ScreeningHistory"]),
        ),
        "literature/academic_screening.md": ("\n".join(markdown) + "\n").encode(
            "utf-8"
        ),
        "literature/academic_screening.xlsx": workbook_bytes(workbook),
    }
