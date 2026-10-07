"""Escaped HTML projection for the read-only Stage 2 comparison workbench."""

import json
from html import escape
from urllib.parse import urlsplit


_LITERATURE_FIELDS = (
    ("question", "Recorded question / rationale"),
    ("geography", "Research region"),
    ("population", "Population / object"),
    ("concepts", "Recorded topic / concepts"),
    ("data", "Data"),
    ("method", "Method"),
    ("findings", "Findings"),
    ("validation", "Validation"),
    ("limitations", "Limitations"),
    ("relevance", "Relevance"),
)


def _text(value):
    if value is None:
        return "Unknown"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _html(value):
    return escape(_text(value), quote=True)


def _payload(view):
    return (
        json.dumps(view, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def _preview(value, limit=180):
    text = _text(value)
    if value is None or len(text) <= limit:
        return '<span class="s2w-value">' + escape(text) + "</span>"
    return (
        '<details class="s2w-preview"><summary>'
        + escape(text[:limit].rstrip() + "…")
        + '</summary><div class="s2w-full">'
        + escape(text)
        + "</div></details>"
    )


def _citation(row):
    recorded_authors = row.get("authors")
    authors = (
        "; ".join(recorded_authors)
        if isinstance(recorded_authors, list)
        and all(isinstance(item, str) for item in recorded_authors)
        else _text(recorded_authors)
    )
    title = _text(row.get("title"))
    year = _text(row.get("year"))
    identity = _text([row.get("work_id"), row.get("version_id")])
    return (
        '<strong class="s2w-title">'
        + escape(title)
        + "</strong><span>"
        + escape(authors)
        + " · "
        + escape(year)
        + '</span><span class="s2w-muted">Source level: '
        + _html(row.get("evidence_level"))
        + "</span><details><summary>Work and version</summary>"
        + escape(identity)
        + "</details>"
    )


def _evidence(row, evidence):
    related = [
        item
        for item in evidence
        if item.get("work_id") == row.get("work_id")
        and item.get("version_id") == row.get("version_id")
        and item.get("source_id") in (row.get("source_ids") or [])
        and item.get("evidence_id") in (row.get("evidence_ids") or [])
    ]
    if not related:
        body = "<p>No associated quote is recorded for this work/version.</p>"
    else:
        items = []
        for item in related:
            label = " · ".join(
                _text(item.get(name))
                for name in ("source_id", "locator", "evidence_level")
            )
            items.append(
                '<li><span class="s2w-muted">'
                + escape(label)
                + "</span>"
                + _preview(item.get("quote"), 240)
                + "</li>"
            )
        body = "<ul>" + "".join(items) + "</ul>"
    return (
        '<details class="s2w-evidence"><summary>Associated evidence ('
        + str(len(related))
        + ")</summary><p>These quotes share the recorded work/version/source association; "
        "that association is not proof for every comparison cell.</p>"
        + body
        + '<p><a href="stage2/report-reader.html">Open the verified report reader</a></p></details>'
    )


_STATUS_LABELS = {
    "present": ("✓", "Present"),
    "absent": ("✕", "Absent"),
    "partial": ("◐", "Partial"),
    "described": ("●", "Described"),
    "unknown": ("?", "Unknown"),
    "not-applicable": ("—", "Not applicable"),
}


def _bound_evidence(
    evidence, evidence_ids, *, work_id=None, version_id=None, source_ids=None
):
    wanted = evidence_ids if isinstance(evidence_ids, list) else []
    return [
        item
        for item in evidence
        if isinstance(item, dict)
        and item.get("evidence_id") in wanted
        and (work_id is None or item.get("work_id") == work_id)
        and (version_id is None or item.get("version_id") == version_id)
        and (source_ids is None or item.get("source_id") in source_ids)
    ]


def _recorded_evidence(items):
    if not items:
        return '<p class="s2w-muted">No matching recorded quote.</p>'
    rows = []
    for item in items:
        rows.append(
            '<li><span class="s2w-muted">'
            + _html(item.get("evidence_id"))
            + " · "
            + _html(item.get("source_id"))
            + " · "
            + _html(item.get("locator"))
            + "</span>"
            + _preview(item.get("quote"), 240)
            + "</li>"
        )
    return '<ul class="s2w-quote-list">' + "".join(rows) + "</ul>"


def _axis_heading(axis):
    details = (
        ("Research need", axis.get("research_need")),
        ("Rationale", axis.get("rationale")),
        ("How papers are assessed", axis.get("definition")),
        ("Conditions", axis.get("conditions")),
    )
    return (
        '<span class="s2w-axis-label">'
        + _html(axis.get("label"))
        + '</span><details class="s2w-axis"><summary>Axis definition</summary><dl>'
        + "".join(
            "<dt>" + label + "</dt><dd>" + _html(value) + "</dd>"
            for label, value in details
        )
        + "</dl></details>"
    )


def _topic_cell(cell, evidence, value_kind, source_ids):
    raw_status = cell.get("status")
    symbol, label = _STATUS_LABELS.get(raw_status, ("?", _text(raw_status)))
    if raw_status in {"present", "absent"} and value_kind != "feature":
        symbol = "!"
    related = _bound_evidence(
        evidence,
        cell.get("evidence_ids"),
        work_id=cell.get("work_id"),
        version_id=cell.get("version_id"),
        source_ids=source_ids,
    )
    details = (
        ("Reason", cell.get("reason")),
        ("Inspection scope", cell.get("inspection_scope")),
        ("Negative basis", cell.get("negative_basis")),
    )
    return (
        '<span class="s2w-status s2w-status--'
        + escape(str(raw_status), quote=True)
        + '" aria-label="Status: '
        + escape(label, quote=True)
        + '"><span aria-hidden="true">'
        + symbol
        + "</span> "
        + escape(label)
        + "</span>"
        + (
            '<div class="s2w-cell-value">' + _preview(cell["value"]) + "</div>"
            if cell.get("value") is not None
            and not (value_kind == "feature" and isinstance(cell.get("value"), bool))
            else ""
        )
        + '<details class="s2w-cell-evidence"><summary>Reason and evidence ('
        + str(len(related))
        + ")</summary><dl>"
        + "".join(
            "<dt>" + label_text + "</dt><dd>" + _html(value) + "</dd>"
            for label_text, value in details
        )
        + "</dl>"
        + _recorded_evidence(related)
        + "</details>"
    )


def _topic_comparison(view):
    tables = view.get("research_tables")
    if not isinstance(tables, dict):
        return (
            '<div class="s2w-empty" role="status"><h3>Topic comparison is unprepared</h3>'
            "<p>This legacy Stage 2 record has no prepared topic-derived research tables. "
            "No comparison cells or feature statuses have been inferred.</p></div>"
        )
    dimensions = tables.get("dimensions")
    work_refs = tables.get("work_refs")
    cells = tables.get("cells")
    dimensions = dimensions if isinstance(dimensions, list) else []
    work_refs = work_refs if isinstance(work_refs, list) else []
    cells = cells if isinstance(cells, list) else []
    evidence = view.get("evidence") or []
    literature = {
        (row.get("work_id"), row.get("version_id")): row
        for row in (view.get("literature") or [])
        + (view.get("supplemental_literature") or [])
        if isinstance(row, dict)
    }
    cell_index = {
        (row.get("work_id"), row.get("version_id"), row.get("dimension_id")): row
        for row in cells
        if isinstance(row, dict)
    }
    headings = "".join(
        '<th scope="col" data-dimension-id="'
        + escape(str(axis.get("dimension_id")), quote=True)
        + '">'
        + _axis_heading(axis)
        + "</th>"
        for axis in dimensions
        if isinstance(axis, dict)
    )
    rows = []
    for work_ref in work_refs:
        if not isinstance(work_ref, dict):
            continue
        identity = (work_ref.get("work_id"), work_ref.get("version_id"))
        work = literature.get(identity)
        citation = (
            _citation(work)
            if work is not None
            else '<strong class="s2w-title">Recorded work/version</strong><span>'
            + _html(list(identity))
            + "</span>"
        )
        if work and work.get("record_kind") == "supplemental-source-version":
            citation += '<span class="s2w-muted">Additional source version of the same study</span>'
        values = []
        for axis in dimensions:
            cell = cell_index.get((*identity, axis.get("dimension_id")))
            values.append(
                "<td>"
                + (
                    _topic_cell(
                        cell,
                        evidence,
                        axis.get("value_kind"),
                        work.get("source_ids") if work is not None else [],
                    )
                    if cell
                    else "No recorded cell in the prepared table."
                )
                + "</td>"
            )
        rows.append(
            '<tr><th scope="row">' + citation + "</th>" + "".join(values) + "</tr>"
        )
    body = "".join(rows)
    if not dimensions or not work_refs:
        body = '<tr><td colspan="99">The prepared table contains no recorded axes or works.</td></tr>'
    return (
        '<div class="s2w-table-scroll" tabindex="0" aria-label="Scrollable topic-derived literature comparison table">'
        '<table class="s2w-table s2w-topic"><thead><tr><th scope="col">Matched literature work</th>'
        + headings
        + "</tr></thead><tbody>"
        + body
        + "</tbody></table></div>"
    )


def _safe_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    return (
        value if parsed.scheme.lower() in {"http", "https"} and parsed.netloc else None
    )


def _resource_url(value):
    href = _safe_url(value)
    if href is None:
        return _html(value)
    return (
        '<a href="'
        + escape(href, quote=True)
        + '" rel="noreferrer">'
        + escape(value)
        + "</a>"
    )


def _resource_table(rows, evidence):
    headings = "".join(
        '<th scope="col">' + label + "</th>"
        for label in (
            "Resource",
            "Role in this direction",
            "Source / version",
            "Access / license",
            "Costs / limits / alternatives",
            "Evidence / check time",
        )
    )
    body = []
    for row in rows:
        required = (
            "Yes"
            if row.get("required") is True
            else "No"
            if row.get("required") is False
            else "Unknown"
        )
        values = [
            "<td><strong>"
            + _html(row.get("name"))
            + '</strong><span class="s2w-muted">'
            + _html(row.get("category"))
            + "</span></td>",
            "<td>"
            + _preview(row.get("purpose"))
            + '<p class="s2w-muted">Required: '
            + required
            + "</p></td>",
            "<td>"
            + _resource_url(row.get("url"))
            + '<p class="s2w-muted">Version: '
            + _html(row.get("version"))
            + "</p></td>",
            "<td><strong>"
            + _html(row.get("status"))
            + "</strong><div>"
            + _preview(row.get("access_conditions"))
            + "</div>"
            + "<details><summary>License</summary>"
            + _preview(row.get("license"))
            + "</details></td>",
            "<td>"
            + _preview(row.get("cost_basis"))
            + "<details><summary>Limits and alternatives</summary><h5>Limits</h5>"
            + _preview(row.get("limitations"))
            + "<h5>Alternatives</h5>"
            + _preview(row.get("alternatives"))
            + "</details></td>",
        ]
        related = _bound_evidence(evidence, row.get("evidence_ids"))
        values.append(
            '<td><span class="s2w-muted">Checked: '
            + _html(row.get("checked_at"))
            + '</span><details class="s2w-cell-evidence"><summary>Recorded evidence ('
            + str(len(related))
            + ")</summary>"
            + _recorded_evidence(related)
            + "</details></td>"
        )
        body.append("<tr>" + "".join(values) + "</tr>")
    return (
        '<div class="s2w-table-scroll" tabindex="0"><table class="s2w-table s2w-resource-table">'
        "<thead><tr>"
        + headings
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def _direction_resources(view):
    tables = view.get("research_tables")
    if not isinstance(tables, dict):
        return '<p class="s2w-empty">No prepared per-direction resource table is recorded.</p>'
    resources = tables.get("direction_resources")
    resources = resources if isinstance(resources, list) else []
    evidence = view.get("evidence") or []
    current = [
        (row.get("candidate_id"), row.get("version"))
        for row in view.get("directions") or []
        if isinstance(row, dict)
    ]
    sections = []
    for candidate_id, version in current:
        matched = [
            row
            for row in resources
            if isinstance(row, dict)
            and row.get("candidate_id") == candidate_id
            and row.get("candidate_version") == version
        ]
        sections.append(
            '<section class="s2w-resource-group"><h4>Current direction · '
            + _html(candidate_id)
            + " · version "
            + _html(version)
            + "</h4>"
            + (
                _resource_table(matched, evidence)
                if matched
                else "<p>No resources recorded for this current version.</p>"
            )
            + "</section>"
        )
    historical = [
        row
        for row in resources
        if isinstance(row, dict)
        and (row.get("candidate_id"), row.get("candidate_version")) not in current
    ]
    if historical:
        groups = {}
        for row in historical:
            groups.setdefault(
                (row.get("candidate_id"), row.get("candidate_version")), []
            ).append(row)
        history = "".join(
            '<section class="s2w-resource-group"><h5>'
            + _html(candidate_id)
            + " · version "
            + _html(version)
            + "</h5>"
            + _resource_table(rows, evidence)
            + "</section>"
            for (candidate_id, version), rows in groups.items()
        )
        sections.append(
            '<details class="s2w-resource-history"><summary>Historical candidate-version associations ('
            + str(len(groups))
            + ")</summary><p>These resources remain associated with older or non-current candidate versions; they are not presented as current.</p>"
            + history
            + "</details>"
        )
    return (
        "".join(sections)
        or '<p class="s2w-empty">No per-direction resources are recorded.</p>'
    )


def _source_versions(row, evidence):
    versions = row.get("source_versions") or []
    if not versions:
        return ""
    sections = []
    for version in versions:
        fields = version.get("cells") or {}
        sections.append(
            _citation(version)
            + "".join(
                "<p><strong>"
                + label
                + ": </strong>"
                + _preview((fields.get(name) or {}).get("text"))
                + "</p>"
                for name, label in (
                    ("data", "Data"),
                    ("method", "Method"),
                    ("findings", "Findings"),
                )
            )
            + _evidence(version, evidence)
        )
    return (
        '<details class="s2w-source-versions"><summary>Additional source versions ('
        + str(len(versions))
        + ")</summary>"
        + "".join(sections)
        + "</details>"
    )


def _literature_rows(view):
    rows = []
    evidence = view.get("evidence") or []
    for index, row in enumerate(view.get("literature") or []):
        key = _text(row.get("key"))
        cells = row.get("cells") or {}
        values = []
        for name, _ in _LITERATURE_FIELDS:
            cell = cells.get(name)
            if name == "question" and cell is None:
                cell = cells.get("rationale")
            cell = cell or {}
            source = (
                '<details class="s2w-field"><summary>Recorded field</summary>'
                + _html(cell.get("field"))
                + "</details>"
                if cell.get("field") is not None
                else ""
            )
            values.append(
                f'<td data-s2w-field="{name}">'
                + _preview(cell.get("text"))
                + source
                + "</td>"
            )
        rows.append(
            '<tr data-s2w-literature-row data-key="'
            + escape(key, quote=True)
            + '"><th scope="row"><label class="s2w-select"><input type="checkbox" '
            + f'data-s2w-select aria-label="Select paper {index + 1} for comparison">'
            + "<span>Compare</span></label>"
            + _citation(row)
            + _evidence(row, evidence)
            + _source_versions(row, evidence)
            + "</th>"
            + "".join(values)
            + "</tr>"
        )
    return (
        "".join(rows)
        or '<tr><td colspan="11">No literature records are available.</td></tr>'
    )


def _direction_rows(view):
    fields = (
        ("question", "Question"),
        ("opportunity", "Recorded contribution / opportunity"),
        ("value", "Value"),
        ("approach", "Method / approach"),
        ("requirements", "Materials / requirements"),
        ("limitations", "Limitations"),
        ("disposition", "Disposition"),
        ("next_step", "Next step"),
    )
    rows = []
    for index, row in enumerate(view.get("directions") or []):
        identity = _text([row.get("candidate_id"), row.get("version")])
        cells = "".join(
            "<td>" + _preview(row.get(name)) + "</td>" for name, _ in fields
        )
        checks = _preview(row.get("checks"), 240)
        rows.append(
            f'<tr><th scope="row"><strong>Option {index + 1}</strong><details><summary>Candidate version</summary>'
            + escape(identity)
            + "</details><details><summary>Reason and recorded checks</summary><p>"
            + _html(row.get("reason"))
            + "</p>"
            + checks
            + "</details></th>"
            + cells
            + "</tr>"
        )
    headings = "".join('<th scope="col">' + label + "</th>" for _, label in fields)
    body = (
        "".join(rows)
        or '<tr><td colspan="9">No research directions are recorded.</td></tr>'
    )
    return headings, body


def render_comparison_workbench(view) -> str:
    """Render a self-contained, read-only comparison surface from a sealed view."""
    direction_headings, direction_rows = _direction_rows(view)
    literature_headings = "".join(
        f'<th scope="col" data-s2w-field="{name}">{label}</th>'
        for name, label in _LITERATURE_FIELDS
    )
    return f"""<section id="stage2-workbench" aria-labelledby="s2w-title">
  <header class="s2w-header"><p class="s2w-kicker">Recorded Stage 2 workspace</p><h2 id="s2w-title">Compare literature and research directions</h2><details class="s2w-notes"><summary>Provenance and interpretation notes</summary><ul><li>Source level does not verify every field; missing fields stay Unknown. Original qualifications and judgments remain unchanged.</li><li>Concepts are recorded topic labels, not an automatic keyword analysis or a claim of historical lineage. Stage 2 research supplies the topic-specific comparison and source checks.</li><li>Topic columns come from the confirmed research need. A check or cross appears only for a recorded feature status; partial, described, unknown and not applicable remain distinct.</li><li>Research directions show recorded candidate properties and dispositions. No external score or ranking is added.</li><li>Resources are bound to an exact candidate version. Access does not certify feasibility; missing access, license, cost, version or check time stays Unknown.</li></ul></details></header>
  <div class="s2w-tabs" role="tablist" aria-label="Stage 2 comparison views">
    <button type="button" role="tab" aria-selected="true" aria-controls="s2w-literature" id="s2w-tab-literature">Literature comparison</button>
    <button type="button" role="tab" aria-selected="false" aria-controls="s2w-topic" id="s2w-tab-topic">Topic comparison</button>
    <button type="button" role="tab" aria-selected="false" aria-controls="s2w-directions" id="s2w-tab-directions">Research directions</button>
    <button type="button" role="tab" aria-selected="false" aria-controls="s2w-resources" id="s2w-tab-resources">Data, models &amp; tools</button>
    <button type="button" role="tab" aria-selected="false" aria-controls="s2w-synthesis" id="s2w-tab-synthesis">Recorded synthesis</button>
  </div>
  <section class="s2w-panel" role="tabpanel" id="s2w-literature" aria-labelledby="s2w-tab-literature">
    <div class="s2w-toolbar"><label>Search recorded literature<input type="search" data-s2w-search placeholder="Search recorded text"></label><label class="s2w-mode">Table view<select data-s2w-mode><option value="overview">Research overview</option><option value="concepts">Concepts &amp; methods</option><option value="detail">Detailed evidence</option></select></label><button type="button" data-s2w-compare>Compare selected</button><button type="button" data-s2w-clear>Clear selection</button><output data-s2w-count aria-live="polite"></output></div>
    <div class="s2w-table-scroll" tabindex="0" aria-label="Scrollable literature comparison table"><table class="s2w-table s2w-literature"><thead><tr><th scope="col">Citation</th>{literature_headings}</tr></thead><tbody>{_literature_rows(view)}</tbody></table></div>
    <section class="s2w-compare" data-s2w-comparison hidden aria-live="polite"></section>
  </section>
  <section class="s2w-panel" role="tabpanel" id="s2w-topic" aria-labelledby="s2w-tab-topic" hidden><h3>Topic-derived literature matrix</h3>{_topic_comparison(view)}</section>
  <section class="s2w-panel" role="tabpanel" id="s2w-directions" aria-labelledby="s2w-tab-directions" hidden><div class="s2w-table-scroll" tabindex="0" aria-label="Scrollable research direction comparison table"><table class="s2w-table s2w-directions"><thead><tr><th scope="col">Direction</th>{direction_headings}</tr></thead><tbody>{direction_rows}</tbody></table></div></section>
  <section class="s2w-panel" role="tabpanel" id="s2w-resources" aria-labelledby="s2w-tab-resources" hidden><h3>Data, reports, references, models and tools by direction</h3>{_direction_resources(view)}<details class="s2w-global-resources"><summary>Original packet-level resource prose</summary><pre class="s2w-record">{_html(view.get("resources"))}</pre></details></section>
  <section class="s2w-panel" role="tabpanel" id="s2w-synthesis" aria-labelledby="s2w-tab-synthesis" hidden><h3>Recorded synthesis</h3><div class="s2w-prose s2w-record">{_preview(view.get("comparison"), 360)}</div><p><a href="stage2/report-reader.html">Open the verified report reader</a></p></section>
  <script type="application/json" data-s2w-view>{_payload(view)}</script>
</section>"""
