"""Real Core pending events through authenticated run-derived intake actions."""

import unittest
from unittest.mock import patch

from research_workspace_native.project_agent_pending import initialize_pending
from research_workspace_native.project_run_authority import action_identity
from research_workspace_native.project_stage1 import ProjectStage1Service
from research_workspace_native.session_api import SessionApiError
from stage1_coverage.run import CoverageLedger
from stage1_ledger.journal import canonical
from stage1_ledger.validation import validate_run
import test_project_stage1_run_grant as fixture
from test_workspace_project_intake import bound_body


class AgentPendingTests(unittest.TestCase):
    body = fixture.RunGrantTests.body
    authorize = fixture.RunGrantTests.authorize

    def setUp(self):
        fixture.RunGrantTests.setUp(self)
        self.stage = ProjectStage1Service(self.intake)
        binding = self.intake.binding(self.ref)
        offer = self.stage._init_offer(binding)
        self.stage.initialize(
            "alice-token",
            self.ref,
            {
                **bound_body(self.intake.read("alice-token", self.ref), "init"),
                "confirmed": True,
                "offer_ref": offer["offer_ref"],
                "offer_sha256": offer["offer_sha256"],
            },
        )
        state = self.intake._load("alice", self.ref)
        _, self.ledger, _ = self.stage._ledger(state, binding)
        coverage = self.ledger.coverage_state()
        planned = next(iter(coverage.queries))
        query = self.ledger.start_planned(planned)
        backend = self.ledger.start(
            "backend",
            {"input": coverage.arguments(planned)},
            backend="openalex",
            parent_id=query,
        )
        output = self.ledger.save_bytes(
            canonical(
                [
                    dict(
                        title=f"Synthetic unassessed study {n}",
                        authors=["Fixture"],
                        year=2025,
                        version="v1",
                    )
                    for n in range(2)
                ]
            ),
            producer=backend,
        )
        empty = self.ledger.save_bytes(b"", producer=backend)
        self.ledger.finish(
            backend,
            outcome="success_nonempty",
            http_status=200,
            exit_code=0,
            stdout=empty,
            stderr=empty,
            records=output,
        )
        self.ledger.complete_query(query)
        self.ledger.extract()
        self.works = list(self.ledger.candidates())
        self.grant = self.authorize()

    def request(self):
        body = {
            **bound_body(self.intake.read("alice-token", self.ref), "draft"),
            "confirmed": False,
            "ledger_state_sha256": self.ledger.state_hash(),
            "work_refs": self.works,
        }
        token = self.service.derive(
            "alice-token",
            self.ref,
            grant_ref=self.grant["grant_ref"],
            grant_sha256=self.grant["grant_sha256"],
            operation="agent-adoption",
            identity=action_identity("stage1-agent-pending", body),
        )
        body.update(
            key=token.key + "-work",
            revision=self.intake.read("alice-token", self.ref)["revision"],
        )
        return body, token

    def test_grouped_pending_is_agent_only_and_same_key_never_appends_twice(self):
        body, token = self.request()
        result = initialize_pending(
            self.stage, "alice-token", self.ref, body, run_authorization=token
        )
        self.assertEqual(result["included_count"], 0)
        self.assertEqual(len(result["work_decision_events"]), 2)
        count = len(self.ledger.events())
        repeated = initialize_pending(
            self.stage, "alice-token", self.ref, body, run_authorization=token
        )
        self.assertTrue(repeated["replayed"])
        self.assertEqual(len(self.ledger.events()), count)
        decisions = [
            r["payload"]
            for r in self.ledger.events()
            if r["payload"]["kind"] == "DecisionEvent"
        ]
        self.assertTrue(
            all(
                e["actor_type"] == "agent"
                and e["authorization"] is None
                and e["new_decision"] == "pending"
                for e in decisions
            )
        )
        self.assertTrue(validate_run(self.ledger.root)["valid"])

    def test_json_proof_and_cross_principal_refuse_before_ledger_write(self):
        body, token = self.request()
        count = len(self.ledger.events())
        for credential, proof in (("bob-token", token), ("alice-token", {})):
            with self.assertRaises(SessionApiError):
                initialize_pending(
                    self.stage, credential, self.ref, body, run_authorization=proof
                )
        self.assertEqual(len(self.ledger.events()), count)

    def test_partial_core_append_stays_unknown_and_blocks_other_mutations(self):
        body, token = self.request()
        original = CoverageLedger.decide

        def interrupted(ledger, *args, **kw):
            original(ledger, *args, **kw)
            raise SessionApiError("synthetic-after-first-core-append")

        with (
            patch.object(CoverageLedger, "decide", new=interrupted),
            self.assertRaises(SessionApiError),
        ):
            initialize_pending(
                self.stage, "alice-token", self.ref, body, run_authorization=token
            )
        receipt = self.intake.action("alice-token", body["key"], project_ref=self.ref)
        self.assertEqual(receipt["status"], "execution-unknown")
        self.assertEqual(receipt["failure_phase"], "core-write-outcome-unobserved")
        count = len(self.ledger.events())
        with self.assertRaises(SessionApiError):
            self.stage.checkpoint(
                "alice-token",
                self.ref,
                {
                    **bound_body(
                        self.intake.read("alice-token", self.ref), "after-unknown"
                    ),
                    "confirmed": True,
                    "ledger_state_sha256": self.ledger.state_hash(),
                },
            )
        self.assertEqual(len(self.ledger.events()), count)


if __name__ == "__main__":
    unittest.main()
