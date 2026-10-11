"""Coverage writes use the real saved owner; probes and external work are mocked."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

import planned_query_fixture
import project_stage1_query_cases as fixture
from planned_query_raw_runner import run_cases
from research_workspace_native.session_api import SessionApiError
from stage1_coverage.run import CoverageLedger
from test_workspace_project_intake import bound_body


class ProjectCoverageOwnedTests(unittest.TestCase):
    def setUp(self):
        self.case = None
        if planned_query_fixture.RAW_SOURCE_PROOF is None:
            return
        self.case = fixture.ProjectQueryCases()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.case.authorize()
        self.case.bootstrap()

    def raw_child(self):
        if self.case is not None:
            return False
        run_cases(
            "test_project_coverage_owned."
            + type(self).__name__
            + "."
            + self._testMethodName,
            self,
        )
        return True

    def request(self, key):
        case = self.case
        view = case.stage1.read("alice-token", case.ref)
        offer = next(
            row
            for row in view["coverage_actions"]["offers"]
            if row["operation"] == "close-round"
        )
        return dict(
            bound_body(case.intake.read("alice-token", case.ref), key),
            ledger_state_sha256=view["ledger"]["state_sha256"],
            operation="close-round",
            offer_ref=offer["offer_ref"],
            offer_sha256=offer["offer_sha256"],
            review={},
            confirmed=True,
        )

    def ledger(self):
        case = self.case
        state = case.intake._load("alice", case.ref)
        run = state["stage1_runs"][state["stage1_active"]]
        self.assertTrue(run["query_owned"])
        return CoverageLedger(case.intake._path(case.ref, run["path"]))

    def test_owned_coverage_commit_and_replay_preserve_query_budget(self):
        if self.raw_child():
            return
        case = self.case
        body = self.request("owned-coverage")
        ledger = self.ledger()
        owner = case.queries.services[case.ref]
        before_events = ledger.events()
        before_frontier = case.queries.saved_frontier(case.ref)
        before_query_budget = deepcopy(
            case.queries.read("alice-token", case.ref)["budget"]
        )
        before_owner_budget = deepcopy(owner.view("alice-token", case.ref)["budget"])

        with (
            patch.object(owner, "mutate_saved", wraps=owner.mutate_saved) as write,
            patch(
                "stage1_retrieval.runtime_identity.capture_identity",
                side_effect=AssertionError("coverage must not probe"),
            ),
            patch(
                "stage1_retrieval.runner.execute",
                side_effect=AssertionError("coverage must not execute a search"),
            ),
        ):
            result = case.stage1.coverage("alice-token", case.ref, body)
            self.assertEqual(result["status"], "saved")
            self.assertEqual(result["kind"], "stage1-coverage")
            self.assertFalse(result["stage1_complete"])
            self.assertFalse(result["grants_external_permission"])
            self.assertEqual(write.call_count, 1)
            self.assertEqual(write.call_args.args[5], "stage1-coverage")
            saved_state_hash = ledger.state_hash()
            with patch.object(
                CoverageLedger,
                "close_round",
                side_effect=AssertionError("same key must not repeat Core writes"),
            ):
                replay = case.stage1.coverage(
                    "alice-token", case.ref, {**body, "revision": 999}
                )
                self.assertTrue(replay["replayed"])
                self.assertEqual(replay["event_id"], result["event_id"])
                with self.assertRaisesRegex(SessionApiError, "idempotency"):
                    case.stage1.coverage(
                        "alice-token", case.ref, {**body, "review": {"changed": True}}
                    )
            self.assertEqual(write.call_count, 1)

        after_events = ledger.events()
        self.assertEqual(after_events[: len(before_events)], before_events)
        self.assertEqual(len(after_events), len(before_events) + 1)
        self.assertEqual(after_events[-1]["payload"]["kind"], "CoverageRoundClosed")
        self.assertEqual(after_events[-1]["payload"]["event_id"], result["event_id"])
        self.assertEqual(ledger.state_hash(), saved_state_hash)
        frontier = case.queries.saved_frontier(case.ref)
        self.assertEqual(frontier["state_sha256"], saved_state_hash)
        self.assertNotEqual(frontier["tree_sha256"], before_frontier["tree_sha256"])
        history = owner.view("alice-token", case.ref)["history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["status"], "completed")
        self.assertEqual(history[0]["outcome"], "observed")
        self.assertEqual(history[0]["request"]["operation"], "stage1-coverage")
        self.assertEqual(
            case.queries.read("alice-token", case.ref)["budget"], before_query_budget
        )
        self.assertEqual(
            owner.view("alice-token", case.ref)["budget"], before_owner_budget
        )
        self.assertEqual(case.children, [])
        from research_workspace_native.planned_query_contract import (
            inspect_registration,
        )

        item = owner._projects[case.ref]["item"]
        with self.assertRaisesRegex(SessionApiError, "query-bound-open-plan-required"):
            inspect_registration(case.ref, item)
        self.assertIsNone(
            inspect_registration(
                case.ref, item, require_ready=False, allow_closed=True
            )[2].active
        )
        self.assertEqual(
            case.stage1.read("alice-token", case.ref)["coverage_actions"][
                "active_round"
            ],
            None,
        )

    def test_closed_owner_refuses_coverage_before_intent_or_core_write(self):
        if self.raw_child():
            return
        case = self.case
        body = self.request("closed-owner-coverage")
        ledger = self.ledger()
        before_events = ledger.events()
        before_history = case.intake.history("alice-token", case.ref)["actions"]
        before_budget = deepcopy(
            case.intake._load("alice", case.ref)["stage1_query_budget"]
        )
        case.queries.close()
        with (
            patch.object(
                CoverageLedger,
                "close_round",
                side_effect=AssertionError("closed owner must not write Core"),
            ),
            patch(
                "stage1_retrieval.runtime_identity.capture_identity",
                side_effect=AssertionError("closed owner must not probe"),
            ),
            patch(
                "stage1_retrieval.runner.execute",
                side_effect=AssertionError("closed owner must not execute"),
            ),
            self.assertRaisesRegex(
                SessionApiError, "project-query-saved-owner-unavailable"
            ),
        ):
            case.stage1.coverage("alice-token", case.ref, body)
        self.assertEqual(ledger.events(), before_events)
        self.assertEqual(
            case.intake.history("alice-token", case.ref)["actions"], before_history
        )
        self.assertEqual(
            case.intake._load("alice", case.ref)["stage1_query_budget"], before_budget
        )
        self.assertEqual(case.children, [])

    def test_claim_kind_uses_owned_writer_and_preserves_pending_metadata(self):
        """Exercise the trusted saved-write wrapper, not model draft approval."""
        if self.raw_child():
            return
        from stage1_deliverable.common import canonical, sha

        case = self.case
        with case.fake_runner(), case.no_probe():
            queued = case.queries.execute(
                "alice-token", case.ref, case.body("query_offer", "claim-candidate")
            )
            owner = case.queries.services[case.ref]
            owner._workers[case.ref].join(30)
        self.assertFalse(owner._workers[case.ref].is_alive())
        self.assertEqual(
            owner.get_action("alice-token", case.ref, queued["query_action_key"])[
                "status"
            ],
            "completed",
        )
        ledger = self.ledger()
        work_id, candidate = next(iter(ledger.candidates().items()))
        version = candidate["version_ids"][0]
        source_ref = candidate["discoveries"][0]["source_ref"]
        args = dict(
            work_id=work_id,
            version_id=version,
            claim_text="Unknown: authored metadata awaits human source review.",
            relation="pending",
            evidence_level="metadata",
            locator=None,
            source_ref=source_ref,
            verifier=dict(actor="alice", actor_type="human", method="fixture-review"),
        )
        request = dict(
            bound_body(case.intake.read("alice-token", case.ref), "owned-claim"),
            ledger_state_sha256=ledger.state_hash(),
            confirmed=True,
            output_ref="synthetic-wrapper-output",
            draft_sha256=sha(canonical(args)),
            evidence_index=0,
            offer_ref="synthetic-wrapper-offer",
            offer_sha256=sha(canonical(args)),
            review=dict(
                claim_text=args["claim_text"],
                relation="pending",
                evidence_level="metadata",
                section="Unknown",
            ),
        )
        before = ledger.events()
        budget = deepcopy(owner.view("alice-token", case.ref)["budget"])
        child_count = len(case.children)

        def produce(_, run, owned, request_sha, actor):
            event = owned.claim(**args)
            return dict(
                claim_event_id=event,
                ledger_state_sha256=owned.state_hash(),
                scientific_acceptance=False,
                reading_registration=False,
            )

        def mutate(payload):
            return case.stage1._mutate(
                "alice-token",
                case.ref,
                payload,
                "stage1-claim",
                produce,
                fields={
                    "output_ref",
                    "draft_sha256",
                    "evidence_index",
                    "offer_ref",
                    "offer_sha256",
                    "review",
                },
                preflight=lambda *args: None,
            )

        with patch.object(owner, "mutate_saved", wraps=owner.mutate_saved) as write:
            result = mutate(request)
            self.assertEqual(result["status"], "saved")
            self.assertEqual(write.call_count, 1)
            self.assertEqual(write.call_args.args[5], "stage1-claim")
            with patch.object(
                CoverageLedger, "claim", side_effect=AssertionError("repeat")
            ):
                replay = mutate({**request, "revision": 999})
                self.assertTrue(replay["replayed"])
                self.assertEqual(replay["claim_event_id"], result["claim_event_id"])
            self.assertEqual(write.call_count, 1)
        self.assertEqual(ledger.events()[: len(before)], before)
        self.assertEqual(len(ledger.events()), len(before) + 1)
        claim = ledger.event(result["claim_event_id"], "ClaimEvidence")
        self.assertEqual(
            (claim["relation"], claim["evidence_level"]), ("pending", "metadata")
        )
        self.assertEqual(owner.view("alice-token", case.ref)["budget"], budget)
        self.assertEqual(len(case.children), child_count)
        self.assertFalse(result["scientific_acceptance"])

        fresh = dict(
            request,
            key="closed-owner-claim",
            revision=case.intake.read("alice-token", case.ref)["revision"],
            ledger_state_sha256=ledger.state_hash(),
        )
        history = case.intake.history("alice-token", case.ref)["actions"]
        case.queries.close()
        with self.assertRaisesRegex(
            SessionApiError, "project-query-saved-owner-unavailable"
        ):
            mutate(fresh)
        self.assertEqual(
            case.intake.history("alice-token", case.ref)["actions"], history
        )
        self.assertEqual(len(ledger.events()), len(before) + 1)


if __name__ == "__main__":
    unittest.main()
