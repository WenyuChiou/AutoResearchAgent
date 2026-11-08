"""Authored material-to-planner and independent-review integration; zero models."""

# ruff: noqa: E402
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]
from stage3_plan.contracts import Stage3Error, canonical_bytes
from stage3_plan.context_projection import expand_context
from stage3_plan.direction_materials import (
    prepare_registered_materials,
    inspect_registered_materials,
)
from stage3_plan.storage import decode_json
from test_stage3_direction_research import _DirectionResearchFixture
from test_stage3_study_jobs import _StudySetup
import test_stage3_direction_research_jobs as fixture


class RegisteredMaterialJobsTests(_DirectionResearchFixture, _StudySetup):
    prepare_job = fixture.Stage3DirectionResearchJobsTests.prepare_job
    run_job = fixture.Stage3DirectionResearchJobsTests.run_job
    saved_root = fixture.Stage3DirectionResearchJobsTests.saved_root

    def configure_materials(self, context, root):
        self.material_raw = canonical_bytes(
            {
                "unit": "authored units",
                "availability": "unknown",
                "source_limit": "Unverified survey weights.",
                "observations": [2, 5],
            }
        )
        self.material_id = "file-" + "1" * 32
        self.material_sha = hashlib.sha256(self.material_raw).hexdigest()
        entry = dict(
            id=self.material_id,
            kind="manual-file",
            project_ref=context["project_ref"],
            stage=3,
            name="authored-original.json",
            bytes=len(self.material_raw),
            sha256=self.material_sha,
            status="registered",
            content_status="unreviewed-material-not-screened-or-read",
            registered_at="2026-01-01T00:00:00Z",
            execution_authorized=False,
        )
        selection = dict(
            file_id=self.material_id,
            sha256=self.material_sha,
            bytes=len(self.material_raw),
            pointers=["/unit", "/availability", "/source_limit", "/observations"],
            question_refs=[context["questions"][0]["question_ref"]],
            purpose="Inspect existing values for a proposed comparison.",
            limits="These observed development data are not new holdout evidence.",
        )
        self.material_reads = []

        def read_file(identity):
            self.material_reads.append(identity)
            return self.material_raw

        binding = prepare_registered_materials(
            context,
            [selection],
            root / "registered-materials",
            catalog=lambda ref: [entry],
            read_file=read_file,
        )
        self.study_adapter.materials = binding
        self.expected_materials = inspect_registered_materials(binding, context)

    def prepare_material_job(self):
        self.setup_study(self.context, self.root)
        self.configure_materials(self.context, self.root)
        return self.prepare_job(self.study_adapter)

    @staticmethod
    def prompt_context(prompt, marker):
        value = decode_json(prompt.split(marker, 1)[1])
        return (
            expand_context(value)
            if value.get("kind") == "Stage3SharedPlanningContext"
            else value
        )

    def test_actual_planner_and_independent_review_share_exact_material_values(self):
        prepared = self.prepare_material_job()
        saved = self.run_job(prepared, self.study_adapter)
        self.assertEqual(saved["result"]["outcome"], "saved")
        planner = self.prompt_context(
            self.study_calls[0]["prompt"], "UNTRUSTED_STAGE2_CONTEXT\n"
        )
        review = self.prompt_context(
            self.study_reviews[0]["prompt"], "UNTRUSTED_RESEARCH_DESIGN\n"
        )
        self.assertEqual(planner["registered_materials"], self.expected_materials)
        self.assertEqual(review["registered_materials"], self.expected_materials)
        self.assertFalse(planner["registered_materials"]["rights_verified"])
        self.assertFalse(review["registered_materials"]["scientific_quality_verified"])
        self.assertEqual(self.run_job(prepared, self.study_adapter), saved)
        self.assertEqual(
            (len(self.study_calls), len(self.study_reviews), len(self.material_reads)),
            (1, 1, 1),
        )

    def test_changed_saved_material_rejects_before_any_model_callback(self):
        prepared = self.prepare_material_job()
        path = self.root / "registered-materials" / (self.material_id + ".json")
        path.write_bytes(b'{"observations":[99]}')
        with self.assertRaises(Stage3Error):
            self.run_job(prepared, self.study_adapter)
        self.assertEqual((self.study_calls, self.study_reviews), ([], []))

    def test_another_material_binding_cannot_reuse_a_prepared_request(self):
        prepared = self.prepare_material_job()
        changed = deepcopy(self.study_adapter.request_context)
        changed["direction_research"]["materials"]["sha256"] = "a" * 64
        self.study_adapter.materials = changed["direction_research"]["materials"]
        with self.assertRaises(Stage3Error):
            self.run_job(prepared, self.study_adapter)
        self.assertEqual((self.study_calls, self.study_reviews), ([], []))


class ProjectRegisteredMaterialTests(unittest.TestCase, _StudySetup):
    @classmethod
    def setUpClass(cls):
        from stage3_direction_fixtures import DirectionFixture

        cls.direction = DirectionFixture(cls.addClassCleanup)

    def setUp(self):
        import test_stage3_study_jobs as studies

        studies.ProjectStudyForwardingTests.setUp(self)
        self.context = self.direction.admit(self.source)
        self.root = self.fixture.fixture.root / self._testMethodName
        RegisteredMaterialJobsTests.configure_materials(self, self.context, self.root)
        self.service.bindings[self.project["project_ref"]]["adapter_context"] = (
            deepcopy(self.study_adapter.request_context)
        )

    def test_original_host_forwards_materials_to_both_configured_callbacks(self):
        ref = self.project["project_ref"]
        prepared = self.service.prepare("own", ref, self.body)
        body = dict(
            self.body, request_sha256=prepared["request_sha256"], confirmed=True
        )
        saved = self.service.run("own", ref, body)
        self.assertEqual(saved["outcome"], "saved")
        for request, marker in (
            (self.study_calls[0], "UNTRUSTED_STAGE2_CONTEXT\n"),
            (self.study_reviews[0], "UNTRUSTED_RESEARCH_DESIGN\n"),
        ):
            context = RegisteredMaterialJobsTests.prompt_context(
                request["prompt"], marker
            )
            self.assertEqual(context["registered_materials"], self.expected_materials)
        self.assertEqual(self.service.run("own", ref, body), saved)
        self.assertEqual(
            (len(self.study_calls), len(self.study_reviews), len(self.material_reads)),
            (1, 1, 1),
        )
        self.assertFalse(saved["execution_authorized"])


if __name__ == "__main__":
    unittest.main()
