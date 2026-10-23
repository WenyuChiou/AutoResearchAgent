"""Existing opt-in seed transitions, shared by CLI and trusted initialization."""

from copy import deepcopy

from stage2_common import Stage2Error, validate_packet


def prepare_opt_in_packet(
    original,
    source_root,
    *,
    supplemental_versions=False,
    prior_work_reviews=False,
    scientific_arguments=False,
):
    """Prepare a new packet; never change the version of an existing workflow."""
    validate_packet(original, source_root)
    packet = derive_opt_in_packet(
        original,
        supplemental_versions=supplemental_versions,
        prior_work_reviews=prior_work_reviews,
        scientific_arguments=scientific_arguments,
    )
    validate_packet(packet, source_root)
    return packet


def derive_opt_in_packet(
    original,
    *,
    supplemental_versions=False,
    prior_work_reviews=False,
    scientific_arguments=False,
):
    """Pure transform only; its caller must validate the input and final packet."""
    version = original["schema_version"]
    if (
        version not in {"2.0.0", "2.1.0"}
        and not (version == "2.2.0" and supplemental_versions)
        and not (version == "2.3.0" and prior_work_reviews)
        and not (
            version == "2.4.0" and scientific_arguments and not original["candidates"]
        )
    ):
        raise Stage2Error(
            "topic tables require an eligible opt-in seed; scientific arguments "
            "require an unformed packet 2.4 seed"
        )
    if scientific_arguments and (version != "2.4.0" or original["candidates"]):
        raise Stage2Error(
            "scientific arguments require an unformed packet 2.4 input seed"
        )
    packet = deepcopy(original)
    packet["schema_version"] = (
        "2.5.0"
        if scientific_arguments
        else "2.4.0"
        if prior_work_reviews
        else "2.3.0"
        if supplemental_versions
        else "2.2.0"
    )
    if supplemental_versions:
        packet["supplemental_literature"] = []
    elif prior_work_reviews:
        packet.setdefault("supplemental_literature", [])
    if prior_work_reviews:
        packet["prior_work_reviews"] = []
    packet["research_tables"] = None
    return packet
