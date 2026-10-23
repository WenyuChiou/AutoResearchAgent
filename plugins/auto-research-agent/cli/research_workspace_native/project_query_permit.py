"""Versioned project query seals; inspecting a seal never probes its runtime."""

from copy import deepcopy
import json
import math
import time

from stage1_brief.brief import validate_bound_plan
from stage1_deliverable.common import canonical, sha
from stage1_ledger.journal import decode, write_new
from stage1_retrieval.receipt import check_pin
from stage1_retrieval.runtime_identity import verify_identity
from .planned_query_contract import (
    BACKENDS,
    PROBE_TIMEOUT_SECONDS,
    raw_file,
    require,
    tree_sha,
)
from .project_stage1 import _basis
from . import project_query_run as run_adapter


def configured_pin(pin):
    check_pin(pin)
    require(pin["status"] == "merged", "project-query-merged-runtime-required")
    verify_identity(pin)  # Byte checks only: probe belongs to an admitted job.
    raw_file(pin["config"]["path"], pin["config"]["sha256"], maximum=1024 * 1024)
    return sha(canonical(pin))


def configuration_sha(config):
    return sha(canonical({k: config[k] for k in ("caps", "backends")}))


def project_basis(intake, ref):
    binding = intake.binding(ref)
    validate_bound_plan(binding["plan_root"], binding["brief_path"])
    return binding, dict(_basis(binding), plan_sha256=tree_sha(binding["plan_root"]))


def proposal(intake, ref, principal, config):
    binding, basis = project_basis(intake, ref)
    settings = binding["settings"]
    require(
        settings["consent"]["external_search"] is True,
        "project-query-search-consent-required",
    )
    caps = config["caps"]
    attempts = min(settings["budgets"]["search_calls"], caps["max_attempts"])
    seconds = min(settings["budgets"]["seconds"], caps["max_reserved_seconds"])
    reserve = config["pin"]["timeout_seconds"] + PROBE_TIMEOUT_SECONDS
    require(
        type(attempts) is int
        and attempts > 0
        and seconds >= PROBE_TIMEOUT_SECONDS + reserve,
        "project-query-requested-budget-insufficient",
        429,
    )
    queries = [
        decode(line, "planned query")["query_id"]
        for line in (binding["plan_root"] / "query_plan.jsonl")
        .read_bytes()
        .splitlines()
    ]
    require(0 < len(queries) <= 256, "project-query-plan-bound")
    # The offer authorizes this explicit bounded prefix, never arbitrary text.
    planned = queries[: min(attempts, 128)]
    document = dict(
        kind="Stage1ProjectQueryAuthorizationOffer",
        schema_version="1.0.0",
        project_ref=ref,
        principal=principal,
        binding=basis,
        runtime_sha256=configured_pin(config["pin"]),
        execution_source_sha256=config["execution_source_sha256"],
        server_configuration_sha256=configuration_sha(config),
        limits=dict(
            bootstrap_probe_attempts=1,
            bootstrap_probe_seconds=PROBE_TIMEOUT_SECONDS,
            max_attempts=attempts,
            max_reserved_seconds=seconds,
            max_results=caps["max_results"],
            planned_ids=planned,
            backends=config["backends"],
            timeout_seconds=config["pin"]["timeout_seconds"],
            validity_seconds=caps["validity_seconds"],
        ),
        allow_search=True,
        allow_source_acquisition=False,
        model_execution=False,
        automatic_retry=False,
        canonical_workspace_index=False,
    )
    digest = sha(canonical(document))
    return (
        binding,
        document,
        dict(
            offer_ref="project-query-" + digest[:32],
            offer_sha256=digest,
            document=document,
        ),
    )


def save_seal(
    intake,
    ref,
    principal,
    config,
    request_hash,
    document,
    user_input,
    *,
    run_guard=None,
):
    paths = {
        name: intake._path(ref, "q1-" + request_hash[:20] + suffix).as_posix()
        for name, suffix in (
            ("parent_ledger_root", "-parent"),
            ("ledger_root", "-work"),
            ("control_store_path", ".sqlite"),
        )
    }
    snapshot = {**document, "kind": "ProjectQueryInputSnapshot"}
    snapshot_raw = canonical(snapshot) + b"\n"
    snapshot_path = intake._path(ref, "q1-" + request_hash[:20] + "-input.json")
    write_new(snapshot_path, snapshot_raw)
    permit = dict(
        kind="Stage1ProjectQueryBootstrapPermit",
        schema_version="1.0.0",
        project_ref=ref,
        principals=[principal],
        binding=dict(
            document["binding"],
            project_input_version=document["binding"]["input_version"],
            input_bytes_sha256=document["binding"]["brief_sha256"],
            index_sha256=sha(snapshot_raw),
            runtime_sha256=document["runtime_sha256"],
            execution_source_sha256=document["execution_source_sha256"],
            execution_source_root=config["execution_source_root"],
            server_configuration_sha256=document["server_configuration_sha256"],
            **paths,
        ),
        limits=deepcopy(document["limits"]),
        expires_at_unix=int(time.time()) + document["limits"]["validity_seconds"],
        scope=["initialize-query-runtime", "execute-planned-query"],
        allow_search=True,
        allow_source_acquisition=False,
        model_execution=False,
        user_input=user_input,
        authorization_request_sha256=request_hash,
    )
    if run_guard is not None:
        _, grant = run_guard.check()
        permit.update(run_adapter.seal_fields(run_guard))
        permit["expires_at_unix"] = min(
            permit["expires_at_unix"], math.floor(grant["expires_at"])
        )
    raw = canonical(permit) + b"\n"
    path = intake._path(ref, "q1-" + request_hash[:20] + "-permit.json")
    write_new(path, raw)
    return dict(
        path=path.name,
        sha256=sha(raw),
        permit=permit,
        snapshot_path=snapshot_path.name,
    )


def inspect_seal(intake, ref, authorization, config, *, ready=True, run_grants=None):
    permit = authorization["permit"]
    path = intake._path(ref, authorization["path"])
    raw = path.read_bytes()
    require(
        sha(raw) == authorization["sha256"] and decode(raw, "query seal") == permit,
        "project-query-seal-bytes-differ",
    )
    snapshot_raw = intake._path(ref, authorization["snapshot_path"]).read_bytes()
    require(
        sha(snapshot_raw) == permit["binding"]["index_sha256"],
        "project-query-snapshot-differs",
    )
    binding, basis = project_basis(intake, ref)
    principal = permit["principals"][0]
    _, offered, _ = proposal(intake, ref, principal, config)
    require(
        decode(snapshot_raw, "query input snapshot")
        == {**offered, "kind": "ProjectQueryInputSnapshot"},
        "project-query-snapshot-semantics-differ",
    )
    rows = intake.db.execute(
        "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND request_hash=?",
        (principal, ref, permit["authorization_request_sha256"]),
    ).fetchall()
    require(len(rows) == 1, "project-query-authorization-history-missing")
    saved = json.loads(rows[0][0])
    events = intake.db.execute(
        "SELECT payload FROM intake_events WHERE project=? AND kind=?",
        (ref, "stage1-query-authorize-saved"),
    ).fetchall()
    require(
        saved["kind"] == "stage1-query-authorize"
        and saved["status"] == "saved"
        and saved["permit_sha256"] == authorization["sha256"]
        and any(json.loads(row[0]) == saved for row in events),
        "project-query-authorization-history-differs",
    )
    run_adapter.check_seal(intake, ref, permit, saved, run_grants)
    prefix = "q1-" + permit["authorization_request_sha256"][:20]
    require(
        authorization["path"] == prefix + "-permit.json"
        and authorization["snapshot_path"] == prefix + "-input.json"
        and permit["kind"] == "Stage1ProjectQueryBootstrapPermit"
        and permit["schema_version"] in {"1.0.0", "1.1.0"}
        and permit["project_ref"] == ref
        and permit["principals"] == [principal]
        and permit["scope"] == ["initialize-query-runtime", "execute-planned-query"]
        and permit["allow_search"] is True
        and permit["allow_source_acquisition"] is False
        and permit["model_execution"] is False
        and permit["limits"] == offered["limits"]
        and permit["user_input"] == saved["request"]["user_input"]
        and all(
            permit["binding"][name] == intake._path(ref, prefix + suffix).as_posix()
            for name, suffix in (
                ("parent_ledger_root", "-parent"),
                ("ledger_root", "-work"),
                ("control_store_path", ".sqlite"),
            )
        ),
        "project-query-seal-scope-or-path-differs",
    )
    require(
        all(permit["binding"][k] == v for k, v in basis.items()),
        "project-query-current-input-differs",
    )
    require(
        type(binding["input_version"]) is int
        and permit["binding"]["project_input_version"] == binding["input_version"]
        and permit["binding"]["input_bytes_sha256"] == binding["brief_sha256"]
        and configured_pin(config["pin"]) == permit["binding"]["runtime_sha256"]
        and config["execution_source_root"]
        == permit["binding"]["execution_source_root"]
        and config["execution_source_sha256"]
        == permit["binding"]["execution_source_sha256"],
        "project-query-bootstrap-binding-differs",
    )
    require(
        configuration_sha(config) == permit["binding"]["server_configuration_sha256"],
        "project-query-server-caps-changed",
    )
    require(
        not ready
        or time.time() + PROBE_TIMEOUT_SECONDS + config["pin"]["timeout_seconds"]
        < permit["expires_at_unix"],
        "project-query-seal-expired",
    )
    return binding, permit


def derived_registration(
    intake, ref, authorization, receipt, config, *, write=True, run_grants=None
):
    binding, permit = inspect_seal(
        intake, ref, authorization, config, ready=write, run_grants=run_grants
    )
    identity = permit["binding"]
    basis = {k: identity[k] for k in (*_basis(binding), "plan_sha256")}
    item = dict(
        project_id=binding["project_id"],
        index_sha256=identity["index_sha256"],
        input_version=binding["brief_sha256"],
        brief_path=binding["brief_path"].as_posix(),
        brief_sha256=binding["brief_sha256"],
        plan_root=binding["plan_root"].as_posix(),
        plan_sha256=identity["plan_sha256"],
        ledger_root=identity["ledger_root"],
        ledger_manifest_sha256=receipt["ledger_manifest_sha256"],
        runtime_sha256=identity["runtime_sha256"],
        execution_source_sha256=identity["execution_source_sha256"],
        execution_source_root=identity["execution_source_root"],
        control_store_path=identity["control_store_path"],
        parent_ledger_root=identity["parent_ledger_root"],
        parent_ledger_sha256=receipt["parent_ledger_sha256"],
        principals=permit["principals"],
        registration_kind="project-intake",
        schema_version="1.1.0",
        project_input_version=binding["input_version"],
        project_binding_sha256=sha(canonical(basis)),
        bootstrap_permit_sha256=authorization["sha256"],
        bootstrap_receipt_sha256=sha(canonical(receipt)),
    )
    keys = (
        "project_id",
        "index_sha256",
        "input_version",
        "brief_sha256",
        "plan_sha256",
        "ledger_manifest_sha256",
        "runtime_sha256",
        "execution_source_sha256",
        "execution_source_root",
        "control_store_path",
        "parent_ledger_sha256",
        "registration_kind",
        "project_input_version",
        "project_binding_sha256",
        "bootstrap_permit_sha256",
        "bootstrap_receipt_sha256",
    )
    limits = permit["limits"]
    query_permit = dict(
        kind="Stage1PlannedQueryPermit",
        schema_version="1.1.0",
        project_ref=ref,
        binding={k: item[k] for k in keys},
        principals=permit["principals"],
        allow_search=True,
        expires_at_unix=permit["expires_at_unix"],
        **{
            k: limits[k]
            for k in (
                "planned_ids",
                "backends",
                "max_attempts",
                "max_results",
            )
        },
        # Legacy permit uses an integer upper bound; actual timeout and all
        # reservations retain the unchanged runtime pin's precise value.
        timeout_seconds=math.ceil(limits["timeout_seconds"]),
        max_reserved_seconds=limits["max_reserved_seconds"] - PROBE_TIMEOUT_SECONDS,
    )
    path = intake._path(
        ref, "q1-" + permit["authorization_request_sha256"][:20] + "-query.json"
    )
    raw = canonical(query_permit) + b"\n"
    if write:
        write_new(path, raw)
    else:
        require(path.read_bytes() == raw, "project-query-derived-permit-bytes-differ")
    item.update(permit_path=path.as_posix(), permit_sha256=sha(raw))
    return item


def check_configuration(pin, source_root, source_sha256, caps, backends):
    require(
        isinstance(caps, dict)
        and set(caps)
        == {"max_attempts", "max_reserved_seconds", "max_results", "validity_seconds"},
        "project-query-server-caps-required",
        400,
    )
    require(
        all(
            type(caps[k]) is int and 1 <= caps[k] <= maximum
            for k, maximum in (
                ("max_attempts", 128),
                ("max_reserved_seconds", 86400),
                ("max_results", 100),
                ("validity_seconds", 86400),
            )
        ),
        "project-query-server-caps-invalid",
        400,
    )
    require(
        isinstance(backends, list)
        and 0 < len(backends) <= 5
        and len(set(backends)) == len(backends)
        and set(backends) <= BACKENDS,
        "project-query-server-backends-invalid",
        400,
    )
    require(
        configured_pin(pin) and pin["timeout_seconds"] <= 600,
        "project-query-server-timeout-invalid",
        400,
    )
    return dict(
        pin=deepcopy(pin),
        execution_source_root=source_root,
        execution_source_sha256=source_sha256,
        caps=deepcopy(caps),
        backends=list(backends),
    )
