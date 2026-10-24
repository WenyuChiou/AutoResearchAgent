"""Run-derived search checks over the original sealed query lane."""

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
        "query-run-issuer-invalid",
    )
    return issuer


def request(service, credential, ref, body, token, action):
    if token is None:
        return None
    _check(
        service.run_grants is not None
        and getattr(token, "service", None) is service.run_grants,
        "query-run-issuer-unconnected",
    )
    return RunActionGuard(
        service.intake,
        service.intake._principal(credential),
        ref,
        body,
        token,
        action=action,
        operation="query",
    )


def saved(intake, issuer, principal, ref, body, action):
    _check(
        type(body) is dict
        and body.get("confirmed") is False
        and type(body.get("run_authority")) is dict
        and type(body["run_authority"].get("action_key")) is str
        and body.get("key") == body["run_authority"].get("action_key", "") + "-work",
        "query-run-request-invalid",
    )
    proof = body["run_authority"]
    token = saved_run_check(
        issuer,
        intake,
        principal,
        ref,
        proof=proof,
        operation="query",
        identity=action_identity(action, body),
    )
    _, grant = issuer._grant(principal, ref, token.grant_ref, token.grant_sha256)
    _check(
        body.get("run_user_input") == grant["user_input"]
        and ("user_input" not in body or body["user_input"] == grant["user_input"])
        and type(body.get("input_version")) is int
        and body["input_version"] == grant["binding"]["input_version"]
        and body.get("brief_sha256") == grant["binding"]["brief_sha256"],
        "query-run-source-consent-differs",
    )
    return token, grant


def check_seal(intake, ref, permit, saved_receipt, issuer):
    if permit["schema_version"] == "1.0.0":
        return
    fields = {
        "kind",
        "schema_version",
        "project_ref",
        "principals",
        "binding",
        "limits",
        "expires_at_unix",
        "scope",
        "allow_search",
        "allow_source_acquisition",
        "model_execution",
        "user_input",
        "authorization_request_sha256",
        "run_request",
    }
    _check(
        permit["schema_version"] == "1.1.0" and set(permit) == fields,
        "query-run-seal-fields-invalid",
    )
    body = permit["run_request"]
    token, grant = saved(
        intake, issuer, permit["principals"][0], ref, body, "query-authorize"
    )
    semantic = {k: v for k, v in body.items() if k != "revision"}
    digest = sha(canonical({"kind": "stage1-query-authorize", "body": semantic}))
    _check(
        saved_receipt["request"] == semantic
        and permit["authorization_request_sha256"]
        == saved_receipt["request_sha256"]
        == digest
        and permit["expires_at_unix"] <= grant["expires_at"],
        "query-run-seal-authority-differs",
    )
    return token


def check_action(service, principal, ref, body, action, permit):
    token, _ = saved(service.intake, service.run_grants, principal, ref, body, action)
    _check(
        permit.get("run_request", {}).get("run_authority", {}).get("grant_sha256")
        == token.grant_sha256,
        "query-run-action-grant-differs",
    )
    return token


def check_job(service, principal, ref, job, permit):
    body = job.get("run_request")
    if body is None:
        _check(permit["schema_version"] == "1.0.0", "query-run-bootstrap-proof-missing")
        return
    check_action(service, principal, ref, body, "query-bootstrap", permit)
    semantic = {k: v for k, v in body.items() if k != "revision"}
    _check(
        job["request_sha256"]
        == sha(canonical({"kind": "stage1-query-bootstrap", "body": semantic})),
        "query-run-bootstrap-request-differs",
    )


def check_execution(service, credential, ref, authorization, event):
    permit = authorization["permit"]
    if permit["schema_version"] == "1.0.0":
        return True
    principal = service.intake._principal(credential)
    key = event["client_key"]
    _check(
        type(key) is str
        and key.startswith("project-")
        and event["principal"] == principal
        and event["project_ref"] == ref,
        "query-run-dispatch-binding-differs",
    )
    digest = key[len("project-") :]
    with service.intake._lock:
        row = service.intake.db.execute(
            "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND request_hash=?",
            (principal, ref, digest),
        ).fetchone()
        _check(row is not None, "query-run-execution-intent-missing")
        receipt = decode(row[0].encode(), "saved run query execution")
        body = receipt["request"]
        _check(
            receipt["kind"] == "stage1-query-execute"
            and receipt["status"] == "saved"
            and receipt["request_sha256"] == digest
            and sha(canonical({"kind": receipt["kind"], "body": body})) == digest
            and receipt["query_action_key"] == key
            and body["offer_ref"]
            == body["offer_sha256"]
            == sha(canonical(event["offer"])),
            "query-run-execution-intent-differs",
        )
        check_action(service, principal, ref, body, "query-execute", permit)
    return True


def seal_fields(guard):
    return (
        {}
        if guard is None
        else {"schema_version": "1.1.0", "run_request": deepcopy(guard.request)}
    )


def check_mode(guard, permit):
    _check(
        (guard is None) == (permit["schema_version"] == "1.0.0"),
        "query-run-request-mode-differs",
    )
    if guard is not None:
        proof, _ = guard.check()
        _check(
            permit["run_request"]["run_authority"]["grant_sha256"]
            == proof["grant_sha256"],
            "query-run-action-grant-differs",
        )
