"""Prepare rich Stage2 contracts before initializing its immutable workflow."""

import os
import stat

from stage1_deliverable.common import reject_links, sha
from stage1_ledger.journal import canonical, decode
from stage2_common import canonical_hash, validate_packet
from stage2_ideation.seed_profile import derive_opt_in_packet

from .session_api import _check

PACKET_FILE = "scientific-initial-packet.json"
MAX_PACKET = 16 * 1024 * 1024


def read_initial_seed(seed_root, expected_packet_sha256):
    path = seed_root / "packet.json"
    reject_links(path)
    _check(stat.S_ISREG(path.stat().st_mode), "stage2-initial-seed-not-regular")
    with path.open("rb") as stream:
        raw = stream.read(MAX_PACKET + 1)
    _check(len(raw) <= MAX_PACKET, "stage2-initial-seed-too-large")
    packet = decode(raw, "original Stage2 import packet")
    _check(
        canonical_hash(packet) == expected_packet_sha256,
        "stage2-initial-seed-differs",
    )
    return packet


def _profile_packet(seed_root, original):
    _check(not original["candidates"], "stage2-initial-profile-requires-empty-seed")
    validate_packet(original, seed_root)
    packet, steps = original, []
    for options in (
        {},
        {"supplemental_versions": True},
        {"prior_work_reviews": True},
        {"scientific_arguments": True},
    ):
        parent = canonical_hash(packet)
        packet = derive_opt_in_packet(packet, **options)
        steps.append(
            dict(
                options=options,
                parent_packet_sha256=parent,
                packet_sha256=canonical_hash(packet),
            )
        )
    validate_packet(packet, seed_root)
    raw = canonical(packet)
    _check(len(raw) <= MAX_PACKET, "stage2-initial-profile-too-large")
    descriptor = dict(
        kind="Stage2InitialPacketProfile",
        schema_version="1.0.0",
        profile="scientific-v3",
        parent_packet_sha256=canonical_hash(original),
        packet_sha256=canonical_hash(packet),
        packet_file_sha256=sha(raw),
        packet_file=PACKET_FILE,
        transitions=steps,
        scientific_quality_verified=False,
        execution_authorized=False,
    )
    return raw, descriptor


def prepare_initial_packet(seed_root, policy_ref, original):
    """Explicit trusted policy opt-in; original import packet remains untouched."""
    profile = policy_ref.get("packet_profile", "legacy-v2")
    _check(profile in ("legacy-v2", "scientific-v3"), "stage2-packet-profile-invalid")
    if profile == "legacy-v2":
        return seed_root / "packet.json", canonical_hash(original), None
    raw, descriptor = _profile_packet(seed_root, original)
    path = seed_root / PACKET_FILE
    reject_links(path)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return path, descriptor["packet_sha256"], descriptor


def inspect_initial_packet(seed_root, policy_ref, original, descriptor):
    """Recompute the exact opt-ins; neither schema changes nor rehashing suffice."""
    profile = policy_ref.get("packet_profile", "legacy-v2")
    if profile == "legacy-v2":
        _check(descriptor is None, "stage2-unexpected-initial-profile")
        return seed_root / "packet.json", canonical_hash(original)
    _check(profile == "scientific-v3", "stage2-packet-profile-invalid")
    expected_raw, expected = _profile_packet(seed_root, original)
    _check(descriptor == expected, "stage2-initial-profile-binding-differs")
    path = seed_root / PACKET_FILE
    reject_links(path)
    _check(stat.S_ISREG(path.stat().st_mode), "stage2-initial-profile-not-regular")
    with path.open("rb") as stream:
        raw = stream.read(MAX_PACKET + 1)
    _check(
        len(raw) <= MAX_PACKET and raw == expected_raw,
        "stage2-initial-profile-bytes-differ",
    )
    return path, canonical_hash(decode(raw, "initial profile packet"))
