"""Run-derived model authority over original saved permits and native admission."""

from copy import deepcopy

from stage1_deliverable.common import canonical, sha
from stage1_ledger.journal import decode

from .project_run_authority import RunActionGuard, action_identity, saved_run_check
from .project_stage1_run_grant import ProjectStage1RunGrantService
from .session_api import _check


def configured(intake, issuer):
    _check(
        issuer is None
        or type(issuer) is ProjectStage1RunGrantService
        and issuer.intake is intake,
        "model-run-issuer-invalid",
    )
    return issuer


def request(service, credential, ref, body, token, *, action, operation):
    if token is None:
        return None
    actor = service.intake._principal(credential)
    _check(
        getattr(token, "service", None) is service.run_grants
        and service.run_grants is not None,
        "model-run-issuer-unconnected",
    )
    return RunActionGuard(
        service.intake, actor, ref, body, token, operation=operation, action=action
    )


def saved(service, actor, ref, body, *, action, operation):
    _check(
        type(body) is dict
        and body.get("confirmed") is False
        and type(body.get("run_authority")) is dict
        and type(body["run_authority"].get("action_key")) is str
        and body.get("key") == body["run_authority"].get("action_key", "") + "-work",
        "model-run-request-invalid",
    )
    proof = body["run_authority"]
    token = saved_run_check(
        service.run_grants,
        service.intake,
        actor,
        ref,
        proof=proof,
        operation=operation,
        identity=action_identity(action, body),
    )
    _, document = service.run_grants._grant(
        actor, ref, token.grant_ref, token.grant_sha256
    )
    _check(
        body.get("run_user_input") == document["user_input"]
        and ("user_input" not in body or body["user_input"] == document["user_input"])
        and type(body.get("input_version")) is int
        and body["input_version"] == document["binding"]["input_version"]
        and body.get("brief_sha256") == document["binding"]["brief_sha256"],
        "model-run-source-consent-differs",
    )
    return token, document


def compact_request(body):
    return deepcopy(
        {
            key: value
            for key, value in body.items()
            if key not in {"revision", "user_input", "run_user_input"}
        }
    )


def check_permit(service, ref, permit, pin):
    if permit.get("schema_version") == "1.0.0":
        return
    compact = permit["run_request"]
    _check(
        type(compact) is dict and type(compact.get("key")) is str,
        "model-run-request-invalid",
    )
    with service.intake._lock:
        row = service.intake.db.execute(
            "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
            (permit["principal"], ref, compact["key"]),
        ).fetchone()
    _check(row is not None, "model-run-authorization-missing")
    receipt = decode(row[1].encode(), "saved model run authorization")
    _check(
        type(receipt) is dict and type(receipt.get("request")) is dict,
        "model-run-authorization-invalid",
    )
    body = receipt["request"]
    digest = sha(canonical({"kind": "model-authorization", "body": body}))
    _check(
        row[0] == digest
        and receipt.get("status") == "saved"
        and receipt.get("kind") == "model-authorization"
        and receipt.get("request_sha256") == digest
        and receipt.get("permit_sha256") == pin
        and compact_request(body) == compact,
        "model-run-permit-authorization-differs",
    )
    token, document = saved(
        service,
        permit["principal"],
        ref,
        body,
        action="model-authorize",
        operation=permit["operation"],
    )
    _check(
        permit["permission_id"] == "ui-content-" + digest[:40]
        and permit["operation"] == body["operation"]
        and permit["input_version"] == body["input_version"]
        and permit["brief_sha256"] == body["brief_sha256"]
        and permit["work_ref"] == body["work_ref"]
        and permit["snapshot_sha256"] == body["snapshot_sha256"]
        and permit["max_calls"] == 1
        and permit["max_seconds"] <= (document["expires_at"] - document["issued_at"]),
        "model-run-permit-authorization-differs",
    )
    from .project_model import _expiry

    _check(
        _expiry(permit["expires_at"]) <= document["expires_at"],
        "model-run-permit-deadline-differs",
    )
    return token


def check_job(service, actor, ref, key):
    job = service._job(actor, ref, key)
    body = job.get("run_request")
    if body is None:
        return
    token, _ = saved(
        service, actor, ref, body, action="model-execute", operation=job["operation"]
    )
    state = service.intake._load(actor, ref)
    offer = state["model_operations"]["offers"][job["offer_ref"]]
    _check(
        offer["context"]
        .get("run_request", {})
        .get("run_authority", {})
        .get("grant_sha256")
        == token.grant_sha256
        and body["offer_ref"] == job["offer_ref"]
        and body["offer_sha256"] == job["offer_sha256"]
        and job["request_sha256"]
        == sha(
            canonical(
                {
                    "kind": "model-operation",
                    "body": {k: v for k, v in body.items() if k != "revision"},
                }
            )
        ),
        "model-run-job-authorization-differs",
    )


def permit_fields(guard):
    return (
        {}
        if guard is None
        else dict(schema_version="1.1.0", run_request=compact_request(guard.request))
    )
