"""Safe deterministic HTML view of a validated Stage 2 selection."""

import json
from html import escape

from stage2_check import report as canonical_report
from stage2_ideation.tables_report import render_tables_html

AXES = ("opportunity", "value", "answerability", "materials", "execution")


def _e(value):
    return escape(str(value), quote=True)


def _text(value):
    if not isinstance(value, str):
        raise TypeError("HTML report prose must be text")
    return _e(value)


def _items(values, *, empty="None recorded"):
    rows = "".join(f"<li>{_text(value)}</li>" for value in values)
    return f"<ul>{rows or f'<li>{_e(empty)}</li>'}</ul>"


def _json(value):
    rendered = json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    )
    return f'<pre class="structured">{_e(rendered)}</pre>'


def _evidence_anchor(evidence_id):
    return canonical_report._evidence_anchor(evidence_id)


def _evidence_links(evidence_ids, evidence):
    links = []
    for evidence_id in evidence_ids:
        if evidence_id not in evidence:
            raise ValueError(f"report-unknown-evidence: {evidence_id}")
        anchor = _evidence_anchor(evidence_id)
        links.append(f'<a href="#{anchor}">{_text(evidence_id)}</a>')
    return ", ".join(links) if links else "None recorded"


def _snapshot_link(source):
    href = canonical_report._safe_snapshot_path(source["path"])
    return f'<a href="{_e(href)}">{_text(source["source_id"])}</a>'


def _candidate(candidate, evidence, *, historical=False):
    parent = candidate["parent_version"]
    history_note = '<p class="tag">Historical version</p>' if historical else ""
    requirements = _items(candidate["requirements"])
    limitations = _items(candidate["limitations"])
    evidence_links = _evidence_links(candidate["evidence_ids"], evidence)
    return f"""
<article class="card candidate">
  <h3>{_text(candidate["candidate_id"])} v{candidate["version"]}</h3>
  {history_note}
  <dl>
    <dt>Parent version</dt><dd>{parent if parent is not None else "none"}</dd>
    <dt>Question</dt><dd>{_text(candidate["question"])}</dd>
    <dt>Research mode</dt><dd>{_text(candidate["research_mode"])}</dd>
    <dt>Opportunity</dt><dd>{_text(candidate["opportunity"])}</dd>
    <dt>Value</dt><dd>{_text(candidate["value"])}</dd>
    <dt>Approach</dt><dd>{_text(candidate["approach"])}</dd>
    <dt>Evidence</dt><dd>{evidence_links}</dd>
  </dl>
  <div class="columns"><div><h4>Requirements</h4>{requirements}</div>
  <div><h4>Limitations</h4>{limitations}</div></div>
</article>"""


def _score(finding):
    if finding["status"] == "unknown":
        return "Unknown"
    if finding["status"] == "not-applicable":
        return "N/A"
    return str(finding["score"])


def _assessment(assessment, evidence, *, historical=False):
    rows = []
    for axis in AXES:
        finding = assessment["checks"][axis]
        next_check = (
            _text(finding["next_check"])
            if finding["next_check"] is not None
            else "None recorded"
        )
        rows.append(
            "<tr>"
            f'<th scope="row">{axis}</th>'
            f"<td>{_text(finding['status'])}</td>"
            f"<td>{_score(finding)}</td>"
            f"<td>{_text(finding['rationale'])}</td>"
            f"<td>{_evidence_links(finding['evidence_ids'], evidence)}</td>"
            f"<td>{'yes' if finding['blocking'] else 'no'}</td>"
            f"<td>{next_check}</td>"
            "</tr>"
        )
    next_step = assessment["next_step"] or (
        "Obtain human review before authorizing Stage 3."
        if assessment["disposition"] == "recommend"
        else "Retain this disposition unless new source-bound evidence supports reassessment."
    )
    label = "Historical assessment/action" if historical else "Current assessment"
    return f"""
<section class="assessment">
  <h4>{label}</h4>
  <dl>
    <dt>Disposition</dt><dd>{_text(assessment["disposition"])}</dd>
    <dt>Reason</dt><dd>{_text(assessment["reason"])}</dd>
    <dt>Scope change requested</dt><dd>{"yes" if assessment["scope_change_requested"] else "no"}</dd>
    <dt>Next step</dt><dd>{_text(next_step)}</dd>
  </dl>
  <div class="table-wrap"><table>
    <thead><tr><th>Axis</th><th>Status</th><th>Score</th><th>Supplied rationale</th><th>Evidence</th><th>Blocking</th><th>Next check</th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table></div>
</section>"""


def _brief(packet):
    brief = packet["brief"]
    needs = "".join(
        f"<li><strong>{_text(row['need_id'])}</strong>: {_text(row['question'])}</li>"
        for row in brief["needs"]
    )
    scope = "".join(
        f"<li><strong>{_text(row['field'])}</strong>: material="
        f"{'yes' if row['material'] else 'no'}; reason={_text(row['reason'])}</li>"
        for row in brief["scope_fields"]
    )
    previous = brief.get("previous_sha256") or "none"
    return f"""
<section id="brief">
  <h2>Research brief and original scope</h2>
  <dl>
    <dt>Original scope</dt><dd>{_text(brief["original_description"])}</dd>
    <dt>Resources</dt><dd>{_text(packet["resources"])}</dd>
    <dt>Previous brief SHA-256</dt><dd><code>{_e(previous)}</code></dd>
  </dl>
  <h3>Research needs</h3><ul>{needs or "<li>None recorded</li>"}</ul>
  <h3>Scope fields</h3><ul>{scope or "<li>None recorded</li>"}</ul>
  <h3>Supplied scope suggestions</h3>
  <p>These are proposals only; no approval is inferred.</p>{_json(brief.get("suggestions", []))}
  <h3>Recorded scope decisions</h3>
  <p>These are shown as supplied; no additional approval is inferred.</p>{_json(brief.get("decisions", []))}
</section>"""


def _portfolio(selection):
    categories = (
        ("Recommend", selection["recommendations"]),
        ("Park", selection["parked_options"]),
        ("Reject", selection["rejected_options"]),
    )
    rows = []
    for label, candidates in categories:
        names = ", ".join(
            f"{_text(row['candidate_id'])} v{row['version']}" for row in candidates
        )
        rows.append(f'<tr><th scope="row">{label}</th><td>{names or "none"}</td></tr>')
    revise = [
        option["candidate"]
        for option in selection["current_options"]
        if option["assessment"] and option["assessment"]["disposition"] == "revise"
    ]
    pending = [
        option["candidate"]
        for option in selection["current_options"]
        if option["assessment"] is None
    ]
    for label, candidates in (("Revise", revise), ("Pending", pending)):
        names = ", ".join(
            f"{_text(row['candidate_id'])} v{row['version']}" for row in candidates
        )
        rows.append(f'<tr><th scope="row">{label}</th><td>{names or "none"}</td></tr>')
    zero = (
        "<p><strong>No direction is currently recommended.</strong> "
        "This is an allowed, explicit outcome.</p>"
        if not selection["recommendations"]
        else ""
    )
    return f"""
<section id="summary">
  <h2>Portfolio recommendation</h2>
  <p>Recommendations: {len(selection["recommendations"])}</p>
  <table class="compact"><tbody>{"".join(rows)}</tbody></table>{zero}
  <h3>Blocking items</h3>{_items(selection["blocking_items"])}
  <h3>Action-record blockers</h3>{_items(selection["action_record_blocking_items"])}
</section>"""


def _current_options(selection, evidence):
    cards = []
    for option in selection["current_options"]:
        cards.append(_candidate(option["candidate"], evidence))
        if option["assessment"] is None:
            cards.append(
                '<section class="assessment pending"><h4>Pending assessment</h4>'
                "<p>No assessment is recorded for this current version.</p>"
                "<p><strong>Next step:</strong> Complete a source-bound assessment before human selection.</p></section>"
            )
        else:
            cards.append(_assessment(option["assessment"], evidence))
    if not cards:
        cards.append("<p>No candidates were supplied.</p>")
    return (
        '<section id="options"><h2>Current candidate options</h2>'
        + "".join(cards)
        + "</section>"
    )


def _questions(selection):
    unresolved = "".join(
        f"<li><strong>Unresolved:</strong> {_text(item)}</li>"
        for item in selection["unresolved"]
    )
    scope = "".join(
        f"<li><strong>Scope question:</strong> {_text(item)}</li>"
        for item in selection["pending_scope_questions"]
    )
    return (
        '<section id="questions"><h2>Global unresolved and scope questions</h2><ul>'
        + (unresolved + scope or "<li>None recorded</li>")
        + "</ul></section>"
    )


def _histories(selection, evidence):
    candidates = []
    for candidate_id in sorted(selection["candidate_histories"]):
        for candidate in selection["candidate_histories"][candidate_id]:
            candidates.append(_candidate(candidate, evidence, historical=True))
    assessments = []
    for event in selection["assessment_history"]:
        value = event["assessment"]
        assessments.append(
            f'<article class="card"><h3>Event {event["sequence"]}: {_text(value["event_id"])}</h3>'
            "<p>Historical assessment/action record; it does not describe a later candidate version.</p>"
            f"<p><strong>Candidate:</strong> {_text(value['candidate_id'])} v{value['candidate_version']}</p>"
            f"<p><strong>Event hash:</strong> <code>{_text(event['event_sha256'])}</code></p>"
            f"{_assessment(value, evidence, historical=True)}</article>"
        )
    if not assessments:
        assessments.append("<p>No assessments or actions are recorded.</p>")
    action = selection["action_record"]
    if action is None:
        action_html = "<h3>Action record unavailable</h3>" + _items(
            selection["action_record_blocking_items"]
        )
    else:
        action_html = f"""
<h3>Action record</h3>
<dl>
  <dt>Status</dt><dd>{_text(selection["action_record_status"])}</dd>
  <dt>Choice rationale</dt><dd>{_text(action["choice_rationale"])}</dd>
  <dt>Internally recommended candidate IDs</dt><dd>{", ".join(_text(item) for item in action["selected_candidate_ids"]) or "none"}</dd>
</dl>
<h4>Complete action record</h4>{_json(action)}"""
    return f"""
<section id="history">
  <h2>Full candidate version history</h2>{"".join(candidates) or "<p>No candidate versions are recorded.</p>"}
  <h2>Full assessment and action history</h2>{"".join(assessments)}{action_html}
</section>"""


def _bibliography(bibliography, evidence):
    if not bibliography["available"]:
        return f'<section id="bibliography"><h2>Accepted bibliography</h2><p>{_text(bibliography["message"])}</p></section>'
    works = []
    for work in bibliography["works"]:
        doi = (
            f'<a href="{_e(work["doi_href"])}">{_text(work["doi"])}</a>'
            if work["doi_href"]
            else _text(work["doi"])
            if work["doi"] is not None
            else "not recorded"
        )
        url = (
            f'<a href="{_e(work["url_href"])}">{_text(work["url"])}</a>'
            if work["url_href"]
            else _text(work["url"])
        )
        roles = (
            "".join(
                f"<li><strong>{_text(role['role'])}</strong>: {_text(role['reason'])}; "
                f"claims={_evidence_links(role['claim_ids'], evidence)}</li>"
                for role in work["roles"]
            )
            or "<li>None recorded</li>"
        )
        sources = (
            ", ".join(
                f"{_snapshot_link(source)} (level={_text(source['evidence_level'])})"
                for source in work["sources"]
            )
            or "none recorded"
        )
        supplemental = "".join(
            "<details><summary>Additional source version of the same study: "
            + _text(version["version_id"])
            + "</summary><dl><dt>Title</dt><dd>"
            + _text(version["title"])
            + "</dd><dt>Recorded evidence level</dt><dd>"
            + _text(version["evidence_level"])
            + "</dd><dt>Saved sources</dt><dd>"
            + ", ".join(
                _snapshot_link(source) + f" (level={_text(source['evidence_level'])})"
                for source in version["sources"]
            )
            + "</dd><dt>Claims</dt><dd>"
            + _evidence_links(version["claim_ids"], evidence)
            + "</dd></dl><ul>"
            + "".join(
                f"<li>{_text(role['role'])}: {_text(role['reason'])}</li>"
                for role in version["roles"]
            )
            + "</ul></details>"
            for version in work.get("supplemental_versions", [])
        )
        works.append(
            '<article class="card bibliography-work">'
            f"<h3>{_text(work['work_id'])} / {_text(work['version_id'])}</h3><dl>"
            f"<dt>Title</dt><dd>{_text(work['title'])}</dd>"
            f"<dt>Authors</dt><dd>{'; '.join(_text(item) for item in work['authors'])}</dd>"
            f"<dt>Year</dt><dd>{work['year'] if work['year'] is not None else 'not recorded'}</dd>"
            f"<dt>Venue</dt><dd>{_text(work['venue'])}</dd>"
            f"<dt>DOI</dt><dd>{doi}</dd><dt>URL</dt><dd>{url}</dd>"
            f"<dt>Origin</dt><dd>{_text(work['origin'])}</dd>"
            f"<dt>Recorded work evidence level</dt><dd>{_text(work['evidence_level'])}</dd>"
            f"<dt>Saved sources</dt><dd>{sources}</dd></dl>"
            "<h4>Recorded literature roles</h4>"
            "<p>These are saved classifications, not semantic verification.</p>"
            f"<ul>{roles}</ul>{supplemental}</article>"
        )
    return (
        '<section id="bibliography"><h2>Accepted bibliography</h2>'
        + "".join(works)
        + "</section>"
    )


def _sources(snapshots, evidence, bibliography):
    evidence_by_source = {}
    for row in evidence.values():
        evidence_by_source.setdefault(row["source_id"], []).append(row["evidence_id"])
    source_rows = []
    for source_id in sorted(snapshots):
        source = snapshots[source_id]
        source_rows.append(
            "<tr>"
            f'<th scope="row">{_snapshot_link(source)}</th>'
            f"<td>{_text(source['work_id'])}</td><td>{_text(source['version_id'])}</td>"
            f"<td>{_text(source['evidence_level'])}</td><td><code>{_text(source['sha256'])}</code></td>"
            f"<td>{_evidence_links(evidence_by_source.get(source_id, []), evidence)}</td>"
            "</tr>"
        )
    inventory = (
        '<div class="table-wrap"><table><thead><tr><th>Snapshot</th><th>Work</th><th>Version</th><th>Level</th><th>SHA-256</th><th>Excerpts</th></tr></thead>'
        f"<tbody>{''.join(source_rows)}</tbody></table></div>"
        if source_rows
        else "<p>No saved source snapshots are recorded.</p>"
    )
    appendix = []
    for evidence_id in sorted(evidence):
        row = evidence[evidence_id]
        source = snapshots[row["source_id"]]
        appendix.append(
            f'<article class="card evidence" id="{_evidence_anchor(evidence_id)}">'
            f"<h3>Evidence {_text(evidence_id)}</h3><dl>"
            f"<dt>Source snapshot</dt><dd>{_snapshot_link(source)}</dd>"
            f"<dt>Locator</dt><dd>{_text(row['locator'])}</dd>"
            f"<dt>Work</dt><dd>{_text(row['work_id'])}</dd>"
            f"<dt>Version</dt><dd>{_text(row['version_id'])}</dd>"
            f"<dt>Evidence level</dt><dd>{_text(source['evidence_level'])}</dd>"
            f"<dt>SHA-256</dt><dd><code>{_text(source['sha256'])}</code></dd>"
            + (
                "<dt>Bibliographic metadata</dt><dd>not recorded in this v1 packet</dd>"
                if not bibliography["available"]
                else ""
            )
            + (
                "<dt>Recorded claim-specific literature roles</dt><dd>"
                "Classification only; semantic support is not verified. "
                + "; ".join(
                    f"{_text(role['role'])}: {_text(role['reason'])}"
                    for role in bibliography["by_evidence"].get(evidence_id, [])
                )
                + "</dd>"
                if bibliography["available"]
                and bibliography["by_evidence"].get(evidence_id)
                else ""
            )
            + f"</dl><h4>Exact excerpt</h4><pre>{_text(row['quote'])}</pre></article>"
        )
    return f"""
<section id="sources"><h2>Saved source snapshots</h2>{inventory}
<p>A saved source with no recorded excerpt remains listed; it is not silently omitted from the source inventory.</p>
<h2>Evidence appendix</h2>{"".join(appendix) or "<p>No evidence excerpts are recorded.</p>"}</section>"""


def render_selection_html(selection, source_snapshots):
    """Render complete validated Stage 2 content as safe standalone HTML bytes."""
    packet, snapshots, evidence, bibliography = canonical_report._validate_bindings(
        selection, source_snapshots
    )
    packet_hash = selection["packet_sha256"]
    comparison = _text(packet["comparison"])
    body = "".join(
        [
            _portfolio(selection),
            _brief(packet),
            (
                '<section id="comparison"><h2>Supplied comparison</h2>'
                '<p class="notice">This is a supplied scientific judgment/proposal, not an exact source excerpt.</p>'
                f"<p>{comparison}</p></section>"
            ),
            render_tables_html(packet.get("research_tables"), packet),
            _current_options(selection, evidence),
            _questions(selection),
            _histories(selection, evidence),
            _bibliography(bibliography, evidence),
            _sources(snapshots, evidence, bibliography),
            (
                '<section id="audit"><h2>Audit trail</h2>'
                f"<p><strong>Original input packet SHA-256:</strong> <code>{_text(packet_hash)}</code></p>"
                "<p>Prehuman status: human selection pending.</p>"
                "<p>Stage 3: not started; execution is not authorized.</p></section>"
            ),
        ]
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stage 2 research-direction proposal</title>
<style>
:root{{--ink:#172033;--muted:#536078;--line:#d9dfeb;--paper:#fff;--wash:#f4f7fb;--accent:#3156a3}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--wash);color:var(--ink);font:16px/1.55 system-ui,sans-serif}}
header,main{{max-width:1120px;margin:auto}} header{{padding:2.5rem 1.25rem 1rem}} main{{padding:0 1.25rem 4rem}}
nav{{display:flex;flex-wrap:wrap;gap:.5rem;margin:1rem 0}} nav a{{background:#e6ecf8;border-radius:999px;padding:.4rem .8rem}}
section{{background:var(--paper);border:1px solid var(--line);border-radius:12px;margin:1rem 0;padding:1.25rem}}
.card{{border:1px solid var(--line);border-radius:10px;margin:1rem 0;padding:1rem}} .assessment{{border-left:4px solid var(--accent)}}
.notice{{background:#fff6d9;border-left:4px solid #c28a00;padding:.75rem}} .tag{{color:var(--muted);font-weight:600}}
.columns{{display:grid;gap:1rem;grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}}
dl{{display:grid;grid-template-columns:minmax(130px,220px) 1fr;gap:.4rem 1rem}} dt{{font-weight:700}} dd{{margin:0;overflow-wrap:anywhere}}
.table-wrap{{overflow-x:auto}} table{{width:100%;border-collapse:collapse}} th,td{{border:1px solid var(--line);padding:.55rem;text-align:left;vertical-align:top}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f8fb;border:1px solid var(--line);padding:1rem;border-radius:8px}}
a{{color:var(--accent)}} code{{overflow-wrap:anywhere}} h1,h2,h3{{line-height:1.2}}
@media(max-width:620px){{dl{{grid-template-columns:1fr}}}}
</style></head><body>
<header><p class="tag">Proposal for discussion</p><h1>Stage 2 research-direction proposal</h1>
<p>Compare the options, review the evidence and open questions, then choose a direction. A proposed method has not yet been shown to work. Your choice and the detailed study plan are the next steps.</p>
<nav aria-label="Report sections"><a href="#summary">Summary</a><a href="#brief">Brief</a><a href="#comparison">Comparison</a><a href="#options">Current options</a><a href="#questions">Open questions</a><a href="#history">History</a><a href="#bibliography">Bibliography</a><a href="#sources">Sources</a><a href="#audit">Audit</a></nav></header>
<main>{body}</main></body></html>
"""
    return document.encode("utf-8")
