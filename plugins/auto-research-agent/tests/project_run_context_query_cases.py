"""Run the actual query-owned controller with a local authored backend."""

from pathlib import Path

import project_stage1_query_cases as fixture
from research_workspace_native.project_run_context import validate_run_context
from research_workspace_native.project_stage1_delivery import (
    ProjectStage1DeliveryService,
)
from test_workspace_project_intake import bound_body


class QueryRunContextCase(fixture.ProjectQueryCases):
    def test_actual_query_owned_delivery_keeps_original_core_identity_and_resources(
        self,
    ):
        self.authorize()
        self.bootstrap()
        with self.fake_runner(), self.no_probe():
            queued = self.queries.execute(
                "alice-token", self.ref, self.body("query_offer", "query")
            )
            self.queries.services[self.ref]._workers[self.ref].join(30)
        service = self.queries.services[self.ref]
        action = service.get_action("alice-token", self.ref, queued["query_action_key"])
        self.assertEqual(action["status"], "completed", action)
        view = self.stage1.read("alice-token", self.ref)
        checkpoint = self.stage1.checkpoint(
            "alice-token",
            self.ref,
            dict(
                bound_body(self.intake.read("alice-token", self.ref), "checkpoint"),
                ledger_state_sha256=view["ledger"]["state_sha256"],
                confirmed=True,
            ),
        )
        delivery = ProjectStage1DeliveryService(self.stage1)
        materials = self.root / "reading-materials"
        materials.mkdir()
        records = self.queries.create_records_service(
            delivery, materials_root=materials
        )
        offer = records.produce_records(
            self.ref,
            expected_ledger_state_sha256=checkpoint["ledger_state_sha256"],
            expected_checkpoint_event_id=checkpoint["checkpoint_event_id"],
        )
        body = dict(
            bound_body(self.intake.read("alice-token", self.ref), "deliver"),
            ledger_state_sha256=checkpoint["ledger_state_sha256"],
            offer_ref=offer["offer_ref"],
            offer_sha256=offer["offer_sha256"],
            confirmed=True,
        )
        children = len(self.children)
        before = self.queries.read("alice-token", self.ref)["budget"]
        with self.no_probe():
            result = delivery.deliver("alice-token", self.ref, body)
            binding = delivery.binding(self.ref)
            root = Path(binding["deliverable_dir"])
            companion = root.with_name(root.name + "-context")
            report = validate_run_context(
                companion, result["run_context"]["manifest_sha256"]
            )
        self.assertEqual(result["status"], "saved")
        self.assertTrue(report["binding"]["run_ref"].startswith("stage1-live-"))
        self.assertEqual(self.queries.read("alice-token", self.ref)["budget"], before)
        self.assertEqual(len(self.children), children)
        self.assertFalse(result["stage1_complete"])
