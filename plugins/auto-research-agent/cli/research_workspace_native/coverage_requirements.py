"""Lower bound of what the Stage 1 coverage gate needs, as plain arithmetic.

This module only counts. It reads no file, writes nothing and never changes the gate: the rules
stay in ``policy.py`` and ``rounds.py``. The numbers are lower bounds ("at least"), taken from the
smallest run the gate can accept:

* The gate needs ``consecutive_zero_yield_rounds`` closed, complete rounds in a row that add no new
  qualified work (``policy.py``), and a work first appears in some round, so at least one more
  round before them: ``1 + consecutive_zero_yield_rounds`` closed rounds.
* A round is complete only when every planned query ran on every backend (``rounds.py``), so one
  round costs ``planned_query_count * backend_count`` search attempts.
* Every closest work needs a references and a cited-by expansion (``policy.py``), one attempt each:
  ``2 * closest_min_verified`` attempts, counted once because expansions are not repeated per round.
"""


def _count(value, name, minimum):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def minimum_requirement(*, planned_query_count, backend_count, stop_policy):
    """Return the least rounds and search attempts the coverage gate can need."""
    planned = _count(planned_query_count, "planned_query_count", 1)
    backends = _count(backend_count, "backend_count", 1)
    zero_rounds = _count(
        stop_policy["consecutive_zero_yield_rounds"],
        "consecutive_zero_yield_rounds",
        1,
    )
    closest = _count(stop_policy["closest_min_verified"], "closest_min_verified", 0)
    rounds = 1 + zero_rounds
    per_round = planned * backends
    expansions = 2 * closest
    return dict(
        min_closed_rounds=rounds,
        searches_per_round=per_round,
        expansions_min=expansions,
        min_search_attempts=rounds * per_round + expansions,
        plan_max_rounds=_count(stop_policy["max_rounds"], "max_rounds", 1),
    )


PROBE_SECONDS = 30  # one runtime probe is reserved before the first search attempt


def compare_with_scope(
    requirement,
    *,
    approved_rounds,
    approved_search_attempts,
    approved_seconds,
    seconds_per_attempt,
):
    """Add the approved scope and whether it can reach the gate. Hint only, never a refusal.

    Every search attempt, expansions included, reserves ``seconds_per_attempt`` (the pin timeout
    plus a 30 s margin) and the probe reserves 30 s, so the reserved seconds can run out before the
    attempts do.
    """
    rounds = _count(approved_rounds, "approved_rounds", 0)
    attempts = _count(approved_search_attempts, "approved_search_attempts", 0)
    seconds = _count(approved_seconds, "approved_seconds", 0)
    per_attempt = _count(seconds_per_attempt, "seconds_per_attempt", 1)
    plan_rounds_too_small = (
        requirement["plan_max_rounds"] < requirement["min_closed_rounds"]
    )
    rounds_enough = (
        rounds >= requirement["min_closed_rounds"] and not plan_rounds_too_small
    )
    attempts_enough = attempts >= requirement["min_search_attempts"]
    min_seconds = PROBE_SECONDS + requirement["min_search_attempts"] * per_attempt
    seconds_enough = seconds >= min_seconds
    return dict(
        requirement,
        approved_rounds=rounds,
        approved_search_attempts=attempts,
        approved_seconds=seconds,
        min_reserved_seconds=min_seconds,
        plan_rounds_too_small=plan_rounds_too_small,
        rounds_enough=rounds_enough,
        search_attempts_enough=attempts_enough,
        seconds_enough=seconds_enough,
        can_reach_coverage_gate=rounds_enough and attempts_enough and seconds_enough,
    )
