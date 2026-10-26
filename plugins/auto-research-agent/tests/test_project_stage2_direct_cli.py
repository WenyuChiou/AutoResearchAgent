"""Synthetic direct Stage2 delivery admission; no model/research/user authority."""

# ruff: noqa: E402 -- reuse repository deterministic fixtures.
import hashlib
import json
from pathlib import Path
import sys
import unittest
import threading
import http.server
import urllib.request
from copy import deepcopy
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "cli")]

from research_workspace_native.session_api import SessionApiError
from research_workspace_native.project_stage2_selection import (
    ProjectStage2SelectionService,
)
from stage2_workflow import initialize_workflow, inspect_workflow
from stage2_workflow.orchestration import prepare_review_batch
from stage2_workflow.delivery import build_delivery
from stage2_common import canonical_hash, source_set_hash, validate_packet
from stage2_workflow.reviews import prepare_review
import test_stage2_scientific_argument as argument_fixture
import test_stage2_checker as checker_fixture
from research_workspace_native import project_host


import test_project_stage2_direct_import as direct_fixture


class DirectDeliveryCliTests(unittest.TestCase):
    def setUp(self):
        fixture = direct_fixture.DirectDeliveryAdmissionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        for name in (
            "root",
            "request_hash",
            "delivery_root",
            "manifest",
            "intake",
            "service",
        ):
            setattr(self, name, getattr(fixture, name))

    def import_package(self, **changes):
        return direct_fixture.DirectDeliveryAdmissionTests.import_package(
            self, **changes
        )

    def eligible_delivery(self):
        source = argument_fixture.Stage2ScientificArgumentTests(
            "test_packet_2_5_is_opt_in_and_requires_a_core_closed_argument"
        )
        source.setUp()
        self.addCleanup(source.doCleanups)
        packet = deepcopy(source.packet)
        direct = json.loads((self.root / "seed" / "packet.json").read_bytes())
        packet["schema_version"] = "2.6.0"
        packet.pop("upstream")
        for field in ("entry", "brief", "resources"):
            packet[field] = direct[field]
        for field in ("sources", "evidence", "literature", "supplemental_literature"):
            for row in packet[field]:
                row["origin"] = "stage2"
        for row in packet["prior_work_reviews"]:
            row["source_set_sha256"] = source_set_hash(packet)
        validate_packet(packet, source.fixture.source_root)
        path = self.root / "eligible-packet.json"
        path.write_text(json.dumps(packet), encoding="utf-8")
        workflow = self.root / "eligible-workflow"
        initialize_workflow(
            path,
            source.fixture.source_root,
            workflow,
            {},
            {},
            expected_packet_sha256=canonical_hash(packet),
        )
        current = inspect_workflow(workflow)
        snapshot = current["latest_snapshot"]["event"]["payload"]["snapshot_sha256"]
        candidate = packet["candidates"][0]
        cid, version = candidate["candidate_id"], candidate["version"]
        evidence = packet["evidence"][0]["evidence_id"]
        batch = prepare_review_batch(
            packet,
            snapshot,
            [
                dict(
                    candidate_id=cid,
                    candidate_version=version,
                    included=True,
                    distance=0,
                    reason="Synthetic engineering case only",
                )
            ],
            "synthetic-direct-choice",
            review_view_version="1.3.0",
        )
        assessment = checker_fixture.assessment(packet)
        assessment.update(candidate_id=cid, candidate_version=version)
        for check in assessment["checks"].values():
            check["evidence_ids"] = [evidence]
        reviews = []
        for role in ("challenger", "feasibility"):
            view = prepare_review(
                packet, cid, snapshot, role, review_view_version="1.3.0"
            )
            review = dict(
                role=role,
                view_sha256=canonical_hash(view),
                snapshot_sha256=snapshot,
                candidate_id=cid,
                candidate_version=version,
                assessment=deepcopy(assessment),
                session_id="synthetic-" + role,
                native_artifact=dict(
                    path="synthetic/" + role + ".jsonl", sha256=canonical_hash([role])
                ),
                initial=True,
                assumptions=["Synthetic fixture only"],
                strongest_alternative="The bounded measurement may differ",
                change_conditions=["New evidence changes the judgment"],
            )
            reviews.append(
                dict(
                    candidate_id=cid,
                    candidate_version=version,
                    role=role,
                    status="complete",
                    review=review,
                    error=None,
                )
            )
        resolution = dict(
            review_sha256s=[canonical_hash(row["review"]) for row in reviews],
            method="synthesis",
            reason="Both supplied synthetic role records agree",
            evidence_ids=[evidence],
            addressed=[],
            assessment=assessment,
            substantive_disagreements=[],
            changed_judgment_reason=None,
        )
        self.delivery_root = self.root / "eligible-delivery"
        self.manifest = build_delivery(
            workflow,
            batch,
            reviews,
            dict(
                candidate_resolutions=[dict(candidate_id=cid, resolution=resolution)],
                next_step=None,
            ),
            self.delivery_root,
            current["head_sha256"],
            record_registered_history=True,
        )

    def test_actual_synthetic_ui_choice_advances_direct_frontier_once(self):
        self.eligible_delivery()
        registered = self.import_package()
        ref = registered["project_ref"]
        ui = ProjectStage2SelectionService(
            self.intake, {ref: registered["selection_binding"]}
        )
        view = ui.read("synthetic-owner", ref)
        self.assertEqual(len(view["eligible"]), 1)
        body = {
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
        body.update(
            key="synthetic-direct-select",
            confirmed=True,
            decision=dict(
                actor="synthetic-ui-user",
                kind="select",
                user_text="Synthetic choice of the displayed version for planning only.",
                selected=view["eligible"],
                conditions=["Retain source limitations"],
                unresolved=["Material access remains unknown"],
                rationale="Offline engineering fixture",
                scope_or_resource_change=False,
            ),
        )
        saved = ui.select("synthetic-owner", ref, body)
        replay = ui.select("synthetic-owner", ref, body)
        self.assertEqual(saved["request_sha256"], replay["request_sha256"])
        reopened = ui.read("synthetic-owner", ref)
        self.assertEqual(reopened["selection_status"], "recorded")
        self.assertEqual(reopened["planning_status"], "verified")
        self.assertFalse(reopened["planning_input"]["execution_authorized"])
        self.assertEqual(
            self.service.read("synthetic-owner", ref)["frontier"]["sequence"], 1
        )

    def config(self):
        value = dict(
            kind="ProjectStage2DirectImportConfiguration",
            schema_version="1.0.0",
            entries=[
                dict(
                    delivery_dir=str(self.delivery_root),
                    expected_manifest_sha256=self.manifest["manifest_sha256"],
                    expected_request_sha256=self.request_hash,
                    project_id="synthetic-cli-direct",
                    input_version=1,
                )
            ],
        )
        path = self.root / "direct-config.json"
        raw = json.dumps(value).encode()
        path.write_bytes(raw)
        return path, hashlib.sha256(raw).hexdigest()

    def test_official_cli_loads_direct_selection_before_listener_and_cleans_up(self):
        path, digest = self.config()
        observed = []

        def serve(host):
            thread = threading.Thread(
                target=http.server.ThreadingHTTPServer.serve_forever,
                args=(host,),
                daemon=True,
            )
            thread.start()
            try:
                refs = host.projects.list(host.credential)
                ref = refs[0]["project_ref"]
                request = urllib.request.Request(
                    host.expected_origin + "/api/projects/" + ref + "/stage2/selection",
                    headers={
                        "Authorization": "Bearer " + host.credential,
                        "Origin": host.expected_origin,
                    },
                )
                with urllib.request.urlopen(request, timeout=20) as response:
                    view = json.load(response)
                host.overview(host.credential, ref)
                for suffix in ("overview", "contract"):
                    check = urllib.request.Request(
                        host.expected_origin + "/api/projects/" + ref + "/" + suffix,
                        headers={
                            "Authorization": "Bearer " + host.credential,
                            "Origin": host.expected_origin,
                        },
                    )
                    with urllib.request.urlopen(check, timeout=20) as response:
                        projection = json.load(response)
                    self.assertIsInstance(projection, dict)
                    if suffix == "overview":
                        self.assertEqual(
                            projection["project"]["stage1_status"],
                            "not-applicable-direct-request",
                        )
                observed.append(view["project_ref"])
                self.assertEqual(view["eligible"], [])
                self.assertFalse(view["execution_authorized"])
            finally:
                host.shutdown()
                thread.join(5)
                self.assertFalse(thread.is_alive())

        with patch.object(project_host.ProjectHost, "serve_forever", new=serve):
            project_host.main(
                [
                    "--projects-root",
                    str(self.root / "cli-catalog"),
                    "--stage2-direct-import-config",
                    str(path),
                    "--stage2-direct-import-sha256",
                    digest,
                ]
            )
        self.assertEqual(len(observed), 1)

    def test_bad_cli_configuration_never_allocates_a_listener(self):
        path, _ = self.config()
        with patch.object(project_host, "ProjectHost") as allocate:
            with self.assertRaises(SessionApiError):
                project_host.main(
                    [
                        "--projects-root",
                        str(self.root / "invalid-cli"),
                        "--stage2-direct-import-config",
                        str(path),
                        "--stage2-direct-import-sha256",
                        "0" * 64,
                    ]
                )
            allocate.assert_not_called()

    def test_duplicate_configuration_projects_are_rejected_before_import(self):
        from research_workspace_native.project_stage2_direct_config import (
            load_direct_request_imports,
        )

        path, _ = self.config()
        config = json.loads(path.read_bytes())
        config["entries"].append(dict(config["entries"][0]))
        raw = json.dumps(config).encode()
        path.write_bytes(raw)
        with self.assertRaisesRegex(
            SessionApiError, "direct-import-config-duplicate-project"
        ):
            load_direct_request_imports(
                self.service, "synthetic-owner", path, hashlib.sha256(raw).hexdigest()
            )
        self.assertEqual(self.intake.list("synthetic-owner"), [])

    def test_valid_configuration_replays_one_import(self):
        from research_workspace_native.project_stage2_direct_config import (
            load_direct_request_imports,
        )

        path, digest = self.config()
        first = load_direct_request_imports(
            self.service, "synthetic-owner", path, digest
        )
        self.assertEqual(
            first,
            load_direct_request_imports(self.service, "synthetic-owner", path, digest),
        )
        self.assertEqual(len(self.intake.list("synthetic-owner")), 1)

    def test_direct_overview_does_not_enter_inapplicable_stage1_services(self):
        imported = self.import_package()
        host = object.__new__(project_host.ProjectHost)
        host.projects = self.intake
        host.project_models = None
        host.project_stage1 = object()
        host.project_stage2 = self.service
        with patch.object(
            host,
            "stage1_view",
            side_effect=AssertionError(
                "Direct Stage2 overview must not enter Stage1 services"
            ),
        ) as blocked:
            overview = host.overview("synthetic-owner", imported["project_ref"])
        blocked.assert_not_called()
        self.assertIsNone(overview["stage1"])
        self.assertFalse(overview["project"]["stage1_lineage"])
        self.assertFalse(overview["stage2"]["execution_authorized"])


if __name__ == "__main__":
    unittest.main()
