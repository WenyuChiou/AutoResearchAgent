"""Immutable located excerpts. Models select IDs; code reconstructs quotations."""

import json
from copy import deepcopy

from .common import EvaluationError, canonical, sha

SPAN_CHARS = 900
CHUNK_CHARS = 12_000


def index_evidence(evidence, *, span_characters=SPAN_CHARS):
    if not isinstance(span_characters, int) or not 1 <= span_characters <= SPAN_CHARS:
        raise EvaluationError("span-index: invalid character limit")
    index = {}
    for evidence_id, item in evidence.items():
        views = [("text", item["text"])]
        if item["origin"] == "subject-native-trace":
            try:
                event = json.loads(item["text"])
                output = event.get("item", {}).get("aggregated_output")
            except (ValueError, AttributeError):
                output = None
            if isinstance(output, str):
                views.append(("item.aggregated_output", output))
        for view, text in views:
            start = 0
            while start < len(text):
                end = min(start + span_characters, len(text))
                # Keep paragraph or line ends when possible, with no omitted bytes.
                if end < len(text):
                    boundary = text.rfind("\n", start + span_characters // 2, end)
                    if boundary >= 0:
                        end = boundary + 1
                identity = {
                    "evidence_id": evidence_id,
                    "artifact_sha256": item["sha256"],
                    "text_sha256": sha(item["text"].encode("utf-8")),
                    "source_version": item.get("source_version"),
                    "work_id": item.get("subject_work_id"),
                    "origin": item["origin"],
                    "view": view,
                    "start": start,
                    "end": end,
                    "locator": item.get("locator"),
                }
                span_id = "span-" + sha(canonical(identity))
                index[span_id] = {**identity, "text": text[start:end]}
                start = end
    return index


def validate_index(index, evidence):
    if index != index_evidence(evidence):
        raise EvaluationError(
            "span-index: content, file, version or locator binding changed"
        )


def select(index, span_ids, *, evidence_id=None):
    if not span_ids or len(set(span_ids)) != len(span_ids):
        raise EvaluationError("span-selection: missing or duplicate span IDs")
    rows = []
    for span_id in span_ids:
        if span_id not in index:
            raise EvaluationError("span-selection: unknown span_id " + span_id)
        row = index[span_id]
        if evidence_id is not None and row["evidence_id"] != evidence_id:
            raise EvaluationError("span-selection: wrong evidence file " + span_id)
        rows.append(row)
    return rows


def restore_passages(result, index):
    restored = deepcopy(result)
    for group in (
        "criteria",
        "core_assessments",
        "omission_assessments",
        "major_issues",
    ):
        for row in restored.get(group, []):
            passages = []
            for selection in row["passages"]:
                if set(selection) != {"span_id"}:
                    raise EvaluationError(
                        "span-selection: models must select IDs, not author quotations"
                    )
                span = select(index, [selection["span_id"]])[0]
                passages.append(
                    {"evidence_id": span["evidence_id"], "exact_quote": span["text"]}
                )
            row["passages"] = passages
    return restored


def extraction_chunks(subject, *, max_characters=CHUNK_CHARS):
    """Lossless fixed partitions; all delivered files, including their tail, count."""
    evidence = {
        k: v
        for k, v in subject["evidence"].items()
        if v["origin"] in {"subject-answer", "subject-delivered-artifact"}
    }
    index = index_evidence(evidence)
    chunks, pending, size = [], {}, 0
    for span_id, row in index.items():
        if pending and size + len(row["text"]) > max_characters:
            chunks.append(pending)
            pending, size = {}, 0
        pending[span_id] = row
        size += len(row["text"])
    if pending:
        chunks.append(pending)
    return index, chunks
