"""Saved canonical indexes receive verified Stage2 views without stage authority."""

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

import test_stage1_screening_records as canonical_fixture
import test_stage2_daily_v3 as evaluated_fixture
from research_workspace.canonical_delivery import project_canonical_delivery
from research_workspace.stage2_import import prepare_stage2_bridge
from research_workspace.view import write_workspace
from research_workspace_native.atlas_host import load_views
from research_workspace_native.http import token_authenticator
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage1 import ProjectStage1Service
from research_workspace_native.project_stage2 import ProjectStage2Service
from stage1_deliverable.common import DeliverableError, canonical, inventory, sha
from stage1_deliverable.package import build


class CanonicalStage2ViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved = canonical_fixture.ScreeningRecordsTests
        cls.saved.setUpClass()
        cls.addClassCleanup(cls.saved.doClassCleanups)

    def setUp(self):
        self.evaluated = evaluated_fixture.DailyV3Tests()
        self.evaluated.setUp()
        self.addCleanup(self.evaluated.doCleanups)
        self.delivery_receipt = self.evaluated.delivery(self.evaluated.run_judges())
        self.delivery = self.evaluated.root / "delivery"
        self.reference = (
            Path(__file__).resolve().parents[1] / "references/research-workspace"
        )

    def index(self, version):
        records = (
            self.saved.original_path if version == "1.1.0" else self.saved.records_path
        )
        output = self.evaluated.root / ("canonical-" + version)
        manifest = build(records, output, sha(records.read_bytes()))
        index = project_canonical_delivery(
            output, "source-bound-project", manifest["manifest_sha256"]
        )
        self.assertEqual(index["schema_version"], version)
        return index, output

    def attach(self, index, destination, **overrides):
        bridge = prepare_stage2_bridge(
            index,
            self.delivery,
            expected_manifest_sha256=self.delivery_receipt["manifest_sha256"],
        )
        options = dict(
            stage2_delivery=self.delivery,
            stage2_bridge=bridge,
            expected_stage2_bridge_sha256=sha(canonical(bridge)),
            atlas=True,
        )
        options.update(overrides)
        return write_workspace(index, self.reference, destination, **options)

    def test_current_canonical_versions_keep_history_and_verified_stage2_bytes(self):
        for version in ("1.1.0", "1.2.0"):
            with self.subTest(version=version):
                index, saved_package = self.index(version)
                original = deepcopy(index)
                package_before = inventory(saved_package)
                delivery_before = inventory(self.delivery)
                destination = self.evaluated.root / ("view-" + version)
                receipt = self.attach(index, destination)
                self.assertEqual(index, original)
                self.assertEqual(inventory(saved_package), package_before)
                self.assertEqual(inventory(self.delivery), delivery_before)
                self.assertEqual(
                    (destination / "workspace-index.json").read_bytes(),
                    canonical(original),
                )
                attachment = json.loads(
                    (destination / "stage2/workspace-attachment.json").read_bytes()
                )
                self.assertEqual(attachment["project_id"], original["project_id"])
                self.assertEqual(
                    attachment["stage1_index_sha256"], sha(canonical(index))
                )
                self.assertEqual(len(attachment["evaluation"]["rows"]), 9)
                self.assertIn("R1 source-bound comment", str(attachment["evaluation"]))
                for flag in (
                    "original_stage1_lineage_attested",
                    "stage3_authorized",
                    "formal_ready",
                    "improvement_demonstrated",
                ):
                    self.assertIs(attachment["bridge_receipt"][flag], False)
                self.assertEqual(
                    attachment["bridge_receipt"]["human_selection"], "pending"
                )
                self.assertFalse(receipt["stage2_attachment"]["stage3_authorized"])
                self.assertEqual(
                    original["stage2_canonical_consumer"]["status"], "unconnected"
                )
                self.assertTrue(
                    all(not stage["execution_enabled"] for stage in index["stages"])
                )
                if version == "1.2.0":
                    self.assertEqual(
                        index["screening_library"], original["screening_library"]
                    )
                    unread = [
                        p
                        for p in index["papers"]
                        if p["reading_status"] == "discovery-only"
                    ]
                    self.assertTrue(unread)
                    self.assertTrue(
                        all(p["findings"]["main_findings"] == "Unknown" for p in unread)
                    )
                for name, digest in receipt["files"].items():
                    self.assertEqual(sha((destination / name).read_bytes()), digest)
                for item in self.delivery_receipt["artifacts"]:
                    self.assertEqual(
                        (destination / "stage2" / item["path"]).read_bytes(),
                        (self.delivery / item["path"]).read_bytes(),
                    )
                self.saved.case.runner.assert_not_called()

    def test_current_canonical_receipts_reject_mismatches_before_output(self):
        for version in ("1.1.0", "1.2.0"):
            with self.subTest(version=version):
                index, _ = self.index(version)
                bridge = prepare_stage2_bridge(
                    index,
                    self.delivery,
                    expected_manifest_sha256=self.delivery_receipt["manifest_sha256"],
                )
                wrong_project = dict(bridge, project_id="another-project")
                cases = (
                    ("wrong-external-hash", bridge, "0" * 64),
                    (
                        "rehashed-wrong-project",
                        wrong_project,
                        sha(canonical(wrong_project)),
                    ),
                )
                for label, supplied, digest in cases:
                    destination = self.evaluated.root / (label + version)
                    with self.subTest(case=label), self.assertRaises(DeliverableError):
                        self.attach(
                            index,
                            destination,
                            stage2_bridge=supplied,
                            expected_stage2_bridge_sha256=digest,
                        )
                    self.assertFalse(destination.exists())
                destination = self.evaluated.root / ("partial-" + version)
                with patch("research_workspace.view.safe_path") as asset_read:
                    with self.assertRaisesRegex(
                        DeliverableError, "receipt hash are required"
                    ):
                        write_workspace(
                            index,
                            self.reference,
                            destination,
                            stage2_delivery=self.delivery,
                        )
                asset_read.assert_not_called()
                self.assertFalse(destination.exists())

    @unittest.skipUnless(
        os.environ.get("ATLAS_RENDERED_CHECK") == "1",
        "set ATLAS_RENDERED_CHECK=1 for installed-browser ProjectHost acceptance",
    )
    def test_project_portal_and_current_stage2_reading_view_are_operable(self):
        node = os.environ.get("ATLAS_NODE_EXECUTABLE") or shutil.which("node")
        self.assertIsNotNone(node, "explicit rendered check requires Node.js")
        index, _ = self.index("1.2.0")
        destination = self.evaluated.root / "served-current-stage2"
        self.attach(index, destination)
        manifest_path = destination / "view-manifest.json"
        config = self.evaluated.root / "views.json"
        config.write_text(
            json.dumps(
                {
                    "views": [
                        {
                            "ref": "current-stage2",
                            "label": "Synthetic current Stage2",
                            "manifest": str(manifest_path),
                            "sha256": sha(manifest_path.read_bytes()),
                            "fixture": True,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        files, views = load_views(config, sha(config.read_bytes()))
        credential = "synthetic-project-browser-token-with-32-characters"
        projects = ProjectIntakeService(
            self.evaluated.root / "projects",
            authenticate=token_authenticator({credential: "local-viewer"}),
        )
        host = None
        worker = None
        try:
            host = ProjectHost(
                projects=projects,
                credential=credential,
                stage1=ProjectStage1Service(projects),
                stage2=ProjectStage2Service(projects),
                files=files,
                views=views,
                port=0,
            )
            worker = threading.Thread(target=host.serve_forever, daemon=True)
            worker.start()
            environment = os.environ.copy()
            environment.update(
                CANONICAL_STAGE2_URL=host.expected_origin + "/",
                CANONICAL_STAGE2_INDEX_SHA256=sha(canonical(index)),
                CANONICAL_STAGE2_SELECTION_SHA256=sha(
                    (destination / "stage2/core_selection.json").read_bytes()
                ),
            )
            driver = Path(__file__).with_name(
                "test_workspace_canonical_stage2_browser.cjs"
            )
            result = subprocess.run(
                [str(node), str(driver)],
                cwd=Path(__file__).parents[1],
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
            print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(len(report["results"]), 6)
            self.assertEqual(report["post_requests"], 0)
            self.assertEqual(projects.list(credential), [])
        finally:
            if host is not None:
                host.shutdown()
                host.server_close()
            if worker is not None:
                worker.join(3)
                self.assertFalse(worker.is_alive())
            projects.close()
        self.saved.case.runner.assert_not_called()
