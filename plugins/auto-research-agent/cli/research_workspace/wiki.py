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
                if name != "supplement" or index["schema_version"] == "1.0.0"
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
    if index["schema_version"] == "2.0.0":
        readme += (
            "[Accepted repairs and core findings](../closeout/core-findings.md)\n\n"
        )
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
        if index["schema_version"] == "2.0.0":
            from .closeout import repair_note

            note += repair_note(index, paper)
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
