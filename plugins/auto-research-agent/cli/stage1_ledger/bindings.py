"""Provenance checks, separate from the truth of a source or reviewer judgment."""

from .journal import LedgerError


def completion_binding(payload):
    for name in ("stdout", "stderr", "records", "execution_ref"):
        ref = payload.get(name)
        if ref is not None and ref["producer"] != payload["attempt_id"]:
            raise LedgerError("completion-artifact-producer-mismatch: " + name)


def import_binding(payload, works):
    work = works.get(payload["work_id"])
    if not work or payload["version_id"] not in work["version_ids"]:
        raise LedgerError("source-import-unknown-version")


def claim_binding(payload, works, imports):
    work = works.get(payload["work_id"])
    if not work or payload["version_id"] not in work["version_ids"]:
        raise LedgerError("claim-unknown-version")
    ref = payload["source_ref"]
    source = imports.get(ref["producer"])
    if source:
        if (source["work_id"], source["version_id"]) != (
            payload["work_id"],
            payload["version_id"],
        ):
            raise LedgerError("claim-source-work-version-mismatch")
        return
    discoveries = [
        d
        for d in work["discoveries"]
        if d["version_id"] == payload["version_id"] and d["source_ref"] == ref
    ]
    if not discoveries:
        raise LedgerError("claim-source-work-version-mismatch")
    # A search batch can contain other papers. Only this record's text counts.
    if payload["evidence_level"] not in {"metadata", "abstract", "unavailable"}:
        raise LedgerError("search-record-is-not-primary-text")
    locator = payload["locator"]
    if locator is not None and not any(
        locator["quote"] in text for d in discoveries for text in strings(d["record"])
    ):
        raise LedgerError("claim-quote-not-in-bound-record")


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
