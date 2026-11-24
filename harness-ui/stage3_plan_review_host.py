"""Project the review and decision for the Host's current saved Stage 3 plan."""

from sqlite3 import Error as SQLiteError

from stage3_plan_review_readback import read_plan_review


_READ_ERRORS = (OSError, ValueError, TypeError, KeyError, RecursionError)


class Stage3PlanReviewReader:
    """Adapt a trusted Host index's exact-identity lookup to a public projection."""

    def __init__(self, lookup):
        if not callable(lookup):
            raise ValueError("trusted plan review lookup required")
        self._lookup = lookup

    def __call__(self, view, *, check_deadline=None):
        result = read_plan_review(view)
        identity = result["identity"]
        if identity is None:
            return dict(result, reason="stage3-saved-strict-plan-required")

        try:
            binding = self._lookup(dict(identity))
        except (*_READ_ERRORS, SQLiteError):
            return dict(
                result,
                readback_status="unavailable",
                reason="stage3-plan-review-index-unavailable",
            )
        if check_deadline:
            check_deadline()
        if binding is None:
            return dict(result, reason="stage3-plan-review-binding-unavailable")

        try:
            saved = read_plan_review(view, trusted_binding=binding)
        except _READ_ERRORS:
            return dict(
                result,
                readback_status="rejected",
                reason="stage3-plan-review-binding-rejected",
            )

        reason = None
        if saved["review"] is None:
            reason = "stage3-semantic-review-not-recorded"
        elif saved["decision"] is None:
            reason = "stage3-plan-decision-not-recorded"
        return dict(saved, reason=reason)
