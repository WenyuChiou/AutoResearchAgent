"""Chunked, span-selected subject extraction for evaluator policy v3.1."""

import itertools
import json
import re
from pathlib import Path

from .common import EVAL_ROOT, EvaluationError, canonical, sha
from .spans import CHUNK_CHARS, SPAN_CHARS, extraction_chunks, select

WORK_SCHEMA = EVAL_ROOT / "schemas" / "subject-works.v3_1.schema.json"
CLAIM_SCHEMA = EVAL_ROOT / "schemas" / "subject-claims.v3_1.schema.json"


def _run_unit(*args, **kwargs):
    from .units import run_unit

    return run_unit(*args, **kwargs)


def _ordered_span_ids(index):
    return list(index)


def _chunk_views(index, chunks):
    """Add one same-file neighbor on each side without changing primary coverage."""
    ordered = _ordered_span_ids(index)
    positions = {span_id: number for number, span_id in enumerate(ordered)}
    views = []
    for chunk in chunks:
        primary = list(chunk)
        visible = list(primary)
        for edge, step in ((primary[0], -1), (primary[-1], 1)):
            position = positions[edge] + step
            if position < 0 or position >= len(ordered):
                continue
            neighbor = ordered[position]
            left = index[edge]
            right = index[neighbor]
            if (
                left["evidence_id"] == right["evidence_id"]
                and left["view"] == right["view"]
                and (left["end"] == right["start"] or right["end"] == left["start"])
                and neighbor not in visible
            ):
                if step < 0:
                    visible.insert(0, neighbor)
                else:
                    visible.append(neighbor)
        views.append(
            {
                "primary_span_ids": primary,
                "visible_span_ids": visible,
                "context_span_ids": [row for row in visible if row not in chunk],
            }
        )
        if sum(len(index[s]["text"]) for s in visible) > CHUNK_CHARS:
            raise EvaluationError(
                "subject extraction visible text exceeds 12000 characters"
            )
    if {span_id for view in views for span_id in view["primary_span_ids"]} != set(
        index
    ):
        raise EvaluationError("subject extraction chunks do not cover every span")
    return views


def _render_spans(index, span_ids):
    blocks = []
    for span_id in span_ids:
        row = index[span_id]
        location = {
            "span_id": span_id,
            "evidence_id": row["evidence_id"],
            "origin": row["origin"],
            "view": row["view"],
            "start": row["start"],
            "end": row["end"],
            "locator": row.get("locator"),
            "source_version": row.get("source_version"),
        }
        blocks.append(
            "<span location='"
            + json.dumps(location, ensure_ascii=False, sort_keys=True)
            + "'>\n"
            + row["text"]
            + "\n</span>"
        )
    return "\n".join(blocks)


def _restore(index, span_ids, allowed):
    if not set(span_ids).issubset(allowed):
        raise EvaluationError("subject extraction selected a span outside its chunk")
    rows = select(index, span_ids)
    first = rows[0]
    if any(
        row["evidence_id"] != first["evidence_id"] or row["view"] != first["view"]
        for row in rows
    ):
        raise EvaluationError("subject extraction selection crosses evidence files")
    for left, right in itertools.pairwise(rows):
        if left["end"] != right["start"]:
            raise EvaluationError(
                "subject extraction spans are not ordered and contiguous"
            )
    return "".join(row["text"] for row in rows), first["evidence_id"]


def _check_completion(value, unit):
    complete = value["extraction_complete"]
    reason = value["unextracted_reason"]
    if complete and reason is not None:
        raise EvaluationError(f"{unit}: complete extraction cannot have a reason")
    if not complete and (not isinstance(reason, str) or not reason.strip()):
        raise EvaluationError(f"{unit}: incomplete extraction requires a reason")


def _normalize_works(value, index, allowed):
    _check_completion(value, "subject-works")
    works = []
    for number, row in enumerate(value["works"], 1):
        exact, evidence_id = _restore(index, row["span_ids"], allowed)
        if row["title"] not in exact:
            raise EvaluationError(
                f"subject-works row {number}: title {row['title']!r} is absent from selected spans; "
                "copy the raw label including Markdown formatting, without rewriting it"
            )
        if row["identifier"] and row["identifier"] not in exact:
            raise EvaluationError(
                f"subject-works row {number} ({row['title']!r}): identifier {row['identifier']!r} "
                "is absent from selected spans; copy a visible DOI/URL exactly or use an empty string; "
                "do not concatenate separated words or remove Markdown formatting"
            )
        works.append(
            {
                **row,
                "exact_reference": exact,
                "evidence_id": evidence_id,
            }
        )
    mentions = []
    for row in value["mentions"]:
        # A mention group is a list of observations, not one quotation or one
        # work identity. Restore each selected span separately, including groups
        # spread across files; never concatenate those passages into a citation.
        select(index, row["span_ids"])
        for span_id in row["span_ids"]:
            exact, evidence_id = _restore(index, [span_id], allowed)
            mentions.append(
                {
                    **row,
                    "span_ids": [span_id],
                    "exact_reference": exact,
                    "evidence_id": evidence_id,
                }
            )
    return {**value, "works": works, "mentions": mentions}


def _work_identity(row):
    # A DOI URL and its bare DOI identify the same work only when the visible
    # titles also agree (apart from case, whitespace, and terminal punctuation).
    # Conflicting titles stay separate for identity review; never merge by DOI alone.
    doi = re.fullmatch(
        r"(?:https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/\S+)", row["identifier"], re.I
    )
    if doi:
        return {
            "identifier": doi.group(1).casefold().rstrip("."),
            "title": " ".join(row["title"].casefold().split()).rstrip("."),
        }
    return {"identifier": row["identifier"], "title": row["title"]}


def work_id_for(row):
    """Use the same canonical work identity at extraction and source admission."""
    return "work-" + sha(canonical(_work_identity(row)))[:16]


def _aggregate_works(results):
    by_identity = {}
    source_map = {}
    for chunk_number, result in enumerate(results, 1):
        for row in result["works"]:
            identity = _work_identity(row)
            key = canonical(identity)
            work_id = work_id_for(row)
            source = {
                "chunk": chunk_number,
                "evidence_id": row["evidence_id"],
                "span_ids": row["span_ids"],
            }
            source_map.setdefault(work_id, []).append(source)
            if key not in by_identity:
                by_identity[key] = {
                    "work_id": work_id,
                    "exact_reference": row["exact_reference"],
                    "title": row["title"],
                    "identifier": row["identifier"],
                    "nominated_core": row["nominated_core"],
                }
            else:
                by_identity[key]["nominated_core"] = (
                    by_identity[key]["nominated_core"] or row["nominated_core"]
                )
    works = sorted(by_identity.values(), key=lambda row: row["work_id"])
    if len({row["work_id"] for row in works}) != len(works):
        raise EvaluationError("subject-works: deterministic work ID collision")
    return works, source_map


def _normalize_claims(value, index, allowed, known_work_ids):
    _check_completion(value, "subject-claims")
    claims = []
    for row in value["central_claims"]:
        unknown = set(row["cited_work_ids"]) - known_work_ids
        if unknown:
            raise EvaluationError(
                "subject-claims: unknown cited work ID " + min(unknown)
            )
        exact, evidence_id = _restore(index, row["span_ids"], allowed)
        claims.append({**row, "exact_text": exact, "evidence_id": evidence_id})
    return {**value, "central_claims": claims}


def _aggregate_claims(results):
    by_identity = {}
    source_map = {}
    for chunk_number, result in enumerate(results, 1):
        for row in result["central_claims"]:
            cited = sorted(row["cited_work_ids"])
            identity = {"exact_text": row["exact_text"], "cited_work_ids": cited}
            key = canonical(identity)
            claim_id = "claim-" + sha(key)[:16]
            source_map.setdefault(claim_id, []).append(
                {
                    "chunk": chunk_number,
                    "evidence_id": row["evidence_id"],
                    "span_ids": row["span_ids"],
                }
            )
            by_identity.setdefault(
                key,
                {
                    "claim_id": claim_id,
                    "exact_text": row["exact_text"],
                    "cited_work_ids": cited,
                },
            )
    claims = sorted(by_identity.values(), key=lambda row: row["claim_id"])
    if len({row["claim_id"] for row in claims}) != len(claims):
        raise EvaluationError("subject-claims: deterministic claim ID collision")
    return claims, source_map


def _works_prompt(index, view, number, total):
    return (
        "Inventory scholarly works with a visible bibliographic title in this subject-output chunk. "
        "Put summary shorthand, author-only references, acronyms repeated in discussion, and group labels "
        "in mentions, not works; these are preserved but must not inflate the paper count or trigger title lookup. "
        "For example, 'the validation review', 'Smith et al.', and 'recent preprints' are mentions. "
        "Select only span_ids shown below. The program restores exact_reference; never write a quotation. "
        "title and identifier must be literal substrings of the selected raw spans, including any Markdown. "
        "identifier means an explicit DOI, URL, arXiv ID, or other unique paper ID; never use an author or title as an ID. "
        "Use an empty identifier when absent. Do not concatenate words across formatting to invent an ID. "
        "Keep incomplete bibliographic entries as works if they name a study; preserve distinct ambiguous works. "
        "Set extraction_complete false and explain genuinely unextractable references; never silently discard them. "
        "Origin and offsets identify the original evidence file and its role. Context spans overlap adjacent chunks; "
        "primary spans are this chunk's lossless coverage. Return only the schema JSON.\n"
        f"Chunk {number}/{total}; primary_span_ids={json.dumps(view['primary_span_ids'])}; "
        f"context_span_ids={json.dumps(view['context_span_ids'])}.\n"
        "<untrusted_subject_spans>\n"
        + _render_spans(index, view["visible_span_ids"])
        + "\n</untrusted_subject_spans>"
    )


def _claims_prompt(index, view, works, number, total):
    catalog = [
        {
            "work_id": row["work_id"],
            "title": row["title"],
            "identifier": row["identifier"],
        }
        for row in works
    ]
    return (
        "Select every central research claim in this subject-output chunk. A central claim is a key finding, method, "
        "limitation, novelty, or coverage statement. Select only contiguous span_ids shown below; the program restores "
        "exact_text, so never write a quotation. cited_work_ids must come from the resolved catalog and may be empty "
        "when the visible claim cites no work. Origin and offsets identify the original evidence file and role. "
        "Return only the schema JSON.\n"
        f"Chunk {number}/{total}; primary_span_ids={json.dumps(view['primary_span_ids'])}; "
        f"context_span_ids={json.dumps(view['context_span_ids'])}.\n"
        f"Resolved work catalog={json.dumps(catalog, ensure_ascii=False, sort_keys=True)}\n"
        "<untrusted_subject_spans>\n"
        + _render_spans(index, view["visible_span_ids"])
        + "\n</untrusted_subject_spans>"
    )


def extract_subject_v31(subject, output_dir, model_options, *, replay_only=False):
    """Extract old-compatible works and claims through independent chunk units."""
    # Reserve both adjacent context spans inside the same 12,000-character cap.
    index, chunks = extraction_chunks(
        subject, max_characters=CHUNK_CHARS - 2 * SPAN_CHARS
    )
    if not chunks:
        raise EvaluationError("subject extraction has no delivered evidence")
    views = _chunk_views(index, chunks)
    output_dir = Path(output_dir)
    work_results = []
    records = []
    for number, view in enumerate(views, 1):
        allowed = set(view["visible_span_ids"])
        label = f"subject-works-{number:03d}"
        prompt = _works_prompt(index, view, number, len(views))
        result, provenance = _run_unit(
            prompt,
            WORK_SCHEMA,
            output_dir,
            label,
            model_options,
            lambda value, allowed=allowed: _normalize_works(value, index, allowed),
            replay_only=replay_only,
        )
        work_results.append(result)
        records.append(
            {
                **view,
                "works_unit_label": label,
                "works_prompt_sha256": sha(prompt.encode("utf-8")),
                "works_schema_sha256": sha(WORK_SCHEMA.read_bytes()),
                "works_provenance": provenance,
            }
        )
    works, work_sources = _aggregate_works(work_results)
    known_work_ids = {row["work_id"] for row in works}
    claim_results = []
    for number, view in enumerate(views, 1):
        allowed = set(view["visible_span_ids"])
        label = f"subject-claims-{number:03d}"
        prompt = _claims_prompt(index, view, works, number, len(views))
        result, provenance = _run_unit(
            prompt,
            CLAIM_SCHEMA,
            output_dir,
            label,
            model_options,
            lambda value, allowed=allowed: _normalize_claims(
                value, index, allowed, known_work_ids
            ),
            replay_only=replay_only,
        )
        claim_results.append(result)
        records[number - 1]["claims_unit_label"] = label
        records[number - 1]["claims_prompt_sha256"] = sha(prompt.encode("utf-8"))
        records[number - 1]["claims_schema_sha256"] = sha(CLAIM_SCHEMA.read_bytes())
        records[number - 1]["claims_provenance"] = provenance
    claims, claim_sources = _aggregate_claims(claim_results)
    incomplete = []
    for unit, results in (("works", work_results), ("claims", claim_results)):
        for number, result in enumerate(results, 1):
            if not result["extraction_complete"]:
                incomplete.append(
                    f"{unit} chunk {number}: {result['unextracted_reason']}"
                )
    for number, record in enumerate(records, 1):
        record["chunk_id"] = f"chunk-{number:03d}"
        record["work_ids"] = sorted(
            work_id
            for work_id, sources in work_sources.items()
            if any(source["chunk"] == number for source in sources)
        )
        record["claim_ids"] = sorted(
            claim_id
            for claim_id, sources in claim_sources.items()
            if any(source["chunk"] == number for source in sources)
        )
    return {
        "works": works,
        "central_claims": claims,
        "extraction_complete": not incomplete,
        "unextracted_reason": "; ".join(incomplete) if incomplete else None,
    }, {
        "schema_version": "3.1.0",
        "span_index_sha256": sha(canonical(index)),
        "chunk_count": len(views),
        "chunks": records,
        "work_source_map": work_sources,
        "mention_sources": [
            {"chunk": number, **row}
            for number, result in enumerate(work_results, 1)
            for row in result["mentions"]
        ],
        "claim_source_map": claim_sources,
        "replay_only": replay_only,
    }
