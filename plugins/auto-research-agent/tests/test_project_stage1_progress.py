"""Authored shared-overview navigation; no runtime, files or model calls."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from research_workspace_native.project_stage1_progress import project_progress


def snapshot():
    project = dict(
        project_ref="p",
        project_id="project-p",
        revision=0,
        input_version=1,
        brief_sha256="a" * 64,
    )
    project.update(
        intake_report={"necessary_clarification_complete": True},
        plan={"manifest_sha256": "b" * 64},
    )
    ledger = dict(
        valid=True,
        state_sha256="c" * 64,
        pending_actions=[],
        counts=dict(queries=1, works=1, decisions=1, claims=1),
    )
    stage = dict(
        project_ref="p",
        revision=0,
        input_version=1,
        ledger=ledger,
        coverage_actions=dict(held=False, blockers=["unverified"], offers=[]),
        reading_registration=dict(
            kind="ProjectStage1ReadingRegistration",
            schema_version="1.0.0",
            **{
                key: project[key]
                for key in ("project_ref", "revision", "input_version", "brief_sha256")
            },
            ledger_state_sha256="c" * 64,
            status="ready",
            reason="reading-registration-ready",
            missing_works=[],
            required_work_count=1,
            registered_work_count=1,
            grants_execution=False,
        ),
    )
    return dict(project=project, models=None, model_offers=None, stage1=stage)


def models(value):
    result = {
        k: value["project"][k]
        for k in ("project_ref", "revision", "input_version", "brief_sha256")
    }
    return result | dict(active_jobs=[], blocking_unknown_count=0, unknown_count=0)


def offer():
    return dict(offer_ref="offer", offer_sha256="d" * 64)


class ProgressTests(unittest.TestCase):
    def test_scope_required_and_projection_leaves_snapshot_unchanged(self):
        value = snapshot()
        value["project"]["intake_report"]["necessary_clarification_complete"] = False
        before = deepcopy(value)
        result = project_progress(value)
        self.assertEqual(result["next_action"]["reason"], "scope-required")
        self.assertEqual(value, before)
        self.assertFalse(result["research_complete"])

    def test_typed_fresh_intake_scope_and_all_negative_guards(self):
        value = snapshot()
        value["project"].update(
            intake_report={"necessary_clarification_complete": False}, plan=None
        )
        value["stage1"].update(
            stage1_status="intake-not-ready",
            ledger=None,
            query_execution=dict(
                status="intake-prerequisite-required",
                refusal="project-query-intake-not-ready",
                execution_authorized=False,
                jobs=[],
            ),
        )
        before = deepcopy(value)
        result = project_progress(value)
        self.assertEqual(
            result["next_action"],
            dict(phase_id="scope", target="scope", reason="scope-required"),
        )
        self.assertEqual(value, before)
        self.assertFalse(result["research_complete"])
        negatives = [
            ("stage1", {"stage1_status": "stale-input"}),
            ("stage1", {"stage1_status": "owner-reopen-required"}),
            ("stage1", {"input_version": 2}),
            ("stage1", {"ledger": {}}),
            ("project", {"status": "execution-unknown"}),
            ("project", {"plan": {"manifest_sha256": "b" * 64}}),
            ("project", {"intake_report": {"necessary_clarification_complete": True}}),
            ("project", {"intake_report": {"necessary_clarification_complete": None}}),
            ("stage1", {"coverage_actions": {"held": True}}),
            ("stage1", {"coverage_actions": {"held": None}}),
            (
                "stage1",
                {"source_execution": {"jobs": [{"status": "execution-unknown"}]}},
            ),
            ("stage1", {"source_execution": {"jobs": [{"status": "running"}]}}),
        ]
        for query_change in (
            {"status": "unavailable-or-stale", "refusal": "query-binding-unavailable"},
            {
                "status": "unavailable-or-stale",
                "refusal": "project-query-version-archive-history-differs",
            },
            {
                "status": "unavailable-or-stale",
                "refusal": "project-resource-reservation-event-differs",
            },
            {
                "status": "unavailable-or-stale",
                "refusal": "project-resource-query-binding-differs",
            },
            {"refusal": "query-binding-unavailable"},
            {"refusal": None},
            {"execution_authorized": True},
            {"execution_authorized": 0},
            {"jobs": None},
            {"jobs": [{"status": "dispatching"}]},
            {"jobs": [{"status": "execution-unknown"}]},
            {"status": "execution-unknown"},
        ):
            query = deepcopy(value["stage1"]["query_execution"])
            query.update(query_change)
            negatives.append(("stage1", {"query_execution": query}))
        for component, change in negatives:
            with self.subTest(component=component, change=change):
                changed = deepcopy(value)
                changed[component].update(change)
                observed = deepcopy(changed)
                result = project_progress(changed)
                self.assertEqual(result["next_action"]["target"], "history")
                self.assertFalse(result["research_complete"])
                self.assertEqual(changed, observed)

    def test_actual_model_offer_envelope_enables_planning_only_when_bound(self):
        value = snapshot()
        value["project"]["plan"] = None
        row = offer() | dict(
            operation="plan-search",
            available=True,
            input_version=1,
            brief_sha256="a" * 64,
        )
        value["model_offers"] = dict(project_ref="p", revision=0, offers=[row])
        self.assertEqual(project_progress(value)["phases"][1]["status"], "available")
        row["available"] = "true"
        self.assertEqual(project_progress(value)["phases"][1]["status"], "required")
        value["model_offers"]["revision"] = False
        self.assertEqual(
            project_progress(value)["next_action"]["reason"], "stale-input"
        )

    def test_first_query_navigation_uses_actual_existing_offer(self):
        for field, reason in (
            ("authorization_offer", "query-permission-required"),
            ("bootstrap_offer", "query-bootstrap-required"),
            ("query_offer", "query-offered"),
        ):
            with self.subTest(field=field):
                value = snapshot()
                value["stage1"]["ledger"] = None
                value["stage1"]["query_execution"] = {field: offer(), "connected": True}
                self.assertEqual(
                    project_progress(value)["next_action"]["reason"], reason
                )

    def test_absent_runtime_and_known_owner_reopen_have_distinct_reasons(self):
        value = snapshot()
        value["stage1"]["ledger"] = None
        self.assertEqual(
            project_progress(value)["next_action"]["reason"], "query-unconnected"
        )
        value["stage1"]["stage1_status"] = "owner-reopen-required"
        self.assertEqual(
            project_progress(value)["next_action"]["reason"], "owner-reopen-required"
        )

    def test_active_or_uncertain_work_only_navigates_to_passive_recovery(self):
        for component, state, target in (
            ("model", "running", "native"),
            ("query", "dispatching", "history"),
            ("source", "execution-unknown", "history"),
        ):
            with self.subTest(component=component):
                value = snapshot()
                if component == "model":
                    value["models"] = models(value) | dict(
                        active_jobs=[dict(status=state)]
                    )
                else:
                    value["stage1"][component + "_execution"] = dict(
                        jobs={"j": dict(status=state)}
                    )
                self.assertEqual(
                    project_progress(value)["next_action"]["target"], target
                )

    def test_retired_unknown_does_not_hide_a_current_coverage_write_hold(self):
        value = snapshot()
        value["models"] = models(value) | dict(unknown_count=5)
        self.assertEqual(project_progress(value)["next_action"]["target"], "coverage")
        value["stage1"]["coverage_actions"]["held"] = True
        self.assertEqual(project_progress(value)["next_action"]["target"], "history")

    def test_bound_package_checkpoint_and_counts_never_accept_research(self):
        value = snapshot()
        stage = value["stage1"]
        stage["stage1_complete"] = True
        stage["checkpoint"] = dict(current=True)
        saved = dict(
            status="saved-evidence-validated",
            artifact_kind="Stage1ResearchDeliverable",
            artifact_ref="artifact",
            manifest_sha256="d" * 64,
            records_sha256="e" * 64,
            handoff_sha256="f" * 64,
            ledger_state_sha256="c" * 64,
            binding=dict(
                project_id="project-p", input_version=1, brief_sha256="a" * 64
            ),
        )
        stage["delivery"] = dict(canonical_package=saved)
        result = project_progress(value)
        self.assertFalse(result["research_complete"])
        self.assertEqual(result["phases"][4]["status"], "recorded")
        self.assertEqual(result["phases"][6]["status"], "partial")
        del saved["manifest_sha256"]
        self.assertEqual(project_progress(value)["next_action"]["target"], "history")
        self.assertEqual(project_progress(value)["phases"][6]["status"], "unknown")

    def test_malformed_boolean_counts_and_capability_flags_do_not_become_zero_or_true(
        self,
    ):
        value = snapshot()
        value["stage1"]["ledger"]["counts"]["works"] = False
        self.assertEqual(project_progress(value)["phases"][3]["status"], "unknown")
        self.assertEqual(project_progress(value)["next_action"]["target"], "history")
        value = snapshot()
        value["stage1"]["ledger"]["counts"]["claims"] = 0
        value["stage1"]["saved_records_connected"] = "true"
        value["stage1"]["reading_registration"].update(
            status="unconnected", required_work_count=None, registered_work_count=None
        )
        value["models"] = models(value) | dict(saved_reading_available=1)
        self.assertEqual(project_progress(value)["phases"][4]["status"], "unconnected")

    def test_unconnected_reading_does_not_skip_query_screening_or_saved_package_review(
        self,
    ):
        value = snapshot()
        stage = value["stage1"]
        stage["reading_registration"].update(
            status="unconnected", required_work_count=None, registered_work_count=None
        )
        stage["ledger"]["counts"].update(works=0, decisions=0, claims=0)
        self.assertEqual(project_progress(value)["next_action"]["target"], "query")
        stage["ledger"]["counts"]["works"] = 1
        self.assertEqual(project_progress(value)["next_action"]["target"], "screening")
        stage["delivery"] = dict(
            canonical_package=dict(
                status="saved-evidence-validated",
                artifact_kind="Stage1ResearchDeliverable",
                artifact_ref="artifact",
                manifest_sha256="d" * 64,
                records_sha256="e" * 64,
                handoff_sha256="f" * 64,
                ledger_state_sha256="c" * 64,
                binding=dict(
                    project_id="project-p", input_version=1, brief_sha256="a" * 64
                ),
            )
        )
        self.assertEqual(
            project_progress(value)["next_action"]["reason"],
            "package-saved-review-required",
        )

    def test_missing_registration_precedes_coverage_and_invalid_binding_is_held(self):
        value = snapshot()
        registration = value["stage1"]["reading_registration"]
        registration.update(
            status="missing",
            registered_work_count=0,
            missing_works=[
                dict(
                    work_ref="work",
                    version_id="version",
                    candidate_event_id="e000001",
                    decision_event_id="e000002",
                    reason="saved-reading-current-record-required",
                )
            ],
        )
        self.assertEqual(
            project_progress(value)["next_action"]["reason"],
            "reading-registration-required",
        )
        for update in (
            {"revision": 999},
            {"ledger_state_sha256": "0" * 64},
            {"grants_execution": True},
            {"registered_work_count": True},
        ):
            changed = deepcopy(value)
            changed["stage1"]["reading_registration"].update(update)
            self.assertEqual(
                project_progress(changed)["next_action"]["target"], "history"
            )

    def test_core_work_and_version_ids_are_not_limited_by_broker_offer_ref(self):
        value = snapshot()
        value["stage1"]["reading_registration"].update(
            status="missing",
            registered_work_count=0,
            missing_works=[
                dict(
                    work_ref="work-" + "x" * 200,
                    version_id="version-" + "y" * 200,
                    candidate_event_id="e000001",
                    decision_event_id="e000002",
                    reason="saved-reading-current-record-required",
                )
            ],
        )
        self.assertEqual(
            project_progress(value)["next_action"]["reason"],
            "reading-registration-required",
        )


if __name__ == "__main__":
    unittest.main()
