"""Output-only external material; saving it does not establish reading or choice."""


def unread_provided(candidate, events, reviews):
    """Only a genuinely unscreened, unassessed provided version gets this view."""
    work = candidate["work_id"]
    return (
        bool(candidate["discoveries"][-1].get("provided"))
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
    return next(
        (
            d["provided"]
            for d in reversed(candidate["discoveries"])
            if d["version_id"] == version and "provided" in d
        ),
        None,
    )
