"""Source-bound researcher intake and isolated query permit are mandatory."""

import atlas_test_paths  # noqa: F401
import json
from stage1_brief.formal_target import formal_target_state
from research_workspace_native.planned_query_contract import inspect_registration
from research_workspace_native.session_api import SessionApiError
from planned_query_fixture import QueryCase


class PlannedQueryContractTests(QueryCase):
    def test_researcher_explicit_formal_target_is_not_replaced_with_a_default(self):
        item, permit, state, pin = inspect_registration("case", self.item)
        self.assertEqual(
            formal_target_state(json.loads(self.brief.read_bytes()))["target"], 37
        )
        self.assertEqual(item["input_version"], "1" * 64)
        self.assertEqual(permit["max_results"], 3)
        self.assertEqual(state.binding["backends"], ["openalex"])
        self.assertEqual(pin["timeout_seconds"], 2)

    def test_native_text_permission_cannot_substitute_for_research_permission(self):
        self.permit["kind"] = "NativeTextPermit"
        self.write_permit()
        with self.assertRaisesRegex(SessionApiError, "research-permit-differs"):
            inspect_registration("case", self.item)
        self.assertFalse((self.root / "query.sqlite3").exists())

    def test_immutable_parent_drift_rejected_before_any_budget_or_execution(self):
        (self.parent_ledger / "coverage_and_stop.md").write_bytes(b"changed")
        with self.assertRaisesRegex(SessionApiError, "parent-source-differs"):
            inspect_registration("case", self.item)
        self.assertEqual(self.children, [])
        self.assertFalse((self.root / "query.sqlite3.created").exists())
