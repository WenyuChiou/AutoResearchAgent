"""Output-only external material; saving it does not establish reading or choice."""


def unread_provided(candidate, events, reviews):
    """Only a genuinely unscreened, unassessed provided version gets this view."""
    work = candidate["work_id"]
    return (
        bool(
            provided_for_version(candidate, candidate["discoveries"][-1]["version_id"])
        )
        and work not in reviews
        and not any(
            (p["kind"] == "DecisionEvent" and p["subject_id"] == work)
            or (
                p["kind"] in {"ClaimEvidence", "CoverageWorkReview"}
                and p["work_id"] == work
            )
            for p in events.values()
        )
    )


def provided_for_version(candidate, version):
    """Latest metadata fallback; report provenance uses the complete list."""
    materials = provided_materials_for_version(candidate, version)
    return materials[-1] if materials else None


def provided_materials_for_version(candidate, version):
    """Preserve each recorded material and its own URI/hash in journal order."""
    return [
        d["provided"]
        for d in candidate["discoveries"]
        if d["version_id"] == version and "provided" in d
    ]
