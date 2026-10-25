"""Derived assessor views; original request/plan bytes are never rewritten."""

from pathlib import PurePosixPath, PureWindowsPath

from .contracts import digest


def assessor_view(request, subject_id):
    """Return a neutral view and its private reversible identifier mapping."""
    aliases = {}

    def collect(value, identifier=False):
        if isinstance(value, dict):
            for key, item in value.items():
                collect(item, key.endswith(("_id", "_ids", "_ref", "_refs")))
        elif isinstance(value, list):
            for item in value:
                collect(item, identifier)
        elif identifier and isinstance(value, str):
            aliases.setdefault(value, "ref-" + digest(value)[:24])

    collect(request["assessor_view"])
    aliases[request["assessor_view"]["plan"]["plan_id"]] = subject_id

    def project(value):
        if isinstance(value, dict):
            return {key: project(item) for key, item in value.items()}
        if isinstance(value, list):
            return [project(item) for item in value]
        if isinstance(value, str):
            if (
                PurePosixPath(value).is_absolute()
                or PureWindowsPath(value).is_absolute()
            ):
                return "private-location-withheld"
            return aliases.get(value, value)
        return value

    return {
        "kind": "Stage3CampaignAssessorView",
        "subject_id": subject_id,
        "request_sha256": None,
        **project(request["assessor_view"]),
        "catalog": request["catalog"]["selected_criteria"],
        "guidance_version": request["guidance"]["version"],
        "identity_and_isolation": "unverified",
        "blinding_limit": "Identifier/path masking does not prove absence of content clues.",
    }, aliases


def restore_judgment(value, aliases):
    """Translate only declared neutral question refs; retain the supplied raw bytes."""
    if not isinstance(value, dict):
        return value
    reverse = {alias: original for original, alias in aliases.items()}
    for criterion in (
        value.get("criteria", []) if isinstance(value.get("criteria"), list) else []
    ):
        if not isinstance(criterion, dict):
            continue
        for row in (
            criterion.get("question_assessments", [])
            if isinstance(criterion.get("question_assessments"), list)
            else []
        ):
            if isinstance(row, dict) and isinstance(row.get("question_ref"), str):
                row["question_ref"] = reverse.get(
                    row["question_ref"], row["question_ref"]
                )
    return value
