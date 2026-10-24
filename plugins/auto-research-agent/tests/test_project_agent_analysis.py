"""Real queue/Core/SQLite saved analysis adoption; provider and HTTP are synthetic."""

import unittest
from contextlib import contextmanager
from unittest.mock import patch

from analysis_run_fixture import LONG_QUOTE, analysis_proposal, analysis_run_fixture
from research_workspace_native.project_agent_analysis import (
    ProjectStage1AnalysisService,
)
from research_workspace_native.project_model import _output_ref
from research_workspace_native.session_api import SessionApiError
from stage1_coverage.run import CoverageLedger
from stage1_deliverable.records import CLASSIFICATION, FINDINGS
from stage1_ledger.validation import validate_run
from test_workspace_project_intake import bound_body


@contextmanager
def agent_analysis_run(**kwargs):
    with analysis_run_fixture(**kwargs) as run:
        run.service = ProjectStage1AnalysisService(
            run.case.delivery.stage1, run.model, run.case.producer
        )
        yield run


class AgentAnalysisTests(unittest.TestCase):
    def _assert_preflight_refusal(self, run):
        body, token = run.derived(
            "stage1-agent-analysis",
            "agent-adoption",
            dict(
                output_ref=_output_ref(run.job),
                draft_sha256=run.job["analysis_draft"]["sha256"],
            ),
        )
        before_events = run.ledger.events()
        before_claims = {
            event["payload"]["event_id"]
            for event in before_events
            if event["payload"]["kind"] == "ClaimEvidence"
        }
        before_reservations = run.model.read("alice-token", run.ref)["calls_reserved"]
        before_dispatches = len(run.calls)
        with self.assertRaises(SessionApiError):
            run.service.adopt("alice-token", run.ref, body, run_authorization=token)
        self.assertEqual(run.ledger.events(), before_events)
        self.assertEqual(
            {
                event["payload"]["event_id"]
                for event in run.ledger.events()
                if event["payload"]["kind"] == "ClaimEvidence"
            },
            before_claims,
        )
        with self.assertRaises(SessionApiError):
            run.case.intake.action("alice-token", body["key"], project_ref=run.ref)
        self.assertEqual(
            run.model.read("alice-token", run.ref)["calls_reserved"],
            before_reservations,
        )
        self.assertEqual(len(run.calls), before_dispatches)

    def test_actual_queue_agent_events_reading_registry_and_no_resend(self):
        with agent_analysis_run() as run:
            body, token = run.derived(
                "stage1-agent-analysis",
                "agent-adoption",
                dict(
                    output_ref=_output_ref(run.job),
                    draft_sha256=run.job["analysis_draft"]["sha256"],
                ),
            )
            before = len(run.ledger.events())
            old_claims = {
                event["payload"]["event_id"]
                for event in run.ledger.events()
                if event["payload"]["kind"] == "ClaimEvidence"
                and event["payload"]["work_id"] == run.work
            }
            for credential, proof in (("bob-token", token), ("alice-token", {})):
                with self.assertRaises(SessionApiError):
                    run.service.adopt(
                        credential, run.ref, body, run_authorization=proof
                    )
            self.assertEqual(len(run.ledger.events()), before)
            folder = run.model._runtime_folder("alice", run.ref, run.job)
            original = (folder / "output.txt").read_bytes()
            (folder / "output.txt").write_bytes(original + b" ")
            with self.assertRaises(SessionApiError):
                run.service.adopt("alice-token", run.ref, body, run_authorization=token)
            (folder / "output.txt").write_bytes(original)
            self.assertEqual(len(run.ledger.events()), before)
            result = run.service.adopt(
                "alice-token", run.ref, body, run_authorization=token
            )
            self.assertEqual(result["status"], "saved")
            self.assertTrue(
                old_claims
                <= {claim["claim_id"] for claim in result["reading"]["claims"]}
            )
            decision = run.ledger.event(result["decision_event_id"])
            self.assertEqual(
                (
                    decision["actor_type"],
                    decision["authorization"],
                    decision["new_decision"],
                ),
                ("agent", None, "pending"),
            )
            self.assertTrue(
                all(
                    row["producer"] != "analysis-agent"
                    for row in decision["evidence_refs"]
                )
            )
            for event in result["claim_event_ids"].values():
                self.assertEqual(
                    run.ledger.event(event)["verifier"]["actor_type"], "agent"
                )
                self.assertEqual(run.ledger.event(event)["relation"], "unclear")
            after = len(run.ledger.events())
            self.assertTrue(
                run.service.adopt(
                    "alice-token", run.ref, body, run_authorization=token
                )["replayed"]
            )
            self.assertEqual(len(run.ledger.events()), after)
            register_body, register_token = run.derived(
                "stage1-agent-reading",
                "records",
                dict(
                    adoption_key=body["key"],
                    adoption_request_sha256=result["request_sha256"],
                    reading_sha256=result["reading_sha256"],
                ),
            )
            registered = run.service.register(
                "alice-token",
                run.ref,
                register_body,
                run_authorization=register_token,
            )
            self.assertEqual(registered["registry_entry"]["payload"], result["reading"])
            self.assertEqual(
                run.service.register(
                    "alice-token",
                    run.ref,
                    register_body,
                    run_authorization=register_token,
                )["registry_entry"],
                registered["registry_entry"],
            )
            self.assertEqual(len(run.ledger.events()), after)
            self.assertFalse(registered["scientific_acceptance"])
            self.assertEqual(len(run.calls), 1)
            self.assertTrue(validate_run(run.ledger.root)["valid"])
            self.assertEqual(
                run.model.read("alice-token", run.ref)["calls_reserved"], 1
            )
            job2 = run.run_job(
                "analysis-2", "Analyze the updated authored fixture once."
            )
            adoption_body, adoption_token = run.derived(
                "stage1-agent-analysis",
                "agent-adoption",
                dict(
                    output_ref=_output_ref(job2),
                    draft_sha256=job2["analysis_draft"]["sha256"],
                ),
            )
            original_claim = CoverageLedger.claim

            def interrupted(owner, *args, **kwargs):
                original_claim(owner, *args, **kwargs)
                raise SessionApiError("synthetic-after-observed-agent-claim")

            count_before = len(run.ledger.events())
            with (
                patch.object(CoverageLedger, "claim", new=interrupted),
                self.assertRaises(SessionApiError),
            ):
                run.service.adopt(
                    "alice-token",
                    run.ref,
                    adoption_body,
                    run_authorization=adoption_token,
                )
            held = run.case.intake.action(
                "alice-token", adoption_body["key"], project_ref=run.ref
            )
            self.assertEqual(held["status"], "execution-unknown")
            self.assertEqual(held["failure_phase"], "core-write-outcome-unobserved")
            count_after = len(run.ledger.events())
            self.assertGreater(count_after, count_before)
            with self.assertRaises(SessionApiError):
                run.case.delivery.stage1.checkpoint(
                    "alice-token",
                    run.ref,
                    {
                        **bound_body(
                            run.case.intake.read("alice-token", run.ref),
                            "held-checkpoint",
                        ),
                        "confirmed": True,
                        "ledger_state_sha256": run.ledger.state_hash(),
                    },
                )
            self.assertEqual(len(run.ledger.events()), count_after)
            self.assertEqual(
                run.model.read("alice-token", run.ref)["calls_reserved"], 2
            )
            self.assertEqual(len(run.calls), 2)
            self.assertTrue(validate_run(run.ledger.root)["valid"])

    def test_control_character_reading_refuses_before_core_append(self):
        def proposal(context):
            classification = {key: "Unknown" for key in CLASSIFICATION}
            findings = {key: "Unknown" for key in FINDINGS}
            classification[next(iter(classification))] = "\x01"
            findings[next(iter(findings))] = "\x01"
            return analysis_proposal(
                context, classification=classification, findings=findings
            )

        with agent_analysis_run(proposal_builder=proposal) as run:
            self._assert_preflight_refusal(run)

    def test_expanded_reading_over_canonical_cap_refuses_before_core_append(self):
        def proposal(context):
            return analysis_proposal(context, quote=LONG_QUOTE, claim_count=32)

        with agent_analysis_run(proposal_builder=proposal, long_source=True) as run:
            self._assert_preflight_refusal(run)


if __name__ == "__main__":
    unittest.main()
