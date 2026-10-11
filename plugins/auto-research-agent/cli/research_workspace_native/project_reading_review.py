"""Human-confirmed saved reading annotations; no Core/model/search execution."""

from copy import deepcopy
import json

from stage1_deliverable.common import canonical, sha
from .project_intake_contract import identifier
from .project_stage1_claims import ProjectStage1ClaimService
from .session_api import _check, _hash

FIELDS = {
    "key",
    "revision",
    "input_version",
    "brief_sha256",
    "ledger_state_sha256",
    "output_ref",
    "draft_sha256",
    "offer_ref",
    "offer_sha256",
    "review",
    "confirmed",
}
KIND = "stage1-reading-registry"


class ProjectReadingReviewService:
    def __init__(self, claims):
        _check(
            isinstance(claims, ProjectStage1ClaimService),
            "saved-reading-claims-service-required",
        )
        self.claims, self.records, self.intake = claims, claims.records, claims.intake

    @staticmethod
    def offer(view):
        bound = {
            name: view[name]
            for name in (
                "project_ref",
                "input_version",
                "brief_sha256",
                "ledger_state_sha256",
                "output_ref",
                "draft_sha256",
                "work_id",
                "version_id",
            )
        }
        digest = sha(canonical(dict(bound, operation="human-reading-review")))
        return dict(
            offer_ref="reading-" + digest[:32],
            offer_sha256=digest,
            grants_execution=False,
            stage1_complete=False,
        )

    def view(self, credential, ref, output_ref, *, check_deadline=None):
        view = self.claims.view(
            credential, ref, output_ref, check_deadline=check_deadline
        )
        view["reading_review_offer"] = self.offer(view)
        return view

    def review(self, credential, ref, body, *, check_deadline=None):
        actor = self.intake._principal(credential)
        _check(
            type(body) is dict and set(body) == FIELDS and body["confirmed"] is True,
            "reading-review-fields",
            400,
        )
        identifier(body["key"])
        _check(
            type(body["revision"]) is int
            and type(body["input_version"]) is int
            and all(
                _hash(body[name])
                for name in (
                    "brief_sha256",
                    "ledger_state_sha256",
                    "output_ref",
                    "draft_sha256",
                    "offer_sha256",
                )
            ),
            "reading-review-identity",
            400,
        )
        _check(
            type(body["review"]) is dict
            and set(body["review"]) == {"classification", "findings", "roles"},
            "reading-review-content-fields",
            400,
        )
        _check(len(canonical(body)) <= 256 * 1024, "reading-review-bound-exceeded", 400)
        with self.intake._lock:
            state = self.intake._load(actor, ref)
            saved = self.intake.db.execute(
                "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                (actor, ref, body["key"]),
            ).fetchone()
            semantic = {
                name: value for name, value in body.items() if name != "revision"
            }
            if saved:
                receipt = json.loads(saved["receipt"])
                original = dict(receipt["request"])
                original.pop("entry_sha256", None)
                _check(
                    receipt["kind"] == KIND
                    and original == semantic
                    and saved["request_hash"]
                    == receipt["request_sha256"]
                    == sha(canonical(dict(kind=KIND, body=receipt["request"]))),
                    "idempotency-payload-differs",
                )
                return self.intake._receipt(receipt, replayed=True)
            _check(
                body["revision"] == state["revision"]
                and body["input_version"] == state["input_version"]
                and body["brief_sha256"] == self.intake.binding(ref)["brief_sha256"],
                "reading-review-source-version-stale",
            )
            history = self.intake.db.execute(
                "SELECT receipt FROM intake_actions WHERE principal=? AND project=?",
                (actor, ref),
            ).fetchall()
            _check(
                not any(
                    (row := json.loads(raw[0]))["kind"] == KIND
                    and row["status"] in {"intent-recorded", "execution-unknown"}
                    for raw in history
                ),
                "reading-review-unresolved",
            )
            if check_deadline is not None:
                check_deadline()
            self.claims._idle(credential, ref)
            view, snapshot = self.claims._view(
                actor, ref, state, body["output_ref"], check_deadline
            )
            offer = self.offer(view)
            _check(
                body["draft_sha256"] == view["draft_sha256"]
                and body["ledger_state_sha256"] == view["ledger_state_sha256"]
                and body["offer_ref"] == offer["offer_ref"]
                and body["offer_sha256"] == offer["offer_sha256"],
                "reading-review-offer-differs",
            )
            reading = self.records.derive_reading_payload(
                ref,
                view["work_id"],
                **deepcopy(body["review"]),
                expected_ledger_state_sha256=body["ledger_state_sha256"],
            )

            def check_current():
                if check_deadline is not None:
                    check_deadline()
                # Recheck the captured durable job and both raw draft files.
                # The immutable snapshot avoids recursive owner-frontier reads
                # while the records service holds its own saved-action guard.
                self.claims._draft(
                    actor, ref, state, body["output_ref"], check_deadline, snapshot
                )
                if check_deadline is not None:
                    check_deadline()

            self.records.register_reading(
                ref,
                reading=reading,
                expected_ledger_state_sha256=body["ledger_state_sha256"],
                action_body=body,
                check_current=check_current,
            )
            observed = self.intake.db.execute(
                "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                (actor, ref, body["key"]),
            ).fetchone()
            _check(observed is not None, "reading-review-receipt-unobserved")
            result = self.intake._receipt(json.loads(observed[0]))
            _check(result["status"] == "saved", "reading-review-save-unobserved")
            return result
