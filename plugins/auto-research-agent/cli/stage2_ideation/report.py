"""Pure source-rich proposal views for Stage 2 literature and ideation."""

import copy
import hashlib
import ipaddress
import re
from html import escape as html_escape
from urllib.parse import quote, urlsplit, urlunsplit

from stage2_common import canonical_hash, validate_packet

from .extraction import validate_extraction
from .integration import build_next_packet
from .tables_report import render_tables_html, render_tables_markdown

VERSION = "1.0.0"
NOTICE = (
    "DRAFT: independent checking and user selection remain pending. "
    "This ideation companion never promotes checker state; the checked selection "
    "report remains authoritative for disposition and choice."
)


def _unknown(value):
    return "unknown" if value is None else value


def _evidence_view(row, sources):
    source = sources[row["source_id"]]
    return {
        **copy.deepcopy(row),
        "source_sha256": source["sha256"],
        "evidence_level": source["evidence_level"],
    }


def build_proposal_view(packet, source_root, raw_proposal, extraction, snapshot_sha256):
    """Validate all inputs and return the common Markdown/HTML proposal view."""
    validate_packet(packet, source_root)
    result = validate_extraction(raw_proposal, extraction, packet, snapshot_sha256)
    sources = {row["source_id"]: row for row in packet["sources"]}
    bibliography = []
    for row in result["bibliography"]:
        source = sources[row["source_id"]]
        bibliography.append(
            {
                "source_id": row["source_id"],
                "work_id": row["work_id"],
                "version_id": row["version_id"],
                "source_sha256": source["sha256"],
                "evidence_level": source["evidence_level"],
                "title": _unknown(row["title"]),
                "authors": _unknown(row["authors"]),
                "year": _unknown(row["year"]),
                "identifier": _unknown(row["identifier"]),
                "roles": copy.deepcopy(row["roles"]),
            }
        )
    view = {
        "kind": "Stage2IdeationProposalView",
        "schema_version": VERSION,
        "status": "draft-pending-independent-check-and-user-selection",
        "notice": NOTICE,
        "packet_sha256": canonical_hash(packet),
        "snapshot_sha256": snapshot_sha256,
        "raw_proposal_sha256": hashlib.sha256(raw_proposal.encode("utf-8")).hexdigest(),
        "extraction_sha256": canonical_hash(result),
        "original_raw_proposal": raw_proposal,
        "brief": copy.deepcopy(packet["brief"]),
        "resources": packet["resources"],
        "starting_comparison": packet["comparison"],
        "bibliography": bibliography,
        "comparison_rows": copy.deepcopy(result["comparison_rows"]),
        "candidates": copy.deepcopy(result["candidates"]),
        "evidence": [_evidence_view(row, sources) for row in packet["evidence"]],
        "packet_unresolved": copy.deepcopy(packet["unresolved"]),
        "proposal_unresolved": copy.deepcopy(result["unresolved"]),
        "receipt": copy.deepcopy(result["receipt"]),
        "validation_boundary": {
            "factual_source_validation": (
                "passed: source bytes, hashes, work/version bindings, and exact "
                "evidence excerpts were validated against the supplied packet"
            ),
            "source_metadata_identity_verified": False,
            "source_metadata_note": (
                "Bibliographic metadata is reproduced as extracted; this renderer "
                "does not independently verify title, authors, year, or identifier."
            ),
            "scientific_validity_verified": False,
            "scientific_validation_note": (
                "Comparisons, mechanisms, novelty, value, and feasibility remain "
                "supplied proposals pending independent checking."
            ),
        },
    }
    if packet.get("schema_version") in {"2.2.0", "2.3.0", "2.4.0"}:
        table_packet = build_next_packet(
            packet, source_root, raw_proposal, extraction, snapshot_sha256
        )["packet"]
        view["research_tables"] = copy.deepcopy(table_packet["research_tables"])
        view["table_packet"] = table_packet
    return view


def _md(value):
    value = str(value).replace("\r", "")
    escaped = value.replace("\\", "\\\\")
    for character in "`*_{}[]()#+-.!|<>":
        escaped = escaped.replace(character, f"\\{character}")
    return escaped.replace("\n", " ")


def _fence(value):
    value = str(value).replace("\r\n", "\n").replace("\r", "\n")
    longest = max((len(run) for run in re.findall(r"`+", value)), default=2)
    fence = "`" * max(3, longest + 1)
    return [fence, value, fence]


def _md_list(values):
    return [f"- {_md(value)}" for value in values] or ["- unknown"]


def _source_url(identifier):
    if not isinstance(identifier, str):
        return None
    try:
        parsed = urlsplit(identifier)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        return None
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or any(c.isspace() for c in identifier):
        return None
    # A URL parser accepts punctuation that can close a Markdown destination.
    # Canonicalize a real hostname, rather than trusting netloc as output text.
    try:
        if ":" in host:
            address = ipaddress.IPv6Address(host)
            if address.scope_id is not None:
                return None
            host = "[" + str(address) + "]"
        else:
            host = host.encode("idna").decode("ascii")
            if len(host) > 253 or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in host.split(".")
            ):
                return None
    except (UnicodeError, ValueError):
        return None
    try:
        if parsed.port is not None:
            return None
    except ValueError:
        return None
    return urlunsplit(
        (
            parsed.scheme,
            host,
            quote(parsed.path, safe="/:@-._~!$&'*,;=%"),
            quote(parsed.query, safe="=&:@-._~!$'*,;/%"),
            quote(parsed.fragment, safe="-._~"),
        )
    )


def _md_identifier(identifier):
    url = _source_url(identifier)
    return f"[{_md(identifier)}]({url})" if url else _md(identifier)


def _md_source_ref(row):
    return f"{_md(row['source_id'])} / {_md(row['work_id'])} / {_md(row['version_id'])}"


def render_proposal_markdown(view):
    """Render a validated proposal view as inert English Markdown bytes."""
    lines = [
        "# DRAFT: Stage 2 literature and ideation proposal",
        "",
        _md(view["notice"]),
        "",
        "## Validation boundary",
        "",
        f"- Source binding validation: {_md(view['validation_boundary']['factual_source_validation'])}",
        f"- Source metadata identity verified: {str(view['validation_boundary']['source_metadata_identity_verified']).lower()}",
        f"- Metadata note: {_md(view['validation_boundary']['source_metadata_note'])}",
        f"- Scientific validity verified: {str(view['validation_boundary']['scientific_validity_verified']).lower()}",
        f"- Scientific note: {_md(view['validation_boundary']['scientific_validation_note'])}",
        "",
        "## Provenance",
        "",
        f"- Packet SHA-256: `{view['packet_sha256']}`",
        f"- Snapshot SHA-256: `{view['snapshot_sha256']}`",
        f"- Raw proposal SHA-256: `{view['raw_proposal_sha256']}`",
        f"- Extraction SHA-256: `{view['extraction_sha256']}`",
        "",
        "## Research scope",
        "",
        f"Original scope: {_md(view['brief']['original_description'])}",
        "",
        f"Resources: {_md(view['resources'])}",
        "",
        f"Starting comparison: {_md(view['starting_comparison'])}",
        "",
        "## Bibliography",
        "",
    ]
    if not view["bibliography"]:
        lines.extend(["No bibliography rows were extracted.", ""])
    for index, row in enumerate(view["bibliography"], 1):
        lines.extend(
            [
                f"### Bibliography {index}: {_md(row['source_id'])}",
                "",
                f"- Title: {_md(row['title'])}",
                f"- Authors: {_md(row['authors'])}",
                f"- Year: {_md(row['year'])}",
                f"- Identifier: {_md_identifier(row['identifier'])}",
                f"- Roles: {', '.join(_md(value) for value in row['roles']) or 'unknown'}",
                f"- Source / work / version: {_md_source_ref(row)}",
                f"- Source SHA-256: `{row['source_sha256']}`",
                f"- Evidence level: {_md(row['evidence_level'])}",
                "",
            ]
        )
    lines.extend(["## Supplied literature comparison", ""])
    if not view["comparison_rows"]:
        lines.extend(["No comparison rows were extracted.", ""])
    for index, row in enumerate(view["comparison_rows"], 1):
        lines.extend(
            [
                f"### Comparison {index}: {_md(row['dimension'])}",
                "",
                f"- Finding: {_md(row['finding'])}",
                f"- Comparability: {_md(row['comparability'])}",
                f"- Noncomparability: {_md(_unknown(row['noncomparability']))}",
                f"- Supporting evidence IDs: {', '.join(_md(value) for value in row['evidence_ids']) or 'unknown'}",
                "- Supporting sources:",
            ]
        )
        for role in row["source_roles"]:
            lines.append(
                f"  - {_md_source_ref(role)}; role: {_md(role['role'])}; evidence: "
                f"{', '.join(_md(value) for value in role['evidence_ids']) or 'unknown'}"
            )
        if not row["source_roles"]:
            lines.append("  - unknown")
        lines.append("- Shared study/data relationships:")
        for relation in row["shared_relationships"]:
            refs = ", ".join(_md_source_ref(ref) for ref in relation["source_refs"])
            lines.append(
                f"  - {_md(relation['relationship'])}: {_md(relation['detail'])}; "
                f"sources: {refs or 'unknown'}; evidence: "
                f"{', '.join(_md(value) for value in relation['evidence_ids']) or 'unknown'}"
            )
        if not row["shared_relationships"]:
            lines.append("  - unknown")
        lines.append("")
    lines.extend(["## Candidate directions (unassessed proposals)", ""])
    if not view["candidates"]:
        lines.extend(
            [
                "No candidate directions were extracted. This is an explicit empty draft, not a negative scientific judgment.",
                "",
            ]
        )
    for row in view["candidates"]:
        candidate = row["candidate"]
        lines.extend(
            [
                f"### {_md(candidate['candidate_id'])} v{candidate['version']} — {_md(row['route'])}",
                "",
                f"- Question: {_md(candidate['question'])}",
                f"- Research mode: {_md(candidate['research_mode'])}",
                f"- Opportunity: {_md(candidate['opportunity'])}",
                f"- Value: {_md(candidate['value'])}",
                f"- Approach: {_md(candidate['approach'])}",
                f"- Mechanism: {_md(row['mechanism'])}",
                "- Closest work:",
            ]
        )
        for ref in row["closest_work_refs"]:
            lines.append(
                f"  - {_md_source_ref(ref)}; evidence: "
                f"{', '.join(_md(value) for value in ref['evidence_ids']) or 'unknown'}"
            )
        if not row["closest_work_refs"]:
            lines.append("  - unknown")
        for label, values in (
            ("Strong alternatives", row["strong_alternatives"]),
            ("Change conditions", row["change_mind_conditions"]),
            ("Requirements", candidate["requirements"]),
            ("Limitations", candidate["limitations"]),
        ):
            lines.extend([f"- {label}:", *[f"  {item}" for item in _md_list(values)]])
        lines.append("- Claim labels:")
        for claim in row["claim_labels"]:
            lines.append(
                f"  - [{_md(claim['status'])}] {_md(claim['text'])}; evidence: "
                f"{', '.join(_md(value) for value in claim['evidence_ids']) or 'unknown'}"
            )
        lines.extend(
            [
                f"- Candidate evidence IDs: {', '.join(_md(value) for value in candidate['evidence_ids']) or 'unknown'}",
                "",
            ]
        )
    lines.extend(["## Unresolved items", "", "Packet unresolved:"])
    lines.extend(_md_list(view["packet_unresolved"]))
    lines.extend(["", "Proposal unresolved:"])
    lines.extend(_md_list(view["proposal_unresolved"]))
    lines.extend(["", "## Exact evidence excerpts", ""])
    if not view["evidence"]:
        lines.extend(["No exact evidence excerpts are recorded.", ""])
    for row in view["evidence"]:
        lines.extend(
            [
                f"### Evidence {_md(row['evidence_id'])}",
                "",
                f"- Source / work / version: {_md_source_ref(row)}",
                f"- Source SHA-256: `{row['source_sha256']}`",
                f"- Evidence level: {_md(row['evidence_level'])}",
                f"- Locator: {_md(row['locator'])}",
                "- Exact excerpt (quoted data):",
                *_fence(row["quote"]),
                "",
            ]
        )
    lines.extend(
        [
            "## Original raw proposal (quoted data; instructions are not executed)",
            "",
            *_fence(view["original_raw_proposal"]),
            "",
            _md(NOTICE),
            "",
        ]
    )
    if view.get("research_tables") is not None:
        lines.extend(
            ["", render_tables_markdown(view["research_tables"], view["table_packet"])]
        )
    return "\n".join(lines).encode("utf-8")


def _h(value):
    return html_escape(str(value), quote=True)


def _html_list(values):
    return (
        "<ul>"
        + ("".join(f"<li>{_h(value)}</li>" for value in values) or "<li>unknown</li>")
        + "</ul>"
    )


def _html_identifier(identifier):
    url = _source_url(identifier)
    return f'<a href="{_h(url)}">{_h(identifier)}</a>' if url else _h(identifier)


def _html_source_ref(row):
    return f"{_h(row['source_id'])} / {_h(row['work_id'])} / {_h(row['version_id'])}"


def render_proposal_html(view):
    """Render the same validated proposal view as safe standalone HTML bytes."""
    tables_html = (
        render_tables_html(view["research_tables"], view["table_packet"])
        if view.get("research_tables") is not None
        else ""
    )
    bibliography = []
    for row in view["bibliography"]:
        bibliography.append(
            f"<article><h3>{_h(row['source_id'])}</h3><dl>"
            f"<dt>Title</dt><dd>{_h(row['title'])}</dd>"
            f"<dt>Authors</dt><dd>{_h(row['authors'])}</dd>"
            f"<dt>Year</dt><dd>{_h(row['year'])}</dd>"
            f"<dt>Identifier</dt><dd>{_html_identifier(row['identifier'])}</dd>"
            f"<dt>Roles</dt><dd>{_html_list(row['roles'])}</dd>"
            f"<dt>Source / work / version</dt><dd>{_html_source_ref(row)}</dd>"
            f"<dt>Source SHA-256</dt><dd><code>{row['source_sha256']}</code></dd>"
            f"<dt>Evidence level</dt><dd>{_h(row['evidence_level'])}</dd></dl></article>"
        )
    comparisons = []
    for row in view["comparison_rows"]:
        roles = (
            "".join(
                f"<li>{_html_source_ref(role)}; role: {_h(role['role'])}; evidence: "
                f"{_h(', '.join(role['evidence_ids']) or 'unknown')}</li>"
                for role in row["source_roles"]
            )
            or "<li>unknown</li>"
        )
        relationships = (
            "".join(
                f"<li>{_h(relation['relationship'])}: {_h(relation['detail'])}; sources: "
                f"{_h(', '.join(_html_source_ref(ref) for ref in relation['source_refs']) or 'unknown')}; "
                f"evidence: {_h(', '.join(relation['evidence_ids']) or 'unknown')}</li>"
                for relation in row["shared_relationships"]
            )
            or "<li>unknown</li>"
        )
        comparisons.append(
            f"<article><h3>{_h(row['dimension'])}</h3><dl>"
            f"<dt>Finding</dt><dd>{_h(row['finding'])}</dd>"
            f"<dt>Comparability</dt><dd>{_h(row['comparability'])}</dd>"
            f"<dt>Noncomparability</dt><dd>{_h(_unknown(row['noncomparability']))}</dd>"
            f"<dt>Supporting evidence IDs</dt><dd>{_h(', '.join(row['evidence_ids']) or 'unknown')}</dd>"
            f"<dt>Supporting sources</dt><dd><ul>{roles}</ul></dd>"
            f"<dt>Shared study/data relationships</dt><dd><ul>{relationships}</ul></dd>"
            "</dl></article>"
        )
    candidates = []
    for row in view["candidates"]:
        candidate = row["candidate"]
        closest = (
            "".join(
                f"<li>{_html_source_ref(ref)}; evidence: {_h(', '.join(ref['evidence_ids']) or 'unknown')}</li>"
                for ref in row["closest_work_refs"]
            )
            or "<li>unknown</li>"
        )
        claims = "".join(
            f"<li><strong>{_h(claim['status'])}</strong>: {_h(claim['text'])}; evidence: "
            f"{_h(', '.join(claim['evidence_ids']) or 'unknown')}</li>"
            for claim in row["claim_labels"]
        )
        candidates.append(
            f"<article><h3>{_h(candidate['candidate_id'])} v{candidate['version']} — {_h(row['route'])}</h3><dl>"
            f"<dt>Question</dt><dd>{_h(candidate['question'])}</dd>"
            f"<dt>Research mode</dt><dd>{_h(candidate['research_mode'])}</dd>"
            f"<dt>Opportunity</dt><dd>{_h(candidate['opportunity'])}</dd>"
            f"<dt>Value</dt><dd>{_h(candidate['value'])}</dd>"
            f"<dt>Approach</dt><dd>{_h(candidate['approach'])}</dd>"
            f"<dt>Mechanism</dt><dd>{_h(row['mechanism'])}</dd>"
            f"<dt>Closest work</dt><dd><ul>{closest}</ul></dd>"
            f"<dt>Strong alternatives</dt><dd>{_html_list(row['strong_alternatives'])}</dd>"
            f"<dt>Change conditions</dt><dd>{_html_list(row['change_mind_conditions'])}</dd>"
            f"<dt>Requirements</dt><dd>{_html_list(candidate['requirements'])}</dd>"
            f"<dt>Limitations</dt><dd>{_html_list(candidate['limitations'])}</dd>"
            f"<dt>Claim labels</dt><dd><ul>{claims}</ul></dd>"
            f"<dt>Candidate evidence IDs</dt><dd>{_h(', '.join(candidate['evidence_ids']) or 'unknown')}</dd>"
            "</dl></article>"
        )
    evidence = "".join(
        f"<article><h3>Evidence {_h(row['evidence_id'])}</h3><dl>"
        f"<dt>Source / work / version</dt><dd>{_html_source_ref(row)}</dd>"
        f"<dt>Source SHA-256</dt><dd><code>{row['source_sha256']}</code></dd>"
        f"<dt>Evidence level</dt><dd>{_h(row['evidence_level'])}</dd>"
        f"<dt>Locator</dt><dd>{_h(row['locator'])}</dd></dl>"
        f"<h4>Exact excerpt (quoted data)</h4><pre>{_h(row['quote'])}</pre></article>"
        for row in view["evidence"]
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DRAFT: Stage 2 literature and ideation proposal</title>
<style>body{{max-width:1100px;margin:auto;padding:2rem;font:16px/1.55 system-ui;color:#172033}}section,article{{border:1px solid #d9dfeb;border-radius:10px;padding:1rem;margin:1rem 0}}.notice{{background:#fff2c7;border-left:5px solid #a66b00}}dl{{display:grid;grid-template-columns:minmax(150px,230px) 1fr;gap:.45rem 1rem}}dt{{font-weight:700}}dd{{margin:0;overflow-wrap:anywhere}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fa;padding:1rem}}code{{overflow-wrap:anywhere}}@media(max-width:650px){{dl{{grid-template-columns:1fr}}}}.table-wrap{{overflow-x:auto}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #d9dfeb;padding:.6rem;text-align:left;vertical-align:top}}
</style>
</head><body><header><h1>DRAFT: Stage 2 literature and ideation proposal</h1><p class="notice">{_h(view["notice"])}</p></header>
<main>{tables_html}<section><h2>Validation boundary</h2><ul><li>Source binding validation: {_h(view["validation_boundary"]["factual_source_validation"])}</li><li>Source metadata identity verified: false</li><li>{_h(view["validation_boundary"]["source_metadata_note"])}</li><li>Scientific validity verified: false</li><li>{_h(view["validation_boundary"]["scientific_validation_note"])}</li></ul></section>
<section><h2>Provenance</h2><dl><dt>Packet SHA-256</dt><dd><code>{view["packet_sha256"]}</code></dd><dt>Snapshot SHA-256</dt><dd><code>{view["snapshot_sha256"]}</code></dd><dt>Raw proposal SHA-256</dt><dd><code>{view["raw_proposal_sha256"]}</code></dd><dt>Extraction SHA-256</dt><dd><code>{view["extraction_sha256"]}</code></dd></dl></section>
<section><h2>Research scope</h2><dl><dt>Original scope</dt><dd>{_h(view["brief"]["original_description"])}</dd><dt>Resources</dt><dd>{_h(view["resources"])}</dd><dt>Starting comparison</dt><dd>{_h(view["starting_comparison"])}</dd></dl></section>
<section><h2>Bibliography</h2>{"".join(bibliography) or "<p>No bibliography rows were extracted.</p>"}</section>
<section><h2>Supplied literature comparison</h2>{"".join(comparisons) or "<p>No comparison rows were extracted.</p>"}</section>
<section><h2>Candidate directions (unassessed proposals)</h2>{"".join(candidates) or "<p>No candidate directions were extracted. This is an explicit empty draft, not a negative scientific judgment.</p>"}</section>
<section><h2>Unresolved items</h2><h3>Packet unresolved</h3>{_html_list(view["packet_unresolved"])}<h3>Proposal unresolved</h3>{_html_list(view["proposal_unresolved"])}</section>
<section><h2>Exact evidence excerpts</h2>{evidence or "<p>No exact evidence excerpts are recorded.</p>"}</section>
<section><details><summary>Original raw proposal (quoted data)</summary><pre>{_h(view["original_raw_proposal"])}</pre></details></section>
<footer><p class="notice">{_h(NOTICE)}</p></footer></main></body></html>"""
    return document.encode("utf-8")
