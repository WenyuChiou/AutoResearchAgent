"""Safe, pure projections for the external Stage 2 v3 evaluation.

The input is a mapping with exactly these top-level keys::

    rubric_id, evaluation_status, dimensions, rows, provenance, errors

``evaluation_status`` is ``completed``, ``audit-required``, ``pending``, or ``failed``. Dimensions
are P4/P5/P6 mappings with ``score`` (0--100 or null), ``sum`` (0--6 or null),
``max=6``, ``assessed`` (0--3), and ``required=3``. A completed view has all
nine rubric rows in rubric order. Each row has ``criterion_id``, ``final``,
``judges``, and ``disagreement``. Final judgments contain ``score``, ``status``,
``rationale``, ``evidence_refs``, ``confidence``, ``unknown_reason``, and
``audit_status``. R1/R2/ADJ omit only ``audit_status``. Evidence references are
``{evidence_id, locator, href}``; href may be a local fragment or safe relative
path. Provenance contains the four named SHA-256 bindings.

The functions do not read files or mutate the input. Invalid web, file, drive,
UNC, private-host, and parent-traversal links are retained as evidence labels
but made non-clickable in every projection.
"""

import copy
import re
from html import escape as html_escape
from urllib.parse import unquote, urlsplit


RUBRIC_ID = "stage2-general-v3"
CRITERIA = (
    "P4V3.FIDELITY",
    "P4V3.COMPARABILITY",
    "P4V3.SYNTHESIS",
    "P5V3.PRECEDENT",
    "P5V3.CONTRIBUTION",
    "P5V3.REVISION",
    "P6V3.VALUE",
    "P6V3.FEASIBILITY",
    "P6V3.CHOICE",
)
DIMENSIONS = {
    name: CRITERIA[index : index + 3]
    for index, name in zip((0, 3, 6), ("P4", "P5", "P6"))
}
_HASH = re.compile(r"^[0-9a-f]{64}$")
_ANCHOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_TOP_KEYS = {
    "rubric_id",
    "evaluation_status",
    "dimensions",
    "rows",
    "provenance",
    "errors",
}
_DIMENSION_KEYS = {"score", "sum", "max", "assessed", "required"}
_ROW_KEYS = {"criterion_id", "final", "judges", "disagreement"}
_FINAL_KEYS = {
    "score",
    "status",
    "rationale",
    "evidence_refs",
    "confidence",
    "unknown_reason",
    "audit_status",
}
_JUDGE_KEYS = _FINAL_KEYS - {"audit_status"}
_JUDGES_KEYS = {"R1", "R2", "ADJ"}
_EVIDENCE_KEYS = {"evidence_id", "locator", "href"}
_PROVENANCE_KEYS = {
    "selection_sha256",
    "source_sha256",
    "rubric_sha256",
    "bundle_sha256",
}


class EvaluationProjectionError(ValueError):
    """The supplied public evaluation view violates its rendering contract."""


def _require(condition, message):
    if not condition:
        raise EvaluationProjectionError(message)


def _exact_keys(value, expected, label):
    _require(isinstance(value, dict), f"{label} must be an object")
    _require(set(value) == expected, f"{label} fields must be {sorted(expected)}")


def _text(value, label, *, nullable=False):
    if nullable and value is None:
        return
    _require(
        isinstance(value, str) and value.strip(), f"{label} must be non-empty text"
    )


def _safe_local_href(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
        return None
    if "\\" in value or value.startswith(("/", "//")):
        return None
    if not re.fullmatch(r"[A-Za-z0-9_./%:#~-]+", value):
        return None
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.query:
        return None
    if parsed.path == "":
        return value if parsed.fragment and _ANCHOR.fullmatch(parsed.fragment) else None
    decoded = unquote(parsed.path)
    if any(ord(char) <= 32 or char in "<>\"'()\\" for char in decoded):
        return None
    if re.match(r"^[A-Za-z]:", decoded):
        return None
    parts = decoded.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    if parsed.fragment and not _ANCHOR.fullmatch(parsed.fragment):
        return None
    return value


def _validate_evidence(refs, label):
    _require(isinstance(refs, list), f"{label} must be a list")
    normalized = []
    seen = set()
    for index, ref in enumerate(refs):
        item_label = f"{label}[{index}]"
        _exact_keys(ref, _EVIDENCE_KEYS, item_label)
        _text(ref["evidence_id"], f"{item_label}.evidence_id")
        _text(ref["locator"], f"{item_label}.locator", nullable=True)
        _require(ref["evidence_id"] not in seen, f"{label} has duplicate evidence IDs")
        seen.add(ref["evidence_id"])
        normalized.append({**ref, "href": _safe_local_href(ref["href"])})
    return normalized


def _validate_judgment(value, label, *, final=False):
    _exact_keys(value, _FINAL_KEYS if final else _JUDGE_KEYS, label)
    _require(value["status"] in {"assessed", "unknown"}, f"{label}.status is invalid")
    _text(value["rationale"], f"{label}.rationale")
    _require(
        value["confidence"] in {"high", "medium", "low"},
        f"{label}.confidence is invalid",
    )
    normalized = copy.deepcopy(value)
    normalized["evidence_refs"] = _validate_evidence(
        value["evidence_refs"], f"{label}.evidence_refs"
    )
    if value["status"] == "assessed":
        _require(
            type(value["score"]) is int and value["score"] in {0, 1, 2},
            f"{label}.score must be 0, 1, or 2",
        )
        _require(
            value["unknown_reason"] is None,
            f"{label}.unknown_reason must be null when assessed",
        )
        _require(bool(value["evidence_refs"]), f"{label} needs evidence when assessed")
    else:
        _require(value["score"] is None, f"{label}.score must be null when unknown")
        _text(value["unknown_reason"], f"{label}.unknown_reason")
    if final:
        _text(value["audit_status"], f"{label}.audit_status")
    return normalized


def _dimension_from_rows(rows, criterion_ids):
    selected = [row["final"] for row in rows if row["criterion_id"] in criterion_ids]
    assessed = sum(row["status"] == "assessed" for row in selected)
    if len(selected) != 3 or assessed != 3:
        return {
            "score": None,
            "sum": None,
            "max": 6,
            "assessed": assessed,
            "required": 3,
        }
    raw_sum = sum(row["score"] for row in selected)
    return {
        "score": round(100 * raw_sum / 6, 6),
        "sum": raw_sum,
        "max": 6,
        "assessed": 3,
        "required": 3,
    }


def validate_projection(view):
    """Validate, recompute score math, and return a sanitized deep copy."""
    _exact_keys(view, _TOP_KEYS, "evaluation view")
    _require(view["rubric_id"] == RUBRIC_ID, "unsupported rubric_id")
    status = view["evaluation_status"]
    _require(
        status in {"completed", "audit-required", "pending", "failed"},
        "invalid evaluation_status",
    )
    scored = status in {"completed", "audit-required"}
    _require(isinstance(view["errors"], list), "errors must be a list")
    for index, error in enumerate(view["errors"]):
        _text(error, f"errors[{index}]")
    _require(
        status != "failed" or bool(view["errors"]), "failed evaluation needs an error"
    )

    _exact_keys(view["provenance"], _PROVENANCE_KEYS, "provenance")
    for key, value in view["provenance"].items():
        _require(
            value is None or (isinstance(value, str) and _HASH.fullmatch(value)),
            f"provenance.{key} must be SHA-256 or null",
        )
        if scored:
            _require(value is not None, f"completed evaluation needs provenance.{key}")

    _require(isinstance(view["rows"], list), "rows must be a list")
    normalized_rows = []
    for index, row in enumerate(view["rows"]):
        label = f"rows[{index}]"
        _exact_keys(row, _ROW_KEYS, label)
        _require(row["criterion_id"] in CRITERIA, f"{label}.criterion_id is invalid")
        _require(
            type(row["disagreement"]) is bool, f"{label}.disagreement must be boolean"
        )
        final = _validate_judgment(row["final"], f"{label}.final", final=True)
        _exact_keys(row["judges"], _JUDGES_KEYS, f"{label}.judges")
        r1 = row["judges"]["R1"]
        r2 = row["judges"]["R2"]
        for role, judgment in (("R1", r1), ("R2", r2)):
            _require(judgment is not None or not scored, f"{label} requires {role}")
        r1 = _validate_judgment(r1, f"{label}.judges.R1") if r1 is not None else None
        r2 = _validate_judgment(r2, f"{label}.judges.R2") if r2 is not None else None
        adj = row["judges"]["ADJ"]
        if adj is not None:
            adj = _validate_judgment(adj, f"{label}.judges.ADJ")
        if scored and row["disagreement"]:
            _require(adj is not None, f"{label} disagreement needs ADJ")
        normalized_rows.append(
            {
                "criterion_id": row["criterion_id"],
                "final": final,
                "judges": {"R1": r1, "R2": r2, "ADJ": adj},
                "disagreement": row["disagreement"],
            }
        )
    ids = [row["criterion_id"] for row in normalized_rows]
    _require(len(ids) == len(set(ids)), "criterion rows must be unique")
    if scored:
        _require(
            ids == list(CRITERIA),
            "completed evaluation needs all nine criteria in rubric order",
        )

    _exact_keys(view["dimensions"], set(DIMENSIONS), "dimensions")
    normalized_dimensions = {}
    for dimension, criteria in DIMENSIONS.items():
        supplied = view["dimensions"][dimension]
        _exact_keys(supplied, _DIMENSION_KEYS, f"dimensions.{dimension}")
        expected = _dimension_from_rows(normalized_rows, criteria)
        if not scored:
            expected["score"] = None
            expected["sum"] = None
        _require(
            supplied == expected,
            f"dimensions.{dimension} does not match criterion scores",
        )
        normalized_dimensions[dimension] = copy.deepcopy(expected)
    _require(
        not scored or not view["errors"],
        "completed evaluation cannot contain errors",
    )
    return {
        "rubric_id": RUBRIC_ID,
        "evaluation_status": status,
        "dimensions": normalized_dimensions,
        "rows": normalized_rows,
        "provenance": copy.deepcopy(view["provenance"]),
        "errors": list(view["errors"]),
    }


def evaluation_wiki_projection(view):
    """Return the validated, JSON-serializable wiki projection."""
    return validate_projection(view)


def _display(value):
    return "Unknown" if value is None else str(value)


def _md(value):
    text = _display(value).replace("\r", " ").replace("\n", " ")
    return re.sub(r"([\\`*_{}\[\]()<>#+.!|\-])", r"\\\1", text)


def _md_evidence(refs):
    if not refs:
        return "Unknown"
    rendered = []
    for ref in refs:
        label = ref["evidence_id"]
        if ref["locator"] is not None:
            label += f" — {ref['locator']}"
        rendered.append(f"[{_md(label)}]({ref['href']})" if ref["href"] else _md(label))
    return "; ".join(rendered)


def render_evaluation_markdown(view):
    """Render a validated v3 view as UTF-8 Markdown bytes."""
    data = validate_projection(view)
    lines = [
        "# External Stage 2 v3 evaluation",
        "",
        f"- Rubric: {_md(data['rubric_id'])}",
        f"- Status: {_md(data['evaluation_status'])}",
        "",
    ]
    if data["evaluation_status"] == "audit-required":
        lines.extend(
            [
                "## Named audit pending",
                "",
                "Scores and comments are provisional until the required named audit is complete. No formal improvement is claimed.",
                "",
            ]
        )
    elif data["evaluation_status"] != "completed":
        lines.extend(
            [
                "## Evaluation not completed",
                "",
                "No score has been inferred from an incomplete evaluator run.",
                "",
            ]
        )
    lines.extend(
        [
            "## Dimensions",
            "",
            "| Dimension | Score | Sum | Maximum | Assessed | Required |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for name, dimension in data["dimensions"].items():
        lines.append(
            f"| {name} | {_md(dimension['score'])} | {_md(dimension['sum'])} | 6 | {dimension['assessed']} | 3 |"
        )
    lines.append("")
    if data["errors"]:
        lines.extend(
            [
                "## Evaluation errors",
                "",
                *[f"- {_md(error)}" for error in data["errors"]],
                "",
            ]
        )
    if data["rows"]:
        lines.extend(["## Criterion details", ""])
    for row in data["rows"]:
        final = row["final"]
        lines.extend(
            [
                f"### {_md(row['criterion_id'])}",
                "",
                f"- Final score: {_md(final['score'])}",
                f"- Final status: {_md(final['status'])}",
                f"- Final rationale: {_md(final['rationale'])}",
                f"- Confidence: {_md(final['confidence'])}",
                f"- Unknown reason: {_md(final['unknown_reason'])}",
                f"- Audit status: {_md(final['audit_status'])}",
                f"- Evidence: {_md_evidence(final['evidence_refs'])}",
                f"- Disagreement: {'Yes' if row['disagreement'] else 'No'}",
                "",
            ]
        )
        for role in ("R1", "R2", "ADJ"):
            judgment = row["judges"][role]
            lines.append(f"#### {role}")
            lines.append("")
            if judgment is None:
                lines.extend(["Unknown", ""])
                continue
            lines.extend(
                [
                    f"- Score: {_md(judgment['score'])}",
                    f"- Status: {_md(judgment['status'])}",
                    f"- Rationale: {_md(judgment['rationale'])}",
                    f"- Confidence: {_md(judgment['confidence'])}",
                    f"- Unknown reason: {_md(judgment['unknown_reason'])}",
                    f"- Evidence: {_md_evidence(judgment['evidence_refs'])}",
                    "",
                ]
            )
    lines.extend(["## Provenance", ""])
    lines.extend(f"- {key}: {_md(value)}" for key, value in data["provenance"].items())
    lines.append("")
    return "\n".join(lines).encode("utf-8")


def _h(value):
    return html_escape(_display(value), quote=True)


def _html_evidence(refs):
    if not refs:
        return "<span>Unknown</span>"
    items = []
    for ref in refs:
        label = ref["evidence_id"] + (
            f" — {ref['locator']}" if ref["locator"] is not None else ""
        )
        content = (
            f'<a href="{_h(ref["href"])}">{_h(label)}</a>' if ref["href"] else _h(label)
        )
        items.append(f"<li>{content}</li>")
    return "<ul>" + "".join(items) + "</ul>"


def render_evaluation_html(view):
    """Render a validated v3 view as safe standalone UTF-8 HTML bytes."""
    data = validate_projection(view)
    dimensions = "".join(
        f"<tr><th>{name}</th><td>{_h(row['score'])}</td><td>{_h(row['sum'])}</td><td>6</td><td>{row['assessed']}</td><td>3</td></tr>"
        for name, row in data["dimensions"].items()
    )
    errors = (
        ""
        if not data["errors"]
        else "<section><h2>Evaluation errors</h2><ul>"
        + "".join(f"<li>{_h(error)}</li>" for error in data["errors"])
        + "</ul></section>"
    )
    criteria = []
    for row in data["rows"]:
        final = row["final"]
        judges = []
        for role in ("R1", "R2", "ADJ"):
            judgment = row["judges"][role]
            body = (
                "<p>Unknown</p>"
                if judgment is None
                else f"<dl><dt>Score</dt><dd>{_h(judgment['score'])}</dd><dt>Status</dt><dd>{_h(judgment['status'])}</dd><dt>Rationale</dt><dd>{_h(judgment['rationale'])}</dd><dt>Confidence</dt><dd>{_h(judgment['confidence'])}</dd><dt>Unknown reason</dt><dd>{_h(judgment['unknown_reason'])}</dd><dt>Evidence</dt><dd>{_html_evidence(judgment['evidence_refs'])}</dd></dl>"
            )
            judges.append(f"<details><summary>{role}</summary>{body}</details>")
        criteria.append(
            f"<article><h3>{_h(row['criterion_id'])}</h3><dl><dt>Final score</dt><dd>{_h(final['score'])}</dd><dt>Final status</dt><dd>{_h(final['status'])}</dd><dt>Final rationale</dt><dd>{_h(final['rationale'])}</dd><dt>Confidence</dt><dd>{_h(final['confidence'])}</dd><dt>Unknown reason</dt><dd>{_h(final['unknown_reason'])}</dd><dt>Audit status</dt><dd>{_h(final['audit_status'])}</dd><dt>Evidence</dt><dd>{_html_evidence(final['evidence_refs'])}</dd><dt>Disagreement</dt><dd>{'Yes' if row['disagreement'] else 'No'}</dd></dl>{''.join(judges)}</article>"
        )
    incomplete = (
        ""
        if data["evaluation_status"] == "completed"
        else "<section class=notice><h2>Named audit pending</h2><p>Scores and comments are provisional until the required named audit is complete. No formal improvement is claimed.</p></section>"
        if data["evaluation_status"] == "audit-required"
        else "<section class=notice><h2>Evaluation not completed</h2><p>No score has been inferred from an incomplete evaluator run.</p></section>"
    )
    provenance = "".join(
        f"<dt>{_h(key)}</dt><dd><code>{_h(value)}</code></dd>"
        for key, value in data["provenance"].items()
    )
    document = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>External Stage 2 v3 evaluation</title><style>body{{max-width:1100px;margin:auto;padding:2rem;font:16px/1.5 system-ui;color:#172033}}section,article{{border:1px solid #d9dfeb;border-radius:8px;padding:1rem;margin:1rem 0}}.notice{{background:#fff2c7}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #d9dfeb;padding:.5rem;text-align:left}}dl{{display:grid;grid-template-columns:minmax(140px,220px) 1fr;gap:.35rem 1rem}}dd{{margin:0;overflow-wrap:anywhere}}code{{overflow-wrap:anywhere}}details{{margin:.6rem 0;padding:.4rem;border:1px solid #e3e7ef}}@media(max-width:650px){{dl{{grid-template-columns:1fr}}}}</style></head><body><header><h1>External Stage 2 v3 evaluation</h1><p>Rubric: {_h(data["rubric_id"])}</p><p>Status: {_h(data["evaluation_status"])}</p></header>{incomplete}<section><h2>Dimensions</h2><table><thead><tr><th>Dimension</th><th>Score</th><th>Sum</th><th>Maximum</th><th>Assessed</th><th>Required</th></tr></thead><tbody>{dimensions}</tbody></table></section>{errors}<section><h2>Criterion details</h2>{"".join(criteria) or "<p>No criterion results are available.</p>"}</section><section><h2>Provenance</h2><dl>{provenance}</dl></section></body></html>"""
    return document.encode("utf-8")
