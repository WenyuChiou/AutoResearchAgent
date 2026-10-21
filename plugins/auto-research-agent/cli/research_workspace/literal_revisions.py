"""Append declared layout reviews without reinstating scientific citation support."""

from copy import deepcopy

from stage1_deliverable.common import DeliverableError, sha


def apply_literal_revisions(claim, checks, revisions, notes, text, raw_sha256):
    def require(condition, message):
        if not condition:
            raise DeliverableError("literal-revision: " + message)

    require(len(revisions) <= 256, "review bound")
    result, seen = deepcopy(checks), set()
    for reference in revisions:
        review = reference["value"]
        require(
            all(
                review[k] == claim[k]
                for k in ("claim_id", "work_id", "version_id", "source_id")
            ),
            "claim identity differs",
        )
        require(
            review["current_source_sha256"] == sha(text.encode("utf-8"))
            and raw_sha256 is not None
            and review["raw_pdf_sha256"] == raw_sha256,
            "source bytes differ",
        )
        require(
            review["reviewer_type"] in {"ai", "human"}
            and review["method"] == "saved-source-layout-review"
            and review["original_support_purpose_reestablished"] is False
            and review["semantic_support_verdict"] is None
            and review["claim_relation_changed"] is False,
            "literal review cannot grant semantic support",
        )
        original = review["original_note"]
        matches = [
            n
            for n, row in enumerate(result)
            if notes[row["note_path"]] == original["sha256"]
            and row["note_pointer"] + row["pointer"] == original["field_pointer"]
            and row["original"] == original["original_span"]
        ]
        require(
            len(matches) == 1 and matches[0] not in seen,
            "original note span differs or repeats",
        )
        number = matches[0]
        require(
            result[number]["state"] in {"quote-not-found", "ambiguous"},
            "original span does not need a layout revision",
        )
        proposed = review["proposed_append_only_literal_revision"]
        start, end, quote = (proposed[k] for k in ("start", "end", "quote"))
        require(
            type(start) is int
            and type(end) is int
            and isinstance(quote, str)
            and bool(quote)
            and 0 <= start < end <= len(text)
            and text[start:end] == quote
            and text.find(quote) == start
            and text.find(quote, start + 1) < 0
            and sha(quote.encode("utf-8")) == proposed["quote_sha256"],
            "new literal span is not exact and unique",
        )
        result[number].update(
            state="layout-reviewed-literal",
            current=dict(start=start, end=end, quote=quote),
            exact_match_count=1,
            literal_review=deepcopy(reference),
            reviewer_authenticated=False,
            original_support_purpose_reestablished=False,
        )
        seen.add(number)
    return result
