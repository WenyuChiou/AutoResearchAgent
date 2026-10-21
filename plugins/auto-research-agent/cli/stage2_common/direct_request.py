"""Explicit direct-request origin; no Stage 1 or human-decision attestation."""

import hashlib

VERSION = "2.6.0"
RESOURCES = "Unknown; only the original research request is supplied."


def request_brief(text):
    """Retain the request without inventing a user's scope decisions."""
    return {
        "kind": "ResearchBrief",
        "schema_version": "1.0.0",
        "original_description": text,
        "needs": [{"need_id": "direct-request", "question": text}],
        "scope_fields": [
            {
                "field": "geography",
                "material": False,
                "reason": "Direct request retained verbatim; no derived scope decision.",
            }
        ],
        "suggestions": [],
        "decisions": [],
    }


def validate_direct_origin(packet, *, canonical_hash, error_type):
    """Check immutable input identity, not research quality or human identity."""
    origin = packet["entry"]
    text = origin["request_text"]
    if "\x00" in text or not text.strip() or len(text.encode("utf-8")) > 8192:
        raise error_type("direct-request-invalid-text")
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != origin["request_sha256"]:
        raise error_type("direct-request-byte-hash-mismatch")
    unsigned = {k: v for k, v in origin.items() if k != "binding_sha256"}
    if canonical_hash(unsigned) != origin["binding_sha256"]:
        raise error_type("direct-request-binding-hash-mismatch")
    if packet["brief"] != request_brief(text) or packet["resources"] != RESOURCES:
        raise error_type("direct-request-derived-input-mismatch")
    for field in ("sources", "evidence", "literature", "supplemental_literature"):
        if any(row["origin"] != "stage2" for row in packet[field]):
            raise error_type("direct-request-cannot-claim-stage1-origin")
