"""Append coverage actions to the existing ledger; never execute a network request."""

from stage1_ledger.store import Ledger
from stage1_ledger.journal import decode, mutation, contained
from .plan import validate_bundle
from .rounds import CoverageReplay, require


class CoverageLedger(Ledger):
    def coverage_state(self):
        state = CoverageReplay(self.manifest, self.read_ref)
        for row in self.events():
            state.observe(row["payload"])
        return state

    def _coverage_append(self, payload):
        state = self.coverage_state()
        state.observe(payload)
        return self.append(payload)

    @mutation
    def bind_plan(self, directory, *, backends, limit):
        require(self.coverage_state().plan is None, "plan-already-bound")
        report = validate_bundle(directory)
        require(report["valid"], "invalid-plan-bundle: " + "; ".join(report["errors"]))
        raw = contained(directory.resolve(), "coverage_plan.json").read_bytes()
        plan = decode(raw, "coverage plan")
        require(
            plan["proposal"]["topic"] == self.manifest["research_run"]["objective"],
            "plan-topic-mismatch",
        )
        require(not self.coverage_state().starts, "plan-must-precede-search")
        ref = self._save(raw, producer="stage1-plan", artifact_type="coverage-input")
        return self.append(
            dict(kind="CoveragePlanBound", plan_ref=ref, backends=backends, limit=limit)
        )

    @mutation
    def open_round(self):
        state = self.coverage_state()
        return self._coverage_append(
            dict(kind="CoverageRoundOpened", round_number=len(state.closed) + 1)
        )

    def start_planned(self, planned_id):
        return self.start("search", self.coverage_state().arguments(planned_id))

    def start_expansion(self, operation, work_id, version_id):
        return self.start(
            "search",
            self.coverage_state().expansion_arguments(operation, work_id, version_id),
        )

    @mutation
    def review_work(
        self,
        *,
        work_id,
        version_id,
        cluster_claims,
        identity_status,
        identity_claims,
        closest,
        assessor,
        rationale,
    ):
        evidence = self.coverage_state().evidence
        require(
            work_id in evidence.candidates and work_id in evidence.decisions,
            "coverage-review-missing-context",
        )
        previous = evidence.reviews.get(work_id)
        return self._coverage_append(
            dict(
                kind="CoverageWorkReview",
                work_id=work_id,
                version_id=version_id,
                candidate_event_id=evidence.candidates[work_id]["event_id"],
                decision_event_id=evidence.decisions[work_id]["event_id"],
                cluster_claims=cluster_claims,
                identity_status=identity_status,
                identity_claims=identity_claims,
                closest=closest,
                assessor=assessor,
                rationale=rationale,
                scope="reviewer-attestation",
                replaces_event_id=previous["event_id"] if previous else None,
            )
        )

    @mutation
    def receipt(self, query_event_id, *, truncated, note):
        state = self.coverage_state()
        previous = state.receipts.get(query_event_id)
        return self._coverage_append(
            dict(
                kind="CoverageReceipt",
                query_event_id=query_event_id,
                truncated=truncated,
                note=note,
                replaces_event_id=previous["event_id"] if previous else None,
            )
        )

    @mutation
    def close_round(self):
        state = self.coverage_state()
        return self._coverage_append(
            dict(
                kind="CoverageRoundClosed",
                round_number=state.active,
                summary=state.summary(),
            )
        )

    @mutation
    def human_action(
        self, *, action, actor, user_input, reviewed_state_sha256, cluster_id=None
    ):
        from stage1_ledger.validation import validate_run

        require(validate_run(self.root)["valid"], "invalid-reviewed-state")
        return self._coverage_append(
            dict(
                kind="CoverageHumanAction",
                action=action,
                actor=actor,
                user_input=user_input,
                reviewed_state_sha256=reviewed_state_sha256,
                cluster_id=cluster_id,
            )
        )
