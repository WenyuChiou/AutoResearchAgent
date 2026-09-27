"""Comparable atomic results and inert reports, after caller-owned replay checks."""

import csv
import html
import io
import json
from datetime import datetime
from pathlib import Path


def capture_costs(record):
    """Keep attempt wall times and observed usage separate from unknown costs."""
    attempts = record.get("attempts", [])
    durations = []
    for row in attempts:
        start, end = row.get("started_at"), row.get("ended_at")
        durations.append(
            (
                datetime.fromisoformat(end) - datetime.fromisoformat(start)
            ).total_seconds()
            if start and end
            else None
        )
    usage = [r.get("summary", {}).get("usage") for r in attempts]
    return {
        "attempt_count": len(attempts) if "attempts" in record else None,
        "attempt_elapsed_seconds": durations,
        "elapsed_seconds_in_attempts": sum(durations)
        if durations and all(v is not None for v in durations)
        else None,
        "elapsed_semantics": "Recorded attempt wall time includes observer overhead; not native tool duration.",
        "observed_usage_by_attempt": usage,
        "human_interventions": record.get("human_interventions"),
        "currency_cost": None,
    }


def compare_results(a, b):
    """Do arithmetic only; a matching result hash is not verified replay or approval."""
    from .general import _check_result_scores

    for value in (a, b):
        _check_result_scores(value)
    binding_reasons = []
    for key in ("rubric_sha256", "spec_sha256", "evaluator_identity", "evidence_mode"):
        if not a.get(key) or not b.get(key):
            binding_reasons.append("missing-" + key)
        elif a[key] != b[key]:
            binding_reasons.append("different-" + key)
    for arm, value in (("A", a), ("B", b)):
        for key in ("evaluator_status", "subject_status", "extraction_status"):
            if value.get(key) != "complete":
                binding_reasons.append(arm + "-" + key + "-incomplete")
    criteria, dimensions = [], {}
    for metric in ("P1", "P2", "P3"):
        left, right = a["dimensions"][metric], b["dimensions"][metric]
        left_rows = {r["criterion_id"]: r for r in left["criteria"]}
        right_rows = {r["criterion_id"]: r for r in right["criteria"]}
        applicable_a = sorted(
            k for k, r in left_rows.items() if r["status"] != "not-applicable"
        )
        applicable_b = sorted(
            k for k, r in right_rows.items() if r["status"] != "not-applicable"
        )
        for key in sorted(left_rows):
            lrow, rrow = left_rows[key], right_rows[key]
            reasons = binding_reasons.copy()
            for arm, row in (("A", lrow), ("B", rrow)):
                if row["status"] != "scored":
                    reasons.append(arm + "-" + row["status"])
            values = {"criterion_id": key, "dimension": metric}
            for arm, row in (("A", lrow), ("B", rrow)):
                values[arm] = row["score"]
                values[arm + "_status"] = row["status"]
                values[arm + "_assessed_fraction"] = (
                    None
                    if row["status"] == "not-applicable"
                    else int(row["status"] == "scored")
                )
                values[arm + "_unknown_reason"] = (
                    row.get("missing_evidence") or [row.get("reason") or "unspecified"]
                    if row["status"] == "unverifiable"
                    else []
                )
                values[arm + "_reason"] = row.get("reason")
                values[arm + "_evidence_ids"] = sorted(
                    {p["evidence_id"] for p in row.get("passages", [])}
                )
            values.update(
                delta_eligible=not reasons,
                ineligibility_reasons=reasons,
                delta=rrow["score"] - lrow["score"] if not reasons else None,
            )
            criteria.append(values)
        reasons = binding_reasons.copy()
        if applicable_a != applicable_b:
            reasons.append("different-applicable-criterion-set")
        if not applicable_a or not applicable_b:
            reasons.append("no-applicable-criteria")
        if left["unknown_count"] or right["unknown_count"]:
            reasons.append("required-criterion-unverifiable")
        dimensions[metric] = {
            "A": left["observed_score_100"],
            "B": right["observed_score_100"],
            "A_assessed_fraction": left["assessed_fraction"],
            "B_assessed_fraction": right["assessed_fraction"],
            "A_applicable_criteria": applicable_a,
            "B_applicable_criteria": applicable_b,
            "delta_eligible": not reasons,
            "ineligibility_reasons": reasons,
            "delta": round(right["observed_score_100"] - left["observed_score_100"], 2)
            if not reasons
            else None,
        }
    return {
        "criteria": criteria,
        "dimensions": dimensions,
        "binding_ineligibility_reasons": binding_reasons,
        "costs": {"A": a.get("costs"), "B": b.get("costs")},
        "major_issues": {"A": a.get("major_issues"), "B": b.get("major_issues")},
        "arithmetic_only": True,
    }


def export_report(decision, output):
    """Write reports beside a replay-validated decision; never assert new approval."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"repeat": pair["repeat"], **row}
        for pair in decision["pairs"]
        for row in pair["criteria"]
    ]
    columns = list(rows[0]) if rows else ["repeat", "criterion_id"]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: json.dumps(value, ensure_ascii=False)
                if isinstance(value, (dict, list))
                else (
                    "'" + value
                    if isinstance(value, str) and value.startswith(("=", "+", "-", "@"))
                    else value
                )
                for key, value in row.items()
            }
        )
    csv_path = output.with_suffix(".criteria.csv")
    html_path = output.with_suffix(".html")
    data_path = output.with_suffix(".report.json")

    # Escape every displayed value, including filenames, unknowns and native text.
    def cell(value):
        return html.escape("unknown" if value is None else str(value))

    headers = (
        "repeat",
        "criterion_id",
        "A",
        "B",
        "delta",
        "delta_eligible",
        "A_unknown_reason",
        "B_unknown_reason",
        "ineligibility_reasons",
    )
    table = "<tr>" + "".join("<th>" + cell(k) + "</th>" for k in headers) + "</tr>"
    for row in rows:
        table += (
            "<tr>" + "".join("<td>" + cell(row[k]) + "</td>" for k in headers) + "</tr>"
        )
    page = (
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Stage 1 comparison</title>'
        "<style>body{font:16px system-ui;margin:2rem}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:.5rem;text-align:left}pre{white-space:pre-wrap}</style>"
        "<h1>Stage 1 comparison</h1><p>Decision: " + cell(decision["decision"]) + "</p>"
        "<p>P1, P2 and P3 remain separate. Null deltas are ineligible comparisons. "
        "This report does not grant freeze or publication approval.</p><table>"
        + table
        + "</table>"
        "<h2>Dimension deltas and ranges</h2><pre>"
        + cell(json.dumps(decision["summary"], indent=2))
        + "</pre>"
        "<h2>Full comparison records</h2><pre>"
        + cell(json.dumps(decision, ensure_ascii=False, indent=2))
        + "</pre></html>"
    )
    for path, raw in (
        (csv_path, stream.getvalue().encode("utf-8")),
        (html_path, page.encode("utf-8")),
        (
            data_path,
            (json.dumps(decision, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        ),
    ):
        if path.exists() and path.read_bytes() != raw:
            raise ValueError(
                "comparison report already exists with different bytes: " + path.name
            )
    for path, raw in (
        (csv_path, stream.getvalue()),
        (html_path, page),
        (data_path, json.dumps(decision, ensure_ascii=False, indent=2) + "\n"),
    ):
        path.write_bytes(raw.encode("utf-8"))
    return {
        "criteria_csv": str(csv_path),
        "html": str(html_path),
        "json": str(data_path),
    }
