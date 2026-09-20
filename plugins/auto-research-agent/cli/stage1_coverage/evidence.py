"""Version-bound coverage judgments, kept separate from source authentication."""

from .rounds import require
from stage1_ledger.bindings import claim_binding


IDENTITY_FIELDS = {"title", "authors", "year", "identifier", "version"}
TEXT_LEVELS = {"abstract", "full_text", "full-text", "primary_data_or_table"}


class EvidenceReplay:
    def __init__(self):
        self.candidates, self.decisions, self.claims, self.reviews = {}, {}, {}, {}
        self.source_imports = {}

    def observe(self, payload, plan):
        kind = payload["kind"]
        if kind == "CandidateRevision":
            self.candidates[payload["work_id"]] = payload
        elif kind == "DecisionEvent":
            self.decisions[payload["subject_id"]] = payload
        elif kind == "ClaimEvidence":
            self.claims[payload["event_id"]] = payload
        elif kind == "SourceImportStarted":
            self.source_imports[payload["event_id"]] = payload
        elif kind == "CoverageWorkReview":
            work = self.candidates.get(payload["work_id"])
            decision = self.decisions.get(payload["work_id"])
            require(plan and work and decision, "coverage-review-missing-context")
            require(
                work["event_id"] == payload["candidate_event_id"]
                and decision["event_id"] == payload["decision_event_id"]
                and decision["new_decision"] == "include",
                "coverage-review-stale-or-excluded",
            )
            require(
                payload["version_id"] in work["version_ids"], "coverage-review-version"
            )
            clusters = {c["cluster_id"] for c in plan["proposal"]["clusters"]}
            require(
                set(payload["cluster_claims"]) <= clusters,
                "coverage-review-unknown-cluster",
            )
            for claim_id in payload["cluster_claims"].values():
                self.check_claim(claim_id, payload, identity=False)
            require(
                set(payload["identity_claims"]) == IDENTITY_FIELDS,
                "identity-review-fields",
            )
            if payload["identity_status"] == "verified":
                require(
                    work["identity_status"] != "conflict",
                    "identity-review-unresolved-conflict",
                )
                require(
                    len(set(payload["identity_claims"].values())) == 5,
                    "identity-review-needs-each-field",
                )
                for claim_id in payload["identity_claims"].values():
                    self.check_claim(claim_id, payload, identity=True)
            else:
                for claim_id in payload["identity_claims"].values():
                    if claim_id is not None:
                        self.check_claim(claim_id, payload, identity=False)
            previous = self.reviews.get(payload["work_id"])
            require(
                payload["replaces_event_id"]
                == (previous["event_id"] if previous else None),
                "coverage-review-history",
            )
            self.reviews[payload["work_id"]] = payload

    def check_claim(self, claim_id, review, *, identity):
        claim = self.claims.get(claim_id)
        require(
            claim
            and claim["work_id"] == review["work_id"]
            and claim["version_id"] == review["version_id"],
            "coverage-review-claim-version",
        )
        claim_binding(claim, self.candidates, self.source_imports)
        require(
            claim["locator"]
            and claim["relation"] in {"supports", "partial"}
            and claim["evidence_level"] in TEXT_LEVELS,
            "coverage-review-needs-text-support",
        )
        if identity:
            require(
                claim["relation"] == "supports"
                and claim["evidence_level"] != "abstract",
                "identity-review-needs-primary-text",
            )

    def current(self):
        return {
            work: review
            for work, review in self.reviews.items()
            if self.candidates[work]["event_id"] == review["candidate_event_id"]
            and self.decisions[work]["event_id"] == review["decision_event_id"]
            and self.decisions[work]["new_decision"] == "include"
        }
