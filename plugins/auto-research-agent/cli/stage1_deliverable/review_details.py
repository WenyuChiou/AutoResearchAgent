"""Project recorded screening and acquisition facts into the reading report."""

from collections import defaultdict
from datetime import datetime


class LiteralLine(str):
    """Recorded text that the Markdown view must present literally."""


def _display_text(value):
    # The Core source journal can carry text that DOCX's XML cannot represent.
    return "".join(
        f"\\u{ord(char):04x}"
        if (ord(char) < 32 and char not in "\t\n\r") or char in "\ufffe\uffff"
        else char
        for char in value
    )


def _review_version_line(decision_id, version):
    if version is None:
        return "Screening version: Unknown (no version-specific review binding)."
    return f"Version named in the saved review of decision {decision_id}: {version}."


def _saved_review_versions(journal, library):
    """Resolve review scope at the time of recording, without selecting a version."""
    known_versions = {
        work: {version["version_id"] for version in row["versions"]}
        for work, row in library.items()
    }
    candidates, decisions = {}, {}
    observed_versions = defaultdict(set)
    for entry in journal:
        event = entry["payload"]
        kind = event["kind"]
        if kind == "CandidateRevision":
            candidates[event["work_id"]] = event
        elif kind == "DecisionEvent":
            decisions[event["subject_id"]] = event
        elif kind == "CoverageWorkReview":
            work, version = event["work_id"], event["version_id"]
            candidate, decision = candidates.get(work), decisions.get(work)
            if (
                candidate is not None
                and candidate["event_id"] == event["candidate_event_id"]
                and version in candidate["version_ids"]
                and version in known_versions.get(work, ())
                and decision is not None
                and decision["event_id"] == event["decision_event_id"]
                and decision["new_decision"] == "include"
            ):
                observed_versions[work, decision["event_id"]].add(version)
    return {
        key: next(iter(versions))
        for key, versions in observed_versions.items()
        if len(versions) == 1
    }


def _screening_lines(decisions, *, core=False, review=None, versions=None):
    if not decisions:
        return ["Screening: Unknown (no decision recorded).", "Reason: Unknown.", ""]
    status, reason, event_id, at = (
        ("new_decision", "rationale", "event_id", "created_at")
        if core
        else ("status", "reason", "decision_id", "observed_at")
    )
    lines = [
        "Screening history (work-level):"
        if core
        else "Screening history (saved records):",
        "",
    ]
    for index, decision in enumerate(decisions):
        label = "current" if index == len(decisions) - 1 else "earlier"
        lines.extend(
            [
                f"Decision {decision[event_id]} ({label}, {decision[at]}): {decision[status]}.",
                LiteralLine(f"Reason: {_display_text(decision[reason])}"),
                "",
            ]
        )
        if versions is not None:
            key = decision[event_id]
            lines.extend([_review_version_line(key, versions.get(key)), ""])
    if core and versions is None:
        lines.extend(
            [
                _review_version_line(review["decision_event_id"], review["version_id"])
                if review is not None
                else _review_version_line(None, None),
                "",
            ]
        )
    elif not core:
        # A legacy version_id labels the canonical projection. It may have
        # been filled from the selected paper version after a Core decision.
        lines.extend(
            [
                "Screening version: Unknown (no original version binding recorded).",
                "",
            ]
        )
    if decisions[-1][status] == "pending":
        lines.extend(["Screening follow-up: the current decision is pending.", ""])
    return lines


def _receipt_lines(receipts):
    lines = []
    for row in receipts:
        lines.extend(
            [
                f"Source {row['source_id']}, attempt {row['attempt']} ({row['observed_at']}): {row['state']}.",
                LiteralLine(f"Requested URI: {_display_text(row['requested_uri'])}"),
                "",
            ]
        )
    return lines


def _source_lines(receipts, attempts, imports):
    lines = ["Source acquisition:", ""]
    if not (receipts or attempts or imports):
        return lines + [
            "Unknown (no source attempt or import recorded for this version).",
            "",
        ]
    receipts_by_id = defaultdict(list)
    for row in receipts:
        receipts_by_id[row["source_id"]].append(row)
    for attempt in attempts:
        start, finish = attempt["started"], attempt["finished"]
        event_id = start["event_id"]
        if event_id in receipts_by_id:
            lines.extend(_receipt_lines(receipts_by_id.pop(event_id)))
            continue
        lines.append(
            f"Saved source attempt {event_id} ({finish['observed_at']}): {finish['outcome']}."
            if finish is not None
            else f"Saved source attempt {event_id} ({start['created_at']}): pending (no result recorded)."
        )
        lines.append(
            LiteralLine(f"Requested URI: {_display_text(start['source_uri'])}")
        )
        if finish is not None:
            lines.append(
                LiteralLine(f"Recorded reason: {_display_text(finish['reason'])}")
            )
        lines.append("")
    for source_receipts in receipts_by_id.values():
        lines.extend(_receipt_lines(source_receipts))
    for item in imports:
        event_id = item["started"]["event_id"]
        material = "saved bytes recorded" if item["artifacts"] else "intent recorded"
        lines.extend([f"Saved source import {event_id}: {material}.", ""])
    lines.extend(
        [
            "Full text: validated receipt recorded for this version."
            if any(row["state"] == "available" for row in receipts)
            else "Full text: Unknown (no validated full-text receipt for this version).",
            "",
        ]
    )
    return lines


def by_work(records, receipts, *, journal=None):
    """Index by the validated work/version pair; Core decisions have work scope."""
    sources_by_version = defaultdict(list)
    for row in receipts:
        sources_by_version[row["work_id"], row["version_id"]].append(row)
    library = {
        row["work_id"]: row
        for row in records.get("screening_library", {}).get("rows", [])
    }
    bindings = _saved_review_versions(journal, library) if journal is not None else None
    decisions_by_version = defaultdict(list)
    if not library:
        for row in records["screening"]:
            decisions_by_version[row["work_id"], row["version_id"]].append(row)

    output = {}
    for paper in records["papers"]:
        work, version = paper["work_id"], paper["version_id"]
        row = library.get(work)
        if row is None:
            decisions = sorted(
                decisions_by_version[work, version],
                key=lambda item: datetime.fromisoformat(item["observed_at"]),
            )
            output[work] = (
                _screening_lines(decisions)
                + _source_lines(sources_by_version[work, version], [], []),
                [],
            )
            continue

        lines = _screening_lines(
            row["decision_history"],
            core=True,
            review=row["current_review"],
            versions=(
                {
                    decision["event_id"]: bindings.get((work, decision["event_id"]))
                    for decision in row["decision_history"]
                }
                if bindings is not None
                else None
            ),
        )
        from .provided_records import provided_materials_for_version

        candidate = next(
            c
            for c in records["screening_library"]["snapshots"][0]["rows"]
            if c["work_id"] == work
        )
        provided_materials = provided_materials_for_version(candidate, version)
        if provided_materials:
            binding = records["screening_library"]["binding"]
            lines.extend(
                [
                    "Recorded origins for this work/version:",
                    "Project: "
                    + binding["project_id"]
                    + "; input version: "
                    + str(binding["input_version"]),
                    "Work: " + work + "; version: " + version,
                    "",
                ]
            )
            for discovery in candidate["discoveries"]:
                if (
                    discovery["version_id"] == version
                    and discovery["query_id"] is not None
                ):
                    lines.extend(
                        [
                            "Recorded search discovery: query "
                            + discovery["query_id"]
                            + "; backend attempt "
                            + discovery["attempt_id"]
                            + ".",
                            "Discovery record: " + discovery["discovery_id"] + ".",
                            "",
                        ]
                    )
            for provided in provided_materials:
                lines.extend(
                    [
                        "Origin: externally provided saved material (this material is not a search result).",
                        "Provided event: " + provided["event_id"],
                        LiteralLine(
                            "Original material type: "
                            + _display_text(provided["original_type"])
                        ),
                        LiteralLine(
                            "Source URL: " + _display_text(provided["source_uri"])
                        ),
                        "Material SHA-256: " + provided["material_ref"]["sha256"],
                        "Saved material path: screening_artifacts/"
                        + provided["material_ref"]["sha256"]
                        + ".bin",
                        "Identity: "
                        + provided["identity_status"]
                        + " (operator-provided metadata; not independently checked).",
                        "",
                    ]
                )
            if paper.get("reading_status") == "provided-unread":
                lines.extend(
                    [
                        "Reading: Unknown (saved material is not a complete-body reading record).",
                        "Abstract/summary: Unknown (no abstract supplied).",
                        "Research claims: Unknown (no claim assessment or screening decision recorded).",
                        "",
                    ]
                )
        attempts = defaultdict(list)
        for item in row["source_attempts"]:
            attempts[item["started"]["version_id"]].append(item)
        imports = defaultdict(list)
        for item in row["source_imports"]:
            imports[item["started"]["version_id"]].append(item)
        lines.extend(
            _source_lines(
                sources_by_version[work, version], attempts[version], imports[version]
            )
        )
        history = []
        for other in row["versions"]:
            historical = other["version_id"]
            if historical == version:
                continue
            history.extend([f"Historical version: {historical}", ""])
            history.extend(
                _source_lines(
                    sources_by_version[work, historical],
                    attempts[historical],
                    imports[historical],
                )
            )
        output[work] = lines, history
    return output
