"""Validate the public contract for a privately curated holdout manifest."""

import argparse
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator, FormatChecker


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = PLUGIN_ROOT / "evals"
SCHEMA_PATH = EVAL_ROOT / "schemas" / "holdout-manifest.v1.schema.json"
RUBRIC_PATH = EVAL_ROOT / "rubrics" / "aging-bidirectional-rubric.v1.json"
REQUIRED_ROLES = {
    "theoretical-mechanism",
    "quantitative-evidence",
    "population-to-agent",
    "simulation-method",
    "cross-context-case",
    "validation",
}


SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
RUBRIC = json.loads(RUBRIC_PATH.read_text(encoding="utf-8"))
SCHEMA_VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def canonical_bytes(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def canonical_sha256(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def validate_manifest(manifest):
    errors = [
        f"schema:{'/'.join(map(str, error.absolute_path)) or '<root>'}:{error.message}"
        for error in sorted(SCHEMA_VALIDATOR.iter_errors(manifest), key=str)
    ]
    if errors:
        return errors

    clusters = set(manifest["coverage_clusters"])
    required_clusters = set(RUBRIC["coverage_clusters"])
    if clusters != required_clusters:
        errors.append("coverage_clusters must exactly match the frozen rubric")
    if set(manifest["required_roles"]) != REQUIRED_ROLES:
        errors.append("required_roles must contain the six frozen curation roles")

    curation = manifest["curation"]
    actors = curation["actors"]
    actor_ids = [actor["actor_id"] for actor in actors]
    if len(actor_ids) != len(set(actor_ids)):
        errors.append("curation actor_id values must be unique")
    declared_actors = set(actor_ids)
    rater_ids = {actor["actor_id"] for actor in actors if actor["role"] == "rater"}
    adjudicator_ids = [
        actor["actor_id"] for actor in actors if actor["role"] == "adjudicator"
    ]
    if len(rater_ids) < 2:
        errors.append("curation requires at least two independent human raters")
    if len(adjudicator_ids) != 1:
        errors.append("curation requires exactly one independent human adjudicator")
    adjudicator_id = adjudicator_ids[0] if len(adjudicator_ids) == 1 else None

    approvals = curation["human_approvals"]
    approval_ids = [approval["actor_id"] for approval in approvals]
    if len(approval_ids) != len(set(approval_ids)):
        errors.append("human approval actor IDs must be unique")
    if not set(approval_ids).issubset(declared_actors):
        errors.append("human approvals must name declared human actors")
    _validate_private_artifact(manifest["answer_key"], "answer_key", errors)
    for index, approval in enumerate(approvals):
        _validate_private_artifact(
            approval["approval_artifact"],
            f"human_approvals[{index}].approval_artifact",
            errors,
        )

    anchors = manifest["anchors"]
    anchor_ids = [anchor["anchor_id"] for anchor in anchors]
    if len(anchor_ids) != len(set(anchor_ids)):
        errors.append("anchor_id values must be unique")
    identities = [anchor["identity"]["doi_or_url"] for anchor in anchors]
    if len(identities) != len(set(identities)):
        errors.append("anchor work identities must be unique")

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
        _validate_ratings(anchor, rater_ids, adjudicator_id, errors)
        _validate_classic(anchor, cutoff.year, errors)
        _validate_anchor_type(anchor, errors)

    if covered_clusters != required_clusters:
        errors.append("anchors must collectively cover all six frozen clusters")
    if covered_roles != REQUIRED_ROLES:
        errors.append("anchors must collectively cover all six curation roles")
    if not any(
        anchor["anchor_type"] in {"core", "core-and-must-have"} for anchor in anchors
    ):
        errors.append("holdout requires at least one core anchor")
    if not any(
        anchor["anchor_type"] in {"must-have", "core-and-must-have"}
        for anchor in anchors
    ):
        errors.append("holdout requires at least one must-have anchor")

    if manifest["status"] == "frozen":
        if manifest["frozen_at"] is None:
            errors.append("a frozen manifest requires frozen_at")
        if len(set(approval_ids)) < 2:
            errors.append("a frozen manifest requires two human approvals")
        if any(
            len({rating["rater_id"] for rating in anchor["independent_ratings"]}) < 2
            for anchor in anchors
        ):
            errors.append("every frozen anchor requires two independent raters")
        if manifest["frozen_at"] is not None:
            _validate_timestamps(manifest, approvals, errors)
    elif manifest["frozen_at"] is not None:
        errors.append("a draft manifest must not set frozen_at")
    return errors


def _is_safe_private_path(value):
    if not value.startswith("private/") or "\\" in value:
        return False
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return False
    parts = value.split("/")
    return len(parts) > 1 and all(part not in {"", ".", ".."} for part in parts)


def _validate_private_artifact(artifact, label, errors):
    if not _is_safe_private_path(artifact["path"]):
        errors.append(f"{label} path must be a normalized path below private/")


def _validate_ratings(anchor, declared_raters, adjudicator_id, errors):
    prefix = anchor["anchor_id"]
    ratings = anchor["independent_ratings"]
    rating_ids = [rating["rater_id"] for rating in ratings]
    if len(rating_ids) != len(set(rating_ids)):
        errors.append(f"{prefix} has duplicate independent rater IDs")
    if not set(rating_ids).issubset(declared_raters):
        errors.append(f"{prefix} uses an undeclared rater")
    decisions = {rating["decision"] for rating in ratings}
    adjudication = anchor["adjudication"]
    if len(decisions) == 1:
        final_decision = next(iter(decisions))
        if adjudication is not None:
            errors.append(
                f"{prefix} has unnecessary adjudication for unanimous ratings"
            )
    elif adjudication is None:
        errors.append(f"{prefix} has unresolved rater disagreement")
        final_decision = None
    else:
        final_decision = adjudication["decision"]
    if adjudication and adjudication["adjudicator_id"] != adjudicator_id:
        errors.append(f"{prefix} uses the wrong adjudicator")
    if final_decision is not None and final_decision != "include":
        errors.append(f"{prefix} final curation decision must be include")


def _validate_classic(anchor, cutoff_year, errors):
    prefix = anchor["anchor_id"]
    classic = anchor["classic_assessment"]
    scores = [
        classic["field_recognition"],
        classic["foundational_role"],
        classic["durability"],
    ]
    qualifies = (
        anchor["identity"]["year"] <= cutoff_year - 5
        and 0 not in scores
        and sum(scores) >= 5
        and len(classic["authority_evidence_ids"]) >= 2
    )
    if (classic["status"] == "qualifies") != qualifies:
        errors.append(f"{prefix} classic status contradicts the frozen rule")


def _must_have_confirmation_passes(rating):
    assessment = rating["must_have_assessment"]
    return (
        rating["decision"] == "include"
        and assessment is not None
        and assessment["directness"] == 2
        and assessment["decision_impact"] == 2
        and assessment["evidence_quality"] >= 1
        and assessment["no_equally_direct_substitute"]
    )


def _validate_anchor_type(anchor, errors):
    prefix = anchor["anchor_id"]
    anchor_type = anchor["anchor_type"]
    classic = anchor["classic_assessment"]["status"] == "qualifies"
    if anchor_type in {"core", "core-and-must-have"} and not classic:
        errors.append(f"{prefix} core status requires classic qualification")
    if anchor_type in {"must-have", "core-and-must-have"}:
        importance = anchor["importance"]
        if not (
            importance["directness"] == 2
            and importance["decision_impact"] == 2
            and importance["evidence_quality"] >= 1
            and not importance["equally_direct_substitute"]
        ):
            errors.append(f"{prefix} does not satisfy the aggregate must-have rule")
        confirmations = sum(
            _must_have_confirmation_passes(rating)
            for rating in anchor["independent_ratings"]
        )
        if confirmations < 2:
            errors.append(f"{prefix} needs two passing must-have rater confirmations")


def _validate_timestamps(manifest, approvals, errors):
    created_at = datetime.fromisoformat(manifest["created_at"])
    frozen_at = datetime.fromisoformat(manifest["frozen_at"])
    cutoff = date.fromisoformat(manifest["cutoff_date"])
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
    for anchor in manifest["anchors"]:
        adjudication = anchor["adjudication"]
        if adjudication is None:
            continue
        decided_at = datetime.fromisoformat(adjudication["decided_at"])
        if not created_at <= decided_at <= frozen_at:
            errors.append(
                f"{anchor['anchor_id']} adjudication must occur between creation and freeze"
            )


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--print-sha256", action="store_true")
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    errors = validate_manifest(manifest)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Holdout manifest is valid.")
    if args.print_sha256:
        print(canonical_sha256(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
