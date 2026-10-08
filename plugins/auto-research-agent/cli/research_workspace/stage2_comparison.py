"""Pure data projection for the Stage 2 comparison workbench."""

from copy import deepcopy
import json

from stage2_common import current_prior_work_reviews


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


def _cell(literature_index, findings, classification, finding, fallback, collection):
    root = f"selection.evaluation_packet.{collection}[{literature_index}]"
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


def _literature(packet, collection="literature"):
    evidence = _evidence_rows(packet)
    rows = packet.get(collection)
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
                    name: _cell(
                        index, findings, classification, finding, fallback, collection
                    )
                    for name, (finding, fallback) in _CELL_FIELDS.items()
                },
            }
        )
    return output


def _directions(selection, prior_reviews=None):
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
        direction = {
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
        if prior_reviews is not None:
            direction["prior_work_review"] = deepcopy(
                prior_reviews.get(
                    (candidate.get("candidate_id"), candidate.get("version"))
                )
            )
        output.append(direction)
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


def _prior_work_source_levels(packet):
    return {
        row.get("source_id"): deepcopy(row.get("evidence_level"))
        for row in packet.get("sources", [])
        if isinstance(row, dict) and row.get("source_id") is not None
    }


def build_comparison_view(attachment):
    """Build an inert view from facts already recorded in an attachment."""
    selection = attachment.get("selection") or {}
    packet = selection.get("evaluation_packet") or {}
    prior_work = None
    if packet.get("schema_version") == "2.4.0":
        prior_work = current_prior_work_reviews(packet)
    view = {
        "schema_version": "1.0.0",
        "literature": _literature(packet),
        "directions": _directions(
            selection,
            None
            if prior_work is None
            else {
                (row["candidate_id"], row["candidate_version"]): row
                for row in prior_work.values()
            },
        ),
        "comparison": _field(packet, "comparison"),
        "evidence": _project_evidence(packet),
        "resources": _field(packet, "resources"),
        "research_tables": _field(packet, "research_tables"),
    }
    if prior_work is not None:
        view["prior_work_reviews"] = deepcopy(list(prior_work.values()))
        view["prior_work_source_levels"] = _prior_work_source_levels(packet)
    if packet.get("schema_version") in {"2.3.0", "2.4.0"}:
        supplements = _literature(packet, "supplemental_literature")
        for row in supplements:
            row["record_kind"] = "supplemental-source-version"
        view["supplemental_literature"] = supplements
        for row in view["literature"]:
            row["source_versions"] = [
                deepcopy(item)
                for item in supplements
                if item["work_id"] == row["work_id"]
            ]
    return view
