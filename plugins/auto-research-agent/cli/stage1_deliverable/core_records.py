"""Lossless Core claim archives for canonical records 1.1; no new judgments."""

from pathlib import PurePosixPath

from stage1_ledger.contracts import check_payload
from stage1_ledger.journal import canonical, digest

from .common import DeliverableError, safe_path, sha

VERSION = "1.1.0"
RELATIONS = {
    "pending",
    "supports",
    "partial",
    "contradicts",
    "unclear",
    "unverifiable",
    "context",
}
LEVELS = {
    "metadata",
    "abstract",
    "full-text",
    "full_text",
    "primary_data_or_table",
    "unavailable",
}


def extended(records):
    return records.get("schema_version") == VERSION


def artifact_path(ref):
    return "core_claim_artifacts/" + ref["sha256"] + ".bin"


def validate_extension(records):
    from .records import _keys

    history = records["core_claim_history"]
    if type(history) is not list or type(records["core_artifacts"]) is not list:
        raise DeliverableError("Core claim history and artifacts require lists")
    by_id, previous_sequence = {}, 0
    references = {}
    for row in history:
        _keys(
            row,
            (
                "schema_version",
                "sequence",
                "previous_sha256",
                "event_sha256",
                "payload",
            ),
            "Core claim journal row",
        )
        event = row["payload"]
        check_payload(event)
        unsigned = {k: v for k, v in row.items() if k != "event_sha256"}
        if (
            row["schema_version"] != "1.0.0"
            or type(row["sequence"]) is not int
            or row["sequence"] <= previous_sequence
            or event["kind"] != "ClaimEvidence"
            or event["event_id"] != f"e{row['sequence']:06d}"
            or row["event_sha256"] != digest(canonical(unsigned))
            or event["event_id"] in by_id
        ):
            raise DeliverableError("Core claim history identity or bytes differ")
        previous_sequence = row["sequence"]
        by_id[event["event_id"]] = row
        references[canonical(event["source_ref"])] = event["source_ref"]
    observed = {}
    for row in records["core_artifacts"]:
        _keys(row, ("source_ref", "artifact_path"), "Core claim artifact")
        key = canonical(row["source_ref"])
        if (
            key not in references
            or key in observed
            or row["artifact_path"] != artifact_path(row["source_ref"])
        ):
            raise DeliverableError("Core claim artifact set or binding differs")
        path = PurePosixPath(row["artifact_path"])
        if path.is_absolute() or ".." in path.parts:
            raise DeliverableError("unsafe Core claim archive path")
        observed[key] = row
    if set(observed) != set(references):
        raise DeliverableError("Core claim artifact history incomplete")
    for claim in records["claims"]:
        row = by_id.get(claim["claim_id"])
        if row is None or row != claim["core_event"]:
            raise DeliverableError("active claim differs from preserved Core event")
        event = row["payload"]
        producer = event["source_ref"]["producer"]
        source_ids = {source["source_id"] for source in records["sources"]}
        if claim["source_id"] != (producer if producer in source_ids else None):
            raise DeliverableError("Core claim source association differs")
        if (
            any(
                event[k] != claim[k]
                for k in ("work_id", "version_id", "relation", "evidence_level")
            )
            or event["claim_text"] != claim["text"]
        ):
            raise DeliverableError("claim projection rewrites Core observation")
        if event["locator"] is None:
            if any(claim[k] is not None for k in ("locator", "start", "end", "quote")):
                raise DeliverableError("nullable Core locator must remain unavailable")
        elif claim["quote"] != event["locator"]["quote"]:
            raise DeliverableError("Core quote differs from exact span")
    return by_id


def validate_artifacts(records, read):
    """Replay preserved bytes and spans; never rank evidence levels."""
    validate_extension(records)
    raw_by_ref = {}
    for artifact in records["core_artifacts"]:
        raw = read(artifact["artifact_path"])
        if sha(raw) != artifact["source_ref"]["sha256"]:
            raise DeliverableError("Core claim source archive bytes differ")
        raw_by_ref[canonical(artifact["source_ref"])] = raw
    # Historical rows retain their original locator even when no active paper
    # selects that version. Do not create character offsets or infer acceptance.
    for row in records["core_claim_history"]:
        event = row["payload"]
        from stage1_ledger.semantics import claim_check

        claim_check(event, lambda ref: raw_by_ref[canonical(ref)])
        raw = raw_by_ref[canonical(event["source_ref"])]
        locator = event["locator"]
        if locator is not None:
            try:
                text = raw.decode("utf8")
            except UnicodeError as error:
                raise DeliverableError("Core located source is not UTF8") from error
            if locator["quote"] not in text:
                raise DeliverableError("historical Core quote missing from source")
    for claim in records["claims"]:
        if claim["locator"] is None:
            continue
        raw = raw_by_ref[canonical(claim["core_event"]["payload"]["source_ref"])]
        text = raw.decode("utf8")
        if (
            claim["end"] > len(text)
            or text[claim["start"] : claim["end"]] != claim["quote"]
        ):
            raise DeliverableError("Core exact character span differs")
    return raw_by_ref


def read_artifacts(records, root):
    return validate_artifacts(records, lambda path: safe_path(root, path).read_bytes())
