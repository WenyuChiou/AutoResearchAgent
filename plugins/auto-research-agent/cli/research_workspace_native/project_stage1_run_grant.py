"""Explicit user run grants; no provider, permit, reservation or acceptance is created.

Only a trusted driver may derive an action token. Downstream services must recheck
that token against their exact operation and payload before using existing lanes.
"""

from copy import deepcopy
from dataclasses import dataclass
import math
import time

from stage1_ledger.journal import canonical, decode
from stage1_deliverable.common import identifier, sha

from .project_intake import ProjectIntakeService
from .project_stage1_run_lease import RunLease
from .session_api import _check, _hash

STORE = "stage1_run_grants"
SCOPE = "stage1-topic-to-deliverable-1.0"
OPERATIONS = frozenset(
    {"query", "source", "analyze-full-paper", "agent-adoption", "records", "delivery"}
)
BOUND = {"key", "revision", "input_version", "brief_sha256"}
AUTHORIZE = BOUND | {
    "confirmed",
    "user_input",
    "scope",
    "operations",
    "max_seconds",
    "max_actions",
}


def _bound(body, fields):
    _check(
        type(body) is dict and set(body) == fields and len(canonical(body)) <= 16384,
        "stage1-run-fields-invalid",
        400,
    )
    identifier(body["key"])
    _check(
        type(body["revision"]) is int
        and body["revision"] >= 0
        and type(body["input_version"]) is int
        and body["input_version"] > 0
        and _hash(body["brief_sha256"]),
        "stage1-run-binding-invalid",
        400,
    )


@dataclass(frozen=True)
class RunActionAuthorization:
    """Trusted Python token; a matching browser JSON object is never sufficient."""

    service: object
    principal: str
    project_ref: str
    grant_ref: str
    grant_sha256: str
    operation: str
    identity: str
    key: str
    request_sha256: str

    def check(self, intake, principal, project_ref, operation, identity):
        _check(
            intake is self.service.intake
            and principal == self.principal
            and project_ref == self.project_ref
            and operation == self.operation
            and identity == self.identity,
            "stage1-run-action-binding-differs",
        )
        with intake._lock:
            _, document = self.service._grant(
                principal, project_ref, self.grant_ref, self.grant_sha256
            )
            _check(
                operation in document["operations"],
                "stage1-run-operation-not-authorized",
            )
            row = intake.db.execute(
                "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                (principal, project_ref, self.key),
            ).fetchone()
            _check(
                row is not None and row[0] == self.request_sha256,
                "stage1-run-derived-intent-missing",
            )
            receipt = decode(row[1].encode(), "derived Stage1 run action")
            _check(
                receipt["kind"] == "stage1-run-derive"
                and receipt["status"] == "saved"
                and receipt["request"]["operation"] == operation
                and receipt["request"]["identity"] == identity
                and receipt["request"]["grant_ref"] == self.grant_ref
                and receipt["request"]["grant_sha256"] == self.grant_sha256,
                "stage1-run-derived-intent-differs",
            )
            return dict(
                kind="Stage1DerivedRunActionAuthorization",
                schema_version="1.0.0",
                grant_ref=self.grant_ref,
                grant_sha256=self.grant_sha256,
                action_key=self.key,
                action_request_sha256=self.request_sha256,
                operation=operation,
                identity=identity,
                authority="user-run-grant",
                automated_actor="agent",
                human_per_action_confirmation=False,
            )


class ProjectStage1RunGrantService:
    def __init__(self, intake, *, runtime_sha256, clock=time.time, max_seconds=10800):
        _check(
            isinstance(intake, ProjectIntakeService)
            and _hash(runtime_sha256)
            and callable(clock)
            and type(max_seconds) is int
            and 0 < max_seconds <= 10800,
            "stage1-run-owner-invalid",
        )
        self.intake, self.runtime_sha256 = intake, runtime_sha256
        self.clock, self.max_seconds = clock, max_seconds

    def _now(self):
        value = self.clock()
        _check(
            type(value) in (int, float) and math.isfinite(value) and value >= 0,
            "stage1-run-clock-invalid",
        )
        return value

    def _binding(self, state):
        binding = self.intake.binding(state["project_ref"])
        _check("stage1_import" not in state, "imported-intake-is-read-only")
        return {
            key: binding[key]
            for key in (
                "project_id",
                "input_version",
                "brief_sha256",
                "plan_manifest_sha256",
            )
        } | {
            "settings_sha256": sha(canonical(binding["settings"])),
            "runtime_sha256": self.runtime_sha256,
        }

    def authorize(self, credential, ref, body):
        _bound(body, AUTHORIZE)
        _check(
            body["confirmed"] is True
            and body["scope"] == SCOPE
            and type(body["user_input"]) is str
            and bool(body["user_input"].strip())
            and len(body["user_input"].encode("utf8")) <= 8192,
            "stage1-run-explicit-user-consent-required",
            400,
        )
        operations = body["operations"]
        _check(
            type(operations) is list
            and bool(operations)
            and all(type(x) is str for x in operations)
            and len(set(operations)) == len(operations)
            and set(operations) <= OPERATIONS,
            "stage1-run-operation-invalid",
            400,
        )
        _check(
            type(body["max_seconds"]) is int
            and 0 < body["max_seconds"] <= self.max_seconds
            and type(body["max_actions"]) is int
            and 0 < body["max_actions"] <= 512,
            "stage1-run-limits-invalid",
            400,
        )
        principal = self.intake._principal(credential)

        def work(state, digest, actor):
            binding = self._binding(state)
            settings = self.intake.binding(ref)["settings"]
            budgets, consent = settings["budgets"], settings["consent"]
            _check(
                body["max_seconds"] <= budgets["seconds"], "stage1-run-budget-exceeded"
            )
            for operation, counter, flag in (
                ("query", "search_calls", "external_search"),
                ("source", "source_reads", "public_source_read"),
                ("analyze-full-paper", "model_calls", None),
            ):
                if operation in operations:
                    _check(
                        budgets[counter] > 0
                        and (flag is None or consent[flag] is True),
                        "stage1-run-lane-not-consented",
                    )
            grants = state.setdefault(STORE, {})
            _check(
                not any(
                    row["document"]["binding"] == binding for row in grants.values()
                ),
                "stage1-run-grant-renewal-refused",
            )
            issued = self._now()
            document = dict(
                kind="Stage1RunGrant",
                schema_version="1.0.0",
                scope=SCOPE,
                principal=actor,
                project_ref=ref,
                binding=binding,
                authority="user",
                provenance="explicit-user-run-consent",
                authorization_key=body["key"],
                authorization_request_sha256=digest,
                user_input=body["user_input"],
                operations=sorted(operations),
                budgets=deepcopy(budgets),
                consent=deepcopy(consent),
                issued_at=issued,
                expires_at=issued + body["max_seconds"],
                max_actions=body["max_actions"],
                automated_actor="agent",
                scientific_acceptance=False,
                core_acceptance=False,
                stage2_execution=False,
                automatic_resend=False,
            )
            grant_ref = "stage1-run-grant-" + digest[:32]
            pin = sha(canonical(document))
            RunLease(self.intake, ref, document, pin).create()
            grants[grant_ref] = dict(document=document, sha256=pin, revoked=False)
            return dict(
                grant_ref=grant_ref,
                grant_sha256=pin,
                expires_at=document["expires_at"],
                execution_observed=False,
                creates_lane_permits=False,
                resets_resources=False,
            )

        return self.intake._perform(
            principal, ref, "stage1-run-authorize", deepcopy(body), work
        )

    def _document(self, principal, ref, grant_ref, pin):
        _check(
            type(grant_ref) is str and _hash(pin), "stage1-run-reference-invalid", 400
        )
        state = self.intake._load(principal, ref)
        row = state.get(STORE, {}).get(grant_ref)
        _check(
            type(row) is dict and set(row) == {"document", "sha256", "revoked"},
            "stage1-run-grant-unavailable",
        )
        document = row["document"]
        _check(
            sha(canonical(document)) == row["sha256"] == pin
            and document["principal"] == principal
            and document["project_ref"] == ref,
            "stage1-run-grant-bytes-differ",
        )
        _check(row["revoked"] is False, "stage1-run-grant-revoked")
        action = self.intake.db.execute(
            "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
            (principal, ref, document["authorization_key"]),
        ).fetchone()
        _check(
            action is not None
            and action[0] == document["authorization_request_sha256"],
            "stage1-run-consent-intent-missing",
        )
        receipt = decode(action[1].encode(), "Stage1 user run consent")
        request = receipt["request"]
        _check(
            receipt["kind"] == "stage1-run-authorize"
            and receipt["status"] == "saved"
            and receipt["grant_ref"] == grant_ref
            and receipt["grant_sha256"] == pin
            and request["confirmed"] is True
            and request["user_input"] == document["user_input"]
            and request["scope"] == document["scope"] == SCOPE
            and sorted(request["operations"]) == document["operations"]
            and type(document["max_actions"]) is int
            and document["max_actions"] == request["max_actions"]
            and document["expires_at"]
            == receipt["expires_at"]
            == document["issued_at"] + request["max_seconds"]
            and document["authority"] == "user"
            and document["provenance"] == "explicit-user-run-consent"
            and document["automated_actor"] == "agent"
            and document["scientific_acceptance"] is False
            and document["core_acceptance"] is False
            and document["stage2_execution"] is False
            and document["automatic_resend"] is False
            and sha(canonical({"kind": receipt["kind"], "body": request})) == action[0],
            "stage1-run-consent-intent-differs",
        )
        return state, document

    def _grant(self, principal, ref, grant_ref, pin):
        state, document = self._document(principal, ref, grant_ref, pin)
        _check(document["binding"] == self._binding(state), "stage1-run-grant-stale")
        RunLease(self.intake, ref, document, pin).check(self._now())
        return state, document

    def inspect(self, credential, ref, grant_ref, grant_sha256):
        principal = self.intake._principal(credential)
        with self.intake._lock:
            _, document = self._grant(principal, ref, grant_ref, grant_sha256)
            return deepcopy(document)

    def derive(self, credential, ref, *, grant_ref, grant_sha256, operation, identity):
        """Trusted driver only; no callable/provider is accepted or dispatched."""
        _check(
            type(operation) is str and operation in OPERATIONS and _hash(identity),
            "stage1-run-action-invalid",
            400,
        )
        principal = self.intake._principal(credential)
        with self.intake._lock:
            state, document = self._grant(principal, ref, grant_ref, grant_sha256)
            _check(
                operation in document["operations"],
                "stage1-run-operation-not-authorized",
            )
            key = (
                "stage1-run-action-"
                + sha(canonical([grant_sha256, operation, identity]))[:40]
            )
            body = {key: state[key] for key in ("revision", "input_version")}
            body.update(
                key=key,
                brief_sha256=document["binding"]["brief_sha256"],
                grant_ref=grant_ref,
                grant_sha256=grant_sha256,
                operation=operation,
                identity=identity,
            )

            def work(current, digest, actor):
                _, fresh = self._grant(actor, ref, grant_ref, grant_sha256)
                rows = self.intake.db.execute(
                    "SELECT receipt FROM intake_actions WHERE principal=? AND project=?",
                    (actor, ref),
                ).fetchall()
                count = sum(
                    1
                    for row in rows
                    if (action := decode(row[0].encode(), "run action"))["kind"]
                    == "stage1-run-derive"
                    and action["request"].get("grant_ref") == grant_ref
                )
                _check(
                    count <= fresh["max_actions"], "stage1-run-action-bound-exhausted"
                )
                return dict(
                    authority="derived-user-run-grant",
                    automated_actor="agent",
                    execution_observed=False,
                    resources_reserved=False,
                )

            receipt = self.intake._perform(
                principal, ref, "stage1-run-derive", body, work
            )
            _check(receipt["status"] == "saved", "stage1-run-action-execution-unknown")
            return RunActionAuthorization(
                self,
                principal,
                ref,
                grant_ref,
                grant_sha256,
                operation,
                identity,
                key,
                receipt["request_sha256"],
            )

    def revoke(self, credential, ref, body):
        _bound(body, BOUND | {"grant_ref", "grant_sha256"})
        _check(
            type(body["grant_ref"]) is str and _hash(body["grant_sha256"]),
            "stage1-run-reference-invalid",
            400,
        )
        principal = self.intake._principal(credential)

        with self.intake._lock:
            _, document = self._document(
                principal, ref, body["grant_ref"], body["grant_sha256"]
            )
            # Cancellation only reduces authority. It is independent of ordinary
            # action-history capacity, clock validity and current settings.
            return RunLease(self.intake, ref, document, body["grant_sha256"]).revoke(
                deepcopy(body)
            )
