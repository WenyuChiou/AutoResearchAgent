"""Deterministic, inert Markdown rendering for a Stage 2 selection."""

import hashlib
import json
import re
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import quote

from stage2_common import Stage2Error
from stage2_check.bibliography import build_bibliography
from stage2_ideation.tables_report import render_tables_markdown

AXES = ("opportunity", "value", "answerability", "materials", "execution")
_SHA = re.compile(r"^[0-9a-f]{64}$")


def _text(value):
    """Render supplied prose on one inert Markdown line."""
    if not isinstance(value, str):
        raise Stage2Error("report-text-must-be-string")
    value = " ".join(value.replace("\r", "").split("\n"))
    escaped = value.replace("\\", "\\\\")
    for character in "`*_{}[]()#+-.!|<>":
        escaped = escaped.replace(character, f"\\{character}")
    return escaped


def _code(value):
    value = str(value)
    fence = "`" * (max((len(run) for run in re.findall(r"`+", value)), default=2) + 1)
    return f"{fence}{value}{fence}"


def _quote_block(value):
    if not isinstance(value, str):
        raise Stage2Error("report-quote-must-be-string")
    longest = max((len(run) for run in re.findall(r"`+", value)), default=2)
    fence = "`" * max(3, longest + 1)
    return [fence, value.replace("\r\n", "\n").replace("\r", "\n"), fence]


def _json_block(value):
    return _quote_block(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    )


def _safe_snapshot_path(value):
    if not isinstance(value, str):
        raise Stage2Error("report-source-path-must-be-string")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or "\\" in value
        or value != posix.as_posix()
        or any(part in {"", ".", ".."} for part in posix.parts)
        or not posix.parts
    ):
        raise Stage2Error(f"unsafe-report-source-path: {value!r}")
    return "/".join(quote(part, safe="") for part in posix.parts)


def _evidence_anchor(evidence_id):
    digest = hashlib.sha256(evidence_id.encode("utf-8")).hexdigest()[:16]
    return f"evidence-{digest}"


def _evidence_links(ids, evidence):
    links = []
    for evidence_id in ids:
        if evidence_id not in evidence:
            raise Stage2Error(f"report-unknown-evidence: {evidence_id}")
        links.append(f"[{_text(evidence_id)}](#{_evidence_anchor(evidence_id)})")
    return ", ".join(links) if links else "None recorded"


def _validate_bindings(selection, source_snapshots):
    if not isinstance(selection, dict) or selection.get("kind") != "Stage2Selection":
        raise Stage2Error("report-selection-invalid")
    packet = selection.get("evaluation_packet")
    if not isinstance(packet, dict):
        raise Stage2Error("report-evaluation-packet-missing")
    original_sources = {row["source_id"]: row for row in packet.get("sources", [])}
    snapshots = {}
    for source in source_snapshots:
        source_id = source.get("source_id")
        if source_id in snapshots:
            raise Stage2Error(f"report-duplicate-source: {source_id}")
        _safe_snapshot_path(source.get("path"))
        snapshots[source_id] = source
    if set(snapshots) != set(original_sources):
        raise Stage2Error("report-source-set-mismatch")
    for source_id, source in snapshots.items():
        original = original_sources[source_id]
        fields = ("source_id", "work_id", "version_id", "sha256", "evidence_level")
        if any(source.get(field) != original.get(field) for field in fields):
            raise Stage2Error(f"report-source-binding-mismatch: {source_id}")

    evidence = {}
    for row in packet.get("evidence", []):
        evidence_id = row.get("evidence_id")
        if evidence_id in evidence:
            raise Stage2Error(f"report-duplicate-evidence: {evidence_id}")
        source = snapshots.get(row.get("source_id"))
        if source is None:
            raise Stage2Error(f"report-evidence-source-missing: {evidence_id}")
        if row.get("work_id") != source.get("work_id") or row.get(
            "version_id"
        ) != source.get("version_id"):
            raise Stage2Error(f"report-evidence-binding-mismatch: {evidence_id}")
        evidence[evidence_id] = row

    histories = selection.get("candidate_histories", {})
    candidate_versions = {
        (candidate_id, row["version"]): row
        for candidate_id, history in histories.items()
        for row in history
    }
    for candidate_id, history in histories.items():
        if not history or any(
            row.get("candidate_id") != candidate_id for row in history
        ):
            raise Stage2Error(f"report-candidate-history-invalid: {candidate_id}")
        for candidate in history:
            _evidence_links(candidate.get("evidence_ids", []), evidence)
    current = selection.get("current_options", [])
    if len(current) != len(histories):
        raise Stage2Error("report-current-option-set-mismatch")
    for option in current:
        candidate = option.get("candidate", {})
        key = (candidate.get("candidate_id"), candidate.get("version"))
        history = histories.get(candidate.get("candidate_id"), [])
        if key not in candidate_versions or candidate != history[-1]:
            raise Stage2Error(f"report-current-option-mismatch: {key}")
    for event in selection.get("assessment_history", []):
        assessment = event.get("assessment", {})
        key = (assessment.get("candidate_id"), assessment.get("candidate_version"))
        if key not in candidate_versions:
            raise Stage2Error(f"report-assessment-candidate-missing: {key}")
        for axis in AXES:
            finding = assessment.get("checks", {}).get(axis)
            if finding is None:
                raise Stage2Error(f"report-assessment-axis-missing: {axis}")
            _evidence_links(finding.get("evidence_ids", []), evidence)
    bibliography = build_bibliography(packet, snapshots, evidence)
    return packet, snapshots, evidence, bibliography


def _bibliography(lines, bibliography, evidence):
    lines.extend(["## Accepted bibliography", ""])
    if not bibliography["available"]:
        lines.extend([bibliography["message"], ""])
        return
    for work in bibliography["works"]:
        authors = "; ".join(_text(author) for author in work["authors"])
        year = str(work["year"]) if work["year"] is not None else "not recorded"
        doi = (
            f"[{_text(work['doi'])}]({work['doi_href']})"
            if work["doi_href"]
            else _text(work["doi"])
            if work["doi"] is not None
            else "not recorded"
        )
        url = (
            f"[{_text(work['url'])}]({work['url_href']})"
            if work["url_href"]
            else _text(work["url"])
        )
        lines.extend(
            [
                f"### {_text(work['work_id'])} / {_text(work['version_id'])}",
                "",
                f"- Title: {_text(work['title'])}",
                f"- Authors: {authors}",
                f"- Year: {year}",
                f"- Venue: {_text(work['venue'])}",
                f"- DOI: {doi}",
                f"- URL: {url}",
                f"- Origin: {_text(work['origin'])}",
                f"- Recorded work evidence level: {_text(work['evidence_level'])}",
                "- Saved sources: "
                + (
                    ", ".join(
                        f"[{_text(source['source_id'])}]({_safe_snapshot_path(source['path'])}) "
                        f"(level={_text(source['evidence_level'])})"
                        for source in work["sources"]
                    )
                    or "none recorded"
                ),
                "- Recorded literature roles describe the saved Stage 1/2 classification; they are not semantic verification:",
            ]
        )
        lines.extend(
            [
                f"  - {_text(role['role'])}: {_text(role['reason'])}; "
                f"claims={_evidence_links(role['claim_ids'], evidence)}"
                for role in work["roles"]
            ]
            or ["  - None recorded"]
        )
        for version in work.get("supplemental_versions", []):
            lines.extend(
                [
                    "- Additional source version of the same study: "
                    + _text(version["version_id"]),
                    "  - Title: " + _text(version["title"]),
                    "  - Recorded evidence level: " + _text(version["evidence_level"]),
                    "  - Sources: "
                    + ", ".join(
                        f"[{_text(source['source_id'])}]({_safe_snapshot_path(source['path'])}) "
                        f"(level={_text(source['evidence_level'])})"
                        for source in version["sources"]
                    ),
                    "  - Claims: " + _evidence_links(version["claim_ids"], evidence),
                    "  - Roles: "
                    + "; ".join(
                        _text(role["role"]) + ": " + _text(role["reason"])
                        for role in version["roles"]
                    ),
                ]
            )
        lines.append("")


def _candidate_details(lines, candidate, evidence, level="###"):
    lines.extend(
        [
            f"{level} {_text(candidate['candidate_id'])} v{candidate['version']}",
            "",
            f"- Parent version: {candidate['parent_version'] if candidate['parent_version'] is not None else 'none'}",
            f"- Question: {_text(candidate['question'])}",
            f"- Research mode: {_text(candidate['research_mode'])}",
            f"- Opportunity: {_text(candidate['opportunity'])}",
            f"- Value: {_text(candidate['value'])}",
            f"- Approach: {_text(candidate['approach'])}",
            "",
            "Requirements:",
            *(
                [f"- {_text(item)}" for item in candidate["requirements"]]
                or ["- None recorded"]
            ),
            "",
            "Limitations:",
            *(
                [f"- {_text(item)}" for item in candidate["limitations"]]
                or ["- None recorded"]
            ),
            "",
            f"- Evidence: {_evidence_links(candidate['evidence_ids'], evidence)}",
            "",
        ]
    )


def _assessment_details(lines, assessment, evidence):
    lines.extend(
        [
            f"- Disposition: {_text(assessment['disposition'])}",
            f"- Reason: {_text(assessment['reason'])}",
            f"- Scope change requested: {'yes' if assessment['scope_change_requested'] else 'no'}",
            "",
            "| Axis | Status | Score | Concise supplied rationale | Evidence | Blocking | Next check |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for axis in AXES:
        finding = assessment["checks"][axis]
        status = finding["status"]
        score = (
            "Unknown"
            if status == "unknown"
            else "N/A"
            if status == "not-applicable"
            else str(finding["score"])
        )
        next_check = (
            _text(finding["next_check"])
            if finding["next_check"] is not None
            else "None recorded"
        )
        lines.append(
            f"| {axis} | {status} | {score} | {_text(finding['rationale'])} | "
            f"{_evidence_links(finding['evidence_ids'], evidence)} | "
            f"{'yes' if finding['blocking'] else 'no'} | {next_check} |"
        )
    next_step = assessment["next_step"] or (
        "Obtain human review before authorizing Stage 3."
        if assessment["disposition"] == "recommend"
        else "Retain this disposition unless new source-bound evidence supports reassessment."
    )
    lines.extend(["", f"- Next step: {_text(next_step)}", ""])


def _brief(lines, brief):
    lines.extend(
        [
            "## Research brief and original scope",
            "",
            f"Original scope: {_text(brief['original_description'])}",
            "",
            "Research needs:",
        ]
    )
    lines.extend(
        [
            f"- {_text(row['need_id'])}: {_text(row['question'])}"
            for row in brief["needs"]
        ]
        or ["- None recorded"]
    )
    lines.extend(["", "Scope fields:"])
    lines.extend(
        [
            f"- {_text(row['field'])}: material={'yes' if row['material'] else 'no'}; "
            f"reason={_text(row['reason'])}"
            for row in brief["scope_fields"]
        ]
        or ["- None recorded"]
    )
    lines.extend(
        [
            "",
            f"Previous brief SHA-256: {_code(brief['previous_sha256']) if brief.get('previous_sha256') is not None else 'none'}",
            "",
            "Supplied scope suggestions (proposals only; no approval is inferred):",
            *_json_block(brief.get("suggestions", [])),
            "",
            "Recorded scope decisions (shown as supplied; no additional approval is inferred):",
            *_json_block(brief.get("decisions", [])),
            "",
        ]
    )


def render_proposal(
    selection, source_snapshots, *, event_head, stored_packet_sha256, audit_prefix=""
):
    """Return a complete prehuman proposal report as deterministic UTF-8 bytes."""
    packet, snapshots, evidence, bibliography = _validate_bindings(
        selection, source_snapshots
    )
    audit_base = (_safe_snapshot_path(audit_prefix) + "/") if audit_prefix else ""
    if not isinstance(event_head, str) or not _SHA.fullmatch(event_head):
        raise Stage2Error("report-event-head-invalid")
    packet_hash = selection.get("packet_sha256")
    if not isinstance(packet_hash, str) or not _SHA.fullmatch(packet_hash):
        raise Stage2Error("report-packet-hash-invalid")
    if not isinstance(stored_packet_sha256, str) or not _SHA.fullmatch(
        stored_packet_sha256
    ):
        raise Stage2Error("report-stored-packet-hash-invalid")

    lines = [
        "# Stage 2 research-direction proposal (prehuman)",
        "",
        "This report presents supplied proposals and scientific judgments. Exact excerpts are clearly fenced in the evidence appendix; excerpt binding alone does not prove an interpretation, an entire method, or novelty. Scientific truth is not validated, human selection has not occurred, and Stage 3 is not authorized.",
        "",
    ]
    _brief(lines, packet["brief"])
    lines.extend(
        [
            f"Resources: {_text(packet['resources'])}",
            "",
            "## Supplied comparison",
            "",
            "The following is a supplied scientific judgment/proposal, not an exact source excerpt:",
            "",
            _text(packet["comparison"]),
            "",
            "## Portfolio recommendation",
            "",
            f"Recommendations: {len(selection['recommendations'])}",
        ]
    )
    categories = (
        ("Recommend", selection["recommendations"]),
        ("Park", selection["parked_options"]),
        ("Reject", selection["rejected_options"]),
    )
    for label, rows in categories:
        names = ", ".join(
            f"{_text(row['candidate_id'])} v{row['version']}" for row in rows
        )
        lines.append(f"- {label}: {names or 'none'}")
    revised = [
        option["candidate"]
        for option in selection["current_options"]
        if option["assessment"] and option["assessment"]["disposition"] == "revise"
    ]
    pending = [
        option["candidate"]
        for option in selection["current_options"]
        if option["assessment"] is None
    ]
    for label, rows in (("Revise", revised), ("Pending", pending)):
        names = ", ".join(
            f"{_text(row['candidate_id'])} v{row['version']}" for row in rows
        )
        lines.append(f"- {label}: {names or 'none'}")
    if not selection["recommendations"]:
        lines.append(
            "- No direction is currently recommended; this is an allowed, explicit outcome."
        )
    lines.extend(["", "### Blocking items", ""])
    lines.extend(
        [f"- {_text(item)}" for item in selection["blocking_items"]]
        or ["- None recorded"]
    )
    lines.extend(["", "### Action-record blockers", ""])
    lines.extend(
        [f"- {_text(item)}" for item in selection["action_record_blocking_items"]]
        or ["- None recorded"]
    )
    if packet.get("research_tables") is not None:
        lines.extend(
            ["", render_tables_markdown(packet["research_tables"], packet), ""]
        )
    lines.extend(["", "## Current candidate options", ""])
    for option in selection["current_options"]:
        candidate = option["candidate"]
        _candidate_details(lines, candidate, evidence)
        if option["assessment"] is None:
            lines.extend(
                [
                    "- Disposition: pending assessment",
                    "- Reason: No assessment is recorded for this current version.",
                    "- Next step: Complete a source-bound assessment before human selection.",
                    "",
                ]
            )
        else:
            _assessment_details(lines, option["assessment"], evidence)

    lines.extend(["## Global unresolved and scope questions", ""])
    for item in selection["unresolved"]:
        lines.append(f"- Unresolved: {_text(item)}")
    for item in selection["pending_scope_questions"]:
        lines.append(f"- Scope question: {_text(item)}")
    if not selection["unresolved"] and not selection["pending_scope_questions"]:
        lines.append("- None recorded")
    lines.extend(["", "## Full candidate version history", ""])
    for candidate_id in sorted(selection["candidate_histories"]):
        for candidate in selection["candidate_histories"][candidate_id]:
            _candidate_details(lines, candidate, evidence)

    lines.extend(["## Full assessment and action history", ""])
    for event in selection["assessment_history"]:
        assessment = event["assessment"]
        lines.extend(
            [
                f"### Event {event['sequence']}: {_text(assessment['event_id'])}",
                "",
                "Historical assessment/action record; it does not describe a later candidate version.",
                "",
                f"- Candidate: {_text(assessment['candidate_id'])} v{assessment['candidate_version']}",
                f"- Event hash: {_code(event['event_sha256'])}",
            ]
        )
        _assessment_details(lines, assessment, evidence)
    if not selection["assessment_history"]:
        lines.extend(["No assessments or actions are recorded.", ""])
    if selection["action_record"] is None:
        lines.append("Action record: unavailable")
        for item in selection["action_record_blocking_items"]:
            lines.append(f"- {_text(item)}")
    else:
        action = selection["action_record"]
        lines.extend(
            [
                f"Action record: {_text(selection['action_record_status'])}",
                f"Choice rationale: {_text(action['choice_rationale'])}",
                f"Internally recommended candidate IDs: {', '.join(_text(item) for item in action['selected_candidate_ids']) or 'none'}",
            ]
        )
        for row in action["revision_history"]:
            lines.append(
                f"- Revision: {_text(row['candidate_id'])} v{row['from_version']} to v{row['to_version']}; "
                f"reason={_text(row['reason'])}; evidence={_evidence_links(row['evidence_ids'], evidence)}"
            )
    lines.append("")
    _bibliography(lines, bibliography, evidence)
    lines.extend(["## Saved source snapshots", ""])
    evidence_by_source = {}
    for row in evidence.values():
        evidence_by_source.setdefault(row["source_id"], []).append(row["evidence_id"])
    for source_id in sorted(snapshots):
        source = snapshots[source_id]
        path = _safe_snapshot_path(source["path"])
        source_evidence = evidence_by_source.get(source_id, [])
        lines.append(
            f"- [{_text(source_id)}]({path}): work={_text(source['work_id'])}; "
            f"version={_text(source['version_id'])}; level={_text(source['evidence_level'])}; "
            f"excerpts={_evidence_links(source_evidence, evidence)}"
        )
    if not snapshots:
        lines.append("- No saved source snapshots are recorded.")
    lines.extend(
        [
            "",
            "A saved source with no recorded excerpt remains listed above; it is not silently omitted from the source inventory.",
            "",
            "## Evidence appendix",
            "",
        ]
    )
    for evidence_id in sorted(evidence):
        row = evidence[evidence_id]
        source = snapshots[row["source_id"]]
        path = _safe_snapshot_path(source["path"])
        lines.extend(
            [
                f'<a id="{_evidence_anchor(evidence_id)}"></a>',
                f"### Evidence {_text(evidence_id)}",
                "",
                f"- Source snapshot: [{_text(source['source_id'])}]({path})",
                f"- Locator: {_text(row['locator'])}",
                f"- Work: {_text(row['work_id'])}",
                f"- Version: {_text(row['version_id'])}",
                f"- Evidence level: {_text(source['evidence_level'])}",
                f"- SHA-256: {_code(source['sha256'])}",
                *(
                    ["- Bibliographic metadata: not recorded in this v1 packet."]
                    if not bibliography["available"]
                    else []
                ),
                *(
                    [
                        "- Recorded claim-specific literature roles (classification only; semantic support is not verified): "
                        + "; ".join(
                            f"{_text(role['role'])}: {_text(role['reason'])}"
                            for role in bibliography["by_evidence"].get(evidence_id, [])
                        )
                    ]
                    if bibliography["available"]
                    and bibliography["by_evidence"].get(evidence_id)
                    else []
                ),
                "Exact excerpt:",
                *_quote_block(row["quote"]),
                "",
            ]
        )
    if not evidence:
        lines.extend(["No evidence excerpts are recorded.", ""])
    lines.extend(
        [
            "## Audit trail",
            "",
            f"- Stored packet: [packet.json]({audit_base}packet.json)",
            f"- Run manifest: [run_manifest.json]({audit_base}run_manifest.json)",
            "- Selection data: [selection.json](selection.json)",
            f"- Original input packet SHA-256: {_code(packet_hash)}",
            f"- Stored packet.json SHA-256: {_code(stored_packet_sha256)}",
            "- Packet hashes use canonical JSON. Stored source paths include the copied sources/ directory, so the original and stored packet hashes may differ; the manifest binds both.",
            f"- Event head SHA-256: {_code(event_head)}",
        ]
    )
    for event in selection["assessment_history"]:
        lines.append(
            f"- Event {event['sequence']}: [events/{event['sequence']:06d}.json]"
            f"({audit_base}events/{event['sequence']:06d}.json)"
        )
    lines.extend(
        [
            "",
            "Prehuman status: human selection pending.",
            "",
            "Stage 3: not started; execution is not authorized.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")
