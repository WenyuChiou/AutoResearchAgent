"""Pure navigation cases only; no native, provider, authority or research evidence."""

from copy import deepcopy
import unittest
from research_workspace_native.project_stage1_run_continuation import (
    round_query_progress,
)


class RoundQueryProgressTests(unittest.TestCase):
    def test_actual_owner_coverage_actions_forward_receipt_close_and_open(self):
        from types import SimpleNamespace
        import test_project_stage1_coverage as fixture
        from research_workspace_native.project_stage1_run_continuation import (
            ProjectStage1RunContinuation,
        )

        base = fixture.ProjectCoverageTests()
        base.setUp()
        try:
            adapter = object.__new__(ProjectStage1RunContinuation)
            selected = []

            def prepare(snapshot, operation, body):
                selected.append((operation, body))
                return body

            adapter.selection = None
            adapter.actions = SimpleNamespace(prepare=prepare)
            snapshot = SimpleNamespace(
                progress={"next_action": {"phase_id": "coverage"}}
            )

            def select(operation):
                view = base.case.service.read("alice-token", base.ref)
                self.assertIn("coverage_actions", view)
                adapter.overview = {"stage1": view}
                history = base.case.intake.history("alice-token", base.ref)
                result = adapter.next_action(snapshot)
                self.assertIsNotNone(result)
                self.assertEqual(result["operation"], operation)
                self.assertEqual(selected[-1][0], "round")
                self.assertEqual(
                    base.case.intake.history("alice-token", base.ref), history
                )
                self.assertIn(
                    result["offer_ref"],
                    [o["offer_ref"] for o in view["coverage_actions"]["offers"]],
                )
                return result

            for planned in base.ledger.coverage_state().queries:
                event = base.observe(planned)
                body = select("receipt")
                self.assertIsNone(body["review"]["truncated"])
                base.submit("receipt", body["review"], event)
            select("close-round")
            base.submit("close-round", {})
            select("open-round")
            self.assertFalse(any(o[0] == "human-action" for o in selected))
        finally:
            base.doCleanups()

    def test_current_open_round_target_is_selected_without_mutating_progress(self):
        progress = dict(
            phases=[
                dict(phase_id="query", status="partial", reason="query-recorded"),
                dict(
                    phase_id="coverage", status="available", reason="coverage-required"
                ),
            ],
            next_action=dict(
                phase_id="coverage", target="coverage", reason="coverage-required"
            ),
        )
        before = deepcopy(progress)
        actual = round_query_progress(
            progress,
            dict(active_round=2, offers=[]),
            dict(document=dict(round_number=2)),
            None,
        )
        self.assertEqual(
            actual["next_action"],
            dict(phase_id="query", target="query", reason="query-offered"),
        )
        self.assertEqual(progress, before)
        for change in (
            dict(active_round=None, offers=[]),
            dict(active_round=1, offers=[]),
            dict(
                active_round=2,
                offers=[dict(operation="receipt", document=dict(current_receipt=None))],
            ),
        ):
            self.assertEqual(
                round_query_progress(
                    progress, change, dict(document=dict(round_number=2)), None
                ),
                before,
            )
        self.assertEqual(
            round_query_progress(
                progress,
                dict(active_round=2, offers=[]),
                dict(document=dict(round_number=2)),
                dict(operation="coverage-review"),
            ),
            before,
        )

    def test_holds_and_other_phases_cannot_be_redirected_by_a_query_offer(self):
        for phase in ("scope", "planning", "query", "screening", "reading", "delivery"):
            progress = dict(
                phases=[
                    dict(
                        phase_id="coverage",
                        status="available",
                        reason="coverage-required",
                    )
                ],
                next_action=dict(
                    phase_id=phase, target="history", reason="existing-barrier"
                ),
            )
            self.assertEqual(
                round_query_progress(
                    progress,
                    dict(active_round=1, offers=[]),
                    dict(document=dict(round_number=1)),
                    None,
                ),
                progress,
            )
        progress = dict(
            phases=[
                dict(phase_id="reading", status="held", reason="execution-unknown")
            ],
            next_action=dict(
                phase_id="coverage", target="history", reason="existing-barrier"
            ),
        )
        self.assertEqual(
            round_query_progress(
                progress,
                dict(active_round=1, offers=[]),
                dict(document=dict(round_number=1)),
                None,
            ),
            progress,
        )


if __name__ == "__main__":
    unittest.main()
