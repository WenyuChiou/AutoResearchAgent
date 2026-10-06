"""Escaped HTML projection for the read-only Stage 2 comparison workbench."""

import json
from html import escape


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
  <header class="s2w-header"><p class="s2w-kicker">Recorded Stage 2 workspace</p><h2 id="s2w-title">Compare literature and research directions</h2><p>Explore recorded studies and options. Source level does not verify every field; missing fields stay Unknown. Original qualifications and judgments remain unchanged.</p></header>
  <div class="s2w-tabs" role="tablist" aria-label="Stage 2 comparison views">
    <button type="button" role="tab" aria-selected="true" aria-controls="s2w-literature" id="s2w-tab-literature">Literature comparison</button>
    <button type="button" role="tab" aria-selected="false" aria-controls="s2w-directions" id="s2w-tab-directions">Research directions</button>
    <button type="button" role="tab" aria-selected="false" aria-controls="s2w-resources" id="s2w-tab-resources">Data, models &amp; tools</button>
    <button type="button" role="tab" aria-selected="false" aria-controls="s2w-synthesis" id="s2w-tab-synthesis">Recorded synthesis</button>
  </div>
  <section class="s2w-panel" role="tabpanel" id="s2w-literature" aria-labelledby="s2w-tab-literature">
    <div class="s2w-toolbar"><label>Search recorded literature<input type="search" data-s2w-search placeholder="Search recorded text"></label><label class="s2w-mode">Table view<select data-s2w-mode><option value="overview">Research overview</option><option value="concepts">Concepts &amp; methods</option><option value="detail">Detailed evidence</option></select></label><button type="button" data-s2w-compare>Compare selected</button><button type="button" data-s2w-clear>Clear selection</button><output data-s2w-count aria-live="polite"></output></div>
    <p class="s2w-prose s2w-muted">Concepts are recorded topic labels, not an automatic keyword analysis or a claim of historical lineage. Stage 2 research supplies the topic-specific comparison and source checks.</p>
    <div class="s2w-table-scroll" tabindex="0" aria-label="Scrollable literature comparison table"><table class="s2w-table s2w-literature"><thead><tr><th scope="col">Citation</th>{literature_headings}</tr></thead><tbody>{_literature_rows(view)}</tbody></table></div>
    <section class="s2w-compare" data-s2w-comparison hidden aria-live="polite"></section>
  </section>
  <section class="s2w-panel" role="tabpanel" id="s2w-directions" aria-labelledby="s2w-tab-directions" hidden><p class="s2w-prose">These are recorded candidate properties and dispositions. No external score or ranking is added.</p><div class="s2w-table-scroll" tabindex="0" aria-label="Scrollable research direction comparison table"><table class="s2w-table s2w-directions"><thead><tr><th scope="col">Direction</th>{direction_headings}</tr></thead><tbody>{direction_rows}</tbody></table></div></section>
  <section class="s2w-panel" role="tabpanel" id="s2w-resources" aria-labelledby="s2w-tab-resources" hidden><h3>Recorded resources</h3><p class="s2w-prose">Values appear as recorded. Missing or unknown cost is not shown as zero, and no resource is automatically labeled available.</p><pre class="s2w-record">{_html(view.get("resources"))}</pre></section>
  <section class="s2w-panel" role="tabpanel" id="s2w-synthesis" aria-labelledby="s2w-tab-synthesis" hidden><h3>Recorded synthesis</h3><div class="s2w-prose s2w-record">{_preview(view.get("comparison"), 360)}</div><p><a href="stage2/report-reader.html">Open the verified report reader</a></p></section>
  <script type="application/json" data-s2w-view>{_payload(view)}</script>
</section>"""
