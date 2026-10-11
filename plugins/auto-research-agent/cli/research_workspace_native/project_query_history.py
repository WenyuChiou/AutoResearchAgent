"""Causal project reservations and the single bootstrap-owned ledger identity.

These checks detect state/history divergence. Local SQLite is not a hostile
multi-tenant trust boundary or a cryptographic native execution attestation.
"""

import json
import math
from pathlib import Path

from stage1_deliverable.common import canonical, sha
from .planned_query_contract import HASH, require


def reserved_intents(intake, state, principal, limits, timeout):
    expected = dict(probes=0, attempts=0, seconds=0)
    intents = {}
    for kind, field, seconds in (
        ("stage1-query-bootstrap", "probes", 30),
        ("stage1-query-execute", "attempts", timeout + 30),
    ):
        events = intake.db.execute(
            "SELECT payload FROM intake_events WHERE project=? AND kind=?",
            (state["project_ref"], kind + "-intent"),
        ).fetchall()
        for event in events:
            intent = json.loads(event[0])
            digest = intent["request_sha256"]
            require(
                digest not in intents
                and intent["status"] == "intent-recorded"
                and intent["kind"] == kind
                and intent["project_ref"] == state["project_ref"]
                and digest == sha(canonical(dict(kind=kind, body=intent["request"]))),
                "project-query-reservation-event-differs",
            )
            row = intake.db.execute(
                "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                (principal, state["project_ref"], intent["key"]),
            ).fetchone()
            require(
                row is not None and row[0] == digest,
                "project-query-reservation-action-missing",
            )
            saved = json.loads(row[1])
            require(
                all(
                    saved[k] == intent[k]
                    for k in ("kind", "project_ref", "key", "request_sha256", "request")
                ),
                "project-query-reservation-action-differs",
            )
            intents[digest] = saved
            expected[field] += 1
            expected["seconds"] += seconds
    budget = state["stage1_query_budget"]
    require(
        set(budget) == set(expected)
        and all(
            type(budget[k]) is int and budget[k] >= 0 for k in ("probes", "attempts")
        )
        and type(budget["seconds"]) in (int, float)
        and math.isfinite(budget["seconds"])
        and budget["seconds"] >= 0
        and budget == expected
        and expected["probes"] <= 1
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
        and action["kind"] == "stage1-query-execute"
        and action["status"] in {"saved", "intent-recorded", "execution-unknown"}
        and event["principal"] == principal
        and event["project_ref"] == ref,
        "project-query-admission-intent-missing",
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
