"""Deterministic invariants shared by recording and independent journal replay."""

from .journal import LedgerError, decode

SUCCESS = {"success_nonempty", "success_empty", "success_evidence"}


def completion_count(payload, read_ref):
    outcome, status = payload["outcome"], payload["http_status"]
    if (status == 429) != (outcome == "rate_limited"):
        raise LedgerError("rate-limit-outcome-conflict")
    if (status in (404, 410)) != (outcome == "not_found"):
        raise LedgerError("not-found-outcome-conflict")
    if outcome == "success_evidence":
        if (
            payload["exit_code"] != 0
            or status is None
            or not 200 <= status < 300
            or payload["records"] is not None
        ):
            raise LedgerError("evidence-without-successful-response")
        return 0
    if outcome in SUCCESS or outcome == "partial_failure":
        if (
            (
                outcome in SUCCESS
                and (
                    payload["exit_code"] != 0
                    or status is None
                    or not 200 <= status < 300
                )
            )
            or (outcome == "partial_failure" and status is not None)
            or payload["records"] is None
        ):
            raise LedgerError("success-without-parsed-response")
        rows = decode(read_ref(payload["records"]), payload["records"]["path"])
        if not isinstance(rows, list):
            raise LedgerError("records-not-array")
        if (outcome == "success_empty") != (len(rows) == 0):
            raise LedgerError("result-count-outcome-conflict")
        return len(rows)
    if payload["records"] is not None:
        raise LedgerError("failure-cannot-supply-success-records")
    return 0


def query_fields(query, children, finished):
    successes = [p for p in finished if p["outcome"] in SUCCESS]
    count = sum(p["result_count"] for p in finished)
    if not successes and not count:
        outcome = "failed"
    elif len(successes) != len(finished):
        outcome = "partial_failure"
    else:
        outcome = (
            "success_evidence"
            if all(p["outcome"] == "success_evidence" for p in finished)
            else "success_nonempty"
            if count
            else "success_empty"
        )
    return dict(
        query_id=query["event_id"],
        arguments=query["arguments"],
        started_at=query["created_at"],
        outcome=outcome,
        attempted_backends=[p["backend"] for p in children],
        completion_ids=[p["event_id"] for p in finished],
        result_count=count,
    )


def claim_check(payload, read_ref):
    # A locator is an auditable observation, not a proof that a claim is true.
    locator = payload["locator"]
    if payload["relation"] not in {"pending", "unclear", "unverifiable"} and (
        locator is None or payload["evidence_level"] in {"metadata", "unavailable"}
    ):
        raise LedgerError("claim-needs-text-evidence-and-locator")
    if payload["evidence_level"] == "unavailable" and locator is not None:
        raise LedgerError("unavailable-evidence-has-locator")
    data = read_ref(payload["source_ref"])
    if locator is not None:
        try:
            text = data.decode("utf-8")
        except UnicodeError as error:
            raise LedgerError("claim-source-must-be-saved-utf8-text") from error
        if locator["quote"] not in text:
            raise LedgerError("claim-quote-not-in-source")
