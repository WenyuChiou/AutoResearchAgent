"""Render validated topic and resource tables in editable proposal reports."""

from html import escape
from urllib.parse import urlsplit

from .topic_tables import validate_research_tables


def _text(value):
    if value is None:
        return "Unknown"
    if isinstance(value, list):
        return "; ".join(_text(item) for item in value) or "None recorded"
    return str(value)


def _md(value):
    text = _text(value).replace("\r", "").replace("\n", " ")
    for character in "\\`*_{}[]()#+.!|<>":
        text = text.replace(character, "\\" + character)
    return text


def _status(cell):
    status = cell["status"]
    mark = {"present": "✓", "absent": "✕"}.get(status)
    value = cell.get("value")
    if isinstance(value, bool):
        value = None
    return " · ".join(
        _text(value)
        for value in (mark, status.replace("-", " "), value)
        if value is not None
    )


def _rows(tables, packet):
    literature = {
        (row["work_id"], row["version_id"]): row for row in packet.get("literature", [])
    }
    cells = {
        (row["work_id"], row["version_id"], row["dimension_id"]): row
        for row in tables["cells"]
    }
    result = []
    for ref in tables["work_refs"]:
        identity = (ref["work_id"], ref["version_id"])
        work = literature[identity]
        citation = f"{work['title']} ({_text(work.get('year'))})"
        result.append(
            [citation]
            + [
                _status(cells[(*identity, axis["dimension_id"])])
                for axis in tables["dimensions"]
            ]
        )
    return result


def _resource_rows(tables):
    return [
        [
            f"{row['candidate_id']} v{row['candidate_version']}",
            row["category"],
            row["name"],
            row["purpose"],
            "Yes" if row["required"] else "No",
            _text(row["url"]) + " · version: " + _text(row["version"]),
            row["status"] + " · " + _text(row["access_conditions"]),
            row["license"],
            row["cost_basis"],
            _text(row["limitations"])
            + " · Alternatives: "
            + _text(row["alternatives"]),
            _text(row["evidence_ids"]) + " · Checked: " + _text(row["checked_at"]),
        ]
        for row in tables["direction_resources"]
    ]


RESOURCE_HEADINGS = [
    "Direction version",
    "Type",
    "Resource",
    "Use",
    "Required",
    "Source / version",
    "Access status / conditions",
    "License",
    "Cost basis",
    "Limits / alternatives",
    "Evidence / checked at",
]


def _markdown_table(headings, rows):
    return "\n".join(
        [
            "| " + " | ".join(_md(value) for value in headings) + " |",
            "| " + " | ".join("---" for _ in headings) + " |",
        ]
        + ["| " + " | ".join(_md(value) for value in row) + " |" for row in rows]
    )


def render_tables_markdown(tables, packet):
    """Emit exact recorded dimensions/cells/resources with visible provenance."""
    if tables is None:
        return ""
    tables = validate_research_tables(tables, packet)
    lines = [
        "## Topic-specific research comparison",
        "",
        "Recorded assessments: source bindings do not certify their scientific interpretation. "
        "Unknown is not absence; resource access does not establish direction feasibility.",
        "",
        _markdown_table(
            ["Dimension", "Research need", "Why compare", "How assessed", "Conditions"],
            [
                [
                    axis[name]
                    for name in (
                        "label",
                        "research_need",
                        "rationale",
                        "definition",
                        "conditions",
                    )
                ]
                for axis in tables["dimensions"]
            ],
        ),
        "",
        _markdown_table(
            ["Study"] + [axis["label"] for axis in tables["dimensions"]],
            _rows(tables, packet),
        ),
        "",
        "### Cell evidence and interpretation",
        "",
    ]
    for cell in tables["cells"]:
        lines.append(
            f"- {_md(cell['work_id'])} / {_md(cell['version_id'])} / {_md(cell['dimension_id'])}: "
            f"{_md(_status(cell))}; reason: {_md(cell['reason'])}; "
            f"inspection: {_md(cell['inspection_scope'])}; negative basis: {_md(cell['negative_basis'])}; "
            f"evidence: {_md(cell['evidence_ids'])}"
        )
    lines.extend(
        [
            "",
            "## Resources for each direction",
            "",
            _markdown_table(RESOURCE_HEADINGS, _resource_rows(tables)),
            "",
        ]
    )
    if not tables["direction_resources"]:
        lines.append(
            "No structured resources are recorded; this does not show that no resources are needed."
        )
    return "\n".join(lines) + "\n"


def _safe_link(value):
    if isinstance(value, str):
        try:
            parsed = urlsplit(value)
        except ValueError:
            return escape(value)
        if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
            return (
                '<a href="'
                + escape(value, quote=True)
                + '" rel="noreferrer">'
                + escape(value)
                + "</a>"
            )
    return escape(_text(value))


def _html_table(headings, rows, *, resource_urls=None):
    return (
        '<div class="table-wrap"><table><thead><tr>'
        + "".join(
            '<th scope="col">' + escape(_text(value)) + "</th>" for value in headings
        )
        + "</tr></thead><tbody>"
        + "".join(
            "<tr>"
            + "".join(
                "<td>"
                + (
                    _safe_link(resource_urls[row_index])
                    + " · version: "
                    + escape(_text(value).split(" · version: ", 1)[-1])
                    if resource_urls is not None and column_index == 5
                    else escape(_text(value))
                )
                + "</td>"
                for column_index, value in enumerate(row)
            )
            + "</tr>"
            for row_index, row in enumerate(rows)
        )
        + "</tbody></table></div>"
    )


def render_tables_html(tables, packet):
    """Provide safe standalone tables without executing source-provided content."""
    if tables is None:
        return ""
    tables = validate_research_tables(tables, packet)
    return (
        '<section id="topic-comparison"><h2>Topic-specific research comparison</h2>'
        "<p>Recorded assessments require independent source review. Unknown is not absence.</p>"
        + _html_table(
            ["Dimension", "Research need", "Why compare", "How assessed", "Conditions"],
            [
                [
                    axis[name]
                    for name in (
                        "label",
                        "research_need",
                        "rationale",
                        "definition",
                        "conditions",
                    )
                ]
                for axis in tables["dimensions"]
            ],
        )
        + _html_table(
            ["Study"] + [axis["label"] for axis in tables["dimensions"]],
            _rows(tables, packet),
        )
        + "<details><summary>Cell reasons and evidence references</summary><ul>"
        + "".join(
            "<li>"
            + escape(
                f"{row['work_id']} / {row['version_id']} / {row['dimension_id']}: {_status(row)}; "
                f"{row['reason']}; inspection: {row['inspection_scope']}; negative basis: {_text(row['negative_basis'])}; "
                f"evidence: {_text(row['evidence_ids'])}"
            )
            + "</li>"
            for row in tables["cells"]
        )
        + '</ul></details></section><section id="direction-resources"><h2>Resources for each direction</h2>'
        "<p>Access does not establish whole-direction feasibility. Missing license, cost or version stays Unknown.</p>"
        + _html_table(
            RESOURCE_HEADINGS,
            _resource_rows(tables),
            resource_urls=[row["url"] for row in tables["direction_resources"]],
        )
        + (
            "<p>No structured resources are recorded; required materials may remain unresolved.</p>"
            if not tables["direction_resources"]
            else ""
        )
        + "</section>"
    )
