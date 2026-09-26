"""Deterministic, bounded evidence views for v3.1 judgment units."""

import re
from collections import defaultdict

from .common import EvaluationError
from .spans import SPAN_CHARS, index_evidence

MAX_VIEW_CHARS = 60_000
MAX_WORK_CHARS = 12_000
_WORD = re.compile(r"[\w-]{4,}", re.UNICODE)
_STOP = {
    "about",
    "after",
    "also",
    "from",
    "into",
    "that",
    "their",
    "these",
    "this",
    "those",
    "using",
    "with",
}


def judge_span_index(evidence, phase):
    """Fit at least one located process excerpt per file without raising the cap.

    More native actions must not mechanically make a run unscorable. The full
    text remains indexed; the unchanged bounded view records all omissions.
    """
    size = SPAN_CHARS
    if phase == "process":
        count = sum(bool(item["text"]) for item in evidence.values())
        size = min(size, MAX_VIEW_CHARS // max(count, 1))
        if size < 1:
            raise EvaluationError(
                "judge view has more evidence files than its character budget"
            )
    return index_evidence(evidence, span_characters=size)


def _terms(packet, work_ids):
    terms = defaultdict(set)
    works = {row["work_id"]: row for row in packet["extraction"]["works"]}
    for work_id in work_ids:
        values = list(_strings(works.get(work_id, {})))
        values.extend(
            _strings(claim)
            for claim in packet["extraction"].get("central_claims", [])
            if work_id in claim.get("cited_work_ids", [])
        )
        for value in _flatten(values):
            terms[work_id].update(
                word.casefold()
                for word in _WORD.findall(value)
                if word.casefold() not in _STOP
            )
    return terms


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)


def _flatten(values):
    for value in values:
        if isinstance(value, str):
            yield value
        else:
            yield from value


def _candidate_index(index, phase):
    """Prefer decoded native output over its duplicate raw JSON representation."""
    decoded = {
        row["evidence_id"]
        for row in index.values()
        if row["view"] == "item.aggregated_output"
    }
    result = {}
    duplicate_count = 0
    for span_id, row in index.items():
        if (
            phase == "process"
            and row["evidence_id"] in decoded
            and row["view"] == "text"
        ):
            duplicate_count += 1
            continue
        result[span_id] = row
    return result, duplicate_count


def _work_id(packet, row):
    return row.get("work_id") or packet.get("sources", {}).get(
        row["evidence_id"], {}
    ).get("subject_work_id")


def _ordered_file_spans(rows, terms):
    rows = sorted(rows, key=lambda pair: (pair[1]["start"], pair[0]))
    if len(rows) < 3:
        return rows
    first, last = rows[0], rows[-1]
    middle = rows[1:-1]
    scored = [
        (
            sum(token in pair[1]["text"].casefold() for token in terms),
            pair,
        )
        for pair in middle
    ]
    matched = [
        pair
        for score, pair in sorted(
            scored, key=lambda item: (-item[0], item[1][1]["start"], item[1][0])
        )
        if score
    ]
    unmatched = [pair for score, pair in scored if not score]
    # Beginning/end prevent a term-only view; remaining spans are then spaced across
    # the file by alternating low/high positions.
    spread = []
    low, high = 0, len(unmatched) - 1
    while low <= high:
        spread.append(unmatched[low])
        low += 1
        if low <= high:
            spread.append(unmatched[high])
            high -= 1
    return [first, last, *matched, *spread]


def bounded_judge_view(packet, phase, index, *, work_ids=None):
    """Return a bounded span index and an explicit selection manifest.

    Each evidence file receives one span before any file receives another. A unit
    fails closed if that minimum representation cannot fit.
    """
    if phase not in {"content", "process"}:
        raise EvaluationError("judge view: invalid phase")
    work_ids = tuple(work_ids or ())
    candidates, duplicate_count = _candidate_index(index, phase)
    if work_ids:
        allowed = set(work_ids)
        candidates = {
            span_id: row
            for span_id, row in candidates.items()
            if _work_id(packet, row) in allowed or _work_id(packet, row) is None
        }
    grouped = defaultdict(list)
    for span_id, row in candidates.items():
        grouped[row["evidence_id"]].append((span_id, row))
    terms = _terms(packet, work_ids)
    ordered = {}
    for evidence_id, rows in grouped.items():
        work_id = _work_id(packet, rows[0][1])
        ordered[evidence_id] = _ordered_file_spans(rows, terms.get(work_id, set()))

    selected = {}
    total = 0
    work_totals = defaultdict(int)
    positions = {key: 0 for key in ordered}
    file_ids = sorted(ordered)
    while True:
        advanced = False
        for evidence_id in file_ids:
            position = positions[evidence_id]
            rows = ordered[evidence_id]
            if position >= len(rows):
                continue
            span_id, row = rows[position]
            length = len(row["text"])
            work_id = _work_id(packet, row)
            fits = total + length <= MAX_VIEW_CHARS and (
                work_id is None or work_totals[work_id] + length <= MAX_WORK_CHARS
            )
            if position == 0 and not fits:
                raise EvaluationError(
                    "judge view budget cannot represent every evidence file; "
                    f"first omitted file: {evidence_id}"
                )
            positions[evidence_id] += 1
            if not fits:
                continue
            selected[span_id] = row
            total += length
            if work_id is not None:
                work_totals[work_id] += length
            advanced = True
        if not advanced:
            break

    per_file = {}
    for evidence_id in file_ids:
        chosen = sum(row["evidence_id"] == evidence_id for row in selected.values())
        per_file[evidence_id] = {
            "total_spans": len(ordered[evidence_id]),
            "selected_spans": chosen,
            "omitted_spans": len(ordered[evidence_id]) - chosen,
            "truncated": chosen < len(ordered[evidence_id]),
        }
    manifest = {
        "schema_version": "3.1",
        "limits": {
            "total_text_chars": MAX_VIEW_CHARS,
            "per_work_text_chars": MAX_WORK_CHARS,
            "max_index_span_chars": max(
                (len(row["text"]) for row in index.values()), default=0
            ),
        },
        "raw_full_span_count": len(index),
        "eligible_span_count": len(candidates),
        "selected_span_count": len(selected),
        "omitted_span_count": len(candidates) - len(selected),
        "selected_text_chars": total,
        "evidence_file_count": len(grouped),
        "selected_evidence_file_count": len(
            {row["evidence_id"] for row in selected.values()}
        ),
        "duplicate_native_json_spans_omitted": duplicate_count,
        "truncated": len(selected) < len(candidates),
        "per_file": per_file,
        "per_work_selected_text_chars": dict(sorted(work_totals.items())),
    }
    return selected, manifest
