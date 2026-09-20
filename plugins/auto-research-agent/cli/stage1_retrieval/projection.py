"""Derive candidates and explicit outcomes from saved public CLI evidence."""

from stage1_ledger.journal import LedgerError
from .audit import read_audit, descendants, result_records, require


def record(value):
    # Preserve malformed/missing fields for the existing extraction failure ledger.
    result = {key: value.get(key) for key in ("title", "authors", "year")}
    for key, alternate in (
        ("doi", "doi"),
        ("arxiv", "arxiv_id"),
        ("pmid", "pmid"),
        ("version", "version"),
    ):
        item = value.get(key) or value.get(alternate)
        if item:
            result[key] = item
    return result


def project(saved, *, backend, process, operation="search", argv=None):
    """Never interpret exit zero or an empty stdout array as search success."""
    empty = dict(records=None, paths=[], provider_attempts=None, http_attempts=None)
    if process["failure"]:
        return dict(
            empty,
            outcome=process["failure"],
            http_status=None,
            error="process-" + process["failure"],
        )
    try:
        audit = read_audit(saved=saved)
        if argv is not None:
            require(
                audit["starts"][audit["manifest"]["command_id"]]["parameters"].get(
                    "argv"
                )
                == argv,
                "observed-command-mismatch",
            )
        require(
            audit["manifest"]["exit_code"] == process["exit_code"],
            "process-exit-mismatch",
        )
        result_operation = {
            "search": "backend-search",
            "enrich": "backend-lookup",
            "verify": "verify-doi" if backend == "doi.org" else "verify-arxiv",
        }.get(operation, operation)
        backend_events = [
            e for e in audit["finishes"].values() if e["operation"] == result_operation
        ]
        require(backend_events, "no-observed-backend")
        require(
            all(e["backend"] == backend for e in backend_events), "unexpected-backend"
        )
        rows, paths = [], []
        failures, statuses = [], []
        for event in backend_events:
            children = descendants(audit, event["attempt_id"])
            if event["outcome"] in {"success", "success_empty"}:
                require(event["artifacts"], "missing-parsed-results")
                require(
                    operation == "verify"
                    or any(
                        e["operation"] == "parse" and e["outcome"] == "success"
                        for e in children
                    ),
                    "missing-parse-observation",
                )
            statuses += [e["http_status"] for e in children if e["operation"] == "http"]
            failures += [
                e["outcome"]
                for e in children
                if e["outcome"] not in {"success", "success_empty"}
            ]
            if event["artifacts"]:
                for index, value in enumerate(
                    result_records(
                        audit, event, single=operation in {"enrich", "verify"}
                    )
                ):
                    if operation == "verify":
                        if value.get("ok") is not True:
                            failures.append("unknown")
                        continue
                    rows.append(record(value))
                    paths.append(
                        dict(
                            attempt_id=event["attempt_id"],
                            record_index=index,
                            parameters=event["parameters"],
                        )
                    )
        failures += (
            [audit["manifest"]["outcome"]]
            if audit["manifest"]["outcome"] not in {"success", "success_empty"}
            else []
        )
        good_statuses = [s for s in statuses if s is not None and 200 <= s < 300]
        if not failures and not good_statuses:
            failures.append("unknown")
        if process["exit_code"] != 0:
            failures.append("error")
        if failures:
            outcome = next(
                (
                    x
                    for x in (
                        "rate_limited",
                        "not_found",
                        "timeout",
                        "network_error",
                        "http_error",
                        "parse_error",
                    )
                    if x in failures
                ),
                "unknown_error",
            )
            status = (
                429
                if outcome == "rate_limited"
                else next((s for s in statuses if s in (404, 410)), None)
                if outcome == "not_found"
                else None
            )
            if rows:
                outcome, status = "partial_failure", None
        else:
            outcome = (
                "success_evidence"
                if operation == "verify"
                else "success_nonempty"
                if rows
                else "success_empty"
            )
            status = good_statuses[-1]
        return dict(
            outcome=outcome,
            http_status=status,
            records=rows if operation != "verify" and (rows or not failures) else None,
            paths=paths,
            provider_attempts=len(backend_events),
            http_attempts=sum(
                e["operation"] == "http" for e in audit["finishes"].values()
            ),
            error=",".join(sorted(set(failures))) or None,
        )
    except (LedgerError, OSError, KeyError, TypeError, ValueError) as error:
        return dict(empty, outcome="unknown_error", http_status=None, error=str(error))
