"""Keep saved reading replays bound to the trusted offline source owner."""

import json

from .project_reading_review import ProjectReadingReviewService
from .project_saved_claims import ProjectSavedClaimService
from .session_api import _check


def check_replay(owner, credential, ref, body, kind):
    """Before an existing service's early return, validate current provenance.

    Historical receipts remain unchanged and available through action history.
    An absent/unknown provenance is not adopted by the currently loaded config.
    The caller holds the intake lock through this check and the original action.
    """
    principal = owner.intake._principal(credential)
    context = owner._context(principal, ref)
    if type(body) is not dict or type(body.get("key")) is not str:
        return
    row = owner.intake.db.execute(
        "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
        (principal, ref, body["key"]),
    ).fetchone()
    if row is None:
        return
    receipt = json.loads(row[0])
    _check(receipt["kind"] == kind, "idempotency-payload-differs")
    records = owner.records
    saved_context = records._context(ref, context[3].state_hash())
    entries = records._entries(saved_context)
    if kind == "stage1-reading-registry":
        entry = receipt.get("registry_entry")
        _check(
            type(entry) is dict and entry in entries,
            "offline-reading-configuration-differs",
        )
    else:
        signature = receipt.get("saved_source_claim", {})
        _check(
            any(
                entry["ref"].startswith("stage1-source-registry-")
                and entry["payload"]["source_id"] == signature.get("source_id")
                for entry in entries
            ),
            "offline-claim-configuration-differs",
        )


class OfflineSavedClaims(ProjectSavedClaimService):
    def claim(self, credential, ref, body, *, check_deadline=None):
        with self.intake._lock:
            check_replay(self.records.owner, credential, ref, body, "stage1-claim")
            return super().claim(credential, ref, body, check_deadline=check_deadline)


class OfflineReadingReview(ProjectReadingReviewService):
    def review(self, credential, ref, body, *, check_deadline=None):
        with self.intake._lock:
            check_replay(
                self.records.owner, credential, ref, body, "stage1-reading-registry"
            )
            return super().review(credential, ref, body, check_deadline=check_deadline)
