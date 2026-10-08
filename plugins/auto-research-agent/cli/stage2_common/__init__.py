"""Shared Stage 2 packet validation and canonical byte bindings."""

from .contract import (
    Stage2Error,
    canonical_hash,
    stage1_projection_hash,
    validate_evidence_refs,
    validate_packet,
)
from .prior_work import current_prior_work_reviews


def source_set_hash(packet):
    """Return the canonical hash of the complete sources/evidence projection."""

    from .prior_work import source_set_hash as hash_source_set

    return hash_source_set(packet, canonical_hash)


def validate_prior_work_reviews(packet, root):
    """Validate the opt-in review contract against packet and receipt bytes."""

    from .prior_work import validate_prior_work_reviews as validate

    return validate(packet, root, canonical_hash=canonical_hash, error_type=Stage2Error)


__all__ = [
    "Stage2Error",
    "canonical_hash",
    "current_prior_work_reviews",
    "source_set_hash",
    "stage1_projection_hash",
    "validate_evidence_refs",
    "validate_packet",
    "validate_prior_work_reviews",
]
