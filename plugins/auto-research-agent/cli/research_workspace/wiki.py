"""Rebuild private Markdown notes from the bound index without new judgments."""

import json
import re

from stage1_deliverable.common import DeliverableError, canonical, sha

from .projection import validate_index

FINDINGS = (
    ("question", "Question"),
    ("data", "Data"),
    ("method", "Method"),
    ("main_findings", "Main findings"),
    ("limitations", "Limitations"),
    ("relevance", "Relevance"),
    ("transferability", "Transferability"),
)


def _fence(value):
    text = (
        value
        if isinstance(value, str)
        else json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
    )
    length = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, length + 1)
    return fence + "\n" + text + "\n" + fence + "\n\n"


def wiki_files(index) -> dict[str, bytes]:
    """Return deterministic relative paths and UTF-8 bytes; never write files."""
    validate_index(index)
    availability = None
    if index["schema_version"] == "3.0.0":
        from .source_availability import derive_source_availability

        availability = derive_source_availability(index)
    files = {}
    readme = (
        (
            "# Research workspace Wiki\n\n"
            "Rebuildable, private reading notes from the canonical records. "
            "These notes preserve recorded judgments without adding rankings, "
            "scientific scores, acceptance, or execution permission. "
            "Missing findings are labeled Not recorded.\n\n"
            "## Workspace context\n\n"
        )
        + _fence(
            {
                name: index[name]
                if name != "supplement"
                or index["supplement"]["status"] == "not-provided"
                else {
                    key: index["supplement"][key]
                    for key in (
                        "status",
                        "manifest_sha256",
                        "review_sha256",
                        "acceptance",
                    )
                }
                for name in (
                    "project_id",
                    "topic",
                    "as_of",
                    "status",
                    "supplement",
                    "readiness",
                    "evaluations",
                    "provenance",
                )
            }
        )
        + "## Records\n\n"
    )
    if (
        index["schema_version"] in {"2.0.0", "3.0.0"}
        and index["supplement"]["status"] != "not-provided"
    ):
        readme += (
            "[Accepted repairs and core findings](../closeout/core-findings.md)\n\n"
        )
    if availability is not None:
        readme += "## Saved-source availability\n\n" + _fence(availability["counts"])
    for ordinal, paper in enumerate(index["papers"]):
        identity = [paper["work_id"], paper["version_id"]]
        filename = sha(canonical(identity)) + ".md"
        path = "wiki/" + filename
        if path in files:
            raise DeliverableError("duplicate work/version in Wiki")
        readme += f"- [Record {ordinal + 1:03d}]({filename})\n"
        note = "# Research record\n\n## Canonical binding\n\n" + _fence(
            {
                "work_id": paper["work_id"],
                "version_id": paper["version_id"],
                "source_ids": paper.get("source_ids", []),
                "claim_ids": paper.get("claim_ids", []),
                "path": "deliverable/records.original.json",
                "sha256": index["provenance"]["records_sha256"],
                "pointer": f"/papers/{ordinal}",
            }
        )
        note += "## Original complete paper record\n\n" + _fence(paper)
        findings = paper.get("findings") or {}
        for field, label in FINDINGS:
            value = findings.get(field)
            note += f"## {label}\n\n" + _fence(
                "Not recorded" if value is None or value == "" else value
            )
        for field, label in (
            ("sources", "Original sources and receipts"),
            ("claims", "Original claims and judgments"),
            ("edges", "Recorded relationships and provenance"),
            ("screening", "Original screening judgments"),
        ):
            rows = []
            for row in index[field]:
                if field in {"sources", "claims"}:
                    id_field = "source_id" if field == "sources" else "claim_id"
                    related = row.get(id_field) in paper.get(id_field + "s", [])
                else:
                    related = (
                        row.get("work_id") == identity[0]
                        and row.get("version_id", identity[1]) == identity[1]
                    )
                if related:
                    rows.append(row)
            note += f"## {label}\n\n" + _fence(rows)
        if (
            index["schema_version"] in {"2.0.0", "3.0.0"}
            and index["supplement"]["status"] != "not-provided"
        ):
            from .closeout import repair_note

            note += repair_note(index, paper)
        if index["schema_version"] == "3.0.0":
            row = next(
                r
                for r in index["source_rerun"]["data"]["rows"]
                if (r["work_id"], r["version_id"]) == tuple(identity)
            )
            note += (
                "## New saved-source read attempt\n\nOriginal judgments above remain historical. Extraction does not establish claim support.\n\n"
                + _fence(row)
            )
            source = next(
                row
                for row in availability["source_rows"]
                if (row["work_id"], row["version_id"]) == tuple(identity)
            )
            claims = [
                row
                for row in availability["claim_rows"]
                if (row["work_id"], row["version_id"]) == tuple(identity)
            ]
            note += (
                "## Source availability\n\nReadable-source status does not change or explain the historical claim assessment.\n\n"
                + _fence({"source_availability": source, "claims": claims})
            )
        files[path] = note.encode("utf-8")
    readme += "\n## Original audit snapshots\n\n"
    for document in index["audit_documents"]:
        readme += (
            "### Audit document\n\n"
            + _fence({key: value for key, value in document.items() if key != "text"})
            + _fence(document["text"])
        )
    files["wiki/README.md"] = readme.encode("utf-8")
    return files
