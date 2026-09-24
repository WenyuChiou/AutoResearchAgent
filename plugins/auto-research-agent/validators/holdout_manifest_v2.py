"""Validate versioned two-rater or Eric-led private Stage 1 holdouts."""

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator, FormatChecker

try:
    from .holdout_manifest import (
        EVAL_ROOT,
        REQUIRED_ROLES,
        RUBRIC,
        _validate_anchor_type,
        _validate_classic,
        _validate_private_artifact,
        canonical_sha256,
    )
except ImportError:  # Direct script execution.
    from holdout_manifest import (
        EVAL_ROOT,
        REQUIRED_ROLES,
        RUBRIC,
        _validate_anchor_type,
        _validate_classic,
        _validate_private_artifact,
        canonical_sha256,
    )


SCHEMA = json.loads(
    (EVAL_ROOT / "schemas" / "holdout-manifest.v2.schema.json").read_text(
        encoding="utf-8"
    )
)
SCHEMA_VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def validate_manifest_v2(manifest):
    errors = [
        f"schema:{'/'.join(map(str, error.absolute_path)) or '<root>'}:{error.message}"
        for error in sorted(SCHEMA_VALIDATOR.iter_errors(manifest), key=str)
    ]
    if errors:
        return errors

    required_clusters = set(RUBRIC["coverage_clusters"])
    clusters = set(manifest["coverage_clusters"])
    if clusters != required_clusters:
        errors.append("coverage_clusters must exactly match the frozen rubric")
    if set(manifest["required_roles"]) != REQUIRED_ROLES:
        errors.append("required_roles must contain the six frozen curation roles")

    single_human = manifest["schema_version"] == "2.1.0"
    actors = manifest["curation"]["actors"]
    rater_ids = {actor["actor_id"] for actor in actors}
    expected_raters = 1 if single_human else 2
    if len(actors) != expected_raters or len(rater_ids) != expected_raters:
        errors.append(
            f"curation requires exactly {expected_raters} distinct human raters"
        )
    if manifest["curation"]["independent_rating"] == single_human:
        errors.append("independent_rating must match the holdout protocol version")
    approvals = manifest["curation"]["human_approvals"]
    approval_ids = [approval["actor_id"] for approval in approvals]
    if len(approval_ids) != len(set(approval_ids)):
        errors.append("human approval actor IDs must be unique")
    if not set(approval_ids).issubset(rater_ids):
        errors.append("human approvals must name declared raters")
    _validate_private_artifact(manifest["answer_key"], "answer_key", errors)
    _validate_private_artifact(
        manifest["candidate_screening_log"], "candidate_screening_log", errors
    )
    for index, approval in enumerate(approvals):
        _validate_private_artifact(
            approval["approval_artifact"],
            f"human_approvals[{index}].approval_artifact",
            errors,
        )

    anchors = manifest["anchors"]
    disagreements = manifest["disagreements"]
    ids = [anchor["anchor_id"] for anchor in anchors] + [
        item["candidate_id"] for item in disagreements
    ]
    if len(ids) != len(set(ids)):
        errors.append("anchor and disagreement IDs must be unique")
    identities = [item["identity"]["doi_or_url"] for item in [*anchors, *disagreements]]
    if len(identities) != len(set(identities)):
        errors.append("anchor and disagreement work identities must be unique")

    covered_clusters = set()
    covered_roles = set()
    cutoff = date.fromisoformat(manifest["cutoff_date"])
    for anchor in anchors:
        prefix = anchor["anchor_id"]
        anchor_clusters = set(anchor["coverage_clusters"])
        anchor_roles = set(anchor["roles"])
        covered_clusters.update(anchor_clusters)
        covered_roles.update(anchor_roles)
        if not anchor_clusters.issubset(clusters):
            errors.append(f"{prefix} names an undeclared coverage cluster")
        if not anchor_roles.issubset(REQUIRED_ROLES):
            errors.append(f"{prefix} names an undeclared curation role")
        ratings = anchor["independent_ratings"]
        if (
            len(ratings) != expected_raters
            or {rating["rater_id"] for rating in ratings} != rater_ids
        ):
            errors.append(f"{prefix} requires one rating from each declared rater")
        if any(rating["decision"] != "include" for rating in ratings):
            errors.append(f"{prefix} requires unanimous inclusion")
        _validate_classic(anchor, cutoff.year, errors)
        _validate_anchor_type(anchor, errors, min_confirmations=expected_raters)

    if single_human and disagreements:
        errors.append("single-human curation cannot declare inter-rater disagreements")
    for item in disagreements:
        prefix = item["candidate_id"]
        ratings = item["independent_ratings"]
        if (
            len(ratings) != expected_raters
            or {rating["rater_id"] for rating in ratings} != rater_ids
        ):
            errors.append(f"{prefix} requires one rating from each declared rater")
        if {rating["decision"] for rating in ratings} != {"include", "exclude"}:
            errors.append(f"{prefix} must preserve an actual rater disagreement")

    if covered_clusters != required_clusters:
        errors.append("anchors must collectively cover all six frozen clusters")
    if covered_roles != REQUIRED_ROLES:
        errors.append("anchors must collectively cover all six curation roles")
    if not any(
        anchor["anchor_type"] in {"core", "core-and-must-have"} for anchor in anchors
    ):
        errors.append("holdout requires at least one classic core anchor")
    if not any(
        anchor["anchor_type"] in {"must-have", "core-and-must-have"}
        for anchor in anchors
    ):
        errors.append("holdout requires at least one must-have anchor")

    if manifest["status"] == "frozen":
        if manifest["frozen_at"] is None:
            errors.append("a frozen manifest requires frozen_at")
        if set(approval_ids) != rater_ids:
            errors.append(
                "a frozen manifest requires approval from the sole rater"
                if single_human
                else "a frozen manifest requires approval from both raters"
            )
        if manifest["frozen_at"] is not None:
            created_at = datetime.fromisoformat(manifest["created_at"])
            frozen_at = datetime.fromisoformat(manifest["frozen_at"])
            if frozen_at < created_at:
                errors.append("frozen_at must not precede created_at")
            if cutoff > frozen_at.date():
                errors.append("cutoff_date must not be later than frozen_at")
            for approval in approvals:
                approved_at = datetime.fromisoformat(approval["approved_at"])
                if not created_at <= approved_at <= frozen_at:
                    errors.append(
                        f"approval by {approval['actor_id']} must occur between creation and freeze"
                    )
    elif manifest["frozen_at"] is not None:
        errors.append("a draft manifest must not set frozen_at")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--print-sha256", action="store_true")
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    errors = validate_manifest_v2(manifest)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Stage 1 holdout manifest is valid.")
    if args.print_sha256:
        print(canonical_sha256(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
