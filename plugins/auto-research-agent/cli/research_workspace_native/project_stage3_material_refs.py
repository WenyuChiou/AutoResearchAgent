"""Small, revision-bound references to complete material files; never model input."""

from copy import deepcopy
import re

from .session_api import _check

MAX_MATERIAL_BYTES = 128 * 1024 * 1024


def revision_materials(body, parent, changed, binding, resolver, check_deadline):
    """Replace references only for edited material fields and verify new files."""
    retained = deepcopy((parent or {}).get("material_refs", []))
    replaced = {ref for ref, field in changed if field == "materials"}
    retained = [row for row in retained if row["question_ref"] not in replaced]
    submitted = body.get("material_refs", [])
    _check(
        type(submitted) is list and len(submitted) <= 8,
        "stage3-material-references-invalid",
        400,
    )
    seen = set()
    for row in submitted:
        _check(
            type(row) is dict
            and set(row) == {"question_ref", "file_id", "sha256", "bytes"},
            "stage3-material-reference-invalid",
            400,
        )
        question = row["question_ref"]
        _check(
            type(question) is str and question in replaced and question not in seen,
            "stage3-material-question-differs",
            409,
        )
        _check(
            type(row["file_id"]) is str
            and re.fullmatch(r"file-[0-9a-f]{32}", row["file_id"])
            and type(row["sha256"]) is str
            and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]),
            "stage3-material-reference-invalid",
            400,
        )
        _check(
            type(row["bytes"]) is int and 0 < row["bytes"] <= MAX_MATERIAL_BYTES,
            "stage3-material-capacity-exceeded",
            413,
        )
        _check(callable(resolver), "stage3-material-reader-unconnected", 409)
        if check_deadline:
            check_deadline()
        try:
            material = resolver(binding["project_ref"], row["file_id"])
        except (ValueError, OSError):
            _check(False, "stage3-material-file-unavailable", 409)
        _check(
            type(material) is dict
            and material.get("kind") == "manual-file"
            and material.get("status") == "registered"
            and material.get("stage") == 3
            and material.get("project_ref") == binding["project_ref"]
            and material.get("id") == row["file_id"]
            and type(material.get("bytes")) is int
            and material["bytes"] == row["bytes"]
            and material.get("sha256") == row["sha256"]
            and type(material.get("name")) is str,
            "stage3-material-file-differs",
            409,
        )
        if check_deadline:
            check_deadline()
        retained.append({**deepcopy(row), "name": material["name"]})
        seen.add(question)
    _check(len(retained) <= 8, "stage3-material-references-invalid", 400)
    return retained
