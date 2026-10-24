"""Trusted run-derived action checks; JSON alone never supplies authority."""

from copy import deepcopy
import math

from stage1_deliverable.common import sha
from stage1_ledger.journal import canonical

from .project_stage1_run_grant import (
    RunActionAuthorization,
    ProjectStage1RunGrantService,
)
from .project_stage1_run_lease import RunLease
from .session_api import _check, _hash


def action_identity(action, body):
    """Bind all operation data, excluding only transport/consent bookkeeping."""
    _check(type(action) is str and type(body) is dict, "run-action-identity-invalid")
    excluded = {
        "key",
        "revision",
        "confirmed",
        "user_input",
        "run_authority",
        "run_user_input",
    }
    return sha(
        canonical(
            {
                "action": action,
                "body": {
                    key: value for key, value in body.items() if key not in excluded
                },
            }
        )
    )


class RunActionGuard:
    def __init__(self, intake, principal, ref, body, token, *, operation, action):
        _check(
            type(token) is RunActionAuthorization
            and type(token.service) is ProjectStage1RunGrantService
            and token.service.intake is intake
            and type(body) is dict
            and body.get("confirmed") is False
            and body.get("key") == token.key + "-work"
            and "run_authority" not in body
            and "run_user_input" not in body,
            "run-action-explicit-derived-request-required",
        )
        self.intake, self.principal, self.ref = intake, principal, ref
        self.token, self.operation, self.action = token, operation, action
        self.identity = action_identity(action, body)
        self.request = deepcopy(body)
        proof, document = self.check()
        _check(
            type(body.get("input_version")) is int
            and body["input_version"] == document["binding"]["input_version"]
            and body.get("brief_sha256") == document["binding"]["brief_sha256"],
            "run-action-source-binding-differs",
        )
        if "user_input" in body:
            _check(
                body["user_input"] == document["user_input"],
                "run-action-consent-text-differs",
            )
        self.request.update(run_authority=proof, run_user_input=document["user_input"])

    def check(self):
        proof = self.token.check(
            self.intake, self.principal, self.ref, self.operation, self.identity
        )
        _, document = self.token.service._grant(
            self.principal, self.ref, self.token.grant_ref, self.token.grant_sha256
        )
        return proof, document

    def deadline_check(self, original=None):
        def check():
            if original is not None:
                original()
            self.check()

        return check

    def remaining_seconds(self):
        _, document = self.check()
        now = self.token.service._now()
        RunLease(self.intake, self.ref, document, self.token.grant_sha256).check(now)
        remaining = math.floor(document["expires_at"] - now)
        _check(remaining > 0, "run-action-deadline-exhausted")
        return remaining


def saved_run_check(service, intake, principal, ref, *, proof, operation, identity):
    """Reconstruct only from the configured issuer and its saved derived intent."""
    _check(
        type(service) is ProjectStage1RunGrantService
        and service.intake is intake
        and type(proof) is dict
        and type(proof.get("action_key")) is str
        and _hash(proof.get("action_request_sha256"))
        and _hash(proof.get("grant_sha256"))
        and type(proof.get("grant_ref")) is str,
        "run-action-owner-unconnected",
    )
    try:
        token = RunActionAuthorization(
            service,
            principal,
            ref,
            proof["grant_ref"],
            proof["grant_sha256"],
            operation,
            identity,
            proof["action_key"],
            proof["action_request_sha256"],
        )
        observed = token.check(intake, principal, ref, operation, identity)
    except (KeyError, TypeError) as exc:
        from .session_api import SessionApiError

        raise SessionApiError("run-action-saved-proof-invalid") from exc
    _check(observed == proof, "run-action-saved-proof-differs")
    return token
