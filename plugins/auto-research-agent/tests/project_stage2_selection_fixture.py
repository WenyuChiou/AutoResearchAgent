"""Synthetic activation and completed Stage2 package fixture.

All package/checker/SQLite producers run offline. No model, real science,
A/B, evaluation or actual user selection is performed.
"""

# ruff: noqa: E402 -- exercise repository package and authored fixtures.
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / "cli"),
    str(Path(__file__).resolve().parent),
]
import test_project_stage2 as activation_fixture
import test_stage2_delivery as delivery_fixture
from stage2_fixture_helpers import _candidate
from stage2_live.controller import materialize_snapshot_input_root
from stage2_common import canonical_hash
from stage2_workflow import add_snapshot, inspect_workflow
from stage2_workflow.orchestration import prepare_review_batch
from research_workspace_native.project_stage2_selection_view import (
    ProjectStage2SelectionView,
)


def evidence_refs(value, old, new):
    if isinstance(value, list):
        return [evidence_refs(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: evidence_refs(item, old, new) for key, item in value.items()}
    return new if value == old else value


class Stage2SelectionFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        activation_fixture.ProjectStage2Tests.setUpClass.__func__(cls)

    setUp = activation_fixture.ProjectStage2Tests.setUp
    body = activation_fixture.ProjectStage2Tests.body

    def prepare_choice(
        self, service_type=ProjectStage2SelectionView, *, packet_transform=None
    ):
        self.service.activate("own", self.ref, self.body())
        initial = self.service.binding(self.ref)
        workflow = Path(initial["workflow_root"])
        state = inspect_workflow(workflow)
        packet = deepcopy(state["latest_snapshot"]["packet"])
        evidence = packet["evidence"][0]["evidence_id"]
        packet["candidates"].append(_candidate("candidate-1", evidence_ids=[evidence]))
        packet["packet_id"] = "synthetic-active-choice"
        source_root = materialize_snapshot_input_root(
            state["latest_snapshot"], self.root / "source-view"
        )
        if packet_transform is not None:
            packet = packet_transform(packet, source_root)
        packet_path = self.root / "choice-packet.json"
        packet_path.write_text(json.dumps(packet), encoding="utf-8")
        add_snapshot(
            workflow,
            packet_path,
            source_root,
            "Synthetic offline candidate for activation E2E only",
            [
                {
                    "candidate_id": "candidate-1",
                    "status": "affected",
                    "reason": "Synthetic candidate",
                }
            ],
            state["head_sha256"],
        )
        state = inspect_workflow(workflow)
        self.service.advance_frontier(
            self.ref,
            key="synthetic-research-frontier",
            expected_activation_sha256=initial["activation_sha256"],
            expected_previous_head_sha256=initial["workflow_head_sha256"],
            new_workflow_head_sha256=state["head_sha256"],
        )
        f = delivery_fixture.Stage2DeliveryTests()
        f.packet, f.workflow, f.state = packet, workflow, state
        f.snapshot = state["latest_snapshot"]["event"]["payload"]["snapshot_sha256"]
        f.batch = prepare_review_batch(
            packet,
            f.snapshot,
            [
                {
                    "candidate_id": "candidate-1",
                    "candidate_version": 1,
                    "included": True,
                    "distance": 0,
                    "reason": "Synthetic candidate only",
                }
            ],
            "synthetic-active-seed",
        )
        reviews, resolutions = f._complete_inputs()
        reviews, resolutions = [
            evidence_refs(row, "ev-1", evidence) for row in [reviews, resolutions]
        ]
        resolutions["candidate_resolutions"][0]["resolution"]["review_sha256s"] = [
            canonical_hash(row["review"]) for row in reviews
        ]
        delivery = self.root / "choice-delivery"
        manifest = f._build(delivery, reviews, resolutions)
        project = self.intake.read("own", self.ref)
        ui = service_type(
            self.intake,
            {
                self.ref: {
                    "input_version": project["input_version"],
                    "brief_sha256": project["brief_sha256"],
                    "workflow_root": str(workflow),
                    "delivery_root": str(delivery),
                    "delivery_manifest_sha256": manifest["manifest_sha256"],
                }
            },
        )
        view = ui.read("own", self.ref)
        body = dict(
            key="synthetic-active-select",
            revision=view["revision"],
            input_version=view["input_version"],
            brief_sha256=view["brief_sha256"],
            delivery_manifest_sha256=view["delivery_manifest_sha256"],
            workflow_head_sha256=view["workflow_head_sha256"],
            snapshot_sha256=view["snapshot_sha256"],
            confirmed=True,
            decision=dict(
                actor="synthetic-ui-user",
                kind="select",
                user_text="Synthetic confirmation of displayed candidate for planning.",
                selected=view["eligible"],
                conditions=["Preserve limitations"],
                unresolved=["Access unknown"],
                rationale="Engineering fixture only",
                scope_or_resource_change=False,
            ),
        )
        return ui, body, workflow
