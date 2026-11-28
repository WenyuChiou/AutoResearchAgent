"""Read-only hint: can the approved scope reach the coverage gate? Never refuses anything."""

from pathlib import Path

from stage1_coverage.requirements import compare_with_scope, minimum_requirement
from stage1_ledger.journal import decode


def _unavailable(reason):
    return dict(unavailable=reason)


def coverage_requirement_hint(binding, limits):
    """Lower bound of the gate against the offered scope.

    ``binding`` is the saved topic binding, ``limits`` the limits of the search authorization offer.
    Only saved plan files are read; nothing is written and no decision depends on the result. When
    a number cannot be computed the result is ``{"unavailable": <reason code>}``, never a guess.
    """
    try:
        root = Path(binding["plan_root"])
        plan = decode((root / "coverage_plan.json").read_bytes(), "plan")
        stop_policy = plan["proposal"]["stop_policy"]
    except (KeyError, TypeError, ValueError, OSError):
        return _unavailable("coverage-plan-unreadable")
    try:
        planned = len((root / "query_plan.jsonl").read_bytes().splitlines())
    except OSError:
        return _unavailable("query-plan-unreadable")
    try:
        requirement = minimum_requirement(
            planned_query_count=planned,
            backend_count=len(limits["backends"]),
            stop_policy=stop_policy,
        )
    except (KeyError, TypeError, ValueError):
        return _unavailable("plan-values-invalid")
    try:
        return compare_with_scope(
            requirement,
            approved_rounds=binding["settings"]["budgets"]["rounds"],
            approved_search_attempts=limits["max_attempts"],
            approved_seconds=limits["max_reserved_seconds"],
            seconds_per_attempt=limits["timeout_seconds"] + 30,
        )
    except (KeyError, TypeError, ValueError):
        return _unavailable("approved-scope-values-missing")
