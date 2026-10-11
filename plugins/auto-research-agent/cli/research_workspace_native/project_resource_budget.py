"""Causal, shared project reservations; declared time is never observed usage.

Only trusted services reserve inside the intake's first intent transaction.
Reads validate saved action/event causality and never migrate, refund, resume or
dispatch. An old counter without recoverable intent evidence fails closed.
"""

from copy import deepcopy
import json
import math
import re

from stage1_deliverable.common import canonical, sha
from .session_api import _check

KINDS = {
    "stage1-query-bootstrap": "query",
    "stage1-query-execute": "query",
    "model-operation": "model",
    "stage1-source-execute": "source",
}
STORE = "project_resource_reservations"
EVENT = "project-resource-reservation"
BUDGET_FIELDS = {"seconds", "model_calls", "search_calls", "source_reads", "rounds"}
ROW_FIELDS = {
    "project_ref",
    "project_id",
    "input_version",
    "brief_sha256",
    "budget_sha256",
    "settings_sha256",
    "declared",
    "lane",
    "kind",
    "key",
    "request_sha256",
    "seconds",
    "calls",
}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _binding(intake, state, principal):
    # Authenticate the actual saved project; a supplied state is not an owner.
    intake._load(principal, state["project_ref"])
    binding = intake.brief_binding(state["project_ref"])
    settings = binding.get("settings")
    _check(
        type(settings) is dict
        and settings.get("brief_sha256") == binding["brief_sha256"]
        and state["project_id"] == binding["project_id"]
        and state["input_version"] == binding["input_version"]
        and state.get("settings") == settings
        and intake._brief(state)[0]["sha256"] == binding["brief_sha256"],
        "project-resource-binding-differs",
    )
    budgets = settings.get("budgets")
    _check(
        type(budgets) is dict
        and set(budgets) == BUDGET_FIELDS
        and all(type(v) is int and v >= 0 for v in budgets.values()),
        "project-resource-declaration-invalid",
    )
    return dict(
        project_ref=state["project_ref"],
        project_id=binding["project_id"],
        input_version=binding["input_version"],
        brief_sha256=binding["brief_sha256"],
        budget_sha256=sha(canonical(budgets)),
        settings_sha256=sha(canonical(settings)),
        declared=deepcopy(budgets),
    )


def _reservation_events(intake, state):
    events = {}
    for raw in intake.db.execute(
        "SELECT id,payload FROM intake_events WHERE project=? AND kind=? ORDER BY id",
        (state["project_ref"], EVENT),
    ):
        row = json.loads(raw["payload"])
        digest = row.get("request_sha256") if type(row) is dict else None
        _check(
            type(row) is dict
            and set(row) == ROW_FIELDS
            and type(digest) is str
            and re.fullmatch("[0-9a-f]{64}", digest)
            and digest not in events,
            "project-resource-reservation-event-differs",
        )
        events[digest] = (raw["id"], row)
    return events


def _intents(intake, state, principal, reservation_events):
    intents = {}
    for kind in KINDS:
        events = intake.db.execute(
            "SELECT id,payload FROM intake_events WHERE project=? AND kind=? ORDER BY id",
            (state["project_ref"], kind + "-intent"),
        ).fetchall()
        for raw in events:
            intent = json.loads(raw["payload"])
            digest = intent.get("request_sha256")
            _check(
                digest not in intents
                and intent.get("kind") == kind
                and intent.get("project_ref") == state["project_ref"]
                and intent.get("status") == "intent-recorded"
                and type(intent.get("request")) is dict
                and digest == sha(canonical(dict(kind=kind, body=intent["request"]))),
                "project-resource-intent-differs",
            )
            action = intake.db.execute(
                "SELECT request_hash,receipt FROM intake_actions "
                "WHERE principal=? AND project=? AND key=?",
                (principal, state["project_ref"], intent["key"]),
            ).fetchone()
            _check(
                action is not None and action[0] == digest,
                "project-resource-action-missing",
            )
            saved = json.loads(action[1])
            _check(
                all(
                    saved.get(k) == intent.get(k)
                    for k in ("kind", "project_ref", "key", "request_sha256", "request")
                ),
                "project-resource-action-differs",
            )
            if digest in reservation_events:
                _check(
                    reservation_events[digest][0] + 1 == raw["id"],
                    "project-resource-reservation-transaction-differs",
                )
            intents[digest] = (intent, saved, raw["id"])
    _check(
        set(reservation_events) <= set(intents),
        "project-resource-reservation-intent-missing",
    )
    return intents


def _query_basis(intake, state, principal, permit, authorization_id):
    identity = permit["binding"]
    settings = None
    _check(
        identity["project_id"] == state["project_id"],
        "project-resource-query-binding-differs",
    )
    # A configure preserves input/brief identity. Reconstruct the last saved
    # settings before this exact authorization, never today's mutable settings
    # or a matching configuration published after permission issuance.
    for raw in intake.db.execute(
        "SELECT id,kind,payload FROM intake_events WHERE project=? "
        "AND kind IN ('submit-saved','configure-saved') AND id<? ORDER BY id DESC",
        (state["project_ref"], authorization_id),
    ):
        submitted = json.loads(raw["payload"])
        request = submitted.get("request")
        _check(type(request) is dict, "project-resource-legacy-binding-unavailable")
        kind = raw["kind"].removesuffix("-saved")
        input_version = (
            submitted.get("input_version")
            if kind == "submit"
            else request.get("input_version")
        )
        brief_sha256 = submitted.get("brief_sha256")
        if (
            input_version != identity["project_input_version"]
            or brief_sha256 != identity["input_bytes_sha256"]
        ):
            continue
        digest = sha(canonical(dict(kind=kind, body=request)))
        action = intake.db.execute(
            "SELECT request_hash,receipt FROM intake_actions "
            "WHERE principal=? AND project=? AND key=?",
            (principal, state["project_ref"], submitted.get("key")),
        ).fetchone()
        _check(
            submitted.get("kind") == kind
            and submitted.get("status") == "saved"
            and submitted.get("project_ref") == state["project_ref"]
            and submitted.get("key") == request.get("key")
            and submitted.get("request_sha256") == digest
            and type(input_version) is int
            and request.get("input_version") == input_version
            and request.get("confirmed") is True
            and (kind != "configure" or request.get("brief_sha256") == brief_sha256)
            and action is not None
            and action["request_hash"] == digest
            and json.loads(action["receipt"]) == submitted,
            "project-resource-legacy-binding-unavailable",
        )
        settings = {
            key: deepcopy(request[key])
            for key in ("resource_envelope", "budgets", "consent", "user_input")
        }
        settings.update(
            brief_sha256=brief_sha256,
            provenance="user-attested",
            execution_authorized=False,
        )
        _check(
            sha(canonical(settings)) == identity["settings_sha256"],
            "project-resource-legacy-binding-unavailable",
        )
        break
    _check(settings is not None, "project-resource-legacy-binding-unavailable")
    return dict(
        project_ref=state["project_ref"],
        project_id=identity["project_id"],
        input_version=identity["project_input_version"],
        brief_sha256=identity["input_bytes_sha256"],
        budget_sha256=sha(canonical(settings["budgets"])),
        settings_sha256=identity["settings_sha256"],
        declared=deepcopy(settings["budgets"]),
    )


def _query(intake, state, principal, intents):
    expected = dict(probes=0, attempts=0, seconds=0)
    rows = {}
    authorizations = intake.db.execute(
        "SELECT id,payload FROM intake_events WHERE project=? AND kind=? ORDER BY id",
        (state["project_ref"], "stage1-query-authorize-saved"),
    ).fetchall()
    for digest, (intent, _, intent_id) in intents.items():
        if KINDS[intent["kind"]] != "query":
            continue
        preceding = [
            (event["id"], json.loads(event["payload"]))
            for event in authorizations
            if event["id"] < intent_id
            and json.loads(event["payload"])["request"]["input_version"]
            == intent["request"]["input_version"]
            and json.loads(event["payload"])["request"]["brief_sha256"]
            == intent["request"]["brief_sha256"]
        ]
        _check(preceding, "project-resource-query-permit-missing")
        authorization_id, saved = preceding[-1]
        path = "q1-" + saved["request_sha256"][:20] + "-permit.json"
        raw = intake._path(state["project_ref"], path).read_bytes()
        permit = json.loads(raw)
        _check(
            sha(raw) == saved["permit_sha256"],
            "project-resource-query-permit-differs",
        )
        actions = intake.db.execute(
            "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND request_hash=?",
            (principal, state["project_ref"], permit["authorization_request_sha256"]),
        ).fetchall()
        action = json.loads(actions[0][0]) if len(actions) == 1 else {}
        _check(
            saved.get("kind") == "stage1-query-authorize"
            and saved.get("status") == "saved"
            and saved.get("project_ref") == state["project_ref"]
            and saved.get("key") == saved["request"].get("key")
            and saved.get("request_sha256")
            == sha(canonical(dict(kind=saved["kind"], body=saved["request"])))
            and saved.get("request_sha256") == permit["authorization_request_sha256"]
            and saved.get("permit_sha256") == sha(raw)
            and action == saved,
            "project-resource-query-authorization-differs",
        )
        identity = permit["binding"]
        _check(
            permit.get("project_ref") == state["project_ref"]
            and permit.get("principals") == [principal]
            and intent["request"]["input_version"] == identity["project_input_version"]
            and intent["request"]["brief_sha256"] == identity["input_bytes_sha256"],
            "project-resource-query-binding-differs",
        )
        probe = intent["kind"] == "stage1-query-bootstrap"
        seconds = 30 if probe else permit["limits"]["timeout_seconds"] + 30
        _check(_number(seconds), "project-resource-query-time-invalid")
        expected["probes" if probe else "attempts"] += 1
        expected["seconds"] += seconds
        rows[digest] = (
            seconds,
            0 if probe else 1,
            _query_basis(intake, state, principal, permit, authorization_id),
        )
    actual = state.get("stage1_query_budget", dict(probes=0, attempts=0, seconds=0))
    _check(
        type(actual) is dict
        and set(actual) == set(expected)
        and type(actual["probes"]) is int
        and type(actual["attempts"]) is int
        and _number(actual["seconds"])
        and actual == expected,
        "project-resource-query-history-differs",
    )
    return rows


def _models(state, intents, reservation_events):
    row = state.get("model_operations", {})
    jobs, offers = row.get("jobs", {}), row.get("offers", {})
    _check(
        type(jobs) is dict and type(offers) is dict,
        "project-resource-model-state-invalid",
    )
    models = {
        d: i for d, (i, _, _) in intents.items() if i["kind"] == "model-operation"
    }
    _check(
        set(jobs) == {i["key"] for i in models.values()}
        and type(row.get("calls_reserved", 0)) is int
        and row.get("calls_reserved", 0) == len(models),
        "project-resource-model-history-differs",
    )
    derived, counts, permit_counts = {}, {}, {}
    for digest, intent in models.items():
        job = jobs[intent["key"]]
        offer = offers.get(job.get("offer_ref"))
        _check(
            type(offer) is dict and type(offer.get("context")) is dict,
            "project-resource-model-offer-missing",
        )
        context = offer["context"]
        settings = context["settings"]
        _check(
            job.get("key") == intent["key"]
            and job.get("request_sha256") == digest
            and job.get("project_ref") == state["project_ref"]
            and job.get("project_id") == state["project_id"]
            and type(job.get("calls_reserved")) is int
            and job["calls_reserved"] == 1
            and job.get("offer_sha256") == offer["offer_sha256"]
            and job.get("offer_ref") == intent["request"]["offer_ref"]
            and job.get("offer_sha256") == intent["request"]["offer_sha256"]
            and job.get("permit_sha256")
            == offer.get("permit_sha256")
            == context.get("permit_sha256")
            and offer["offer_sha256"] == sha(canonical(context))
            and all(
                job.get(k) == context.get(k)
                for k in ("input_version", "brief_sha256", "budget_sha256")
            )
            and intent["request"]["input_version"] == job["input_version"]
            and intent["request"]["brief_sha256"] == job["brief_sha256"]
            and settings["brief_sha256"] == job["brief_sha256"]
            and job["budget_sha256"] == sha(canonical(settings["budgets"]))
            and _number(job.get("started_at"))
            and _number(job.get("deadline_at"))
            and job["deadline_at"] > job["started_at"],
            "project-resource-model-job-differs",
        )
        window = job["deadline_at"] - job["started_at"]
        _check(
            type(context.get("max_seconds")) is int
            and 0 < window <= context["max_seconds"],
            "project-resource-model-deadline-differs",
        )
        _check(
            "reservation_seconds" not in job or job["reservation_seconds"] == window,
            "project-resource-model-reservation-differs",
        )
        # Legacy timestamps were mutable: charge the original request-bound
        # offer's full allowance. New exact windows have an immutable event.
        seconds = window if digest in reservation_events else context["max_seconds"]
        basis = dict(
            project_ref=state["project_ref"],
            project_id=state["project_id"],
            input_version=job["input_version"],
            brief_sha256=job["brief_sha256"],
            budget_sha256=job["budget_sha256"],
            settings_sha256=sha(canonical(settings)),
            declared=deepcopy(settings["budgets"]),
        )
        _check(
            set(basis["declared"]) == BUDGET_FIELDS
            and all(type(v) is int and v >= 0 for v in basis["declared"].values()),
            "project-resource-declaration-invalid",
        )
        derived[digest] = (seconds, 1, basis)
        version = str(job["input_version"])
        counts[version] = counts.get(version, 0) + 1
        pin = job["permit_sha256"]
        permit_counts.setdefault(version, {})
        permit_counts[version][pin] = permit_counts[version].get(pin, 0) + 1
        _check(
            type(context.get("max_calls")) is int
            and permit_counts[version][pin] <= context["max_calls"],
            "project-resource-model-permit-count-differs",
        )
    scopes = row.get("scopes", {})
    _check(
        type(scopes) is dict
        and set(counts) == set(scopes)
        and all(
            type(scopes[v].get("calls")) is int
            and scopes[v]["calls"] == counts.get(v, 0)
            for v in scopes
        ),
        "project-resource-model-scope-differs",
    )
    for version, scope in scopes.items():
        permits = scope.get("permits")
        _check(
            type(permits) is dict
            and set(permits) == set(permit_counts[version])
            and all(
                type(permits[pin].get("calls")) is int
                and permits[pin]["calls"] == count
                for pin, count in permit_counts[version].items()
            ),
            "project-resource-model-permit-history-differs",
        )
    return derived


def resource_view(intake, state, principal):
    """Validate causal history and return current resource-version reservations."""
    with intake._lock:
        basis = _binding(intake, state, principal)
        events = _reservation_events(intake, state)
        intents = _intents(intake, state, principal, events)
        query = _query(intake, state, principal, intents)
        models = _models(state, intents, events)
        store = state.get(STORE, dict(schema_version="1.0.0", reservations={}))
        _check(
            type(store) is dict
            and set(store) == {"schema_version", "reservations"}
            and store["schema_version"] == "1.0.0"
            and type(store["reservations"]) is dict,
            "project-resource-reservation-state-invalid",
        )
        reservations = store["reservations"]
        _check(set(reservations) <= set(intents), "project-resource-intent-missing")
        _check(
            set(reservations) == set(events)
            and all(reservations[d] == events[d][1] for d in reservations),
            "project-resource-reservation-event-differs",
        )
        source_total = dict(fetches=0, seconds=0)
        reserved = dict(seconds=0, model_calls=0, search_calls=0, source_reads=0)
        history = {}
        for digest, (intent, _, _) in intents.items():
            lane = KINDS[intent["kind"]]
            saved = events[digest][1] if digest in events else None
            if lane == "query":
                seconds, calls, old_basis = query[digest]
                if saved is None:
                    saved = {**old_basis, "seconds": seconds, "calls": calls}
            elif lane == "model":
                seconds, calls, old_basis = models[digest]
                if saved is None:
                    saved = {**old_basis, "seconds": seconds, "calls": calls}
            else:
                _check(saved is not None, "project-resource-source-intent-unbound")
                seconds, calls = saved["seconds"], saved["calls"]
                source_total["fetches"] += calls
                source_total["seconds"] += seconds
            if digest in reservations:
                _check(
                    set(saved) == ROW_FIELDS
                    and saved["lane"] == lane
                    and saved["kind"] == intent["kind"]
                    and saved["key"] == intent["key"]
                    and saved["request_sha256"] == digest
                    and saved["project_ref"] == state["project_ref"]
                    and saved["project_id"] == state["project_id"]
                    and saved["input_version"] == intent["request"]["input_version"]
                    and saved["brief_sha256"] == intent["request"]["brief_sha256"]
                    and saved["seconds"] == seconds
                    and saved["calls"] == calls
                    and type(saved["calls"]) is int
                    and _number(saved["seconds"])
                    and saved["seconds"] > 0
                    and saved["calls"]
                    == (0 if intent["kind"] == "stage1-query-bootstrap" else 1)
                    and type(saved["declared"]) is dict
                    and set(saved["declared"]) == BUDGET_FIELDS
                    and all(
                        type(v) is int and v >= 0 for v in saved["declared"].values()
                    )
                    and saved["budget_sha256"] == sha(canonical(saved["declared"])),
                    "project-resource-reservation-binding-differs",
                )
                if lane in {"model", "query"}:
                    _check(
                        all(saved[k] == old_basis[k] for k in old_basis),
                        "project-resource-" + lane + "-binding-differs",
                    )
            version = tuple(
                saved[k]
                for k in (
                    "input_version",
                    "brief_sha256",
                    "budget_sha256",
                    "settings_sha256",
                )
            )
            total, declaration = history.setdefault(
                version,
                (
                    dict(seconds=0, model_calls=0, search_calls=0, source_reads=0),
                    saved["declared"],
                ),
            )
            _check(
                declaration == saved["declared"], "project-resource-declaration-invalid"
            )
            total["seconds"] += seconds
            total[
                {
                    "query": "search_calls",
                    "model": "model_calls",
                    "source": "source_reads",
                }[lane]
            ] += calls
            if saved["input_version"] == basis["input_version"]:
                _check(
                    all(saved[k] == basis[k] for k in basis),
                    "project-resource-version-differs",
                )
                reserved["seconds"] += seconds
                if lane == "query":
                    reserved["search_calls"] += calls
                else:
                    reserved["model_calls" if lane == "model" else "source_reads"] += (
                        calls
                    )
        actual_source = state.get("stage1_source_budget", dict(fetches=0, seconds=0))
        _check(
            type(actual_source) is dict
            and set(actual_source) == set(source_total)
            and type(actual_source["fetches"]) is int
            and _number(actual_source["seconds"])
            and actual_source == source_total,
            "project-resource-source-history-differs",
        )
        remaining = {k: basis["declared"][k] - v for k, v in reserved.items()}
        _check(
            all(value >= 0 for value in remaining.values())
            and all(
                all(total[k] <= declaration[k] for k in total)
                for total, declaration in history.values()
            ),
            "project-resource-declared-budget-exceeded",
            429,
        )
        digest = sha(
            canonical(
                dict(
                    binding=basis,
                    reservations=store,
                    intents=intents,
                    query_budget=state.get("stage1_query_budget"),
                    source_budget=actual_source,
                    model_operations=state.get("model_operations"),
                )
            )
        )
        return dict(
            binding=basis,
            declared=deepcopy(basis["declared"]),
            reserved=reserved,
            remaining=remaining,
            reservation_state_sha256=digest,
            actual_seconds=None,
            usage_status="separate-platform-receipts",
            automatic_refund=False,
        )


def reserve_resource(
    intake, state, principal, *, lane, kind, key, request_sha256, seconds, calls=1
):
    """Reserve with the action's first transaction, before its intent publication.

    Source counters are updated here; query/model services retain their existing
    local counters. No expiry, failure, completion or reopen refunds a charge.
    """
    _check(
        intake.db.in_transaction
        and KINDS.get(kind) == lane
        and type(key) is str
        and type(request_sha256) is str
        and re.fullmatch("[0-9a-f]{64}", request_sha256)
        and _number(seconds)
        and seconds > 0
        and type(calls) is int
        and (calls == 0 if kind == "stage1-query-bootstrap" else calls == 1),
        "project-resource-reservation-invalid",
    )
    view = resource_view(intake, state, principal)
    count = {"query": "search_calls", "model": "model_calls", "source": "source_reads"}[
        lane
    ]
    _check(
        seconds <= view["remaining"]["seconds"] and calls <= view["remaining"][count],
        "project-resource-budget-exhausted",
        429,
    )
    store = state.setdefault(STORE, dict(schema_version="1.0.0", reservations={}))
    _check(
        request_sha256 not in store["reservations"],
        "project-resource-reservation-repeated",
    )
    record = dict(
        view["binding"],
        lane=lane,
        kind=kind,
        key=key,
        request_sha256=request_sha256,
        seconds=seconds,
        calls=calls,
    )
    store["reservations"][request_sha256] = record
    intake.db.execute(
        "INSERT INTO intake_events(project,kind,payload) VALUES(?,?,?)",
        (state["project_ref"], EVENT, canonical(record).decode()),
    )
    if lane == "source":
        budget = state.setdefault("stage1_source_budget", dict(fetches=0, seconds=0))
        budget["fetches"] += calls
        budget["seconds"] += seconds
    return deepcopy(record)
