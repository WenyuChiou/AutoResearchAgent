"""Actual imported controller/choice services with an explicit synthetic adapter.

The controlled recommendation tests composition only. It is unrelated to real
B's zero recommendations and establishes no scientific or native admission proof.
"""

# ruff: noqa: E402 -- repository packages and bounded authored source fixtures.
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "cli"), str(HERE)]

import test_project_stage1_identity_import as imported_fixture
import test_project_stage2_controller as driver_fixture
import test_project_stage2_selection_http as http_fixture
import test_stage2_controller as controller_fixture
from test_stage2_scientific_argument import argument
from stage2_fixture_helpers import _candidate
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage2 import ProjectStage2Service
from research_workspace_native.project_stage2_controller import (
    ProjectStage2ControllerDriver,
)
from research_workspace_native.project_stage2_selection import (
    ProjectStage2SelectionService,
)
from stage1_deliverable.common import sha
from stage2_common import canonical_hash, source_set_hash
from stage2_live.controller import verify_controller
from stage2_workflow import add_snapshot, inspect_workflow
from stage3_plan.intake import admit_intake


class RichSyntheticAdapter(controller_fixture.SyntheticAdapter):
    identity = "explicit-synthetic-rich-controller-choice-v1"

    def extract(self, context):
        result = super().extract(context)
        packet = result["next_packet"]["packet"]
        if packet["schema_version"] != "2.5.0":
            raise AssertionError("The real imported workflow must start at packet2.5")
        evidence = packet["evidence"][0]["evidence_id"]
        source = packet["sources"][0]
        candidate = _candidate("candidate-1", evidence_ids=[evidence])
        candidate["scientific_argument"] = argument(
            evidence,
            {key: source[key] for key in ("source_id", "work_id", "version_id")},
        )
        packet["candidates"].append(candidate)
        return result

    def review(self, context):
        result = super().review(context)
        for finding in result["review"]["assessment"]["checks"].values():
            finding["evidence_ids"] = [context["packet"]["evidence"][0]["evidence_id"]]
        return result

    def resolve(self, context):
        result = super().resolve(context)
        result["resolution"]["evidence_ids"] = [
            context["packet"]["evidence"][0]["evidence_id"]
        ]
        return result


class SyntheticPreparation(driver_fixture.Handler):
    identity = "explicit-synthetic-rich-prerequisites-v1"

    def __init__(self, case):
        super().__init__(case.spec)
        self.case = case
        self.gates = []

    def prepare(self, request):
        case = self.case
        gate = request["gate"]["status"]
        self.gates.append(gate)
        spec, head = deepcopy(request["spec"]), request["expected_head"]
        if gate == "needs-prior-work":
            state = inspect_workflow(case.workflow)
            packet = deepcopy(state["latest_snapshot"]["packet"])
            candidate, work = packet["candidates"][0], packet["literature"][0]
            packet["prior_work_reviews"] = [
                dict(
                    kind="Stage2PriorWorkReview",
                    schema_version="1.0.0",
                    candidate_id=candidate["candidate_id"],
                    candidate_version=candidate["version"],
                    candidate_sha256=canonical_hash(candidate),
                    source_set_sha256=source_set_hash(packet),
                    positioning="A synthetic retained comparison; global novelty is unknown.",
                    review_status="partial",
                    stop_reason="This deterministic test has no search executor.",
                    search_limits=["No actual search is authorized."],
                    unresolved=["Actual search remains unavailable."],
                    searches=[
                        dict(
                            search_id="planned-only",
                            need="Inspect the closest precedent.",
                            query="synthetic planned query",
                            status="planned",
                            tool_ref=None,
                            raw_path=None,
                            raw_sha256=None,
                            outcome="unknown",
                            work_refs=[],
                        )
                    ],
                    comparisons=[
                        dict(
                            work_id=work["work_id"],
                            version_id=work["version_id"],
                            role="closest",
                            established="A retained synthetic baseline.",
                            overlap="A bounded synthetic comparison.",
                            difference="An untested synthetic method component.",
                            evidence_ids=[packet["evidence"][0]["evidence_id"]],
                            limitations=["No scientific novelty claim is established."],
                        )
                    ],
                )
            ]
            path = case.root / "synthetic-prepared-prior-work.json"
            path.write_text(json.dumps(packet), encoding="utf-8")
            head = add_snapshot(
                case.workflow,
                path,
                state["latest_snapshot"]["checker"]["root"] / "sources",
                "Retain a partial synthetic dossier and its planned-only search.",
                {
                    "candidate-1": dict(
                        status="affected", reason="Synthetic dossier supplied."
                    )
                },
                state["head_sha256"],
            )["event_sha256"]
        elif gate == "needs-workspace":
            for index, key in enumerate(request["gate"]["required_workspace_keys"]):
                spec["workspaces"][key] = dict(
                    home=str(case.root / f"prepared-home-{index}"),
                    workspace=str(case.root / f"prepared-workspace-{index}"),
                )
        else:
            raise AssertionError(f"Unexpected prerequisite gate: {gate}")
        receipt = case.root / f"synthetic-preparation-{len(self.gates)}.json"
        receipt.write_text(
            json.dumps(dict(synthetic_test_only=True, gate=gate)), encoding="utf-8"
        )
        return dict(
            status="complete",
            spec=spec,
            expected_head=head,
            continuation_snapshot_sha256=None,
            receipts=[dict(path=str(receipt), sha256=sha(receipt.read_bytes()))],
        )


class ImportedRichControllerChoiceE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        imported_fixture.ImportedStage1ProjectTests.setUpClass.__func__(cls)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rich-controller-choice-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.token = "synthetic-rich-controller-choice-" + "x" * 32
        self.intake = ProjectIntakeService(
            self.root,
            authenticate=lambda token: (
                "local-viewer" if token in ("own", self.token) else None
            ),
        )
        self.addCleanup(self.intake.close)
        self.service = ProjectStage2Service(self.intake)
        source = self.shared
        self.original_brief = source.brief.read_bytes()
        imported = self.service.import_stage1_project(
            "own",
            brief_path=source.brief,
            expected_brief_sha256=sha(self.original_brief),
            settings=dict(
                resource_envelope=source.resources.read_text(encoding="utf-8")
            ),
            deliverable_dir=source.f.package,
            expected_manifest_sha256=source.manifest["sha256"],
            handoff_path=source.handoff_path,
            expected_handoff_sha256=sha(source.handoff_path.read_bytes()),
            resources_path=source.resources,
            expected_resources_sha256=sha(source.resources.read_bytes()),
            policy_ref=dict(
                route="stage2-general-v3/daily_v3",
                execution_authorized=False,
                packet_profile="scientific-v3",
            ),
            saved_source_root=source.root,
            saved_source_acceptance_sha256=source.acceptance_ref["sha256"],
            **source.replay_args,
        )
        self.ref = imported["project_ref"]
        project = self.intake.read("own", self.ref)
        self.assertIs(type(project["input_version"]), str)
        activation = self.service.activate(
            "own",
            self.ref,
            dict(
                key="synthetic-rich-activation",
                revision=project["revision"],
                input_version=project["input_version"],
                brief_sha256=project["brief_sha256"],
                offer_ref=imported["offer"]["offer_ref"],
                offer_sha256=imported["offer"]["offer_sha256"],
                confirmed=True,
            ),
        )
        self.assertEqual(activation["status"], "saved")
        self.binding = self.service.binding(self.ref)
        self.workflow = Path(self.binding["workflow_root"])
        state = inspect_workflow(self.workflow)
        self.packet = state["latest_snapshot"]["packet"]
        self.assertEqual(self.packet["schema_version"], "2.5.0")
        self.assertEqual(self.packet["candidates"], [])
        self.base = state["latest_snapshot"]["event"]["payload"]["snapshot_sha256"]
        self.spec = controller_fixture.Stage2ControllerTests._spec(self)
        self.spec["workspaces"] = {
            key: value
            for key, value in self.spec["workspaces"].items()
            if key in {"research", "extractor"}
        }
        self.output, self.delivery = self.root / "controller", self.root / "delivery"
        self.handler = SyntheticPreparation(self)

    def request(self, path, body=None, *, token=None, origin=None):
        return http_fixture.ProjectSelectionTests.request(
            self, path, body, token=token, origin=origin, timeout=35
        )

    selection_body = http_fixture.ProjectSelectionTests.selection_body

    def test_rich_import_prepares_controller_and_records_one_http_choice_for_stage3(
        self,
    ):
        driver = ProjectStage2ControllerDriver(
            self.service,
            spec=self.spec,
            controller_dir=self.output,
            delivery_dir=self.delivery,
            prerequisite_handler=self.handler,
        )
        adapter = RichSyntheticAdapter()
        with patch("stage2_live.controller._ProductionAdapter", return_value=adapter):
            first = driver.run("own", self.ref, key="synthetic-controller-once")
            self.assertEqual(first["status"], "saved", first)
            self.assertEqual(
                self.handler.gates, ["needs-prior-work", "needs-workspace"]
            )
            self.assertEqual(first["controller"]["preparation"]["status"], "complete")
            self.assertEqual(first["controller"]["status"], "awaiting-human")
            self.assertTrue(first["controller"]["synthetic_test_only"])
            self.assertFalse(first["formal_ready"])
            self.assertFalse(first["execution_authorized"])
            self.assertEqual(adapter.calls.count("research"), 1)
            self.assertEqual(adapter.calls.count("extract"), 1)
            self.assertIn("review:challenger", adapter.calls)
            self.assertIn("review:feasibility", adapter.calls)
            self.assertEqual(adapter.calls.count("resolve"), 1)
            calls = list(adapter.calls)
            replay = driver.run("own", self.ref, key="synthetic-controller-once")
            self.assertTrue(replay["replayed"])
            self.assertEqual(replay["controller"], first["controller"])
            self.assertEqual(adapter.calls, calls)
            self.assertEqual(
                self.handler.gates, ["needs-prior-work", "needs-workspace"]
            )
        verified = verify_controller(
            self.output, first["controller"]["controller_manifest_sha256"]
        )
        self.assertTrue(verified["synthetic_test_only"])
        self.assertFalse(verified["authentic_native_execution"])
        self.assertFalse(verified["completion"]["research_delivery_ready"])
        self.assertEqual(
            self.service.binding(self.ref)["workflow_head_sha256"],
            first["controller"]["workflow_head_sha256"],
        )
        manifest = json.loads((self.delivery / "delivery_manifest.json").read_bytes())
        project = self.intake.read(self.token, self.ref)
        self.choice = ProjectStage2SelectionService(
            self.intake,
            {
                self.ref: dict(
                    input_version=project["input_version"],
                    brief_sha256=project["brief_sha256"],
                    workflow_root=str(self.workflow),
                    delivery_root=str(self.delivery),
                    delivery_manifest_sha256=manifest["manifest_sha256"],
                )
            },
        )
        self.host = ProjectHost(
            projects=self.intake,
            credential=self.token,
            stage2=self.service,
            stage2_selection=self.choice,
            files={},
            views=[],
            port=0,
        )
        thread = threading.Thread(target=self.host.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(
            lambda: (
                self.host.shutdown(),
                self.host.server_close(),
                thread.join(timeout=5),
            )
        )
        body = self.selection_body()
        self.assertIs(type(body["input_version"]), str)
        self.assertEqual(body["input_version"], project["input_version"])
        path = "/api/projects/" + self.ref + "/stage2/select"
        status, raw, _ = self.request(path, body)
        self.assertEqual(status, 200, raw)
        saved = json.loads(raw)
        self.assertEqual(saved["planning_status"], "verified")
        output = self.intake._path(self.ref, saved["artifact_ref"])
        submission = json.loads((output / "submission.json").read_bytes())
        self.assertEqual(submission["schema_version"], "1.1.0")
        self.assertEqual(submission["decision"], body["decision"])
        self.assertIs(type(submission["input_version"]), str)
        self.assertEqual(
            hashlib.sha256(
                (output / "interaction" / "interaction.json").read_bytes()
            ).hexdigest(),
            saved["interaction_file_sha256"],
        )
        before = {
            file.relative_to(output): file.read_bytes()
            for file in output.rglob("*")
            if file.is_file()
        }
        status, raw, _ = self.request(path, body)
        self.assertEqual(status, 200, raw)
        self.assertTrue(json.loads(raw)["replayed"])
        self.assertEqual(
            {
                file.relative_to(output): file.read_bytes()
                for file in output.rglob("*")
                if file.is_file()
            },
            before,
        )
        self.assertEqual(
            self.intake.db.execute(
                "SELECT COUNT(*) FROM intake_actions WHERE project=? AND key=?",
                (self.ref, body["key"]),
            ).fetchone()[0],
            1,
        )
        admitted = admit_intake(
            output / "planning",
            self.delivery,
            expected_manifest_sha256=saved["planning_manifest_sha256"],
        )
        self.assertEqual(len(admitted["questions"]), 1)
        self.assertEqual(admitted["legacy_candidates"], [])
        self.assertEqual(admitted["input_origin"]["kind"], "projecthost-ui-submission")
        self.assertEqual(
            admitted["selection_conditions"], body["decision"]["conditions"]
        )
        self.assertEqual(admitted["unresolved"], body["decision"]["unresolved"])
        self.assertIs(admitted["execution_authorized"], False)
        self.assertEqual(self.shared.brief.read_bytes(), self.original_brief)


if __name__ == "__main__":
    unittest.main()
