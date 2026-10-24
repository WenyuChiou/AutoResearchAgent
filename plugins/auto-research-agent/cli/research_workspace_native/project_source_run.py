"""Run-derived source authority; transport and source evidence stay separate."""

from copy import deepcopy

from stage1_deliverable.common import canonical, sha
from .project_run_authority import RunActionGuard, action_identity, saved_run_check
from .project_stage1_run_grant import ProjectStage1RunGrantService
from .session_api import _check


def configured(intake, issuer):
    _check(
        issuer is None
        or type(issuer) is ProjectStage1RunGrantService
        and issuer.intake is intake,
        "source-run-issuer-invalid",
    )
    return issuer


def request(service, credential, ref, body, token, action):
    if token is None:
        return None
    _check(
        service.run_grants is not None
        and getattr(token, "service", None) is service.run_grants,
        "source-run-issuer-unconnected",
    )
    return RunActionGuard(
        service.intake,
        service.intake._principal(credential),
        ref,
        body,
        token,
        operation="source",
        action=action,
    )


def saved(service, principal, ref, body, action):
    _check(
        type(body) is dict
        and body.get("confirmed") is False
        and type(body.get("run_authority")) is dict
        and type(body["run_authority"].get("action_key")) is str
        and body.get("key") == body["run_authority"].get("action_key", "") + "-work",
        "source-run-request-invalid",
    )
    token = saved_run_check(
        service.run_grants,
        service.intake,
        principal,
        ref,
        proof=body["run_authority"],
        operation="source",
        identity=action_identity(action, body),
    )
    _, grant = service.run_grants._grant(
        principal, ref, token.grant_ref, token.grant_sha256
    )
    _check(
        body.get("run_user_input") == grant["user_input"]
        and "user_input" not in body
        and type(body.get("input_version")) is int
        and body["input_version"] == grant["binding"]["input_version"]
        and body.get("brief_sha256") == grant["binding"]["brief_sha256"],
        "source-run-consent-binding-differs",
    )
    return token, grant


def seal_fields(guard):
    if guard is None:
        return {}
    return dict(schema_version="1.1.0", run_request=deepcopy(guard.request))


def check_grant(service, principal, ref, grant):
    document = grant["document"]
    if document["schema_version"] == "1.0.0":
        return None
    _check(
        document["kind"] == "Stage1ProjectSourceGrant"
        and document["schema_version"] == "1.1.0"
        and set(document)
        == {
            "kind",
            "schema_version",
            "project_ref",
            "principal",
            "authorization_request_sha256",
            "offer_sha256",
            "offer",
            "issued_at",
            "expires_at",
            "automatic_retry",
            "execution_authorized",
            "run_request",
        },
        "source-run-grant-fields-invalid",
    )
    body = document["run_request"]
    token, original = saved(service, principal, ref, body, "source-authorize")
    semantic = {k: v for k, v in body.items() if k != "revision"}
    _check(
        grant["principal"] == document["principal"] == principal
        and grant["project_ref"] == document["project_ref"] == ref
        and grant["offer"] == document["offer"]
        and grant["offer_sha256"]
        == document["offer_sha256"]
        == semantic["offer_sha256"]
        == sha(canonical(document["offer"]))
        and grant["request"] == semantic
        and document["authorization_request_sha256"]
        == grant["request_sha256"]
        == sha(canonical(dict(kind="stage1-source-authorize", body=semantic)))
        and grant["expires_at"] == document["expires_at"] <= original["expires_at"],
        "source-run-grant-authority-differs",
    )
    return token


def check_mode(guard, grant):
    _check(
        (guard is None) == (grant["document"]["schema_version"] == "1.0.0"),
        "source-run-request-mode-differs",
    )
    if guard is not None:
        proof, _ = guard.check()
        _check(
            proof["grant_sha256"]
            == grant["document"]["run_request"]["run_authority"]["grant_sha256"],
            "source-run-action-grant-differs",
        )


def check_job(service, principal, ref, job, grant):
    original = check_grant(service, principal, ref, grant)
    if original is None:
        _check(
            "run_authority" not in job["action_request"],
            "source-run-request-mode-differs",
        )
        return
    token, document = saved(
        service, principal, ref, job["action_request"], "source-execute"
    )
    _check(
        token.grant_sha256 == original.grant_sha256
        and job["binding"]["deadline_at"] <= document["expires_at"],
        "source-run-job-authority-differs",
    )
