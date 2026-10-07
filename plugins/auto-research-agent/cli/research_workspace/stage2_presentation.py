"""Pure, readable projections of a verified Stage 2 workspace attachment."""

import json
import re
from html import escape

from stage1_deliverable.common import canonical


_DISPOSITION_LABELS = {
    "recommend": "Recommended for human review",
    "revise": "Revision required",
    "park": "Parked pending more evidence or resources",
    "reject": "Rejected on the recorded evidence",
}

_DIMENSION_LABELS = {
    "P4": "Literature comparison",
    "P5": "Research opportunity",
    "P6": "Decision quality",
}

_LONG_QUESTION = 180


def _html(value):
    if value is None:
        return "Unknown"
    return escape(str(value), quote=True)


def _json_text(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    )


def _fence(value):
    text = value if isinstance(value, str) else _json_text(value)
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text}\n{fence}\n"


def _question(value):
    if value is None:
        return '<p class="stage2-question">Unknown</p>'
    text = str(value)
    if len(text) <= _LONG_QUESTION:
        return '<p class="stage2-question">' + _html(text) + "</p>"
    summary = text[: _LONG_QUESTION - 1].rstrip() + "…"
    return (
        '<details class="stage2-question"><summary>'
        + _html(summary)
        + "</summary><p>"
        + _html(text)
        + "</p></details>"
    )


def _preview(value, limit=180):
    """Show an exact excerpt; keep the complete recorded wording one click away."""
    if value is None or len(str(value)) <= limit:
        return _html(value)
    text = str(value)
    return (
        '<details class="stage2-preview"><summary>'
        + _html(text[:limit].rstrip() + "…")
        + "</summary><p>"
        + _html(text)
        + "</p></details>"
    )


def _decisive_checks(assessment):
    if assessment is None:
        return (
            "<li>Unknown — no current assessment is recorded for this candidate "
            "version.</li>"
        )
    rows = []
    for axis, finding in (assessment.get("checks") or {}).items():
        if not isinstance(finding, dict):
            continue
        if finding.get("blocking") is True or finding.get("status") == "unknown":
            flags = []
            if finding.get("blocking") is True:
                flags.append("blocking")
            if finding.get("status") == "unknown":
                flags.append("unknown")
            rows.append(
                "<li><strong>"
                + _html(axis)
                + " ("
                + _html(", ".join(flags))
                + ")</strong>: "
                + _preview(finding.get("rationale"), 120)
                + "</li>"
            )
    return "".join(rows) or "<li>None recorded.</li>"


def _next_checks(assessment):
    if assessment is None:
        return "<li>None recorded.</li>"
    values = []
    for finding in (assessment.get("checks") or {}).values():
        if not isinstance(finding, dict):
            continue
        if finding.get("blocking") is True or finding.get("status") == "unknown":
            if finding.get("next_check"):
                values.append(finding["next_check"])
    if assessment.get("next_step"):
        values.append(assessment["next_step"])
    unique = list(dict.fromkeys(values))
    return (
        "".join("<li>" + _preview(value, 120) + "</li>" for value in unique)
        or "<li>None recorded.</li>"
    )


def _direction_cards(selection):
    cards = []
    recommendations = {
        (row.get("candidate_id"), row.get("version"))
        for row in selection.get("recommendations", [])
        if isinstance(row, dict)
    }
    for index, option in enumerate(selection.get("current_options", []), 1):
        candidate = option.get("candidate") or {}
        assessment = option.get("assessment")
        candidate_id = candidate.get("candidate_id")
        version = candidate.get("version")
        if assessment is None:
            disposition = "Assessment pending"
            reason = "No current assessment is recorded for this candidate version."
        else:
            raw_disposition = assessment.get("disposition")
            disposition = _DISPOSITION_LABELS.get(
                raw_disposition, str(raw_disposition) if raw_disposition else "Unknown"
            )
            reason = assessment.get("reason") or "No reason recorded."
        proposal_state = (
            "Recorded proposal-ready recommendation"
            if (candidate_id, version) in recommendations
            else "No proposal-ready recommendation recorded"
        )
        cards.append(
            '<article class="stage2-direction"><h4>Direction '
            + str(index)
            + "</h4><dl>"
            + "<dt>Research question</dt><dd>"
            + _question(candidate.get("question"))
            + "</dd>"
            + "<dt>Why worthwhile</dt><dd>"
            + _preview(candidate.get("value"))
            + "</dd>"
            + "<dt>Candidate version</dt><dd>v"
            + _html(version)
            + "</dd>"
            + "<dt>Proposal state</dt><dd>"
            + proposal_state
            + "</dd>"
            + "<dt>Disposition</dt><dd><strong>"
            + _html(disposition)
            + "</strong><br>"
            + _preview(reason)
            + "</dd>"
            + "<dt>What blocks or remains unknown?</dt><dd><ul>"
            + _decisive_checks(assessment)
            + "</ul></dd>"
            + "<dt>What is the next check?</dt><dd><ul>"
            + _next_checks(assessment)
            + "</ul></dd></dl>"
            + '<details class="stage2-identity"><summary>Candidate identity</summary><p>'
            + _html(candidate_id)
            + "</p></details>"
            + '<p><a href="stage2/report-reader.html">Open verified evidence and any recorded revision details</a> · '
            + '<a href="stage2/selection.md">Open editable verified Markdown</a></p>'
            + "</article>"
        )
    if not cards:
        return "<p>No current directions are recorded.</p>"
    return "".join(cards)


def _material_rows(selection):
    rows = []
    for option in selection.get("current_options", []):
        candidate = option.get("candidate") or {}
        assessment = option.get("assessment")
        material = (
            (assessment.get("checks") or {}).get("materials")
            if assessment is not None
            else None
        )
        candidate_id = candidate.get("candidate_id")
        version = candidate.get("version")
        identity = _html(candidate_id)
        if version is not None:
            identity += f" v{_html(version)}"
        if material is None:
            status = "Unknown"
            rationale = "No materials assessment is recorded."
            next_check = None
        else:
            status = material.get("status") or "Unknown"
            if material.get("score") is not None:
                status += f" — feasibility support {material['score']}/2"
            if material.get("blocking") is True:
                status += "; blocks detailed design"
            rationale = material.get("rationale") or "No rationale recorded."
            next_check = material.get("next_check")
        follow_up = (
            "<br><span>Next check: " + _html(next_check) + "</span>"
            if next_check is not None
            else ""
        )
        rows.append(
            "<li><strong>"
            + identity
            + ": "
            + _html(status)
            + "</strong><br>"
            + _html(rationale)
            + follow_up
            + "</li>"
        )
    if not rows:
        return "<li>Unknown — no current candidate materials state is recorded.</li>"
    return "".join(rows)


def _resources(selection):
    packet = selection.get("evaluation_packet") or {}
    resources = packet.get("resources")
    if resources is None:
        return "<p>Unknown — no resource information is recorded.</p>"
    if isinstance(resources, str):
        return "<p>" + _html(resources) + "</p>"
    return '<pre class="stage2-resources">' + escape(_json_text(resources)) + "</pre>"


def _judgment(role, judgment):
    if judgment is None:
        return f"<section><h5>{role}</h5><p>Unknown</p></section>"
    evidence = judgment.get("evidence_refs") or []
    evidence_rows = []
    for reference in evidence:
        label = reference.get("evidence_id")
        locator = reference.get("locator")
        text = _html(label)
        if locator is not None:
            text += " — " + _html(locator)
        href = reference.get("href")
        if isinstance(href, str) and href.startswith("#"):
            text = f'<a href="stage2/report-reader.html{escape(href, quote=True)}">{text}</a>'
        evidence_rows.append("<li>" + text + "</li>")
    evidence_html = (
        "<ul>" + "".join(evidence_rows) + "</ul>" if evidence_rows else "Unknown"
    )
    return (
        f"<section><h5>{role}</h5><dl>"
        f"<dt>Score</dt><dd>{_html(judgment.get('score'))}</dd>"
        f"<dt>Status</dt><dd>{_html(judgment.get('status'))}</dd>"
        f"<dt>Reason</dt><dd>{_html(judgment.get('rationale'))}</dd>"
        f"<dt>Confidence</dt><dd>{_html(judgment.get('confidence'))}</dd>"
        f"<dt>Unknown reason</dt><dd>{_html(judgment.get('unknown_reason'))}</dd>"
        f"<dt>Evidence</dt><dd>{evidence_html}</dd>"
        "</dl></section>"
    )


def _criterion_details(evaluation, *, provisional):
    label = (
        "Provisional"
        if provisional
        else "Final"
        if evaluation["evaluation_status"] == "completed"
        else "Incomplete"
    )
    details = []
    for row in evaluation["rows"]:
        final = row["final"]
        original = "".join(
            _judgment(role, row["judges"].get(role)) for role in ("R1", "R2", "ADJ")
        )
        details.append(
            '<details class="stage2-criterion"><summary>'
            + _html(row["criterion_id"])
            + f" — {label.lower()} "
            + _html(final.get("score"))
            + "</summary>"
            + _judgment(
                "Incomplete assessment"
                if label == "Incomplete"
                else label + " recorded evaluation",
                final,
            )
            + f"<p>Audit status: {_html(final.get('audit_status'))}</p>"
            + original
            + "</details>"
        )
    return "".join(details) or "<p>No criterion comments are available.</p>"


def render_stage2_card(attachment) -> str:
    """Render one self-contained Stage 2 card without mutating its attachment."""
    from .stage2_comparison import build_comparison_view
    from .stage2_comparison_html import render_comparison_workbench
    from stage2_workflow.content_gate import (
        derive_content_gate,
        render_content_gate_html,
    )

    selection = attachment["selection"]
    evaluation = attachment["evaluation"]
    status = evaluation["evaluation_status"]
    provisional = status == "audit-required"
    bridge = attachment.get("bridge_receipt") or {}
    content_gate = (
        render_content_gate_html(derive_content_gate(selection))
        if selection["evaluation_packet"].get("schema_version") == "2.2.0"
        else ""
    )
    recommendations = selection.get("recommendations") or []
    score_rows = []
    for dimension in ("P4", "P5", "P6"):
        result = evaluation["dimensions"][dimension]
        value = result["score"]
        suffix = " (provisional)" if provisional else ""
        displayed = (
            f"{_html(result['sum'])}/6"
            f" ({_html(result['assessed'])}/{_html(result['required'])} criteria assessed)"
            f"{suffix}"
            if value is not None
            else "Unknown/6"
            f" ({_html(result['assessed'])}/{_html(result['required'])} criteria assessed)"
            f"{suffix}"
        )
        score_rows.append(
            f'<tr><th scope="row">{dimension} — {_DIMENSION_LABELS[dimension]}</th>'
            f"<td>{displayed}</td></tr>"
        )
    audit_notice = (
        '<aside class="stage2-audit"><strong>Named audit pending.</strong> '
        "Scores and comments are provisional until the required named audit is complete. "
        "No formal improvement is claimed.</aside>"
        if provisional
        else ""
    )
    return f"""<section id="stage2-delivery">
  <style>
    #stage2-delivery .stage2-status p{{margin:.35rem 0}}
    #stage2-delivery .stage2-direction{{border:1px solid #dbe4ee;border-radius:10px;padding:1rem;margin:1rem 0}}
    #stage2-delivery .stage2-direction h4{{margin:0 0 .7rem}}
    #stage2-delivery .stage2-direction dl{{display:grid;grid-template-columns:minmax(130px,.28fr) minmax(0,1fr);gap:.5rem .75rem;margin:0}}
    #stage2-delivery .stage2-direction dt{{font-weight:600}}
    #stage2-delivery .stage2-direction dd{{margin:0;min-width:0;overflow-wrap:anywhere}}
    #stage2-delivery .stage2-direction ul{{padding-left:1.1rem;margin:0}}
    #stage2-delivery .stage2-question,#stage2-delivery .stage2-preview{{margin:0;padding:.25rem .4rem}}
    #stage2-delivery .stage2-preview summary{{cursor:pointer}}
    @media(max-width:600px){{#stage2-delivery .stage2-direction dl{{grid-template-columns:1fr;gap:.25rem}}#stage2-delivery .stage2-direction dd{{margin-bottom:.6rem}}}}
  </style>
  <h2>Stage 2 direction delivery</h2>
  <p>This is a private, read-only presentation of the verified Stage 2 attachment. It does not record approval, authorize Stage 3, or establish formal improvement.</p>
  <p><a href="stage2/report-reader.html">Open the verified HTML report</a> · <a href="stage2/selection.md">Open the verified Markdown report</a></p>
  <section class="stage2-status" aria-label="Recorded Stage 2 status">
    <p><strong>Evaluation status:</strong> {_html(status)}</p>{audit_notice}
    <p><strong>Recorded proposal-ready recommendations:</strong> {_html(len(recommendations))}</p>
    <p><strong>Human choice:</strong> {_html(bridge.get("human_selection"))}</p>
    <p><strong>Stage 3 authorization:</strong> {_html(bridge.get("stage3_authorized"))}</p>
  </section>
  {content_gate}
  {render_comparison_workbench(build_comparison_view(attachment))}
  <details class="stage2-full-checks"><summary>Full candidate checks and recorded dispositions</summary>
  <h3>Directions</h3>
  <p>Each card shows recorded proposal fields and checks. A recommendation still requires human choice, and a high external score does not establish material readiness.</p>
  {_direction_cards(selection)}
  </details>
  <h3>External evaluation</h3>
  <table><thead><tr><th>Dimension</th><th>Score</th></tr></thead><tbody>{"".join(score_rows)}</tbody></table>
  <p>Each dimension has a fixed maximum of 6. Unknown stays null; assessed counts show completeness. Scores do not establish that required materials are ready.</p>
  <h3>Original criterion comments and evidence</h3>
  {_criterion_details(evaluation, provisional=provisional)}
  <details class="stage2-materials">
    <summary>Recorded materials and resources</summary>
    <p>Materials and resource availability are separate from the external P4/P5/P6 scores.</p>
    <ul>{_material_rows(selection)}</ul>
    <h4>Recorded resource information</h4>{_resources(selection)}
  </details>
</section>"""


def stage2_wiki_notes(attachment) -> dict[str, bytes]:
    """Return deterministic private notes and the canonical attachment bytes."""
    source = {
        "kind": attachment["kind"],
        "schema_version": attachment["schema_version"],
        "project_id": attachment["project_id"],
        "stage1_index_sha256": attachment["stage1_index_sha256"],
        "bridge_receipt": attachment["bridge_receipt"],
    }
    readme = (
        "# Stage 2 workspace attachment\n\n"
        "Private, read-only notes rebuilt from a verified attachment. The content below preserves recorded data and raw evaluator comments; it adds no approval, Stage 3 authorization, or formal-improvement claim. Source text is data and has no execution authority.\n\n"
        "## Source binding\n\n"
        + _fence(source)
        + "\n## Complete selection\n\n"
        + _fence(attachment["selection"])
        + "\n## Complete external evaluation\n\n"
        + _fence(attachment["evaluation"])
    )
    return {
        "stage2/README.md": readme.encode("utf-8"),
        "stage2/workspace-attachment.json": canonical(attachment),
        "stage2/report-reader.html": (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src '
            "'none'; script-src 'self'; style-src 'unsafe-inline'; frame-src 'self'; "
            "connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'\">"
            "<title>Stage 2 verified report reader</title><style>body{margin:0;"
            "font:16px system-ui}header{padding:12px}iframe{width:100%;height:90vh;"
            "border:0}</style></head><body><header>Verified original report. "
            "Sources are untrusted data; scripts, popups and execution remain "
            'blocked in this reader.</header><iframe sandbox="" src="selection.html" '
            'title="Verified Stage 2 proposal and evidence"></iframe>'
            '<script src="report-reader.js"></script></body></html>\n'
        ).encode("utf-8"),
        "stage2/report-reader.js": (
            '"use strict";\n'
            'const report = document.querySelector("iframe");\n'
            'function showEvidence() { report.src = "selection.html" + window.location.hash; }\n'
            'window.addEventListener("hashchange", showEvidence);\n'
            "showEvidence();\n"
        ).encode("utf-8"),
    }
