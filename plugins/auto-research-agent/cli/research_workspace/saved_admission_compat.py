"""Explicit compatibility for a trusted historical producer and current receiver.

This validates independently supplied evidence. It never creates Core acceptance,
relabels the producer, executes archived code, or grants Stage2 execution.
"""

import hashlib
from pathlib import Path

from jsonschema import Draft202012Validator
from stage1_deliverable.common import canonical, sha

from .host_replay import HostReplay
from .saved_admission_evidence import read_bound, read_bound_json

SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "schemas/stage1-saved-admission-compat.v2.schema.json"
)
SCOPE = "saved-source-producer-receiver-compatibility"


def check_compatibility(
    root, acceptance, snapshot_digest, snapshot, view_manifest, host_replay
):
    # Delayed import avoids a module cycle. The public entry checks the external
    # envelope digest before this helper; neither a root override nor a v1 failure
    # can opt into compatibility.
    from .saved_admission import _check_acceptance_v1, _check_producer, require

    import json

    schema = json.loads(SCHEMA.read_bytes())
    errors = list(Draft202012Validator(schema).iter_errors(acceptance))
    require(not errors, "compatibility acceptance contract invalid")
    for field, expected in (
        ("snapshot_sha256", snapshot_digest),
        ("project_id", snapshot["project_id"]),
        ("input_version", snapshot["input_version"]),
        ("contract_sha256", hashlib.sha256(SCHEMA.read_bytes()).hexdigest()),
    ):
        require(
            type(acceptance[field]) is type(expected) and acceptance[field] == expected,
            "compatibility binding mismatch: " + field,
        )
    require(
        isinstance(host_replay, HostReplay), "compatibility needs verified host replay"
    )
    host_replay.check_snapshot(root, acceptance["snapshot_ref"])
    require(
        acceptance["snapshot_ref"]["sha256"] == snapshot_digest,
        "compatibility snapshot reference differs",
    )
    replay = host_replay.evidence()
    require(
        replay["sha256"] == acceptance["host_replay_sha256"]
        and replay["new_source_execution"] is False
        and replay["core_acceptance"] is False,
        "compatibility host replay binding differs",
    )

    receiver = acceptance["receiver"]
    # Exactly today's complete installed source closure, not a subset of the
    # historical producer. Source/post-main CI remains receiver-only.
    _check_producer(receiver, root)
    historical_ref = acceptance["historical_acceptance"]
    historical = read_bound_json(root, historical_ref)
    require(
        type(historical) is dict
        and historical.get("kind") == "SavedSourceAdmissionAcceptance"
        and historical.get("schema_version") == "1.0.0",
        "historical acceptance must retain v1 identity",
    )
    archived = acceptance["historical_sources"]
    require(
        set(archived) == set(historical["producer"]["sources"]),
        "historical producer inventory incomplete",
    )
    for name, ref in archived.items():
        require(
            ref["sha256"] == historical["producer"]["sources"][name],
            "historical producer digest differs",
        )
        read_bound(root, ref)

    review = read_bound_json(root, acceptance["compatibility_review"])
    expected = {
        "kind",
        "schema_version",
        "snapshot_sha256",
        "project_id",
        "input_version",
        "historical_acceptance_sha256",
        "receiver_delivered_commit",
        "receiver_sources_sha256",
        "host_replay_sha256",
        "scope",
        "validator",
        "rubric",
        "results",
        "outcome",
        "observations",
        "evidence",
        "scientific_acceptance",
        "execution_authorized",
    }
    require(
        type(review) is dict and set(review) == expected,
        "compatibility review fields invalid",
    )
    for field, value in (
        ("kind", "SavedSourceAdmissionCompatibilityReview"),
        ("schema_version", "1.0.0"),
        ("snapshot_sha256", snapshot_digest),
        ("project_id", snapshot["project_id"]),
        ("input_version", snapshot["input_version"]),
        ("historical_acceptance_sha256", historical_ref["sha256"]),
        ("receiver_delivered_commit", receiver["delivered_commit"]),
        ("receiver_sources_sha256", sha(canonical(receiver["sources"]))),
        ("host_replay_sha256", replay["sha256"]),
        ("scope", SCOPE),
        ("outcome", "accepted"),
        ("scientific_acceptance", False),
        ("execution_authorized", False),
    ):
        require(
            type(review[field]) is type(value) and review[field] == value,
            "compatibility review binding mismatch: " + field,
        )
    require(
        type(review["observations"]) is str
        and bool(review["observations"].strip())
        and type(review["results"]) is list
        and bool(review["results"])
        and type(review["evidence"]) is list
        and bool(review["evidence"]),
        "compatibility review incomplete",
    )
    for item in review["results"]:
        require(
            type(item) is dict
            and set(item) == {"check_id", "status", "locator", "reason"}
            and item["status"] == "passed"
            and all(
                type(item[key]) is str and bool(item[key].strip())
                for key in ("check_id", "locator", "reason")
            ),
            "compatibility result invalid",
        )
    for ref in [review["validator"], review["rubric"], *review["evidence"]]:
        read_bound(root, ref)

    # Preserve all four original category/rubric/result bindings, actual seven
    # HTML actions, producer identity/CI and exact BibTeX/view membership checks.
    # Archived source references contain bytes only and are never imported.
    _check_acceptance_v1(
        root,
        historical_ref,
        historical_ref["sha256"],
        snapshot_digest,
        snapshot,
        view_manifest,
        historical_sources=archived,
    )
    return acceptance
