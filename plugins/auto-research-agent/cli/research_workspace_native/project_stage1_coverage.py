"""Explicit local Core coverage actions; no claim creation or external work."""

from copy import deepcopy
import json

from stage1_coverage.evidence import IDENTITY_FIELDS
from stage1_deliverable.common import canonical, sha
from stage1_ledger.validation import validate_run

from .project_intake_contract import _text
from .session_api import _check

FIELDS = {"operation", "offer_ref", "offer_sha256", "review"}
MAX_OFFERS = 256
MAX_OFFER_BYTES = 512 * 1024


def _review_fields(review, expected):
    _check(
        type(review) is dict and set(review) == set(expected),
        "stage1-coverage-review-fields",
        400,
    )


def unresolved(service, ref, actor, version):
    """Uncertain local writes remain held across reconnect and new action keys."""
    rows = service.intake.db.execute(
        "SELECT receipt FROM intake_actions WHERE principal=? AND project=?",
        (actor, ref),
    ).fetchall()
    return [
        row
        for raw in rows
        if (row := json.loads(raw[0]))["kind"] in {"stage1-coverage", "stage1-claim"}
        and row["status"] in {"intent-recorded", "execution-unknown"}
        and row["request"]["input_version"] == version
    ]


def offers(ledger, binding, run, report):
    state = ledger.coverage_state()
    clusters = [
        {"cluster_id": c["cluster_id"], "title": c.get("label", c["cluster_id"])}
        for c in state.plan["proposal"]["clusters"]
    ]
    result = []
    offered_bytes = 0
    omitted_actions = 0

    def add(operation, document):
        nonlocal offered_bytes, omitted_actions
        document_bytes = len(canonical(document))
        if (
            len(result) >= MAX_OFFERS
            or document_bytes > 128 * 1024
            or offered_bytes + document_bytes > MAX_OFFER_BYTES
        ):
            omitted_actions += 1
            return
        bound = dict(
            project_id=binding["project_id"],
            input_version=binding["input_version"],
            brief_sha256=binding["brief_sha256"],
            run_ref=run["run_ref"],
            ledger_state_sha256=report["state_sha256"],
            operation=operation,
            document=document,
        )
        digest = sha(canonical(bound))
        result.append(
            dict(
                operation=operation,
                offer_ref="coverage-" + digest[:32],
                offer_sha256=digest,
                document=deepcopy(document),
            )
        )
        offered_bytes += document_bytes

    blockers = deepcopy((report.get("coverage") or {}).get("blockers", []))
    add("human-action", dict(clusters=clusters, blockers=blockers))
    if state.active is not None:
        add("close-round", dict(round_number=state.active, summary=state.summary()))
    next_round = len(state.closed) + 1
    max_rounds = min(
        state.plan["proposal"]["stop_policy"]["max_rounds"],
        binding["settings"]["budgets"]["rounds"],
    )
    if state.active is None and next_round <= max_rounds:
        add("open-round", dict(round_number=next_round, max_rounds=max_rounds))
    for row in state.completed.values():
        if row["arguments"].get("coverage", {}).get("round_number") == state.active:
            add(
                "receipt",
                dict(
                    query_event_id=row["event_id"],
                    query=row["arguments"].get("query", "Unknown"),
                    result_count=row["result_count"],
                    outcome=row["outcome"],
                    current_receipt=state.receipts.get(row["event_id"]),
                ),
            )
    eligible = 0
    for work, candidate in state.evidence.candidates.items():
        decision = state.evidence.decisions.get(work)
        if not decision or decision["new_decision"] != "include":
            continue
        eligible += 1
        review = state.evidence.current().get(work)
        version = (
            review["version_id"]
            if review
            else candidate["discoveries"][-1]["version_id"]
        )
        claims = [
            dict(
                claim_ref=c["event_id"],
                text=c["claim_text"],
                relation=c["relation"],
                evidence_level=c["evidence_level"],
                quote=c["locator"]["quote"],
                source_sha256=c["source_ref"]["sha256"],
            )
            for c in state.evidence.claims.values()
            if (c["work_id"], c["version_id"]) == (work, version)
            and c["relation"] in {"supports", "partial"}
            and c["evidence_level"]
            in {"abstract", "full-text", "full_text", "primary_data_or_table"}
            and c["locator"] is not None
        ]
        discovery = next(
            d for d in reversed(candidate["discoveries"]) if d["version_id"] == version
        )
        add(
            "review-work",
            dict(
                work_ref=work,
                version_id=version,
                title=discovery["record"].get("title", work),
                candidate_event_id=candidate["event_id"],
                decision_event_id=decision["event_id"],
                current_review=review,
                clusters=clusters,
                claims=claims,
            ),
        )
    return dict(
        schema_version="1.0.0",
        ledger_state_sha256=report["state_sha256"],
        active_round=state.active,
        blockers=blockers,
        offers=result,
        eligible_work_count=eligible,
        omitted_work_count=eligible
        - sum(r["operation"] == "review-work" for r in result),
        omitted_action_count=omitted_actions,
        creates_claims=False,
        grants_external_permission=False,
    )


def prepare(ledger, binding, run, report, body, actor):
    offer = next(
        (
            row
            for row in offers(ledger, binding, run, report)["offers"]
            if row["operation"] == body["operation"]
            and row["offer_ref"] == body["offer_ref"]
            and row["offer_sha256"] == body["offer_sha256"]
        ),
        None,
    )
    _check(offer is not None, "stage1-coverage-offer-stale")
    document, review = offer["document"], body["review"]
    operation = offer["operation"]
    if operation == "review-work":
        _review_fields(
            review,
            {
                "cluster_claims",
                "identity_status",
                "identity_claims",
                "closest",
                "rationale",
            },
        )
        _check(
            type(review["cluster_claims"]) is dict
            and bool(review["cluster_claims"])
            and type(review["identity_claims"]) is dict
            and type(review["closest"]) is bool,
            "stage1-coverage-review-fields",
            400,
        )
        available = {c["claim_ref"] for c in document["claims"]}
        _check(
            all(type(v) is str for v in review["cluster_claims"].values())
            and all(
                v is None or type(v) is str for v in review["identity_claims"].values()
            ),
            "stage1-coverage-claim-reference-invalid",
            400,
        )
        _check(
            set(review["cluster_claims"])
            <= {c["cluster_id"] for c in document["clusters"]}
            and set(review["cluster_claims"].values()) <= available
            and set(review["identity_claims"]) == IDENTITY_FIELDS
            and all(
                v is None or v in available for v in review["identity_claims"].values()
            ),
            "stage1-coverage-claim-not-offered",
            400,
        )
        _check(
            type(review["identity_status"]) is str
            and review["identity_status"] in {"verified", "unverifiable", "conflict"},
            "stage1-coverage-identity-status",
            400,
        )
        args = dict(
            work_id=document["work_ref"],
            version_id=document["version_id"],
            cluster_claims=review["cluster_claims"],
            identity_status=review["identity_status"],
            identity_claims=review["identity_claims"],
            closest=review["closest"],
            assessor=actor,
            rationale=_text(review["rationale"]),
        )
        payload = dict(
            kind="CoverageWorkReview",
            **args,
            candidate_event_id=document["candidate_event_id"],
            decision_event_id=document["decision_event_id"],
            scope="reviewer-attestation",
            replaces_event_id=(document["current_review"] or {}).get("event_id"),
        )
        method = "review_work"
    elif operation == "receipt":
        _review_fields(review, {"truncated", "note"})
        _check(
            review["truncated"] is None or type(review["truncated"]) is bool,
            "stage1-coverage-truncated-invalid",
            400,
        )
        args = dict(
            query_event_id=document["query_event_id"],
            truncated=review["truncated"],
            note=_text(review["note"]),
        )
        payload = dict(
            kind="CoverageReceipt",
            **args,
            replaces_event_id=(document["current_receipt"] or {}).get("event_id"),
        )
        method = "receipt"
    elif operation == "human-action":
        _review_fields(review, {"action", "cluster_id", "user_input"})
        _check(
            type(review["action"]) is str
            and review["action"] in {"accept-stop", "request-cluster"}
            and (review["cluster_id"] is None or type(review["cluster_id"]) is str),
            "stage1-coverage-human-action-invalid",
            400,
        )
        args = dict(
            action=review["action"],
            cluster_id=review["cluster_id"],
            actor=actor,
            user_input=_text(review["user_input"]),
            reviewed_state_sha256=report["state_sha256"],
        )
        payload, method = dict(kind="CoverageHumanAction", **args), "human_action"
    else:
        _review_fields(review, set())
        args = {}
        if operation == "open-round":
            payload, method = (
                dict(kind="CoverageRoundOpened", round_number=document["round_number"]),
                "open_round",
            )
        else:
            payload, method = (
                dict(
                    kind="CoverageRoundClosed",
                    round_number=document["round_number"],
                    summary=document["summary"],
                ),
                "close_round",
            )
    # Apply the unchanged Core semantics on a fresh in-memory replay before intent.
    # A locator proves a recorded quotation, not the scientific truth of a claim.
    ledger.coverage_state().observe(payload)
    return method, deepcopy(args), payload


def execute(service, credential, ref, body, *, check_deadline=None):
    _check(
        type(body) is dict
        and type(body.get("operation")) is str
        and type(body.get("review")) is dict,
        "stage1-coverage-fields",
        400,
    )

    def preflight(state, run, ledger, report, actor):
        prepare(ledger, service.intake.binding(ref), run, report, body, actor)
        if check_deadline is not None:
            check_deadline()

    def producer(state, run, ledger, _, actor):
        report = validate_run(ledger.root)
        method, args, expected = prepare(
            ledger, service.intake.binding(ref), run, report, body, actor
        )
        if check_deadline is not None:
            check_deadline()
        event = getattr(ledger, method)(**args)
        _check(
            all(event.get(k) == v for k, v in expected.items()),
            "stage1-coverage-core-result-differs",
        )
        return dict(
            operation=body["operation"],
            event_id=event["event_id"],
            ledger_state_sha256=ledger.state_hash(),
            scientific_acceptance=False,
            stage1_complete=False,
            grants_external_permission=False,
        )

    return service._mutate(
        credential,
        ref,
        body,
        "stage1-coverage",
        producer,
        fields=FIELDS,
        preflight=preflight,
        check_deadline=check_deadline,
    )
