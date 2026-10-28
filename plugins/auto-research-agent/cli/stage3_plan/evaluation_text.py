"""Mechanical raw-text subjects; no scientific extraction or model execution."""

import hashlib

from . import intake as source_intake
from .contracts import Stage3Error, digest
from .preparation import closed, sha256, text
from .storage import read_bytes, safe_path

REQUEST_KIND = "Stage3NativeTextEvaluationRequest"
SUBJECT_KIND = "Stage3NativeTextSubject"


def text_request_parts(source):
    """Re-admit shared science context and read one externally pinned snapshot."""
    closed(
        source,
        {"package", "delivery", "manifest_sha256", "text_path", "raw_sha256"},
        "native text source",
    )
    for name in ("package", "delivery", "text_path"):
        text(source[name], "native text " + name)
    for name in ("manifest_sha256", "raw_sha256"):
        sha256(source[name])
    normalized = {
        **source,
        **{
            name: str(safe_path(source[name]))
            for name in ("package", "delivery", "text_path")
        },
    }
    intake = source_intake.admit_intake(
        normalized["package"],
        normalized["delivery"],
        expected_manifest_sha256=source["manifest_sha256"],
    )
    refs = [row["question_ref"] for row in intake["questions"]]
    if not refs or len(refs) != len(set(refs)) or intake["legacy_candidates"]:
        raise Stage3Error("native text evaluation needs admitted scientific questions")
    raw = read_bytes(normalized["text_path"])
    if hashlib.sha256(raw).hexdigest() != source["raw_sha256"]:
        raise Stage3Error("native text external raw hash mismatch")
    try:
        value = raw.decode("utf-8")
    except UnicodeError as error:
        raise Stage3Error("native text subject must be UTF-8") from error
    if not value.lstrip("\ufeff").strip():
        raise Stage3Error("native text subject is empty")
    # Keep terminators, BOM and Unicode unchanged. No field extraction occurs.
    subject = {
        "kind": SUBJECT_KIND,
        "schema_version": "1.0.0",
        "encoding": "utf-8",
        "raw_sha256": source["raw_sha256"],
        "lines": value.splitlines(keepends=True),
    }
    bindings = {
        "subject_sha256": digest(subject),
        "intake_sha256": digest(intake),
        "source_manifest_sha256": intake["source_manifest_sha256"],
        "selected_candidates": intake["selected_candidates"],
        "question_refs": refs,
        "admission_scope": "source-verified-native-text",
        "native_execution_attested": False,
    }
    return normalized, bindings, subject, intake
