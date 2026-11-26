"""Authored claim types and bounded split hints, never semantic verification."""

import re

from .journal import LedgerError

TYPES = {"source_statement", "project_interpretation"}
LABELS = {
    "source_statement": "Source statement / 来源陈述",
    "project_interpretation": "Project interpretation / 项目解释",
    "unclassified": "Unclassified / 未分类",
}


def check_structure(claim, prior):
    """Resolve only earlier same-work/version source statements in this ledger.

    No cross-run IDs, inferred type, interpretation chains or automatic split.
    A source statement can remain unverified; a basis is not an endorsement.
    """
    if "claim_type" not in claim and "basis_claim_ids" not in claim:
        return
    kind, basis = claim.get("claim_type"), claim.get("basis_claim_ids")
    if (
        type(kind) is not str
        or kind not in TYPES
        or type(basis) is not list
        or any(type(item) is not str for item in basis)
        or len(set(basis)) != len(basis)
    ):
        raise LedgerError("claim-type-or-basis-invalid")
    if kind == "source_statement":
        if basis:
            raise LedgerError("source-statement-cannot-have-interpretation-basis")
        if claim.get("locator") is None:
            raise LedgerError("source-statement-needs-located-source")
        return
    if not basis:
        raise LedgerError("project-interpretation-needs-source-statements")
    for event_id in basis:
        source = prior.get(event_id)
        if (
            source is None
            or source.get("claim_type") != "source_statement"
            or source.get("locator") is None
            or any(
                source.get(key) != claim.get(key) for key in ("work_id", "version_id")
            )
        ):
            raise LedgerError("interpretation-basis-not-prior-same-work-version-source")
        # A new interpretation cannot launder a malformed saved declaration.
        check_structure(source, {})


def split_hint(text):
    """Punctuation/coordinated-predicate heuristic; no numeric-count rule.

    This deliberately cannot certify atomicity. Dates, decimals and a numeric
    comparison alone are not triggers. Unknown sentence semantics stay unchecked.
    """
    clauses = [
        x
        for x in re.split(r"[;；。！？!?]|(?<=[\w%])\.\s+(?=[A-Z])|\n+", text)
        if x.strip()
    ]
    coordinated = re.search(
        r"\b(?:and|also|while)\s+(?:\w+\s+)?(?:increases?|increased|decreases?|decreased|improves?|improved|reduces?|reduced|shows?|showed|demonstrates?|demonstrated)\b|(?:并且|而且|同时|且)(?:提高|降低|增加|减少|证明|改善)",
        text,
        re.IGNORECASE,
    )
    if len(clauses) > 1 or coordinated:
        return "Consider splitting into separately cited claims / 建议拆分并逐条关联原句 (heuristic; not a rejection or verification)."
    return None


def presentation(claim):
    """Pure UI/report projection. Legacy absence stays unclassified."""
    kind = claim.get("claim_type", "unclassified")
    return {
        "claim_type": kind,
        "type_label": LABELS[kind],
        "basis_claim_ids": list(claim.get("basis_claim_ids", [])),
        "split_hint": split_hint(claim.get("claim_text", claim.get("text", ""))),
        "atomicity_verified": False,
    }
