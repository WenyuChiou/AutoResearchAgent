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


def _label(value, ui_text):
    return escape((ui_text or {}).get(value, value), quote=True)


def _html_list(values, empty="None recorded", *, ui_text=None):
    rows = "".join(f"<li>{_html(value)}</li>" for value in values)
    return f"<ul>{rows or '<li>' + _label(empty, ui_text) + '</li>'}</ul>"


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


def _resource_html(use, ui_text=None):
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
        f"<dt>{_label(label, ui_text)}</dt><dd>{_html(value)}</dd>"
        for label, value in details
    )
    limitations = _html_list(resource.get("limitations", []), ui_text=ui_text)
    alternatives = _html_list(resource.get("alternatives", []), ui_text=ui_text)
    return (
        '<article class="decision-resource">'
        f"<h5>{_html(resource.get('category'))}: {_html(resource.get('name'))}</h5>"
        f"<dl>{items}</dl><h6>{_label('Limitations', ui_text)}</h6>{limitations}"
        f"<h6>{_label('Alternatives', ui_text)}</h6>{alternatives}</article>"
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


def _claim_html(claim, ui_text=None):
    return (
        '<article class="decision-contribution">'
        f"<h5>{_html(claim.get('text'))}</h5><dl>"
        f"<dt>{_label('Status', ui_text)}</dt><dd>{_html(claim.get('status'))}</dd>"
        f"<dt>{_label('Question IDs', ui_text)}</dt><dd>"
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


def _prior_work_html(prior, ui_text=None):
    review = prior.get("review")
    if not isinstance(review, dict):
        return f"<p>{_label('Not recorded for this candidate version.', ui_text)}</p>"
    comparisons = []
    for row in review.get("comparisons", []):
        comparisons.append(
            '<article class="decision-precedent">'
            f"<h4>{_html(row.get('work_id'))} / {_html(row.get('version_id'))}</h4>"
            "<dl>"
            f"<dt>{_label('Role', ui_text)}</dt><dd>{_html(row.get('role'))}</dd>"
            f"<dt>{_label('Established', ui_text)}</dt><dd>{_html(row.get('established'))}</dd>"
            f"<dt>{_label('Overlap', ui_text)}</dt><dd>{_html(row.get('overlap'))}</dd>"
            f"<dt>{_label('Difference', ui_text)}</dt><dd>{_html(row.get('difference'))}</dd>"
            f"<dt>{_label('Evidence IDs', ui_text)}</dt><dd>"
            + _html(", ".join(row.get("evidence_ids", [])) or None)
            + "</dd>"
            "</dl></article>"
        )
    return (
        "<dl>"
        f"<dt>{_label('Review status', ui_text)}</dt><dd>{_html(review.get('review_status'))}</dd>"
        f"<dt>{_label('Positioning', ui_text)}</dt><dd>{_html(review.get('positioning'))}</dd>"
        "</dl>"
        + (
            "".join(comparisons)
            or f"<p>{_label('No closest-work comparison recorded.', ui_text)}</p>"
        )
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


def render_decision_cards_html(cards, *, ui_text=None):
    """Render decision cards as an escaped, script-free HTML fragment."""

    rendered = [
        '<section class="stage2-decision-cards"><h1>'
        + _label("Stage 2 decision cards", ui_text)
        + "</h1>"
    ]
    for card in cards["cards"]:
        questions = []
        for question_card in card.get("scientific_questions", []):
            question = question_card["question"]
            status = question_card["resource_mapping_status"]
            uses = (
                "".join(
                    _resource_html(use, ui_text)
                    for use in question_card.get("resource_uses", [])
                )
                or f"<p>{_label('None mapped for this candidate version.', ui_text)}</p>"
            )
            contributions = (
                "".join(
                    _claim_html(row, ui_text)
                    for row in question_card.get("contributions", [])
                )
                or f"<p>{_label('None recorded.', ui_text)}</p>"
            )
            next_checks = _html_list(
                [row.get("text") for row in question_card.get("next_checks", [])],
                ui_text=ui_text,
            )
            questions.append(
                '<article class="decision-question">'
                f"<h3>{_html(question.get('text'))}</h3><dl>"
                f"<dt>{_label('Question ID', ui_text)}</dt><dd>{_html(question.get('question_id'))}</dd>"
                f"<dt>{_label('Priority / status', ui_text)}</dt><dd>"
                f"{_html(question.get('priority'))} / {_html(question.get('status'))}"
                "</dd>"
                f"<dt>{_label('Object', ui_text)}</dt><dd>{_html(question.get('object'))}</dd>"
                f"<dt>{_label('Intended claim', ui_text)}</dt><dd>"
                f"{_html(question.get('intended_claim'))}</dd>"
                f"<dt>{_label('Resource mapping', ui_text)}</dt><dd><strong>{_html(status)}</strong>; "
                f"{_label(_MAPPING_NOTES[status], ui_text)}</dd>"
                f"</dl><h4>{_label('Contribution', ui_text)}</h4>{contributions}"
                f"<h4>{_label('Mapped resources', ui_text)}</h4>{uses}"
                f"<h4>{_label('Next checks', ui_text)}</h4>{next_checks}"
                "</article>"
            )
        question_html = "".join(questions) or (
            f"<p>{_label('No scientific questions are recorded for this candidate version.', ui_text)}</p>"
        )
        unused = (
            "".join(
                _resource_html(row, ui_text)
                for row in card.get("unmapped_resources", [])
            )
            or f"<p>{_label('None recorded.', ui_text)}</p>"
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
                _claim_html(claim, ui_text)
                for claim in card.get("contribution", [])
                if not any(
                    question_id in question_ids
                    for question_id in claim.get("question_ids", [])
                )
            )
            or f"<p>{_label('None recorded.', ui_text)}</p>"
        )
        rendered.append(
            '<article class="decision-card">'
            f"<h2>{_html(card.get('candidate_id'))} "
            f"v{_html(card.get('candidate_version'))}</h2>"
            f"<p><strong>{_label('Candidate question:', ui_text)}</strong> "
            f"{_html(card.get('candidate_question'))}</p>"
            f"<p><strong>{_label('Research mode:', ui_text)}</strong> {_html(card.get('research_mode'))}</p>"
            f"<p><strong>{_label('Scientific argument:', ui_text)}</strong> "
            f"{_html(card.get('scientific_argument_status'))}</p>"
            f"<h3>{_label('Closest precedent', ui_text)}</h3>"
            f"{_prior_work_html(card.get('closest_prior_work', {}), ui_text)}"
            f"<h3>{_label('Scientific questions', ui_text)}</h3>{question_html}"
            f"<h3>{_label('Unassigned contribution claims', ui_text)}</h3>{unassigned}"
            f"<h3>{_label('Suggested approach', ui_text)}</h3><p>{_html(card.get('suggested_approach'))}</p>"
            f"<h3>{_label('Requirements', ui_text)}</h3>{_html_list(card.get('requirements', []), ui_text=ui_text)}"
            f"<h3>{_label('Same-version resources not mapped to a question', ui_text)}</h3>{unused}"
            f"<h3>{_label('Limitations', ui_text)}</h3>{_html_list(card.get('limitations', []), ui_text=ui_text)}"
            f"<h3>{_label('Alternatives', ui_text)}</h3>{_html_list(alternatives, ui_text=ui_text)}"
            f"<h3>{_label('Next checks', ui_text)}</h3>"
            f"{_html_list([row.get('text') for row in card.get('next_checks', [])], ui_text=ui_text)}"
            "</article>"
        )
    rendered.append("</section>")
    return "".join(rendered)
