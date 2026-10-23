"""Human-readable views for pure Stage 2 decision-card projections."""

from html import escape


_MAPPING_NOTES = {
    "mapped": (
        "Mapped to this question. Mapping does not establish feasibility or "
        "availability."
    ),
    "unknown": (
        "The mapping or a recorded resource status is unknown. This is not "
        "evidence that the resource does not exist."
    ),
    "unmapped": (
        "No same-version resource is mapped to this question. This is not "
        "evidence that no data or resource exists."
    ),
}


def _plain(value):
    if value is None:
        return "Not recorded"
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _html(value):
    return escape(_plain(value), quote=True)


def _md(value):
    text = escape(_plain(value), quote=False)
    for character in "\\`*_{}[]()#+!|>":
        text = text.replace(character, "\\" + character)
    return text


def _md_list(values, empty="None recorded"):
    return "\n".join(f"- {_md(value)}" for value in values) or f"- {_md(empty)}"


def _html_list(values, empty="None recorded"):
    rows = "".join(f"<li>{_html(value)}</li>" for value in values)
    return f"<ul>{rows or '<li>' + _html(empty) + '</li>'}</ul>"


def _resource_markdown(use):
    resource = use["resource"]
    ref = use.get("resource_ref")
    fit = ref.get("fit_status") if isinstance(ref, dict) else "unmapped"
    lines = [
        f"- **{_md(resource.get('category'))}: {_md(resource.get('name'))}**",
        f"  - Resource ID: {_md(resource.get('resource_id'))}",
        f"  - Required: {_md(resource.get('required'))}",
        f"  - Availability: {_md(resource.get('status'))}",
        f"  - Question fit: {_md(fit)}",
        "  - Question-specific purpose: "
        + _md(ref.get("purpose") if isinstance(ref, dict) else None),
        f"  - Resource purpose: {_md(resource.get('purpose'))}",
        f"  - Version: {_md(resource.get('version'))}",
        f"  - Access conditions: {_md(resource.get('access_conditions'))}",
        f"  - License: {_md(resource.get('license'))}",
        f"  - Cost basis: {_md(resource.get('cost_basis'))}",
        f"  - Checked at: {_md(resource.get('checked_at'))}",
        f"  - URL: {_md(resource.get('url'))}",
        "  - Question evidence IDs: "
        + _md(
            ", ".join(ref.get("evidence_ids", []))
            if isinstance(ref, dict) and ref.get("evidence_ids")
            else None
        ),
        "  - Resource evidence IDs: "
        + _md(", ".join(resource.get("evidence_ids", [])) or None),
        f"  - Resource-ref source: {_md(use.get('resource_ref_source'))}",
        "  - Resource source: " + _md(use.get("resource_source", use.get("source"))),
    ]
    for limitation in resource.get("limitations", []):
        lines.append(f"  - Limitation: {_md(limitation)}")
    for alternative in resource.get("alternatives", []):
        lines.append(f"  - Alternative: {_md(alternative)}")
    return "\n".join(lines)


def _resource_html(use):
    resource = use["resource"]
    ref = use.get("resource_ref")
    fit = ref.get("fit_status") if isinstance(ref, dict) else "unmapped"
    details = [
        ("Resource ID", resource.get("resource_id")),
        ("Required", resource.get("required")),
        ("Availability", resource.get("status")),
        ("Question fit", fit),
        (
            "Question-specific purpose",
            ref.get("purpose") if isinstance(ref, dict) else None,
        ),
        ("Resource purpose", resource.get("purpose")),
        ("Version", resource.get("version")),
        ("Access conditions", resource.get("access_conditions")),
        ("License", resource.get("license")),
        ("Cost basis", resource.get("cost_basis")),
        ("Checked at", resource.get("checked_at")),
        ("URL", resource.get("url")),
        (
            "Question evidence IDs",
            ", ".join(ref.get("evidence_ids", []))
            if isinstance(ref, dict) and ref.get("evidence_ids")
            else None,
        ),
        (
            "Resource evidence IDs",
            ", ".join(resource.get("evidence_ids", [])) or None,
        ),
        ("Resource-ref source", use.get("resource_ref_source")),
        ("Resource source", use.get("resource_source", use.get("source"))),
    ]
    items = "".join(
        f"<dt>{escape(label)}</dt><dd>{_html(value)}</dd>" for label, value in details
    )
    limitations = _html_list(resource.get("limitations", []))
    alternatives = _html_list(resource.get("alternatives", []))
    return (
        '<article class="decision-resource">'
        f"<h5>{_html(resource.get('category'))}: {_html(resource.get('name'))}</h5>"
        f"<dl>{items}</dl><h6>Limitations</h6>{limitations}"
        f"<h6>Alternatives</h6>{alternatives}</article>"
    )


def _claim_markdown(claim):
    return "\n".join(
        [
            f"- **{_md(claim.get('text'))}**",
            f"  - Status: {_md(claim.get('status'))}",
            "  - Question IDs: "
            + _md(", ".join(claim.get("question_ids", [])) or None),
        ]
    )


def _claim_html(claim):
    return (
        '<article class="decision-contribution">'
        f"<h5>{_html(claim.get('text'))}</h5><dl>"
        f"<dt>Status</dt><dd>{_html(claim.get('status'))}</dd>"
        "<dt>Question IDs</dt><dd>"
        f"{_html(', '.join(claim.get('question_ids', [])) or None)}</dd>"
        "</dl></article>"
    )


def _prior_work_markdown(prior):
    review = prior.get("review")
    if not isinstance(review, dict):
        return "- Not recorded for this candidate version."
    lines = [
        f"- Review status: {_md(review.get('review_status'))}",
        f"- Positioning: {_md(review.get('positioning'))}",
    ]
    for row in review.get("comparisons", []):
        lines.extend(
            [
                f"- **{_md(row.get('work_id'))} / {_md(row.get('version_id'))}**",
                f"  - Role: {_md(row.get('role'))}",
                f"  - Established: {_md(row.get('established'))}",
                f"  - Overlap: {_md(row.get('overlap'))}",
                f"  - Difference: {_md(row.get('difference'))}",
                "  - Evidence IDs: "
                + _md(", ".join(row.get("evidence_ids", [])) or None),
            ]
        )
    return "\n".join(lines)


def _prior_work_html(prior):
    review = prior.get("review")
    if not isinstance(review, dict):
        return "<p>Not recorded for this candidate version.</p>"
    comparisons = []
    for row in review.get("comparisons", []):
        comparisons.append(
            '<article class="decision-precedent">'
            f"<h4>{_html(row.get('work_id'))} / {_html(row.get('version_id'))}</h4>"
            "<dl>"
            f"<dt>Role</dt><dd>{_html(row.get('role'))}</dd>"
            f"<dt>Established</dt><dd>{_html(row.get('established'))}</dd>"
            f"<dt>Overlap</dt><dd>{_html(row.get('overlap'))}</dd>"
            f"<dt>Difference</dt><dd>{_html(row.get('difference'))}</dd>"
            "<dt>Evidence IDs</dt><dd>"
            + _html(", ".join(row.get("evidence_ids", [])) or None)
            + "</dd>"
            "</dl></article>"
        )
    return (
        "<dl>"
        f"<dt>Review status</dt><dd>{_html(review.get('review_status'))}</dd>"
        f"<dt>Positioning</dt><dd>{_html(review.get('positioning'))}</dd>"
        "</dl>"
        + ("".join(comparisons) or "<p>No closest-work comparison recorded.</p>")
    )


def render_decision_cards_markdown(cards):
    """Render decision cards as deterministic readable Markdown."""

    lines = ["# Stage 2 decision cards", ""]
    for card in cards["cards"]:
        lines.extend(
            [
                (
                    f"## {_md(card.get('candidate_id'))} "
                    f"v{_md(card.get('candidate_version'))}"
                ),
                "",
                f"**Candidate question:** {_md(card.get('candidate_question'))}",
                f"**Research mode:** {_md(card.get('research_mode'))}",
                "**Scientific argument:** "
                + _md(card.get("scientific_argument_status")),
                "",
                "### Closest precedent",
                _prior_work_markdown(card.get("closest_prior_work", {})),
                "",
                "### Scientific questions",
            ]
        )
        questions = card.get("scientific_questions", [])
        if not questions:
            lines.append(
                "No scientific questions are recorded for this candidate version."
            )
        for question_card in questions:
            question = question_card["question"]
            status = question_card["resource_mapping_status"]
            lines.extend(
                [
                    "",
                    f"#### {_md(question.get('text'))}",
                    f"- Question ID: {_md(question.get('question_id'))}",
                    (
                        f"- Priority / status: {_md(question.get('priority'))} / "
                        f"{_md(question.get('status'))}"
                    ),
                    f"- Object: {_md(question.get('object'))}",
                    f"- Intended claim: {_md(question.get('intended_claim'))}",
                    (
                        f"- Resource mapping: **{_md(status)}**; "
                        f"{_md(_MAPPING_NOTES[status])}"
                    ),
                    "- Contribution:",
                    "\n".join(
                        _claim_markdown(row)
                        for row in question_card.get("contributions", [])
                    )
                    or "- None recorded",
                    "- Mapped resources:",
                ]
            )
            uses = question_card.get("resource_uses", [])
            lines.extend(_resource_markdown(use) for use in uses)
            if not uses:
                lines.append("- None mapped for this candidate version.")
            lines.extend(
                [
                    "- Next checks:",
                    _md_list(
                        [
                            row.get("text")
                            for row in question_card.get("next_checks", [])
                        ]
                    ),
                ]
            )
        lines.extend(
            [
                "",
                "### Unassigned contribution claims",
                "\n".join(
                    _claim_markdown(claim)
                    for claim in card.get("contribution", [])
                    if not any(
                        question_id
                        in {
                            row["question"].get("question_id")
                            for row in card.get("scientific_questions", [])
                        }
                        for question_id in claim.get("question_ids", [])
                    )
                )
                or "- None recorded",
                "",
                "### Suggested approach",
                _md(card.get("suggested_approach")),
                "",
                "### Requirements",
                _md_list(card.get("requirements", [])),
                "",
                "### Same-version resources not mapped to a question",
            ]
        )
        unused = card.get("unmapped_resources", [])
        lines.extend(_resource_markdown(row) for row in unused)
        if not unused:
            lines.append("- None recorded.")
        lines.extend(
            [
                "",
                "### Limitations",
                _md_list(card.get("limitations", [])),
                "",
                "### Alternatives",
            ]
        )
        alternatives = [
            alternative
            for row in card.get("alternatives", [])
            for alternative in row.get("alternatives", [])
        ]
        lines.extend(
            [
                _md_list(alternatives),
                "",
                "### Next checks",
                _md_list([row.get("text") for row in card.get("next_checks", [])]),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_decision_cards_html(cards):
    """Render decision cards as an escaped, script-free HTML fragment."""

    rendered = [
        '<section class="stage2-decision-cards"><h1>Stage 2 decision cards</h1>'
    ]
    for card in cards["cards"]:
        questions = []
        for question_card in card.get("scientific_questions", []):
            question = question_card["question"]
            status = question_card["resource_mapping_status"]
            uses = (
                "".join(
                    _resource_html(use)
                    for use in question_card.get("resource_uses", [])
                )
                or "<p>None mapped for this candidate version.</p>"
            )
            contributions = (
                "".join(
                    _claim_html(row) for row in question_card.get("contributions", [])
                )
                or "<p>None recorded.</p>"
            )
            next_checks = _html_list(
                [row.get("text") for row in question_card.get("next_checks", [])]
            )
            questions.append(
                '<article class="decision-question">'
                f"<h3>{_html(question.get('text'))}</h3><dl>"
                f"<dt>Question ID</dt><dd>{_html(question.get('question_id'))}</dd>"
                "<dt>Priority / status</dt><dd>"
                f"{_html(question.get('priority'))} / {_html(question.get('status'))}"
                "</dd>"
                f"<dt>Object</dt><dd>{_html(question.get('object'))}</dd>"
                "<dt>Intended claim</dt><dd>"
                f"{_html(question.get('intended_claim'))}</dd>"
                f"<dt>Resource mapping</dt><dd><strong>{_html(status)}</strong>; "
                f"{_html(_MAPPING_NOTES[status])}</dd>"
                f"</dl><h4>Contribution</h4>{contributions}"
                f"<h4>Mapped resources</h4>{uses}<h4>Next checks</h4>{next_checks}"
                "</article>"
            )
        question_html = "".join(questions) or (
            "<p>No scientific questions are recorded for this candidate version.</p>"
        )
        unused = (
            "".join(_resource_html(row) for row in card.get("unmapped_resources", []))
            or "<p>None recorded.</p>"
        )
        alternatives = [
            alternative
            for row in card.get("alternatives", [])
            for alternative in row.get("alternatives", [])
        ]
        question_ids = {
            row["question"].get("question_id")
            for row in card.get("scientific_questions", [])
        }
        unassigned = (
            "".join(
                _claim_html(claim)
                for claim in card.get("contribution", [])
                if not any(
                    question_id in question_ids
                    for question_id in claim.get("question_ids", [])
                )
            )
            or "<p>None recorded.</p>"
        )
        rendered.append(
            '<article class="decision-card">'
            f"<h2>{_html(card.get('candidate_id'))} "
            f"v{_html(card.get('candidate_version'))}</h2>"
            "<p><strong>Candidate question:</strong> "
            f"{_html(card.get('candidate_question'))}</p>"
            f"<p><strong>Research mode:</strong> {_html(card.get('research_mode'))}</p>"
            "<p><strong>Scientific argument:</strong> "
            f"{_html(card.get('scientific_argument_status'))}</p>"
            "<h3>Closest precedent</h3>"
            f"{_prior_work_html(card.get('closest_prior_work', {}))}"
            f"<h3>Scientific questions</h3>{question_html}"
            f"<h3>Unassigned contribution claims</h3>{unassigned}"
            f"<h3>Suggested approach</h3><p>{_html(card.get('suggested_approach'))}</p>"
            f"<h3>Requirements</h3>{_html_list(card.get('requirements', []))}"
            f"<h3>Same-version resources not mapped to a question</h3>{unused}"
            f"<h3>Limitations</h3>{_html_list(card.get('limitations', []))}"
            f"<h3>Alternatives</h3>{_html_list(alternatives)}"
            "<h3>Next checks</h3>"
            f"{_html_list([row.get('text') for row in card.get('next_checks', [])])}"
            "</article>"
        )
    rendered.append("</section>")
    return "".join(rendered)
