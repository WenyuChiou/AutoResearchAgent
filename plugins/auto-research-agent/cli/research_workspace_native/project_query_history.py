"""Causal project reservations and the single bootstrap-owned ledger identity.

These checks detect state/history divergence. Local SQLite is not a hostile
multi-tenant trust boundary or a cryptographic native execution attestation.
"""

import json
from pathlib import Path

from stage1_deliverable.common import canonical, sha
from .planned_query_contract import HASH, require


def reserved_intents(intake, state, principal, limits, timeout):
    from .project_resource_budget import query_resources

    expected = dict(probes=0, attempts=0, seconds=0)
    rows, all_intents = query_resources(intake, state, principal)
    permit = state["stage1_query_authorization"]["permit"]
    identity = permit["binding"]
    require(
        permit["principals"] == [principal]
        and permit["limits"] == limits
        and limits["timeout_seconds"] == timeout,
        "project-query-reservation-permit-differs",
    )
    intents = {}
    for digest, (seconds, _, basis) in rows.items():
        if basis["input_version"] != identity["project_input_version"]:
            continue
        require(
            basis["brief_sha256"] == identity["input_bytes_sha256"],
            "project-query-reservation-input-differs",
        )
        intents[digest] = all_intents[digest]
        expected[
            "probes"
            if intents[digest]["kind"] == "stage1-query-bootstrap"
            else "attempts"
        ] += 1
        expected["seconds"] += seconds
    expansions = {
        digest
        for digest, row in all_intents.items()
        if row["kind"] == "stage1-expansion-execute"
    }
    uses = state.get("stage1_expansion_uses", {})
    require(
        type(uses) is dict
        and len(uses) == len(set(uses.values()))
        and set(uses.values()) == expansions
        and set(state.get("stage1_expansion_dispatches", {})) == expansions,
        "project-expansion-consumption-history-differs",
    )
    require(
        expected["probes"] <= 1
        and expected["attempts"] <= limits["max_attempts"]
        and expected["seconds"] <= limits["max_reserved_seconds"],
        "project-query-reservation-history-differs",
    )
    return intents


def admitted_query(intents, event, ref, principal):
    client = event.get("client_key")
    require(
        isinstance(client, str)
        and client.startswith("project-")
        and HASH.fullmatch(client[8:]),
        "project-query-admission-key-differs",
    )
    action = intents.get(client[8:])
    require(
        action is not None
        and action["kind"] in {"stage1-query-execute", "stage1-expansion-execute"}
        and action["status"] in {"saved", "intent-recorded", "execution-unknown"}
        and event["principal"] == principal
        and event["project_ref"] == ref,
        "project-query-admission-intent-missing",
    )
    expansion = action["kind"] == "stage1-expansion-execute"
    offer = event["offer"]
    require(
        sha(canonical(offer)) == action["request"]["offer_sha256"]
        and ("expansion_grant_sha256" in offer) == expansion
        and (
            not expansion
            or offer.get("operation") in {"references", "cited-by"}
            and offer["arguments"].get("operation") == offer["operation"]
            and offer["arguments"]["coverage"].get("seed_work_id") == offer["work_id"]
            and offer["arguments"]["coverage"].get("seed_version_id")
            == offer["version_id"]
        ),
        "project-query-admission-offer-differs",
    )
    # A committed response must identify this inner action. A lost commit retains
    # the same observation independently; neither grants a second dispatch.
    observation = action.get("output_observation", action)
    if action["status"] != "intent-recorded":
        require(
            observation.get("query_action_key") == client,
            "project-query-admission-observation-differs",
        )


def bound_run(intake, state, basis, run):
    permit = state["stage1_query_authorization"]["permit"]
    reserved_intents(
        intake,
        state,
        permit["principals"][0],
        permit["limits"],
        permit["limits"]["timeout_seconds"],
    )
    jobs = list(state.get("stage1_query_jobs", {}).values())
    require(
        len(jobs) == 1 and jobs[0]["status"] == "completed",
        "project-query-run-bootstrap-not-completed",
    )
    job = jobs[0]
    events = intake.db.execute(
        "SELECT payload FROM intake_events WHERE project=? AND kind=?",
        (state["project_ref"], "stage1-query-bootstrap-observation"),
    ).fetchall()
    require(
        any(json.loads(row[0]) == job for row in events),
        "project-query-run-observation-differs",
    )
    registration, receipt = job["registration"], job["receipt"]
    expected = dict(
        run_ref="stage1-live-" + job["request_sha256"][:24],
        path=Path(registration["ledger_root"]).name,
        binding=basis,
        manifest_sha256=receipt["ledger_manifest_sha256"],
        query_owned=True,
    )
    require(
        set(run) <= set(expected) | {"last_checkpoint"}
        and all(run.get(k) == v for k, v in expected.items())
        and state["stage1_active"] == expected["run_ref"]
        and intake._path(state["project_ref"], run["path"]).as_posix()
        == registration["ledger_root"]
        and registration["ledger_manifest_sha256"] == receipt["ledger_manifest_sha256"],
        "project-query-run-identity-differs",
    )
    return registration
