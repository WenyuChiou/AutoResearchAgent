"""Explicit citation grants on the existing query owner and resource ledger.

GET reads saved Core reviews. Each new grant permits exactly one seed/version,
round and backend attempt, charging the original query and project allowances.
Neither a search seal nor an available offer authorizes citation execution.
"""

from copy import deepcopy
import json
import time

from stage1_coverage.run import CoverageLedger
from stage1_coverage.policy import query_complete
from stage1_deliverable.common import canonical, sha
from stage1_ledger.journal import write_new
from stage1_retrieval.runner import identifier_for
from .planned_query_contract import require, tree_sha
from .project_query_permit import inspect_seal
from .project_resource_budget import resource_view


def saved_grant(intake, state, principal, digest):
    """Validate immutable bytes and the exact saved authorization action/event."""
    record = state.get("stage1_expansion_grants", {}).get(digest)
    require(
        type(record) is dict and set(record) == {"path", "sha256", "permit"},
        "project-expansion-grant-missing",
    )
    raw = intake._path(state["project_ref"], record["path"]).read_bytes()
    permit = record["permit"]
    require(
        sha(raw) == digest == record["sha256"] and json.loads(raw) == permit,
        "project-expansion-grant-bytes-differ",
    )
    request_hash = permit["authorization_request_sha256"]
    require(
        record["path"] == "x1-" + request_hash[:20] + "-permit.json",
        "project-expansion-grant-path-differs",
    )
    action = intake.db.execute(
        "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND request_hash=?",
        (principal, state["project_ref"], request_hash),
    ).fetchall()
    saved = json.loads(action[0][0]) if len(action) == 1 else {}
    events = intake.db.execute(
        "SELECT payload FROM intake_events WHERE project=? AND kind='stage1-expansion-authorize-saved'",
        (state["project_ref"],),
    ).fetchall()
    require(
        set(permit)
        == {
            "kind",
            "schema_version",
            "principal",
            "project_ref",
            "document",
            "expires_at_unix",
            "max_attempts",
            "authorization_request_sha256",
            "user_input",
        }
        and permit["kind"] == "Stage1ExactExpansionPermit"
        and permit["schema_version"] == "1.0.0"
        and permit["principal"] == principal
        and permit["project_ref"] == state["project_ref"]
        and type(permit["max_attempts"]) is int
        and permit["max_attempts"] == 1
        and type(permit["expires_at_unix"]) is int
        and saved.get("kind") == "stage1-expansion-authorize"
        and saved.get("status") == "saved"
        and saved.get("permit_sha256") == digest
        and saved.get("request_sha256")
        == sha(canonical(dict(kind=saved["kind"], body=saved["request"])))
        and saved["request"].get("user_input") == permit["user_input"]
        and saved["request"].get("confirmed") is True
        and saved["request"].get("offer_sha256") == sha(canonical(permit["document"]))
        and saved["request"].get("offer_ref")
        == "project-expansion-" + saved["request"]["offer_sha256"][:32]
        and any(json.loads(row[0]) == saved for row in events),
        "project-expansion-authorization-differs",
    )
    return permit


def expansion_target(permit, digest):
    document = permit["document"]
    return dict(
        **{
            k: deepcopy(document[k])
            for k in (
                "operation",
                "work_id",
                "version_id",
                "title",
                "backend",
                "arguments",
            )
        },
        planned_id=None,
        query_id=None,
        expansion_grant_sha256=digest,
        expansion_expires_at_unix=permit["expires_at_unix"],
    )


def validate_expansion(queries, ref, principal, target, phase, *, client_key=None):
    """No callback or dispatch. Worker callers never hold the query lock here."""
    intake = queries.intake
    state = intake._load(principal, ref)
    authorization = state["stage1_query_authorization"]
    binding, original = inspect_seal(
        intake, ref, authorization, queries.config, ready=False
    )
    digest = target["expansion_grant_sha256"]
    permit = saved_grant(intake, state, principal, digest)
    document = permit["document"]
    service = queries.services.get(ref)
    require(
        service is not None and not queries.closing,
        "project-query-owner-reopen-required",
    )
    item = service._projects[ref]["item"]
    require(
        document["project_ref"] == ref
        and document["principal"] == principal
        and document["input_version"] == binding["input_version"]
        and document["brief_sha256"] == binding["brief_sha256"]
        and document["original_permit_sha256"] == authorization["sha256"]
        and document["registration_sha256"] == sha(canonical(item))
        and all(
            target.get(k) == value
            for k, value in expansion_target(permit, digest).items()
        ),
        "project-expansion-binding-differs",
    )
    ledger = CoverageLedger(item["ledger_root"])
    coverage = ledger.coverage_state()
    review = coverage.evidence.current().get(document["work_id"])
    require(
        coverage.active == document["round_number"]
        and review is not None
        and review["closest"]
        and review["identity_status"] == "verified"
        and review["version_id"] == document["version_id"]
        and sha(canonical(review)) == document["review_sha256"]
        and coverage.expansion_arguments(
            document["operation"], document["work_id"], document["version_id"]
        )
        == document["arguments"]
        and coverage.backends_for(document["arguments"]) == [document["backend"]]
        and identifier_for(ledger, dict(arguments=document["arguments"]))
        == document["identifier"],
        "project-expansion-seed-or-round-stale",
    )
    require(
        time.time() + queries.config["pin"]["timeout_seconds"] + 30
        < permit["expires_at_unix"],
        "project-expansion-grant-expired",
    )
    uses = state.get("stage1_expansion_uses", {})
    if client_key is None:
        require(digest not in uses, "project-expansion-grant-consumed")
    else:
        require(
            client_key == "project-" + uses.get(digest, ""),
            "project-expansion-dispatch-intent-differs",
        )
    if isinstance(phase, str) and phase in {"offer", "before-runner"}:
        require(
            tree_sha(ledger.root) == document["ledger_tree_sha256"],
            "project-expansion-frontier-stale",
        )
    return permit, original


class ProjectStage1ExpansionService:
    def __init__(self, queries):
        from .project_stage1_queries import ProjectStage1QueryService

        require(
            isinstance(queries, ProjectStage1QueryService),
            "project-expansion-query-owner-required",
        )
        self.queries, self.intake = queries, queries.intake

    def _context(self, credential, ref):
        principal, state = self.queries._state(credential, ref)
        authorization = state.get("stage1_query_authorization")
        require(authorization is not None, "project-query-permission-required")
        binding, original = inspect_seal(
            self.intake, ref, authorization, self.queries.config, ready=False
        )
        service = self.queries.services.get(ref)
        require(
            service is not None and not self.queries.closing,
            "project-query-owner-reopen-required",
        )
        frontier = service.inspect_saved(credential, ref)
        from .project_query_versions import current_budget

        budget = current_budget(self.intake, state, principal)
        seconds = self.queries.config["pin"]["timeout_seconds"] + 30
        resources = resource_view(self.intake, state, principal)
        remaining = original["limits"]["max_attempts"] - budget["attempts"]
        require(
            remaining > 0
            and budget["seconds"] + seconds
            <= original["limits"]["max_reserved_seconds"]
            and resources["remaining"]["search_calls"] > 0
            and resources["remaining"]["seconds"] >= seconds,
            "project-query-total-budget-exhausted",
            429,
        )
        item = service._projects[ref]["item"]
        ledger = CoverageLedger(item["ledger_root"])
        coverage = ledger.coverage_state()
        require(coverage.active is not None, "project-expansion-round-not-open")
        return (
            principal,
            state,
            binding,
            service,
            ledger,
            coverage,
            frontier,
            remaining,
            seconds,
        )

    def _offers(self, credential, ref, *, unavailable=None):
        (
            principal,
            state,
            binding,
            service,
            ledger,
            coverage,
            frontier,
            remaining,
            seconds,
        ) = self._context(credential, ref)
        result = []
        for work_id, review in sorted(coverage.evidence.current().items()):
            if not review["closest"] or review["identity_status"] != "verified":
                continue
            for operation in ("references", "cited-by"):
                arguments = coverage.expansion_arguments(
                    operation, work_id, review["version_id"]
                )
                matches = [
                    row
                    for row in coverage.completed.values()
                    if row["arguments"].get("coverage", {}).get("seed_work_id")
                    == work_id
                    and row["arguments"].get("coverage", {}).get("seed_version_id")
                    == review["version_id"]
                    and row["arguments"].get("operation") == operation
                ]
                if matches and query_complete(coverage, matches[-1]):
                    continue
                if coverage.backends_for(arguments) != ["semantic-scholar"]:
                    if unavailable is not None:
                        unavailable.append(
                            dict(
                                work_id=work_id,
                                version_id=review["version_id"],
                                operation=operation,
                                code="project-expansion-citation-backend-unavailable",
                            )
                        )
                    continue
                try:
                    identifier = identifier_for(ledger, dict(arguments=arguments))
                except Exception:
                    if unavailable is not None:
                        unavailable.append(
                            dict(
                                work_id=work_id,
                                version_id=review["version_id"],
                                operation=operation,
                                code="citation-seed-has-no-supported-identifier",
                            )
                        )
                    continue
                candidate = coverage.evidence.candidates[work_id]
                document = dict(
                    project_ref=ref,
                    principal=principal,
                    input_version=binding["input_version"],
                    brief_sha256=binding["brief_sha256"],
                    original_permit_sha256=state["stage1_query_authorization"][
                        "sha256"
                    ],
                    registration_sha256=sha(canonical(service._projects[ref]["item"])),
                    ledger_tree_sha256=frontier["tree_sha256"],
                    ledger_state_sha256=frontier["state_sha256"],
                    round_number=coverage.active,
                    work_id=work_id,
                    version_id=review["version_id"],
                    title=candidate["discoveries"][0]["record"].get("title", work_id),
                    review_sha256=sha(canonical(review)),
                    operation=operation,
                    arguments=arguments,
                    backend="semantic-scholar",
                    identifier=identifier,
                    remaining_attempts=remaining,
                    reserved_seconds=seconds,
                    validity_seconds=self.queries.config["caps"]["validity_seconds"],
                    max_attempts=1,
                    model_execution=False,
                    source_acquisition=False,
                    automatic_retry=False,
                )
                digest = sha(canonical(document))
                result.append(
                    dict(
                        offer_ref="project-expansion-" + digest[:32],
                        offer_sha256=digest,
                        document=document,
                    )
                )
        require(len(result) <= 128, "project-expansion-offer-bound", 429)
        return result

    def read(self, credential, ref):
        with self.intake._lock:
            principal, state = self.queries._state(credential, ref)
            result = dict(
                connected=True,
                authorization_offers=[],
                execution_offers=[],
                history=[],
                unavailable=[],
                automatic_retry=False,
                stage1_complete=False,
            )
            for record in state.get("stage1_expansion_grants", {}).values():
                doc = record["permit"]["document"]
                result["history"].append(
                    dict(
                        operation=doc["operation"],
                        work_id=doc["work_id"],
                        version_id=doc["version_id"],
                        status="consumed"
                        if record["sha256"] in state.get("stage1_expansion_uses", {})
                        else "permission-saved",
                        permit_sha256=record["sha256"],
                    )
                )
            try:
                offers = self._offers(
                    credential, ref, unavailable=result["unavailable"]
                )
                for position, record in enumerate(
                    state.get("stage1_expansion_grants", {}).values()
                ):
                    try:
                        target = expansion_target(record["permit"], record["sha256"])
                        validate_expansion(
                            self.queries, ref, principal, target, "offer"
                        )
                        offered = self.queries.services[ref].offer(
                            credential, ref, expansion=target
                        )
                        result["execution_offers"].append(offered)
                        offers = [
                            row
                            for row in offers
                            if row["document"] != record["permit"]["document"]
                        ]
                    except Exception as error:
                        result["history"][position]["refusal"] = getattr(
                            error, "code", "project-expansion-grant-unavailable"
                        )
                result["authorization_offers"] = offers
            except Exception as error:
                result["refusal"] = getattr(
                    error, "code", "project-expansion-unavailable"
                )
            return result

    def authorize(self, credential, ref, body, *, check_deadline=None):
        self.queries._request(body, authorization=True)
        principal = self.intake._principal(credential)

        def work(state, request_hash, actor):
            grants = state.setdefault("stage1_expansion_grants", {})
            require(len(grants) < 128, "project-expansion-grant-bound", 429)
            offered = next(
                (
                    row
                    for row in self._offers(credential, ref)
                    if row["offer_ref"] == body["offer_ref"]
                    and row["offer_sha256"] == body["offer_sha256"]
                ),
                None,
            )
            require(offered is not None, "project-expansion-offer-differs")
            document = offered["document"]
            require(
                not any(
                    row["permit"]["document"] == document for row in grants.values()
                ),
                "project-expansion-already-authorized",
            )
            permit = dict(
                kind="Stage1ExactExpansionPermit",
                schema_version="1.0.0",
                principal=actor,
                project_ref=ref,
                document=document,
                expires_at_unix=int(time.time()) + document["validity_seconds"],
                max_attempts=1,
                authorization_request_sha256=request_hash,
                user_input=body["user_input"],
            )
            raw = canonical(permit) + b"\n"
            digest = sha(raw)
            path = "x1-" + request_hash[:20] + "-permit.json"
            write_new(self.intake._path(ref, path), raw)
            grants[digest] = dict(path=path, sha256=digest, permit=permit)
            return dict(
                permit_sha256=digest,
                operation=document["operation"],
                work_id=document["work_id"],
                version_id=document["version_id"],
                stage1_complete=False,
            )

        return self.intake._perform(
            principal,
            ref,
            "stage1-expansion-authorize",
            deepcopy(body),
            work,
            check_deadline=check_deadline,
        )

    def execute(self, credential, ref, body, *, check_deadline=None):
        self.queries._request(body)
        principal = self.intake._principal(credential)

        def offered():
            value = self.read(credential, ref)
            offer = next(
                (
                    row
                    for row in value["execution_offers"]
                    if row["offer_ref"] == body["offer_ref"]
                    and row["offer_sha256"] == body["offer_sha256"]
                ),
                None,
            )
            require(offer is not None, "project-expansion-offer-differs")
            return offer

        captured = {}

        def reserve(state, request_hash, actor):
            offer = offered()
            target = offer["document"]
            validate_expansion(self.queries, ref, actor, target, "offer")
            self.queries._reserve(
                state, actor, body["key"], request_hash, expansion=True
            )
            state.setdefault("stage1_expansion_uses", {})[
                target["expansion_grant_sha256"]
            ] = request_hash
            state.setdefault("stage1_expansion_dispatches", {})[request_hash] = (
                deepcopy(offer)
            )
            captured["offer"] = offer

        def work(state, request_hash, actor):
            offer = captured["offer"]
            target = offer["document"]
            permit, _ = validate_expansion(
                self.queries,
                ref,
                actor,
                target,
                "offer",
                client_key="project-" + request_hash,
            )
            inner = dict(
                key="project-" + request_hash,
                revision=offer["revision"],
                index_sha256=target["index_sha256"],
                input_version=target["input_version"],
                offer_ref=offer["offer_ref"],
                offer_sha256=offer["offer_sha256"],
                confirmed=True,
            )
            deadline = time.monotonic() + min(
                permit["expires_at_unix"] - time.time(), target["reserved_seconds"]
            )
            observed = self.queries.services[ref].execute(
                credential,
                ref,
                inner,
                deadline=deadline,
                expansion=expansion_target(permit, target["expansion_grant_sha256"]),
            )
            return dict(
                query_status=observed["status"],
                query_action_key=inner["key"],
                query_request_sha256=observed["request_sha256"],
                operation=target["operation"],
                work_id=target["work_id"],
                version_id=target["version_id"],
                expansion_grant_sha256=target["expansion_grant_sha256"],
                stage1_complete=False,
            )

        return self.intake._perform(
            principal,
            ref,
            "stage1-expansion-execute",
            deepcopy(body),
            work,
            reserve=reserve,
            check_deadline=check_deadline,
        )
