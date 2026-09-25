"""Check core, classic and closest-work nominations without deciding semantics.

The validator proves source/version/quote bindings and required reasoning fields.
An independent evaluator must still judge whether a passage supports the role.
"""

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[2] / "schemas/core-assessment.v1.schema.json"
    ).read_text(encoding="utf-8")
)
VALIDATOR = Draft202012Validator(SCHEMA)


def validate_assessment(record, root):
    errors = [
        f"schema:{'/'.join(map(str, error.absolute_path)) or '<root>'}:{error.message}"
        for error in sorted(VALIDATOR.iter_errors(record), key=str)
    ]
    if errors:
        return errors
    root = Path(root).resolve()
    sources = {row["source_id"]: row for row in record["sources"]}
    evidence = {row["evidence_id"]: row for row in record["evidence"]}
    works = {row["work_id"]: row for row in record["works"]}
    if len(sources) != len(record["sources"]):
        errors.append("duplicate source_id")
    if len(evidence) != len(record["evidence"]):
        errors.append("duplicate evidence_id")
    if len(works) != len(record["works"]):
        errors.append("duplicate work_id")
    for source_id, source in sources.items():
        path = (root / source["path"]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            errors.append(f"{source_id}: source path missing or escapes bundle")
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            errors.append(f"{source_id}: source bytes changed")
    for evidence_id, item in evidence.items():
        source = sources.get(item["source_id"])
        if source is None:
            errors.append(f"{evidence_id}: unknown source")
            continue
        path = (root / source["path"]).resolve()
        if path.is_relative_to(root) and path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeError:
                errors.append(f"{evidence_id}: source is not UTF-8 text")
                continue
            if item["quote"] not in text:
                errors.append(f"{evidence_id}: quote absent from bound source")
    needs = set(record["requirements"])
    for work_id, work in works.items():
        prefix = f"{work_id}:"
        if not set(work["requirement_ids"]).issubset(needs):
            errors.append(prefix + " undeclared requirement")
        if work_id in work["alternatives_considered"]:
            errors.append(prefix + " self cannot be an alternative")
        if not set(work["alternatives_considered"]).issubset(works):
            errors.append(prefix + " unknown alternative")
        bound = []
        for evidence_id in [*work["evidence_ids"], *work["recognition_evidence_ids"]]:
            item = evidence.get(evidence_id)
            if item is None or item["source_id"] not in sources:
                errors.append(prefix + f" unknown evidence {evidence_id}")
            else:
                bound.append((evidence_id, sources[item["source_id"]]))
        own = [
            evidence_id
            for evidence_id, source in bound
            if source["work_id"] == work_id
            and source["version_id"] == work["version_id"]
        ]
        if work["selection_tier"] == "topic-core":
            if not work["requirement_ids"] or not own:
                errors.append(
                    prefix + " topic-core needs a requirement and same-version source"
                )
            if not all(
                work[key].strip()
                for key in (
                    "contribution",
                    "decision_relevance",
                    "omission_consequence",
                )
            ):
                errors.append(prefix + " topic-core reasoning chain incomplete")
        if work["closest_status"] == "closest-supported":
            if "closest-work" not in work["roles"] or not own:
                errors.append(
                    prefix + " closest-work needs role and same-version source"
                )
            if not all(
                work["similarity_dimensions"].get(key, "").strip()
                for key in ("question", "system", "method", "outcome")
            ):
                errors.append(
                    prefix + " closest-work needs four explicit comparison dimensions"
                )
        if work["historical_status"] == "classic-supported":
            recognition_sources = {
                source["work_id"]
                for evidence_id, source in bound
                if evidence_id in work["recognition_evidence_ids"]
                and source["source_type"] == "recognition"
                and source["work_id"] != work_id
            }
            if len(recognition_sources) < 2:
                errors.append(
                    prefix + " classic requires two independent recognition sources"
                )
    return errors
