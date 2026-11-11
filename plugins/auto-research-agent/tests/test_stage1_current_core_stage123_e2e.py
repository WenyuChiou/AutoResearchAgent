"""Offline current Core to saved plan integration using authored responses."""

# ruff: noqa: E402 -- use repository packages and existing authored fixtures.
from contextlib import closing
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "cli"), str(HERE)]

from current_core_stage12_fixtures import current_core_stage1_case
from research_workspace_native.journal import Journal
from research_workspace_native.project_stage2 import ProjectStage2Service
from research_workspace_native.project_stage2_controller import (
    ProjectStage2ControllerDriver,
)
from research_workspace_native.project_stage2_selection import (
    ProjectStage2SelectionService,
)
from research_workspace_native.project_stage3_http import ProjectStage3Http
from research_workspace_native.project_stage3_planning import (
    ProjectStage3PlanningService,
)
from stage1_deliverable.common import read_json, sha
from stage2_common import canonical_hash
from stage2_fixture_helpers import _candidate
from stage2_workflow import inspect_workflow
from stage3_plan.contracts import canonical_bytes, digest
from stage3_plan.intake import admit_intake
from stage3_plan.jobs import POLICY, PlanningJobs
from test_project_stage123_controller_e2e import (
    RichSyntheticAdapter,
    SyntheticPreparation,
)
from test_project_stage3_planning import authored_plan
from test_stage2_controller import Stage2ControllerTests, SyntheticAdapter
from test_stage2_scientific_argument import argument


class CurrentCoreSyntheticAdapter(RichSyntheticAdapter):
    identity = "explicit-synthetic-current-core-choice-v1"

    def extract(self, context):
        result = SyntheticAdapter.extract(self, context)
        packet = result["next_packet"]["packet"]
        if packet["schema_version"] != "2.7.0":
            raise AssertionError("The current Core workflow must keep packet 2.7.")
        evidence = packet["evidence"][0]["evidence_id"]
        source = packet["sources"][0]
        candidate = _candidate("candidate-1", evidence_ids=[evidence])
        candidate["scientific_argument"] = argument(
            evidence,
            {key: source[key] for key in ("source_id", "work_id", "version_id")},
        )
        packet["candidates"].append(candidate)
        return result


class CurrentCoreStage123E2ETests(unittest.TestCase):
    def test_screened_core12_selection_saves_and_reopens_one_synthetic_plan(self):
        with current_core_stage1_case(screened=True) as fixture:
            intake, ref = fixture["case"].intake, fixture["project_ref"]
            root, credential = fixture["root"], "alice-token"
            original = intake.read(credential, ref)
            self.assertEqual(fixture["records"]["schema_version"], "1.2.0")
            resources = root / "native-resources.txt"
            resources.write_text(
                intake.binding(ref)["settings"]["resource_envelope"], encoding="utf-8"
            )
            service = ProjectStage2Service(intake)
            offer = service.register(
                ref,
                deliverable_dir=fixture["deliverable_dir"],
                expected_manifest_sha256=fixture["manifest_sha256"],
                handoff_path=fixture["handoff_path"],
                expected_handoff_sha256=fixture["handoff_sha256"],
                resources_path=resources,
                expected_resources_sha256=sha(resources.read_bytes()),
                policy_ref=dict(
                    route="stage2-general-v3/daily_v3",
                    execution_authorized=False,
                    packet_profile="scientific-v3",
                ),
            )
            project = intake.read(credential, ref)
            self.assertEqual(project["input_version"], original["input_version"])
            self.assertEqual(project["brief_sha256"], fixture["brief_sha256"])
            identity = {key: project[key] for key in ("input_version", "brief_sha256")}
            service.activate(
                credential,
                ref,
                dict(
                    key="synthetic-core-activate",
                    revision=project["revision"],
                    **identity,
                    offer_ref=offer["offer_ref"],
                    offer_sha256=offer["offer_sha256"],
                    confirmed=True,
                ),
            )
            binding = service.binding(ref)
            workflow = Path(binding["workflow_root"])
            snapshot = inspect_workflow(
                workflow, expected_head=binding["workflow_head_sha256"]
            )["latest_snapshot"]
            packet = snapshot["packet"]
            self.assertEqual(packet["schema_version"], "2.7.0")
            self.assertEqual(packet["core_source"]["records_version"], "1.2.0")
            self.assertEqual(canonical_hash(packet), binding["packet_sha256"])
            for packet_key, fixture_key in (
                ("stage1_records_sha256", "records_sha256"),
                ("stage1_deliverable_manifest_sha256", "manifest_sha256"),
                ("stage1_handoff_sha256", "handoff_sha256"),
            ):
                self.assertEqual(packet["upstream"][packet_key], fixture[fixture_key])

            preparation = SimpleNamespace(
                root=root,
                workflow=workflow,
                packet=packet,
                base=snapshot["event"]["payload"]["snapshot_sha256"],
            )
            preparation.spec = Stage2ControllerTests._spec(preparation)
            delivery = root / "delivery"
            driver = ProjectStage2ControllerDriver(
                service,
                spec=preparation.spec,
                controller_dir=root / "controller",
                delivery_dir=delivery,
                prerequisite_handler=SyntheticPreparation(preparation),
            )
            with patch(
                "stage2_live.controller._ProductionAdapter",
                return_value=CurrentCoreSyntheticAdapter(),
            ):
                generated = driver.run(credential, ref, key="synthetic-core-controller")
            self.assertEqual(generated["status"], "saved", generated)
            self.assertTrue(generated["controller"]["synthetic_test_only"])
            self.assertFalse(generated["execution_authorized"])
            final = inspect_workflow(
                workflow, expected_head=generated["controller"]["workflow_head_sha256"]
            )["latest_snapshot"]["packet"]
            self.assertEqual(final["schema_version"], "2.7.0")
            self.assertEqual(final["upstream"], packet["upstream"])
            self.assertEqual(final["core_source"], packet["core_source"])

            delivery_pin = read_json(delivery / "delivery_manifest.json")[
                "manifest_sha256"
            ]
            selection = ProjectStage2SelectionService(
                intake,
                {
                    ref: dict(
                        **identity,
                        workflow_root=str(workflow),
                        delivery_root=str(delivery),
                        delivery_manifest_sha256=delivery_pin,
                    )
                },
            )
            view = selection.read(credential, ref)
            self.assertEqual(len(view["eligible"]), 1, view)
            choice_body = {
                key: view[key]
                for key in (
                    "revision",
                    "input_version",
                    "brief_sha256",
                    "delivery_manifest_sha256",
                    "workflow_head_sha256",
                    "snapshot_sha256",
                )
            }
            choice_body.update(
                key="synthetic-core-select",
                confirmed=True,
                decision=dict(
                    actor="synthetic-user",
                    kind="select",
                    selected=view["eligible"],
                    user_text="Authored selection for the offline engineering test.",
                    conditions=["Keep the source limitations."],
                    unresolved=["Material access is unknown."],
                    rationale="Deterministic regression fixture.",
                    scope_or_resource_change=False,
                ),
            )
            selected = selection.select(credential, ref, choice_body)
            self.assertEqual(selected["status"], "saved", selected)
            self.assertEqual(selected["planning_status"], "verified")
            output = intake._path(ref, selected["artifact_ref"])
            submission = read_json(output / "submission.json")
            self.assertEqual(submission["project_ref"], ref)
            for key, expected in identity.items():
                self.assertEqual(submission[key], expected)
                self.assertIs(type(submission[key]), type(expected))
            self.assertEqual(submission["delivery_manifest_sha256"], delivery_pin)
            self.assertEqual(submission["decision"], choice_body["decision"])
            interaction = output / "interaction" / "interaction.json"
            interaction_before = interaction.read_bytes()
            self.assertEqual(
                sha(interaction_before), selected["interaction_file_sha256"]
            )
            replayed = selection.select(credential, ref, choice_body)
            self.assertEqual(replayed, dict(selected, replayed=True))
            self.assertEqual(interaction.read_bytes(), interaction_before)
            self.assertEqual(
                intake.db.execute(
                    "SELECT COUNT(*) FROM intake_actions WHERE project=? AND key=?",
                    (ref, choice_body["key"]),
                ).fetchone()[0],
                1,
            )

            pin = selected["planning_manifest_sha256"]
            admitted = admit_intake(
                output / "planning", delivery, expected_manifest_sha256=pin
            )
            self.assertEqual(len(admitted["questions"]), 1)
            self.assertEqual(admitted["legacy_candidates"], [])
            self.assertEqual(
                admitted["unresolved"], choice_body["decision"]["unresolved"]
            )
            with closing(Journal(root / "plan.sqlite")) as journal:
                project_id = project["project_id"]
                journal.bind_project(project_id, digest({"fixture": ref}))
                owner = journal.acquire_owner(project_id, "synthetic-host")
                jobs = PlanningJobs(
                    journal, project_id, owner, root / "plans", project_ref=ref
                )
                callback = Mock()
                callback.request_context = {
                    "kind": "fixed-callback",
                    "timeout_seconds": 5,
                }
                planning = ProjectStage3PlanningService(
                    intake,
                    selection,
                    bindings={
                        ref: dict(
                            jobs=jobs,
                            configuration={
                                "model": "fixture-model",
                                "reasoning": "medium",
                            },
                            callback=callback,
                        )
                    },
                )
                http = ProjectStage3Http(planning)
                try:
                    request = http.view(credential, ref)["default_request"]
                    for key, expected in identity.items():
                        self.assertEqual(request[key], expected)
                    self.assertEqual(
                        request["selection_request_sha256"], selected["request_sha256"]
                    )
                    plan = authored_plan(
                        admitted, pin, "host-plan-" + digest(request["key"])
                    )
                    callback.return_value = dict(
                        raw_response=canonical_bytes(plan),
                        provenance={"kind": "authored-test"},
                    )
                    prepared = planning.prepare(credential, ref, request)
                    self.assertEqual(prepared["status"], "intent-recorded")
                    callback.assert_not_called()
                    run = dict(
                        request,
                        request_sha256=prepared["request_sha256"],
                        confirmed=True,
                    )
                    saved = planning.run(credential, ref, run)
                    self.assertEqual(saved["outcome"], "saved", saved)
                    self.assertEqual(saved["project_ref"], ref)
                    self.assertEqual(
                        saved["request_sha256"], prepared["request_sha256"]
                    )
                    readback = http.view(credential, ref)
                    self.assertEqual(readback["project_ref"], ref)
                    self.assertEqual(
                        readback["input_version"], identity["input_version"]
                    )
                    self.assertEqual(readback["job"], saved)
                    self.assertEqual(readback["plan"], plan)
                    self.assertEqual(readback["plan"]["source_manifest_sha256"], pin)
                    self.assertTrue(saved["plan_manifest_sha256"])
                    before = journal.snapshot(project_id)
                    self.assertEqual(len(before["intents"]), 1)
                    self.assertEqual(planning.run(credential, ref, run), saved)
                    self.assertEqual(journal.snapshot(project_id), before)
                    self.assertEqual(callback.call_count, 1)
                    for flag in POLICY:
                        self.assertIs(saved[flag], False)
                finally:
                    http.close()
            fixture["case"].runner.assert_not_called()
