"""Read-only hint: can the approved scope reach the coverage gate? Never refuses anything."""

from pathlib import Path

from stage1_coverage.requirements import compare_with_scope, minimum_requirement
from stage1_ledger.journal import decode


def coverage_requirement_hint(binding, limits):
    """Lower bound of the gate against the offered scope, or None if it cannot be computed.

    ``binding`` is the saved topic binding, ``limits`` the limits of the search authorization offer.
    Only saved plan files are read; nothing is written and no decision depends on the result.
    """
    try:
        root = Path(binding["plan_root"])
        plan = decode((root / "coverage_plan.json").read_bytes(), "plan")
        planned = len((root / "query_plan.jsonl").read_bytes().splitlines())
        requirement = minimum_requirement(
            planned_query_count=planned,
            backend_count=len(limits["backends"]),
            stop_policy=plan["proposal"]["stop_policy"],
        )
        return compare_with_scope(
            requirement,
            approved_rounds=binding["settings"]["budgets"]["rounds"],
            approved_search_attempts=limits["max_attempts"],
        )
    except (KeyError, TypeError, ValueError, OSError):
        return None
