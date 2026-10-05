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


def _direction_rows(selection):
    rows = []
    for option in selection.get("current_options", []):
        candidate = option.get("candidate") or {}
        assessment = option.get("assessment")
        candidate_id = candidate.get("candidate_id")
        version = candidate.get("version")
        identity = _html(candidate_id)
        if version is not None:
            identity += f" v{_html(version)}"
        if assessment is None:
            disposition = "Assessment pending"
            reason = "No current assessment is recorded for this candidate version."
        else:
            raw_disposition = assessment.get("disposition")
            disposition = _DISPOSITION_LABELS.get(
                raw_disposition, str(raw_disposition) if raw_disposition else "Unknown"
            )
            reason = assessment.get("reason") or "No reason recorded."
        rows.append(
            "<li><p><strong>"
            + _html(candidate.get("question"))
            + "</strong></p><strong>"
            + identity
            + ": "
            + _html(disposition)
            + "</strong><br>"
            + _html(reason)
            + "</li>"
        )
    if not rows:
        return "<li>No current direction dispositions are recorded.</li>"
    return "".join(rows)


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
    selection = attachment["selection"]
    evaluation = attachment["evaluation"]
    status = evaluation["evaluation_status"]
    provisional = status == "audit-required"
    score_rows = []
    for dimension in ("P4", "P5", "P6"):
        result = evaluation["dimensions"][dimension]
        value = result["score"]
        suffix = " (provisional)" if provisional and value is not None else ""
        displayed = (
            f"{_html(value)}% ({_html(result['sum'])}/6){suffix}"
            if value is not None
            else f"Unknown ({_html(result['assessed'])}/{_html(result['required'])} criteria assessed)"
        )
        score_rows.append(
            f'<tr><th scope="row">{dimension}</th><td>{displayed}</td></tr>'
        )
    audit_notice = (
        '<aside class="stage2-audit"><strong>Named audit pending.</strong> '
        "Scores and comments are provisional until the required named audit is complete. "
        "No formal improvement is claimed.</aside>"
        if provisional
        else ""
    )
    return f"""<section id="stage2-delivery">
  <h2>Stage 2 direction delivery</h2>
  <p>This is a private, read-only presentation of the verified Stage 2 attachment. It does not record approval, authorize Stage 3, or establish formal improvement.</p>
  <p><a href="stage2/report-reader.html">Open the verified HTML report</a> · <a href="stage2/selection.md">Open the verified Markdown report</a></p>
  <h3>Direction disposition</h3>
  <p>These are recorded prehuman dispositions. A recommendation still requires human review.</p>
  <ul>{_direction_rows(selection)}</ul>
  <aside class="stage2-materials">
    <h3>Materials state</h3>
    <p>Materials and resource availability are shown independently from the external P4/P5/P6 scores.</p>
    <ul>{_material_rows(selection)}</ul>
    <h4>Recorded resource information</h4>{_resources(selection)}
  </aside>
  <h3>External evaluation</h3>
  <p>Status: {_html(status)}</p>{audit_notice}
  <table><thead><tr><th>Dimension</th><th>Score</th></tr></thead><tbody>{"".join(score_rows)}</tbody></table>
  <h3>Original criterion comments and evidence</h3>
  {_criterion_details(evaluation, provisional=provisional)}
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
