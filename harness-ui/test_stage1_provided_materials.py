"""Ordinary uploaded bytes enter Core as provided, never as a query result."""

# ruff: noqa: E402 -- the plugin tests are repository-local imports.
import base64
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugins/auto-research-agent/tests"))
import test_project_stage1
from test_stage1_ledger import SYNTHETIC
from test_material_project_access import MaterialsHttpHarness
from stage1_deliverable.common import sha


class ProvidedMaterialHttpTests(unittest.TestCase):
    def setUp(self):
        self.case = test_project_stage1.ProjectStage1Tests()
        self.case.setUp()
        self.ref = self.case.new(topic="Isolated offline uploaded-source test")
        self.case.initialize(self.ref)
        self.web = MaterialsHttpHarness(self.case.root / "materials")
        self.web.host.authenticate = self.case.intake.authenticate
        self.web.host.projects = self.case.intake
        self.web.host.project_stage1 = self.case.service
        # The ordinary material access guard delegates to this original service.
        from materials_http import install_materials

        self.web.store = install_materials(
            self.web.host,
            self.case.intake,
            self.case.root / "materials",
            self.case.root / "incoming",
        )
        self.data = (
            b"Offline authored source: two concurrent notes; engineering only.\n"
        )
        self.item = self.post(
            "upload/start",
            dict(
                project_ref=self.ref,
                stage=1,
                name="authored.txt",
                bytes=len(self.data),
                sha256=sha(self.data),
            ),
        )
        self.post(
            "upload/chunk",
            dict(
                id=self.item["id"],
                offset=0,
                base64=base64.b64encode(self.data).decode(),
            ),
        )
        self.post("upload/finish", dict(id=self.item["id"]))

    def tearDown(self):
        self.web.close()
        self.case.tearDown()

    def post(self, route, body):
        return self.web.post(route, body, credential="alice-token")

    def body(self):
        return dict(
            self.case.action_body(self.ref, "provided-wiki"),
            project_ref=self.ref,
            material_id=self.item["id"],
            material_sha256=sha(self.data),
            record=deepcopy(SYNTHETIC),
            source_uri="https://example.org/authored-test",
            original_type="text/plain",
            reason="Existing authored engineering material; not research.",
            consequence_acknowledged=True,
        )

    def state(self):
        return (
            self.case.intake._load("alice", self.ref),
            self.case.private_ledger(self.ref).events(),
        )

    def test_upload_admit_same_key_and_reopen_preserve_unreviewed_core(self):
        body = self.body()
        receipt = self.post("stage1/admit-material", body)
        self.assertEqual(receipt["status"], "saved")
        state = self.state()
        self.assertTrue(self.post("stage1/admit-material", body)["replayed"])
        self.assertEqual(self.state(), state)
        from research_workspace_native.project_intake import ProjectIntakeService
        from research_workspace_native.project_stage1 import ProjectStage1Service

        auth = self.case.intake.authenticate
        self.case.intake.close()
        self.case.intake = ProjectIntakeService(self.case.root, authenticate=auth)
        self.case.service = ProjectStage1Service(self.case.intake)
        self.web.host.project_stage1 = self.case.service
        self.assertTrue(self.post("stage1/admit-material", body)["replayed"])
        self.assertEqual(self.state(), state)
        view = self.case.service.read("alice-token", self.ref)
        self.assertEqual(view["ledger"]["counts"]["works"], 1)
        for key in ("queries", "backend_attempts", "decisions", "claims"):
            self.assertEqual(view["ledger"]["counts"][key], 0)
        self.assertFalse(view["stage1_complete"])
        self.assertIsNone(view["canonical_package"])

    def test_rejections_do_not_append(self):
        original = self.body()
        variants = [
            dict(confirmed=False),
            dict(consequence_acknowledged=False),
            dict(input_version="1"),
            dict(input_version=2),
            dict(material_sha256="0" * 64),
            dict(project_ref="project-missing"),
            dict(source_relative="../escape"),
            dict(record={}),
            dict(principal="invented"),
            dict(material_id=[]),
            dict(record=dict(SYNTHETIC, doi=123)),
        ]
        for changes in variants:
            with self.subTest(changes=changes):
                before = self.state()
                status, _ = self.web.request(
                    "stage1/admit-material",
                    dict(original, **changes),
                    credential="alice-token",
                )
                self.assertNotEqual(status, 200)
                self.assertEqual(self.state(), before)

    def test_tampered_material_and_foreign_owner_reject_before_core(self):
        before = self.state()
        status, _ = self.web.request(
            "stage1/admit-material", self.body(), credential="bob-token"
        )
        self.assertNotEqual(status, 200)
        (self.web.store.root / "files" / (self.item["id"] + ".bin")).write_bytes(
            b"tampered"
        )
        status, _ = self.web.request(
            "stage1/admit-material", self.body(), credential="alice-token"
        )
        self.assertNotEqual(status, 200)
        self.assertEqual(self.state(), before)

    def test_unconnected_core_stays_closed(self):
        self.web.host.project_stage1 = None
        before = self.state()
        status, raw = self.web.request(
            "stage1/admit-material", self.body(), credential="alice-token"
        )
        self.assertEqual(status, 409)
        self.assertEqual(
            json.loads(raw)["error"], "stage1-provided-admission-unconnected"
        )
        self.assertEqual(self.state(), before)

    def test_other_owned_project_cannot_borrow_material(self):
        original = self.body()
        other = self.case.new(topic="Other isolated negative control", key="other")
        self.case.initialize(other)
        body = dict(
            original, **self.case.action_body(other, "wrong-project"), project_ref=other
        )
        before = self.state()
        status, raw = self.web.request(
            "stage1/admit-material", body, credential="alice-token"
        )
        self.assertEqual(status, 409)
        self.assertEqual(
            json.loads(raw)["error"], "provided-material-project-or-stage-differs"
        )
        self.assertEqual(self.state(), before)

    def test_missing_confirmation_stale_ledger_and_unknown_fields_do_not_reserve(self):
        original = self.body()
        for changes in (
            {"confirmed": False},
            {"ledger_state_sha256": "0" * 64},
            {"revision": 0},
            {"input_version": True},
        ):
            with self.subTest(changes=changes):
                before = self.state()
                status, raw = self.web.request(
                    "stage1/admit-material",
                    dict(original, **changes),
                    credential="alice-token",
                )
                self.assertNotEqual(status, 200, json.loads(raw))
                self.assertEqual(self.state(), before)


if __name__ == "__main__":
    unittest.main()
