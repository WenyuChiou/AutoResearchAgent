"""Pure data projection for the Stage 2 comparison workbench."""

from copy import deepcopy
import json


_CELL_FIELDS = {
    "question": ("question", None),
    "data": ("data", "data_type"),
    "method": ("method", "method"),
    "findings": ("main_findings", None),
    "validation": ("validation", None),
    "limitations": ("limitations", None),
    "relevance": ("relevance", None),
    "geography": ("geography", "geography"),
    "population": ("population", "population"),
    "concepts": ("concepts", "topic_cluster"),
}


def _key(*parts):
    """Return a collision-safe, stable string for a recorded version identity."""
    return json.dumps(parts, ensure_ascii=False, separators=(",", ":"))


def _field(record, name):
    if not isinstance(record, dict) or name not in record:
        return None
    return deepcopy(record[name])


def _cell(literature_index, findings, classification, finding, fallback):
    root = f"selection.evaluation_packet.literature[{literature_index}]"
    if finding in findings:
        return {
            "text": deepcopy(findings[finding]),
            "field": f"{root}.findings.{finding}",
        }
    if fallback is not None and fallback in classification:
        return {
            "text": deepcopy(classification[fallback]),
            "field": f"{root}.classification.{fallback}",
        }
    return {"text": None, "field": None}


def _evidence_rows(packet):
    rows = packet.get("evidence")
    return rows if isinstance(rows, list) else []


def _related_evidence_ids(work, evidence):
    required = ("work_id", "version_id", "source_ids")
    if any(name not in work for name in required):
        return None
    source_ids = work["source_ids"]
    if not isinstance(source_ids, list):
        return None
    return [
        deepcopy(row.get("evidence_id"))
        for row in evidence
        if isinstance(row, dict)
        and row.get("work_id") == work["work_id"]
        and row.get("version_id") == work["version_id"]
        and row.get("source_id") in source_ids
    ]


def _literature(packet):
    evidence = _evidence_rows(packet)
    rows = packet.get("literature")
    if not isinstance(rows, list):
        return []
    output = []
    for index, work in enumerate(rows):
        work = work if isinstance(work, dict) else {}
        findings = work.get("findings")
        findings = findings if isinstance(findings, dict) else {}
        classification = work.get("classification")
        classification = classification if isinstance(classification, dict) else {}
        output.append(
            {
                "key": _key(work.get("work_id"), work.get("version_id")),
                **{
                    name: _field(work, name)
                    for name in (
                        "work_id",
                        "version_id",
                        "title",
                        "authors",
                        "year",
                        "roles",
                        "evidence_level",
                        "source_ids",
                        "classification",
                    )
                },
                "evidence_ids": _related_evidence_ids(work, evidence),
                "cells": {
                    name: _cell(index, findings, classification, finding, fallback)
                    for name, (finding, fallback) in _CELL_FIELDS.items()
                },
            }
        )
    return output


def _directions(selection):
    rows = selection.get("current_options")
    if not isinstance(rows, list):
        return []
    output = []
    for option in rows:
        option = option if isinstance(option, dict) else {}
        candidate = option.get("candidate")
        candidate = candidate if isinstance(candidate, dict) else {}
        assessment = option.get("assessment")
        assessment = assessment if isinstance(assessment, dict) else {}
        output.append(
            {
                "key": _key(candidate.get("candidate_id"), candidate.get("version")),
                **{
                    name: _field(candidate, name)
                    for name in (
                        "candidate_id",
                        "version",
                        "question",
                        "opportunity",
                        "value",
                        "approach",
                        "requirements",
                        "limitations",
                    )
                },
                **{
                    name: _field(assessment, name)
                    for name in ("disposition", "reason", "next_step")
                },
                "evidence_ids": _field(candidate, "evidence_ids"),
                "checks": _field(assessment, "checks"),
            }
        )
    return output


def _project_evidence(packet):
    return [
        {
            name: _field(row, name)
            for name in (
                "evidence_id",
                "source_id",
                "work_id",
                "version_id",
                "locator",
                "quote",
                "evidence_level",
            )
        }
        for row in _evidence_rows(packet)
        if isinstance(row, dict)
    ]


def build_comparison_view(attachment):
    """Build an inert view from facts already recorded in an attachment."""
    selection = attachment.get("selection") or {}
    packet = selection.get("evaluation_packet") or {}
    return {
        "schema_version": "1.0.0",
        "literature": _literature(packet),
        "directions": _directions(selection),
        "comparison": _field(packet, "comparison"),
        "evidence": _project_evidence(packet),
        "resources": _field(packet, "resources"),
        "research_tables": _field(packet, "research_tables"),
    }
