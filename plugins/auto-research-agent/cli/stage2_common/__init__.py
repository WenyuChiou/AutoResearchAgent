"""Shared Stage 2 packet validation and canonical byte bindings."""

from .contract import (
    Stage2Error,
    canonical_hash,
    validate_evidence_refs,
    validate_packet,
)

__all__ = [
    "Stage2Error",
    "canonical_hash",
    "validate_evidence_refs",
    "validate_packet",
]
